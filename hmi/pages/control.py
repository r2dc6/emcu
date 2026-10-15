from __future__ import annotations

import time
import uuid
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..dialogs import ConfirmDialog
from ..system_state import (
    AcuiState,
    SystemState,
)
from ..theme import (
    ACCENT_BLUE,
    ACCENT_BLUE_2,
    AMBER_WARN,
    AMBER_WARN_DIM,
    BG_CARD,
    BG_CHARCOAL_2,
    BG_CARD_HOVER,
    BG_INPUT,
    BORDER,
    BORDER_LIGHT,
    FG_DIM,
    FG_MUTED,
    FG_TEXT,
    GREEN_OK_DIM,
    RED_FAULT,
    RED_FAULT_DIM,
)
from ..widgets import (
    StateBadge,
    StatusCard,
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


def _primary_btn_css() -> str:
    return f"""
QPushButton {{
    background: {ACCENT_BLUE}; color: white; border: 1px solid {ACCENT_BLUE_2};
    border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600;
    min-width: 48px; min-height: 48px;
}}
QPushButton:hover {{
    background: {ACCENT_BLUE_2};
}}
QPushButton:disabled {{
    background: {BG_INPUT}; color: {FG_DIM}; border-color: {BORDER};
}}
"""


def _danger_btn_css() -> str:
    return f"""
QPushButton {{
    background: {RED_FAULT}; color: white; border: 1px solid {RED_FAULT_DIM};
    border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600;
    min-width: 48px; min-height: 48px;
}}
QPushButton:hover {{
    background: #ef5d4c;
}}
QPushButton:disabled {{
    background: {BG_INPUT}; color: {FG_DIM}; border-color: {BORDER};
}}
"""


def _ghost_btn_css() -> str:
    return f"""
QPushButton {{
    background: transparent; border: 1px solid {BORDER_LIGHT}; color: {FG_MUTED};
    border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600;
    min-width: 48px; min-height: 48px;
}}
QPushButton:hover {{
    color: {FG_TEXT}; border-color: {ACCENT_BLUE};
}}
QPushButton:disabled {{
    background: {BG_CHARCOAL_2}; color: {FG_DIM}; border-color: {BORDER};
}}
"""


_BANNER_BASE_CSS = "padding: 6px 10px; border-radius: 6px; font-weight: 700; font-size: 13px;"


def _banner_css(prop: str) -> str:
    prop_map = {
        "info": (ACCENT_BLUE, "white"),
        "warn": (AMBER_WARN, "#1a1a1a"),
        "fault": (RED_FAULT, "white"),
        "ok": (GREEN_OK_DIM, "white"),
    }
    bg, fg = prop_map.get(prop, (ACCENT_BLUE, "white"))
    return f"QLabel {{ {_BANNER_BASE_CSS} background: {bg}; color: {fg}; }}"


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


_BANNER_PROP_MAP = {
    "pending": "warn",
    "accepted": "ok",
    "rejected": "fault",
    "failed": "fault",
    "info": "info",
}


def _large_button_base(text: str) -> QPushButton:
    btn = QPushButton()
    btn.setMinimumSize(56, 56)
    btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    btn.setText(text)
    return btn


class ControlPage(QWidget):
    request_mode = Signal(str)
    request_acu_command = Signal(int, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._command_statuses: Dict[str, tuple[str, str]] = {}
        self._backend_enabled: bool = False
        self._manual_available: bool = False
        self._controller_ready: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        self._build_banner(outer)
        self._build_mode_bar(outer)
        self._build_acu_cards(outer)

        self.setMinimumHeight(360)
        self._apply_backend_enable()

    def _build_banner(self, outer: QVBoxLayout) -> None:
        self.command_banner = QLabel(self)
        self.command_banner.setObjectName("control_command_banner")
        self.command_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.command_banner.setMinimumHeight(36)
        self.command_banner.setMaximumHeight(40)
        self.command_banner.setText("")
        self.command_banner.setStyleSheet(f"QLabel {{ {_BANNER_BASE_CSS} }}")
        outer.addWidget(self.command_banner)

    def _build_mode_bar(self, outer: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(12)

        self.mode_auto_btn = _large_button_base("AUTO")
        self.mode_auto_btn.setObjectName("control_mode_auto_btn")
        self.mode_auto_btn.setMinimumSize(160, 60)
        self.mode_auto_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.mode_auto_btn.setStyleSheet(_primary_btn_css())
        self.mode_auto_btn.clicked.connect(self._on_auto_clicked)
        bar.addWidget(self.mode_auto_btn)

        self.mode_manual_btn = _large_button_base("MANUAL")
        self.mode_manual_btn.setObjectName("control_mode_manual_btn")
        self.mode_manual_btn.setMinimumSize(160, 60)
        self.mode_manual_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.mode_manual_btn.setStyleSheet(_ghost_btn_css())
        self.mode_manual_btn.clicked.connect(self._on_manual_clicked)
        bar.addWidget(self.mode_manual_btn)

        self.mode_pause_btn = _large_button_base("PAUSE")
        self.mode_pause_btn.setObjectName("control_mode_pause_btn")
        self.mode_pause_btn.setMinimumSize(160, 60)
        self.mode_pause_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.mode_pause_btn.setStyleSheet(_ghost_btn_css())
        self.mode_pause_btn.clicked.connect(self._on_pause_clicked)
        bar.addWidget(self.mode_pause_btn)

        bar.addStretch(1)

        bar_widget = QWidget(self)
        bar_widget.setLayout(bar)
        bar_widget.setMinimumHeight(72)
        bar_widget.setMaximumHeight(72)
        outer.addWidget(bar_widget)

    def _build_acu_cards(self, outer: QVBoxLayout) -> None:
        cards = QHBoxLayout()
        outer.addLayout(cards, 1)
        self.acu1_card = self._build_acu_control_card(acu_idx=0, title="ACU 1 CONTROL")
        self.acu1_card["card_wrap"].setObjectName("control_acu1_card")
        self.acu1_card["card_wrap"].setStyleSheet(_status_card_css())
        cards.addWidget(self.acu1_card["card_wrap"], 1)

        self.acu2_card = self._build_acu_control_card(acu_idx=1, title="ACU 2 CONTROL")
        self.acu2_card["card_wrap"].setObjectName("control_acu2_card")
        self.acu2_card["card_wrap"].setStyleSheet(_status_card_css())
        cards.addWidget(self.acu2_card["card_wrap"], 1)

    def _build_acu_control_card(self, acu_idx: int, title: str) -> dict:
        card = StatusCard(title=title, parent=self)

        inner = QVBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(4)

        state_badge = StateBadge(state="unknown", text="UNKNOWN", parent=card)
        left_col.addWidget(state_badge)

        commanded_label = QLabel("Relay command only", card)
        commanded_label.setStyleSheet(_CARD_BODY_CSS)
        left_col.addWidget(commanded_label)

        left_col.addStretch(1)
        inner.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        start_btn = _large_button_base("ON")
        start_btn.setObjectName(f"control_acu{acu_idx + 1}_start")
        start_btn.setMinimumSize(120, 48)
        start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        start_btn.setStyleSheet(_primary_btn_css())
        start_btn.setEnabled(False)
        start_btn.setToolTip("Available in MANUAL mode; configured restart delay applies (0 disables it)")
        start_btn.clicked.connect(lambda: self._on_acu_start_clicked(acu_idx))
        btn_row.addWidget(start_btn, 1)

        stop_btn = _large_button_base("OFF")
        stop_btn.setObjectName(f"control_acu{acu_idx + 1}_stop")
        stop_btn.setMinimumSize(120, 48)
        stop_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        stop_btn.setStyleSheet(_danger_btn_css())
        stop_btn.setEnabled(False)
        stop_btn.setToolTip("Available in MANUAL mode")
        stop_btn.clicked.connect(lambda: self._on_acu_stop_clicked(acu_idx))
        btn_row.addWidget(stop_btn, 1)

        right_col.addLayout(btn_row)

        note_label = QLabel(
            "Select MANUAL to use ON/OFF. Alarm monitoring stays active. Restart delay applies unless set to 0.",
            card,
        )
        note_label.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        note_label.setWordWrap(True)
        right_col.addWidget(note_label)

        right_col.addStretch(1)
        inner.addLayout(right_col, 1)

        inner_wrap = QWidget(card)
        inner_wrap.setLayout(inner)
        card.add_widget(inner_wrap)

        return {
            "card_wrap": card,
            "card_inner": card,
            "state_badge": state_badge,
            "commanded_label": commanded_label,
            "start_btn": start_btn,
            "stop_btn": stop_btn,
        }

    @staticmethod
    def _gen_cmd_id(prefix: str) -> str:
        short_uuid = uuid.uuid4().hex[:8]
        ts = int(time.time() * 1000)
        return f"{prefix}_{ts}_{short_uuid}"

    def _apply_backend_enable(self) -> None:
        enabled = self._backend_enabled and self._controller_ready
        self.mode_auto_btn.setEnabled(enabled)
        self.mode_manual_btn.setEnabled(enabled)
        self.mode_pause_btn.setEnabled(enabled)
        for card_data in (self.acu1_card, self.acu2_card):
            card_data["start_btn"].setEnabled(enabled and self._manual_available)
            card_data["stop_btn"].setEnabled(enabled and self._manual_available)

    @Slot(SystemState)
    def update_state(self, state: SystemState) -> None:
        self._controller_ready = state.backend_online and state.mode != "unknown" and not any(
            alarm.key == "CONTROLLER_ERROR" for alarm in state.alarms
        )
        self._manual_available = state.mode == "manual"
        self._update_mode_buttons(state)
        self._update_acu_control(self.acu1_card, state.acus[0] if len(state.acus) > 0 else None)
        self._update_acu_control(self.acu2_card, state.acus[1] if len(state.acus) > 1 else None)
        self._apply_backend_enable()

    def _update_mode_buttons(self, state: SystemState) -> None:
        mode = state.mode
        self.mode_manual_btn.setStyleSheet(
            _primary_btn_css() if mode == "manual" else _ghost_btn_css()
        )

        if mode == "auto":
            self.mode_auto_btn.setStyleSheet(_primary_btn_css())
            self.mode_pause_btn.setStyleSheet(_ghost_btn_css())
        elif mode == "pause":
            self.mode_auto_btn.setStyleSheet(_ghost_btn_css())
            self.mode_pause_btn.setStyleSheet(_danger_btn_css())
        else:
            self.mode_auto_btn.setStyleSheet(_ghost_btn_css())
            self.mode_pause_btn.setStyleSheet(_ghost_btn_css())

    def _update_acu_control(self, card_data: dict, acu) -> None:
        state = acu.state if acu is not None else AcuiState.UNKNOWN
        color = "on" if state == AcuiState.ON else "off" if state == AcuiState.OFF else "unknown"
        card_data["state_badge"].set_state(color, text=state.value)
        card_data["commanded_label"].setText(
            "UNKNOWN / STALE command" if state == AcuiState.UNKNOWN else "Relay command only"
        )

    @staticmethod
    def _set_card_flags(card: StatusCard, warn: bool, fault: bool) -> None:
        card.setStyleSheet(_status_card_css(warn=warn, fault=fault))

    @Slot()
    def _on_auto_clicked(self) -> None:
        ok = ConfirmDialog.confirm(
            parent=self,
            title="Switch to AUTO?",
            message="This will restore automatic ACU rotation and control logic. Continue?",
            dangerous=False,
        )
        if not ok:
            return
        self._manual_available = False
        self._apply_backend_enable()
        cmd_id = self._gen_cmd_id("mode_auto")
        self.set_command_status(cmd_id, "pending", "AUTO mode request pending\u2026")
        self.request_mode.emit("auto")

    @Slot()
    def _on_manual_clicked(self) -> None:
        ok = ConfirmDialog.confirm(
            parent=self,
            title="Disable automatic switching?",
            message="Select MANUAL to control each ACU with ON/OFF. Current ACU commands are retained. Alarm monitoring stays active. Restart delay applies unless set to 0. Continue?",
            dangerous=False,
        )
        if not ok:
            return
        self._manual_available = False
        self._apply_backend_enable()
        cmd_id = self._gen_cmd_id("mode_manual")
        self.set_command_status(cmd_id, "pending", "MANUAL mode request pending...")
        self.request_mode.emit("manual")

    @Slot()
    def _on_pause_clicked(self) -> None:
        ok = ConfirmDialog.confirm(
            parent=self,
            title="Switch to PAUSE?",
            message="Command both ACUs OFF. Physical operation cannot be confirmed. Alarm relays remain active. Continue?",
            dangerous=True,
        )
        if not ok:
            return
        self._manual_available = False
        self._apply_backend_enable()
        cmd_id = self._gen_cmd_id("mode_pause")
        self.set_command_status(cmd_id, "pending", "PAUSE mode request pending\u2026")
        self.request_mode.emit("pause")

    def _on_acu_start_clicked(self, acu_idx: int) -> None:
        if not (self._backend_enabled and self._controller_ready and self._manual_available):
            return
        acu_num_1based = acu_idx + 1
        ok = ConfirmDialog.confirm(
            parent=self,
            title=f"Turn ACU {acu_num_1based} ON?",
            message=f"Command ACU {acu_num_1based} ON in MANUAL mode. Configured restart delay applies (0 disables it); physical operation cannot be confirmed. Continue?",
            dangerous=False,
        )
        if not ok:
            return
        cmd_id = self._gen_cmd_id(f"acu{acu_num_1based}_start")
        self.set_command_status(cmd_id, "pending", f"ACU {acu_num_1based} ON request pending\u2026")
        self.request_acu_command.emit(acu_num_1based, "on")

    def _on_acu_stop_clicked(self, acu_idx: int) -> None:
        if not (self._backend_enabled and self._controller_ready and self._manual_available):
            return
        acu_num_1based = acu_idx + 1
        ok = ConfirmDialog.confirm(
            parent=self,
            title=f"Turn ACU {acu_num_1based} OFF?",
            message=f"Command ACU {acu_num_1based} OFF in MANUAL mode. Physical operation cannot be confirmed. Continue?",
            dangerous=True,
        )
        if not ok:
            return
        cmd_id = self._gen_cmd_id(f"acu{acu_num_1based}_stop")
        self.set_command_status(cmd_id, "pending", f"ACU {acu_num_1based} OFF request pending\u2026")
        self.request_acu_command.emit(acu_num_1based, "off")

    @Slot(str, str, str)
    def set_command_status(self, cmd_id: str, status: str, detail: str = "") -> None:
        self._command_statuses[cmd_id] = (status, detail)

        if status in ("pending", "accepted", "rejected", "failed"):
            prop = _BANNER_PROP_MAP.get(status, "info")
            banner_text = detail if detail else status.upper()
        else:
            prop = status if status in ("info", "warn", "fault", "ok") else "info"
            banner_text = detail if detail else ""

        self.command_banner.setStyleSheet(_banner_css(prop))
        self.command_banner.setText(
            f"{time.strftime('%H:%M:%S')} {status.upper()}: {banner_text}"
        )

    @Slot(bool)
    def set_backend_enabled(self, enabled: bool) -> None:
        self._backend_enabled = enabled
        if not enabled:
            self.set_command_status(
                "backend_disabled",
                "fault",
                "Backend unavailable \u2014 all commands disabled.",
            )
        self._apply_backend_enable()
