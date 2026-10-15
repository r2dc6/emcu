from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .constants import MIN_TOUCH
from .theme import (
    ACCENT_BLUE,
    AMBER_WARN,
    FG_DIM,
    FG_MUTED,
    GREEN_OK,
    RED_FAULT,
)

_STATE_COLOR_MAP = {
    "running": GREEN_OK,
    "ok": GREEN_OK,
    "on": GREEN_OK,
    "online": GREEN_OK,
    "accepted": GREEN_OK,
    "standby": FG_MUTED,
    "off": FG_MUTED,
    "stopped": FG_MUTED,
    "idle": FG_MUTED,
    "fault": RED_FAULT,
    "failed": RED_FAULT,
    "rejected": RED_FAULT,
    "error": RED_FAULT,
    "offline": RED_FAULT,
    "starting": AMBER_WARN,
    "pending": AMBER_WARN,
    "warn": AMBER_WARN,
    "warning": AMBER_WARN,
    "amber": AMBER_WARN,
    "boost": AMBER_WARN,
    "auto": ACCENT_BLUE,
    "pause": FG_MUTED,
    "paused": FG_MUTED,
    "unknown": FG_DIM,
    "stale": FG_DIM,
}

_STATE_ICON_MAP = {
    "running": "\u25B6",
    "ok": "\u2713",
    "on": "\u25B6",
    "online": "\u2713",
    "accepted": "\u2713",
    "standby": "\u25FC",
    "off": "\u25FC",
    "stopped": "\u23F8",
    "idle": "\u25FC",
    "fault": "\u26A0",
    "failed": "\u2717",
    "rejected": "\u2717",
    "error": "\u26A0",
    "offline": "\u2717",
    "starting": "\u27F3",
    "pending": "\u27F3",
    "warn": "!",
    "warning": "!",
    "amber": "!",
    "boost": "\u27F3",
    "auto": "A",
    "pause": "P",
    "paused": "P",
    "unknown": "?",
    "stale": "?",
}


def _resolve_color(state: str) -> str:
    return _STATE_COLOR_MAP.get(state.lower(), FG_DIM)


def _resolve_icon(state: str) -> str:
    return _STATE_ICON_MAP.get(state.lower(), "?")


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StatusCard(QFrame):
    def __init__(
        self,
        title: str,
        parent: Optional[QWidget] = None,
        warn: bool = False,
        fault: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatusCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        self._title_label = QLabel(title, self)
        self._title_label.setObjectName("CardTitle")
        outer.addWidget(self._title_label)

        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(3)
        outer.addLayout(self._content_layout)

        if warn:
            self.setProperty("warn", True)
        if fault:
            self.setProperty("fault", True)
        if warn or fault:
            _repolish(self)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)


class StateBadge(QFrame):
    def __init__(
        self,
        state: str,
        text: Optional[str] = None,
        icon_char: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._icon_label = QLabel(self)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setMinimumWidth(20)
        layout.addWidget(self._icon_label)

        self._text_label = QLabel(self)
        self._text_label.setObjectName("BadgeText")
        layout.addWidget(self._text_label)

        self.set_state(state, text=text, icon_char=icon_char)

    def set_state(
        self,
        state: str,
        text: Optional[str] = None,
        icon_char: Optional[str] = None,
    ) -> None:
        color = _resolve_color(state)
        icon = icon_char if icon_char is not None else _resolve_icon(state)
        display_text = text if text is not None else state.capitalize()

        self._icon_label.setText(icon)
        self._icon_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 700;")
        self._text_label.setText(display_text)
        self._text_label.setStyleSheet(
            f"QLabel#BadgeText {{ background: {color}22; color: {color}; "
            f"font-size: 13px; font-weight: 700; letter-spacing: 0.5px; "
            f"padding: 3px 8px; border-radius: 4px; }}"
        )


class BigReadout(QWidget):
    def __init__(
        self,
        value_str: str,
        unit_str: str,
        label_str: str,
        condition: str = "ok",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._value_label = QLabel(self)
        self._value_label.setObjectName("BigReadoutValue")
        self._value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(self._value_label)

        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)
        mid_row.setSpacing(8)

        self._unit_label = QLabel(self)
        self._unit_label.setObjectName("BigReadoutUnit")
        self._unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        mid_row.addWidget(self._unit_label)

        self._condition_indicator = QLabel(self)
        self._condition_indicator.setMinimumWidth(40)
        self._condition_indicator.setStyleSheet(
            "border-radius: 5px; background: transparent;"
        )
        mid_row.addWidget(self._condition_indicator)
        mid_row.addStretch(1)
        outer.addLayout(mid_row)

        self._label_label = QLabel(self)
        self._label_label.setObjectName("BigReadoutLabel")
        self._label_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(self._label_label)

        self.set_value(value_str, condition=condition)
        self.set_unit(unit_str)
        self.set_label(label_str)

    def set_value(self, value_str: str, condition: Optional[str] = None) -> None:
        effective_condition = condition
        if value_str is None or value_str == "\u2014":
            display_val = "\u2014"
            effective_condition = "unknown"
        else:
            display_val = value_str
            if effective_condition is None:
                effective_condition = "ok"

        for c in ("ok", "warn", "fault", "stale"):
            self._value_label.setProperty(c, False)
        self._value_label.setProperty(
            "stale" if effective_condition == "unknown" else effective_condition, True
        )
        _repolish(self._value_label)

        self._value_label.setText(display_val)

        cond_color_map = {
            "ok": GREEN_OK,
            "warn": AMBER_WARN,
            "fault": RED_FAULT,
            "stale": FG_DIM,
        }
        dot_color = cond_color_map.get(effective_condition, FG_DIM)
        self._condition_indicator.setStyleSheet(
            f"color: {dot_color}; font-size: 10px; font-weight: 700;"
        )
        self._condition_indicator.setText(effective_condition.upper())

    def set_unit(self, unit_str: str) -> None:
        self._unit_label.setText(unit_str)

    def set_label(self, label_str: str) -> None:
        self._label_label.setText(label_str)


class IndicatorLamp(QLabel):
    def __init__(
        self,
        on: bool = False,
        color: str = "green",
        blink: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Lamp")
        self.setMinimumSize(16, 16)
        self.setMaximumSize(16, 16)
        self.setAlignment(Qt.AlignCenter)

        self._on = on
        self._color = color
        self._blink = blink
        self._blink_state = on

        self._timer: Optional[QTimer] = None
        self._apply_visual()

        if blink:
            self._start_blink()

    def _clear_on_props(self) -> None:
        for c in ("green", "amber", "red", "blue"):
            self.setProperty(f"on-{c}", False)

    def _apply_visual(self) -> None:
        self._clear_on_props()
        effective_on = self._on and (not self._blink or self._blink_state)
        if effective_on and self._color in ("green", "amber", "red", "blue"):
            self.setProperty(f"on-{self._color}", True)
        _repolish(self)

    def _start_blink(self) -> None:
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self._on_blink_tick)
        self._timer.start()

    def _stop_blink(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._blink_state = self._on

    def _on_blink_tick(self) -> None:
        self._blink_state = not self._blink_state
        self._apply_visual()

    def set(
        self,
        on: Optional[bool] = None,
        color: Optional[str] = None,
        blink: Optional[bool] = None,
    ) -> None:
        if on is not None:
            self._on = on
            self._blink_state = on
        if color is not None:
            self._color = color
        if blink is not None:
            if blink and not self._blink:
                self._blink = True
                self._start_blink()
            elif not blink and self._blink:
                self._blink = False
                self._stop_blink()
            else:
                self._blink = blink
        self._apply_visual()


class CountdownLabel(QWidget):
    def __init__(
        self,
        seconds: Optional[int] = None,
        label: Optional[str] = "Next Rotation",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._label_label: Optional[QLabel] = None
        if label is not None:
            self._label_label = QLabel(label, self)
            self._label_label.setObjectName("BigReadoutLabel")
            outer.addWidget(self._label_label)

        self._time_label = QLabel(self)
        self._time_label.setObjectName("Countdown")
        self._time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        outer.addWidget(self._time_label)

        self._last_server_s: Optional[int] = None
        self._last_set_monotonic: Optional[float] = None
        self.set_seconds(seconds)

    @staticmethod
    def _format_hms(total_seconds: int) -> str:
        ts = max(0, int(total_seconds))
        h = ts // 3600
        m = (ts % 3600) // 60
        s = ts % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def set_seconds(self, seconds: Optional[int]) -> None:
        if seconds is None:
            self._last_server_s = None
            self._last_set_monotonic = None
            self._time_label.setText("--:--:--")
            self._time_label.setProperty("warn", True)
        else:
            self._last_server_s = max(0, int(seconds))
            self._last_set_monotonic = time.monotonic()
            self._time_label.setText(self._format_hms(self._last_server_s))
            self._time_label.setProperty("warn", False)
        _repolish(self._time_label)

    def tick_1s(self) -> None:
        if self._last_server_s is None or self._last_set_monotonic is None:
            return
        now = time.monotonic()
        delta = max(0, int(round(now - self._last_set_monotonic)))
        remaining = max(0, self._last_server_s - delta)
        self._time_label.setText(self._format_hms(remaining))


class StaleOverlay(QWidget):
    def __init__(
        self,
        child: QWidget,
        enabled: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self._child = child
        self._child.setParent(self)

        self._dim_effect = QGraphicsOpacityEffect(self._child)
        self._dim_effect.setOpacity(1.0)
        self._child.setGraphicsEffect(self._dim_effect)

        grid.addWidget(self._child, 0, 0, 1, 1)

        self._stale_label = QLabel("STALE", self)
        self._stale_label.setAlignment(Qt.AlignTop | Qt.AlignRight)
        self._stale_label.setStyleSheet(
            f"color: {RED_FAULT}; font-size: 18px; font-weight: 800; "
            f"letter-spacing: 2px; padding: 6px 10px; background: transparent;"
        )
        grid.addWidget(self._stale_label, 0, 0, 1, 1, Qt.AlignTop | Qt.AlignRight)
        self._stale_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._enabled = enabled
        self._refresh_visual()

    def _refresh_visual(self) -> None:
        if self._enabled:
            self._stale_label.show()
            self._dim_effect.setOpacity(0.55)
        else:
            self._stale_label.hide()
            self._dim_effect.setOpacity(1.0)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._refresh_visual()


def large_button(
    text: str,
    icon: Optional[str] = None,
    variant: str = "default",
) -> QPushButton:
    btn = QPushButton()
    btn.setMinimumSize(56, 56)
    btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

    if variant == "primary":
        btn.setObjectName("Primary")
    elif variant == "danger":
        btn.setObjectName("Danger")
    elif variant == "ghost":
        btn.setObjectName("Ghost")

    if icon is not None:
        btn.setText(f"{icon}  {text}")
    else:
        btn.setText(text)

    return btn
