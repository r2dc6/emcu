from pathlib import Path
import logging
from log_config import setup_backend

_close_logging = setup_backend()

try:
    from backend.api import create_app
    from backend.config import Configuration
    from backend.engine import Engine, EventStore

    BASE = Path(__file__).resolve().parent
    DB = BASE / "coolshift.sqlite3"
    configuration = Configuration(BASE / "config.json")
    CFG = configuration.effective
    engine = Engine(configuration, event_store=EventStore(DB))
    app = create_app(engine)
except Exception:
    logging.getLogger("acuPilot.backend").exception("acuPilot backend initialization failed")
    _close_logging()
    raise
