"""Command-only cooling and independent alarm qualification."""
import copy
import logging
from contextlib import closing
import sqlite3
import threading
import time
import uuid

from .config import OUTPUTS
from .io import DHT_FIELDS, DIGITAL_FIELDS, IO

TRIGGERS = {
    "DOOR_OPEN": ("door_alarm_seconds", "door"),
    "WATER_LEVEL_ALARM": ("water_alarm_seconds", "water"),
    "SMOKE_ALARM": ("smoke_alarm_seconds", "smoke"),
    "HIGH_TEMPERATURE": ("temperature_alarm_seconds", "temperature"),
    "HIGH_HUMIDITY": ("humidity_alarm_seconds", "humidity"),
}
RESET_SETTINGS = {
    "DOOR_OPEN": {"door_alarm_seconds"},
    "WATER_LEVEL_ALARM": {"water_alarm_seconds"},
    "SMOKE_ALARM": {"smoke_alarm_seconds"},
    "HIGH_TEMPERATURE": {"temperature_alarm_seconds", "high_temp_alarm_c"},
    "HIGH_HUMIDITY": {"humidity_alarm_seconds", "high_humidity_alarm_pct"},
}

OUTPUT_TEST_LEASE_SECONDS = 10


class OutputTestWriteError(RuntimeError):
    """A test write failed and the controller has entered fail-OFF."""


class EventStore:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path, timeout=0.05)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, detail TEXT)")

    def log(self, kind, detail):
        with closing(sqlite3.connect(self.path, timeout=0.05)) as connection, connection:
            connection.execute("INSERT INTO events(kind,detail) VALUES(?,?)", (kind, detail))

    def events(self, limit):
        with closing(sqlite3.connect(self.path, timeout=0.05)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 500),))]


class Engine:
    def __init__(self, configuration, io=None, clock=time.monotonic, event_store=None):
        self.configuration = configuration
        self.settings = copy.deepcopy(configuration.effective)
        self.clock = clock
        self.io = io or IO(self.settings, clock=clock)
        self.lock = threading.RLock()
        self.event_store = event_store
        self._history_warning_at = float("-inf")
        self.mode = "auto"
        self.lead = 0
        now = clock()
        self.last_rotation = now
        self.off_since = [now - self.settings["min_off_seconds"]] * 2
        self.on_since = [None, None]
        self.pending = None
        self.pending_since = None
        self.boost = False
        self.values = {key: None for key in (*DHT_FIELDS, *DIGITAL_FIELDS.values())}
        self.sample_times = {key: None for key in self.values}
        self.trigger_since = {key: None for key in TRIGGERS}
        self.alarms = []
        self.controller_error = None
        self.stop_event = threading.Event()
        self.threads = []
        self.closed = False
        self.output_test = None
        self.ended_output_tests = {}
        self.restoration_outcome = None
        self.restoration_error = None
        self.suppress_tick_outputs = False
        if self.io.sim:
            self.acquire_dht()

    def log(self, kind, detail):
        # History failure must never interrupt a safety write or control timing.
        logger = logging.getLogger("acuPilot.backend.engine")
        level = (logging.ERROR if kind in {"engine_error", "output_error"}
                 else logging.WARNING if kind == "sensor_error" else logging.INFO)
        try:
            logger.log(level, "%s: %s", kind, detail)
        except Exception:
            pass
        try:
            if self.event_store is not None:
                self.event_store.log(kind, detail)
        except Exception as exc:
            try:
                now = time.monotonic()
                if now - self._history_warning_at >= 60:
                    self._history_warning_at = now
                    logger.warning("acuPilot event history unavailable: %r", exc)
            except Exception:
                pass

    def acquire_dht(self):
        with self.lock:
            poll_seconds = self.settings["sensor_poll_seconds"]
        samples = self.io.poll_dht(poll_seconds)
        with self.lock:
            if self.stop_event.is_set() or self.controller_error:
                return
            for key, (value, sampled_at) in samples.items():
                self.values[key] = value
                self.sample_times[key] = sampled_at

    def fresh(self, key, now):
        sampled_at = self.sample_times[key]
        return (self.values[key] is not None and sampled_at is not None
                and now - sampled_at <= self.settings["sensor_stale_seconds"])

    def set_output(self, name, value, now, force_write=False):
        changed = self.io.outputs[name] != value
        if not changed and not force_write:
            return
        self.io.write(name, value)
        if not changed:
            return
        if name in ("acu1", "acu2"):
            index = int(name[-1]) - 1
            if value:
                self.on_since[index] = now
            else:
                self.off_since[index] = now
                self.on_since[index] = None
                if self.pending == index:
                    self.pending_since = None
        self.log("output", f"{name} {'ON' if value else 'OFF'}")

    def all_off(self, now):
        errors = []
        for name in OUTPUTS:
            try:
                # Always attempt a physical OFF, even if the cached command is OFF.
                self.io.write(name, False)
                if name in ("acu1", "acu2"):
                    index = int(name[-1]) - 1
                    self.off_since[index] = now
                    self.on_since[index] = None
            except Exception as exc:
                errors.append(f"{name}: {exc!r}")
        return errors

    def fatal(self, exc):
        with self.lock:
            self.cancel_output_test("fatal controller error")
            if self.controller_error is None:
                self.controller_error = f"{exc!r}; backend restart required"
            self.stop_event.set()
            self.boost = False
            self.pending = self.pending_since = None
            self.alarms = sorted(set(self.alarms) | {"CONTROLLER_ERROR"})
            errors = self.all_off(self.clock())
        self.log("engine_error", self.controller_error)
        for error in errors:
            self.log("output_error", error)

    def can_start(self, index, now):
        delay = self.settings["min_off_seconds"]
        return delay == 0 or now - self.off_since[index] >= delay

    def cooling(self, now):
        if self.mode == "manual":
            self.pending = self.pending_since = None
            return
        if self.mode == "pause":
            for name in ("acu1", "acu2"):
                self.set_output(name, False, now)
            self.pending = self.pending_since = None
            return
        if self.pending is None and now - self.last_rotation >= self.settings["rotation_seconds"]:
            self.pending = 1 - self.lead
            self.pending_since = None
            self.log("rotation", f"Handover requested to ACU{self.pending + 1}")
        if self.can_start(self.lead, now):
            self.set_output(f"acu{self.lead + 1}", True, now)
        if self.pending is not None:
            incoming = self.pending
            name = f"acu{incoming + 1}"
            if self.can_start(incoming, now):
                self.set_output(name, True, now)
            if self.io.outputs[name]:
                if self.pending_since is None:
                    self.pending_since = now
                if now - self.pending_since >= self.settings["handover_overlap_seconds"]:
                    previous = self.lead
                    self.lead = incoming
                    self.pending = self.pending_since = None
                    self.last_rotation = now
                    if not self.boost:
                        self.set_output(f"acu{previous + 1}", False, now)
                    self.log("rotation", f"Lead ACU{previous + 1} -> ACU{incoming + 1}")
        if self.pending is None:
            other = 1 - self.lead
            if self.boost and self.can_start(other, now):
                self.set_output(f"acu{other + 1}", True, now)
            elif not self.boost:
                self.set_output(f"acu{other + 1}", False, now)

    def update_alarms(self, now):
        temperature_ok = self.fresh("temperature_c", now)
        humidity_ok = self.fresh("humidity_pct", now)
        conditions = {
            "DOOR_OPEN": self.values["door_open"] is True,
            "WATER_LEVEL_ALARM": self.values["water_level_alarm"] is True,
            "SMOKE_ALARM": self.values["smoke_alarm"] is True,
            "HIGH_TEMPERATURE": temperature_ok and self.values["temperature_c"] >= self.settings["high_temp_alarm_c"],
            "HIGH_HUMIDITY": humidity_ok and self.values["humidity_pct"] >= self.settings["high_humidity_alarm_pct"],
        }
        alarms = set()
        if not temperature_ok or not humidity_ok:
            alarms.add("SENSOR_STALE")
        for key, (delay_setting, output) in TRIGGERS.items():
            if not conditions[key]:
                self.trigger_since[key] = None
            elif self.trigger_since[key] is None:
                self.trigger_since[key] = now
            active = (self.trigger_since[key] is not None
                      and now - self.trigger_since[key] >= self.settings[delay_setting])
            if active:
                alarms.add(key)
            if output is not None and not self.output_test and not self.suppress_tick_outputs:
                self.set_output(output, active, now)
        previous = set(self.alarms)
        self.alarms = sorted(alarms)
        for key in sorted(alarms - previous):
            self.log("alarm", key)
        for key in sorted(previous - alarms):
            self.log("alarm_clear", key)

    def tick(self):
        with self.lock:
            if self.controller_error or self.stop_event.is_set():
                return
            try:
                now = self.clock()
                # Preserve the restored snapshot for this tick; normal ownership
                # resumes on the next tick, not halfway through lease recovery.
                self.suppress_tick_outputs = False
                if self.output_test and now >= self.output_test["deadline"]:
                    self.restore_output_test(now)
                    self.suppress_tick_outputs = True
                for key, value in self.io.read_digital(self.settings["input_active_high"]).items():
                    self.values[key] = value
                    self.sample_times[key] = now
                if self.io.sim:
                    self.acquire_dht()
                if self.fresh("temperature_c", now) and self.fresh("humidity_pct", now):
                    if self.values["temperature_c"] >= self.settings["boost_on_c"]:
                        self.boost = True
                    elif self.values["temperature_c"] <= self.settings["boost_off_c"]:
                        self.boost = False
                else:
                    self.boost = False
                if self.mode != "auto":
                    self.boost = False
                if not self.output_test and not self.suppress_tick_outputs:
                    self.cooling(now)
                self.update_alarms(now)
            except Exception as exc:
                if not self.controller_error:
                    self.fatal(exc)

    def apply_settings(self, candidate):
        old = self.settings
        for key, relevant in RESET_SETTINGS.items():
            reset = any(old[name] != candidate[name] for name in relevant)
            input_name = {"DOOR_OPEN": "door", "WATER_LEVEL_ALARM": "water",
                          "SMOKE_ALARM": "smoke"}.get(key)
            if input_name:
                reset |= old["input_active_high"][input_name] != candidate["input_active_high"][input_name]
            if reset:
                self.trigger_since[key] = None
        self.settings = copy.deepcopy(candidate)

    def patch_settings(self, patch):
        with self.lock:
            self.reject_output_test_conflict()
            candidate = self.configuration.candidate(patch)
            self.configuration.save(patch, candidate)
            self.apply_settings(candidate)
            return self.configuration.contract()

    def settings_contract(self):
        with self.lock:
            return self.configuration.contract()

    def set_mode(self, mode):
        with self.lock:
            if mode not in ("auto", "manual", "pause"):
                raise ValueError("Allowed: auto, manual, pause")
            if self.controller_error or self.closed or self.stop_event.is_set():
                raise RuntimeError("Controller stopped; backend restart required")
            self.reject_output_test_conflict()
            if mode != self.mode:
                self.pending = self.pending_since = None
                self.boost = False
                if mode == "auto":
                    self.last_rotation = self.clock()
            self.mode = mode
            self.log("mode", mode)
            return self.status()

    def command_acu(self, acu, action):
        with self.lock:
            if acu not in (1, 2) or action not in ("on", "off"):
                raise ValueError("Choose ACU 1 or 2 and action on or off")
            if self.controller_error or self.closed or self.stop_event.is_set():
                raise RuntimeError("Controller stopped; backend restart required")
            self.reject_output_test_conflict()
            if self.mode != "manual":
                raise RuntimeError("Disable automatic switching by selecting MANUAL first")
            now = self.clock()
            name = f"acu{acu}"
            if action == "on" and not self.io.outputs[name] and not self.can_start(acu - 1, now):
                remaining = max(0, self.settings["min_off_seconds"] - (now - self.off_since[acu - 1]))
                raise RuntimeError(f"ACU {acu} restart delay active; retry in {remaining:.0f}s")
            try:
                self.set_output(name, action == "on", now, force_write=True)
            except Exception as exc:
                self.fatal(exc)
                raise RuntimeError("ACU command failed; backend restart required") from exc
            return self.status()

    def reject_output_test_conflict(self):
        if self.output_test:
            raise RuntimeError("Manual output testing active; end the test first")

    def require_output_test(self, session_id):
        if type(session_id) is not str or not session_id:
            raise ValueError("session_id must be a nonempty string")
        if self.controller_error or self.closed or self.stop_event.is_set():
            raise RuntimeError("Controller stopped; backend restart required")
        if not self.output_test or self.output_test["session_id"] != session_id:
            raise RuntimeError("Unknown or inactive output-test session")
        if self.clock() >= self.output_test["deadline"]:
            raise RuntimeError("Output-test session lease expired")
        return self.output_test

    def start_output_test(self):
        with self.lock:
            if self.controller_error or self.closed or self.stop_event.is_set():
                raise RuntimeError("Controller stopped; backend restart required")
            self.reject_output_test_conflict()
            self.output_test = {
                "session_id": uuid.uuid4().hex,
                "original_states": {name: self.io.outputs[name] for name in OUTPUTS},
                "deadline": self.clock() + OUTPUT_TEST_LEASE_SECONDS,
            }
            self.restoration_outcome = self.restoration_error = None
            return {
                "session_id": self.output_test["session_id"],
                "original_states": self.output_test["original_states"].copy(),
                "lease_seconds": OUTPUT_TEST_LEASE_SECONDS,
                "status": self.status(),
            }

    def command_output_test(self, session_id, channel, value):
        with self.lock:
            if channel not in OUTPUTS or type(value) is not bool:
                raise ValueError("Choose a configured output channel and boolean value")
            session = self.require_output_test(session_id)
            now = self.clock()
            try:
                self.set_output(channel, value, now, force_write=True)
            except Exception as exc:
                self.restoration_outcome = "failed"
                self.restoration_error = f"{channel}: {exc!r}"
                self.fatal(exc)
                raise OutputTestWriteError("Output-test write failed; backend restart required") from exc
            session["deadline"] = now + OUTPUT_TEST_LEASE_SECONDS
            return self.status()

    def heartbeat_output_test(self, session_id):
        with self.lock:
            session = self.require_output_test(session_id)
            session["deadline"] = self.clock() + OUTPUT_TEST_LEASE_SECONDS
            return self.status()

    def restore_output_test(self, now):
        session = self.output_test
        errors = []
        for name, value in session["original_states"].items():
            try:
                self.set_output(name, value, now, force_write=True)
            except Exception as exc:
                errors.append(f"{name}: {exc!r}")
        self.restoration_outcome = "failed" if errors else "restored"
        self.restoration_error = "; ".join(errors) if errors else None
        self.ended_output_tests[session["session_id"]] = self.restoration_outcome
        self.output_test = None
        if errors:
            self.fatal(RuntimeError(self.restoration_error))
            raise OutputTestWriteError("Output restoration failed; backend restart required")

    def end_output_test(self, session_id):
        with self.lock:
            if type(session_id) is not str or not session_id:
                raise ValueError("session_id must be a nonempty string")
            outcome = self.ended_output_tests.get(session_id)
            if outcome == "restored":
                return self.status()
            if outcome == "failed":
                raise OutputTestWriteError("Output restoration failed; backend restart required")
            self.require_output_test(session_id)
            self.restore_output_test(self.clock())
            return self.status()

    def cancel_output_test(self, reason):
        if self.output_test:
            if self.restoration_outcome != "failed":
                self.restoration_outcome = "cancelled"
                self.restoration_error = reason
            self.ended_output_tests[self.output_test["session_id"]] = self.restoration_outcome
            self.output_test = None

    def simulation_update(self, patch):
        with self.lock:
            if not self.io.sim:
                raise PermissionError("Simulation endpoint disabled in hardware mode")
            if self.closed or self.controller_error:
                raise RuntimeError("Controller stopped; backend restart required")
            self.io.simulation_update(patch)
            self.acquire_dht()
            for key in DIGITAL_FIELDS.values():
                if key in patch:
                    self.values[key] = patch[key]
                    self.sample_times[key] = self.clock()
            return self.status()

    def status(self):
        with self.lock:
            now = self.clock()
            ages = {key: None if sampled_at is None else max(0, now - sampled_at)
                    for key, sampled_at in self.sample_times.items()}
            freshness = {key: ("UNKNOWN" if self.values[key] is None or ages[key] is None
                               else "OK" if self.fresh(key, now) else "STALE") for key in self.values}
            return {
                "simulation": self.io.sim, "mode": self.mode,
                "sensors": self.values.copy(), "sensor_age_s": ages,
                "sensor_freshness": freshness,
                "acu_outputs": {key: self.io.outputs[key] for key in ("acu1", "acu2")},
                "alarm_outputs": {key: self.io.outputs[key] for key in ("water", "smoke", "temperature", "humidity", "door")},
                "lead_acu": self.lead + 1,
                "rotation_remaining_s": max(0, round(self.settings["rotation_seconds"] - (now - self.last_rotation))),
                "handover_pending": None if self.pending is None else self.pending + 1,
                "boost": self.boost, "alarms": self.alarms[:],
                "controller_error": self.controller_error, "fatal_error": self.controller_error,
                "output_test": {
                    "active": self.output_test is not None,
                    "original_states": (self.output_test["original_states"].copy()
                                        if self.output_test else None),
                    "lease_remaining_s": (max(0, self.output_test["deadline"] - now)
                                          if self.output_test else 0),
                    "restoration_outcome": self.restoration_outcome,
                    "restoration_error": self.restoration_error,
                },
            }

    def start(self):
        try:
            self._start_workers()
        except Exception:
            self.shutdown()
            raise

    def _start_workers(self):
        with self.lock:
            if self.closed or self.controller_error or self.threads:
                return
            try:
                self.io.start(self.settings["sensor_poll_seconds"])
            except Exception as exc:
                self.fatal(exc)
                self.io.close()
                raise

            def control_loop():
                while not self.stop_event.is_set():
                    self.tick()
                    with self.lock:
                        interval = self.settings["control_tick_seconds"]
                    self.stop_event.wait(interval)

            def acquisition_loop():
                while not self.stop_event.is_set():
                    try:
                        self.acquire_dht()
                    except Exception as exc:
                        self.log("sensor_error", repr(exc))
                    self.stop_event.wait(0.05)

            try:
                for target in (control_loop, acquisition_loop):
                    thread = threading.Thread(target=target, daemon=True)
                    thread.start()
                    self.threads.append(thread)
            except Exception as exc:
                self.fatal(exc)
                raise

    def shutdown(self, timeout=2):
        with self.lock:
            self.stop_event.set()
            if self.closed:
                return
            self.cancel_output_test("backend shutdown")
            errors = self.all_off(self.clock())
            self.closed = True
        deadline = time.monotonic() + timeout
        try:
            for thread in self.threads:
                if thread is not threading.current_thread():
                    try:
                        thread.join(max(0, deadline - time.monotonic()))
                    except Exception as exc:
                        errors.append(f"worker join: {exc!r}")
        finally:
            self.io.close()
        for error in errors:
            self.log("output_error", error)
