from __future__ import annotations

import math

from PySide6.QtCore import QObject, QTimer, Signal


OUTPUT_CHANNELS = {
    "acu1": "ACU 1",
    "acu2": "ACU 2",
    "water": "Water Alarm",
    "smoke": "Smoke Alarm",
    "temperature": "Temperature Alarm",
    "humidity": "Humidity Alarm",
    "door": "Door Alarm",
}


def valid_commands(values: object) -> bool:
    return (isinstance(values, dict) and set(values) == set(OUTPUT_CHANNELS)
            and all(isinstance(value, bool) for value in values.values()))


def valid_test_status(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    test = raw.get("output_test")
    if not isinstance(test, dict) or not isinstance(test.get("active"), bool):
        return False
    remaining = test.get("lease_remaining_s")
    return (
        isinstance(raw.get("acu_outputs"), dict)
        and all(isinstance(raw["acu_outputs"].get(key), bool) for key in ("acu1", "acu2"))
        and isinstance(raw.get("alarm_outputs"), dict)
        and all(isinstance(raw["alarm_outputs"].get(key), bool)
                for key in ("water", "smoke", "temperature", "humidity", "door"))
        and isinstance(remaining, (int, float)) and not isinstance(remaining, bool)
        and math.isfinite(remaining) and remaining >= 0
        and "restoration_outcome" in test and "restoration_error" in test
        and (not test["active"] or valid_commands(test.get("original_states")))
    )


class OutputTestController(QObject):
    """One in-flight mutation; departure drains it before sending end."""

    changed = Signal()
    status_ready = Signal(dict)
    departure_ready = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.session_id = None
        self.pending = None
        self.pending_id = None
        self.ending = False
        self.uncertain = False
        self.on_settings = False
        self.online = False
        self.active = False
        self.available = False
        self.message = "Backend offline - commands UNKNOWN"
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(2000)
        self._heartbeat.timeout.connect(self.heartbeat)
        backend.output_test_received.connect(self._response)
        backend.command_result.connect(self._result)

    @property
    def needs_end(self):
        return bool(self.session_id or self.pending or self.uncertain)

    @property
    def can_start(self):
        return (self.online and self.available and self.on_settings and not self.active
                and not self.needs_end and not self.ending)

    @property
    def can_toggle(self):
        return (self.online and self.on_settings and self.active and bool(self.session_id)
                and not self.pending and not self.ending and not self.uncertain)

    def set_page(self, settings):
        self.on_settings = settings
        self._refresh()

    def connection(self, online):
        self.online = online
        if not online:
            if self.needs_end:
                self.ending = True
                self.uncertain = True
                self.message = "OFFLINE / UNKNOWN - Restoration unconfirmed; lease recovery pending"
            else:
                self.message = "Backend offline - commands UNKNOWN"
        self._refresh()

    def observe(self, raw):
        if not valid_test_status(raw):
            self.available = False
            if self.needs_end:
                self.ending = True
                self.uncertain = True
                self.message = "Restoration unconfirmed - invalid backend status"
            self._refresh()
            return
        self.available = True
        self.active = raw["output_test"]["active"]
        # Polls cannot settle an in-flight start or command. The client also
        # filters polls issued before a mutation to avoid older status races.
        if not self.pending:
            if not self.active and self.needs_end:
                self._settle_inactive(raw)
            elif self.ending and self.active and self.session_id and self.online:
                self._send("end")
            elif self.active and not self.session_id:
                self.message = "Testing active in another client; controls unavailable"
            elif not self.needs_end:
                self.message = "Ready - relay commands only (not measured contacts)"
        self._refresh()

    def start(self):
        if self.can_start:
            self.message = "Starting output test..."
            self._send("start")

    def toggle(self, channel, value):
        if self.can_toggle and channel in OUTPUT_CHANNELS and isinstance(value, bool):
            self.message = f"{OUTPUT_CHANNELS[channel]} command pending..."
            self._send("output", channel, value)

    def heartbeat(self):
        if self.can_toggle:
            self._send("heartbeat")

    def end(self):
        if not self.needs_end:
            self.departure_ready.emit()
            return
        self.ending = True
        self.message = "Restoring outputs..."
        self._refresh()
        if not self.pending and self.session_id and self.online:
            self._send("end")
        elif not self.pending:
            self.uncertain = True
            self.message = "Restoration unconfirmed - awaiting backend status / lease recovery"
            self._refresh()
            self.backend.fetch_status()

    def _send(self, kind, *args):
        if self.pending:
            return
        self.pending = kind
        self.pending_id = None
        self._refresh()
        methods = {
            "start": self.backend.start_output_test,
            "output": self.backend.set_test_output,
            "heartbeat": self.backend.heartbeat_output_test,
            "end": self.backend.end_output_test,
        }
        arguments = args if kind == "start" else (self.session_id, *args)
        self.pending_id = methods[kind](*arguments)

    def _result(self, cmd_id, result, detail):
        if not cmd_id.startswith("output-test-") or not self.pending:
            return
        if result == "pending" and self.pending_id is None:
            self.pending_id = cmd_id
        if cmd_id != self.pending_id or result not in ("failed", "rejected"):
            return
        kind = self.pending
        self.pending = self.pending_id = None
        # Even a failed start can have reached the server before its reply was
        # lost. Never retry start or replay an uncertain output automatically.
        if result == "failed" or kind == "end" or self.ending:
            self.uncertain = True
            self.ending = True
            self.message = "Restoration unconfirmed - " + (detail or "Request failed")
            self._refresh()
            self.backend.fetch_status()
        else:
            self.message = "Test request rejected: " + detail
            self._refresh()

    def _response(self, cmd_id, data):
        if cmd_id != self.pending_id or not self.pending:
            return
        kind = self.pending
        raw = data.get("status") if kind == "start" else data
        self.pending = self.pending_id = None
        if kind == "start":
            self.session_id = data["session_id"]
        self.active = raw["output_test"]["active"]
        self.status_ready.emit(raw)
        if not self.active:
            self._settle_inactive(raw)
        elif self.ending:
            self._send("end")
        else:
            self.message = "TEST ACTIVE - automatic relay control overridden; saving disabled"
        self._refresh()

    def _settle_inactive(self, raw):
        test = raw["output_test"]
        outcome = test["restoration_outcome"]
        if test["restoration_error"] or outcome in ("failed", "fatal", "shutdown"):
            self.session_id = None
            self.uncertain = True
            self.ending = True
            self.message = "Restoration unconfirmed - " + str(
                test["restoration_error"] or outcome)
            return
        self.session_id = None
        self.uncertain = False
        self.ending = False
        self.message = ("Outputs restored; normal control resumed" if outcome == "restored"
                        else "Test inactive - backend confirmed; normal control may resume")
        self.departure_ready.emit()

    def _refresh(self):
        renew = (self.online and self.on_settings and self.active and self.session_id
                 and not self.ending and not self.uncertain)
        if renew and not self._heartbeat.isActive():
            self._heartbeat.start()
        elif not renew:
            self._heartbeat.stop()
        self.changed.emit()
