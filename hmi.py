from __future__ import annotations

import sys
import os
import signal
import logging
import argparse
import platform
from log_config import setup_hmi, close_owned


_shutdown_requested = False
_shutdown_signal = None


def setup_logging(LOG_FILE, LOG_MAX_BYTES, LOG_BACKUPS) -> logging.Logger:
    return setup_hmi(LOG_FILE, LOG_MAX_BYTES, LOG_BACKUPS)


def install_signal_handlers(app, logger) -> None:
    global _shutdown_requested, _shutdown_signal
    _shutdown_requested = False
    _shutdown_signal = None

    def handler(signum, frame):
        global _shutdown_requested, _shutdown_signal
        # Avoid logging or Qt calls while a signal interrupts another operation.
        _shutdown_signal = signum
        _shutdown_requested = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    from PySide6.QtCore import QTimer

    def poll_shutdown():
        if _shutdown_requested:
            poller.stop()
            logger.info("HMI shutting down (received %s)", signal.Signals(_shutdown_signal).name)
            QTimer.singleShot(0, app.quit)

    poller = QTimer(app)
    poller.timeout.connect(poll_shutdown)
    poller.start(500)


def main() -> int:
    from hmi.constants import APP_NAME

    parser = argparse.ArgumentParser(description=f"{APP_NAME} HMI")
    parser.add_argument(
        "--dev",
        action="store_true",
        default=False,
        help="Development mode (windowed instead of kiosk fullscreen)",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="Override backend URL (sets COOLSHIFT_BACKEND_URL env var)",
    )
    args = parser.parse_args()

    dev_mode = args.dev or (os.environ.get("COOLSHIFT_DEV", "0") == "1")

    if args.backend_url:
        os.environ["COOLSHIFT_BACKEND_URL"] = args.backend_url
        # Constants were loaded for CLI branding before parsing the override.
        from hmi import constants
        constants.BACKEND_URL = args.backend_url

    from hmi.constants import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUPS
    logger = setup_logging(LOG_FILE, LOG_MAX_BYTES, LOG_BACKUPS)
    try:
        return run_gui(args, dev_mode, APP_NAME, logger)
    except Exception:
        logger.exception("acuPilot HMI startup or runtime failure")
        raise
    finally:
        close_owned(logger)


def run_gui(args, dev_mode, APP_NAME, logger) -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer

    from hmi.theme import set_app_fonts
    from hmi.main_window import CoolShiftHMI
    from hmi.constants import (
        LOG_FILE,
        LOG_MAX_BYTES,
        LOG_BACKUPS,
        HMI_VERSION,
    )

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} HMI")
    app.setApplicationDisplayName(f"{APP_NAME} HMI")
    # Qt 6 enables high-DPI scaling by default.

    logger.info(
        f"{APP_NAME} HMI v{HMI_VERSION} starting "
        f"(dev={dev_mode}, platform={platform.platform()}). "
        f"Backend URL from env: {os.environ.get('COOLSHIFT_BACKEND_URL', '<default>')}"
    )

    set_app_fonts(app)

    win = CoolShiftHMI(dev_mode=dev_mode)
    def shutdown():
        win.shutdown()
        app.closeAllWindows()
        for timer in app.findChildren(QTimer):
            timer.stop()
        logger.info("HMI shutting down")

    app.aboutToQuit.connect(shutdown)
    install_signal_handlers(app, logger)
    win.start()

    logger.info("HMI event loop starting")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
