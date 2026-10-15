"""Capture Python and native HMI output without unbounded startup logs."""
import codecs
import logging
import os
import selectors
import signal
import subprocess
import sys
import time

from log_config import APP_BASE, STARTUP_LOG_FILE, file_handler, warn


def run_child(command, log_path=STARTUP_LOG_FILE, cwd=APP_BASE, env=None,
              stop_timeout=8):
    handler = file_handler(log_path)
    logger = logging.Logger("acuPilot.startup", logging.INFO)
    if handler:
        logger.addHandler(handler)
    child = None
    requested = None
    deadline = None
    previous = {}

    def forward(signum, frame):
        nonlocal requested, deadline
        requested = signum
        if deadline is None:
            deadline = time.monotonic() + stop_timeout
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, forward)
        child = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True)
        if requested is not None:
            forward(requested, None)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map() or child.poll() is None:
                if deadline is not None and time.monotonic() >= deadline:
                    if child.poll() is None:
                        warn("HMI shutdown timed out; killing only the HMI child")
                        child.kill()
                    deadline = None
                for key, _ in selector.select(timeout=0.1):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        text = decoder.decode(b"", final=True)
                    else:
                        text = decoder.decode(data)
                    if text:
                        for line in text.splitlines():
                            logger.info(line)
                        try:
                            sys.stderr.write(text)
                            sys.stderr.flush()
                        except (OSError, ValueError):
                            pass
        code = child.wait()
        return code if code >= 0 else 128 - code
    except Exception:
        logger.exception("acuPilot HMI launcher failed")
        raise
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=stop_timeout)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            child.stdout.close()
        for sig, old in previous.items():
            signal.signal(sig, old)
        if handler:
            handler.close()


if __name__ == "__main__":
    sys.exit(run_child([sys.executable, str(APP_BASE / "hmi.py"), *sys.argv[1:]]))
