"""Validated installation configuration and atomic runtime persistence."""
import copy
import json
import math
import os
import tempfile
from pathlib import Path

# Logical channels map to configuration keys, not BCM pin numbers.
INPUT_GPIO_KEYS = {
    "door": "door",
    "water": "water",
    "smoke": "smoke",
}
OUTPUT_GPIO_KEYS = {
    "acu1": "acu1",
    "acu2": "acu2",
    "water": "alarm_water",
    "smoke": "alarm_smoke",
    "temperature": "alarm_temperature",
    "humidity": "alarm_humidity",
    "door": "alarm_door",
}
ACU_SECONDARY_GPIO_KEYS = {
    "acu1": "acu1_2",
    "acu2": "acu2_2",
}
SENSOR_GPIO_KEYS = {
    "dht": "dht",
}
INPUTS = tuple(INPUT_GPIO_KEYS)
OUTPUTS = tuple(OUTPUT_GPIO_KEYS)
RESTART_REQUIRED = ("simulation", "gpio", "output_active_high", "input_pull")
DEFAULTS = {
    "simulation": False,
    # Assign BCM numbers here; None means unassigned.
    # Installation settings in config.json override these defaults.
    "gpio": {
        # ACU relay outputs
        "acu1": 16,
        "acu1_2": 11,
        "acu2": 9,
        "acu2_2": 10,
        # Digital inputs
        "door": 24,
        "water": 23,
        "smoke": 25,
        # DHT11 sensor data
        "dht": 4,
        # Alarm relay outputs
        "alarm_water": 26,       #Relay 1
        "alarm_smoke": 19,       #Relay 2
        "alarm_temperature": 13, #Relay 3
        "alarm_humidity": 6,     #Relay 4
        "alarm_door": 0,         #Relay 5
    },
    "output_active_high": {key: True for key in OUTPUTS},
    "input_active_high": {"door": False, "water": True, "smoke": True},
    "input_pull": {key: "up" for key in INPUTS},
    "rotation_seconds": 21600, "handover_overlap_seconds": 15,
    "min_off_seconds": 300, "boost_on_c": 27, "boost_off_c": 25,
    "high_temp_alarm_c": 30, "high_humidity_alarm_pct": 65,
    "door_alarm_seconds": 3, "water_alarm_seconds": 0,
    "smoke_alarm_seconds": 0, "temperature_alarm_seconds": 0,
    "humidity_alarm_seconds": 0, "sensor_stale_seconds": 30,
    "sensor_poll_seconds": 3, "control_tick_seconds": 1,
}
PIN_KEYS = tuple(DEFAULTS["gpio"])
RUNTIME = set(DEFAULTS) - set(RESTART_REQUIRED)


def merged(base, updates):
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(copy.deepcopy(value))
        else:
            result[key] = copy.deepcopy(value)
    return result


def migrate(raw):
    raw = copy.deepcopy(raw)
    if type(raw.get("output_active_high")) is bool:
        raw["output_active_high"] = {key: raw["output_active_high"] for key in OUTPUTS}
    return raw


def validate(config):
    if not isinstance(config, dict) or set(config) - set(DEFAULTS):
        raise ValueError("Unknown configuration setting")
    for key, default in DEFAULTS.items():
        value = config[key]
        if isinstance(default, dict):
            if not isinstance(value, dict) or set(value) != set(default):
                raise ValueError(f"{key}: expected keys {', '.join(default)}")
            continue
        if key == "simulation":
            if type(value) is not bool:
                raise ValueError("simulation must be boolean")
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        elif value < 0:
            raise ValueError(f"{key} must be nonnegative")
    for channel in ("acu1", "acu2", "door"):
        if config["output_active_high"][channel] is not True:
            raise ValueError(f"output_active_high.{channel} must be exactly True")
    for group in ("input_active_high", "output_active_high"):
        if any(type(value) is not bool for value in config[group].values()):
            raise ValueError(f"{group} values must be booleans")
    if any(value not in ("none", "up", "down") for value in config["input_pull"].values()):
        raise ValueError("input_pull must use none, up, or down")
    for key, pin in config["gpio"].items():
        if pin is not None and (type(pin) is not int or not 0 <= pin <= 27):
            raise ValueError(f"gpio.{key}: unsupported BCM pin")
    if not config["simulation"]:
        pins = list(config["gpio"].values())
        if None in pins or len(set(pins)) != len(pins):
            raise ValueError("Hardware mode requires assigned, distinct BCM pins")
    for key in ("boost_on_c", "boost_off_c", "high_temp_alarm_c"):
        if not 0 <= config[key] <= 50:
            raise ValueError(f"{key} must be within 0-50 C")
    if not 0 <= config["high_humidity_alarm_pct"] <= 100:
        raise ValueError("high_humidity_alarm_pct must be within 0-100")
    if config["boost_on_c"] <= config["boost_off_c"]:
        raise ValueError("boost_on_c must exceed boost_off_c")
    for key, minimum in (("rotation_seconds", 1800),
                         ("sensor_poll_seconds", 2)):
        if config[key] < minimum:
            raise ValueError(f"{key} must be >= {minimum}")
    if config["control_tick_seconds"] <= 0:
        raise ValueError("control_tick_seconds must be positive")
    if config["sensor_stale_seconds"] <= config["sensor_poll_seconds"]:
        raise ValueError("sensor_stale_seconds must exceed sensor_poll_seconds")
    return config


class Configuration:
    def __init__(self, path, raw=None):
        self.path = Path(path)
        raw = json.loads(self.path.read_text()) if raw is None else raw
        if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
            raise ValueError("Unknown configuration setting")
        self.raw = migrate(raw)
        self.effective = validate(merged(DEFAULTS, self.raw))

    def contract(self):
        return {"effective": copy.deepcopy(self.effective),
                "defaults": copy.deepcopy(DEFAULTS),
                "restart_required": list(RESTART_REQUIRED)}

    def candidate(self, patch):
        if not isinstance(patch, dict) or set(patch) - RUNTIME:
            raise ValueError("Unknown or restart-required setting")
        if "input_active_high" in patch:
            value = patch["input_active_high"]
            if not isinstance(value, dict) or set(value) - set(INPUTS):
                raise ValueError("input_active_high accepts door, water, smoke")
        return validate(merged(self.effective, patch))

    def save(self, patch, candidate):
        raw = merged(self.raw, patch)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent,
                                             prefix=".config-", delete=False) as stream:
                temporary = stream.name
                json.dump(raw, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self.raw = raw
        self.effective = copy.deepcopy(candidate)
