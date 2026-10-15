"""Exercise uvicorn signal handling and actual lifespan fail-OFF in a child."""
import json
import signal
import subprocess
import sys
import unittest
from pathlib import Path


CHILD = """
import json, socket, tempfile, threading, time
from pathlib import Path
import uvicorn
from backend.api import create_app
from backend.config import Configuration
from backend.engine import Engine

with tempfile.TemporaryDirectory() as directory:
    engine = Engine(Configuration(Path(directory) / "config.json", {}))
    engine.simulation_update({"temperature_c":35, "humidity_pct":80,
                              "smoke_alarm":True, "water_level_alarm":True})
    engine.tick()
    session = engine.start_output_test()
    engine.command_output_test(session["session_id"], "door", True)
    original_shutdown = engine.shutdown
    def shutdown():
        original_shutdown()
        print(json.dumps({"closed":engine.closed, "outputs":engine.io.outputs,
                          "output_test":engine.status()["output_test"],
                          "workers_alive":any(t.is_alive() for t in engine.threads)}), flush=True)
    engine.shutdown = shutdown
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(create_app(engine), log_level="critical"))
    def ready():
        while not server.started:
            time.sleep(0.01)
        print("READY", flush=True)
    threading.Thread(target=ready, daemon=True).start()
    server.run(sockets=[listener])
"""


class SignalTests(unittest.TestCase):
    def test_sigint_sigterm_fail_off_and_join(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                process = subprocess.Popen([sys.executable, "-u", "-c", CHILD],
                                           cwd=Path(__file__).resolve().parents[2],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    import selectors
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=10), "child readiness timeout")
                    self.assertEqual(process.stdout.readline().strip(), "READY")
                    process.send_signal(sig)
                    stdout, stderr = process.communicate(timeout=10)
                    result = json.loads(stdout.strip())
                    self.assertTrue(result["closed"])
                    self.assertEqual(len(result["outputs"]), 7)
                    self.assertIn("door", result["outputs"])
                    self.assertFalse(any(result["outputs"].values()))
                    self.assertFalse(result["workers_alive"])
                    self.assertFalse(result["output_test"]["active"])
                    self.assertEqual(result["output_test"]["restoration_outcome"], "cancelled")
                    self.assertNotIn("RuntimeError", stderr)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
                    process.stdout.close()
                    process.stderr.close()
