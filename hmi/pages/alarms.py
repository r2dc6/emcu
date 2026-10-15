from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import ALARM_DEFINITIONS
from ..system_state import AlarmActive, AlarmSeverity, SystemState
from ..widgets import IndicatorLamp


@dataclass
class _RecentEntry:
    key: str
    severity: AlarmSeverity
    description: str
    cleared_at_monotonic: float


class _AlarmRow(QFrame):
    def __init__(
        self,
        key: str,
        severity: AlarmSeverity,
        description: str,
        active: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AlarmRow")
        self.setFixedHeight(60)
        self.setStyleSheet(
            "QFrame#AlarmRow { background: transparent; border-bottom: 1px solid #3a434f; }"
        )

        self._alarm_key: str = key
        self._acknowledged: bool = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(8)

        col0 = QHBoxLayout()
        col0.setContentsMargins(0, 0, 0, 0)
        col0.setSpacing(4)
        col0.setAlignment(Qt.AlignCenter)
        col0_container = QWidget(self)
        col0_container.setFixedWidth(60)
        col0_container.setLayout(col0)

        if severity == AlarmSeverity.CRITICAL:
            lamp_color = "red"
            sev_text = "CRIT"
            sev_color = "#e74c3c"
        elif severity == AlarmSeverity.WARNING:
            lamp_color = "amber"
            sev_text = "WARN"
            sev_color = "#f0ad4e"
        else:
            lamp_color = "blue"
            sev_text = "INFO"
            sev_color = "#3a8fd6"

        self._lamp = IndicatorLamp(
            on=active, color=lamp_color, blink=(active and severity == AlarmSeverity.CRITICAL), parent=self
        )
        col0.addWidget(self._lamp)

        sev_label = QLabel(sev_text, self)
        sev_label.setStyleSheet(
            f"font-size: 11px; font-weight: 800; color: {sev_color};"
            f"letter-spacing: 0.5px;"
        )
        sev_label.setAlignment(Qt.AlignCenter)
        col0.addWidget(sev_label)

        outer.addWidget(col0_container)

        col1_container = QWidget(self)
        col1_container.setMinimumWidth(240)
        col1_layout = QVBoxLayout(col1_container)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        col1_layout.setSpacing(0)
        col1_layout.setAlignment(Qt.AlignVCenter)

        self._desc_label = QLabel(description, self)
        if active:
            self._desc_label.setStyleSheet(
                "font-size: 13px; font-weight: 700; color: #e6ecf2;"
            )
        else:
            self._desc_label.setStyleSheet(
                "font-size: 13px; color: #8a95a3;"
            )
        self._desc_label.setWordWrap(True)
        col1_layout.addWidget(self._desc_label)

        outer.addWidget(col1_container, 1)

        col2_container = QWidget(self)
        col2_container.setFixedWidth(100)
        col2_layout = QVBoxLayout(col2_container)
        col2_layout.setContentsMargins(0, 0, 0, 0)
        col2_layout.setSpacing(0)
        col2_layout.setAlignment(Qt.AlignVCenter)

        self._status_label = QLabel(self)
        if active:
            self._status_label.setText("Active since\nunknown")
            self._status_label.setStyleSheet(
                "font-size: 12px; font-weight: 700; color: #e74c3c;"
            )
        else:
            self._status_label.setText("")
            self._status_label.setStyleSheet(
                "font-size: 12px; color: #8a95a3;"
            )
        self._status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col2_layout.addWidget(self._status_label)

        outer.addWidget(col2_container)

        col3_container = QWidget(self)
        col3_container.setFixedWidth(120)
        col3_layout = QVBoxLayout(col3_container)
        col3_layout.setContentsMargins(0, 0, 0, 0)
        col3_layout.setSpacing(0)
        col3_layout.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self._ack_btn = QPushButton("ACKNOWLEDGE", self)
        self._ack_btn.setObjectName(f"alarms_ack_{key}")
        self._ack_btn.setToolTip("Local display acknowledgement only; relay commands are unchanged")
        self._ack_btn.setEnabled(active)
        self._ack_btn.setFixedSize(110, 48)
        self._ack_btn.setStyleSheet("font-size: 11px; padding: 2px; min-height: 44px;")
        col3_layout.addWidget(self._ack_btn)

        outer.addWidget(col3_container)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

    @property
    def alarm_key(self) -> str:
        return self._alarm_key

    @property
    def ack_button(self) -> QPushButton:
        return self._ack_btn

    def set_acknowledged(self, ack: bool) -> None:
        self._acknowledged = ack
        self._opacity_effect.setOpacity(0.55 if ack else 1.0)

    @property
    def acknowledged(self) -> bool:
        return self._acknowledged


class AlarmsPage(QWidget):
    acknowledge_request = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._ack_times: Dict[str, float] = {}
        self._recent_history: List[_RecentEntry] = []
        self._prev_alarm_keys: set = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)
        self._relay_summary = QLabel("Alarm relay commands: UNKNOWN", self)
        self._relay_summary.setObjectName("alarms_relay_summary")
        self._relay_summary.setWordWrap(True)
        self._relay_summary.setStyleSheet("font-size: 12px;")
        outer.addWidget(self._relay_summary)

        active_title_row = QHBoxLayout()
        active_title_row.setContentsMargins(4, 0, 4, 0)
        active_title_row.setSpacing(8)

        active_title = QLabel("ACTIVE ALARMS", self)
        active_title.setStyleSheet(
            "font-size: 15px; font-weight: 800; letter-spacing: 0.5px; color: #e6ecf2;"
        )
        active_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        active_title_row.addWidget(active_title)

        self._active_count_label = QLabel("0", self)
        self._active_count_label.setObjectName("alarms_active_count")
        self._active_count_label.setStyleSheet(
            "font-size: 12px; font-weight: 700; padding: 3px 10px;"
            "border-radius: 10px; background: #e74c3c22; color: #e74c3c;"
        )
        active_title_row.addWidget(self._active_count_label)
        active_title_row.addStretch(1)

        active_title_wrap = QWidget(self)
        active_title_wrap.setLayout(active_title_row)
        active_title_wrap.setFixedHeight(28)
        outer.addWidget(active_title_wrap)

        self._active_list = QListWidget(self)
        self._active_list.setObjectName("alarms_active_list")
        self._active_list.setFixedHeight(160)
        self._active_list.setSpacing(0)
        self._active_list.setSelectionMode(QListWidget.NoSelection)
        self._active_list.setFocusPolicy(Qt.NoFocus)
        outer.addWidget(self._active_list)

        divider = QFrame(self)
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer.addWidget(divider)

        recent_title_row = QHBoxLayout()
        recent_title_row.setContentsMargins(4, 0, 4, 0)
        recent_title_row.setSpacing(8)

        recent_title = QLabel("RECENT / CLEARED", self)
        recent_title.setStyleSheet(
            "font-size: 14px; font-weight: 700; letter-spacing: 0.5px; color: #8a95a3;"
        )
        recent_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        recent_title_row.addWidget(recent_title)

        self._recent_count_label = QLabel("0", self)
        self._recent_count_label.setObjectName("alarms_recent_count")
        self._recent_count_label.setStyleSheet(
            "font-size: 12px; font-weight: 700; padding: 3px 10px;"
            "border-radius: 10px; background: #3a434f; color: #8a95a3;"
        )
        recent_title_row.addWidget(self._recent_count_label)
        recent_title_row.addStretch(1)

        recent_title_wrap = QWidget(self)
        recent_title_wrap.setLayout(recent_title_row)
        recent_title_wrap.setFixedHeight(28)
        outer.addWidget(recent_title_wrap)

        self._recent_list = QListWidget(self)
        self._recent_list.setObjectName("alarms_recent_list")
        # Leave room for a full row and slider travel in the shorter recent list.
        self._recent_list.setMinimumHeight(74)
        self._recent_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._recent_list.setSpacing(0)
        self._recent_list.setSelectionMode(QListWidget.NoSelection)
        self._recent_list.setFocusPolicy(Qt.NoFocus)
        outer.addWidget(self._recent_list, 1)

        for alarm_list in (self._active_list, self._recent_list):
            alarm_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
            alarm_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            alarm_list.verticalScrollBar().setStyleSheet(
                "QScrollBar:vertical { width: 48px; margin: 0; background: #262b33; }"
                "QScrollBar::handle:vertical { min-height: 48px; background: #485462;"
                " border-radius: 5px; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            )

    @Slot(object)
    def update_state(self, state: SystemState) -> None:
        self._relay_summary.setText(" | ".join(
            f"{key.title()}: {state.alarm_command_text(key)}" for key in state.alarm_outputs
        ))
        if not state.backend_online:
            self._active_count_label.setText("STALE / OFFLINE")
            return
        current_keys: set = set()
        for alarm in state.alarms:
            current_keys.add(alarm.key)

        for prev_key in self._prev_alarm_keys:
            if prev_key not in current_keys:
                prev_def = ALARM_DEFINITIONS.get(prev_key)
                if prev_def is not None:
                    sev_str = prev_def.get("severity", "warning").upper()
                    desc = prev_def.get("description", prev_key)
                else:
                    sev_str = "WARNING"
                    desc = f"Unknown alarm: {prev_key}"
                try:
                    sev = AlarmSeverity(sev_str)
                except ValueError:
                    sev = AlarmSeverity.WARNING
                entry = _RecentEntry(
                    key=prev_key,
                    severity=sev,
                    description=desc,
                    cleared_at_monotonic=time.monotonic(),
                )
                self._recent_history.insert(0, entry)
                if len(self._recent_history) > 50:
                    self._recent_history = self._recent_history[:50]

        self._prev_alarm_keys = current_keys

        self._rebuild_active_list(state.alarms)
        self._rebuild_recent_list()

    def _rebuild_active_list(self, alarms: List[AlarmActive]) -> None:
        self._active_list.clear()
        for alarm in alarms:
            row = _AlarmRow(
                key=alarm.key,
                severity=alarm.severity,
                description=alarm.description,
                active=True,
                parent=self,
            )
            if alarm.key in self._ack_times:
                row.set_acknowledged(True)
            row.ack_button.clicked.connect(
                lambda _=False, k=alarm.key, r=row: self._on_ack_clicked(k, r)
            )
            item = QListWidgetItem(self._active_list)
            item.setSizeHint(QSize(0, 60))
            self._active_list.addItem(item)
            self._active_list.setItemWidget(item, row)

        self._active_count_label.setText(str(len(alarms)))

    def _rebuild_recent_list(self) -> None:
        self._recent_list.clear()
        for entry in self._recent_history:
            row = _AlarmRow(
                key=entry.key,
                severity=entry.severity,
                description=entry.description,
                active=False,
                parent=self,
            )
            if entry.key in self._ack_times:
                row.set_acknowledged(True)
            item = QListWidgetItem(self._recent_list)
            item.setSizeHint(QSize(0, 60))
            self._recent_list.addItem(item)
            self._recent_list.setItemWidget(item, row)

        self._recent_count_label.setText(str(len(self._recent_history)))

    def _on_ack_clicked(self, alarm_key: str, row: _AlarmRow) -> None:
        self._ack_times[alarm_key] = time.monotonic()
        row.set_acknowledged(True)
        self.acknowledge_request.emit(alarm_key)
