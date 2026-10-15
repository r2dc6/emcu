"""Installation-relative diagnostic logging for acuPilot."""
import atexit
import logging
import queue
import sys
from pathlib import Path
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

APP_BASE = Path(__file__).resolve().parent
LOG_DIR = APP_BASE / "Logs"
LOG_FILE = LOG_DIR / "coolshift_hmi.log"
STARTUP_LOG_FILE = LOG_DIR / "hmi_startup.log"
BACKEND_LOG_FILE = LOG_DIR / "coolshift_backend.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def warn(message):
    try:
        sys.stderr.write(f"acuPilot logging warning: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


class SafeRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        if not getattr(self, "_warned", False):
            self._warned = True
            warn(f"cannot write {self.baseFilename}; console output remains available")


def file_handler(path, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = SafeRotatingHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT))
        handler._acupilot_owned = True
        return handler
    except OSError as exc:
        warn(f"cannot open {path}: {exc}; using console only")
        return None


def close_owned(logger):
    for handler in list(logger.handlers):
        if getattr(handler, "_acupilot_owned", False):
            logger.removeHandler(handler)
            handler.close()


def setup_hmi(path=LOG_FILE, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
    logger = logging.getLogger("coolshift_hmi")
    close_owned(logger)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = file_handler(path, max_bytes, backups)
    if handler:
        logger.addHandler(handler)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    console._acupilot_owned = True
    logger.addHandler(console)
    return logger


class DroppingQueueHandler(QueueHandler):
    """Never block the controller on disk or a full diagnostics queue."""
    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def handleError(self, record):
        self.dropped += 1

    dropped = 0


class DrainingListener(QueueListener):
    def enqueue_sentinel(self):
        # Producers are detached before shutdown; drain even a full queue.
        self.queue.put(self._sentinel)


_backend_cleanup = None


def setup_backend(path=BACKEND_LOG_FILE, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
    global _backend_cleanup
    if _backend_cleanup:
        _backend_cleanup()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    attached = []
    if not root.handlers:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(console)
        attached.append((root, console))
    handler = file_handler(path, max_bytes, backups)
    listener = None
    if handler:
        sink = DroppingQueueHandler(queue.Queue(maxsize=1024))
        sink._acupilot_owned = True
        listener = DrainingListener(sink.queue, handler)
        listener.start()
        root.addHandler(sink)
        attached.append((root, sink))
        # Attach only where propagation to root is blocked by Uvicorn config.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            ancestor = logger
            reaches_root = True
            already_attached = False
            while ancestor is not root:
                if sink in ancestor.handlers:
                    already_attached = True
                    break
                if not ancestor.propagate:
                    reaches_root = False
                    break
                ancestor = ancestor.parent
            if not reaches_root and not already_attached:
                logger.addHandler(sink)
                attached.append((logger, sink))

    closed = False

    def cleanup():
        nonlocal closed
        if closed:
            return
        closed = True
        for logger, owned in attached:
            logger.removeHandler(owned)
        if listener:
            listener.stop()
        for owned in {entry[1] for entry in attached}:
            owned.close()
        if handler:
            handler.close()

    _backend_cleanup = cleanup
    atexit.register(cleanup)
    return cleanup
