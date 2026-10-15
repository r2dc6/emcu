from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .constants import ALARM_DEFINITIONS, STALE_SENSOR_SECONDS, load_config_defaults


class Freshness(str, Enum):
    OK = "OK"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AcuiState(str, Enum):
    ON = "Commanded ON"
    OFF = "Commanded OFF"
    UNKNOWN = "UNKNOWN"


class AlarmSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class SensorReading:
    value: Optional[float | bool]
    freshness: Freshness
    age_s: Optional[float] = None


@dataclass
class AlarmActive:
    key: str
    severity: AlarmSeverity
    description: str
    triggered_at_monotonic: Optional[float] = None


@dataclass
class AcuStatus:
    index: int
    commanded_on: Optional[bool]
    state: AcuiState


@dataclass
class SystemState:
    backend_online: bool
    simulation_mode: bool
    mode: str
    temperature: SensorReading
    humidity: SensorReading
    door: SensorReading
    smoke: SensorReading
    water: SensorReading
    acus: list[AcuStatus]
    alarm_outputs: dict[str, Optional[bool]]
    lead_acu: Optional[int]
    rotation_remaining_s: Optional[int]
    handover_pending_acu: Optional[int]
    boost_active: bool
    alarms: list[AlarmActive]
    config_defaults: dict
    received_monotonic: float
    latency_ms: Optional[float] = None
    output_test: dict = field(default_factory=dict)

    @classmethod
    def build_empty(cls) -> SystemState:
        return cls.from_status_payload({}, False, time.monotonic())

    @classmethod
    def from_status_payload(
        cls, raw: dict, backend_online: bool, received_monotonic_s: float,
        stale_threshold_s: float = STALE_SENSOR_SECONDS,
        config_defaults: Optional[dict] = None,
    ) -> SystemState:
        config = config_defaults if config_defaults is not None else load_config_defaults()
        threshold = config.get("sensor_stale_seconds", stale_threshold_s)
        sensors = raw.get("sensors") or {}
        ages = raw.get("sensor_age_s") or {}
        freshness_map = raw.get("sensor_freshness") or {}

        def reading(key: str, digital: bool = False) -> SensorReading:
            value = sensors.get(key)
            valid = isinstance(value, bool) if digital else (
                isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value)
            )
            if not valid:
                value = None
            age = ages.get(key)
            if not isinstance(age, (int, float)) or isinstance(age, bool) or not math.isfinite(age) or age < 0:
                age = None
            freshness = Freshness.UNKNOWN
            if value is not None:
                if not backend_online:
                    freshness = Freshness.STALE
                elif age is not None:
                    freshness = Freshness.STALE if age > threshold else Freshness.OK
                    if freshness_map.get(key) in ("OK", "STALE", "UNKNOWN"):
                        freshness = Freshness(freshness_map[key])
            return SensorReading(value, freshness, age)

        def command(mapping: dict, key: str) -> Optional[bool]:
            value = mapping.get(key)
            return value if isinstance(value, bool) else None

        outputs = raw.get("acu_outputs") or {}
        acus = []
        for index in range(2):
            cmd = command(outputs, f"acu{index + 1}")
            state = AcuiState.UNKNOWN
            if backend_online and cmd is not None:
                state = AcuiState.ON if cmd else AcuiState.OFF
            acus.append(AcuStatus(index, cmd, state))
        alarms = []
        keys = list(raw.get("alarms") or [])
        if not backend_online and "BACKEND_OFFLINE" not in keys:
            keys.append("BACKEND_OFFLINE")
        for key in keys:
            if not isinstance(key, str):
                continue
            definition = ALARM_DEFINITIONS.get(key, {})
            alarms.append(AlarmActive(
                key, AlarmSeverity(definition.get("severity", "warning").upper()),
                definition.get("description", f"Unknown alarm: {key}"),
            ))
        rotation = raw.get("rotation_remaining_s")
        if not isinstance(rotation, (int, float)) or not math.isfinite(rotation):
            rotation = None
        state = cls(
            backend_online, bool(raw.get("simulation", False)),
            raw.get("mode") if backend_online and raw.get("mode") in ("auto", "manual", "pause") else "unknown",
            reading("temperature_c"), reading("humidity_pct"),
            reading("door_open", True), reading("smoke_alarm", True),
            reading("water_level_alarm", True), acus,
            {key: command(raw.get("alarm_outputs") or {}, key)
             for key in ("water", "smoke", "temperature", "humidity", "door")},
            raw.get("lead_acu") if raw.get("lead_acu") in (1, 2) else None,
            int(rotation) if rotation is not None else None,
            raw.get("handover_pending") if raw.get("handover_pending") in (1, 2) else None,
            bool(raw.get("boost", False)), alarms, dict(config), received_monotonic_s,
        )
        test = raw.get("output_test")
        state.output_test = dict(test) if isinstance(test, dict) else {}
        return state

    def active_alarm_count(self) -> int:
        return len(self.alarms)

    def active_alarm_summary(self) -> str:
        if not self.alarms:
            return "No active alarms"
        return f"{len(self.alarms)} ALARMS: " + ", ".join(a.key for a in self.alarms)

    def mode_display(self) -> str:
        return {"auto": "AUTO", "manual": "MANUAL", "pause": "PAUSED"}.get(self.mode, "UNKNOWN")

    def last_sensor_update_age_s(self, now_s: Optional[float] = None) -> Optional[float]:
        ages = [self.temperature.age_s, self.humidity.age_s]
        if any(age is None for age in ages):
            return None
        return max(ages) + max(0, (now_s or time.monotonic()) - self.received_monotonic)

    def alarm_command_text(self, key: str) -> str:
        value = self.alarm_outputs.get(key)
        if not self.backend_online:
            return "UNKNOWN (STALE)"
        if value is None:
            return "UNKNOWN"
        return "Commanded ON" if value else "Commanded OFF"
