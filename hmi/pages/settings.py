from __future__ import annotations

import math
import copy
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    BACKEND_URL,
    MIN_ROTATION_HOURS,
)
from ..dialogs import ConfirmDialog, NumericKeypad
from ..system_state import SystemState
from ..output_test import OUTPUT_CHANNELS
from ..theme import BG_CARD, BORDER
from ..widgets import StateBadge, StatusCard, large_button


_FIELD_DEFS: Dict[str, dict] = {
    "rotation_hours": {
        "label": "Rotation interval",
        "unit": "h",
        "min": MIN_ROTATION_HOURS,
        "max": 168.0,
        "decimals": 1,
        "step": 0.5,
    },
    "boost_on_c": {
        "label": "Boost activation",
        "unit": "\u00b0C",
        "min": 0.0,
        "max": 50.0,
        "decimals": 1,
        "step": 0.5,
    },
    "boost_off_c": {
        "label": "Boost deactivation",
        "unit": "\u00b0C",
        "min": 0.0,
        "max": 50.0,
        "decimals": 1,
        "step": 0.5,
    },
    "min_restart_minutes": {
        "label": "Min restart delay (0 = disabled)",
        "unit": "min",
        "min": 0,
        "max": 60.0,
        "decimals": 0,
        "step": 1.0,
    },
    "overlap_s": {
        "label": "Handover overlap",
        "unit": "s",
        "min": 0.0,
        "max": 120.0,
        "decimals": 0,
        "step": 1.0,
    },
    "high_temp_c": {
        "label": "High temp threshold",
        "unit": "\u00b0C",
        "min": 0.0,
        "max": 50.0,
        "decimals": 1,
        "step": 0.5,
    },
    "high_humidity_pct": {
        "label": "High humidity threshold",
        "unit": "%",
        "min": 0.0,
        "max": 100.0,
        "decimals": 0,
        "step": 1.0,
    },
    "door_delay_s": {
        "label": "Door-open warning delay",
        "unit": "s",
        "min": 0.0,
        "max": 3600.0,
        "decimals": 0,
        "step": 10.0,
    },
}

_API_FIELDS = {
    "rotation_hours": ("rotation_seconds", 3600),
    "min_restart_minutes": ("min_off_seconds", 60),
    "overlap_s": ("handover_overlap_seconds", 1),
    "high_temp_c": ("high_temp_alarm_c", 1),
    "high_humidity_pct": ("high_humidity_alarm_pct", 1),
    "door_delay_s": ("door_alarm_seconds", 1),
}
for _key, _label, _minimum in (
    ("water_alarm_seconds", "Water delay", 0),
    ("smoke_alarm_seconds", "Smoke delay", 0),
    ("temperature_alarm_seconds", "Temperature delay", 0),
    ("humidity_alarm_seconds", "Humidity delay", 0),
    ("sensor_stale_seconds", "DHT stale interval", 0.1),
    ("sensor_poll_seconds", "DHT poll interval", 2),
    ("control_tick_seconds", "Control interval", 0.1),
):
    _FIELD_DEFS[_key] = dict(label=_label, unit="s", min=_minimum,
                            max=86400.0, decimals=1, step=1)
for _key in ("door", "water", "smoke"):
    _FIELD_DEFS[f"{_key}_active_high"] = dict(label=f"{_key.title()} active level", unit="", digital=True)
for _key, _definition in _FIELD_DEFS.items():
    if not _definition.get("digital") and _key not in (
        "boost_on_c", "boost_off_c", "high_temp_c", "high_humidity_pct"
    ):
        _definition["max"] = math.inf
_FIELD_DEFS["control_tick_seconds"]["min"] = 0
_FIELD_DEFS["sensor_stale_seconds"]["min"] = 0


class SettingsPage(QWidget):
    request_save_settings = Signal(dict)
    probe_settings = Signal()
    request_start_test = Signal()
    request_end_test = Signal()
    request_test_output = Signal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._saved: Dict[str, float] = {}
        self._edited: Dict[str, float] = {}
        self._errors: Dict[str, str] = {}
        self._endpoint_available: bool = False
        self._state_loaded: bool = False
        self._backend_online = False
        self._defaults = {}
        self._pending_snapshot = None
        self._pending_cmd_id = None
        self._response_received = False
        self._field_buttons: Dict[str, QPushButton] = {}
        self._field_dirty_markers: Dict[str, QLabel] = {}
        self._field_error_labels: Dict[str, QLabel] = {}
        self._field_default_labels: Dict[str, QLabel] = {}
        self._test_block_save = False
        self._test_values = {}
        self._test_buttons = {}
        self._test_labels = {}

        self._build_ui()
        self.probe_settings.emit()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)

        scroll = QScrollArea(self)
        scroll.setObjectName("settings_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        columns = QHBoxLayout()
        content_layout.addLayout(columns)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._scroll = scroll
        scroll.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical { width: 48px; }"
            "QScrollBar::handle:vertical { min-height: 48px; background: #485462; }"
        )
        scroll_controls = QHBoxLayout()
        scroll_controls.addWidget(QLabel("More settings: scroll up / down", self), 1)
        for direction, text in ((-1, "Up"), (1, "Down")):
            button = QPushButton(text, self)
            button.setObjectName(f"settings_scroll_{text.lower()}")
            button.setFixedSize(80, 48)
            button.clicked.connect(lambda _=False, delta=direction: scroll.verticalScrollBar().setValue(
                scroll.verticalScrollBar().value() + delta * max(48, scroll.viewport().height() - 48)
            ))
            scroll_controls.addWidget(button)
        outer.addLayout(scroll_controls)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)

        cooling_card = StatusCard("COOLING")
        left_col.addWidget(cooling_card)

        cooling_fields = [
            ("rotation_hours", "settings_field_rotation_btn"),
            ("boost_on_c", "settings_field_booston_btn"),
            ("boost_off_c", "settings_field_boostoff_btn"),
        ]
        for key, obj_name in cooling_fields:
            self._add_field_row(cooling_card, key, obj_name)

        protection_card = StatusCard("PROTECTION")
        left_col.addWidget(protection_card)

        protection_fields = [
            ("min_restart_minutes", "settings_field_minrestart_btn"),
            ("overlap_s", "settings_field_overlap_btn"),
        ]
        for key, obj_name in protection_fields:
            self._add_field_row(protection_card, key, obj_name)

        for key in ("sensor_stale_seconds", "sensor_poll_seconds", "control_tick_seconds"):
            self._add_field_row(protection_card, key, f"settings_field_{key}_btn")

        left_col.addStretch(1)
        columns.addLayout(left_col)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        alarms_card = StatusCard("ALARMS")
        right_col.addWidget(alarms_card)

        alarm_fields = [
            ("high_temp_c", "settings_field_hightemp_btn"),
            ("high_humidity_pct", "settings_field_highhum_btn"),
            ("door_delay_s", "settings_field_doordelay_btn"),
        ]
        for key, obj_name in alarm_fields:
            self._add_field_row(alarms_card, key, obj_name)
        for key in ("water_alarm_seconds", "smoke_alarm_seconds",
                    "temperature_alarm_seconds", "humidity_alarm_seconds",
                    "door_active_high", "water_active_high", "smoke_active_high"):
            self._add_field_row(alarms_card, key, f"settings_field_{key}_btn")

        system_card = StatusCard("SYSTEM")
        right_col.addWidget(system_card)
        self._restart_label = QLabel("Installation settings require backend restart", self)
        self._restart_label.setWordWrap(True)
        system_card.add_widget(self._restart_label)
        self._error_detail = QLabel("", self)
        self._error_detail.setObjectName("settings_error_detail")
        self._error_detail.setWordWrap(True)
        self._error_detail.setStyleSheet("color: #e74c3c; font-size: 12px;")
        system_card.add_widget(self._error_detail)

        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(4, 4, 4, 4)
        theme_row.setSpacing(8)
        theme_lbl = QLabel("Display theme", self)
        theme_lbl.setMinimumWidth(140)
        theme_btn = QPushButton("Dark Charcoal", self)
        theme_btn.setObjectName("settings_theme_btn")
        theme_btn.setMinimumSize(120, 48)
        theme_btn.setEnabled(False)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(theme_btn, 1)
        theme_wrap = QWidget(self)
        theme_wrap.setLayout(theme_row)
        system_card.add_widget(theme_wrap)

        backend_row = QHBoxLayout()
        backend_row.setContentsMargins(4, 4, 4, 4)
        backend_row.setSpacing(8)
        backend_lbl = QLabel("Saving via backend endpoint", self)
        backend_lbl.setWordWrap(True)
        self._endpoint_badge = StateBadge("unknown", text="unknown")
        backend_row.addWidget(backend_lbl)
        backend_row.addWidget(self._endpoint_badge)
        backend_row.addStretch(1)
        backend_wrap = QWidget(self)
        backend_wrap.setLayout(backend_row)
        system_card.add_widget(backend_wrap)

        right_col.addStretch(1)
        columns.addLayout(right_col)

        self._test_card = StatusCard("MANUAL OUTPUT TESTING")
        self._test_card.setObjectName("settings_output_test")
        # Keep the testing hook while retaining the established StatusCard appearance.
        self._test_card.setStyleSheet(
            f"QFrame#settings_output_test {{ background: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        content_layout.addWidget(self._test_card)
        warning = QLabel(
            "Direct relay test bypasses compressor restart protection. Disconnect ACUs or use "
            "dummy loads. Displayed states are commands, not measured contacts.", self)
        warning.setWordWrap(True)
        self._test_card.add_widget(warning)
        self._test_banner = QLabel("Backend offline - commands UNKNOWN", self)
        self._test_banner.setObjectName("settings_test_banner")
        self._test_banner.setWordWrap(True)
        self._test_banner.setTextFormat(Qt.PlainText)
        self._test_banner.setStyleSheet("color: #f0ad4e; font-weight: 700;")
        self._test_card.add_widget(self._test_banner)
        actions = QWidget(self)
        action_layout = QHBoxLayout(actions)
        self._start_test_btn = QPushButton("Start Test", self)
        self._start_test_btn.setObjectName("settings_test_start")
        self._end_test_btn = QPushButton("End Test", self)
        self._end_test_btn.setObjectName("settings_test_end")
        for button in (self._start_test_btn, self._end_test_btn):
            button.setMinimumSize(140, 48)
            button.setEnabled(False)
            action_layout.addWidget(button)
        self._start_test_btn.clicked.connect(self._on_start_test)
        self._end_test_btn.clicked.connect(self.request_end_test.emit)
        self._test_card.add_widget(actions)
        for channel, name in OUTPUT_CHANNELS.items():
            row = QWidget(self)
            layout = QHBoxLayout(row)
            layout.addWidget(QLabel(name, self), 1)
            label = QLabel("UNKNOWN", self)
            label.setObjectName(f"settings_test_state_{channel}")
            layout.addWidget(label, 1)
            button = QPushButton("Toggle ON/OFF", self)
            button.setObjectName(f"settings_test_toggle_{channel}")
            button.setMinimumSize(140, 48)
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, key=channel: self._on_test_toggle(key))
            layout.addWidget(button)
            self._test_buttons[channel] = button
            self._test_labels[channel] = label
            self._test_card.add_widget(row)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 4)
        bottom_bar.setSpacing(10)

        self._endpoint_banner = QLabel(self)
        self._endpoint_banner.setObjectName("settings_endpoint_banner")
        self._endpoint_banner.setText("Backend settings endpoint unavailable \u2014 saving disabled")
        self._endpoint_banner.setStyleSheet(
            "background: #e74c3c; color: white; padding: 6px 10px; "
            "border-radius: 6px; font-weight: 700; font-size: 13px;"
        )
        self._endpoint_banner.setMinimumHeight(40)
        self._endpoint_banner.setWordWrap(True)
        self._endpoint_banner.setMinimumWidth(0)
        self._endpoint_banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_bar.addWidget(self._endpoint_banner, 1)

        self._save_banner = QLabel("", self)
        self._save_banner.setObjectName("settings_save_banner")
        self._save_banner.setWordWrap(True)
        self._save_banner.setMaximumWidth(120)
        self._save_banner.hide()
        self._save_banner.setMinimumHeight(40)
        self._save_banner.setAlignment(Qt.AlignCenter)
        bottom_bar.addWidget(self._save_banner, 0)

        self._revert_btn = large_button("Revert", variant="ghost")
        self._revert_btn.setObjectName("settings_revert_btn")
        self._revert_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #485462; color: #8a95a3; "
            "border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600; "
            "min-width: 48px; min-height: 48px; }"
            "QPushButton:hover { color: #e6ecf2; border-color: #3a8fd6; background: transparent; }"
            "QPushButton:pressed { background: #262b33; }"
            "QPushButton:disabled { background: #262b33; color: #5f6a78; border-color: #3a434f; }"
        )
        self._revert_btn.setMinimumWidth(120)
        self._revert_btn.clicked.connect(self._on_revert)
        bottom_bar.addWidget(self._revert_btn, 0)

        self._save_btn = large_button("Save Settings", variant="primary")
        self._save_btn.setObjectName("settings_save_btn")
        self._save_btn.setStyleSheet(
            "QPushButton { background: #3a8fd6; color: white; border: 1px solid #57a7ea; "
            "border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600; "
            "min-width: 48px; min-height: 48px; }"
            "QPushButton:hover { background: #57a7ea; }"
            "QPushButton:pressed { background: #262b33; }"
            "QPushButton:disabled { background: #3a434f; color: #5f6a78; border-color: #3a434f; }"
        )
        self._save_btn.setMinimumWidth(160)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        bottom_bar.addWidget(self._save_btn, 0)

        bottom_wrap = QWidget(self)
        bottom_wrap.setFixedHeight(80)
        bottom_wrap.setLayout(bottom_bar)
        outer.addWidget(bottom_wrap, 0)

        self._refresh_save_button_state()

    def _add_field_row(self, card: StatusCard, key: str, obj_name: str) -> None:
        defn = _FIELD_DEFS[key]
        unit = defn["unit"]

        row_wrap = QVBoxLayout()
        row_wrap.setContentsMargins(0, 0, 0, 0)
        row_wrap.setSpacing(2)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(4, 4, 4, 0)
        main_row.setSpacing(8)

        label = QLabel(defn["label"], self)
        label.setMinimumWidth(140)
        label.setWordWrap(True)
        main_row.addWidget(label, 0)

        value_btn = QPushButton(self)
        value_btn.setObjectName(obj_name)
        value_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #485462; color: #8a95a3; "
            "border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600; "
            "min-width: 120px; min-height: 44px; }"
            "QPushButton:hover { color: #e6ecf2; border-color: #3a8fd6; background: transparent; }"
            "QPushButton:pressed { background: #262b33; }"
            "QPushButton:disabled { background: #262b33; color: #5f6a78; border-color: #3a434f; }"
        )
        value_btn.setMinimumSize(120, 48)
        value_btn.clicked.connect(lambda _=False, k=key: self._on_edit_field(k))
        self._field_buttons[key] = value_btn
        main_row.addWidget(value_btn, 0)

        dirty_marker = QLabel("*", self)
        dirty_marker.setObjectName("DirtyMarker")
        dirty_marker.setVisible(False)
        self._field_dirty_markers[key] = dirty_marker
        main_row.addWidget(dirty_marker, 0)

        main_row.addStretch(1)
        row_wrap.addLayout(main_row)
        default_label = QLabel("Default: UNKNOWN", self)
        default_label.setStyleSheet("font-size: 11px; color: #8a95a3;")
        default_label.setContentsMargins(4, 0, 4, 0)
        self._field_default_labels[key] = default_label
        row_wrap.addWidget(default_label)

        error_label = QLabel("", self)
        error_label.setObjectName("FieldError")
        error_label.setContentsMargins(4, 0, 4, 0)
        error_label.setVisible(False)
        self._field_error_labels[key] = error_label
        row_wrap.addWidget(error_label)

        row_widget = QWidget(self)
        row_widget.setLayout(row_wrap)
        card.add_widget(row_widget)

    def _format_field_value(self, key: str, value: float) -> str:
        defn = _FIELD_DEFS[key]
        if defn.get("digital"):
            return "HIGH" if value else "LOW"
        decimals = defn["decimals"]
        unit = defn["unit"]
        if decimals <= 0:
            val_str = f"{int(round(value))}"
        else:
            val_str = f"{value:.{decimals}f}"
        return f"{val_str} {unit}"

    def _init_models_from_defaults(self, config_defaults: Dict[str, float]) -> None:
        self._saved = self._model_from_api(config_defaults)
        self._edited = dict(self._saved)

    @staticmethod
    def _model_from_api(values: dict) -> dict:
        model = {}
        for key, definition in _FIELD_DEFS.items():
            if definition.get("digital"):
                value = values["input_active_high"][key.removesuffix("_active_high")]
                if not isinstance(value, bool):
                    raise ValueError("Invalid active level")
            else:
                api_key, scale = _API_FIELDS.get(key, (key, 1))
                value = values[api_key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Invalid {api_key}")
                value /= scale
            model[key] = value
        return model

    def _refresh_all_views(self) -> None:
        for key in _FIELD_DEFS:
            self._refresh_field_view(key)
        self._refresh_save_button_state()

    def _refresh_field_view(self, key: str) -> None:
        btn = self._field_buttons.get(key)
        if btn is None:
            return
        value = self._edited.get(key)
        btn.setText("UNKNOWN" if value is None else self._format_field_value(key, value))
        btn.setEnabled(self._state_loaded)
        if key in self._defaults:
            default_text = "Default: " + self._format_field_value(key, self._defaults[key])
            btn.setToolTip(default_text)
            self._field_default_labels[key].setText(default_text)

        dirty = self._is_field_dirty(key)
        marker = self._field_dirty_markers.get(key)
        if marker is not None:
            marker.setVisible(dirty)

        error_lbl = self._field_error_labels.get(key)
        err = self._errors.get(key)
        if error_lbl is not None:
            if err:
                error_lbl.setText(err)
                error_lbl.setVisible(True)
            else:
                error_lbl.setText("")
                error_lbl.setVisible(False)

    def _is_field_dirty(self, key: str) -> bool:
        if key not in self._saved or key not in self._edited:
            return False
        return self._saved[key] != self._edited[key]

    def _is_dirty(self) -> bool:
        for key in _FIELD_DEFS:
            if self._is_field_dirty(key):
                return True
        return False

    def _has_errors(self) -> bool:
        return any(bool(v) for v in self._errors.values())

    def _validate_all(self) -> None:
        self._errors.clear()

        for key, defn in _FIELD_DEFS.items():
            val = self._edited.get(key)
            if val is None:
                continue
            if defn.get("digital"):
                if not isinstance(val, bool):
                    self._errors[key] = "Choose HIGH or LOW"
                continue
            mn = defn["min"]
            mx = defn["max"]
            if isinstance(val, bool) or not math.isfinite(val) or val < mn or val > mx:
                self._errors[key] = (
                    f"Value must be between {mn} and {mx}"
                )

        if "boost_on_c" in self._edited and "boost_off_c" in self._edited:
            if self._edited["boost_on_c"] <= self._edited["boost_off_c"]:
                self._errors["boost_on_c"] = (
                    "Must be above boost deactivation"
                )

        if "rotation_hours" in self._edited:
            if self._edited["rotation_hours"] < MIN_ROTATION_HOURS:
                self._errors["rotation_hours"] = (
                    f"Min rotation interval is {MIN_ROTATION_HOURS} hours"
                )

        if self._edited.get("sensor_stale_seconds", 30) <= self._edited.get("sensor_poll_seconds", 3):
            self._errors["sensor_stale_seconds"] = "Must exceed DHT poll interval"
        if self._edited.get("control_tick_seconds", 1) <= 0:
            self._errors["control_tick_seconds"] = "Must be positive"

    def _refresh_save_button_state(self) -> None:
        can_save = (self._backend_online and self._endpoint_available and self._state_loaded
                    and not self._test_block_save and self._pending_snapshot is None
                    and not self._has_errors() and self._is_dirty())
        self._save_btn.setEnabled(can_save)
        self._revert_btn.setEnabled(self._state_loaded and self._pending_snapshot is None and self._is_dirty())

    def _on_edit_field(self, key: str) -> None:
        if not self._state_loaded:
            return
        defn = _FIELD_DEFS[key]
        if defn.get("digital"):
            self._edited[key] = not self._edited[key]
            self._validate_all()
            self._refresh_all_views()
            return
        current = self._edited.get(key, defn["min"])
        result = NumericKeypad.get_value(
            self,
            initial_value=current,
            min_value=defn["min"],
            max_value=defn["max"],
            step=defn["step"],
            decimals=defn["decimals"],
            unit=defn["unit"],
            title=f"Set {defn['label']}",
        )
        if result is None:
            return
        self._edited[key] = float(result)
        self._validate_all()
        self._refresh_all_views()

    def _on_revert(self) -> None:
        if self._pending_snapshot is not None:
            return
        self._edited = dict(self._saved)
        self._errors.clear()
        self._refresh_all_views()
        self._save_banner.setText("")
        self._save_banner.setStyleSheet("")
        self._error_detail.clear()

    def _on_save(self) -> None:
        if not self._save_btn.isEnabled():
            return
        self._validate_all()
        self._refresh_all_views()
        if self._has_errors():
            return
        confirmed = ConfirmDialog.confirm(
            self,
            title="Save Settings?",
            message="Apply new configuration values to the backend?",
        )
        if not confirmed:
            return
        if not self._backend_online or self._pending_snapshot is not None:
            return
        payload = self._build_payload()
        self._pending_snapshot = copy.deepcopy(self._edited)
        self._response_received = False
        self._error_detail.clear()
        self._save_banner.setText("Saving\u2026")
        self._save_banner.setStyleSheet(
            "background: #f0ad4e; color: #1a1a1a; padding: 6px 10px; "
            "border-radius: 6px; font-weight: 700; font-size: 13px;"
        )
        self._save_banner.show()
        self._refresh_save_button_state()
        self.request_save_settings.emit(payload)

    def _build_payload(self) -> dict:
        payload = {}
        for key, value in self._edited.items():
            if _FIELD_DEFS[key].get("digital"):
                payload.setdefault("input_active_high", {})[key.removesuffix("_active_high")] = value
            else:
                api_key, scale = _API_FIELDS.get(key, (key, 1))
                payload[api_key] = value * scale
        return payload

    def update_state(self, state: SystemState) -> None:
        self._backend_online = state.backend_online
        values = {f"acu{acu.index + 1}": acu.commanded_on for acu in state.acus}
        values.update(state.alarm_outputs)
        self._test_values = values if state.backend_online else {}
        for channel, label in self._test_labels.items():
            value = self._test_values.get(channel)
            label.setText("UNKNOWN / OFFLINE" if not state.backend_online else
                          "UNKNOWN" if value is None else
                          "Commanded ON" if value else "Commanded OFF")
        self._refresh_save_button_state()
        if not state.backend_online:
            self._endpoint_banner.setText("Backend offline - retained settings; saving disabled")
        elif self._endpoint_available:
            self._endpoint_banner.setText("Backend effective settings loaded")

    def set_test_controls(self, controller) -> None:
        self._test_block_save = (controller.active or controller.needs_end or controller.ending)
        self._start_test_btn.setEnabled(controller.can_start and self._pending_snapshot is None)
        self._end_test_btn.setEnabled(bool(controller.session_id) and controller.online
                                       and (not controller.ending or not controller.pending))
        self._test_banner.setText(controller.message)
        for channel, button in self._test_buttons.items():
            button.setEnabled(controller.can_toggle and
                              isinstance(self._test_values.get(channel), bool))
        self._refresh_save_button_state()
        if self._test_block_save:
            self._endpoint_banner.setText("Output testing / restoration pending - saving disabled; edits retained")

    def _on_start_test(self):
        if not self._start_test_btn.isEnabled():
            return
        confirmed = ConfirmDialog.confirm(
            self, title="Start Direct Relay Test?",
            message="Actual relays will be energized. Automatic relay control is temporarily "
                    "overridden and compressor restart protection is bypassed. "
                    "Disconnect ACUs or replace them with dummy loads before continuing.",
            dangerous=True)
        if confirmed and self._start_test_btn.isEnabled():
            self.request_start_test.emit()

    def _on_test_toggle(self, channel):
        value = self._test_values.get(channel)
        if self._test_buttons[channel].isEnabled() and isinstance(value, bool):
            self.request_test_output.emit(channel, not value)

    def effective_settings(self) -> Optional[dict]:
        if not self._state_loaded:
            return None
        payload = {}
        for key, value in self._saved.items():
            if _FIELD_DEFS[key].get("digital"):
                payload.setdefault("input_active_high", {})[key.removesuffix("_active_high")] = value
            else:
                api_key, scale = _API_FIELDS.get(key, (key, 1))
                payload[api_key] = value * scale
        return payload

    def receive_settings(self, cmd_id: str, payload: dict) -> bool:
        try:
            model = self._model_from_api(payload["effective"])
            defaults = self._model_from_api(payload["defaults"])
        except (KeyError, TypeError, ValueError):
            self.set_settings_endpoint_available(False)
            self._save_banner.setText("Invalid backend settings; saving disabled")
            self._save_banner.show()
            return False
        if cmd_id.startswith("settings-"):
            if cmd_id != self._pending_cmd_id or self._pending_snapshot is None:
                return False
            baseline = self._pending_snapshot
            self._response_received = True
        else:
            if self._pending_snapshot is not None:
                return False
            baseline = self._saved
        self._edited = {
            key: self._edited[key] if key in self._edited and self._edited[key] != baseline.get(key)
            else value for key, value in model.items()
        }
        self._saved = model
        self._defaults = defaults
        self._state_loaded = True
        self._restart_label.setText("Restart-required installation settings: " +
                                   ", ".join(str(key) for key in payload["restart_required"]))
        self.set_settings_endpoint_available(True)
        self._validate_all()
        self._refresh_all_views()
        return True

    def set_settings_endpoint_available(self, available: bool) -> None:
        self._endpoint_available = bool(available)
        if self._endpoint_available:
            self._endpoint_banner.setText("Backend settings endpoint available")
            self._endpoint_banner.setStyleSheet(
                "background: #248a53; color: white; padding: 6px 10px; "
                "border-radius: 6px; font-weight: 700; font-size: 13px;"
            )
            self._endpoint_badge.set_state("ok", text="available")
        else:
            self._endpoint_banner.setText(
                "Backend settings endpoint unavailable \u2014 saving disabled"
            )
            self._endpoint_banner.setStyleSheet(
                "background: #e74c3c; color: white; padding: 6px 10px; "
                "border-radius: 6px; font-weight: 700; font-size: 13px;"
            )
            self._endpoint_badge.set_state("rejected", text="unavailable")
        self._refresh_save_button_state()

    def set_save_result(self, cmd_id: str, status: str, detail: str = "") -> None:
        if status == "pending":
            if self._pending_snapshot is not None and self._pending_cmd_id is None:
                self._pending_cmd_id = cmd_id
            self._refresh_save_button_state()
            return
        if cmd_id != self._pending_cmd_id or self._pending_snapshot is None:
            return
        self._save_banner.show()
        s = (status or "").lower()
        if s == "accepted" and self._response_received:
            self._save_banner.setText("Settings saved")
            self._save_banner.setStyleSheet(
                "background: #248a53; color: white; padding: 6px 10px; "
                "border-radius: 6px; font-weight: 700; font-size: 13px;"
            )
        elif s == "rejected":
            self._save_banner.setText("Save rejected")
            self._endpoint_banner.setText("Save rejected: " + detail)
            self._error_detail.setText("Save rejected: " + detail)
            self._save_banner.setStyleSheet(
                "background: #e74c3c; color: white; padding: 6px 10px; "
                "border-radius: 6px; font-weight: 700; font-size: 13px;"
            )
        elif s == "pending":
            self._save_banner.setText("Saving...")
        else:
            self._save_banner.setText("Save failed")
            self._endpoint_banner.setText("Save failed: " + (detail or "No effective settings response"))
            self._error_detail.setText("Save failed: " + (detail or "No effective settings response"))
            self._save_banner.setStyleSheet(
                "background: #e74c3c; color: white; padding: 6px 10px; "
                "border-radius: 6px; font-weight: 700; font-size: 13px;"
            )
        self._pending_snapshot = None
        self._pending_cmd_id = None
        self._validate_all()
        self._refresh_all_views()
