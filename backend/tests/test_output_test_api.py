import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import create_app
from backend.config import Configuration, OUTPUTS
from backend.engine import Engine
from backend.io import IO
from test_api import LiveServer
from test_io import Clock


class OutputTestAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.path.write_text("{}")
        self.configuration = Configuration(self.path)
        self.clock = Clock()
        self.io = IO(self.configuration.effective, clock=self.clock)
        self.engine = Engine(self.configuration, self.io, self.clock)
        # Live HTTP validation, with deterministic fake-clock control ticks.
        with patch.object(self.engine, "start"):
            self.server = LiveServer(create_app(self.engine))
        self.addCleanup(self.server.close)

    def request(self, action, payload=None, raw=None):
        return self.server.request("/api/output-test/" + action, "POST", payload, raw=raw)

    def start(self):
        code, reply = self.request("start")
        self.assertEqual(code, 200)
        return reply

    def assert_status(self, reply):
        self.assertEqual(set(reply), set(self.engine.status()))
        self.assertEqual(reply["acu_outputs"], self.engine.status()["acu_outputs"])
        self.assertEqual(reply["alarm_outputs"], self.engine.status()["alarm_outputs"])
        self.assertEqual(set(reply["output_test"]), {
            "active", "original_states", "lease_remaining_s",
            "restoration_outcome", "restoration_error",
        })
        self.assertNotIn("session_id", json.dumps(reply))

    def test_exact_contract_empty_body_and_authoritative_mutation_replies(self):
        snapshot = dict(zip(OUTPUTS, (True, False, True, False, True, False, True)))
        for name, value in snapshot.items():
            self.engine.set_output(name, value, self.clock())
        for payload in (None, {}):
            reply = self.start() if payload is None else self.request("start", payload)[1]
            self.assertEqual(set(reply), {"session_id", "original_states", "lease_seconds", "status"})
            self.assertEqual(reply["lease_seconds"], 10)
            self.assertEqual(reply["original_states"], snapshot)
            self.assert_status(reply["status"])
            self.assertNotIn(reply["session_id"], json.dumps(reply["status"]))
            session_id = reply["session_id"]
            for channel in OUTPUTS:
                code, status = self.request("output", {
                    "session_id": session_id, "channel": channel, "value": not snapshot[channel]})
                self.assertEqual(code, 200)
                self.assert_status(status)
                states = {**status["acu_outputs"], **status["alarm_outputs"]}
                self.assertEqual(states[channel], not snapshot[channel])
            code, status = self.request("heartbeat", {"session_id": session_id})
            self.assertEqual(code, 200)
            self.assert_status(status)
            code, status = self.request("end", {"session_id": session_id})
            self.assertEqual(code, 200)
            self.assert_status(status)
            self.assertEqual({**status["acu_outputs"], **status["alarm_outputs"]}, snapshot)
            self.assertEqual(status["output_test"], {
                "active": False, "original_states": None, "lease_remaining_s": 0,
                "restoration_outcome": "restored", "restoration_error": None,
            })
        self.assertEqual(self.path.read_text(), "{}")

    def test_start_rejects_every_nonempty_or_malformed_body_without_writes(self):
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            for raw in (b'{"extra":1}', b'null', b'[]', b'"text"', b'false',
                        b'1', b'{', b'{"session_id":"wrong"}'):
                with self.subTest(raw=raw):
                    code, data = self.request("start", raw=raw)
                    self.assertEqual(code, 422)
                    self.assertIn("detail", data)
                    self.assertFalse(self.engine.status()["output_test"]["active"])
            write.assert_not_called()

    def test_strict_mutation_payloads_do_not_write_or_renew(self):
        session_id = self.start()["session_id"]
        self.clock.now = 9
        valid = {"session_id": session_id, "channel": "acu1", "value": True}
        bad_outputs = [
            {}, [], None, {**valid, "extra": 1},
            {**valid, "channel": "unknown"}, {**valid, "channel": "dht"},
            {**valid, "channel": "ACU 1"}, {**valid, "channel": 1},
            {"session_id": session_id, "value": True},
            {"session_id": session_id, "channel": "acu1"},
        ]
        for value in (0, 1, "true", "false", None, [], {}):
            bad_outputs.append({**valid, "value": value})
        for identifier in ("", None, 1, True, [], {}):
            bad_outputs.append({**valid, "session_id": identifier})
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            for payload in bad_outputs:
                with self.subTest(payload=payload):
                    self.assertEqual(self.request("output", payload)[0], 422)
            for action in ("heartbeat", "end"):
                for payload in ({}, [], None, {"session_id": ""},
                                {"session_id": 1}, {"session_id": None},
                                {"session_id": session_id, "extra": 1},
                                {"session_id": session_id, "channel": "acu1"}):
                    self.assertEqual(self.request(action, payload)[0], 422)
            for action in ("output", "heartbeat", "end"):
                self.assertEqual(self.request(action, raw=b'{')[0], 422)
            write.assert_not_called()
        self.assertEqual(self.engine.status()["output_test"]["lease_remaining_s"], 1)

    def test_concurrent_start_has_exactly_one_owner(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: self.request("start", {}), range(16)))
        self.assertEqual(sum(code == 200 for code, _ in replies), 1)
        self.assertEqual(sum(code == 409 for code, _ in replies), 15)
        owner = next(data for code, data in replies if code == 200)
        self.assertEqual(self.engine.output_test["session_id"], owner["session_id"])
        self.assertEqual(self.engine.output_test["original_states"], owner["original_states"])

    def test_wrong_expired_ids_and_old_end_retries_cannot_override_new_owner(self):
        old_id = self.start()["session_id"]
        for action, body in (
            ("output", {"session_id": "wrong", "channel": "acu1", "value": True}),
            ("heartbeat", {"session_id": "wrong"}),
            ("end", {"session_id": "wrong"}),
        ):
            self.assertEqual(self.request(action, body)[0], 409)
        self.clock.now = 10
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            for action, body in (
                ("output", {"session_id": old_id, "channel": "acu1", "value": True}),
                ("heartbeat", {"session_id": old_id}),
                ("end", {"session_id": old_id}),
            ):
                self.assertEqual(self.request(action, body)[0], 409)
            self.assertEqual(self.request("start")[0], 409)
            write.assert_not_called()
        self.engine.tick()
        self.assertEqual(self.request("end", {"session_id": old_id})[0], 200)
        newer_id = self.start()["session_id"]
        self.request("output", {"session_id": newer_id, "channel": "water", "value": True})
        with patch.object(self.io, "write", wraps=self.io.write) as write:
            code, status = self.request("end", {"session_id": old_id})
            self.assertEqual(code, 200)
            self.assertTrue(status["output_test"]["active"])
            self.assertTrue(status["alarm_outputs"]["water"])
            write.assert_not_called()
        self.assertEqual(self.request("heartbeat", {"session_id": old_id})[0], 409)
        self.assertEqual(self.request("output", {
            "session_id": old_id, "channel": "water", "value": False})[0], 409)

    def test_existing_endpoints_conflict_without_persistence_then_resume(self):
        self.server.request("/api/mode", "POST", {"mode": "manual"})
        session_id = self.start()["session_id"]
        before = self.server.request("/api/settings")[1]
        for endpoint, method, body in (
            ("/api/settings", "PATCH", {"smoke_alarm_seconds": 8}),
            ("/api/mode", "POST", {"mode": "pause"}),
            ("/api/acu/1/command", "POST", {"action": "on"}),
        ):
            code, reply = self.server.request(endpoint, method, body)
            self.assertEqual(code, 409)
            self.assertIn("testing active", reply["detail"])
        self.assertEqual(self.server.request("/api/settings")[1], before)
        self.assertEqual(self.path.read_text(), "{}")
        self.assertEqual(self.server.request("/api/simulation", "POST", {"smoke_alarm": True})[0], 200)
        self.engine.tick()
        self.assertIn("SMOKE_ALARM", self.engine.alarms)
        self.request("end", {"session_id": session_id})
        self.assertEqual(self.server.request("/api/settings", "PATCH", {"smoke_alarm_seconds": 8})[0], 200)
        self.assertEqual(self.server.request("/api/acu/1/command", "POST", {"action": "on"})[0], 200)
        self.assertEqual(self.server.request("/api/mode", "POST", {"mode": "pause"})[0], 200)

    def test_write_failures_are_500_and_status_reports_failure(self):
        session_id = self.start()["session_id"]
        original = self.io.write

        def write(name, value):
            if name == "water":
                raise OSError("relay write")
            original(name, value)

        with patch.object(self.io, "write", side_effect=write):
            code, reply = self.request("output", {
                "session_id": session_id, "channel": "water", "value": True})
            self.assertEqual(code, 500)
            self.assertIn("failed", reply["detail"])
            status = self.server.request("/api/status")[1]
            self.assert_status(status)
            self.assertEqual(status["output_test"]["restoration_outcome"], "failed")
            self.assertIn("water", status["output_test"]["restoration_error"])
            self.assertIn("CONTROLLER_ERROR", status["alarms"])
            self.assertEqual(self.request("start")[0], 409)

    def test_restore_failure_and_retries_remain_explicit_errors(self):
        session_id = self.start()["session_id"]
        with patch.object(self.io, "write", side_effect=OSError("restore relay")) as write:
            self.assertEqual(self.request("end", {"session_id": session_id})[0], 500)
            self.assertEqual(write.call_count, 2 * len(OUTPUTS))
            self.assertEqual(self.request("end", {"session_id": session_id})[0], 500)
            self.assertEqual(write.call_count, 2 * len(OUTPUTS))
        self.assertEqual(self.engine.status()["output_test"]["restoration_outcome"], "failed")

    def test_stopped_fatal_closed_start_and_mutations_rejected(self):
        session_id = self.start()["session_id"]
        self.engine.stop_event.set()
        for action, body in (
            ("start", {}),
            ("heartbeat", {"session_id": session_id}),
            ("output", {"session_id": session_id, "channel": "acu1", "value": True}),
            ("end", {"session_id": session_id}),
        ):
            self.assertEqual(self.request(action, body)[0], 409)
        self.engine.fatal(RuntimeError("fatal"))
        self.assertEqual(self.request("start")[0], 409)
        self.engine.shutdown()
        self.assertEqual(self.request("start")[0], 409)
        self.assertFalse(self.server.request("/api/status")[1]["output_test"]["active"])
