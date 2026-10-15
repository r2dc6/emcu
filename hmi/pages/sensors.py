from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..constants import load_config_defaults
from ..system_state import Freshness, SystemState
from ..widgets import (
    BigReadout,
    IndicatorLamp,
    StateBadge,
    StatusCard,
)


class SensorsPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._config_defaults = load_config_defaults()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)

        env_card = StatusCard("ENVIRONMENT", self)
        self._temp_readout = BigReadout(
            value_str="\u2014",
            unit_str="\u00b0C",
            label_str="Temperature",
            condition="stale",
            parent=env_card,
        )
        self._temp_readout.setObjectName("sensors_temp_readout")
        env_card.add_widget(self._temp_readout)

        self._hum_readout = BigReadout(
            value_str="\u2014",
            unit_str="%",
            label_str="Humidity",
            condition="stale",
            parent=env_card,
        )
        self._hum_readout.setObjectName("sensors_hum_readout")
        env_card.add_widget(self._hum_readout)
        left_col.addWidget(env_card)

        comm_card = StatusCard("COMMUNICATION", self)
        last_update_row = QHBoxLayout()
        last_update_row.setContentsMargins(0, 0, 0, 0)
        last_update_row.setSpacing(6)
        last_update_label_pre = QLabel("Last sensor update:", comm_card)
        last_update_label_pre.setObjectName("CardBody")
        last_update_row.addWidget(last_update_label_pre)
        self._last_update_label = QLabel("offline", comm_card)
        self._last_update_label.setObjectName("sensors_last_update_label")
        self._last_update_label.setStyleSheet(
            "font-size: 14px; color: #8a95a3;"
        )
        last_update_row.addWidget(self._last_update_label, 1)
        comm_card.add_widget(self._wrap_layout(last_update_row))

        health_row = QHBoxLayout()
        health_row.setContentsMargins(0, 0, 0, 0)
        health_row.setSpacing(6)
        health_label_pre = QLabel("Sensor health:", comm_card)
        health_label_pre.setObjectName("CardBody")
        health_row.addWidget(health_label_pre)
        self._health_badge = StateBadge("unknown", parent=comm_card)
        health_row.addWidget(self._health_badge)
        health_row.addStretch(1)
        comm_card.add_widget(self._wrap_layout(health_row))
        left_col.addWidget(comm_card)

        left_container = QWidget(self)
        left_container.setLayout(left_col)
        outer.addWidget(left_container, 1)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(10)

        di_card = StatusCard("DIGITAL INPUTS", self)

        door_row = QHBoxLayout()
        door_row.setContentsMargins(0, 0, 0, 0)
        door_row.setSpacing(10)
        self._door_lamp = IndicatorLamp(on=False, color="grey", parent=di_card)
        self._door_lamp.setObjectName("sensors_door_lamp")
        door_row.addWidget(self._door_lamp)
        door_label = QLabel("Door contact:", di_card)
        door_label.setObjectName("CardBody")
        door_label.setFixedWidth(110)
        door_row.addWidget(door_label)
        self._door_value = QLabel("UNKNOWN", di_card)
        self._door_value.setObjectName("CardBody")
        door_row.addWidget(self._door_value, 1)
        di_card.add_widget(self._wrap_layout(door_row))

        smoke_row = QHBoxLayout()
        smoke_row.setContentsMargins(0, 0, 0, 0)
        smoke_row.setSpacing(10)
        self._smoke_lamp = IndicatorLamp(on=False, color="grey", parent=di_card)
        self._smoke_lamp.setObjectName("sensors_smoke_lamp")
        smoke_row.addWidget(self._smoke_lamp)
        smoke_label = QLabel("Smoke detector:", di_card)
        smoke_label.setObjectName("CardBody")
        smoke_label.setFixedWidth(110)
        smoke_row.addWidget(smoke_label)
        smoke_text_col = QVBoxLayout()
        smoke_text_col.setContentsMargins(0, 0, 0, 0)
        smoke_text_col.setSpacing(2)
        self._smoke_value = QLabel("UNKNOWN", di_card)
        self._smoke_value.setObjectName("CardBody")
        smoke_text_col.addWidget(self._smoke_value)
        self._smoke_warn = QLabel("\u26A0 SMOKE \u2014 INVESTIGATE", di_card)
        self._smoke_warn.setStyleSheet(
            "color: #e74c3c; font-size: 12px; font-weight: 700;"
        )
        self._smoke_warn.setVisible(False)
        smoke_text_col.addWidget(self._smoke_warn)
        smoke_row.addLayout(smoke_text_col, 1)
        di_card.add_widget(self._wrap_layout(smoke_row))

        water_row = QHBoxLayout()
        self._water_lamp = IndicatorLamp(on=False, color="grey", parent=di_card)
        self._water_lamp.setObjectName("sensors_water_lamp")
        water_row.addWidget(self._water_lamp)
        water_row.addWidget(QLabel("High water:", di_card))
        self._water_value = QLabel("UNKNOWN", di_card)
        self._water_value.setObjectName("sensors_water_value")
        water_row.addWidget(self._water_value, 1)
        di_card.add_widget(self._wrap_layout(water_row))

        right_col.addWidget(di_card)
        relay_card = StatusCard("ALARM RELAY COMMANDS", self)
        self._relay_values = {}
        for key in ("water", "smoke", "temperature", "humidity"):
            label = QLabel(f"{key.title()}: UNKNOWN", relay_card)
            label.setObjectName(f"sensors_relay_{key}")
            relay_card.add_widget(label)
            self._relay_values[key] = label
        right_col.addWidget(relay_card)
        right_col.addStretch(1)
        right_container = QWidget(self)
        right_container.setLayout(right_col)
        outer.addWidget(right_container, 1)


    @staticmethod
    def _wrap_layout(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        w.setContentsMargins(0, 0, 0, 0)
        return w

    @Slot(object)
    def update_state(self, state: SystemState) -> None:
        self._config_defaults = state.config_defaults or self._config_defaults
        high_temp = self._config_defaults.get("high_temp_alarm_c", 30.0)
        high_hum = self._config_defaults.get("high_humidity_alarm_pct", 65.0)
        stale_threshold = self._config_defaults.get(
            "sensor_stale_seconds", 30
        )

        temp_val = state.temperature.value
        temp_fresh = state.temperature.freshness
        if temp_val is None or temp_fresh == Freshness.UNKNOWN:
            temp_str = "\u2014"
            temp_cond = "stale"
        else:
            temp_f = float(temp_val)
            temp_str = f"{temp_f:.1f}"
            if temp_fresh == Freshness.STALE:
                temp_cond = "stale"
            elif temp_f >= high_temp:
                temp_cond = "fault"
            else:
                temp_cond = "ok"
        self._temp_readout.set_value(temp_str, condition=temp_cond)

        hum_val = state.humidity.value
        hum_fresh = state.humidity.freshness
        if hum_val is None or hum_fresh == Freshness.UNKNOWN:
            hum_str = "\u2014"
            hum_cond = "stale"
        else:
            hum_f = float(hum_val)
            hum_str = f"{hum_f:.0f}"
            if hum_fresh == Freshness.STALE:
                hum_cond = "stale"
            elif hum_f >= high_hum:
                hum_cond = "fault"
            else:
                hum_cond = "ok"
        self._hum_readout.set_value(hum_str, condition=hum_cond)

        age = state.last_sensor_update_age_s(time.monotonic())
        if not state.backend_online:
            age_text = "offline"
        elif age is None:
            age_text = "UNKNOWN"
        elif age > stale_threshold:
            age_text = "stale"
        else:
            age_text = f"{int(age)}s ago"
        self._last_update_label.setText(age_text)

        has_stale_alarm = any(a.key == "SENSOR_STALE" for a in state.alarms)
        temp_ok = (
            temp_val is not None
            and temp_fresh == Freshness.OK
            and float(temp_val) < high_temp
        )
        hum_ok = (
            hum_val is not None
            and hum_fresh == Freshness.OK
            and float(hum_val) < high_hum
        )
        if not state.backend_online or (
            temp_fresh == Freshness.UNKNOWN and hum_fresh == Freshness.UNKNOWN
        ):
            self._health_badge.set_state("unknown", text="UNKNOWN")
        elif has_stale_alarm or temp_fresh == Freshness.STALE or hum_fresh == Freshness.STALE:
            self._health_badge.set_state("warn", text="STALE")
        else:
            if temp_ok and hum_ok:
                self._health_badge.set_state("ok", text="OK")
            else:
                self._health_badge.set_state("warn", text="WARN")

        door_val = state.door.value
        door_fresh = state.door.freshness
        if door_fresh == Freshness.UNKNOWN or door_val is None:
            self._door_lamp.set(on=False, color="grey", blink=False)
            self._door_value.setText("UNKNOWN")
        elif bool(door_val):
            self._door_lamp.set(on=True, color="amber", blink=False)
            self._door_value.setText("OPEN")
        else:
            self._door_lamp.set(on=True, color="green", blink=False)
            self._door_value.setText("CLOSED")

        smoke_val = state.smoke.value
        smoke_fresh = state.smoke.freshness
        if smoke_fresh == Freshness.UNKNOWN or smoke_val is None:
            self._smoke_lamp.set(on=False, color="grey", blink=False)
            self._smoke_value.setText("UNKNOWN")
            self._smoke_warn.setVisible(False)
        elif bool(smoke_val):
            self._smoke_lamp.set(on=True, color="red", blink=True)
            self._smoke_value.setText("ALARM")
            self._smoke_warn.setVisible(True)
        else:
            self._smoke_lamp.set(on=True, color="green", blink=False)
            self._smoke_value.setText("CLEAR")
            self._smoke_warn.setVisible(False)

        for reading, label, lamp, active, clear in (
            (state.door, self._door_value, self._door_lamp, "OPEN", "CLOSED"),
            (state.smoke, self._smoke_value, self._smoke_lamp, "ALARM", "CLEAR"),
            (state.water, self._water_value, self._water_lamp, "ALARM", "CLEAR"),
        ):
            if reading.value is None or reading.freshness == Freshness.UNKNOWN:
                text = "UNKNOWN"
            else:
                text = active if reading.value else clear
            if reading.freshness == Freshness.STALE:
                text += " (STALE)"
            elif reading.age_s is not None:
                text += f" ({reading.age_s:.0f}s)"
            label.setText(text)
            lamp.set(on=reading.freshness == Freshness.OK,
                     color="red" if reading.value else "green",
                     blink=reading.freshness == Freshness.OK and bool(reading.value))
        self._smoke_warn.setVisible(state.smoke.freshness == Freshness.OK and state.smoke.value is True)
        for key, label in self._relay_values.items():
            label.setText(f"{key.title()}: {state.alarm_command_text(key)}")
