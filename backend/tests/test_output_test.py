import itertools
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import Configuration, OUTPUTS, OUTPUT_GPIO_KEYS
from backend.engine import Engine, OutputTestWriteError
from backend.io import IO
from test_io import Clock, mapped_hardware_config, mock_hardware_io


class OutputTestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.configuration = Configuration(self.path, {})
        self.clock = Clock()
        self.io = IO(self.configuration.effective, clock=self.clock)
        self.engine = Engine(self.configuration, self.io, self.clock)
        self.addCleanup(self.engine.shutdown)

    def start(self):
        return self.engine.start_output_test()["session_id"]

    def test_all_128_snapshots_restore_and_each_channel_is_independent(self):
        for mode in ("auto", "manual", "pause"):
            self.engine.set_mode(mode)
            for states in itertools.product((False, True), repeat=len(OUTPUTS)):
                with self.subTest(mode=mode, states=states):
                    snapshot = dict(zip(OUTPUTS, states))
                    for name, value in snapshot.items():
                        self.engine.set_output(name, value, self.clock())
                    with patch.object(self.io, "write", wraps=self.io.write) as write:
                        reply = self.engine.start_output_test()
                        write.assert_not_called()
                        self.assertEqual(reply["original_states"], snapshot)
                        reply["original_states"]["acu1"] = not snapshot["acu1"]
                        self.assertEqual(self.io.outputs, snapshot)
                        self.assertEqual(self.engine.mode, mode)
                        session_id = reply["session_id"]
                        for name in OUTPUTS:
                            for value in (not snapshot[name], snapshot[name], not snapshot[name]):
                                before = self.io.outputs.copy()
                                write.reset_mock()
                                self.engine.command_output_test(session_id, name, value)
                                write.assert_called_once_with(name, value)
                                self.assertEqual(self.io.outputs, {**before, name: value})
                        write.reset_mock()
                        status = self.engine.end_output_test(session_id)
                        self.assertEqual([call.args for call in write.call_args_list],
                                         list(snapshot.items()))
                    self.assertEqual(self.io.outputs, snapshot)
                    self.assertFalse(status["output_test"]["active"])
                    self.assertEqual(status["output_test"]["restoration_outcome"], "restored")
                    self.assertEqual(status["mode"], mode)

    def test_polarity_and_configured_pins_for_all_128_snapshots(self):
        for active_high in (False, True):
            raw = mapped_hardware_config()
            raw["gpio"].update(acu1=20, acu2=21)
            for name in ("water", "smoke", "temperature", "humidity"):
                raw["output_active_high"][name] = active_high
            config = Configuration(self.path, raw)
            io, factory = mock_hardware_io(config.effective, clock=self.clock)
            engine = Engine(config, io, self.clock)
            self.addCleanup(engine.shutdown)
            inputs = {name: device.pin.state for name, device in io.inputs.items()}
            for states in itertools.product((False, True), repeat=len(OUTPUTS)):
                with self.subTest(active_high=active_high, states=states):
                    snapshot = dict(zip(OUTPUTS, states))
                    for name, value in snapshot.items():
                        engine.set_output(name, value, self.clock())
                    session_id = engine.start_output_test()["session_id"]
                    for name in OUTPUTS:
                        for value in (True, False):
                            engine.command_output_test(session_id, name, value)
                            polarity = True if name.startswith("acu") or name == "door" else active_high
                            pin = factory.pin(raw["gpio"][OUTPUT_GPIO_KEYS[name]])
                            self.assertEqual(pin.state, value == polarity)
                    engine.end_output_test(session_id)
                    for name, value in snapshot.items():
                        polarity = True if name.startswith("acu") or name == "door" else active_high
                        pin = factory.pin(raw["gpio"][OUTPUT_GPIO_KEYS[name]])
                        self.assertEqual(pin.state, value == polarity)
                    self.assertEqual(io.outputs, snapshot)
                    self.assertEqual(inputs, {name: device.pin.state for name, device in io.inputs.items()})
                    self.assertNotIn(4, [device.pin.number for device in io.devices.values()])
                    self.assertFalse(factory.pin(17).state)
                    self.assertFalse(factory.pin(27).state)

    def test_restart_bypass_real_transition_times_and_repeated_writes(self):
        self.engine.set_mode("manual")
        self.engine.command_acu(1, "on")
        self.engine.pending = 1
        self.engine.pending_since = 0
        self.clock.now = 2
        session_id = self.start()
        self.engine.command_output_test(session_id, "acu1", False)
        self.assertEqual(self.engine.off_since[0], 2)
        self.clock.now = 3
        self.engine.command_output_test(session_id, "acu1", True)
        self.assertEqual(self.engine.on_since[0], 3)
        self.engine.command_output_test(session_id, "acu2", True)
        self.engine.command_output_test(session_id, "acu2", False)
        self.assertIsNone(self.engine.pending_since)
        self.clock.now = 4
        self.engine.command_output_test(session_id, "acu1", False)
        self.clock.now = 5
        self.engine.end_output_test(session_id)
        self.assertEqual(self.engine.on_since[0], 5)
        self.assertEqual(self.engine.off_since[0], 4)
        self.assertEqual(self.engine.last_rotation, 0)
        self.engine.command_acu(1, "off")
        with self.assertRaisesRegex(RuntimeError, "restart delay"):
            self.engine.command_acu(1, "on")
        session_id = self.start()
        self.engine.command_output_test(session_id, "acu1", True)
        timings = (self.engine.on_since[:], self.engine.off_since[:])
        self.clock.now = 6
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            self.engine.command_output_test(session_id, "acu1", True)
            write.assert_called_once_with("acu1", True)
        self.assertEqual(timings, (self.engine.on_since[:], self.engine.off_since[:]))
        self.engine.end_output_test(session_id)
        self.assertEqual(self.engine.off_since[0], 6)

    def test_ticks_suppress_all_writes_but_qualify_clear_and_stale_alarms(self):
        self.engine.patch_settings({"smoke_alarm_seconds": 2})
        session_id = self.start()
        self.engine.command_output_test(session_id, "water", True)
        self.engine.simulation_update({"smoke_alarm": True, "temperature_c": 35,
                                      "humidity_pct": 80, "door_open": True})
        snapshot = self.io.outputs.copy()
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            self.engine.tick()
            self.clock.now = 2
            self.engine.tick()
            status = self.engine.status()
            self.assertTrue(status["boost"])
            self.assertIn("SMOKE_ALARM", status["alarms"])
            self.assertIn("HIGH_TEMPERATURE", status["alarms"])
            self.assertNotIn("WATER_LEVEL_ALARM", status["alarms"])
            self.assertEqual(status["sensor_age_s"]["smoke_alarm"], 0)
            self.engine.simulation_update({"smoke_alarm": False, "temperature_c": None})
            self.clock.now = 3
            self.engine.tick()
            self.assertIn("SENSOR_STALE", self.engine.alarms)
            self.assertIn("DOOR_OPEN", self.engine.alarms)
            self.assertFalse(self.io.outputs["door"])
            self.assertNotIn("SMOKE_ALARM", self.engine.alarms)
            write.assert_not_called()
        self.assertEqual(self.io.outputs, snapshot)
        self.engine.end_output_test(session_id)
        self.assertFalse(self.io.outputs["door"])
        self.engine.tick()
        self.assertTrue(self.io.outputs["door"])
        self.assertFalse(self.io.outputs["water"])
        self.assertTrue(self.io.outputs["acu1"])

    def test_lease_boundary_wrong_ids_invalid_commands_do_not_renew(self):
        session_id = self.start()
        self.clock.now = 9
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            for identifier, channel, value in (
                ("wrong", "acu1", True), (session_id, "unknown", True),
                (session_id, "acu1", 1), ("", "acu1", False),
            ):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.engine.command_output_test(identifier, channel, value)
            with self.assertRaises(RuntimeError):
                self.engine.heartbeat_output_test("wrong")
            with self.assertRaises(RuntimeError):
                self.engine.end_output_test("wrong")
            write.assert_not_called()
        self.assertEqual(self.engine.status()["output_test"]["lease_remaining_s"], 1)
        self.engine.heartbeat_output_test(session_id)
        self.clock.now = 18
        self.engine.command_output_test(session_id, "acu1", True)
        self.clock.now = 27.999
        self.engine.tick()
        self.assertTrue(self.engine.status()["output_test"]["active"])
        self.clock.now = 28
        for operation, args in (
            (self.engine.heartbeat_output_test, (session_id,)),
            (self.engine.command_output_test, (session_id, "acu1", False)),
            (self.engine.end_output_test, (session_id,)),
        ):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                operation(*args)
        with patch("backend.engine.time.time", create=True, return_value=-999999):
            self.engine.tick()
        self.assertFalse(any(self.io.outputs.values()))
        self.assertEqual(self.engine.status()["output_test"]["restoration_outcome"], "restored")
        self.engine.end_output_test(session_id)
        self.clock.now = 28.1
        self.engine.tick()
        self.assertFalse(self.io.outputs["acu1"])  # Real OFF at restore starts protection.
        self.clock.now = 328
        self.engine.tick()
        self.assertTrue(self.io.outputs["acu1"])

    def test_conflicts_fresh_snapshots_no_persistence_and_harmless_end_retries(self):
        self.engine.set_mode("manual")
        before = self.engine.settings_contract()
        session_id = self.start()
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            for operation in (
                self.engine.start_output_test,
                lambda: self.engine.set_mode("pause"),
                lambda: self.engine.command_acu(1, "on"),
                lambda: self.engine.patch_settings({"smoke_alarm_seconds": 8}),
            ):
                with self.assertRaisesRegex(RuntimeError, "testing active"):
                    operation()
            write.assert_not_called()
        self.assertEqual(self.engine.settings_contract(), before)
        self.assertFalse(self.path.exists())
        self.engine.end_output_test(session_id)
        self.engine.command_acu(2, "on")
        newer = self.engine.start_output_test()
        self.assertTrue(newer["original_states"]["acu2"])
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            self.engine.end_output_test(session_id)
            write.assert_not_called()
        self.assertTrue(self.engine.status()["output_test"]["active"])
        self.assertTrue(self.io.outputs["acu2"])
        with self.assertRaises(RuntimeError):
            self.engine.heartbeat_output_test(session_id)
        fresh = Engine(self.configuration, clock=self.clock)
        self.addCleanup(fresh.shutdown)
        self.assertFalse(fresh.status()["output_test"]["active"])

    def test_each_restore_failure_attempts_remaining_then_fatal_off(self):
        for fail_name in OUTPUTS:
            for expire in (False, True):
                with self.subTest(channel=fail_name, expire=expire):
                    io = IO(self.configuration.effective, clock=self.clock)
                    engine = Engine(self.configuration, io, self.clock)
                    self.addCleanup(engine.shutdown)
                    for name in OUTPUTS:
                        engine.set_output(name, True, self.clock())
                    session_id = engine.start_output_test()["session_id"]
                    original = io.write
                    calls = []

                    def write(name, value):
                        calls.append((name, value))
                        if name == fail_name:
                            raise OSError("broken relay")
                        original(name, value)

                    with patch.object(io, "write", side_effect=write):
                        if expire:
                            self.clock.now += 10
                            engine.tick()
                        else:
                            with self.assertRaises(OutputTestWriteError):
                                engine.end_output_test(session_id)
                        self.assertEqual(calls, [(name, True) for name in OUTPUTS]
                                         + [(name, False) for name in OUTPUTS])
                        status = engine.status()
                        self.assertFalse(status["output_test"]["active"])
                        self.assertEqual(status["output_test"]["restoration_outcome"], "failed")
                        self.assertIn(fail_name, status["output_test"]["restoration_error"])
                        self.assertIn("CONTROLLER_ERROR", status["alarms"])
                        self.assertEqual(io.outputs, {name: name == fail_name for name in OUTPUTS})
                        with self.assertRaises(OutputTestWriteError):
                            engine.end_output_test(session_id)
                        self.assertEqual(len(calls), 2 * len(OUTPUTS))

    def test_each_failed_test_write_cache_and_timings_remain_truthful(self):
        for fail_name in OUTPUTS:
            io = IO(self.configuration.effective, clock=self.clock)
            engine = Engine(self.configuration, io, self.clock)
            self.addCleanup(engine.shutdown)
            session_id = engine.start_output_test()["session_id"]
            before = (engine.on_since[:], engine.off_since[:])
            original = io.write
            calls = []

            def write(name, value):
                calls.append((name, value))
                if name == fail_name:
                    raise OSError("broken relay")
                original(name, value)

            with patch.object(io, "write", side_effect=write):
                with self.assertRaises(OutputTestWriteError):
                    engine.command_output_test(session_id, fail_name, True)
                self.assertEqual(calls, [(fail_name, True)] + [(name, False) for name in OUTPUTS])
                self.assertFalse(io.outputs[fail_name])
                if fail_name.startswith("acu"):
                    index = int(fail_name[-1]) - 1
                    self.assertEqual(engine.on_since[index], before[0][index])
                    self.assertEqual(engine.off_since[index], before[1][index])
                self.assertEqual(engine.status()["output_test"]["restoration_outcome"], "failed")

    def test_shutdown_fatal_and_stopped_controllers_never_restore_on_snapshot(self):
        for lifecycle in ("shutdown", "fatal", "stopped"):
            io = IO(self.configuration.effective, clock=self.clock)
            engine = Engine(self.configuration, io, self.clock)
            self.addCleanup(engine.shutdown)
            for name in OUTPUTS:
                engine.set_output(name, True, self.clock())
            session_id = engine.start_output_test()["session_id"]
            with patch.object(io, "write", wraps=io.write) as write:
                if lifecycle == "shutdown":
                    engine.shutdown()
                elif lifecycle == "fatal":
                    engine.fatal(RuntimeError("failure"))
                else:
                    engine.stop_event.set()
                if lifecycle != "stopped":
                    self.assertEqual([call.args for call in write.call_args_list],
                                     [(name, False) for name in OUTPUTS])
                    self.assertFalse(any(io.outputs.values()))
                write.reset_mock()
                for operation in (
                    engine.start_output_test,
                    lambda: engine.command_output_test(session_id, "acu1", True),
                    lambda: engine.heartbeat_output_test(session_id),
                    lambda: engine.end_output_test(session_id),
                ):
                    with self.assertRaises(RuntimeError):
                        operation()
                engine.tick()
                write.assert_not_called()

    def test_lock_serializes_output_end_tick_and_new_owner(self):
        session_id = self.start()
        entered, release = threading.Event(), threading.Event()
        original = self.io.write
        results = []

        def write(name, value):
            if name == "acu1" and value:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test synchronization timeout")
            original(name, value)

        def command():
            results.append(self.engine.command_output_test(session_id, "acu1", True))

        def end():
            results.append(self.engine.end_output_test(session_id))

        with patch.object(self.io, "write", side_effect=write):
            command_thread = threading.Thread(target=command)
            end_thread = threading.Thread(target=end)
            tick_thread = threading.Thread(target=self.engine.tick)
            command_thread.start()
            try:
                self.assertTrue(entered.wait(1))
                end_thread.start()
                tick_thread.start()
                self.assertFalse(self.engine.lock.acquire(blocking=False))
            finally:
                release.set()
                for thread in (command_thread, end_thread, tick_thread):
                    if thread.ident is not None:
                        thread.join(3)
            self.assertFalse(any(t.is_alive() for t in (command_thread, end_thread, tick_thread)))
        self.assertEqual(len(results), 2)
        self.assertFalse(self.engine.status()["output_test"]["active"])
        newer = self.start()
        self.assertNotEqual(session_id, newer)
        with self.assertRaises(RuntimeError):
            self.engine.command_output_test(session_id, "water", True)
        self.engine.end_output_test(newer)
