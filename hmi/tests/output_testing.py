from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QStyleOptionSlider

from ..backend_client import BackendClient
from ..dialogs import ConfirmDialog
from ..main_window import CoolShiftHMI
from ..output_test import OUTPUT_CHANNELS, valid_test_status
from ..system_state import SystemState
from ..theme import AMBER_WARN, BG_CARD, FG_TEXT, set_app_fonts
from .smoke import make_fresh_status_payload, make_settings_payload


def status(active=False, outcome=None, error=None, values=None):
    values = values or dict(acu1=True, acu2=False, water=True, smoke=False,
                           temperature=True, humidity=False, door=True)
    return make_fresh_status_payload(
        acu_outputs={key: values[key] for key in ("acu1", "acu2")},
        alarm_outputs={key: values[key] for key in ("water", "smoke", "temperature", "humidity", "door")},
        output_test=dict(active=active, original_states=copy.deepcopy(values) if active else None,
                         lease_remaining_s=10 if active else 0,
                         restoration_outcome=outcome, restoration_error=error))


class Harness:
    def __init__(self):
        self.window = CoolShiftHMI(dev_mode=True)
        self.client = self.window.backend
        self.client.probe_settings_endpoint = lambda: "probe-settings-fixture"
        self.client.fetch_status = lambda: "status-fixture"
        self.calls = []
        self.counter = 0
        self.client.start_output_test = lambda: self.request("start")
        self.client.set_test_output = lambda *args: self.request("output", *args)
        self.client.heartbeat_output_test = lambda *args: self.request("heartbeat", *args)
        self.client.end_output_test = lambda *args: self.request("end", *args)
        self.window.show()
        self.window._on_status_received(status())
        self.window._on_settings_received("probe-settings-fixture", make_settings_payload())
        self.window.navigate_to("settings")
        QApplication.processEvents()
        self.controller = self.window.output_test
        self.page = self.window.settings_page

    def request(self, kind, *args):
        self.counter += 1
        cid = f"output-test-{kind}-{self.counter}"
        self.calls.append((cid, kind, args))
        self.client.command_result.emit(cid, "pending", "")
        return cid

    def reply(self, raw=None, cid=None, owner="owner"):
        cid = cid or self.calls[-1][0]
        kind = next(row[1] for row in self.calls if row[0] == cid)
        raw = raw or status(kind != "end", "restored" if kind == "end" else None)
        data = (dict(session_id=owner, original_states=raw["output_test"]["original_states"],
                     lease_seconds=10, status=raw) if kind == "start" else raw)
        self.client.output_test_received.emit(cid, data)
        self.client.command_result.emit(cid, "accepted", "")

    def start(self):
        with patch.object(ConfirmDialog, "confirm", return_value=True):
            self.page._start_test_btn.click()
        self.reply()
        assert self.controller.can_toggle

    def close(self):
        if self.controller.pending:
            self.reply(status(False, "restored"))
        if self.controller.needs_end:
            self.window._on_status_received(status(False, "restored"))
        self.window.close()


def T22_output_test_layout_warning_toggles():
    legacy = status()
    del legacy["alarm_outputs"]["door"]
    assert not valid_test_status(legacy)
    state = SystemState.from_status_payload(legacy, True, time.monotonic())
    assert state.alarm_command_text("door") == "UNKNOWN"
    fixture = Harness()
    try:
        page, control = fixture.page, fixture.controller
        assert not fixture.calls
        assert len(page._test_buttons) == len(OUTPUT_CHANNELS) == 7
        assert not any(button.isEnabled() for button in page._test_buttons.values())
        with patch.object(ConfirmDialog, "confirm", return_value=False) as confirm:
            page._start_test_btn.click()
            warning = confirm.call_args.kwargs["message"]
            for term in ("Actual relays", "temporarily", "restart protection", "bypassed",
                         "Disconnect ACUs", "dummy loads"):
                assert term in warning
        assert not fixture.calls
        page._edited["water_alarm_seconds"] = 9
        page._refresh_all_views()
        assert page._save_btn.isEnabled()
        fixture.start()
        assert not page._save_btn.isEnabled() and page._edited["water_alarm_seconds"] == 9
        for channel in OUTPUT_CHANNELS:
            before = page._test_values[channel]
            label = page._test_labels[channel].text()
            page._test_buttons[channel].click()
            assert fixture.calls[-1][1:] == ("output", ("owner", channel, not before))
            assert page._test_labels[channel].text() == label
            assert not any(button.isEnabled() for button in page._test_buttons.values())
            size = len(fixture.calls)
            page._test_buttons[channel].click()
            assert len(fixture.calls) == size
            values = dict(page._test_values)
            values[channel] = not before
            fixture.reply(status(True, values=values))
            assert page._test_values[channel] is not before

        scroll = page._scroll
        card = page._test_card
        columns = scroll.widget().layout().itemAt(0).layout()
        assert scroll.widget().layout().itemAt(1).widget() is card
        assert card.y() > columns.geometry().bottom()
        assert card.width() >= scroll.viewport().width() - 4
        assert scroll.horizontalScrollBar().maximum() == 0
        buttons = [page._start_test_btn, page._end_test_btn, *page._test_buttons.values()]
        bar = scroll.verticalScrollBar()
        for button in buttons:
            scroll.ensureWidgetVisible(button, 0, 0)
            QApplication.processEvents()
            rect = scroll.viewport().rect()
            assert rect.contains(button.mapTo(scroll.viewport(), button.rect().topLeft()))
            assert rect.contains(button.mapTo(scroll.viewport(), button.rect().bottomRight()))
            assert button.width() >= 48 and button.height() >= 48
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        handle = bar.style().subControlRect(
            QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, bar)
        assert handle.width() >= 48 and handle.height() >= 48, handle
        assert fixture.window.width() == 800 and fixture.window.height() == 480
        page._end_test_btn.click()
        fixture.reply()
        assert page._save_btn.isEnabled() and page._edited["water_alarm_seconds"] == 9
        assert "restored" in page._test_banner.text().lower()
        assert not control._heartbeat.isActive()
        return True, "Full-width below columns; seven authoritative toggles, warning cancel/confirm, dirty edits, rendered 48px targets"
    finally:
        fixture.close()


def T23_output_test_navigation_races():
    fixture = Harness()
    try:
        window, controller = fixture.window, fixture.controller
        for destination in ("dashboard", "control", "sensors", "alarms", "logs", "system"):
            fixture.start()
            fixture.page._test_buttons["water"].click()
            old_command = fixture.calls[-1][0]
            window.navigate_to(destination)
            window.navigate_to("system" if destination != "system" else "dashboard")
            assert window._stack.currentWidget() is fixture.page
            assert not controller._heartbeat.isActive()
            assert fixture.calls[-1][1] == "output"
            controller.toggle("smoke", True)
            fixture.reply()
            assert fixture.calls[-1][1] == "end"
            assert window._stack.currentWidget() is fixture.page
            fixture.reply()
            assert window._stack.currentIndex() == window._page_index[destination]
            fixture.reply(status(True), cid=old_command)
            assert not controller.active and not controller.session_id
            window.navigate_to("settings")
        # Start can race page departure as well as output commands.
        controller.start()
        window.navigate_to("logs")
        assert window._stack.currentWidget() is fixture.page
        fixture.reply(owner="fresh-owner")
        assert fixture.calls[-1][1:] == ("end", ("fresh-owner",))
        fixture.reply()
        assert window._stack.currentWidget() is window.logs_page
        count = len(fixture.calls)
        window.navigate_to("settings")
        window.navigate_to("dashboard")
        assert len(fixture.calls) == count
        return True, "All six departure destinations drain commands/start, freeze renewals, retain first click, ignore stale replies; no-test exit writes nothing"
    finally:
        fixture.close()


def T24_output_test_recovery_and_failures():
    fixture = Harness()
    try:
        controller, window = fixture.controller, fixture.window
        fixture.start()
        assert controller._heartbeat.interval() == 2000 and controller._heartbeat.isActive()
        controller.heartbeat()
        assert fixture.calls[-1][1] == "heartbeat"
        fixture.reply()
        window._on_conn(False, 0)
        assert not controller._heartbeat.isActive() and not controller.can_toggle
        assert all("UNKNOWN" in label.text() for label in fixture.page._test_labels.values())
        assert "unconfirmed" in fixture.page._test_banner.text().lower()
        window.navigate_to("control")
        assert window._stack.currentWidget() is fixture.page
        window._on_status_received(status(True))
        assert fixture.calls[-1][1] == "end" and not controller._heartbeat.isActive()
        lost_end = fixture.calls[-1][0]
        fixture.client.command_result.emit(lost_end, "failed", "Request timeout")
        assert window._stack.currentWidget() is fixture.page
        assert "unconfirmed" in fixture.page._test_banner.text().lower()
        # Lease expiry is confirmed via fresh status without replaying toggles.
        window._on_status_received(status(False, "restored"))
        assert window._stack.currentWidget() is window.control_page
        assert not controller.needs_end
        fixture.reply(status(True), cid=lost_end)
        assert not controller.active
        window.navigate_to("settings")
        fixture.start()
        fixture.page._test_buttons["acu1"].click()
        rejected = fixture.calls[-1][0]
        fixture.client.command_result.emit(rejected, "rejected", "Wrong session")
        assert "rejected" in fixture.page._test_banner.text().lower()
        fixture.page._test_buttons["acu1"].click()
        fixture.client.command_result.emit(fixture.calls[-1][0], "failed", "Malformed output-test response")
        assert not controller.can_toggle and not controller._heartbeat.isActive()
        window._on_status_received(status(True))
        fixture.reply(status(False, "failed", "GPIO restoration failed"))
        assert "unconfirmed" in fixture.page._test_banner.text().lower()
        assert "GPIO" in fixture.page._test_banner.text()
        assert not controller.can_start
        window.navigate_to("dashboard")
        window._on_status_received(status(False, "shutdown", "Backend stopped; outputs OFF"))
        assert window._stack.currentWidget() is fixture.page
        window._on_status_received(status(False, "restored"))
        assert window._stack.currentWidget() is window.dashboard_page
        # Lost start has no owner id. Never renew or restart it on reconnect.
        window.navigate_to("settings")
        controller.start()
        fixture.client.command_result.emit(fixture.calls[-1][0], "failed", "Request timeout")
        count = len(fixture.calls)
        window._on_status_received(status(True))
        assert len(fixture.calls) == count and not controller._heartbeat.isActive()
        window._on_status_received(status(False, "restored"))
        assert controller.can_start
        return True, "2s active-only heartbeat, UNKNOWN disconnect, reconnect ends rather than resumes; lost start/end, lease, rejection and restore/fatal failures"
    finally:
        fixture.close()


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), "Timed out waiting for asynchronous response"


def T25_output_test_network_contract():
    calls = []
    mode = {"value": "ok", "delay": False}
    delayed_get = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append((self.path, body))
            if mode["value"] == "delay":
                time.sleep(0.25)
            action = self.path.rsplit("/", 1)[-1]
            raw = status(action != "end", "restored" if action == "end" else None)
            data = (dict(session_id="network-owner", original_states=raw["output_test"]["original_states"],
                         lease_seconds=10, status=raw) if action == "start" else raw)
            if mode["value"] == "malformed":
                data = {"output_test": {"active": True}}
            code = 422 if mode["value"] == "reject" else 200
            self.send_response(code)
            self.end_headers()
            try:
                self.wfile.write(json.dumps({"detail": "Invalid test request"} if code == 422 else data).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            delayed = mode["delay"]
            raw = status(True) if delayed else status(False, "restored")
            if delayed:
                delayed_get.set()
                time.sleep(0.2)
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(json.dumps(raw).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = BackendClient(f"http://127.0.0.1:{server.server_port}", timeout_ms=120)
    results, received, polls = [], [], []
    client.command_result.connect(lambda *args: results.append(args))
    client.output_test_received.connect(lambda *args: received.append(args))
    client.status_received.connect(polls.append)

    def request(call):
        cid = call()
        wait_for(lambda: any(row[0] == cid and row[1] != "pending" for row in results))
        return cid

    try:
        request(client.start_output_test)
        assert received[-1][1]["session_id"] == "network-owner"
        assert calls[0] == ("/api/output-test/start", b"")
        for channel in OUTPUT_CHANNELS:
            for value in (True, False):
                request(lambda: client.set_test_output("network-owner", channel, value))
                assert json.loads(calls[-1][1]) == dict(
                    session_id="network-owner", channel=channel, value=value)
        for method, action in ((client.heartbeat_output_test, "heartbeat"), (client.end_output_test, "end")):
            request(lambda: method("network-owner"))
            assert calls[-1][0] == f"/api/output-test/{action}"
            assert json.loads(calls[-1][1]) == {"session_id": "network-owner"}
        count = len(received)
        for response, expected in (("malformed", "failed"), ("reject", "rejected"), ("delay", "failed")):
            mode["value"] = response
            cid = request(client.start_output_test)
            assert next(row[1] for row in results if row[0] == cid and row[1] != "pending") == expected
        assert len(received) == count
        mode["value"] = "ok"
        mode["delay"] = True
        client._timeout_ms = 1000
        client.fetch_status()
        wait_for(delayed_get.is_set)
        request(lambda: client.end_output_test("network-owner"))
        QTest.qWait(250)
        assert not polls, "A pre-end delayed status was published"
        mode["delay"] = False
        request(client.fetch_status)
        assert len(polls) == 1 and not polls[-1]["output_test"]["active"]
        # Latest poll wins when two polls complete in reverse order.
        delayed_get.clear()
        mode["delay"] = True
        client.fetch_status()
        wait_for(delayed_get.is_set)
        mode["delay"] = False
        request(client.fetch_status)
        QTest.qWait(250)
        assert len(polls) == 2 and not polls[-1]["output_test"]["active"], [
            row["output_test"] for row in polls]
        return True, "Actual async HTTP: empty start, seven strict boolean writes, heartbeat/end bodies, 422, malformed, timeout and out-of-order polls"
    finally:
        client.shutdown()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        client.deleteLater()


def T26_output_test_graceful_shutdown():
    fixture = Harness()
    try:
        fixture.start()
        fixture.page._test_buttons["smoke"].click()
        events = []
        fixture.client.shutdown = lambda: events.append("network shutdown")
        QTimer.singleShot(30, lambda: (events.append("output reply"), fixture.reply()))
        QTimer.singleShot(80, lambda: (events.append("restore ack"), fixture.reply()))
        start = time.monotonic()
        fixture.window.shutdown()
        assert time.monotonic() - start < 1
        assert fixture.calls[-1][1] == "end"
        assert events == ["output reply", "restore ack", "network shutdown"], events
        assert not any(timer.isActive() for timer in fixture.window.findChildren(QTimer))
    finally:
        fixture.close()
    fixture = Harness()
    try:
        fixture.start()
        events = []
        fixture.client.shutdown = lambda: events.append("network shutdown")
        ticks = []
        tick = QTimer(fixture.window)
        tick.timeout.connect(lambda: ticks.append(time.monotonic()))
        tick.start(20)
        start = time.monotonic()
        fixture.window.shutdown()
        elapsed = time.monotonic() - start
        assert 2 <= elapsed < 3.5, elapsed
        assert fixture.calls[-1][1] == "end"
        assert events == ["network shutdown"] and len(ticks) > 50
        assert "unconfirmed" in fixture.page._test_banner.text().lower()
        assert not fixture.controller._heartbeat.isActive()
        return True, "Shutdown drains output then restores before network teardown; lost end bounds shutdown at 2.5s with responsive Qt loop and no renewals"
    finally:
        fixture.close()


def T27_output_test_signals_restore_before_exit():
    started = threading.Event()
    ended = threading.Event()
    live = {"active": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data):
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(json.dumps(data).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.respond(make_settings_payload() if self.path == "/api/settings" else
                         status(live["active"], None if live["active"] else "restored"))

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            action = self.path.rsplit("/", 1)[-1]
            if action == "start":
                live["active"] = True
                raw = status(True)
                self.respond(dict(session_id="signal-owner", lease_seconds=10,
                                  original_states=raw["output_test"]["original_states"], status=raw))
                started.set()
            else:
                if action == "end":
                    live["active"] = False
                    ended.set()
                self.respond(status(live["active"], None if live["active"] else "restored"))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    script = """
import logging, runpy
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from hmi.main_window import CoolShiftHMI
app = QApplication([])
win = CoolShiftHMI(dev_mode=True)
app.aboutToQuit.connect(win.shutdown)
runpy.run_path('hmi.py')['install_signal_handlers'](app, logging.getLogger('test'))
win.start()
def begin():
    if not win.output_test.available:
        QTimer.singleShot(50, begin)
        return
    win.navigate_to('settings')
    win.output_test.start()
QTimer.singleShot(50, begin)
app.exec()
"""
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            started.clear()
            ended.clear()
            live["active"] = False
            process = subprocess.Popen(
                [sys.executable, "-c", script],
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                     "COOLSHIFT_BACKEND_URL": f"http://127.0.0.1:{server.server_port}"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                assert started.wait(5), "Child did not start output session"
                process.send_signal(signum)
                stdout, stderr = process.communicate(timeout=5)
                assert process.returncode == 0, stderr
                assert ended.is_set() and not live["active"], (signum, stderr)
                assert "Traceback" not in stderr, stderr
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        return True, "Subprocess SIGINT and SIGTERM with accepted live test session both POST end before exiting cleanly"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def T28_output_test_rendered_contrast():
    app = QApplication.instance()
    old_font, old_qss = app.font(), app.styleSheet()
    set_app_fonts(app)
    fixture = Harness()
    for timer in fixture.window.findChildren(QTimer):
        timer.stop()
    contrasts = []

    def luminance(rgb):
        channels = [value / 255 for value in rgb]
        linear = [value / 12.92 if value <= 0.04045 else
                  ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    def check_painted_label(label, foreground, scenario):
        page = fixture.page
        page._scroll.ensureWidgetVisible(label, 0, 0)
        QApplication.processEvents()
        viewport = page._scroll.viewport()
        top_left = label.mapTo(viewport, label.rect().topLeft())
        bottom_right = label.mapTo(viewport, label.rect().bottomRight())
        assert viewport.rect().contains(top_left) and viewport.rect().contains(bottom_right)
        # Capture the composed window, including the background behind transparent labels.
        pixmap = fixture.window.grab()
        scale = pixmap.devicePixelRatio()
        position = label.mapTo(fixture.window, label.rect().topLeft())
        image = pixmap.toImage().copy(
            round(position.x() * scale), round(position.y() * scale),
            round(label.width() * scale), round(label.height() * scale))
        pixels = Counter(
            image.pixelColor(x, y).getRgb()[:3]
            for y in range(image.height()) for x in range(image.width()))
        background = pixels.most_common(1)[0][0]
        expected_foreground = QColor(foreground).getRgb()[:3]
        text_pixels = {
            rgb: count for rgb, count in pixels.items()
            if max(abs(a - b) for a, b in zip(rgb, expected_foreground)) <= 8}
        context = (scenario, label.text(), background)
        assert background == QColor(BG_CARD).getRgb()[:3], context
        assert sum(text_pixels.values()) >= 3, ("Missing painted text", context)
        painted_foreground = min(
            text_pixels, key=lambda rgb: sum(abs(a - b) for a, b in zip(rgb, expected_foreground)))
        light, dark = sorted((luminance(background), luminance(painted_foreground)), reverse=True)
        contrast = (light + 0.05) / (dark + 0.05)
        assert contrast >= 4.5, (context, painted_foreground, contrast)
        contrasts.append(contrast)

    def check_scenario(scenario, commanded):
        page = fixture.page
        # Pixel sampling must not enqueue a heartbeat ahead of fixture replies.
        fixture.controller._heartbeat.stop()
        assert fixture.window.size().width() == 800 and fixture.window.size().height() == 480
        assert page._test_card.objectName() == "settings_output_test"
        assert page.findChild(type(page._test_card), "settings_output_test") is page._test_card
        check_painted_label(page._test_card._title_label, FG_TEXT, scenario)
        check_painted_label(page._test_card.content_layout.itemAt(0).widget(), FG_TEXT, scenario)
        check_painted_label(page._test_banner, AMBER_WARN, scenario)
        for channel, name in OUTPUT_CHANNELS.items():
            label = page._test_labels[channel]
            name_label = label.parentWidget().layout().itemAt(0).widget()
            assert name_label.text() == name
            assert label.text() == commanded[channel]
            check_painted_label(name_label, FG_TEXT, scenario)
            check_painted_label(label, FG_TEXT, scenario)
        assert page._scroll.horizontalScrollBar().maximum() == 0

    try:
        commands = {channel: f"Commanded {'ON' if value else 'OFF'}"
                    for channel, value in fixture.page._test_values.items()}
        check_scenario("inactive", commands)
        fixture.start()
        fixture.controller._heartbeat.stop()
        check_scenario("active", commands)
        fixture.page._test_buttons["acu1"].click()
        fixture.client.command_result.emit(fixture.calls[-1][0], "rejected", "Wrong session")
        assert "rejected" in fixture.page._test_banner.text().lower()
        check_scenario("rejected", commands)
        fixture.page._end_test_btn.click()
        assert "restoring" in fixture.page._test_banner.text().lower()
        check_scenario("restoring", commands)
        fixture.reply()
        assert "restored" in fixture.page._test_banner.text().lower()
        check_scenario("restored", commands)
        fixture.start()
        fixture.controller._heartbeat.stop()
        fixture.window._on_conn(False, 0)
        assert "unconfirmed" in fixture.page._test_banner.text().lower()
        check_scenario("offline", {channel: "UNKNOWN / OFFLINE" for channel in OUTPUT_CHANNELS})
        return True, (
            f"Production-font 800x480 painted title/warning/banner and all seven names/states: "
            f"{len(contrasts)} samples, minimum contrast {min(contrasts):.2f}:1; "
            "inactive/active/rejected/restoring/restored/offline")
    finally:
        fixture.close()
        app.setFont(old_font)
        app.setStyleSheet(old_qss)


TESTS = [(function.__name__, function) for function in (
    T22_output_test_layout_warning_toggles, T23_output_test_navigation_races,
    T24_output_test_recovery_and_failures, T25_output_test_network_contract,
    T26_output_test_graceful_shutdown, T27_output_test_signals_restore_before_exit,
    T28_output_test_rendered_contrast)]
