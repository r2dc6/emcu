from __future__ import annotations

import platform
from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..constants import BACKEND_URL, HMI_VERSION
from ..system_state import SystemState
from ..widgets import StateBadge, StatusCard, large_button

try:
    from PySide6.QtCore import qVersion
except Exception:
    qVersion = None

try:
    import PySide6
    _PYSIDE6_VERSION = getattr(PySide6, "__version__", "unknown")
except Exception:
    _PYSIDE6_VERSION = "unknown"


def _format_timestamp(ts: Optional[datetime]) -> str:
    if ts is None:
        return "N/A"
    try:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "N/A"


def _latency_color_style(latency_ms: Optional[float]) -> str:
    if latency_ms is None:
        return "color: #5f6a78;"
    if latency_ms < 100:
        return "color: #2ecc71;"
    if latency_ms < 500:
        return "color: #f0ad4e;"
    return "color: #e74c3c;"


class _DiagnosticLogDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], lines: List[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostic Log")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setSizeGripEnabled(False)
        self.setFixedSize(720, 420)

        body = QWidget(self)
        body.setObjectName("DialogBody")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel("Diagnostic Log", body)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #e6ecf2;")
        title_bar.addWidget(title_lbl)
        title_bar.addStretch(1)
        layout.addLayout(title_bar)

        divider = QWidget(body)
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        text_edit = QTextEdit(body)
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.NoWrap)
        text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        display_lines = lines[-100:] if lines else []
        if display_lines:
            text_edit.setPlainText("\n".join(display_lines))
        else:
            text_edit.setPlainText("(no log entries available)")

        layout.addWidget(text_edit, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 6, 0, 0)
        btn_row.addStretch(1)

        close_btn = QPushButton("Close", body)
        close_btn.setObjectName("Ghost")
        close_btn.setMinimumSize(140, 56)
        close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)


class SystemPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentPage")

        self._diag_log_lines: List[str] = []
        self._config_defaults_loaded: bool = False
        self._backend_version_text: str = "unknown (/api/info missing)"

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)

        conn_card = StatusCard("BACKEND CONNECTIVITY")
        left_col.addWidget(conn_card, 1)

        self._conn_url_lbl = self._add_label_row(
            conn_card, "URL", BACKEND_URL, "system_conn_url"
        )

        state_row = QHBoxLayout()
        state_row.setContentsMargins(4, 4, 4, 4)
        state_row.setSpacing(8)
        state_lbl = QLabel("Connection", self)
        state_lbl.setMinimumWidth(160)
        self._conn_state_badge = StateBadge("unknown", text="UNKNOWN")
        self._conn_state_wrap = QWidget(self)
        self._conn_state_wrap.setObjectName("system_conn_state")
        wl = QHBoxLayout(self._conn_state_wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self._conn_state_badge)
        wl.addStretch(1)
        state_row.addWidget(state_lbl)
        state_row.addWidget(self._conn_state_wrap, 1)
        state_wrap = QWidget(self)
        state_wrap.setLayout(state_row)
        conn_card.add_widget(state_wrap)

        self._conn_last_lbl = self._add_label_row(
            conn_card, "Last successful poll", "N/A", "system_conn_last"
        )

        self._conn_latency_lbl = self._add_label_row(
            conn_card, "Status API latency", "unknown", "system_conn_latency"
        )

        self._conn_counters_lbl = self._add_label_row(
            conn_card, "Total polls / errors", "0 / 0", "system_conn_counters"
        )

        diag_row = QHBoxLayout()
        diag_row.setContentsMargins(4, 8, 4, 4)
        diag_row.addStretch(1)
        self._diag_btn = large_button("Diagnostic Log", variant="ghost")
        self._diag_btn.setObjectName("system_diag_btn")
        self._diag_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #485462; color: #8a95a3; "
            "border-radius: 6px; padding: 8px 14px; font-size: 14px; font-weight: 600; "
            "min-width: 48px; min-height: 48px; }"
            "QPushButton:hover { color: #e6ecf2; border-color: #3a8fd6; background: transparent; }"
            "QPushButton:pressed { background: #262b33; }"
            "QPushButton:disabled { background: #262b33; color: #5f6a78; border-color: #3a434f; }"
        )
        self._diag_btn.setMinimumWidth(180)
        self._diag_btn.clicked.connect(self._on_show_diagnostic_log)
        diag_row.addWidget(self._diag_btn)
        diag_wrap = QWidget(self)
        diag_wrap.setLayout(diag_row)
        conn_card.add_widget(diag_wrap)

        left_col.addStretch(1)
        columns.addLayout(left_col)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        sw_card = StatusCard("SOFTWARE")
        right_col.addWidget(sw_card, 1)

        qt_ver = qVersion() if qVersion is not None else "unknown"
        py_ver = platform.python_version()

        self._sw_hmi_lbl = self._add_label_row(
            sw_card, "HMI version", HMI_VERSION, "system_sw_hmi"
        )

        self._sw_python_lbl = self._add_label_row(
            sw_card, "Python version", py_ver, "system_sw_python"
        )

        self._sw_qt_lbl = self._add_label_row(
            sw_card, "Qt version", f"{qt_ver} / PySide6 {_PYSIDE6_VERSION}", "system_sw_qt"
        )

        self._sw_backend_lbl = self._add_label_row(
            sw_card, "Backend version", self._backend_version_text, "system_sw_backend"
        )

        self._sw_config_loaded_lbl = self._add_label_row(
            sw_card, "Config defaults loaded", "NO", None
        )

        right_col.addStretch(1)
        columns.addLayout(right_col)

        outer.addLayout(columns, 1)

    def _add_label_row(
        self,
        card: StatusCard,
        label_text: str,
        value_text: str,
        obj_name: Optional[str],
    ) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        lbl = QLabel(label_text, self)
        lbl.setMinimumWidth(160)
        row.addWidget(lbl, 0)

        val_lbl = QLabel(value_text, self)
        val_lbl.setWordWrap(True)
        if obj_name is not None:
            val_lbl.setObjectName(obj_name)
        val_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(val_lbl, 1)

        wrap = QWidget(self)
        wrap.setLayout(row)
        card.add_widget(wrap)
        return val_lbl

    def _update_conn_state_display(self, online: bool) -> None:
        if online:
            self._conn_state_badge.set_state("online", text="ONLINE")
        else:
            self._conn_state_badge.set_state("offline", text="OFFLINE")

    def _update_latency_display(self, latency_ms: Optional[float]) -> None:
        if latency_ms is None:
            text = "unknown"
        else:
            text = f"{latency_ms:.0f} ms"
        self._conn_latency_lbl.setText(text)
        self._conn_latency_lbl.setStyleSheet(
            f"font-weight: 600; {_latency_color_style(latency_ms)}"
        )

    def _update_config_loaded_display(self) -> None:
        if self._config_defaults_loaded:
            self._sw_config_loaded_lbl.setText("YES")
            self._sw_config_loaded_lbl.setStyleSheet(
                "color: #2ecc71; font-weight: 700;"
            )
        else:
            self._sw_config_loaded_lbl.setText("NO")
            self._sw_config_loaded_lbl.setStyleSheet(
                "color: #e74c3c; font-weight: 700;"
            )

    def _on_show_diagnostic_log(self) -> None:
        dlg = _DiagnosticLogDialog(self, self._diag_log_lines)
        dlg.exec()

    def update_state(self, state: SystemState) -> None:
        if state.config_defaults:
            self._config_defaults_loaded = True
            self._update_config_loaded_display()
        if state.latency_ms is not None:
            self._update_latency_display(state.latency_ms)
        if hasattr(state, "backend_online"):
            self._update_conn_state_display(state.backend_online)

    def update_connection_stats(
        self,
        online: bool,
        latency_ms: float,
        total_polls: int,
        error_count: int,
        last_success_ts: Optional[datetime],
    ) -> None:
        self._update_conn_state_display(online)
        self._update_latency_display(latency_ms if latency_ms is not None else None)
        self._conn_counters_lbl.setText(f"{total_polls} / {error_count}")
        self._conn_last_lbl.setText(_format_timestamp(last_success_ts))

    def update_backend_info(self, d: Optional[dict]) -> None:
        version: Optional[str] = None
        if isinstance(d, dict):
            for key in ("version", "backend_version", "server_version", "app_version"):
                v = d.get(key)
                if isinstance(v, str) and v:
                    version = v
                    break
        if version:
            self._backend_version_text = version
        else:
            self._backend_version_text = "unknown (/api/info missing)"
        self._sw_backend_lbl.setText(self._backend_version_text)

    def set_diagnostic_log(self, lines: Optional[List[str]]) -> None:
        if isinstance(lines, list):
            self._diag_log_lines = list(lines)
        else:
            self._diag_log_lines = []
