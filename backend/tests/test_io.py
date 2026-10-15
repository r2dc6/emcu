import copy
import multiprocessing
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.config import DEFAULTS, OUTPUTS
from backend.io import IO


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Device:
    def __init__(self, pin, **kwargs):
        self.pin = SimpleNamespace(state=False)
        self.number = pin
        self.kwargs = kwargs
        self.state = False
        self.closed = False
        self.fail = False
        self.off_calls = 0

    def on(self):
        if self.fail:
            raise OSError("write")
        self.state = True

    def off(self):
        self.off_calls += 1
        if self.fail:
            raise OSError("write")
        self.state = False

    def close(self):
        self.closed = True


def hardware_config():
    config = copy.deepcopy(DEFAULTS)
    config["simulation"] = False
    config["gpio"] = dict(zip(config["gpio"], range(4, 4 + len(config["gpio"]))))
    return config


def mapped_hardware_config():
    config = copy.deepcopy(DEFAULTS)
    config["simulation"] = False
    config["gpio"] = {
        "acu1": 17,
        "acu1_2": 11,
        "acu2": 27,
        "acu2_2": 10,
        "door": 22,
        "water": 24,
        "smoke": 23,
        "dht": 4,
        "alarm_water": 5,
        "alarm_smoke": 6,
        "alarm_temperature": 13,
        "alarm_humidity": 19,
        "alarm_door": 0,
    }
    return config


def mock_hardware_io(config, **kwargs):
    from gpiozero import DigitalInputDevice, DigitalOutputDevice
    from gpiozero.pins.mock import MockFactory
    factory = MockFactory()
    io = IO(config,
            lambda *args, **options: DigitalOutputDevice(
                *args, pin_factory=factory, **options),
            lambda *args, **options: DigitalInputDevice(
                *args, pin_factory=factory, **options),
            dht_reader=lambda: (None, None), **kwargs)
    return io, factory


def blocked_worker(event, entered):
    entered.set()
    event.wait(60)


class IOTests(unittest.TestCase):
    def make_io(self, config=None, **kwargs):
        io = IO(config or hardware_config(), Device, Device, **kwargs)
        self.addCleanup(io.close)
        return io

    def test_explicit_channel_pin_bindings(self):
        io = self.make_io(mapped_hardware_config())
        self.assertEqual({key: device.number for key, device in io.devices.items()},
                         {"acu1": 17, "acu2": 27, "water": 5, "smoke": 6,
                          "temperature": 13, "humidity": 19, "door": 0})
        self.assertEqual({key: device.number for key, device in io.secondary_devices.items()},
                         {"acu1": 11, "acu2": 10})
        self.assertEqual({key: device.number for key, device in io.inputs.items()},
                         {"door": 22, "water": 24, "smoke": 23})

    def test_default_digital_inputs_pull_up_without_claiming_dht_pin(self):
        config = copy.deepcopy(DEFAULTS)
        config["simulation"] = False
        io, factory = mock_hardware_io(config)
        self.addCleanup(io.close)
        self.assertEqual(config["input_pull"],
                         {"door": "up", "water": "up", "smoke": "up"})
        for device in io.inputs.values():
            self.assertEqual(device.pin.pull, "up")
            self.assertTrue(device.pin.state)
            self.assertNotEqual(device.pin.info.name, "GPIO4")
        self.assertEqual(config["gpio"]["dht"], 4)
        io.dht_reader = None
        context = Mock()
        context.Process.return_value.is_alive.return_value = False
        with patch("backend.io.multiprocessing.get_context", return_value=context):
            io.start(3)
        self.assertEqual(context.Process.call_args.kwargs["args"][0], 4)

    def test_smoke_low_level_does_not_disable_input_pull_up(self):
        config = copy.deepcopy(DEFAULTS)
        config["simulation"] = False
        io, factory = mock_hardware_io(config)
        self.addCleanup(io.close)
        smoke_pin = factory.pin(25)
        smoke_pin.drive_low()
        self.assertFalse(smoke_pin.state)
        for name, number in (("door", 24), ("water", 23), ("smoke", 25)):
            self.assertEqual(io.inputs[name].pin.info.name, f"GPIO{number}")
            self.assertEqual(io.inputs[name].pin.pull, "up")

    def test_default_acu_pairs_follow_commands_and_shutdown(self):
        config = copy.deepcopy(DEFAULTS)
        config["simulation"] = False
        io, factory = mock_hardware_io(config)
        self.addCleanup(io.close)
        for name, numbers in (("acu1", (16, 11)), ("acu2", (9, 10))):
            pins = [factory.pin(number) for number in numbers]
            self.assertTrue(all(not pin.state for pin in pins))
            for value in (True, False, True):
                io.write(name, value)
                self.assertTrue(all(bool(pin.state) == value for pin in pins))
                self.assertEqual(io.outputs[name], value)
        io.close()
        for number in (16, 11, 9, 10):
            self.assertFalse(factory.pin(number).state)
        self.assertTrue(all(device.closed for device in io.secondary_devices.values()))

    def test_acu_pair_failure_still_attempts_other_relay(self):
        for failed_secondary in (False, True):
            io = self.make_io()
            primary = io.devices["acu1"]
            secondary = io.secondary_devices["acu1"]
            failed, other = (secondary, primary) if failed_secondary else (primary, secondary)
            failed.fail = True
            with self.assertRaises(OSError):
                io.write("acu1", True)
            self.assertTrue(other.state)
            self.assertFalse(io.outputs["acu1"])
            with self.assertRaises(OSError):
                io.write("acu1", False)
            self.assertFalse(other.state)
            io.close()
            self.assertTrue(primary.closed and secondary.closed)

    def test_dht_process_uses_configured_sensor_pin(self):
        config = mapped_hardware_config()
        config["gpio"]["dht"] = 18
        io = self.make_io(config)
        context = Mock()
        context.Process.return_value.is_alive.return_value = False
        with patch("backend.io.multiprocessing.get_context", return_value=context):
            io.start(3)
        self.assertEqual(context.Process.call_args.kwargs["args"],
                         (18, context.Value.return_value, context.Queue.return_value,
                          context.Event.return_value))
        context.Process.return_value.start.assert_called_once_with()

    def test_raw_level_polarity_independent_of_pull(self):
        for pull in ("none", "up", "down"):
            config = hardware_config()
            config["input_pull"] = {key: pull for key in ("door", "water", "smoke")}
            io = self.make_io(config)
            for level in (False, True):
                for active in (False, True):
                    for device in io.inputs.values():
                        device.pin.state = level
                    result = io.read_digital({key: active for key in io.inputs})
                    self.assertTrue(all(value == (level == active) for value in result.values()))
            for device in io.inputs.values():
                self.assertEqual("active_state" in device.kwargs, pull == "none")

    def test_real_gpiozero_mock_electrical_levels(self):
        from gpiozero import DigitalInputDevice, DigitalOutputDevice
        from gpiozero.pins.mock import MockFactory
        for pull in ("none", "up", "down"):
            factory = MockFactory()
            config = hardware_config()
            config["input_pull"] = {key: pull for key in ("door", "water", "smoke")}
            io = IO(config,
                    lambda *args, **kwargs: DigitalOutputDevice(*args, pin_factory=factory, **kwargs),
                    lambda *args, **kwargs: DigitalInputDevice(*args, pin_factory=factory, **kwargs))
            try:
                for active in (True, False):
                    for device in io.inputs.values():
                        device.pin.drive_high()
                    self.assertTrue(all(value == active for value in
                                        io.read_digital({key: active for key in io.inputs}).values()))
                    for device in io.inputs.values():
                        device.pin.drive_low()
                    self.assertTrue(all(value != active for value in
                                        io.read_digital({key: active for key in io.inputs}).values()))
            finally:
                io.close()

    def test_seven_outputs_and_failed_write_state(self):
        config = hardware_config()
        config["output_active_high"]["smoke"] = False
        io = self.make_io(config)
        self.assertEqual(io.outputs, dict.fromkeys(OUTPUTS, False))
        self.assertFalse(io.devices["smoke"].kwargs["active_high"])
        for name in OUTPUTS:
            io.write(name, True)
        self.assertTrue(all(io.outputs.values()))
        io.devices["water"].fail = True
        with self.assertRaises(OSError):
            io.write("water", False)
        self.assertTrue(io.outputs["water"])
        io.close()
        self.assertTrue(all(device.closed for device in io.devices.values()))
        self.assertTrue(all(device.off_calls >= 1 for device in io.devices.values()))

    def test_door_output_active_high_and_input_is_independent(self):
        config = mapped_hardware_config()
        io, factory = mock_hardware_io(config)
        self.addCleanup(io.close)
        output = factory.pin(0)
        input_pin = factory.pin(22)
        self.assertFalse(output.state)
        self.assertTrue(io.devices["door"].active_high)
        input_pin.drive_high()
        for value in (True, False, True):
            io.write("door", value)
            self.assertEqual(output.state, value)
            self.assertTrue(input_pin.state)
            self.assertFalse(io.read_digital(config["input_active_high"])["door_open"])
        io.close()
        self.assertFalse(output.state)

    def test_gpiozero_per_output_physical_polarity(self):
        config = mapped_hardware_config()
        config["output_active_high"]["smoke"] = False
        io, factory = mock_hardware_io(config)
        pins = {name: factory.pin(config["gpio"][name]) for name in ("acu1", "acu2")}
        alarm_pin = factory.pin(config["gpio"]["alarm_smoke"])
        self.addCleanup(io.close)
        for pin in pins.values():
            self.assertFalse(pin.state)
        self.assertTrue(alarm_pin.state)
        for name, pin in pins.items():
            io.write(name, True)
            self.assertTrue(pin.state)
            io.write(name, False)
            self.assertFalse(pin.state)
            io.write(name, True)
        io.write("smoke", True)
        self.assertFalse(alarm_pin.state)
        io.write("smoke", False)
        self.assertTrue(alarm_pin.state)
        io.close()
        self.assertTrue(all(not pin.state for pin in pins.values()))
        self.assertTrue(alarm_pin.state)

    def test_mock_pin_overrides_and_failed_write_state(self):
        config = mapped_hardware_config()
        config["gpio"].update(acu1=20, acu2=21)
        io, factory = mock_hardware_io(config)
        self.addCleanup(io.close)
        for name in ("acu1", "acu2"):
            pin = factory.pin(config["gpio"][name])
            self.assertIs(io.devices[name].pin, pin)
            self.assertTrue(io.devices[name].active_high)
            self.assertFalse(pin.state)
            with patch.object(pin, "_set_state", side_effect=OSError("pin write")):
                with self.assertRaises(OSError):
                    io.write(name, True)
            self.assertFalse(pin.state)
            self.assertFalse(io.outputs[name])
            io.write(name, True)
            with patch.object(pin, "_set_state", side_effect=OSError("pin write")):
                with self.assertRaises(OSError):
                    io.write(name, False)
            self.assertTrue(pin.state)
            self.assertTrue(io.outputs[name])
        self.assertFalse(factory.pin(17).state)
        self.assertFalse(factory.pin(27).state)

    def test_invalid_acu_polarity_never_constructs_devices(self):
        for simulation in (True, False):
            for name in ("acu1", "acu2", "door"):
                config = mapped_hardware_config()
                config["simulation"] = simulation
                config["output_active_high"][name] = False
                factory = Mock()
                with self.subTest(simulation=simulation, name=name):
                    with self.assertRaisesRegex(ValueError, name):
                        IO(config, factory, factory)
                    factory.assert_not_called()

    def test_mock_partial_initialization_leaves_acus_low(self):
        from gpiozero import DigitalOutputDevice
        from gpiozero.pins.mock import MockFactory
        config = mapped_hardware_config()
        factory = MockFactory()
        devices = []

        def output(*args, **kwargs):
            if len(devices) == 2:
                raise OSError("initialization")
            device = DigitalOutputDevice(*args, pin_factory=factory, **kwargs)
            devices.append(device)
            return device

        with self.assertRaisesRegex(OSError, "initialization"):
            IO(config, output, Device)
        self.assertTrue(all(device.closed for device in devices))
        self.assertFalse(factory.pin(17).state)
        self.assertFalse(factory.pin(27).state)

    def test_simulation_never_constructs_physical_devices(self):
        factory = Mock()
        io = IO(copy.deepcopy(DEFAULTS), factory, factory)
        try:
            io.write("acu1", True)
            io.write("acu2", True)
            self.assertTrue(io.outputs["acu1"])
            self.assertTrue(io.outputs["acu2"])
            factory.assert_not_called()
        finally:
            io.close()

    def test_partial_initialization_cleanup(self):
        devices = []

        def factory(*args, **kwargs):
            if len(devices) == 3:
                raise RuntimeError("setup")
            device = Device(*args, **kwargs)
            devices.append(device)
            return device

        with self.assertRaises(RuntimeError):
            IO(hardware_config(), factory, Device)
        self.assertTrue(all(device.closed and device.off_calls for device in devices))

    def test_dht_schedule_invalid_samples_and_failures(self):
        clock = Clock()
        readings = iter([(24, 50), (float("nan"), 101), RuntimeError("transient"), (25, None)])

        def reader():
            value = next(readings)
            if isinstance(value, Exception):
                raise value
            return value

        io = self.make_io(dht_reader=reader, clock=clock)
        self.assertEqual(io.poll_dht(3)["temperature_c"], (24, 0))
        clock.now = 2.9
        self.assertEqual(io.poll_dht(3), {})
        for now in (3, 6):
            clock.now = now
            self.assertEqual(io.poll_dht(3), {})
        clock.now = 9
        self.assertEqual(io.poll_dht(3), {"temperature_c": (25, 9)})

    def test_sim_updates_do_not_refresh_unrelated_dht(self):
        clock = Clock()
        io = self.make_io(copy.deepcopy(DEFAULTS), clock=clock)
        clock.now = 10
        io.simulation_update({"smoke_alarm": True})
        self.assertEqual(io.poll_dht(3)["temperature_c"], (24, 0))
        io.simulation_update({"temperature_c": None})
        self.assertEqual(io.poll_dht(3)["temperature_c"], (None, None))
        self.assertEqual(io.poll_dht(3)["humidity_pct"], (50, 0))

    def test_dht_teardown_errors_never_skip_gpio_cleanup(self):
        io = self.make_io()
        io.process = Mock()
        io.process.is_alive.return_value = True
        for name in ("join", "terminate", "kill", "close"):
            getattr(io.process, name).side_effect = OSError(name)
        io.samples = Mock()
        io.samples.close.side_effect = OSError("queue")
        io.samples.cancel_join_thread.side_effect = OSError("queue")
        io.dht_stop = Mock()
        io.dht_stop.set.side_effect = OSError("event")
        io.close()
        self.assertTrue(all(device.closed for device in (*io.devices.values(), *io.inputs.values())))
        self.assertTrue(all(device.off_calls == 1 for device in io.devices.values()))
        io.process.terminate.assert_called_once()
        io.process.kill.assert_called_once()

    def test_failed_process_start_releases_acquired_hardware(self):
        io = self.make_io()
        context = Mock()
        context.Process.return_value.start.side_effect = RuntimeError("spawn")
        with patch("backend.io.multiprocessing.get_context", return_value=context), \
                self.assertRaises(RuntimeError):
            io.start(3)
        self.assertTrue(io.closed)
        self.assertTrue(all(device.closed and device.off_calls for device in io.devices.values()))
        context.Queue.return_value.close.assert_called_once()

    def test_failed_process_resource_creation_also_cleans_up(self):
        io = self.make_io()
        context = Mock()
        context.Event.side_effect = OSError("semaphore")
        with patch("backend.io.multiprocessing.get_context", return_value=context), \
                self.assertRaises(OSError):
            io.start(3)
        self.assertTrue(io.closed)
        self.assertTrue(all(device.closed and device.off_calls for device in io.devices.values()))
        context.Queue.return_value.close.assert_called_once()

    def test_blocked_real_child_is_terminated_within_bound(self):
        io = self.make_io()
        context = multiprocessing.get_context("spawn")
        io.dht_stop = context.Event()
        io.samples = context.Queue()
        blocked = context.Event()
        entered = context.Event()
        io.process = context.Process(target=blocked_worker, args=(blocked, entered))
        io.process.start()
        self.assertTrue(entered.wait(5))
        process = io.process
        started = time.monotonic()
        io.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(process._closed)
        self.assertTrue(all(device.closed for device in io.devices.values()))
