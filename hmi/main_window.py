from __future__ import annotations

import time
import logging
from dataclasses import replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QEvent, QEventLoop
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .backend_client import BackendClient
from .output_test import OutputTestController
from .constants import (
    APP_NAME,
    BACKEND_URL,
    PAGES,
    POLL_INTERVAL_MS,
    SCREEN_H,
    SCREEN_W,
)
from .system_state import AcuiState, AlarmSeverity, Freshness, SystemState

from .pages.alarms import AlarmsPage
from .pages.control import ControlPage
from .pages.dashboard import DashboardPage
from .pages.logs import LogsPage
from .pages.sensors import SensorsPage
from .pages.settings import SettingsPage
from .pages.system import SystemPage

from .theme import (
    ACCENT_BLUE,
    BG_CARD,
    FG_MUTED,
    FG_TEXT,
    GREEN_OK,
    RED_FAULT,
    AMBER_WARN,
)


_NAV_ICONS: Dict[str, str] = {
    "dashboard": "\u229E",
    "control": "\u2699",
    "sensors": "\u25CE",
    "alarms": "\u26A0",
    "logs": "\u2630",
    "settings": "\u2692",
    "system": "\u24D8",
}


class CoolShiftHMI(QMainWindow):
    def __init__(self, dev_mode: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RootWidget")

        self._dev_mode: bool = dev_mode
        self._current_state: Optional[SystemState] = None
        self._last_success_ts: float = 0.0
        self._first_poll_done: bool = False
        self._dashboard_ticks_started: bool = False
        self._nav_buttons: List[Tuple[QPushButton, str, int]] = []
        self._page_index: Dict[str, int] = {}
        self._diagnostic_lines: List[str] = []
        self._backend_online: bool = False
        self._pending_info: Dict[str, dict] = {}
        self._shutdown = False
        self._pending_navigation = None
        self._shutdown_waiting = False
        self.setWindowTitle(f"{APP_NAME} HMI")

        if dev_mode:
            self.setFixedSize(SCREEN_W, SCREEN_H)
            self.setWindowTitle(f"{APP_NAME} HMI Dev")
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            )
            self.showFullScreen()

        central = QWidget(self)
        central.setObjectName("RootWidget")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._top_header = self._build_top_header()
        self._top_header.setFixedHeight(56)
        outer.addWidget(self._top_header)

        self._stack = QStackedWidget()
        self._stack.setObjectName("main_stack")
        outer.addWidget(self._stack, 1)

        self._bottom_nav = self._build_bottom_nav()
        self._bottom_nav.setFixedHeight(64)
        outer.addWidget(self._bottom_nav)

        self._build_pages()
        self._wire_backend()
        self._wire_pages()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(10000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        self.navigate_to("dashboard")
        self._on_conn(False, 0.0)

    # ---- Header / Nav ----
    def _build_top_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("TopHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        layout.addWidget(title)

        layout.addStretch(1)

        self._offline_banner = QLabel("\u26A0 BACKEND OFFLINE")
        self._offline_banner.setObjectName("header_offline_banner")
        self._offline_banner.setStyleSheet(
            f"QLabel#header_offline_banner {{ background: {RED_FAULT}; color: white;"
            f" padding: 4px 10px; font-weight: 700; border-radius: 4px; }}"
        )
        self._offline_banner.hide()
        layout.addWidget(self._offline_banner)

        self._alarm_badge = QLabel("0")
        self._alarm_badge.setObjectName("header_alarm_badge")
        self._alarm_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._alarm_badge.setMinimumWidth(36)
        self._style_alarm_badge(0)
        layout.addWidget(self._alarm_badge)

        self._clock_label = QLabel("--:--")
        self._clock_label.setObjectName("header_clock")
        self._clock_label.setStyleSheet(
            f"QLabel#header_clock {{ font-size: 16px; color: {FG_MUTED}; }}"
        )
        layout.addWidget(self._clock_label)

        return header

    def _build_bottom_nav(self) -> QWidget:
        nav = QWidget()
        nav.setObjectName("BottomNav")
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        for index, (name, page_id) in enumerate(PAGES):
            icon = _NAV_ICONS.get(page_id, "")
            btn = QPushButton(f"{icon}\n{name}")
            btn.setObjectName(f"nav_btn_{page_id}")
            btn.setMinimumSize(96, 56)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(False)
            btn.setProperty("active", False)
            btn.setStyleSheet(
                f"""
                QPushButton#nav_btn_{page_id} {{
                    background: transparent;
                    color: {FG_MUTED};
                    border: none;
                    border-radius: 6px;
                    font-size: 12px;
                    padding: 4px 2px;
                    min-width: 96px;
                    min-height: 56px;
                }}
                QPushButton#nav_btn_{page_id}:checked,
                QPushButton#nav_btn_{page_id}[active="true"] {{
                    background: {ACCENT_BLUE};
                    color: white;
                }}
                QPushButton#nav_btn_{page_id}:hover:!checked {{
                    color: {FG_TEXT};
                    background: {BG_CARD};
                }}
                """
            )
            btn.clicked.connect(lambda _=False, pid=page_id: self.navigate_to(pid))
            layout.addWidget(btn)
            self._nav_buttons.append((btn, page_id, index))

        return nav

    def _build_pages(self) -> None:
        self.dashboard_page = DashboardPage()
        self.control_page = ControlPage()
        self.sensors_page = SensorsPage()
        self.alarms_page = AlarmsPage()
        self.logs_page = LogsPage()
        self.settings_page = SettingsPage()
        self.system_page = SystemPage()

        pages = [
            self.dashboard_page,
            self.control_page,
            self.sensors_page,
            self.alarms_page,
            self.logs_page,
            self.settings_page,
            self.system_page,
        ]

        for i, (name, page_id) in enumerate(PAGES):
            self._stack.addWidget(pages[i])
            self._page_index[page_id] = i

    # ---- Wiring ----
    def _wire_backend(self) -> None:
        self.backend = BackendClient(BACKEND_URL, parent=self)

        self.backend.status_received.connect(self._on_status_received)
        self.backend.connection_state_changed.connect(self._on_conn)
        self.backend.events_received.connect(self.logs_page.update_events)
        self.backend.settings_received.connect(self._on_settings_received)
        self.backend.command_result.connect(self._on_command_result)
        self.backend.error.connect(self._on_backend_error)
        self.backend.info_log.connect(self._on_backend_info_log)
        self.output_test = OutputTestController(self.backend, self)
        self.output_test.changed.connect(
            lambda: self.settings_page.set_test_controls(self.output_test))
        self.output_test.status_ready.connect(self._on_status_received)
        self.output_test.departure_ready.connect(self._on_test_departure_ready)

    def _wire_pages(self) -> None:
        self.control_page.request_mode.connect(self._on_request_mode)
        self.control_page.request_acu_command.connect(self._on_request_acu_command)

        self.settings_page.request_save_settings.connect(self._on_request_save_settings)
        self.settings_page.probe_settings.connect(self._on_probe_settings)
        self.settings_page.request_start_test.connect(self.output_test.start)
        self.settings_page.request_end_test.connect(self.output_test.end)
        self.settings_page.request_test_output.connect(self.output_test.toggle)

        self.logs_page.request_events.connect(self._on_request_events)

        self.alarms_page.acknowledge_request.connect(self._on_alarm_acknowledge)

    # ---- Navigation ----
    def navigate_to(self, page_id: str) -> None:
        if page_id not in self._page_index:
            return
        if self._shutdown or self._shutdown_waiting:
            return
        if (self._stack.currentWidget() is self.settings_page and page_id != "settings"
                and self.output_test.needs_end):
            if self._pending_navigation is None:
                self._pending_navigation = page_id
                self.output_test.end()
            return
        if self._pending_navigation is not None:
            return
        self.output_test.set_page(page_id == "settings")
        idx = self._page_index[page_id]
        if self._stack.currentIndex() != idx:
            self._stack.setCurrentIndex(idx)
        for btn, pid, _i in self._nav_buttons:
            is_active = pid == page_id
            if btn.property("active") != is_active:
                btn.setProperty("active", is_active)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

    def _on_test_departure_ready(self):
        if self._pending_navigation is not None and not self._shutdown_waiting:
            page_id = self._pending_navigation
            self._pending_navigation = None
            self.navigate_to(page_id)

    # ---- Header Helpers ----
    def _style_alarm_badge(self, count: int) -> None:
        if count <= 0:
            self._alarm_badge.setText("0")
            bg = GREEN_OK
            fg = "white"
        else:
            self._alarm_badge.setText(f"!{count}")
            has_critical = False
            if self._current_state is not None:
                for a in self._current_state.alarms:
                    if a.severity == AlarmSeverity.CRITICAL:
                        has_critical = True
                        break
            bg = RED_FAULT if has_critical else AMBER_WARN
            fg = "white"
        self._alarm_badge.setStyleSheet(
            f"QLabel#header_alarm_badge {{ background: {bg}; color: {fg};"
            f" border-radius: 10px; padding: 2px 8px; font-weight: 700; font-size: 13px; }}"
        )

    def _update_clock(self) -> None:
        now = datetime.now()
        self._clock_label.setText(now.strftime("%H:%M"))

    # ---- Backend slots ----
    def _on_status_received(self, raw: dict) -> None:
        reconnecting = not self._backend_online
        self._last_success_ts = datetime.now()
        was_first = not self._first_poll_done
        self._first_poll_done = True
        self._backend_online = True
        self._offline_banner.hide()
        self.control_page.set_backend_enabled(True)
        state = SystemState.from_status_payload(
            raw, True, time.monotonic(),
            config_defaults=self.settings_page.effective_settings(),
        )
        self._current_state = state
        self._cascade_state(state)
        self.output_test.connection(True)
        self.output_test.observe(raw)
        self._style_alarm_badge(state.active_alarm_count())
        self.system_page.update_connection_stats(
            True,
            self.backend.get_latency_avg_ma(),
            self.backend.total_polls,
            self.backend.error_count,
            self._last_success_ts,
        )
        if was_first and not self._dashboard_ticks_started:
            self._dashboard_ticks_started = True
            self.dashboard_page.start_local_ticks()
        if reconnecting:
            self.backend.probe_settings_endpoint()

    def _on_conn(self, online: bool, latency_ms: float) -> None:
        was_online = self._backend_online
        self._backend_online = online
        if online:
            self._offline_banner.hide()
            if not was_online:
                self.backend.probe_settings_endpoint()
        else:
            self._offline_banner.show()
            empty = SystemState.build_empty()
            if self._current_state is not None:
                previous = self._current_state
                readings = {
                    name: replace(getattr(previous, name), freshness=Freshness.STALE)
                    for name in ("temperature", "humidity", "door", "smoke", "water")
                }
                empty = replace(
                    previous, backend_online=False, **readings,
                    acus=[replace(acu, state=AcuiState.UNKNOWN) for acu in previous.acus],
                    alarms=[alarm for alarm in previous.alarms if alarm.key != "BACKEND_OFFLINE"]
                    + empty.alarms,
                )
            self._current_state = empty
            self._cascade_state(empty)
            self._style_alarm_badge(empty.active_alarm_count())

        self.control_page.set_backend_enabled(online)
        self.output_test.connection(online)

        if self._current_state is not None:
            self.logs_page.update_state(self._current_state)

        self.system_page.update_connection_stats(
            online,
            latency_ms if online else self.backend.get_latency_avg_ma(),
            self.backend.total_polls,
            self.backend.error_count,
            self._last_success_ts,
        )

    def _on_command_result(self, cmd_id: str, status: str, detail: str) -> None:
        if cmd_id.startswith(("mode-", "acu-", "sim-")):
            self.control_page.set_command_status(cmd_id, status, detail)
        elif cmd_id.startswith("probe-settings-"):
            if status in ("rejected", "failed"):
                self.settings_page.set_settings_endpoint_available(False)
        elif cmd_id.startswith("probe-info-"):
            info = self._pending_info.pop(cmd_id, {})
            self.system_page.update_backend_info(info)
        elif cmd_id.startswith("settings-"):
            self.settings_page.set_save_result(cmd_id, status, detail)

    def _on_backend_error(self, msg: str) -> None:
        self._append_diagnostic(f"ERROR: {msg}")

    def _on_backend_info_log(self, line: str) -> None:
        if "info " in line and "probe-info-" in line:
            try:
                import json
                prefix_candidates = ["probe-info-"]
                for cand in prefix_candidates:
                    marker_start = line.find("req ")
                    if marker_start >= 0:
                        rest = line[marker_start + 4:]
                        space_idx = rest.find(" ")
                        if space_idx >= 0:
                            cid = rest[:space_idx]
                            after = rest[space_idx + 1:]
                            if after.startswith("info ") and cid.startswith("probe-info-"):
                                payload_str = after[5:]
                                try:
                                    parsed = json.loads(payload_str)
                                    if isinstance(parsed, dict):
                                        self._pending_info[cid] = parsed
                                except Exception:
                                    self._pending_info[cid] = {"raw": payload_str}
            except Exception:
                pass
        self._append_diagnostic(line)

    def _append_diagnostic(self, line: str) -> None:
        logging.getLogger("coolshift_hmi").info(line)
        self._diagnostic_lines.append(line)
        if len(self._diagnostic_lines) > 200:
            self._diagnostic_lines = self._diagnostic_lines[-200:]
        self.system_page.set_diagnostic_log(list(self._diagnostic_lines))

    # ---- Page signal slots ----
    def _on_request_mode(self, mode: str) -> None:
        cmd_id = self.backend.post_mode(mode)
        self.control_page.set_command_status(cmd_id, "pending", f"Setting mode {mode}")

    def _on_request_acu_command(self, idx: int, action: str) -> None:
        if not self._backend_online:
            self.control_page.set_command_status("acu-offline", "failed", "Backend offline")
            return
        self.backend.post_acu_command(idx, action)

    def _on_request_save_settings(self, payload: dict) -> None:
        if (not self._backend_online or self.output_test.active
                or self.output_test.needs_end):
            self.settings_page.set_save_result(
                self.settings_page._pending_cmd_id, "failed",
                "Output testing / restoration pending" if self._backend_online else "Backend offline"
            )
            return
        cmd_id = self.backend.post_settings(payload)
        self.settings_page.set_save_result(cmd_id, "pending", "Saving...")

    def _on_probe_settings(self) -> None:
        self.backend.probe_settings_endpoint()

    def _on_settings_received(self, cmd_id: str, payload: dict) -> None:
        if self.settings_page.receive_settings(cmd_id, payload) and self._current_state is not None:
            previous = self._current_state
            elapsed = max(0, time.monotonic() - previous.received_monotonic)
            threshold = payload["effective"]["sensor_stale_seconds"]
            readings = {}
            for name in ("temperature", "humidity", "door", "smoke", "water"):
                reading = getattr(previous, name)
                freshness = Freshness.UNKNOWN
                if reading.value is not None and reading.age_s is not None:
                    freshness = (Freshness.OK if previous.backend_online
                                 and reading.age_s + elapsed <= threshold else Freshness.STALE)
                readings[name] = replace(reading, freshness=freshness)
            self._current_state = replace(
                previous, config_defaults=dict(payload["effective"]), **readings
            )
            self._cascade_state(self._current_state)

    def _on_request_events(self, limit: int) -> None:
        self.backend.fetch_events(limit)

    def _on_alarm_acknowledge(self, key: str) -> None:
        self._append_diagnostic(f"Local display acknowledgement; relay commands unchanged: key={key}")

    # ---- State cascade ----
    def _cascade_state(self, state: SystemState) -> None:
        self.dashboard_page.update_state(state)
        self.control_page.update_state(state)
        self.sensors_page.update_state(state)
        self.alarms_page.update_state(state)
        self.logs_page.update_state(state)
        self.settings_page.update_state(state)
        self.system_page.update_state(state)

    # ---- Lifecycle ----
    def start(self) -> None:
        self.show()
        QTimer.singleShot(0, self._start_async)

    def _start_async(self) -> None:
        if self._shutdown:
            return
        self.backend.start_polling(POLL_INTERVAL_MS)
        self.backend.probe_settings_endpoint()
        self.backend.probe_info_endpoint()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)

    def shutdown(self) -> None:
        if self._shutdown or self._shutdown_waiting:
            return
        self._shutdown_waiting = True
        self.backend.stop_polling()
        if self.output_test.needs_end:
            # Keep Qt networking alive for a bounded drain/end acknowledgement,
            # including close triggered from aboutToQuit or a POSIX signal.
            loop = QEventLoop(self)
            deadline = QTimer(self)
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            self.output_test.departure_ready.connect(loop.quit)
            self.output_test.end()
            if self.output_test.needs_end:
                deadline.start(2500)
                loop.exec()
            deadline.stop()
            self.output_test.departure_ready.disconnect(loop.quit)
            deadline.deleteLater()
            loop.deleteLater()
            if self.output_test.needs_end:
                self.output_test.uncertain = True
                self.output_test.message = (
                    "Restoration unconfirmed - shutdown deadline; backend lease recovery pending")
                self.output_test._refresh()
        self._shutdown = True
        self._shutdown_waiting = False
        self.backend.shutdown()
        for timer in self.findChildren(QTimer):
            timer.stop()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()
