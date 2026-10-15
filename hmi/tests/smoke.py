#!/usr/bin/env python3
from __future__ import annotations

import copy
import os
import sys
import time
import json
import signal
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt, QTimer, QCoreApplication, QEvent, QThread
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QPushButton,
        QSizePolicy,
        QStackedWidget,
        QStyle,
        QStyleOptionSlider,
        QToolButton,
        QWidget,
    )
except ImportError:
    sys.stderr.write("PySide6 not installed — skipping smoke tests\n")
    sys.exit(77)

from ..constants import (
    ALARM_DEFINITIONS,
    EVENT_KIND_ACU,
    EVENT_KIND_ALARM,
    EVENT_KIND_SYSTEM,
    MIN_TOUCH,
    PAGES,
    SCREEN_H,
    SCREEN_W,
    load_config_defaults,
)
from ..dialogs import ConfirmDialog, NumericKeypad
from ..system_state import (
    AcuiState,
    AlarmSeverity,
    Freshness,
    SystemState,
)
from ..widgets import (
    BigReadout,
    CountdownLabel,
    IndicatorLamp,
    StateBadge,
    StatusCard,
    StaleOverlay,
    large_button,
)


_results: List[Tuple[str, bool, str]] = []


def _record(test_id: str, passed: bool, message: str) -> None:
    _results.append((test_id, passed, message))


def make_fresh_status_payload(**overrides) -> dict:
    payload: dict = {
        "sensors": {
            "temperature_c": 24,
            "humidity_pct": 50,
            "door_open": False,
            "smoke_alarm": False,
            "water_level_alarm": False,
        },
        "sensor_age_s": {key: 0 for key in (
            "temperature_c", "humidity_pct", "door_open", "smoke_alarm", "water_level_alarm")},
        "alarm_outputs": dict(water=False, smoke=False, temperature=False, humidity=False, door=False),
        "mode": "auto",
        "acu_outputs": {"acu1": True, "acu2": False},
        "lead_acu": 1,
        "rotation_remaining_s": 3600,
        "handover_pending": None,
        "boost": False,
        "alarms": [],
        "simulation": False,
    }
    if overrides:
        for key, value in overrides.items():
            if key == "sensors" and isinstance(value, dict):
                payload["sensors"].update(value)
            elif key == "acu_outputs" and isinstance(value, dict):
                payload["acu_outputs"].update(value)
            else:
                payload[key] = value
    return payload


def make_settings_payload(**overrides) -> dict:
    effective = load_config_defaults()
    effective.update(overrides)
    return dict(effective=effective, defaults=load_config_defaults(),
                restart_required=["gpio", "simulation", "output_active_high", "input_pull"])


def check_widget_sizes(
    min_w: int = MIN_TOUCH, min_h: int = MIN_TOUCH
) -> Tuple[int, List[str]]:
    app = QApplication.instance()
    if app is None:
        return (0, [])
    fails: List[str] = []
    pass_count = 0
    for top in app.topLevelWidgets():
        for cls in (QPushButton, QToolButton):
            for btn in top.findChildren(cls):
                hint = btn.minimumSizeHint()
                mw = max(btn.minimumWidth(), hint.width())
                mh = max(btn.minimumHeight(), hint.height())
                name = btn.objectName() or btn.__class__.__name__
                text_snippet = ""
                if isinstance(btn, QPushButton):
                    text_snippet = btn.text()[:16]
                label = f"{name}"
                if text_snippet:
                    label += f" ('{text_snippet}')"
                if mw < min_w:
                    fails.append(f"{label}: width {mw} < {min_w}")
                elif mh < min_h:
                    fails.append(f"{label}: height {mh} < {min_h}")
                else:
                    pass_count += 1
    return (pass_count, fails)


# ---------------- TEST FUNCTIONS ----------------


def T01_widgets_smoke() -> Tuple[bool, str]:
    try:
        card = StatusCard(title="Test Card")
        card.setObjectName("test_status_card")
        if card.objectName() != "test_status_card":
            return (False, "StatusCard setObjectName failed")

        badge = StateBadge(state="on", text="Commanded ON")
        badge.setObjectName("test_state_badge")
        if badge.objectName() != "test_state_badge":
            return (False, "StateBadge setObjectName failed")

        readout = BigReadout(
            value_str="24.0", unit_str="\u00b0C", label_str="ROOM TEMP"
        )
        readout.setObjectName("test_readout")
        if readout.objectName() != "test_readout":
            return (False, "BigReadout setObjectName failed")

        lamp = IndicatorLamp(on=True, color="green", blink=False)
        lamp.setObjectName("test_lamp")
        if lamp.objectName() != "test_lamp":
            return (False, "IndicatorLamp setObjectName failed")

        countdown = CountdownLabel(seconds=60, label="Test Countdown")
        countdown.setObjectName("test_countdown")
        if countdown.objectName() != "test_countdown":
            return (False, "CountdownLabel setObjectName failed")

        inner = QLabel("Child")
        overlay = StaleOverlay(child=inner, enabled=False)
        overlay.setObjectName("test_overlay")
        if overlay.objectName() != "test_overlay":
            return (False, "StaleOverlay setObjectName failed")

        btn = large_button(text="Press Me", icon="!", variant="primary")
        btn.setObjectName("test_large_btn")
        if btn.objectName() != "test_large_btn":
            return (False, "large_button setObjectName failed")
        if btn.minimumWidth() < 48 or btn.minimumHeight() < 48:
            return (False, "large_button minimumSize too small")

        return (True, "All custom widgets instantiated without error")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T02_countdown_tick() -> Tuple[bool, str]:
    try:
        c = CountdownLabel(3605)
        lbl = c.findChild(QLabel, "Countdown")
        if lbl is None:
            return (False, "Could not find child QLabel#Countdown")

        if lbl.text() != "01:00:05":
            return (False, f"Initial display expected '01:00:05', got '{lbl.text()}'")

        now = time.monotonic()
        c._last_set_monotonic = now - 1
        c.tick_1s()
        if lbl.text() != "01:00:04":
            return (False, f"After 1 tick expected '01:00:04', got '{lbl.text()}'")

        c._last_set_monotonic = now - 2
        c.tick_1s()
        if lbl.text() != "01:00:03":
            return (False, f"After 2 ticks expected '01:00:03', got '{lbl.text()}'")

        c._last_set_monotonic = now - 3
        c.tick_1s()
        if lbl.text() != "01:00:02":
            return (False, f"After 3 ticks expected '01:00:02', got '{lbl.text()}'")

        return (True, "Countdown ticks displayed correctly")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T03_system_state_empty() -> Tuple[bool, str]:
    try:
        s = SystemState.build_empty()
        if s.backend_online is not False:
            return (False, f"backend_online={s.backend_online}, expected False")
        if len(s.acus) < 1 or s.acus[0].state != AcuiState.UNKNOWN:
            acu0_state = s.acus[0].state if len(s.acus) > 0 else None
            return (False, f"acus[0].state={acu0_state}, expected UNKNOWN")
        if s.temperature.freshness != Freshness.UNKNOWN:
            return (
                False,
                f"temperature.freshness={s.temperature.freshness}, expected UNKNOWN",
            )
        alarm_keys = [a.key for a in s.alarms]
        if "BACKEND_OFFLINE" not in alarm_keys:
            return (False, f"BACKEND_OFFLINE missing from alarms: {alarm_keys}")
        return (True, "build_empty() produces correct default state")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T04_system_state_command_only() -> Tuple[bool, str]:
    try:
        payload = make_fresh_status_payload(
            acu_outputs={"acu1": True, "acu2": False},
            sensors={
                "temperature_c": 24,
                "humidity_pct": 50,
                "door_open": False,
                "smoke_alarm": False,
            },
        )
        received = time.monotonic()
        s = SystemState.from_status_payload(
            payload, backend_online=True, received_monotonic_s=received
        )
        acu1 = s.acus[0]
        if acu1.state != AcuiState.ON or s.acus[1].state != AcuiState.OFF:
            return (
                False,
                f"ACU1.state={acu1.state}, expected Commanded ON",
            )
        missing = copy.deepcopy(payload)
        missing["acu_outputs"] = {}
        assert all(acu.state == AcuiState.UNKNOWN for acu in
                   SystemState.from_status_payload(missing, True, received).acus)
        return (True, "Command-only ON/OFF; missing commands UNKNOWN")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T05_sensor_none_not_zero() -> Tuple[bool, str]:
    try:
        payload = make_fresh_status_payload(
            sensors={
                "temperature_c": None,
                "humidity_pct": None,
                "door_open": None,
                "smoke_alarm": None,
                "water_level_alarm": None,
            },
        )
        received = time.monotonic()
        s = SystemState.from_status_payload(
            payload, backend_online=True, received_monotonic_s=received
        )

        if s.temperature.value is not None:
            return (
                False,
                f"temperature.value={s.temperature.value!r}, expected None",
            )
        if s.humidity.value is not None:
            return (
                False,
                f"humidity.value={s.humidity.value!r}, expected None",
            )
        if s.temperature.freshness not in (Freshness.STALE, Freshness.UNKNOWN):
            return (
                False,
                f"temperature.freshness={s.temperature.freshness}, expected STALE or UNKNOWN",
            )
        if s.humidity.freshness not in (Freshness.STALE, Freshness.UNKNOWN):
            return (
                False,
                f"humidity.freshness={s.humidity.freshness}, expected STALE or UNKNOWN",
            )
        if s.temperature.value == 0 or s.humidity.value == 0:
            return (False, "Sensor value equals integer 0 (should be None)")
        return (True, "None-valued sensors preserved, not zeroed")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T06_alarm_definitions_backend_offline() -> Tuple[bool, str]:
    try:
        if "BACKEND_OFFLINE" not in ALARM_DEFINITIONS:
            return (False, "BACKEND_OFFLINE missing from ALARM_DEFINITIONS")
        s = SystemState.build_empty()
        keys = [a.key for a in s.alarms]
        if "BACKEND_OFFLINE" not in keys:
            return (False, f"BACKEND_OFFLINE missing from build_empty alarms: {keys}")
        alarm = next((a for a in s.alarms if a.key == "BACKEND_OFFLINE"), None)
        if alarm is None:
            return (False, "BACKEND_OFFLINE alarm object not found")
        if alarm.severity != AlarmSeverity.CRITICAL:
            return (
                False,
                f"BACKEND_OFFLINE severity={alarm.severity}, expected CRITICAL",
            )
        return (True, "BACKEND_OFFLINE alarm present in definitions + empty state")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T07_page_layouts_no_scroll() -> Tuple[bool, str]:
    try:
        from ..main_window import CoolShiftHMI

        hmi = CoolShiftHMI(dev_mode=True)
        hmi._on_status_received(make_fresh_status_payload(
            alarms=["WATER_LEVEL_ALARM", "SMOKE_ALARM", "HIGH_TEMPERATURE", "HIGH_HUMIDITY"],
            alarm_outputs=dict(water=True, smoke=True, temperature=True, humidity=True, door=True)))
        hmi._on_settings_received("probe-settings-layout", make_settings_payload())
        hmi.show()

        stack = hmi.findChild(QStackedWidget, "main_stack")
        if stack is None:
            return (False, "Could not find QStackedWidget#main_stack")

        page_ids = [pid for (_name, pid) in PAGES]

        for page_id in page_ids:
            nav_btn = hmi.findChild(QPushButton, f"nav_btn_{page_id}")
            if nav_btn is None:
                return (False, f"Missing nav button for page '{page_id}'")
            nav_btn.click()
            QApplication.processEvents()
            expected_idx = hmi._page_index.get(page_id)
            if expected_idx is None:
                return (False, f"No page index for '{page_id}'")
            if stack.currentIndex() != expected_idx:
                return (
                    False,
                    f"After nav to '{page_id}', stack idx={stack.currentIndex()}, expected {expected_idx}",
                )
            current = stack.currentWidget()
            if current is None:
                return (False, f"currentWidget() None after nav to '{page_id}'")
            if hmi.width() != 800 or hmi.height() != 480:
                return False, f"Window grew to {hmi.size()}"
            widgets = current.findChildren(QWidget)
            buttons = current.findChildren(QPushButton)
            print(f"PAGE {page_id}: {len(widgets)} widgets, "
                  f"buttons={[button.objectName() for button in buttons]}")
            for widget in widgets:
                if not widget.isVisible():
                    continue
                # Scrollable content is checked against its viewport separately.
                ancestor = widget.parentWidget()
                scroll_child = False
                while ancestor is not None and ancestor is not current:
                    if ancestor.objectName() == "qt_scrollarea_viewport":
                        scroll_child = True
                    ancestor = ancestor.parentWidget()
                if scroll_child:
                    continue
                origin = widget.mapTo(current, widget.rect().topLeft())
                if origin.x() < 0 or origin.y() < 0 or (
                    origin.x() + widget.width() > current.width()
                    or origin.y() + widget.height() > current.height()
                ):
                    return False, f"{page_id}: {widget.objectName()} outside page: {origin}, {widget.size()}"
            for button in buttons:
                if not button.objectName():
                    return False, f"{page_id}: unnamed button {button.text()}"
                if button.width() < 48 or button.height() < 48:
                    return False, f"{page_id}: undersized {button.objectName()} {button.size()}"

        dashboard = hmi.dashboard_page
        required = [
            ("dashboard_temp_readout", "temp_readout"),
            ("dashboard_hum_readout", "hum_readout"),
            ("dashboard_acu1_card", "acu1_card"),
            ("dashboard_acu2_card", "acu2_card"),
            ("dashboard_mode_badge", "mode_badge"),
            ("dashboard_countdown", "countdown"),
            ("dashboard_boost_badge", "boost_badge"),
            ("dashboard_alarm_summary", "alarm_summary"),
            ("dashboard_backend_status", "backend_status"),
        ]
        missing = []
        for obj_name, friendly in required:
            w = dashboard.findChild(QWidget, obj_name)
            if w is None:
                missing.append(f"{friendly} (objectName='{obj_name}')")
        if missing:
            return (False, "Dashboard missing children: " + ", ".join(missing))

        hmi.close()
        if any(timer.isActive() for timer in hmi.findChildren(QTimer)):
            return False, "Window timers active after close"
        return (True, f"All {len(page_ids)} pages navigable, dashboard children present")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T08_button_min_sizes() -> Tuple[bool, str]:
    try:
        from ..main_window import CoolShiftHMI
        window = CoolShiftHMI(dev_mode=True)
        window.show()
        window._on_status_received(make_fresh_status_payload(alarms=["HIGH_TEMPERATURE"]))
        _pass_count, fails = check_widget_sizes(min_w=MIN_TOUCH, min_h=MIN_TOUCH)
        if len(fails) > 0:
            sample = "; ".join(fails[:5])
            if len(fails) > 5:
                sample += f" ... ({len(fails)} total)"
            return (False, f"{len(fails)} buttons too small: {sample}")
        return (True, f"All checked buttons >= {MIN_TOUCH}x{MIN_TOUCH}")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T09_confirm_dialog() -> Tuple[bool, str]:
    try:
        dlg = ConfirmDialog(None, "T", "msg", dangerous=True)

        if dlg.width() > SCREEN_W:
            return (False, f"Dialog width={dlg.width()} > SCREEN_W={SCREEN_W}")
        if dlg.height() > SCREEN_H:
            return (False, f"Dialog height={dlg.height()} > SCREEN_H={SCREEN_H}")

        buttons = dlg.findChildren(QPushButton)
        if len(buttons) < 2:
            return (False, f"Expected >=2 QPushButtons, found {len(buttons)}")

        confirm_btn = None
        cancel_btn = None
        for b in buttons:
            txt = b.text().strip().upper()
            if txt in ("CONFIRM", "OK"):
                confirm_btn = b
            elif txt == "CANCEL":
                cancel_btn = b

        if confirm_btn is None:
            texts = [b.text() for b in buttons]
            return (False, f"Confirm button not found. Buttons: {texts}")
        ct = confirm_btn.text().strip()
        if ct not in ("Confirm", "OK"):
            return (False, f"Confirm button text='{ct}', expected 'Confirm' or 'OK'")

        if cancel_btn is None:
            return (False, "Cancel button not found")

        if confirm_btn.objectName() != "Danger":
            return (
                False,
                f"Dangerous confirm btn objectName='{confirm_btn.objectName()}', expected 'Danger'",
            )

        return (True, "ConfirmDialog dangerous variant structured correctly")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T10_numeric_keypad() -> Tuple[bool, str]:
    try:
        dlg = NumericKeypad(
            None, None, min_value=0, max_value=50, decimals=1, unit="\u00b0C"
        )

        def _find_btn(text_suffix: str) -> Optional[QPushButton]:
            for b in dlg.findChildren(QPushButton):
                if b.text().strip() == text_suffix:
                    return b
            return None

        btn7 = _find_btn("7")
        btn_dot = _find_btn(".")
        btn3 = _find_btn("3")
        btn_ok = _find_btn("OK")

        if btn7 is None or btn_dot is None or btn3 is None or btn_ok is None:
            names = [b.text() for b in dlg.findChildren(QPushButton)]
            return (False, f"Keypad button missing. Buttons found: {names}")

        btn7.click()
        QApplication.processEvents()
        btn_dot.click()
        QApplication.processEvents()
        btn3.click()
        QApplication.processEvents()

        if dlg._entry != "7.3":
            return (False, f"Entry buffer expected '7.3', got '{dlg._entry}'")

        accepted = False

        def _on_accept() -> None:
            nonlocal accepted
            accepted = True

        dlg.accepted.connect(_on_accept)
        btn_ok.click()
        QApplication.processEvents()

        if not accepted:
            return (False, "OK click with 7.3 did not accept dialog")
        if dlg.value() != 7.3:
            return (False, f"value()={dlg.value()}, expected 7.3")

        dlg2 = NumericKeypad(
            None, None, min_value=0, max_value=50, decimals=1, unit="\u00b0C"
        )
        dlg2._entry = "55.0"
        dlg2._refresh_display()

        btn_ok2 = None
        for b in dlg2.findChildren(QPushButton):
            if b.text().strip() == "OK":
                btn_ok2 = b
                break

        error_lbl = dlg2._error_label
        before_visible = error_lbl.isVisible()
        btn_ok2.click() if btn_ok2 else None
        QApplication.processEvents()
        after_visible = error_lbl.isVisible()

        if error_lbl.isHidden() or not error_lbl.text():
            return (
                False,
                "55.0 entry (max 50) OK click did not show error label",
            )
        if dlg2.value() is not None:
            return (False, "value() should be None for rejected out-of-range entry")

        return (True, "NumericKeypad accepts 7.3, rejects 55.0 (>max 50)")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T11_settings_validator_bad_boost_pair() -> Tuple[bool, str]:
    try:
        from ..pages.settings import SettingsPage

        sp = SettingsPage()
        sp.set_settings_endpoint_available(False)

        sp._edited["boost_on_c"] = 22.0
        sp._edited["boost_off_c"] = 25.0

        sp._validate_all()

        if "boost_on_c" not in sp._errors:
            return (
                False,
                f"boost_on_c not in errors after pair conflict. errors={dict(sp._errors)}",
            )
        err_msg = sp._errors["boost_on_c"]
        if "boost" not in err_msg.lower() and "0.5" not in err_msg:
            return (False, f"Unexpected boost conflict error text: '{err_msg}'")
        return (True, "Settings validation flags boost_on <= boost_off conflict")
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T12_logs_filter_categories() -> Tuple[bool, str]:
    try:
        from ..pages.logs import LogsPage

        lp = LogsPage()

        kinds_counts: List[Tuple[str, int]] = [
            ("output", 50),
            ("alarm", 20),
            ("alarm_clear", 20),
            ("fault", 10),
            ("rotation", 10),
            ("mode", 10),
            ("engine_error", 10),
            ("simulation", 10),
            ("fault_reset", 10),
        ]
        rows: List[dict] = []
        i = 0
        for kind, count in kinds_counts:
            for _ in range(count):
                rows.append(
                    {
                        "ts": f"2025-01-01 00:{(i % 60):02d}:00",
                        "kind": kind,
                        "detail": f"sample event {kind} #{i}",
                    }
                )
                i += 1
        if len(rows) != 150:
            return (False, f"Built {len(rows)} rows, expected 150")

        lp._all_rows = rows
        lp._current_filter = "ALL"
        lp._apply_filter()
        all_count = len(lp._filtered_rows)
        if all_count != 150:
            return (False, f"ALL filter: {all_count} rows, expected 150")

        lp._current_filter = "ACU"
        lp._apply_filter()
        acu_count = len(lp._filtered_rows)
        expected_acu = sum(1 for r in rows if r.get("kind") in EVENT_KIND_ACU)
        if acu_count != expected_acu:
            return (
                False,
                f"ACU filter: {acu_count} rows, expected {expected_acu}",
            )

        lp._current_filter = "ALARM"
        lp._apply_filter()
        alarm_count = len(lp._filtered_rows)
        expected_alarm = sum(1 for r in rows if r.get("kind") in EVENT_KIND_ALARM)
        if alarm_count != expected_alarm:
            return (
                False,
                f"ALARM filter: {alarm_count} rows, expected {expected_alarm}",
            )

        lp._current_filter = "SYSTEM"
        lp._apply_filter()
        sys_count = len(lp._filtered_rows)
        expected_sys = sum(1 for r in rows if r.get("kind") in EVENT_KIND_SYSTEM)
        if sys_count != expected_sys:
            return (
                False,
                f"SYSTEM filter: {sys_count} rows, expected {expected_sys}",
            )

        return (
            True,
            f"Filters correct: ALL={all_count} / ACU={acu_count} / "
            f"ALARM={alarm_count} / SYSTEM={sys_count}",
        )
    except Exception as exc:
        return (False, f"Exception: {type(exc).__name__}: {exc}")


def T13_dialog_flows_and_bounds() -> Tuple[bool, str]:
    parent = QWidget()
    parent.setFixedSize(800, 480)
    parent.show()
    for accept in (True, False):
        dialog = ConfirmDialog(parent, "Confirm", "Test action", dangerous=True)
        QTimer.singleShot(0, dialog.accept if accept else dialog.reject)
        assert (dialog.exec() == QDialog.Accepted) == accept
    for entry, valid in (("27.3", True), ("55.0", False), ("12.34", False)):
        dialog = NumericKeypad(parent, None, 0, 50, decimals=1)
        dialog.show()
        QApplication.processEvents()
        assert dialog.frameGeometry().width() <= 800
        assert dialog.frameGeometry().height() <= 480
        for button in dialog.findChildren(QPushButton):
            if button.isVisible():
                assert button.width() >= 48 and button.height() >= 48
                assert dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight()))
        dialog._entry = entry
        dialog._on_enter()
        assert (dialog.value() is not None) == valid
        dialog.reject()
    return True, "Confirm accept/cancel; keypad bounds, precision and range verified"


def T14_acceptance_inventory_and_behavior() -> Tuple[bool, str]:
    from ..main_window import CoolShiftHMI
    from unittest.mock import patch
    window = CoolShiftHMI(dev_mode=True)
    window.show()
    window._on_status_received(make_fresh_status_payload())
    window._on_settings_received("probe-settings-test", make_settings_payload())
    inventory = {
        "AC-1": "dashboard_temp_readout", "AC-2": "main_stack",
        "AC-3": "nav_btn_dashboard", "AC-4": "system_conn_counters",
        "AC-5": "header_offline_banner", "AC-6": "control_acu1_card",
        "AC-7": "control_command_banner", "AC-8": "sensors_temp_readout",
        "AC-9": "alarms_active_list", "AC-10": "logs_table",
        "AC-11": "settings_field_booston_btn", "AC-12": "dashboard_countdown",
        "AC-13": "RootWidget", "AC-14": "dashboard_backend_status",
        "AC-15": "settings_field_rotation_btn", "AC-16": "system_conn_latency",
    }
    for criterion, name in inventory.items():
        assert window.objectName() == name or window.findChild(QWidget, name) is not None
        print(f"INVENTORY {criterion}: {name}")
    assert window.system_page._conn_last_lbl.text() != "N/A"
    control = window.control_page
    commands = []
    control.request_mode.connect(commands.append)
    with patch.object(ConfirmDialog, "confirm", return_value=False):
        control.mode_pause_btn.click()
    assert not commands
    with patch.object(ConfirmDialog, "confirm", return_value=True):
        control.mode_pause_btn.click()
    assert commands == ["pause"]
    acu_commands = []
    control.request_acu_command.connect(lambda acu, action: acu_commands.append((acu, action)))
    assert not control.acu1_card["start_btn"].isEnabled()
    with patch.object(window.backend, "post_acu_command", return_value="acu-test") as post:
        with patch.object(ConfirmDialog, "confirm", return_value=True):
            control.mode_manual_btn.click()
            assert commands[-1] == "manual"
            assert not control.acu1_card["start_btn"].isEnabled()
            raw = make_fresh_status_payload()
            raw["mode"] = "manual"
            window._on_status_received(raw)
            assert window._current_state.mode_display() == "MANUAL"
            for acu, card in enumerate((control.acu1_card, control.acu2_card), 1):
                assert card["start_btn"].text() == "ON"
                assert card["stop_btn"].text() == "OFF"
                assert card["start_btn"].isEnabled() and card["stop_btn"].isEnabled()
                card["start_btn"].click()
                post.assert_called_with(acu, "on")
                card["stop_btn"].click()
                post.assert_called_with(acu, "off")
            assert acu_commands == [(1, "on"), (1, "off"), (2, "on"), (2, "off")]
            raw["alarms"] = ["CONTROLLER_ERROR"]
            window._on_status_received(raw)
            assert not control.acu1_card["start_btn"].isEnabled()
            assert not control.mode_manual_btn.isEnabled()
            raw["alarms"] = []
            raw["mode"] = "pause"
            window._on_status_received(raw)
            assert not control.acu2_card["stop_btn"].isEnabled()
    control.set_command_status("mode-test", "rejected", "HTTP 409")
    assert "REJECTED" in control.command_banner.text()
    control.set_command_status("acu-test", "failed", "GPIO write failed")
    assert "FAILED" in control.command_banner.text()
    assert "GPIO write failed" in control.command_banner.text()
    settings = window.settings_page
    settings._edited["min_restart_minutes"] = 1
    settings._edited["rotation_hours"] = 0.1
    settings._validate_all()
    assert "rotation_hours" in settings._errors
    assert "min_restart_minutes" not in settings._errors
    settings._refresh_all_views()
    assert settings._is_dirty() and not settings._save_btn.isEnabled()
    settings._on_revert()
    assert not settings._is_dirty()
    assert settings._field_buttons["min_restart_minutes"] is not None
    for minutes in (0, 1, 2):
        settings._edited["min_restart_minutes"] = minutes
        settings._validate_all()
        assert "min_restart_minutes" not in settings._errors
        settings._refresh_all_views()
        assert settings._is_dirty() and settings._save_btn.isEnabled()
        assert settings._build_payload()["min_off_seconds"] == minutes * 60
        settings._on_revert()
    logs = window.logs_page
    requests = []
    logs.request_events.connect(requests.append)
    logs.update_events([{"kind": "mode", "ts": "", "detail": str(i)} for i in range(205)])
    logs._next_btn.click()
    assert logs._page == 1 and logs._table.rowCount() == 40 and not requests
    window._on_conn(False, 0)
    assert window._offline_banner.isVisible()
    assert window._current_state.temperature.value == 24
    assert window._current_state.temperature.freshness == Freshness.STALE
    assert all(acu.state == AcuiState.UNKNOWN for acu in window._current_state.acus)
    assert not control.mode_auto_btn.isEnabled()
    window._on_status_received(make_fresh_status_payload())
    window._on_conn(True, 1)
    assert control.mode_auto_btn.isEnabled()
    window.close()
    return True, "AC-1..16 widget inventory and cross-page behavior verified"


def T15_backend_async_timeout_recovery() -> Tuple[bool, str]:
    from ..backend_client import BackendClient
    mode = {"response": "ok"}
    server_threads = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            server_threads.append(threading.get_ident())
            if mode["response"] == "delay":
                time.sleep(0.3)
            response = mode["response"]
            body = (b"not-json" if response == "malformed" else
                    json.dumps([] if self.path.startswith("/api/events") else
                               make_fresh_status_payload()).encode())
            self.send_response(500 if response == "error" else 200)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(409 if mode["response"] == "reject" else 200)
            self.end_headers()
            self.wfile.write(b'{"detail":"test response"}' if mode["response"] == "reject"
                             else json.dumps(make_fresh_status_payload()).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = BackendClient(f"http://127.0.0.1:{server.server_port}", timeout_ms=100)
    signals = []
    results = []
    online = []
    errors = []
    client.command_result.connect(lambda *args: results.append(args))
    client.connection_state_changed.connect(lambda state, latency: online.append(state))
    client.error.connect(errors.append)
    client.status_received.connect(
        lambda raw: signals.append(QThread.currentThread() == QApplication.instance().thread()))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)

    def wait_for(predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        assert predicate(), "Timed out waiting for network result"

    try:
        for _ in range(10):
            cid = client.fetch_status()
            wait_for(lambda: any(row[0] == cid and row[1] == "accepted" for row in results))
        for command in (lambda: client.post_mode("pause"), lambda: client.post_mode("auto"),
                        lambda: client.post_acu_command(1, "on"),
                        lambda: client.post_acu_command(2, "off"),
                        client.fetch_events, client.fetch_events):
            cid = command()
            wait_for(lambda: any(row[0] == cid and row[1] == "accepted" for row in results))
        mode["response"] = "reject"
        cid = client.post_mode("pause")
        wait_for(lambda: any(row[0] == cid and row[1] == "rejected" for row in results))
        assert any(row[2] == "test response" for row in results)
        cid = client.post_acu_command(1, "on")
        wait_for(lambda: any(row[0] == cid and row[1] == "rejected" for row in results))
        for response in ("malformed", "error", "delay"):
            mode["response"] = response
            cid = client.fetch_status()
            wait_for(lambda: any(row[0] == cid and row[1] == "failed" for row in results))
        mode["response"] = "ok"
        cid = client.fetch_status()
        wait_for(lambda: any(row[0] == cid and row[1] == "accepted" for row in results))
        assert signals and all(signals)
        assert all(thread != threading.get_ident() for thread in server_threads)
        assert False in online and online[-1] is True and errors
        assert len(ticks) > 10
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.5
        client.shutdown()
        assert not client._replies and not client._poll_timer.isActive()
    finally:
        timer.stop()
        client.shutdown()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        client.deleteLater()
    return True, "QNAM asynchronous I/O; GUI signals, HTTP 409/500, bad JSON, timeout, recovery"


def T16_entrypoint_and_deployment() -> Tuple[bool, str]:
    from ..constants import APP_NAME, LOG_FILE
    from ..main_window import CoolShiftHMI

    root = Path(__file__).resolve().parents[2]
    assert APP_NAME == "acuPilot"
    assert LOG_FILE.name == "coolshift_hmi.log"
    window = CoolShiftHMI(dev_mode=True)
    assert window.windowTitle() == "acuPilot HMI Dev"
    assert window.findChild(QLabel, "Title").text() == "acuPilot"
    window.close()
    help_result = subprocess.run(
        [sys.executable, str(root / "hmi.py"), "--help"],
        capture_output=True, text=True, timeout=5, cwd=root)
    assert help_result.returncode == 0 and "acuPilot HMI" in help_result.stdout
    import ast
    entry_tree = ast.parse((root / "main.py").read_text())
    assert any(isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "app" for target in node.targets
    ) for node in ast.walk(entry_tree)), "main:app launch compatibility missing"
    factory_path = root / "backend/api.py"
    backend_tree = ast.parse(factory_path.read_text()) if factory_path.exists() else entry_tree
    api_titles = [
        keyword.value.value
        for node in ast.walk(backend_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "FastAPI"
        for keyword in node.keywords
        if keyword.arg == "title" and isinstance(keyword.value, ast.Constant)
    ]
    assert api_titles == ["acuPilot Backend"]
    unit = (root / "deploy/coolshift-hmi.service").read_text()
    assert "Description=acuPilot HMI" in unit
    for field in ("[Unit]", "[Service]", "[Install]", "Environment=DISPLAY=:0",
                  "ExecStart=", "Restart=on-failure"):
        assert field in unit
    assert "PySide6>=6.5,<7" in (root / "requirements.txt").read_text()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        process = subprocess.Popen(
            [sys.executable, str(root / "hmi.py"), "--dev",
             "--backend-url", "http://127.0.0.1:1"],
            cwd=root, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # Wait for startup through the real entry point's flushed logger.
            output = ""
            import selectors
            selector = selectors.DefaultSelector()
            selector.register(process.stderr, selectors.EVENT_READ)
            deadline = time.monotonic() + 10
            while "HMI event loop starting" not in output and time.monotonic() < deadline:
                if selector.select(timeout=0.2):
                    output += process.stderr.readline()
                if process.poll() is not None:
                    break
            selector.close()
            assert "HMI event loop starting" in output, output
            process.send_signal(shutdown_signal)
            stdout, stderr = process.communicate(timeout=5)
            output += stderr
            assert "acuPilot HMI v" in output
            assert "http://127.0.0.1:1" in output
            assert process.returncode == 0, output
            assert "HMI shutting down" in output
            assert "Traceback" not in output and "QThread: Destroyed" not in output, output
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    return True, "Real --dev launch exits cleanly on SIGINT and SIGTERM; artifacts present"


# ---------------- MAIN ----------------

def T17_command_sensors_and_concurrent_alarms() -> Tuple[bool, str]:
    from ..main_window import CoolShiftHMI
    window = CoolShiftHMI(dev_mode=True)
    window.show()
    payload = make_fresh_status_payload(
        mode="pause", acu_outputs=dict(acu1=False, acu2=False),
        sensors=dict(water_level_alarm=True, smoke_alarm=True),
        alarms=["WATER_LEVEL_ALARM", "SMOKE_ALARM", "HIGH_TEMPERATURE", "HIGH_HUMIDITY"],
        alarm_outputs=dict(water=True, smoke=True, temperature=True, humidity=True, door=True),
        sensor_age_s=dict(temperature_c=35, humidity_pct=0, door_open=0,
                          smoke_alarm=0, water_level_alarm=0),
    )
    window._on_status_received(payload)
    state = window._current_state
    assert state.temperature.freshness == Freshness.STALE
    assert state.humidity.freshness == Freshness.OK and state.water.freshness == Freshness.OK
    assert state.last_sensor_update_age_s() >= 35
    authoritative = copy.deepcopy(payload)
    authoritative["sensor_freshness"] = {"temperature_c": "OK"}
    assert SystemState.from_status_payload(
        authoritative, True, time.monotonic()).temperature.freshness == Freshness.OK
    assert window.sensors_page._water_value.text().startswith("ALARM")
    for label in window.sensors_page._relay_values.values():
        assert "Commanded ON" in label.text()
    for page in (window.dashboard_page, window.control_page):
        for card in (page.acu1_card, page.acu2_card):
            assert card["state_badge"]._text_label.text() == "Commanded OFF"
            assert card["commanded_label"].text() == "Relay command only"
    assert not window.control_page.acu1_card["start_btn"].isEnabled()
    assert window.alarms_page._active_list.count() == 4
    item = window.alarms_page._active_list.item(0)
    window.alarms_page._active_list.itemWidget(item).ack_button.click()
    assert all(window._current_state.alarm_outputs.values())
    window._on_conn(False, 0)
    assert all("UNKNOWN (STALE)" in label.text()
               for label in window.sensors_page._relay_values.values())
    assert "STALE" in window.sensors_page._water_value.text()
    for page in (window.dashboard_page, window.control_page):
        for card in (page.acu1_card, page.acu2_card):
            assert card["state_badge"]._text_label.text() == "UNKNOWN"
            assert card["commanded_label"].text() == "UNKNOWN / STALE command"
    window._on_status_received(make_fresh_status_payload())
    for page in (window.dashboard_page, window.control_page):
        assert page.acu1_card["state_badge"]._text_label.text() == "Commanded ON"
        assert page.acu2_card["state_badge"]._text_label.text() == "Commanded OFF"
        for card in (page.acu1_card, page.acu2_card):
            assert card["commanded_label"].text() == "Relay command only"
    window._on_status_received(make_fresh_status_payload(
        sensors=dict(temperature_c=None, humidity_pct=None)))
    assert window.dashboard_page.temp_readout._condition_indicator.text() == "UNKNOWN"
    assert window.sensors_page._temp_readout._condition_indicator.text() == "UNKNOWN"
    window.close()
    return True, "Independent ages; water, five concurrent relay commands, local ACK and offline truth"


def T18_settings_authoritative_snapshot_safety() -> Tuple[bool, str]:
    from ..pages.settings import SettingsPage
    from unittest.mock import patch
    page = SettingsPage()
    page.update_state(SystemState.from_status_payload(make_fresh_status_payload(), True, time.monotonic()))
    assert not page._state_loaded and not page._save_btn.isEnabled()
    assert page.receive_settings("probe-settings-test", make_settings_payload(high_temp_alarm_c=20))
    assert page._saved["high_temp_c"] == 20 and not page._errors
    assert page._field_buttons["door_active_high"].text() == "LOW"
    assert page._field_buttons["high_temp_c"].toolTip() == "Default: 30.0 \u00b0C"
    page._on_edit_field("water_active_high")
    assert page._build_payload()["input_active_high"]["water"] is False
    page._edited["water_alarm_seconds"] = 2
    page._validate_all()
    page._refresh_all_views()
    requests = []
    page.request_save_settings.connect(lambda payload: (
        requests.append(copy.deepcopy(payload)),
        page.set_save_result("settings-test", "pending")))
    with patch.object(ConfirmDialog, "confirm", return_value=True):
        page._on_save()
    assert len(requests) == 1 and not page._save_btn.isEnabled()
    assert not page._revert_btn.isEnabled()
    page._edited["water_alarm_seconds"] = 7
    page._refresh_all_views()
    with patch.object(ConfirmDialog, "confirm", return_value=True):
        page._on_save()
    assert len(requests) == 1
    assert not page.receive_settings("settings-unrelated", make_settings_payload())
    assert page.receive_settings("settings-test", make_settings_payload(**requests[0]))
    page.set_save_result("settings-test", "accepted")
    assert page._saved["water_alarm_seconds"] == 2
    assert page._edited["water_alarm_seconds"] == 7 and page._is_dirty()
    assert page._save_btn.isEnabled()
    page._on_revert()
    assert page._edited["water_alarm_seconds"] == 2 and not page._is_dirty()
    page._edited["water_alarm_seconds"] = 8
    page._refresh_all_views()
    with patch.object(ConfirmDialog, "confirm", return_value=True):
        page._on_save()
    page.set_save_result("settings-test", "rejected", "Persistence failed")
    assert page._saved["water_alarm_seconds"] == 2 and page._edited["water_alarm_seconds"] == 8
    assert "Persistence failed" in page._error_detail.text()
    assert page._field_default_labels["water_active_high"].text() == "Default: HIGH"
    page.update_state(SystemState.build_empty())
    assert not page._save_btn.isEnabled()
    with patch.object(ConfirmDialog, "confirm", return_value=True):
        page._on_save()
    assert len(requests) == 2
    assert page._revert_btn.isEnabled()
    for key, value in (("high_temp_c", float("nan")), ("high_humidity_pct", 101),
                       ("water_alarm_seconds", -1), ("sensor_poll_seconds", 1)):
        page._edited[key] = value
        page._validate_all()
        assert key in page._errors
        page._on_revert()
    page._edited["boost_on_c"] = page._edited["boost_off_c"]
    page._validate_all()
    assert "boost_on_c" in page._errors
    page._on_revert()
    page._edited["sensor_stale_seconds"] = page._edited["sensor_poll_seconds"]
    page._validate_all()
    assert "sensor_stale_seconds" in page._errors
    return True, "Server defaults/effective values, HIGH/LOW, rejection, offline and pending snapshots"


def T19_settings_network_contract() -> Tuple[bool, str]:
    from ..backend_client import BackendClient
    behavior = {"response": "ok"}
    calls = []
    settings = make_settings_payload()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data):
            response = behavior["response"]
            self.send_response(422 if response == "reject" else 200)
            self.end_headers()
            body = (b'{"detail":"Invalid boost pair"}' if response == "reject" else
                    b'{"effective":{}}' if response == "malformed" else json.dumps(data).encode())
            self.wfile.write(body)

        def do_GET(self):
            calls.append(("GET", self.path))
            self.respond(settings)

        def do_PATCH(self):
            calls.append(("PATCH", self.path))
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if behavior["response"] == "ok":
                settings["effective"].update(payload)
            self.respond(settings)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = BackendClient(f"http://127.0.0.1:{server.server_port}")
    responses, results = [], []
    client.settings_received.connect(lambda *args: responses.append(args))
    client.command_result.connect(lambda *args: results.append(args))

    def wait(cid):
        deadline = time.monotonic() + 3
        while not any(row[0] == cid and row[1] != "pending" for row in results):
            assert time.monotonic() < deadline
            QTest.qWait(10)

    try:
        cid = client.probe_settings_endpoint()
        wait(cid)
        assert responses[-1][0] == cid and responses[-1][1]["effective"]["input_active_high"]["door"] is False
        cid = client.post_settings({"water_alarm_seconds": 5})
        wait(cid)
        assert responses[-1][1]["effective"]["water_alarm_seconds"] == 5
        behavior["response"] = "reject"
        cid = client.post_settings({"boost_on_c": 1})
        wait(cid)
        assert results[-1] == (cid, "rejected", "Invalid boost pair")
        behavior["response"] = "malformed"
        cid = client.post_settings({"water_alarm_seconds": 6})
        wait(cid)
        assert results[-1][1] == "failed" and len(responses) == 2
        assert calls == [("GET", "/api/settings")] + [("PATCH", "/api/settings")] * 3
    finally:
        client.shutdown()
        client.deleteLater()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    return True, "GET/PATCH emit effective settings before acceptance; malformed/rejected responses visible"


def T20_review_geometry_scroll_ranges_freshness() -> Tuple[bool, str]:
    from ..main_window import CoolShiftHMI
    from unittest.mock import patch
    window = CoolShiftHMI(dev_mode=True)
    window.backend.probe_settings_endpoint = lambda: "probe-settings-review"
    window.show()
    window._on_status_received(make_fresh_status_payload(
        alarms=["WATER_LEVEL_ALARM", "SMOKE_ALARM", "HIGH_TEMPERATURE", "HIGH_HUMIDITY"],
        alarm_outputs=dict(water=True, smoke=True, temperature=True, humidity=True, door=True),
        sensor_age_s=dict(temperature_c=45, humidity_pct=45, door_open=0,
                          smoke_alarm=0, water_level_alarm=0)))
    window._on_settings_received("probe-settings-review", make_settings_payload(
        rotation_seconds=200 * 3600, min_off_seconds=120 * 60,
        handover_overlap_seconds=180, sensor_stale_seconds=60))
    QApplication.processEvents()
    dashboard = window.dashboard_page
    assert window._current_state.temperature.freshness == Freshness.OK
    assert "stale" not in dashboard.last_update.text().lower()
    assert dashboard.temp_readout._condition_indicator.text() != "STALE"
    for label in (dashboard.alarm_summary, dashboard.relay_summary, dashboard.water_status):
        needed = label.heightForWidth(label.width())
        assert label.height() >= needed, (label.text(), label.height(), needed)
        origin = label.mapTo(dashboard, label.rect().topLeft())
        assert dashboard.rect().contains(origin)
        assert dashboard.rect().contains(label.mapTo(dashboard, label.rect().bottomRight()))
        print(f"GEOMETRY {label.text().splitlines()[0]}: actual={label.height()} required={needed}")
    assert dashboard.relay_summary.text().count("Commanded ON") == 5
    window.navigate_to("settings")
    QApplication.processEvents()
    page = window.settings_page
    assert not page._errors, page._errors
    page._edited["high_humidity_pct"] = 70
    page._validate_all()
    page._refresh_all_views()
    assert page._save_btn.isEnabled()
    down = page.findChild(QPushButton, "settings_scroll_down")
    up = page.findChild(QPushButton, "settings_scroll_up")
    assert down.width() >= 48 and down.height() >= 48
    bar = page._scroll.verticalScrollBar()
    assert bar.width() >= 48
    for key in ("water_alarm_seconds", "door_active_high", "water_active_high", "smoke_active_high"):
        button = page._field_buttons[key]
        for _ in range(20):
            origin = button.mapTo(page._scroll.viewport(), button.rect().topLeft())
            if page._scroll.viewport().rect().contains(origin) and page._scroll.viewport().rect().contains(
                    button.mapTo(page._scroll.viewport(), button.rect().bottomRight())):
                break
            down.click()
            QApplication.processEvents()
        else:
            raise AssertionError(f"{key} inaccessible with touch scroll controls")
        assert button.width() >= 48 and button.height() >= 48
        if key.endswith("active_high"):
            before = page._edited[key]
            QTest.mouseClick(button, Qt.LeftButton)
            assert page._edited[key] != before
        else:
            with patch.object(NumericKeypad, "get_value", return_value=4):
                QTest.mouseClick(button, Qt.LeftButton)
            assert page._edited[key] == 4
    old = bar.value()
    up.click()
    assert bar.value() < old
    page._edited["door_delay_s"] = 10000
    page._edited["water_alarm_seconds"] = 100000
    page._edited["control_tick_seconds"] = 0.01
    page._validate_all()
    assert not page._errors, page._errors
    window._on_settings_received("probe-settings-review", make_settings_payload(sensor_stale_seconds=30))
    assert window._current_state.temperature.freshness == Freshness.STALE
    assert "stale" in dashboard.last_update.text().lower()
    window.close()
    return True, "Five-relay text fits; 48px touch scrolling reaches lower fields; backend ranges and freshness"


def T21_alarm_list_touch_scrolling() -> Tuple[bool, str]:
    from ..main_window import CoolShiftHMI

    window = CoolShiftHMI(dev_mode=True)
    try:
        window.show()
        window.navigate_to("alarms")
        page = window.alarms_page
        relay_outputs = dict(water=True, smoke=True, temperature=True, humidity=True, door=True)

        def update(keys):
            page.update_state(SystemState.from_status_payload(
                make_fresh_status_payload(alarms=keys, alarm_outputs=relay_outputs),
                True, time.monotonic()))
            QApplication.processEvents()

        cleared_keys = [f"CLEARED_{i:02d}" for i in range(50)]
        update(cleared_keys)
        active_keys = list(ALARM_DEFINITIONS)
        update(active_keys)
        assert page._recent_list.count() == 50
        assert window.size().width() == 800 and window.size().height() == 480
        summary = page._relay_summary
        assert summary.text().count("Commanded ON") == 5
        assert summary.height() >= summary.heightForWidth(summary.width())
        assert page.rect().contains(summary.mapTo(page, summary.rect().topLeft()))
        assert page.rect().contains(summary.mapTo(page, summary.rect().bottomRight()))

        acknowledgements = []
        page.acknowledge_request.connect(acknowledgements.append)
        for alarm_list in (page._active_list, page._recent_list):
            viewport = alarm_list.viewport()
            bar = alarm_list.verticalScrollBar()
            assert bar.isVisible() and bar.maximum() > 0, alarm_list.objectName()
            assert bar.width() >= MIN_TOUCH, (alarm_list.objectName(), bar.size())
            assert viewport.height() >= 60, viewport.size()
            assert page.rect().contains(alarm_list.mapTo(page, alarm_list.rect().topLeft()))
            assert page.rect().contains(alarm_list.mapTo(page, alarm_list.rect().bottomRight()))

            def slider_rect():
                option = QStyleOptionSlider()
                bar.initStyleOption(option)
                return bar.style().subControlRect(
                    QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, bar)

            # Check real style geometry, not just QSS or minimum size hints.
            bar.setValue(bar.minimum())
            QApplication.processEvents()
            handle = slider_rect()
            assert handle.width() >= MIN_TOUCH and handle.height() >= MIN_TOUCH, handle
            assert bar.rect().contains(handle)
            start = handle.center()
            end = start + bar.rect().bottomLeft() - handle.bottomLeft()
            assert end.y() > start.y(), (bar.size(), handle)
            QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, start)
            QTest.mouseMove(bar, end)
            QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, end)
            QApplication.processEvents()
            assert bar.value() == bar.maximum(), (bar.value(), bar.maximum())
            final_handle = slider_rect()
            assert final_handle.width() >= MIN_TOUCH and final_handle.height() >= MIN_TOUCH
            assert bar.rect().contains(final_handle)
            final_item = alarm_list.item(alarm_list.count() - 1)
            assert viewport.rect().contains(alarm_list.visualItemRect(final_item))

            for i in range(alarm_list.count()):
                row = alarm_list.itemWidget(alarm_list.item(i))
                description = row._desc_label
                assert description.height() >= description.heightForWidth(description.width()), (
                    row.alarm_key, description.size())
                assert description.width() >= 240
                for child in (description, row.ack_button, row._status_label):
                    assert row.rect().contains(child.mapTo(row, child.rect().topLeft()))
                    assert row.rect().contains(child.mapTo(row, child.rect().bottomRight()))
                assert row.ack_button.width() >= MIN_TOUCH
                assert row.ack_button.height() >= MIN_TOUCH
                assert row.width() <= viewport.width()

            final_row = alarm_list.itemWidget(final_item)
            assert viewport.rect().contains(final_row.ack_button.mapTo(
                viewport, final_row.ack_button.rect().bottomRight()))
            if alarm_list is page._active_list:
                QTest.mouseClick(final_row.ack_button, Qt.LeftButton)
                assert acknowledgements == [final_row.alarm_key]
                assert final_row.acknowledged
                assert summary.text().count("Commanded ON") == 5
            print(f"ALARM SCROLL {alarm_list.objectName()}: rows={alarm_list.count()}, "
                  f"viewport={viewport.width()}x{viewport.height()}, "
                  f"bar={bar.width()}x{bar.height()}, "
                  f"handle={handle.width()}x{handle.height()}, final={final_row.alarm_key}")
        return True, "Both overflowing lists: rendered >=48px bars/handles, drag to final row, readable rows/ACK/relays"
    finally:
        window.close()


_TESTS = [
    ("T01_widgets_smoke", T01_widgets_smoke),
    ("T02_countdown_tick", T02_countdown_tick),
    ("T03_system_state_empty", T03_system_state_empty),
    (
        "T04_system_state_command_only",
        T04_system_state_command_only,
    ),
    ("T05_sensor_none_not_zero", T05_sensor_none_not_zero),
    ("T06_alarm_definitions_backend_offline", T06_alarm_definitions_backend_offline),
    ("T07_page_layouts_no_scroll", T07_page_layouts_no_scroll),
    ("T08_button_min_sizes", T08_button_min_sizes),
    ("T09_confirm_dialog", T09_confirm_dialog),
    ("T10_numeric_keypad", T10_numeric_keypad),
    ("T11_settings_validator_bad_boost_pair", T11_settings_validator_bad_boost_pair),
    ("T12_logs_filter_categories", T12_logs_filter_categories),
    ("T13_dialog_flows_and_bounds", T13_dialog_flows_and_bounds),
    ("T14_acceptance_inventory_and_behavior", T14_acceptance_inventory_and_behavior),
    ("T15_backend_async_timeout_recovery", T15_backend_async_timeout_recovery),
    ("T16_entrypoint_and_deployment", T16_entrypoint_and_deployment),
    ("T17_command_sensors_and_concurrent_alarms", T17_command_sensors_and_concurrent_alarms),
    ("T18_settings_authoritative_snapshot_safety", T18_settings_authoritative_snapshot_safety),
    ("T19_settings_network_contract", T19_settings_network_contract),
    ("T20_review_geometry_scroll_ranges_freshness", T20_review_geometry_scroll_ranges_freshness),
    ("T21_alarm_list_touch_scrolling", T21_alarm_list_touch_scrolling),
]


def main() -> int:
    from .output_testing import TESTS as output_test_tests
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    from ..theme import set_app_fonts
    set_app_fonts(app)

    for test_id, test_fn in _TESTS + output_test_tests:
        try:
            passed, message = test_fn()
        except Exception as exc:
            passed = False
            message = f"UNCAUGHT {type(exc).__name__}: {exc}"
        _record(test_id, passed, message)
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()

    pass_count = sum(1 for _tid, ok, _msg in _results if ok)
    fail_count = len(_results) - pass_count

    width_id = max(len(tid) for tid, _ok, _msg in _results)
    width_status = 6

    print()
    print("=" * (width_id + width_status + 4 + 40))
    print(
        f"{'TEST':<{width_id}}  {'RESULT':<{width_status}}  MESSAGE"
    )
    print("-" * (width_id + width_status + 4 + 40))
    for tid, ok, msg in _results:
        status = "PASS" if ok else "FAIL"
        print(f"{tid:<{width_id}}  {status:<{width_status}}  {msg}")
    print("=" * (width_id + width_status + 4 + 40))
    print(f"Results: {pass_count} passed, {fail_count} failed, {len(_results)} total")

    if fail_count > 0:
        print(f"\n{fail_count} smoke test(s) FAILED.")
        return 1
    print("\nAll smoke tests PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
