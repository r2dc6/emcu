# acuPilot HMI - Implementation Plan

## Branding Update
- **Status**: `completed`
- **Description**: Rename app and HMI display branding to `acuPilot`, centralized
  as `APP_NAME` in `hmi/constants.py`. Update window/header, Qt metadata, CLI help,
  startup log, backend API title, deployment display names, and documentation.
  Preserve legacy environment variables, service/database/log filenames,
  specification folder, and `CoolShiftHMI` class for compatibility.
- **Verified**: 2026-10-09. All 16 offscreen smoke tests pass, including
  header/window branding, CLI help, backend title, service description, startup
  log, and SIGINT/SIGTERM shutdown checks. Python compilation and systemd user
  service validation pass. Deferred signal-handler logging prevents reentrant
  writes during shutdown.

## Task 1: Scaffold project structure and constants
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Create a Python package structure under `/home/rheg/App/hmi/` with `__init__.py`, `constants.py`, `theme.py`.
  - In `constants.py`: screen size (800x480), default backend URL (env-overridable `COOLSHIFT_BACKEND_URL`, default `http://127.0.0.1:8000`), poll interval (1000ms), staleness thresholds, min touch target 48px, page names.
  - In `theme.py`: centralized QSS stylesheet builder producing dark charcoal + blue accent + green/amber/red semantic colors; fonts and spacing tuned for 5-inch.
  - Append `PySide6>=6.5,<7` to `requirements.txt`.
- **Acceptance Criteria Addressed**: AC-1, AC-3, AC-14, NFR-1, NFR-2, NFR-3
- **Test Requirements**:
  - `rule` TR-1.1: Package imports without error; constants resolve; theme QSS compiles with no Qt warnings when applied to a QApplication.
  - `rule` TR-1.2: requirements.txt contains PySide6 with specified version range.
  - `rubric` TR-1.3: Theme quality; scale 1-5; anchors 1=no style, 3=basic dark, 5=charcoal dark + blue accents + semantic state colors + large readable fonts; threshold >=4; evidence: apply theme to a sample QLabel/QPushButton and screenshot.

## Task 2: Implement BackendClient (nonblocking)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - Create `hmi/backend_client.py` with `BackendClient(QObject)` using `QNetworkAccessManager` (no httpx required; Qt std network).
  - Methods: `fetch_status()`, `fetch_events(limit, kind_filter)`, `post_mode(mode)`, `post_reset_faults()`, `post_simulation(...)`, plus stubs for missing endpoints that return "not supported".
  - Every method posts work off GUI thread (QNAM runs on its own thread internally; ensure result handling via signals only).
  - Signals: `status_received(state: dict)`, `events_received(rows: list)`, `command_result(cmd_id, status: "pending|accepted|rejected|failed", detail)`, `connection_state_changed(online: bool, latency_ms: float)`, `error(message)`.
  - Add `start_polling(interval_ms)`, `stop_polling()`, exponential-backoff reconnect for persistent offline.
  - Measure round-trip latency per call and expose as moving average.
- **Acceptance Criteria Addressed**: FR-9, FR-11, FR-14, AC-4, AC-5, AC-16
- **Test Requirements**:
  - `rule` TR-2.1: Thread test: `QThread.currentThread()` at the moment QNetworkReply `finished` is emitted and signal handlers all run on GUI thread; no HTTP on GUI thread. Use a test-local thread-trace.
  - `rule` TR-2.2: Simulate backend offline (unreachable host) for 10s; signals include `connection_state_changed(online=False)`; controls-facing API reports offline; subsequent recovery emits `online=True` within 5 poll cycles.
  - `rule` TR-2.3: Timeout handling: status endpoint with a 5s artificial delay (use `QTimer::singleShot` + mock); BackendClient reports failure via `error`/connection signals; no GUI freeze.
  - `rubric` TR-2.4: Graceful error handling; scale 1-5; anchors 1=uncaught exceptions, 3=logs errors, 5=all failure modes (timeout, 4xx, 5xx, malformed JSON, DNS fail) emit typed `error` signal + never crash GUI; threshold >=4; evidence: unit test matrix of 5 failure modes.

## Task 3: Implement SystemState (validated snapshot)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - Create `hmi/system_state.py` with dataclasses/enums: `AcuiState(RUNNING,STANDBY,FAULT,STARTING,UNKNOWN)`, `AlarmSeverity(INFO,WARNING,CRITICAL)`, `SensorReading(value, freshness: OK|STALE|UNKNOWN, updated_at)`, `SystemState`.
  - Build `SystemState.from_status_payload(raw: dict, now_monotonic_sec, stale_threshold_s, backend_online: bool)` — normalizes `/api/status` into typed fields.
  - Derive ACU state per ACU: combine `acu_outputs[i]`, `failed[i]`, `sensors.feedback(i)`, start-confirmation window (use `updated_monotonic` to estimate; or flag STARTING when commanded ON but feedback False and not yet FAULT).
  - Add `alarm_definitions: dict[key -> {severity, description}]` mapping backend alarm keys plus synthetic `BACKEND_OFFLINE`.
  - Compute per-sensor freshness for temp/humidity based on `updated_monotonic`; never convert `None` to 0.
- **Acceptance Criteria Addressed**: FR-10, AC-6, AC-8, AC-9
- **Test Requirements**:
  - `rule` TR-3.1: Derivation test — payload `acu_outputs.acu1=true, failed[0]=false, feedback1=false, updated_monotonic recent` → ACU1 state != RUNNING (should be STARTING or similar).
  - `rule` TR-3.2: `temperature_c=None, humidity_pct=None, updated_monotonic > stale` → SensorReading states are STALE/UNKNOWN, not numeric 0.
  - `rule` TR-3.3: Known backend alarm keys each map to a severity and description; synthetic BACKEND_OFFLINE alarm appears when `backend_online=False`.
  - `rubric` TR-3.4: State normalization fidelity; scale 1-5; anchors 1=raw dict passthrough, 3=enums + stale markers, 5=every field typed, edge cases for all combinations of outputs/feedback/failed across both ACUs; threshold >=4.

## Task 4: Build reusable custom widgets
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 3
- **Description**:
  - Create `hmi/widgets.py` containing:
    - `StatusCard(title)`: large card container with rounded dark frame, title bar, content area.
    - `StateBadge(state, text, icon_char)`: semantic color + icon + text; never color alone.
    - `BigReadout(value_str, unit_str, label_str, condition: OK|WARN|FAULT|STALE)`: large numeric readout with unit and small label.
    - `IndicatorLamp(on, blink, color)`: small circular indicator for feedback/door/smoke rows.
    - `CountdownLabel`: displays HH:MM:SS; accepts seconds remaining; supports local-tick method to decrement by 1s (for FR-14 between polls).
    - `StaleOverlay(enabled: bool)`: overlays "STALE" badge with dim.
  - Guarantee every button subclass or pushable compound widget has minimum 48x48 size policy.
- **Acceptance Criteria Addressed**: NFR-1, NFR-2, NFR-3, AC-3, AC-6, AC-8, AC-12, AC-14
- **Test Requirements**:
  - `rule` TR-4.1: All interactive custom widgets report min size >= (48,48) via `minimumSizeHint()`.
  - `rule` TR-4.2: `CountdownLabel` local-tick: start at 3605, tick 3x → display "01:00:02".
  - `rule` TR-4.3: StateBadge with state=RUNNING always shows both color AND a distinct icon/text badge (no color-only information).
  - `rubric` TR-4.4: Industrial visual quality; scale 1-5; anchors 1=raw widgets, 3=styled, 5=cards + badges + big readouts look clean, compact, industrial on 800x480; threshold >=4.

## Task 5: Implement ConfirmDialog and NumericKeypad
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 4
- **Description**:
  - `hmi/dialogs.py` defines:
    - `ConfirmDialog(parent, title, message, confirm_text="Confirm", cancel_text="Cancel", dangerous: bool)`: modal, fixed-size fitting 800x480; two large bottom buttons; dangerous actions use red confirm.
    - `NumericKeypad(parent, initial_value, min_value, max_value, step=1, decimals=0, unit="")`: modal, fixed-size <= 720x400; grid with digits 0-9, backspace, clear, decimal (when decimals>0), cancel, enter; up/down step buttons optional; validation on enter.
  - All buttons >= 48x48.
- **Acceptance Criteria Addressed**: FR-12, FR-13, AC-7, AC-11, AC-15
- **Test Requirements**:
  - `rule` TR-5.1: Both dialogs `sizeHint()` + any frame <= 800x480 when shown as modal on a 800x480 parent; buttons min size pass.
  - `rule` TR-5.2: NumericKeypad entry `27.3` with min=0, max=50, decimals=1 accepted; `55.0` rejected; `12.34` rejected when decimals=1; cancel returns None/initial.
  - `rule` TR-5.3: ConfirmDialog: confirm returns True/Accepted, cancel returns False/Rejected; dangerous variant paints confirm button red.

## Task 6: Implement DashboardPage
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3, Task 4
- **Description**:
  - `hmi/pages/dashboard.py`: QWidget with grid layout fitting inside content area ~800x380 (excludes header/bottom bar).
  - Left column: BigReadout (temperature), BigReadout (humidity); small sensor health indicators.
  - Middle column: Two StatusCards for ACU1 and ACU2 with StateBadge + short runtime/feedback lines.
  - Right column: Mode badge, CountdownLabel, Boost indicator, Alarm summary (count + list of top active), Backend connection badge, last update time.
  - Public slot `update_state(state: SystemState)` redraws from snapshot; no direct BackendClient coupling here (wired in main window).
  - Local countdown ticking via 1-second QTimer on the page, using latest `rotation_remaining_s` baseline.
- **Acceptance Criteria Addressed**: FR-1, AC-1, AC-6, AC-12, AC-14
- **Test Requirements**:
  - `rule` TR-6.1: With a valid SystemState fixture, 9 required indicators are visible non-empty widgets (temp, humidity, ACU1, ACU2, mode, countdown, boost, alarm-summary, backend-status).
  - `rule` TR-6.2: BACKEND_OFFLINE + stale fields show STALE overlays on readouts; ACU states degrade to UNKNOWN.
  - `rubric` TR-6.3: "Understandable within 2 seconds"; scale 1-5; anchors 1=cluttered, 3=readable but info-dense, 5=large well-separated readouts and badges where a new viewer can identify temp/humidity/acu-states/mode/countdown/connections instantly; threshold >=4.

## Task 7: Implement ControlPage
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3, Task 4, Task 5
- **Description**:
  - `hmi/pages/control.py`: Two large horizontal StatusCards (ACU1, ACU2). Each card shows:
    - Requested output state (ON/OFF), Confirmed RUNNING state (feedback-driven), runtime N/A or local estimate, fault text (if any).
    - Start/Stop push buttons (clearly disabled when manual per-ACU endpoint is missing; tooltip "Requires backend manual command endpoint").
  - Top area: Mode selector (AUTO / PAUSE) with large toggle buttons; PAUSE action requires ConfirmDialog; Reset Faults button (disabled unless mode=PAUSE) with ConfirmDialog.
  - Command status banner: shows per-command PENDING → ACCEPTED/REJECTED/FAILED with timestamp from BackendClient `command_result` signals.
  - Buttons auto-disabled when backend offline.
- **Acceptance Criteria Addressed**: FR-2, FR-11, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-7.1: Mode AUTO→PAUSE opens ConfirmDialog; on confirm emits command and shows PENDING then ACCEPTED banner; on cancel no command sent.
  - `rule` TR-7.2: Reset Faults in AUTO mode disabled; in PAUSE mode opens dialog; simulating backend 409 displays REJECTED banner.
  - `rule` TR-7.3: Offline disables Mode toggle, Reset Faults, and both per-ACU Start/Stop buttons.
  - `rubric` TR-7.4: Command lifecycle visibility; scale 1-5; anchors 1=no status, 3=text banner only, 5=color-coded banner with timestamp, per-action progress, human-readable detail; threshold >=4.

## Task 8: Implement SensorsPage
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 3, Task 4
- **Description**:
  - `hmi/pages/sensors.py`: Grid of sensor rows.
    - Temperature: BigReadout + freshness indicator.
    - Humidity: BigReadout + freshness indicator.
    - Door contact: IndicatorLamp + text (CLOSED / OPEN / UNKNOWN).
    - Smoke detector: IndicatorLamp + text (CLEAR / ALARM / UNKNOWN); ALARM additionally red + amber warning text.
    - ACU1 feedback: IndicatorLamp + text (OK / NO / UNKNOWN).
    - ACU2 feedback: same.
    - Communication health summary card and "Last sensor update: ... ago (at wall clock)".
  - Render NONE values as UNKNOWN; never zeros.
- **Acceptance Criteria Addressed**: FR-3, AC-8
- **Test Requirements**:
  - `rule` TR-8.1: Mock state with temperature_c=None, humidity_pct=None, door/smoke/feedback UNKNOWN; page does not display 0.0 or 0% anywhere.
  - `rule` TR-8.2: Smoke alarm payload true → indicator RED + text label "ALARM" visible (not only color).
  - `rule` TR-8.3: "Last sensor update" shows age (seconds/minutes) when online and "N/A (backend offline)" when not.

## Task 9: Implement AlarmsPage
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 3, Task 4, Task 5
- **Description**:
  - `hmi/pages/alarms.py`: Two sections: ACTIVE ALARMS (top, separated header, any-count scroll area) and RECENT ALARMS (historical).
  - Each alarm row: severity badge (color+icon), alarm key description, triggered-at (or "active since unknown"), Acknowledge button for active alarms (local-only acknowledge tracked in the page; records a local timestamp).
  - Alarm definitions from SystemState; synthetic BACKEND_OFFLINE injected when offline.
  - Acknowledge is strictly UI-local: greys the row in active section but does not remove it; tooltip notes "Local only - requires backend ack endpoint".
- **Acceptance Criteria Addressed**: FR-4, AC-9
- **Test Requirements**:
  - `rule` TR-9.1: Backend offline adds BACKEND_OFFLINE to the active section with CRITICAL severity.
  - `rule` TR-9.2: Active alarms appear above historical; active with HIGH_TEMPERATURE + ACU1_FAULT both render; after tapping Acknowledge the row is visually dimmed but still present.
  - `rubric` TR-9.3: Alarm severity clarity; scale 1-5; anchors 1=text only, 3=color+text, 5=severity icons (bell/exclamation/wrench) + color + description + timestamps + ack state; threshold >=4.

## Task 10: Implement LogsPage with filters and batching
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2, Task 3, Task 4
- **Description**:
  - `hmi/pages/logs.py`: Compact scrollable QTableWidget/QListWidget rows: `[ts] [kind] [detail]` with small monospace-style font but readable.
  - Filter buttons at top: All / ACU / Alarm / System. Until a backend `kind=` filter is available, filter client-side over a rolling fetch window (last 500 rows by default, fetched on page open + refresh button).
  - Previous/Next page buttons (client-side paging of the in-memory batch); page size ~40 rows.
  - Explicit refresh button (large, 48x48+).
- **Acceptance Criteria Addressed**: FR-5, AC-10
- **Test Requirements**:
  - `rule` TR-10.1: Backend events fixture of 150 rows spanning output/alarm/alarm_clear/fault/mode/rotation kinds → filters All shows 150, ACU matches output+rotation+fault related, Alarm matches alarm+alarm_clear+fault, System matches mode+engine_error+simulation+fault_reset.
  - `rule` TR-10.2: Paging prev/next does not trigger refetches (only refresh button does); page sizes correct.
  - `rule` TR-10.3: Loading while the table has 200 rows -> GUI remains responsive (paint events happen); no frozen frames >500ms (verified by logging paint timestamps).

## Task 11: Implement SettingsPage with validation + numeric keypad
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3, Task 4, Task 5
- **Description**:
  - `hmi/pages/settings.py`: Four collapsible or stacked sections: Cooling, Protection, Alarms, System.
  - Cooling: rotation interval hours (default 6), boost_on_c, boost_off_c.
  - Protection: min_restart_delay_minutes, start_confirmation_timeout_seconds, handover_overlap_seconds, fault_retry_toggle (if supported; disabled otherwise).
  - Alarms: high_temp_c, high_humidity_pct, door_open_warning_delay_seconds.
  - System: display preferences (theme placeholder), backend status link, software info.
  - Each numeric field opens NumericKeypad on tap; shows inline error when invalid (e.g., boost_on <= boost_off, min_restart_delay < safe minimum of e.g. 3 minutes).
  - Dirty visual indicators (asterisk or tinted border); Save and Revert buttons at bottom bar.
  - Save flow: if backend endpoint PATCH /api/settings is present (detect by probing), call it; otherwise show an inline banner "Backend settings endpoint unavailable — saving disabled" and keep Save button disabled.
  - Default values initialized from `config.json` constants mirrored in SystemState defaults section (read `config.json` if file-readable; fallback in constants.py to numbers from existing config.json).
- **Acceptance Criteria Addressed**: FR-6, AC-11, AC-15
- **Test Requirements**:
  - `rule` TR-11.1: Validation tests: boost_on=22, boost_off=25 → inline error save disabled; min_off_seconds < 180 → inline error; rotation_hours < 0.5 → inline error.
  - `rule` TR-11.2: Dirty indicators: change any numeric → indicator appears; tap Revert → values restored, dirty cleared.
  - `rule` TR-11.3: Save attempts when endpoint probe absent → Save disabled + banner visible.
  - `rubric` TR-11.4: Settings usability; scale 1-5; anchors 1=unorganized, 3=sections exist, 5=clean sections, clear dirty state, keypad opens instantly, validation errors human-readable; threshold >=4.

## Task 12: Implement SystemPage
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2, Task 3, Task 4
- **Description**:
  - `hmi/pages/system.py`: Two cards: Backend connectivity and Software.
  - Connectivity card: Backend URL, current state (ONLINE/OFFLINE badge), last-successful poll (wall time), status endpoint moving-average latency (ms), poll count, error count.
  - Software card: HMI version (e.g., "0.1.0"), Python version, PySide6/Qt version, backend version either from `/api/info` stub or "unknown (backend /api/info missing)".
  - Diagnostic info button: opens a small dialog with last 50 BackendClient log lines (keep a bounded in-memory ring log).
- **Acceptance Criteria Addressed**: FR-7, AC-16
- **Test Requirements**:
  - `rule` TR-12.1: Online state shows latency + success time; offline state shows OFFLINE badge with large red color + icon/text; error count increments on simulated failures.
  - `rule` TR-12.2: Software card lists 5+ distinct labels (HMI ver, Python ver, Qt ver, backend URL, backend ver or missing note).

## Task 13: Implement CoolShiftHMI main window with header + bottom nav + QStackedWidget
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6, 7, 8, 9, 10, 11, 12
- **Description**:
  - `hmi/main_window.py`: `CoolShiftHMI(QMainWindow)` with a central widget layout:
    - Top header bar (~56px): app title "acuPilot", active alarm count badge (amber/red if any), BACKEND OFFLINE persistent banner if offline, clock.
    - Content area: QStackedWidget containing 7 pages.
    - Bottom navigation bar (~64px): 7 large icon/text buttons: Dashboard, Control, Sensors, Alarms, Logs, Settings, System. Each button min size 64x64. Active page highlighted with blue accent underline or fill.
  - Wires BackendClient signals to each page's `update_state` or data methods.
  - On closeEvent: stops polling, cleans threads, closes windows orderly.
- **Acceptance Criteria Addressed**: FR-8, NFR-1, NFR-2, AC-2, AC-3
- **Test Requirements**:
  - `rule` TR-13.1: 7 bottom-nav buttons navigate to each matching page in QStackedWidget; header + nav remain fixed; content never scrolls horizontally.
  - `rule` TR-13.2: Window logical size fixed to 800x480 (dev mode); fullscreen flag mode sets no title bar.
  - `rule` TR-13.3: closeEvent stops poll timer, no lingering timers/threads after window closes (assert no active QTimers attached to window).

## Task 14: Create hmi.py entry point + deployment artifacts
- **Status**: `completed`
- **Verified**: 2026-10-09. `hmi.py`, rotating logger, dev/env/CLI modes,
  signal cleanup, `deploy/coolshift-hmi.service`, PySide6 requirement, and
  README installation/kiosk instructions present. Smoke T16 launches the real
  entry point and verifies exit code 0 on both SIGINT and SIGTERM.
  `systemd-analyze --user verify deploy/coolshift-hmi.service` exits 0.
  Physical Raspberry Pi graphical-session autostart remains an on-device check.
- **Priority**: high
- **Depends On**: Task 13
- **Description**:
  - `/home/rheg/App/hmi.py`: Entry point:
    - Parse argv/env: `--dev` or env `COOLSHIFT_DEV=1` → 800x480 fixed window; otherwise fullscreen kiosk frameless.
    - `QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)` as needed but target logical 800x480.
    - Instantiate BackendClient, CoolShiftHMI; wire; show; install Python signal handlers (SIGINT, SIGTERM) → `QApplication.quit()`.
    - Diagnostic logger: `logging` module writing to `coolshift_hmi.log` in APP dir; rotating file handler; log level INFO default.
  - `deploy/coolshift-hmi.service` systemd unit example: `Type=notify` (or `simple`), `Environment=DISPLAY=:0`, `ExecStart=/home/rheg/App/.venv/bin/python /home/rheg/App/hmi.py`, `Restart=on-failure`, user slice; notes for Raspberry Pi OS autostart.
  - Update `README.md` (append section) with install + run instructions (desktop dev + kiosk).
- **Acceptance Criteria Addressed**: FR-15, AC-13
- **Test Requirements**:
  - `rule` TR-14.1: `python hmi.py --dev` launches a 800x480 window; SIGINT triggers clean shutdown with log line "HMI shutting down"; no zombie threads.
  - `rule` TR-14.2: `coolshift-hmi.service` file present with required fields (Unit/Service/Install sections, DISPLAY, ExecStart, Restart).
  - `rule` TR-14.3: requirements.txt includes PySide6; README.md HMI section describes both dev run and kiosk setup.
  - `rubric` TR-14.4: Deployment guide clarity; scale 1-5; anchors 1=no docs, 3=basic steps, 5=step-by-step venv, apt deps (Qt libs on Pi), xserver/display notes, systemd enable commands, log file location; threshold >=4.

## Task 15: Cross-cutting tests + layout smoke test
- **Status**: `completed`
- **Verified**: 2026-10-09. Installed the missing PySide6 dependency in `.venv`.
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke` exits 0:
  **16 passed, 0 failed**. Prints all seven page widget counts, button names,
  and an AC-1 through AC-16 widget inventory. Checks rendered 800x480 bounds,
  touch targets, navigation, state derivation, stale retained values, disabled
  offline controls, settings validation/revert, log paging, countdown, dialog
  bounds/flows, local HTTP failures/timeout/recovery, and clean signal shutdown.
  Qt 6 QNetworkAccessManager performs asynchronous transport internally;
  request submission and result handling intentionally stay on its GUI-thread
  owner. The thread test verifies server I/O off-thread, GUI-thread delivery,
  and event-loop responsiveness, not an off-thread QNAM submission call.
  Physical touch calibration and subjective visual rubrics are not certified
  by offscreen tests. Tasks 1-13 retain their original checklist statuses:
  their files exist, but a full task-by-task completion audit was not requested.
- **Priority**: high
- **Depends On**: Task 1-14
- **Description**:
  - Add a `hmi/tests/` directory (no top-level test runner required; simple scripts using PySide6 offscreen `QT_QPA_PLATFORM=offscreen`).
  - Tests: layout smoke at 800x480 (all pages, no overflow), thread check for BackendClient, SystemState derivation, settings validator, countdown tick, keypad entry, confirm dialog flow.
  - Ensure any interactive widget on every page has accessible objectName for automated inspection.
- **Acceptance Criteria Addressed**: AC-1 through AC-16 coverage end-to-end
- **Test Requirements**:
  - `rule` TR-15.1: `QT_QPA_PLATFORM=offscreen python -m hmi.tests.smoke` runs without crash; returns 0; prints per-page widget-count sanity.
  - `rule` TR-15.2: Per-page objectName inventory confirms every acceptance criterion has a corresponding widget to assert against.
