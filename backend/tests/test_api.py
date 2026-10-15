import concurrent.futures
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import uvicorn

from backend.api import create_app
from backend.config import Configuration, DEFAULTS
from backend.engine import Engine, EventStore
from backend.io import IO
from test_io import Clock, Device, hardware_config, mapped_hardware_config, mock_hardware_io


class LiveServer:
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.base = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        self.thread = threading.Thread(target=self.server.run,
                                       kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("API test server failed to start")
            threading.Event().wait(0.01)

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("API test server failed to stop")

    def request(self, path, method="GET", payload=None, raw=None):
        body = raw if raw is not None else (
            None if payload is None else json.dumps(payload).encode())
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.path.write_text("{}")
        self.configuration = Configuration(self.path)
        self.engine = Engine(self.configuration, event_store=EventStore(
            Path(self.temp.name) / "coolshift.sqlite3"))
        self.server = LiveServer(create_app(self.engine))
        self.addCleanup(self.server.close)

    def request(self, *args, **kwargs):
        return self.server.request(*args, **kwargs)

    def test_status_contract_and_settings(self):
        code, data = self.request("/api/status")
        self.assertEqual(code, 200)
        keys = {"temperature_c", "humidity_pct", "door_open", "smoke_alarm", "water_level_alarm"}
        self.assertEqual(set(data["sensors"]), keys)
        self.assertEqual(set(data["sensor_age_s"]), keys)
        self.assertEqual(set(data["sensor_freshness"]), keys)
        self.assertEqual(set(data), {
            "simulation", "mode", "sensors", "sensor_age_s", "sensor_freshness",
            "acu_outputs", "alarm_outputs", "lead_acu", "rotation_remaining_s",
            "handover_pending", "boost", "alarms", "controller_error", "fatal_error",
            "output_test",
        })
        self.assertEqual(set(data["alarm_outputs"]), {"water", "smoke", "temperature", "humidity", "door"})
        self.assertNotIn("failed", data)
        code, data = self.request("/api/settings")
        self.assertEqual(code, 200)
        self.assertEqual(data["effective"], DEFAULTS)
        self.assertEqual(data["defaults"], DEFAULTS)
        self.assertEqual(data["effective"]["door_alarm_seconds"], 3)
        self.assertEqual(data["restart_required"],
                         ["simulation", "gpio", "output_active_high", "input_pull"])

    def test_patch_persists_and_returns_authoritative_values(self):
        code, data = self.request("/api/settings", "PATCH",
                                  {"high_humidity_alarm_pct": 73, "water_alarm_seconds": 8,
                                   "input_active_high": {"door": True}})
        self.assertEqual(code, 200)
        self.assertEqual(data["effective"]["high_humidity_alarm_pct"], 73)
        self.assertTrue(data["effective"]["input_active_high"]["door"])
        restarted = Configuration(self.path)
        self.assertEqual(restarted.effective, data["effective"])
        self.assertEqual(self.engine.settings, data["effective"])

    def test_patch_rejections_are_all_or_nothing(self):
        before = self.request("/api/settings")[1]
        original = self.path.read_bytes()
        for payload in ({"unknown": 1}, {"simulation": False}, {"gpio": {}},
                        {"output_active_high": {}}, {"input_pull": {}},
                        {"boost_on_c": 24, "water_alarm_seconds": 8},
                        {"rotation_seconds": True}, {"sensor_poll_seconds": "3"},
                        {"input_active_high": {"water": None}}, {"high_temp_alarm_c": 51}):
            with self.subTest(payload=payload):
                code, data = self.request("/api/settings", "PATCH", payload)
                self.assertEqual(code, 422)
                self.assertIn("detail", data)
                self.assertEqual(self.request("/api/settings")[1], before)
                self.assertEqual(self.path.read_bytes(), original)
        for raw in (b'{"water_alarm_seconds": NaN}', b'{"water_alarm_seconds": Infinity}'):
            self.assertEqual(self.request("/api/settings", "PATCH", raw=raw)[0], 422)
        self.assertEqual(self.request("/api/settings", "PATCH", [1])[0], 422)

    def test_disk_failure_returns_visible_error_without_application(self):
        before = self.request("/api/settings")[1]
        with patch("backend.config.os.replace", side_effect=OSError("disk")):
            code, data = self.request("/api/settings", "PATCH", {"water_alarm_seconds": 9})
        self.assertEqual(code, 500)
        self.assertIn("no changes applied", data["detail"])
        self.assertEqual(self.request("/api/settings")[1], before)
        self.assertEqual(self.path.read_text(), "{}")

    def test_simulation_missing_dht_and_strict_fields(self):
        code, data = self.request("/api/simulation", "POST",
                                  {"temperature_c": None, "water_level_alarm": True})
        self.assertEqual(code, 200)
        self.assertIsNone(data["sensors"]["temperature_c"])
        self.assertIsNone(data["sensor_age_s"]["temperature_c"])
        self.assertTrue(data["sensors"]["water_level_alarm"])
        self.assertEqual(data["sensors"]["humidity_pct"], 50)
        for payload in ({"extra_sensor": True}, {"failed": [False, False]},
                        {"unknown": 2}, {"door_open": None}, {"smoke_alarm": 1},
                        {"temperature_c": 51}, {"humidity_pct": -1},
                        {"temperature_c": True}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("/api/simulation", "POST", payload)[0], 422)

    def test_mode_and_removed_route(self):
        self.assertEqual(self.request("/api/mode", "POST", {"mode": "pause"})[1]["mode"], "pause")
        self.assertEqual(self.request("/api/mode", "POST", {"mode": "manual"})[1]["mode"], "manual")
        self.assertEqual(self.request("/api/mode", "POST", {"mode": "invalid"})[0], 400)
        self.assertEqual(self.request("/api/mode", "POST", {"mode": "auto", "unknown": 1})[0], 422)
        code, data = self.request("/api/reset-faults", "POST", {})
        self.assertEqual(code, 404)
        self.assertEqual(data["detail"], "Not Found")

    def test_manual_acu_commands_and_rejections(self):
        endpoint = "/api/acu/2/command"
        self.assertEqual(self.request(endpoint, "POST", {"action": "on"})[0], 409)
        self.request("/api/mode", "POST", {"mode": "manual"})
        code, data = self.request(endpoint, "POST", {"action": "on"})
        self.assertEqual(code, 200)
        self.assertTrue(data["acu_outputs"]["acu2"])
        self.assertEqual(self.request(endpoint, "POST", {"action": "off"})[0], 200)
        code, data = self.request(endpoint, "POST", {"action": "on"})
        self.assertEqual(code, 409)
        self.assertIn("restart delay", data["detail"])
        self.assertEqual(self.request("/api/acu/3/command", "POST", {"action": "off"})[0], 400)
        self.assertEqual(self.request(endpoint, "POST", {"action": "start"})[0], 400)
        self.assertEqual(self.request(endpoint, "POST", {"action": True})[0], 422)
        self.assertEqual(self.request(endpoint, "POST", {"action": "off", "unknown": 1})[0], 422)
        self.engine.fatal(RuntimeError("fatal"))
        self.assertEqual(self.request(endpoint, "POST", {"action": "off"})[0], 409)

    def test_history_survives_and_errors_are_visible(self):
        self.engine.log("test", "retained row")
        code, rows = self.request("/api/events?limit=500")
        self.assertEqual(code, 200)
        # The live control worker may append output events after the retained row.
        self.assertTrue(any(row["kind"] == "test" and row["detail"] == "retained row"
                            for row in rows))
        for row in rows:
            self.assertEqual(set(row), {"id", "ts", "kind", "detail"})
        self.assertEqual(self.request("/api/events?limit=bad")[0], 422)
        with patch.object(self.engine.event_store, "events", side_effect=OSError("history")):
            self.assertEqual(self.request("/api/events")[0], 503)

    def test_concurrent_status_and_settings_have_no_partial_state(self):
        def operation(index):
            if index % 2:
                return self.request("/api/settings", "PATCH", {
                    "water_alarm_seconds": index, "smoke_alarm_seconds": index})
            return self.request("/api/settings")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(operation, range(20)))
        for code, data in results:
            self.assertEqual(code, 200)
            self.assertEqual(data["effective"]["water_alarm_seconds"],
                             data["effective"]["smoke_alarm_seconds"])
        self.assertEqual(Configuration(self.path).effective, self.request("/api/settings")[1]["effective"])
        self.assertEqual(self.request("/api/status")[0], 200)

    def test_fatal_visible_and_mode_rejected(self):
        self.engine.fatal(RuntimeError("fatal"))
        code, data = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertIn("CONTROLLER_ERROR", data["alarms"])
        self.assertIn("restart required", data["controller_error"])
        self.assertEqual(self.request("/api/mode", "POST", {"mode": "auto"})[0], 409)

    def test_lifespan_joins_workers_and_fails_off(self):
        self.engine.simulation_update({"smoke_alarm": True, "water_level_alarm": True,
                                       "temperature_c": 35, "humidity_pct": 80})
        self.engine.tick()
        self.assertTrue(any(self.engine.io.outputs.values()))
        self.server.close()
        self.assertTrue(self.engine.closed)
        self.assertTrue(self.engine.io.closed)
        self.assertFalse(any(thread.is_alive() for thread in self.engine.threads))
        self.assertFalse(any(self.engine.io.outputs.values()))

    def test_hardware_simulation_endpoint_forbidden(self):
        config = Configuration(self.path, hardware_config())
        io = IO(config.effective, Device, Device, dht_reader=lambda: (None, None))
        engine = Engine(config, io)
        server = LiveServer(create_app(engine))
        try:
            self.assertEqual(server.request("/api/simulation", "POST", {"water_level_alarm": True})[0], 403)
            self.assertIsNone(server.request("/api/status")[1]["sensors"]["temperature_c"])
        finally:
            server.close()


class MockPinAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        raw = mapped_hardware_config()
        raw["gpio"].update(acu1=20, acu2=21)
        config = Configuration(Path(self.temp.name) / "config.json", raw)
        self.io, self.factory = mock_hardware_io(config.effective, clock=self.clock)
        self.engine = Engine(config, self.io, self.clock, EventStore(
            Path(self.temp.name) / "events.sqlite3"))
        self.addCleanup(self.engine.shutdown)
        self.engine.set_mode("manual")
        self.server = LiveServer(create_app(self.engine))
        self.addCleanup(self.server.close)

    def test_http_commands_apply_mock_levels_before_response_including_repeats(self):
        for acu, number in ((1, 20), (2, 21)):
            pin = self.factory.pin(number)
            self.assertFalse(pin.state)
            for action, level in (("off", False), ("on", True), ("off", False)):
                endpoint = f"/api/acu/{acu}/command"
                code, data = self.server.request(endpoint, "POST", {"action": action})
                self.assertEqual(code, 200)
                self.assertEqual(data["acu_outputs"][f"acu{acu}"], level)
                self.assertEqual(pin.state, level)
                timings = (self.engine.on_since[:], self.engine.off_since[:])
                history = self.engine.event_store.events(500)
                self.clock.now += 1
                pin.state = not level
                device = self.io.devices[f"acu{acu}"]
                with patch.object(device, action, wraps=getattr(device, action)) as write:
                    code, data = self.server.request(endpoint, "POST", {"action": action})
                    self.assertEqual(code, 200)
                    write.assert_called_once_with()
                self.assertEqual(pin.state, level)
                self.assertEqual(data["acu_outputs"][f"acu{acu}"], level)
                self.assertEqual((self.engine.on_since[:], self.engine.off_since[:]), timings)
                self.assertEqual(self.engine.event_store.events(500), history)
        self.assertFalse(self.factory.pin(17).state)
        self.assertFalse(self.factory.pin(27).state)
        self.clock.now += 300
        for acu in (1, 2):
            self.assertEqual(self.server.request(
                f"/api/acu/{acu}/command", "POST", {"action": "on"})[0], 200)
        self.assertTrue(self.factory.pin(20).state)
        self.assertTrue(self.factory.pin(21).state)
        self.server.close()
        self.assertFalse(self.factory.pin(20).state)
        self.assertFalse(self.factory.pin(21).state)

    def test_http_rejections_do_not_write_mock_pins(self):
        endpoint = "/api/acu/1/command"
        with patch.object(self.engine, "tick"), \
                patch.object(self.io, "write", wraps=self.io.write) as write:
            for mode in ("auto", "pause"):
                self.server.request("/api/mode", "POST", {"mode": mode})
                for action in ("on", "off"):
                    code, data = self.server.request(endpoint, "POST", {"action": action})
                    self.assertEqual(code, 409)
                    self.assertIn("MANUAL", data["detail"])
            self.server.request("/api/mode", "POST", {"mode": "manual"})
            for path, body, code in (
                (endpoint, {"action": "invalid"}, 400),
                ("/api/acu/3/command", {"action": "off"}, 400),
                (endpoint, {"action": True}, 422),
                (endpoint, {"action": "off", "unknown": 1}, 422),
            ):
                self.assertEqual(self.server.request(path, "POST", body)[0], code)
            write.assert_not_called()
            self.server.request(endpoint, "POST", {"action": "on"})
            self.server.request(endpoint, "POST", {"action": "off"})
            write.reset_mock()
            self.clock.now = 299.99
            code, data = self.server.request(endpoint, "POST", {"action": "on"})
            self.assertEqual(code, 409)
            self.assertIn("restart delay", data["detail"])
            write.assert_not_called()
            self.assertFalse(self.factory.pin(20).state)
            self.clock.now = 300
            self.assertEqual(self.server.request(endpoint, "POST", {"action": "on"})[0], 200)
            self.assertTrue(self.factory.pin(20).state)

    def test_http_failed_write_is_fatal_and_state_is_truthful(self):
        self.server.request("/api/acu/2/command", "POST", {"action": "on"})
        pin = self.factory.pin(20)
        with patch.object(pin, "_set_state", side_effect=OSError("pin write")):
            code, data = self.server.request("/api/acu/1/command", "POST", {"action": "on"})
            self.assertEqual(code, 409)
            self.assertIn("restart required", data["detail"])
            code, data = self.server.request("/api/status")
            self.assertEqual(code, 200)
            self.assertEqual(data["acu_outputs"], {"acu1": False, "acu2": False})
            self.assertFalse(pin.state)
            self.assertFalse(self.factory.pin(21).state)
            self.assertIn("CONTROLLER_ERROR", data["alarms"])
            with patch.object(self.io, "write", wraps=self.io.write) as write:
                self.assertEqual(self.server.request(
                    "/api/acu/2/command", "POST", {"action": "on"})[0], 409)
                write.assert_not_called()
