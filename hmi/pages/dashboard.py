from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import STALE_SENSOR_SECONDS
from ..system_state import (
    AcuiState,
    AlarmSeverity,
    Freshness,
    SystemState,
)
from ..theme import (
    AMBER_WARN_DIM,
    BG_CARD,
    BORDER,
    FG_MUTED,
    RED_FAULT_DIM,
)
from ..widgets import (
    BigReadout,
    CountdownLabel,
    StateBadge,
    StatusCard,
    StaleOverlay,
)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


_CARD_BODY_CSS = f"font-size: 14px; color: {FG_MUTED};"


def _status_card_css(warn: bool = False, fault: bool = False) -> str:
    if fault:
        border = RED_FAULT_DIM
    elif warn:
        border = AMBER_WARN_DIM
    else:
        border = BORDER
    return (
        f"QFrame {{ background: {BG_CARD}; border: 1px solid {border}; "
        f"border-radius: 8px; }}"
    )


def _format_runtime(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return "N/A"
    s = int(seconds)
    if s >= 3600:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"
    if s >= 60:
        m = s // 60
        return f"{m}m"
    return f"{s}s"


def _format_last_update(age_s: Optional[float], backend_online: bool,
                        stale_threshold_s: float = STALE_SENSOR_SECONDS) -> str:
    if not backend_online:
        return "offline"
    if age_s is None:
        return "stale"
    if age_s > stale_threshold_s:
        return "stale"
    return f"{max(1, int(round(age_s)))}s ago"


class DashboardPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._tick_timer: Optional[QTimer] = None
        self._text_fit_timer = QTimer(self)
        self._text_fit_timer.setSingleShot(True)
        self._text_fit_timer.timeout.connect(self._fit_alarm_text)

        root = QGridLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setHorizontalSpacing(12)
        root.setVerticalSpacing(8)
        root.setColumnStretch(0, 250)
        root.setColumnStretch(1, 280)
        root.setColumnStretch(2, 250)
        root.setRowStretch(0, 1)

        col0 = QVBoxLayout()
        col0.setContentsMargins(0, 0, 0, 0)
        col0.setSpacing(10)
        self._build_col0(col0)
        root.addLayout(col0, 0, 0)

        col1 = QVBoxLayout()
        col1.setContentsMargins(0, 0, 0, 0)
        col1.setSpacing(10)
        self._build_col1(col1)
        self._acu_column = col1
        root.addLayout(col1, 0, 1)

        col2 = QVBoxLayout()
        col2.setContentsMargins(0, 0, 0, 0)
        col2.setSpacing(8)
        self._build_col2(col2)
        root.addLayout(col2, 0, 2)

        self.setMinimumHeight(360)

    def _build_col0(self, layout: QVBoxLayout) -> None:
        self.temp_readout = BigReadout(
            value_str="\u2014",
            unit_str="\u00b0C",
            label_str="ROOM TEMPERATURE",
            condition="stale",
            parent=self,
        )
        self.temp_readout.setObjectName("dashboard_temp_readout")
        layout.addWidget(self.temp_readout)

        self.hum_readout = BigReadout(
            value_str="\u2014",
            unit_str="%RH",
            label_str="RELATIVE HUMIDITY",
            condition="stale",
            parent=self,
        )
        self.hum_readout.setObjectName("dashboard_hum_readout")
        layout.addWidget(self.hum_readout)

        self.freshness_summary = QLabel(self)
        self.freshness_summary.setObjectName("BigReadoutLabel")
        self.freshness_summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.freshness_summary.setText("Sensors: initializing\u2026")
        layout.addWidget(self.freshness_summary)
        layout.addStretch(1)

    def _build_col1(self, layout: QVBoxLayout) -> None:
        self.acu1_card = self._build_acu_card(acu_idx=0, title="ACU 1")
        self.acu1_card["card"].setObjectName("dashboard_acu1_card")
        self.acu1_card["card"].setStyleSheet(_status_card_css())
        self.acu1_card["card"].setMaximumHeight(90)
        layout.addWidget(self.acu1_card["card"], 1)

        self.acu2_card = self._build_acu_card(acu_idx=1, title="ACU 2")
        self.acu2_card["card"].setObjectName("dashboard_acu2_card")
        self.acu2_card["card"].setStyleSheet(_status_card_css())
        self.acu2_card["card"].setMaximumHeight(90)
        layout.addWidget(self.acu2_card["card"], 1)

    def _build_acu_card(self, acu_idx: int, title: str) -> dict:
        card = StatusCard(title=title, parent=self)

        state_badge = StateBadge(state="unknown", text="UNKNOWN", parent=card)
        card.add_widget(state_badge)

        commanded_label = QLabel("Relay command only", card)
        commanded_label.setStyleSheet(_CARD_BODY_CSS)
        card.add_widget(commanded_label)

        return {
            "card": card,
            "state_badge": state_badge,
            "commanded_label": commanded_label,
        }

    def _build_col2(self, layout: QVBoxLayout) -> None:
        mode_card = StatusCard(title="MODE & AUTOMATION", parent=self)
        mode_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        mode_card.setStyleSheet(_status_card_css())

        self.mode_badge = StateBadge(state="unknown", text="UNKNOWN", parent=mode_card)
        self.mode_badge.setObjectName("dashboard_mode_badge")
        mode_card.add_widget(self.mode_badge)

        self.boost_badge = StateBadge(state="ok", text="BOOST OFF", icon_char="\u2713", parent=mode_card)
        self.boost_badge.setObjectName("dashboard_boost_badge")
        mode_card.add_widget(self.boost_badge)

        self.lead_label = QLabel("Lead: N/A", mode_card)
        self.lead_label.setStyleSheet(_CARD_BODY_CSS)
        mode_card.add_widget(self.lead_label)

        layout.addWidget(mode_card)

        self.countdown = CountdownLabel(seconds=None, label="NEXT ROTATION", parent=self)
        self.countdown.setObjectName("dashboard_countdown")
        self.countdown_overlay = StaleOverlay(child=self.countdown, enabled=False, parent=self)
        layout.addWidget(self.countdown_overlay)

        alarm_card = StatusCard(title="ALARMS", parent=self)
        alarm_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        alarm_card.setStyleSheet(_status_card_css())

        self.alarm_summary = QLabel("0 ALARMS: None", alarm_card)
        self.alarm_summary.setObjectName("dashboard_alarm_summary")
        self.alarm_summary.setWordWrap(True)
        self.alarm_summary.setStyleSheet("font-size: 14px; color: #2ecc71; font-weight: 600;")
        alarm_card.add_widget(self.alarm_summary)
        self.water_status = QLabel("Water: UNKNOWN", alarm_card)
        alarm_card.add_widget(self.water_status)
        self.relay_summary = QLabel(alarm_card)
        self.relay_summary.setWordWrap(True)
        self.relay_summary.setStyleSheet("font-size: 11px;")
        alarm_card.add_widget(self.relay_summary)

        self._acu_column.addWidget(alarm_card)

        backend_card = StatusCard(title="BACKEND", parent=self)
        backend_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        backend_card.setStyleSheet(_status_card_css())

        self.backend_status = StateBadge(state="offline", text="OFFLINE", parent=backend_card)
        self.backend_status.setObjectName("dashboard_backend_status")
        backend_card.add_widget(self.backend_status)

        self.last_update = QLabel("Last update: \u2014", backend_card)
        self.last_update.setObjectName("dashboard_last_update")
        self.last_update.setStyleSheet(_CARD_BODY_CSS)
        backend_card.add_widget(self.last_update)

        layout.addWidget(backend_card)
        layout.addStretch(1)

    def start_local_ticks(self) -> None:
        if self._tick_timer is None:
            self._tick_timer = QTimer(self)
            self._tick_timer.setInterval(1000)
            self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

    @Slot()
    def _tick(self) -> None:
        self.countdown.tick_1s()

    @Slot(SystemState)
    def update_state(self, state: SystemState) -> None:
        self._update_temp_humidity(state)
        self._update_acu_card(self.acu1_card, state.acus[0] if len(state.acus) > 0 else None)
        self._update_acu_card(self.acu2_card, state.acus[1] if len(state.acus) > 1 else None)
        self._update_mode_automation(state)
        self._update_countdown(state)
        self._update_alarms(state)
        self._update_backend_status(state)

    def _update_temp_humidity(self, state: SystemState) -> None:
        cfg = state.config_defaults
        high_temp = float(cfg.get("high_temp_alarm_c", 30.0))
        boost_on = float(cfg.get("boost_on_c", 27.0))
        high_hum = float(cfg.get("high_humidity_alarm_pct", 65.0))
        hum_warn = high_hum * 0.9

        temp_sensor = state.temperature
        temp_freshness = temp_sensor.freshness
        temp_val = temp_sensor.value

        if temp_freshness == Freshness.UNKNOWN or temp_val is None:
            self.temp_readout.set_value("\u2014", condition="stale")
        elif temp_freshness == Freshness.STALE:
            self.temp_readout.set_value(f"{temp_val:.1f}", condition="stale")
        else:
            t = float(temp_val)
            if t >= high_temp:
                cond = "fault"
            elif t >= boost_on:
                cond = "warn"
            else:
                cond = "ok"
            self.temp_readout.set_value(f"{t:.1f}", condition=cond)

        hum_sensor = state.humidity
        hum_freshness = hum_sensor.freshness
        hum_val = hum_sensor.value

        if hum_freshness == Freshness.UNKNOWN or hum_val is None:
            self.hum_readout.set_value("\u2014", condition="stale")
        elif hum_freshness == Freshness.STALE:
            self.hum_readout.set_value(f"{hum_val:.0f}", condition="stale")
        else:
            h = float(hum_val)
            if h >= high_hum:
                cond = "fault"
            elif h >= hum_warn:
                cond = "warn"
            else:
                cond = "ok"
            self.hum_readout.set_value(f"{h:.0f}", condition=cond)

        parts = []
        if temp_freshness == Freshness.OK:
            parts.append("Temp OK")
        elif temp_freshness == Freshness.STALE:
            parts.append("Temp STALE")
        else:
            parts.append("Temp \u2014")
        if hum_freshness == Freshness.OK:
            parts.append("Hum OK")
        elif hum_freshness == Freshness.STALE:
            parts.append("Hum STALE")
        else:
            parts.append("Hum \u2014")
        self.freshness_summary.setText("Sensors: " + "  |  ".join(parts))

    def _update_acu_card(self, card_data: dict, acu) -> None:
        state = acu.state if acu is not None else AcuiState.UNKNOWN
        color = "on" if state == AcuiState.ON else "off" if state == AcuiState.OFF else "unknown"
        card_data["state_badge"].set_state(color, text=state.value)
        card_data["commanded_label"].setText(
            "UNKNOWN / STALE command" if state == AcuiState.UNKNOWN else "Relay command only"
        )

    @staticmethod
    def _set_card_flags(card: StatusCard, warn: bool, fault: bool) -> None:
        card.setStyleSheet(_status_card_css(warn=warn, fault=fault))

    def _update_mode_automation(self, state: SystemState) -> None:
        mode_display = state.mode_display()
        mode_state = "pause" if state.mode == "manual" else state.mode
        if mode_state not in ("auto", "pause", "unknown"):
            mode_state = "unknown"
        self.mode_badge.set_state(state=mode_state, text=mode_display)

        if not state.backend_online:
            self.boost_badge.set_state(state="unknown", text="BOOST UNKNOWN")
        elif state.boost_active:
            self.boost_badge.set_state(state="boost", text="BOOST ON", icon_char="\u21D1")
        else:
            self.boost_badge.set_state(state="ok", text="BOOST OFF", icon_char="\u2713")

        if state.lead_acu in (1, 2):
            suffix = " (STALE)" if not state.backend_online else ""
            self.lead_label.setText(f"Lead: ACU {state.lead_acu}{suffix}")
        else:
            self.lead_label.setText("Lead: N/A")

    def _update_countdown(self, state: SystemState) -> None:
        self.countdown.set_seconds(state.rotation_remaining_s if state.mode == "auto" else None)
        self.countdown_overlay.set_enabled(not state.backend_online)

    def _update_alarms(self, state: SystemState) -> None:
        water = state.water
        water_text = "UNKNOWN" if water.value is None else "ALARM" if water.value else "CLEAR"
        if water.freshness != Freshness.OK:
            water_text += f" ({water.freshness.value})"
        self.water_status.setText(f"Water: {water_text}")
        self.relay_summary.setText("\n".join(
            f"{key.title()}: {state.alarm_command_text(key)}" for key in state.alarm_outputs
        ))
        count = state.active_alarm_count()
        summary_text = f"{count} active alarms" if count else "No active alarms"
        if not state.backend_online:
            summary_text += " (STALE)"

        has_critical = any(a.severity == AlarmSeverity.CRITICAL for a in state.alarms)
        has_warning = any(a.severity == AlarmSeverity.WARNING for a in state.alarms)

        if has_critical:
            color = "#e74c3c"
        elif has_warning:
            color = "#f0ad4e"
        else:
            color = "#2ecc71"

        self.alarm_summary.setText(summary_text)
        self.alarm_summary.setStyleSheet(f"font-size: 14px; color: {color}; font-weight: 600;")
        self._text_fit_timer.start(0)

    def _fit_alarm_text(self) -> None:
        for label in (self.alarm_summary, self.relay_summary):
            label.setFixedHeight(max(label.fontMetrics().height(),
                                     label.heightForWidth(max(1, label.width()))))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._text_fit_timer.start(0)

    def _update_backend_status(self, state: SystemState) -> None:
        age = state.last_sensor_update_age_s(time.monotonic())
        update_text = _format_last_update(
            age, state.backend_online, state.config_defaults.get("sensor_stale_seconds", 30))

        if state.backend_online:
            self.backend_status.set_state(state="online", text="ONLINE")
        else:
            self.backend_status.set_state(state="offline", text="OFFLINE")

        self.last_update.setText(f"Last update: {update_text}")
