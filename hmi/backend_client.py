from __future__ import annotations

import json
import time
import uuid
from collections import deque
from typing import Deque, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .constants import BACKEND_URL, POLL_INTERVAL_MS, REQUEST_TIMEOUT_MS
from .output_test import valid_commands, valid_test_status


class BackendClient(QObject):
    status_received = Signal(dict)
    events_received = Signal(list)
    settings_received = Signal(str, dict)
    output_test_received = Signal(str, dict)
    command_result = Signal(str, str, str)
    connection_state_changed = Signal(bool, float)
    error = Signal(str)
    info_log = Signal(str)

    def __init__(
        self,
        base_url: str = BACKEND_URL,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._base_url: str = base_url.rstrip("/")
        self._timeout_ms: int = timeout_ms
        self._nam: QNetworkAccessManager = QNetworkAccessManager(self)
        self._poll_timer: QTimer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_timer)
        self._poll_interval_ms: int = POLL_INTERVAL_MS
        self._consecutive_failures: int = 0
        self._latencies: Deque[float] = deque(maxlen=10)
        self._diagnostic_log: Deque[str] = deque(maxlen=200)
        self._total_polls: int = 0
        self._error_count: int = 0
        self._last_online: Optional[bool] = None
        self._replies: set[QNetworkReply] = set()
        self._closing = False
        self._test_revision = 0
        self._status_sequence = 0
        self._last_status_sequence = 0

    def start_output_test(self) -> str:
        return self._post_output_test("start", {})

    def set_test_output(self, session_id: str, channel: str, value: bool) -> str:
        return self._post_output_test("output", dict(
            session_id=session_id, channel=channel, value=value))

    def heartbeat_output_test(self, session_id: str) -> str:
        return self._post_output_test("heartbeat", {"session_id": session_id})

    def end_output_test(self, session_id: str) -> str:
        return self._post_output_test("end", {"session_id": session_id})

    def _post_output_test(self, action: str, payload: dict) -> str:
        cmd_id = f"output-test-{action}-{uuid.uuid4().hex[:8]}"
        self._test_revision += 1
        revision = self._test_revision
        self.command_result.emit(cmd_id, "pending", "")
        if action == "start":
            reply = self._nam.post(QNetworkRequest(
                QUrl(self._base_url + "/api/output-test/start")), b"")
        else:
            reply = self._post_json(f"/api/output-test/{action}", payload)

        def on_done():
            code = self._reply_status_code(reply)
            if reply.error() != QNetworkReply.NoError or not 200 <= code < 300:
                self._test_revision += 1
                self.command_result.emit(
                    cmd_id, "rejected" if code in (400, 409, 422) else "failed",
                    self._extract_error_detail(reply))
                return
            data = self._parse_json_body(reply, cmd_id)
            raw = data.get("status") if action == "start" and isinstance(data, dict) else data
            valid = valid_test_status(raw)
            if action == "start":
                valid = (valid and isinstance(data.get("session_id"), str)
                         and bool(data["session_id"]) and valid_commands(data.get("original_states"))
                         and data.get("lease_seconds") == 10 and raw["output_test"]["active"]
                         and data["original_states"] == raw["output_test"]["original_states"])
            if not valid:
                self._test_revision += 1
                self.command_result.emit(cmd_id, "failed", "Malformed output-test response")
                return
            if revision != self._test_revision:
                return
            self._test_revision += 1
            self.output_test_received.emit(cmd_id, data)
            self.command_result.emit(cmd_id, "accepted", "")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def _status_ticket(self):
        self._status_sequence += 1
        return self._test_revision, self._status_sequence

    def _status_is_current(self, ticket):
        revision, sequence = ticket
        if revision != self._test_revision or sequence < self._last_status_sequence:
            return False
        self._last_status_sequence = sequence
        return True

    def start_polling(self, interval_ms: int = POLL_INTERVAL_MS) -> None:
        self._poll_interval_ms = interval_ms
        self._consecutive_failures = 0
        self._poll_timer.start(interval_ms)
        self._append_log(f"polling start interval={interval_ms}ms")

    def stop_polling(self) -> None:
        self._poll_timer.stop()
        self._append_log("polling stop")

    def shutdown(self) -> None:
        self._closing = True
        self.stop_polling()
        for reply in list(self._replies):
            reply.abort()

    def diagnostic_log(self) -> List[str]:
        return list(self._diagnostic_log)

    def get_latency_avg_ma(self) -> float:
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)

    @property
    def total_polls(self) -> int:
        return self._total_polls

    @property
    def error_count(self) -> int:
        return self._error_count

    def fetch_status(self) -> str:
        ticket = self._status_ticket()
        cmd_id = f"status-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} GET /api/status")
        start = time.time()
        reply = self._get("/api/status")

        def on_done() -> None:
            if not self._status_is_current(ticket):
                return
            latency_ms = (time.time() - start) * 1000.0
            self._handle_status_reply(cmd_id, reply, latency_ms)

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def fetch_events(self, limit: int = 200) -> str:
        cmd_id = f"events-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} GET /api/events limit={limit}")
        reply = self._get(f"/api/events?limit={limit}")

        def on_done() -> None:
            self._handle_events_reply(cmd_id, reply)

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def post_mode(self, mode: str) -> str:
        cmd_id = f"mode-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} POST /api/mode mode={mode}")
        reply = self._post_json("/api/mode", {"mode": mode})

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                data = self._parse_json_body(reply, cmd_id)
                if isinstance(data, dict) and "acu_outputs" in data:
                    self.status_received.emit(data)
                self.command_result.emit(cmd_id, "accepted", "")
                self._append_log(f"req {cmd_id} accepted status={status_code}")
            elif status_code in (400, 409):
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "rejected", detail)
                self._append_log(f"req {cmd_id} rejected status={status_code} detail={detail}")
            else:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "failed", detail)
                self._append_log(f"req {cmd_id} failed status={status_code} detail={detail}")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def post_simulation(self, payload: dict) -> str:
        cmd_id = f"sim-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} POST /api/simulation keys={list(payload.keys())}")
        reply = self._post_json("/api/simulation", payload)

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                self.command_result.emit(cmd_id, "accepted", "")
                self._append_log(f"req {cmd_id} accepted status={status_code}")
            elif status_code == 403:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "rejected", detail)
                self._append_log(f"req {cmd_id} rejected 403 detail={detail}")
            else:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "failed", detail)
                self._append_log(f"req {cmd_id} failed status={status_code} detail={detail}")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def post_acu_command(self, acu: int, action: str) -> str:
        cmd_id = f"acu-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", f"ACU {acu} {action.upper()} pending")
        reply = self._post_json(f"/api/acu/{acu}/command", {"action": action})
        self._append_log(f"req {cmd_id} POST /api/acu/{acu}/command action={action}")

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                data = self._parse_json_body(reply, cmd_id)
                if not isinstance(data, dict) or "acu_outputs" not in data:
                    self.command_result.emit(cmd_id, "failed", "Malformed ACU command response")
                    return
                self.status_received.emit(data)
                self.command_result.emit(cmd_id, "accepted", f"ACU {acu} commanded {action.upper()}")
            else:
                detail = self._extract_error_detail(reply)
                result = "rejected" if status_code in (400, 409, 422) else "failed"
                self.command_result.emit(cmd_id, result, detail)

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def probe_settings_endpoint(self) -> str:
        cmd_id = f"probe-settings-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} GET /api/settings probe")
        reply = self._get("/api/settings")

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                self._handle_settings_body(cmd_id, reply)
            elif status_code == 404:
                self.command_result.emit(cmd_id, "rejected", "settings endpoint unavailable")
                self._append_log(f"req {cmd_id} probe rejected 404")
            else:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "failed", detail)
                self._append_log(f"req {cmd_id} probe failed status={status_code} detail={detail}")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def post_settings(self, payload: dict) -> str:
        cmd_id = f"settings-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} PATCH /api/settings keys={list(payload.keys())}")
        reply = self._patch_json("/api/settings", payload)

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                self._handle_settings_body(cmd_id, reply)
            else:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "rejected", detail)
                self._append_log(f"req {cmd_id} rejected status={status_code} detail={detail}")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def _handle_settings_body(self, cmd_id: str, reply: QNetworkReply) -> None:
        data = self._parse_json_body(reply, cmd_id)
        if (not isinstance(data, dict) or not isinstance(data.get("effective"), dict)
                or not isinstance(data.get("defaults"), dict)
                or not isinstance(data.get("restart_required"), list)):
            self.command_result.emit(cmd_id, "failed", "Malformed settings response")
            return
        self.settings_received.emit(cmd_id, data)
        self.command_result.emit(cmd_id, "accepted", "")

    def probe_info_endpoint(self) -> str:
        cmd_id = f"probe-info-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        self._append_log(f"req {cmd_id} GET /api/info probe")
        reply = self._get("/api/info")

        def on_done() -> None:
            status_code = self._reply_status_code(reply)
            if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
                data = self._parse_json_body(reply, cmd_id)
                if data is not None:
                    self._append_log(f"req {cmd_id} info {json.dumps(data, default=str)[:200]}")
                    self.command_result.emit(cmd_id, "accepted", "")
                else:
                    self.command_result.emit(cmd_id, "failed", "malformed JSON")
            else:
                detail = self._extract_error_detail(reply)
                self.command_result.emit(cmd_id, "rejected", detail)
                self._append_log(f"req {cmd_id} probe info rejected status={status_code} detail={detail}")

        self._handle_network_reply(reply, cmd_id, on_done)
        return cmd_id

    def _on_poll_timer(self) -> None:
        ticket = self._status_ticket()
        self._total_polls += 1
        cmd_id = f"poll-{uuid.uuid4().hex[:8]}"
        self.command_result.emit(cmd_id, "pending", "")
        start = time.time()
        reply = self._get("/api/status")

        def on_done() -> None:
            if not self._status_is_current(ticket):
                return
            latency_ms = (time.time() - start) * 1000.0
            self._handle_status_reply(cmd_id, reply, latency_ms, from_poll=True)

        self._handle_network_reply(reply, cmd_id, on_done)

    def _handle_status_reply(self, cmd_id: str, reply: QNetworkReply, latency_ms: float, from_poll: bool = False) -> None:
        status_code = self._reply_status_code(reply)
        if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
            data = self._parse_json_body(reply, cmd_id)
            if isinstance(data, dict):
                self._latencies.append(latency_ms)
                self._set_online(True, latency_ms)
                self.status_received.emit(data)
                self.command_result.emit(cmd_id, "accepted", "")
                self._append_log(f"req {cmd_id} ok status={status_code} latency={latency_ms:.1f}ms")
                if from_poll:
                    self._consecutive_failures = 0
                    self._reset_poll_interval()
            else:
                self._error_count += 1
                self.command_result.emit(cmd_id, "failed", "Malformed JSON response")
                self.error.emit(f"Malformed JSON response for /api/status")
                self._append_log(f"req {cmd_id} failed malformed json")
                self._set_online(False, 0.0)
                if from_poll:
                    self._record_poll_failure()
        else:
            self._error_count += 1
            detail = self._extract_error_detail(reply)
            self.command_result.emit(cmd_id, "failed", detail)
            self.error.emit(f"Status request failed: {detail}")
            self._append_log(f"req {cmd_id} failed status={status_code} err={reply.error()} detail={detail[:120]}")
            self._set_online(False, 0.0)
            if from_poll:
                self._record_poll_failure()

    def _handle_events_reply(self, cmd_id: str, reply: QNetworkReply) -> None:
        status_code = self._reply_status_code(reply)
        if reply.error() == QNetworkReply.NoError and 200 <= status_code < 300:
            data = self._parse_json_body(reply, cmd_id)
            if isinstance(data, list):
                self.events_received.emit(data)
                self.command_result.emit(cmd_id, "accepted", "")
                self._append_log(f"req {cmd_id} ok rows={len(data)}")
            else:
                self.command_result.emit(cmd_id, "failed", "Unexpected JSON type for events")
                self.error.emit(f"Unexpected JSON type for /api/events")
                self._append_log(f"req {cmd_id} failed wrong json type={type(data).__name__}")
        else:
            detail = self._extract_error_detail(reply)
            self.command_result.emit(cmd_id, "failed", detail)
            self.error.emit(f"Events request failed: {detail}")
            self._append_log(f"req {cmd_id} failed status={status_code} detail={detail[:120]}")

    def _record_poll_failure(self) -> None:
        self._consecutive_failures += 1
        self._set_online(False, 0.0)
        if self._poll_timer.isActive():
            step = min(self._consecutive_failures, 5)
            backoff_ms = min((2 ** max(0, step - 1)) * 1000, 30000)
            self._poll_timer.start(backoff_ms)
            self._append_log(f"poll backoff failures={self._consecutive_failures} interval={backoff_ms}ms")

    def _reset_poll_interval(self) -> None:
        if self._poll_timer.isActive():
            self._poll_timer.start(self._poll_interval_ms)

    def _set_online(self, online: bool, latency_ms: float) -> None:
        if self._last_online != online:
            self._last_online = online
            self.connection_state_changed.emit(online, latency_ms)

    def _handle_network_reply(self, reply: QNetworkReply, cmd_id: str, on_done) -> None:
        self._replies.add(reply)
        aborted = {"flag": False}
        timer = QTimer(reply)
        timer.setSingleShot(True)

        def on_finished() -> None:
            timer.stop()
            self._replies.discard(reply)
            if not aborted["flag"] and not self._closing:
                on_done()
            reply.deleteLater()

        def on_aborted() -> None:
            aborted["flag"] = True
            self._error_count += 1
            if cmd_id.startswith("output-test-"):
                self._test_revision += 1
            self.command_result.emit(cmd_id, "failed", "Request timeout")
            self.error.emit(f"Request timeout ({self._timeout_ms}ms): {cmd_id}")
            self._append_log(f"req {cmd_id} timeout after {self._timeout_ms}ms")
            if cmd_id.startswith(("poll-", "status-")):
                self._set_online(False, 0.0)
            if cmd_id.startswith("poll-"):
                self._record_poll_failure()
            reply.abort()

        reply.finished.connect(on_finished)
        timer.timeout.connect(on_aborted)
        timer.start(self._timeout_ms)

    def _get(self, path: str) -> QNetworkReply:
        url = QUrl(self._base_url + path)
        request = QNetworkRequest(url)
        return self._nam.get(request)

    def _post_json(self, path: str, payload: dict) -> QNetworkReply:
        url = QUrl(self._base_url + path)
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        body = json.dumps(payload).encode("utf-8")
        return self._nam.post(request, body)

    def _patch_json(self, path: str, payload: dict) -> QNetworkReply:
        url = QUrl(self._base_url + path)
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        body = json.dumps(payload).encode("utf-8")
        return self._nam.sendCustomRequest(request, b"PATCH", body)

    def _reply_status_code(self, reply: QNetworkReply) -> int:
        attr = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if attr is None:
            return 0
        try:
            return int(attr)
        except (TypeError, ValueError):
            return 0

    def _parse_json_body(self, reply: QNetworkReply, cmd_id: str) -> Optional[object]:
        try:
            raw = bytes(reply.readAll())
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.error.emit(f"Malformed JSON response: {exc}")
            self._append_log(f"req {cmd_id} json decode error: {exc}")
            return None

    def _extract_error_detail(self, reply: QNetworkReply) -> str:
        data = self._parse_json_body(reply, "internal-detail")
        if isinstance(data, dict):
            if isinstance(data.get("detail"), str):
                return data["detail"]
            if isinstance(data.get("message"), str):
                return data["message"]
            if data.get("detail") is not None:
                return json.dumps(data["detail"])
        if reply.error() != QNetworkReply.NoError:
            return reply.errorString()
        status_code = self._reply_status_code(reply)
        if status_code:
            return f"HTTP {status_code}"
        return "unknown error"

    def _append_log(self, line: str) -> None:
        self._diagnostic_log.append(line)
        self.info_log.emit(line)
