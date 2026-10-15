"""Run with python3 -B -m unittest discover -s tests -p 'test_service_control.py' -v.

All subprocess lifecycle calls use a copied installation and fake managers.
HTTP servers and unmanaged processes are confined to temporary test fixtures.
"""
import contextlib
import fcntl
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("service_control", PROJECT / "deploy/service_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
VALID = {"mode": "auto", "sensors": {}, "acu_outputs": {}, "alarm_outputs": {},
         "controller_error": None, "fatal_error": None}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acuPilot control ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "deploy").mkdir()
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / "bin").mkdir()
        (self.root / ".venv/bin/python").symlink_to(sys.executable)
        for filename in ("service_control.sh", "start_hmi.sh", "restart_hmi.sh"):
            shutil.copy(PROJECT / filename, self.root / filename)
        shutil.copy(PROJECT / "deploy/service_control.py", self.root / "deploy/service_control.py")
        for filename in ("main.py", "launch_hmi.py", "hmi.py"):
            (self.root / filename).write_text("import time; time.sleep(30)\n")
        for name in ("systemctl", "sudo", "pkcheck"):
            shutil.copy(PROJECT / "tests/service_control_fake.py", self.root / "bin" / name)
            (self.root / "bin" / name).chmod(0o755)
        self.config = {}
        self.configure()
        self.set_state("backend", "active")
        self.set_state("hmi", "active")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.env = dict(os.environ, PATH=f"{self.root / 'bin'}:{os.environ['PATH']}",
                        FAKE_MANAGER=str(self.root),
                        COOLSHIFT_BACKEND_URL=f"http://127.0.0.1:{self.port}",
                        ACUPILOT_CONTROL_COMMAND_TIMEOUT="1",
                        ACUPILOT_CONTROL_JOB_TIMEOUT="1.5",
                        ACUPILOT_CONTROL_READY_TIMEOUT="0.8",
                        ACUPILOT_CONTROL_HMI_TIMEOUT="0.12",
                        ACUPILOT_CONTROL_LOCK_TIMEOUT="0.15")

    def configure(self, **kwargs):
        self.config.update(kwargs)
        (self.root / "config.json").write_text(json.dumps(self.config))

    def set_state(self, component, active, **kwargs):
        state = dict(LoadState="loaded", ActiveState=active,
                     SubState="running" if active == "active" else "dead",
                     Result="success", ExecMainStatus="0", Job="", Environment="")
        state.update(kwargs)
        (self.root / f"{component}.json").write_text(json.dumps(state))

    def state(self, component):
        return json.loads((self.root / f"{component}.json").read_text())

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def mutations(self):
        return [(("backend" if "--system" in args else "hmi"),
                 next(arg for arg in args if arg in ("start", "stop", "restart")))
                for args in self.calls() if "-l" not in args and "--action-id" not in args
                and any(arg in ("start", "stop", "restart") for arg in args)
                and "-n" not in args]

    def invoke(self, *args, script="service_control.sh", env=None):
        return subprocess.run(["bash", str(self.root / script), *args], env=env or self.env,
                              cwd="/tmp", capture_output=True, text=True, timeout=8)

    def serve(self, payload=VALID, code=200, delay=0, deferred=False, raw=None):
        fixture = self
        stop = threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(delay)
                body = raw if raw is not None else json.dumps(payload).encode()
                self.send_response(code)
                if code == 302:
                    self.send_header("Location", "/elsewhere")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler,
                                                bind_and_activate=False)
        server.daemon_threads = True
        def run():
            if deferred:
                while not stop.wait(0.01):
                    try:
                        if fixture.state("backend")["ActiveState"] == "active":
                            break
                    except (ValueError, FileNotFoundError):
                        pass
            if stop.is_set():
                return
            server.server_bind()
            server.server_activate()
            server.serve_forever(poll_interval=0.01)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        if not deferred:
            deadline = time.monotonic() + 1
            while not server.socket.getsockname()[1] and time.monotonic() < deadline:
                time.sleep(0.005)
        def cleanup():
            stop.set()
            if server.socket.getsockname()[1]:
                server.shutdown()
            thread.join(2)
            server.server_close()
        self.addCleanup(cleanup)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LifecycleTests(Fixture):
    def test_strict_parsing_before_manager_access(self):
        for args in ((), ("invalid",), ("start", "bad"), ("stop", "both", "extra"),
                     ("restart", "--dev"), ("status", "--help")):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_start_both_order_and_repeated_start_is_idempotent(self):
        self.set_state("backend", "inactive")
        self.set_state("hmi", "inactive")
        self.serve(deferred=True)
        self.assert_success(self.invoke("start"))
        self.assertEqual(self.mutations(), [("backend", "start"), ("hmi", "start")])
        self.assert_success(self.invoke("start", "both"))
        self.assertEqual(len(self.mutations()), 2)

    def test_restart_waits_for_each_job_and_keeps_scope(self):
        self.configure(polls=3)
        self.serve()
        self.assert_success(self.invoke("restart"))
        self.assertEqual(self.mutations(), [("hmi", "stop"), ("backend", "restart"), ("hmi", "start")])
        for args in self.calls():
            if "--system" in args:
                self.assertNotIn("coolshift-hmi.service", args)
            if "--user" in args and "show-environment" not in args and "is-active" not in args:
                self.assertIn("coolshift-hmi.service", args)

    def test_stop_order_and_idempotence_without_display(self):
        self.configure(session=False, environment="")
        self.assert_success(self.invoke("stop"))
        self.assert_success(self.invoke("stop", "both"))
        self.assertEqual(self.mutations(), [("hmi", "stop"), ("backend", "stop")])

    def test_hmi_only_restart_never_contacts_backend(self):
        self.assert_success(self.invoke("restart", "hmi"))
        self.assertEqual(self.mutations(), [("hmi", "restart")])
        self.assertTrue(all("--system" not in args and "--action-id" not in args for args in self.calls()))

    def test_backend_only_works_without_desktop(self):
        self.configure(session=False, environment="", disconnected="hmi")
        self.serve()
        self.assert_success(self.invoke("restart", "backend"))
        self.assertEqual(self.mutations(), [("backend", "restart")])

    def test_denied_authorization_before_coordinated_stops(self):
        self.configure(polkit=False, sudo=False)
        result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertIn("authorization unavailable before any stops", result.stderr)
        self.assertEqual(self.mutations(), [])
        probe = next(args for args in self.calls() if "-l" in args)
        self.assertEqual(probe[:3], ["-n", "-l", "--"])
        self.assertIn("--system", probe)
        self.assertIn("--no-block", probe)
        self.assertIn("restart", probe)
        self.assertNotIn("true", probe)

    def test_narrow_sudo_permission_probed_before_hmi_stop(self):
        self.configure(polkit=False, sudo=True)
        self.serve()
        self.assert_success(self.invoke("restart"))
        calls = self.calls()
        probe_index = next(i for i, args in enumerate(calls) if "-l" in args)
        stop_index = next(i for i, args in enumerate(calls) if "stop" in args)
        self.assertLess(probe_index, stop_index)
        probe = calls[probe_index][3:]
        execution = next(args[2:] for args in calls if args[:2] == ["-n", "--"])
        self.assertEqual(probe, execution)

    def test_hmi_preflight_failure_does_not_disrupt_backend(self):
        for kwargs in (dict(session=False), dict(environment=""),
                       dict(disconnected="hmi")):
            with self.subTest(kwargs=kwargs):
                self.config = {}
                self.configure(**kwargs)
                self.assertEqual(self.invoke("restart").returncode, 1)
                self.assertEqual(self.mutations(), [])

    def test_missing_masked_and_pending_units_refused(self):
        for kwargs in (dict(LoadState="not-found"), dict(LoadState="masked"), dict(Job="7 /job/7")):
            self.set_state("hmi", "active", **kwargs)
            self.assertEqual(self.invoke("restart").returncode, 1)
            self.assertEqual(self.mutations(), [])

    def test_missing_prerequisite_refused(self):
        (self.root / "launch_hmi.py").unlink()
        self.assertEqual(self.invoke("restart").returncode, 1)
        self.assertEqual(self.mutations(), [])

    def test_lock_timeout_no_manager_calls(self):
        with (self.root / ".service_control.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertIn("lock timeout", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_status_read_only_ignores_lock_and_authorization(self):
        self.configure(polkit=False, sudo=False)
        self.serve()
        with (self.root / ".service_control.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.invoke("status")
        self.assert_success(result)
        self.assertIn("scope=system", result.stdout)
        self.assertIn("scope=user", result.stdout)
        self.assertIn("readiness: ready", result.stdout)
        self.assertEqual(self.mutations(), [])
        self.assertTrue(all("-l" not in args and "--action-id" not in args for args in self.calls()))

    def test_unowned_listener_refused_without_mutation(self):
        self.set_state("backend", "inactive")
        self.serve()
        result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertIn("port", result.stderr)
        self.assertIn("Nothing was killed", result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_manual_hmi_process_refused_and_not_killed(self):
        process = subprocess.Popen([sys.executable, str(self.root / "hmi.py")], cwd="/tmp")
        self.addCleanup(lambda: process.wait(timeout=2))
        self.addCleanup(process.terminate)
        result = self.invoke("restart", "hmi")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"PID {process.pid}", result.stderr)
        self.assertIsNone(process.poll())
        self.assertEqual(self.mutations(), [])

    def test_failed_backend_leaves_hmi_stopped_with_diagnostics(self):
        self.configure(fail="backend:restart")
        result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.state("hmi")["ActiveState"], "inactive")
        self.assertEqual(self.mutations(), [("hmi", "stop"), ("backend", "restart")])
        self.assertIn("partial state", result.stderr)
        self.assertIn("journalctl --system", result.stderr)

    def test_failed_hmi_leaves_healthy_backend(self):
        self.configure(fail="hmi:start")
        self.serve()
        result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.state("backend")["ActiveState"], "active")
        self.assertIn("journalctl --user", result.stderr)

    def test_job_deadline_does_not_start_backend_after_stuck_hmi_stop(self):
        self.configure(polls=1000)
        env = dict(self.env, ACUPILOT_CONTROL_JOB_TIMEOUT="0.25")
        result = self.invoke("restart", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("job deadline exceeded", result.stderr)
        self.assertEqual(self.mutations(), [("hmi", "stop")])

    def test_preflight_command_timeout(self):
        self.configure(hang=True)
        result = self.invoke("restart", env=dict(self.env, ACUPILOT_CONTROL_COMMAND_TIMEOUT="0.15"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("bounded command failed", result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_wrappers_forward_defaults_components_exit_and_reject_flags(self):
        self.serve()
        self.assert_success(self.invoke(script="start_hmi.sh"))
        self.assert_success(self.invoke("hmi", script="restart_hmi.sh"))
        self.assertEqual(self.mutations(), [("hmi", "restart")])
        result = self.invoke("--dev", script="start_hmi.sh")
        self.assertEqual(result.returncode, 2)
        self.assertIn("python launch_hmi.py --dev", result.stderr)

    def test_invalid_timeout_and_remote_endpoint_refused(self):
        for env in (dict(self.env, ACUPILOT_CONTROL_JOB_TIMEOUT="nan"),
                    dict(self.env, COOLSHIFT_BACKEND_URL="http://example.com:8000"),
                    dict(self.env, COOLSHIFT_BACKEND_URL="http://127.0.0.1:8000/api")):
            self.assertEqual(self.invoke("restart", env=env).returncode, 1)
        self.assertEqual(self.calls(), [])


class ReadinessTests(Fixture):
    def test_invalid_and_fatal_http_fail_coordinated_restart(self):
        self.serve(payload=dict(VALID, fatal_error="latched"))
        result = self.invoke("restart")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fatal controller state", result.stderr)
        self.assertEqual(self.state("hmi")["ActiveState"], "inactive")
        self.assertEqual(self.mutations(), [("hmi", "stop"), ("backend", "restart")])

    def test_invalid_json_status_not_ready(self):
        self.serve(raw=b"not JSON")
        self.assertEqual(self.invoke("status", "backend").returncode, 1)

    def test_empty_schema_status_not_ready(self):
        self.serve(payload={})
        result = self.invoke("status", "backend")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid acuPilot API status schema", result.stdout)

    def test_http_error_status_not_ready(self):
        self.serve(code=503)
        self.assertEqual(self.invoke("status", "backend").returncode, 1)

    def test_redirect_status_not_ready(self):
        self.serve(code=302)
        self.assertEqual(self.invoke("status", "backend").returncode, 1)

    def test_stopped_unit_not_ready_despite_valid_listener(self):
        self.serve()
        self.set_state("backend", "inactive")
        result = self.invoke("status", "backend")
        self.assertEqual(result.returncode, 1)
        self.assertIn("HTTP is not ownership", result.stdout)

    def test_slow_http_has_wall_clock_bound(self):
        self.serve(delay=2)
        start = time.monotonic()
        result = self.invoke("restart", env=dict(self.env, ACUPILOT_CONTROL_READY_TIMEOUT="0.3",
                                               ACUPILOT_CONTROL_COMMAND_TIMEOUT="0.5"))
        self.assertEqual(result.returncode, 1)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(self.state("hmi")["ActiveState"], "inactive")


class SmallUnitTests(unittest.TestCase):
    def test_restart_job_budget_covers_both_unit_budgets(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertGreater(control.budget("JOB", 75), 30 + 30)

    def test_root_never_addresses_root_user_manager(self):
        with patch.object(control.os, "geteuid", return_value=0), \
                patch.object(control.Controller, "state") as state, \
                patch.object(control.Controller, "conflicts"), \
                patch.object(control.Controller, "locked", return_value=contextlib.nullcontext()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(control.main(["restart", "hmi"]), 1)
            self.assertEqual(control.main(["status", "hmi"]), 1)
            state.assert_not_called()

    def test_immediate_hmi_failure_observation(self):
        controller = control.Controller("start", "hmi")
        controller.timeouts["HMI"] = 0.01
        with patch.object(controller, "state", side_effect=[
                dict(ActiveState="active", SubState="running"),
                dict(ActiveState="failed", SubState="failed")]):
            with self.assertRaisesRegex(control.ControlError, "immediate"):
                controller.start("hmi")


if __name__ == "__main__":
    unittest.main()
