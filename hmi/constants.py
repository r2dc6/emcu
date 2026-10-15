from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from log_config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUPS

APP_BASE = Path(__file__).resolve().parent.parent
APP_NAME = "acuPilot"
SCREEN_W = 800
SCREEN_H = 480
CONTENT_H = SCREEN_H - 56 - 64
MIN_TOUCH = 48
POLL_INTERVAL_MS = 1000
STALE_SENSOR_SECONDS = 30
BACKEND_URL_DEFAULT = "http://127.0.0.1:8000"
BACKEND_URL = os.environ.get("COOLSHIFT_BACKEND_URL", BACKEND_URL_DEFAULT)
REQUEST_TIMEOUT_MS = 3000
HMI_VERSION = "0.1.0"
CONFIG_FILE = APP_BASE / "config.json"
DEFAULT_CONFIG: Dict[str, float] = {
    "rotation_seconds": 21600,
    "handover_overlap_seconds": 15,
    "min_off_seconds": 300,
    "boost_on_c": 27.0,
    "boost_off_c": 25.0,
    "high_temp_alarm_c": 30.0,
    "high_humidity_alarm_pct": 65.0,
    "door_alarm_seconds": 3,
    "water_alarm_seconds": 0,
    "smoke_alarm_seconds": 0,
    "temperature_alarm_seconds": 0,
    "humidity_alarm_seconds": 0,
    "sensor_stale_seconds": 30,
    "sensor_poll_seconds": 3,
    "control_tick_seconds": 1,
    "input_active_high": {"door": False, "water": True, "smoke": True},
}


def load_config_defaults() -> Dict[str, float]:
    # Display fallback only; editable settings must come from the backend.
    return {**DEFAULT_CONFIG, "input_active_high": dict(DEFAULT_CONFIG["input_active_high"])}


PAGES = [
    ("Dashboard", "dashboard"),
    ("Control", "control"),
    ("Sensors", "sensors"),
    ("Alarms", "alarms"),
    ("Logs", "logs"),
    ("Settings", "settings"),
    ("System", "system"),
]

ALARM_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "HIGH_TEMPERATURE": {"severity": "critical", "description": "Room temperature above high-temperature alarm threshold."},
    "HIGH_HUMIDITY": {"severity": "warning", "description": "Room humidity above high-humidity alarm threshold."},
    "SENSOR_STALE": {"severity": "warning", "description": "DHT11 sensor readings are stale or unavailable."},
    "DOOR_OPEN": {"severity": "warning", "description": "Door contact has been open beyond the warning delay."},
    "SMOKE_ALARM": {"severity": "critical", "description": "Smoke detector active — verify conditions immediately."},
    "WATER_LEVEL_ALARM": {"severity": "critical", "description": "High-water detector active. Verify water level."},
    "CONTROLLER_ERROR": {"severity": "critical", "description": "Controller stopped after an error. Backend restart required; relay commands do not confirm physical operation."},
    "BACKEND_OFFLINE": {"severity": "critical", "description": "Backend server unreachable — displayed values may be stale."},
}

EVENT_KIND_ACU = {"output", "rotation", "failover", "fault", "fault_reset", "mode"}
EVENT_KIND_ALARM = {"alarm", "alarm_clear", "fault"}
EVENT_KIND_SYSTEM = {"mode", "engine_error", "simulation", "fault_reset", "rotation", "failover"}

MIN_SAFE_RESTART_DELAY_SECONDS = 3
MIN_ROTATION_HOURS = 0.5
