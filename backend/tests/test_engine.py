import copy
import itertools
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.config import Configuration, OUTPUTS
from backend.engine import Engine, EventStore
from backend.io import IO
from test_io import Clock, Device, hardware_config, mapped_hardware_config, mock_hardware_io


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.config = Configuration(self.path, {})
        self.clock = Clock()
        self.io = IO(self.config.effective, clock=self.clock)
        self.events = EventStore(Path(self.temp.name) / "coolshift.sqlite3")
        self.engine = Engine(self.config, self.io, self.clock, self.events)
        self.addCleanup(self.engine.shutdown)

    def cycle(self, now, **sensors):
        self.clock.now = now
        if sensors:
            self.engine.simulation_update(sensors)
        self.engine.tick()
        return self.engine.status()

    def test_auto_pause_and_restart_boundary(self):
        self.assertEqual(self.engine.status()["acu_outputs"], {"acu1": False, "acu2": False})
        self.cycle(0)
        self.assertTrue(self.io.outputs["acu1"])
        self.engine.set_mode("pause")
        self.cycle(1)
        self.assertFalse(self.io.outputs["acu1"])
        self.engine.set_mode("auto")
        self.cycle(300)
        self.assertFalse(self.io.outputs["acu1"])
        self.cycle(301)
        self.assertTrue(self.io.outputs["acu1"])

    def test_zero_delay_allows_immediate_manual_restart_and_reenable(self):
        self.engine.set_mode("manual")
        for acu in (1, 2):
            self.engine.command_acu(acu, "on")
            self.engine.command_acu(acu, "off")
            with self.assertRaisesRegex(RuntimeError, "restart delay"):
                self.engine.command_acu(acu, "on")
        self.engine.patch_settings({"min_off_seconds": 0})
        for acu in (1, 2):
            self.engine.command_acu(acu, "on")
            self.engine.command_acu(acu, "off")
            self.engine.command_acu(acu, "on")
            self.engine.command_acu(acu, "off")
        self.engine.patch_settings({"min_off_seconds": 180})
        for acu in (1, 2):
            with self.assertRaisesRegex(RuntimeError, "restart delay"):
                self.engine.command_acu(acu, "on")
        self.clock.now = 180
        for acu in (1, 2):
            self.engine.command_acu(acu, "on")

    def test_zero_delay_allows_auto_resume_and_boost_restart(self):
        self.engine.patch_settings({"min_off_seconds": 0})
        self.cycle(0)
        self.engine.set_mode("pause")
        self.cycle(0)
        self.engine.set_mode("auto")
        self.assertTrue(self.cycle(0)["acu_outputs"]["acu1"])
        self.assertTrue(self.cycle(0, temperature_c=27)["acu_outputs"]["acu2"])
        self.assertFalse(self.cycle(0, temperature_c=25)["acu_outputs"]["acu2"])
        self.assertTrue(self.cycle(0, temperature_c=27)["acu_outputs"]["acu2"])

    def test_delayed_rotation_measures_actual_overlap(self):
        self.cycle(0)
        self.engine.last_rotation = -21600
        self.engine.off_since[1] = 0
        self.cycle(1)
        self.assertEqual(self.engine.pending, 1)
        self.assertIsNone(self.engine.pending_since)
        self.assertTrue(self.io.outputs["acu1"])
        self.cycle(299.99)
        self.assertFalse(self.io.outputs["acu2"])
        self.cycle(300)
        self.assertEqual(self.engine.pending_since, 300)
        self.cycle(314.99)
        self.assertTrue(self.io.outputs["acu1"])
        self.cycle(315)
        self.assertEqual(self.engine.lead, 1)
        self.assertFalse(self.io.outputs["acu1"])
        self.assertTrue(self.io.outputs["acu2"])

    def test_manual_commands_survive_ticks_and_keep_alarms_active(self):
        self.cycle(0)
        self.engine.set_mode("manual")
        self.assertTrue(self.io.outputs["acu1"])
        self.engine.command_acu(2, "on")
        self.engine.command_acu(1, "off")
        status = self.cycle(21600, temperature_c=35, humidity_pct=80,
                            smoke_alarm=True, water_level_alarm=True)
        self.assertEqual(status["acu_outputs"], {"acu1": False, "acu2": True})
        self.assertTrue(all(value for key, value in status["alarm_outputs"].items() if key != "door"))
        self.assertFalse(status["boost"])
        self.assertIsNone(status["handover_pending"])
        self.engine.command_acu(2, "off")
        self.assertFalse(any(self.cycle(21601)["acu_outputs"].values()))
        self.engine.set_mode("auto")
        self.assertEqual(self.engine.last_rotation, 21601)
        self.assertTrue(self.cycle(21602)["acu_outputs"]["acu1"])

    def test_manual_gating_restart_delay_and_failure(self):
        for mode in ("auto", "pause"):
            self.engine.set_mode(mode)
            with self.assertRaisesRegex(RuntimeError, "MANUAL"):
                self.engine.command_acu(1, "on")
        self.engine.set_mode("manual")
        self.engine.command_acu(1, "on")
        self.engine.command_acu(1, "off")
        self.clock.now = 299.99
        with self.assertRaisesRegex(RuntimeError, "restart delay"):
            self.engine.command_acu(1, "on")
        self.clock.now = 300
        self.engine.command_acu(1, "on")
        self.engine.command_acu(1, "on")
        self.engine.set_mode("pause")
        self.assertFalse(any(self.cycle(301)["acu_outputs"].values()))
        self.engine.set_mode("manual")
        with patch.object(self.io, "write", side_effect=OSError("relay")):
            with self.assertRaisesRegex(RuntimeError, "restart required"):
                self.engine.command_acu(2, "on")
        self.assertIn("CONTROLLER_ERROR", self.engine.alarms)
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            self.engine.command_acu(1, "off")

    def make_mock_engine(self):
        raw = mapped_hardware_config()
        raw["gpio"].update(acu1=20, acu2=21)
        config = Configuration(self.path, raw)
        io, factory = mock_hardware_io(config.effective, clock=self.clock)
        engine = Engine(config, io, self.clock, self.events)
        self.addCleanup(engine.shutdown)
        return engine, io, factory

    def test_manual_mock_pins_repeated_commands_preserve_transition_state(self):
        engine, io, factory = self.make_mock_engine()
        engine.set_mode("manual")
        for acu in (1, 2):
            name = f"acu{acu}"
            pin = factory.pin(engine.settings["gpio"][name])
            for action, level in (("off", False), ("on", True), ("off", False)):
                self.clock.now += 10
                engine.command_acu(acu, action)
                self.assertEqual(pin.state, level)
                timings = (engine.on_since[:], engine.off_since[:],
                           engine.last_rotation, engine.pending, engine.pending_since)
                history = self.events.events(500)
                self.clock.now += 10
                # Disturb only the mock electrical level to prove the write is reapplied.
                pin.state = not level
                with patch.object(io.devices[name], action, wraps=getattr(io.devices[name], action)) as write:
                    status = engine.command_acu(acu, action)
                    write.assert_called_once_with()
                self.assertEqual(pin.state, level)
                self.assertEqual(status["acu_outputs"][name], level)
                self.assertEqual(timings, (engine.on_since[:], engine.off_since[:],
                                          engine.last_rotation, engine.pending, engine.pending_since))
                self.assertEqual(self.events.events(500), history)
        self.assertFalse(factory.pin(17).state)
        self.assertFalse(factory.pin(27).state)

    def test_manual_mock_rejections_do_not_write(self):
        engine, io, factory = self.make_mock_engine()
        with patch.object(io, "write", wraps=io.write) as write:
            for mode in ("auto", "pause"):
                engine.set_mode(mode)
                for acu in (1, 2):
                    for action in ("on", "off"):
                        with self.assertRaisesRegex(RuntimeError, "MANUAL"):
                            engine.command_acu(acu, action)
            engine.set_mode("manual")
            for acu, action in ((0, "on"), (3, "off"), (1, "invalid")):
                with self.assertRaises(ValueError):
                    engine.command_acu(acu, action)
            write.assert_not_called()
            engine.command_acu(1, "on")
            engine.command_acu(1, "off")
            write.reset_mock()
            self.clock.now = 299.99
            with self.assertRaisesRegex(RuntimeError, "restart delay"):
                engine.command_acu(1, "on")
            write.assert_not_called()
            self.assertFalse(factory.pin(20).state)
            self.clock.now = 300
            engine.command_acu(1, "on")
            self.assertTrue(factory.pin(20).state)
            engine.shutdown()
            write.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                engine.command_acu(1, "off")
            write.assert_not_called()

    def test_manual_mock_write_failure_and_fatal_off_state_integrity(self):
        for initially_on in (False, True):
            with self.subTest(initially_on=initially_on):
                engine, io, factory = self.make_mock_engine()
                engine.set_mode("manual")
                pin = factory.pin(20)
                if initially_on:
                    engine.command_acu(1, "on")
                engine.command_acu(2, "on")
                history = self.events.events(500)
                on_since = engine.on_since[0]
                off_since = engine.off_since[0]
                action = "off" if initially_on else "on"
                with patch.object(pin, "_set_state", side_effect=OSError("pin write")), \
                        patch.object(io, "write", wraps=io.write) as write:
                    with self.assertRaisesRegex(RuntimeError, "command failed"):
                        engine.command_acu(1, action)
                    self.assertEqual(write.call_args_list[0].args, ("acu1", not initially_on))
                    self.assertEqual([call.args for call in write.call_args_list[1:]],
                                     [(name, False) for name in OUTPUTS])
                    self.assertEqual(pin.state, initially_on)
                    self.assertEqual(engine.status()["acu_outputs"]["acu1"], initially_on)
                    self.assertEqual(engine.on_since[0], on_since)
                    self.assertEqual(engine.off_since[0], off_since)
                    self.assertFalse(factory.pin(21).state)
                    self.assertIn("CONTROLLER_ERROR", engine.alarms)
                    self.assertFalse(any(row["kind"] == "output" for row in
                                         self.events.events(500) if row["id"] > history[0]["id"]))
                    write.reset_mock()
                    with self.assertRaisesRegex(RuntimeError, "stopped"):
                        engine.command_acu(2, "on")
                    write.assert_not_called()
                engine.shutdown()
                self.assertFalse(pin.state)

    def test_automatic_mock_writes_are_transition_only_and_shutdown_is_low(self):
        engine, io, factory = self.make_mock_engine()
        with patch.object(io, "write", wraps=io.write) as write:
            engine.tick()
            self.assertTrue(factory.pin(20).state)
            self.assertFalse(factory.pin(21).state)
            write.assert_called_once_with("acu1", True)
            write.reset_mock()
            self.clock.now += 1
            engine.tick()
            write.assert_not_called()
            engine.set_mode("manual")
            engine.command_acu(2, "on")
            self.assertTrue(factory.pin(21).state)
            engine.shutdown()
            self.assertFalse(factory.pin(20).state)
            self.assertFalse(factory.pin(21).state)

    def test_boost_hysteresis_and_handover(self):
        self.cycle(0, temperature_c=27)
        self.assertTrue(self.engine.boost)
        self.assertTrue(self.io.outputs["acu2"])
        self.cycle(10, temperature_c=26)
        self.assertTrue(self.engine.boost)
        self.engine.last_rotation = -21600
        self.cycle(11, temperature_c=28)
        self.cycle(26, temperature_c=28)
        self.assertEqual(self.engine.lead, 1)
        self.assertTrue(self.io.outputs["acu1"])
        self.cycle(27, temperature_c=25)
        self.assertFalse(self.engine.boost)
        self.assertFalse(self.io.outputs["acu1"])

    def test_all_alarms_in_pause_clear_independently(self):
        self.engine.set_mode("pause")
        status = self.cycle(0, water_level_alarm=True, smoke_alarm=True,
                            temperature_c=30, humidity_pct=65, door_open=True)
        self.assertTrue(all(value for key, value in status["alarm_outputs"].items() if key != "door"))
        self.assertFalse(status["alarm_outputs"]["door"])
        self.assertFalse(any(status["acu_outputs"].values()))
        self.assertNotIn("DOOR_OPEN", status["alarms"])
        status = self.cycle(3, temperature_c=30, humidity_pct=65)
        self.assertIn("DOOR_OPEN", status["alarms"])
        self.assertTrue(status["alarm_outputs"]["door"])
        status = self.cycle(4, water_level_alarm=False)
        self.assertFalse(status["alarm_outputs"]["water"])
        self.assertTrue(status["alarm_outputs"]["smoke"])
        self.assertTrue(status["alarm_outputs"]["temperature"])
        self.assertTrue(status["alarm_outputs"]["humidity"])
        events = self.events.events(500)
        self.assertTrue(any(row["kind"] == "alarm_clear" and
                            row["detail"] == "WATER_LEVEL_ALARM" for row in events))

    def test_door_three_second_boundary_close_and_reopen_all_modes(self):
        for mode in ("auto", "manual", "pause"):
            self.engine.set_mode(mode)
            base = self.clock.now + 10
            self.cycle(base, door_open=False)
            self.assertFalse(self.io.outputs["door"])
            self.cycle(base + 1, door_open=True)
            self.assertFalse(self.cycle(base + 3.999)["alarm_outputs"]["door"])
            status = self.cycle(base + 4)
            self.assertTrue(status["alarm_outputs"]["door"])
            self.assertIn("DOOR_OPEN", status["alarms"])
            self.assertTrue(self.cycle(base + 5)["alarm_outputs"]["door"])
            status = self.cycle(base + 6, door_open=False)
            self.assertFalse(status["alarm_outputs"]["door"])
            self.assertNotIn("DOOR_OPEN", status["alarms"])
            self.cycle(base + 7, door_open=True)
            self.cycle(base + 9, door_open=False)
            self.cycle(base + 10, door_open=True)
            self.assertFalse(self.cycle(base + 12.999)["alarm_outputs"]["door"])
            self.assertTrue(self.cycle(base + 13)["alarm_outputs"]["door"])

    def test_door_setting_and_input_polarity_reset_qualification(self):
        self.cycle(0, door_open=True)
        self.cycle(2)
        self.engine.patch_settings({"door_alarm_seconds": 4})
        self.cycle(3)
        self.assertFalse(self.cycle(6.999)["alarm_outputs"]["door"])
        self.assertTrue(self.cycle(7)["alarm_outputs"]["door"])
        self.engine.patch_settings({"input_active_high": {"door": True}})
        self.assertIsNone(self.engine.trigger_since["DOOR_OPEN"])
        self.assertFalse(self.cycle(8)["alarm_outputs"]["door"])
        self.assertTrue(self.cycle(12)["alarm_outputs"]["door"])

    def test_mock_door_pin_qualifies_and_closes_for_both_input_polarities(self):
        for active_high in (False, True):
            engine, io, factory = self.make_mock_engine()
            engine.patch_settings({"input_active_high": {"door": active_high}})
            input_pin, output_pin = factory.pin(22), factory.pin(0)
            input_pin.drive_high() if active_high else input_pin.drive_low()
            self.clock.now = 0
            engine.tick()
            self.clock.now = 2.999
            engine.tick()
            self.assertFalse(output_pin.state)
            self.clock.now = 3
            engine.tick()
            self.assertTrue(output_pin.state)
            input_pin.drive_low() if active_high else input_pin.drive_high()
            engine.tick()
            self.assertFalse(output_pin.state)
            self.assertFalse(io.outputs["door"])
            engine.shutdown()

    def test_continuous_delays_and_setting_reset(self):
        self.engine.patch_settings({"water_alarm_seconds": 10, "smoke_alarm_seconds": 5})
        self.cycle(0, water_level_alarm=True, smoke_alarm=True)
        self.cycle(5)
        self.assertFalse(self.io.outputs["water"])
        self.assertTrue(self.io.outputs["smoke"])
        self.cycle(9, water_level_alarm=False)
        self.cycle(10, water_level_alarm=True)
        self.cycle(19)
        self.assertFalse(self.io.outputs["water"])
        self.engine.patch_settings({"water_alarm_seconds": 9})
        self.cycle(20)
        self.assertFalse(self.io.outputs["water"])
        self.cycle(29)
        self.assertTrue(self.io.outputs["water"])
        self.engine.patch_settings({"smoke_alarm_seconds": 5})
        self.assertIsNotNone(self.engine.trigger_since["SMOKE_ALARM"])

    def test_threshold_and_polarity_reset_only_related_timer(self):
        self.engine.patch_settings({"temperature_alarm_seconds": 10})
        self.cycle(0, temperature_c=35, smoke_alarm=True)
        self.engine.patch_settings({"high_temp_alarm_c": 32, "input_active_high": {"water": False}})
        self.assertIsNone(self.engine.trigger_since["HIGH_TEMPERATURE"])
        self.assertIsNotNone(self.engine.trigger_since["SMOKE_ALARM"])
        self.cycle(9, temperature_c=35)
        self.assertFalse(self.io.outputs["temperature"])
        self.cycle(19, temperature_c=35)
        self.assertTrue(self.io.outputs["temperature"])

    def test_stale_boundary_digital_independence_missing_values(self):
        self.cycle(0, temperature_c=35, humidity_pct=80, smoke_alarm=True)
        status = self.cycle(30, door_open=True)
        self.assertEqual(status["sensor_freshness"]["temperature_c"], "OK")
        status = self.cycle(30.01, water_level_alarm=True)
        self.assertEqual(status["sensor_age_s"]["temperature_c"], 30.01)
        self.assertEqual(status["sensor_age_s"]["door_open"], 0)
        self.assertEqual(status["sensor_freshness"]["temperature_c"], "STALE")
        self.assertFalse(status["boost"])
        self.assertFalse(status["alarm_outputs"]["temperature"])
        self.assertFalse(status["alarm_outputs"]["humidity"])
        self.assertTrue(status["alarm_outputs"]["water"])
        self.assertTrue(status["alarm_outputs"]["smoke"])
        self.assertIn("SENSOR_STALE", status["alarms"])
        self.assertEqual(sum(status["acu_outputs"].values()), 1)
        status = self.cycle(31, temperature_c=None)
        self.assertIsNone(status["sensors"]["temperature_c"])
        self.assertIsNone(status["sensor_age_s"]["temperature_c"])
        self.assertEqual(status["sensor_freshness"]["temperature_c"], "UNKNOWN")

    def test_logging_errors_do_not_interrupt_output_or_safety(self):
        with patch.object(self.events, "log", side_effect=OSError("database")):
            self.cycle(0, temperature_c=35, humidity_pct=80, smoke_alarm=True,
                       water_level_alarm=True, door_open=True)
            self.cycle(3)
            self.assertTrue(all(self.io.outputs.values()))
            self.engine.shutdown()
            self.assertFalse(any(self.io.outputs.values()))

    def test_fatal_latch_attempts_every_channel_without_lying(self):
        self.cycle(0, temperature_c=35, humidity_pct=80, smoke_alarm=True, water_level_alarm=True)
        calls = []
        original = self.io.write

        def write(name, value):
            calls.append((name, value))
            if name == "water":
                raise OSError("relay")
            return original(name, value)

        with patch.object(self.io, "read_digital", side_effect=RuntimeError("control")), \
                patch.object(self.io, "write", side_effect=write), \
                patch.object(self.events, "log", side_effect=OSError("history")):
            self.engine.tick()
            self.assertEqual(calls, [(name, False) for name in OUTPUTS])
            status = self.engine.status()
            self.assertIn("CONTROLLER_ERROR", status["alarms"])
            self.assertIn("restart required", status["controller_error"])
            self.assertTrue(status["alarm_outputs"]["water"])
            self.assertFalse(status["acu_outputs"]["acu1"])
            self.engine.tick()
            self.assertEqual(len(calls), len(OUTPUTS))
            with self.assertRaises(RuntimeError):
                self.engine.set_mode("auto")

    def test_output_failure_is_fatal_not_physical_acu_fault(self):
        with patch.object(self.io, "write", side_effect=OSError("write")):
            self.engine.tick()
        self.assertFalse(self.io.outputs["acu1"])
        self.assertIn("CONTROLLER_ERROR", self.engine.alarms)
        self.assertFalse(any("ACU" in alarm for alarm in self.engine.alarms))
        self.assertNotIn("failed", self.engine.status())

    def test_hardware_starts_unknown_failed_dht_does_not_refresh(self):
        config = Configuration(self.path, hardware_config())
        readings = iter([(24, 50), RuntimeError("transient")])

        def reader():
            value = next(readings)
            if isinstance(value, Exception):
                raise value
            return value

        io = IO(config.effective, Device, Device, reader, self.clock)
        engine = Engine(config, io, self.clock)
        self.addCleanup(engine.shutdown)
        self.assertIsNone(engine.status()["sensors"]["temperature_c"])
        engine.acquire_dht()
        self.clock.now = 3
        engine.acquire_dht()
        engine.tick()
        self.assertEqual(engine.status()["sensor_age_s"]["temperature_c"], 3)

    def test_slow_injected_dht_not_under_engine_lock(self):
        entered, release = threading.Event(), threading.Event()

        def reader():
            entered.set()
            release.wait(2)
            return 24, 50

        config = Configuration(self.path, hardware_config())
        io = IO(config.effective, Device, Device, reader, self.clock)
        engine = Engine(config, io, self.clock)
        thread = threading.Thread(target=engine.acquire_dht)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            engine.tick()
            self.assertTrue(engine.status()["acu_outputs"]["acu1"])
            engine.patch_settings({"water_alarm_seconds": 2})
        finally:
            release.set()
            thread.join(2)
            engine.shutdown()
        self.assertFalse(thread.is_alive())

    def test_start_shutdown_threads_are_joined_and_idempotent(self):
        self.engine.start()
        self.engine.start()
        self.assertEqual(len(self.engine.threads), 2)
        self.engine.shutdown()
        self.engine.shutdown()
        self.assertFalse(any(thread.is_alive() for thread in self.engine.threads))
        self.assertTrue(self.io.closed)

    def test_stable_lead_command_between_rotations(self):
        self.cycle(0)
        status = self.cycle(100)
        self.assertTrue(status["acu_outputs"]["acu1"])
        self.assertEqual(status["acu_outputs"], {"acu1": True, "acu2": False})
        self.assertEqual(status["lead_acu"], 1)

    def test_all_thirty_two_alarm_combinations_auto_and_pause(self):
        self.engine.patch_settings({"door_alarm_seconds": 0})
        now = 0
        for mode in ("auto", "pause"):
            self.engine.set_mode(mode)
            for water, smoke, temperature, humidity, door in itertools.product((False, True), repeat=5):
                status = self.cycle(now, water_level_alarm=water, smoke_alarm=smoke,
                                    door_open=door,
                                    temperature_c=35 if temperature else 24,
                                    humidity_pct=80 if humidity else 50)
                self.assertEqual(status["alarm_outputs"], {
                    "water": water, "smoke": smoke, "temperature": temperature,
                    "humidity": humidity, "door": door})
                if mode == "pause":
                    self.assertFalse(any(status["acu_outputs"].values()))
                now += 1

    def test_thread_start_failure_attempts_all_off_and_closes(self):
        for fail_on in (1, 2):
            configuration = Configuration(self.path, {})
            io = IO(configuration.effective, clock=self.clock)
            engine = Engine(configuration, io, self.clock)
            self.addCleanup(engine.shutdown)
            real_start = threading.Thread.start
            count = 0

            def start(thread):
                nonlocal count
                count += 1
                if count == fail_on:
                    raise RuntimeError("thread start")
                real_start(thread)

            with patch("backend.engine.threading.Thread.start", new=start), \
                    patch.object(io, "write", wraps=io.write) as write:
                with self.assertRaisesRegex(RuntimeError, "thread start"):
                    engine.start()
                self.assertTrue(engine.closed)
                self.assertTrue(io.closed)
                self.assertIn("CONTROLLER_ERROR", engine.alarms)
                self.assertFalse(any(thread.is_alive() for thread in engine.threads))
                self.assertTrue(all((name, False) in [call.args for call in write.call_args_list]
                                    for name in OUTPUTS))
            engine.shutdown()

    def test_join_failure_still_closes_io(self):
        thread = Mock()
        thread.join.side_effect = RuntimeError("unstarted")
        self.engine.threads = [thread]
        with patch.object(self.io, "close", wraps=self.io.close) as close:
            self.engine.shutdown()
        close.assert_called_once()
        self.assertTrue(self.io.closed)
        self.assertFalse(any(self.io.outputs.values()))
