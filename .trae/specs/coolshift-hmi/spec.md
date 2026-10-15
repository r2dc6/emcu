# acuPilot HMI - Product Requirements Document

## Overview
- **Summary**: Production-oriented `hmi.py` PySide6-based touchscreen frontend for the acuPilot dual-ACU control system, running on a Raspberry Pi 4B with a 5-inch 800x480 capacitive touchscreen in landscape kiosk mode.
- **Purpose**: Provide complete monitoring and operator configuration capabilities for the acuPilot backend in a minimalist, industrial, finger-friendly interface.
- **Target Users**: Facility operators, maintenance technicians, and on-site personnel who need to monitor ACU status, acknowledge alarms, adjust settings, and manually control equipment.
- **Branding**: App and HMI display name is exactly `acuPilot`. Legacy
  `COOLSHIFT_*` variables, service/database/log filenames, specification folder,
  and `CoolShiftHMI` Python class name remain compatible.

## Goals
- Deliver a complete, touch-optimized HMI that displays all critical system information at a glance on the default dashboard.
- Provide safe, validated operator controls with proper confirmation flows for equipment-changing commands.
- Maintain a non-blocking UI with robust backend disconnection handling, stale data indicators, and automatic reconnection.
- Visualize all automation rules (rotation, boost, handover, failover, restart protection, alarms) without duplicating backend logic.
- Provide pages for dashboard, control, sensors, alarms, logs, settings, and system diagnostics.
- Support desktop development mode (800x480 window) and Raspberry Pi fullscreen kiosk deployment.

## Non-Goals
- Implementing any automation, safety, or GPIO logic in the HMI — these remain backend responsibilities.
- Remote access, authentication, TLS, or multi-user features — the HMI connects exclusively to localhost.
- Replacing or extending the backend's SQLite schema; the HMI accesses history exclusively through backend endpoints.
- Mobile or web-based interfaces — this is a local Qt Widgets application only.
- Fire safety or compressor protection logic; the HMI only displays what the backend reports.

## Background & Context
- The existing backend is a FastAPI server in `main.py` exposing:
  - `GET /api/status` — returns `{simulation, mode, sensors{temperature_c,humidity_pct,door_open,smoke_alarm,feedback1,feedback2,updated_monotonic}, acu_outputs{acu1,acu2}, lead_acu, rotation_remaining_s, handover_pending, boost, failed[bool,bool], alarms[str,...]}`
  - `GET /api/events?limit=N` — events table rows: `id, ts, kind, detail` (max 500)
  - `POST /api/mode` — `{"mode":"auto"|"pause"}`
  - `POST /api/simulation` — sim-only sensor overrides
  - `POST /api/reset-faults` — requires `mode==pause`
- Backend reads configuration once from `config.json` at startup; there is **no** runtime settings API.
- ACU states are `RUNNING|STANDBY|FAULT|UNKNOWN` derived from `acu_outputs[i] && feedback[i+1]`, `!acu_outputs[i] && !failed[i]`, `failed[i]`, and backend-unreachable respectively.
- Backend modes are `auto` and `pause`; the HMI spec also requests a `manual` per-ACU command concept (see Missing Backend Interfaces).

## Functional Requirements
- **FR-1 (Dashboard Page)**: Display room temperature (°C), humidity (%RH), ACU1/ACU2 state (RUNNING/STANDBY/FAULT/UNKNOWN), operating mode (AUTO/PAUSE), rotation countdown (HH:MM:SS), dual-ACU boost status, active alarm count/summary, and backend connection status.
- **FR-2 (Control Page)**: Two large ACU cards each showing commanded state, confirmed/running state, runtime (if derivable), fault status, and manual start/stop controls (if supported). Provide AUTO vs PAUSE mode selector with confirmation. Show command progress states PENDING → ACCEPTED/REJECTED/FAILED.
- **FR-3 (Sensors Page)**: Display DHT11 temp/humidity, door, smoke, ACU feedback inputs, sensor communication health, and last successful update timestamp. Render UNKNOWN and STALE states; never display zeros for failed DHT11 reads.
- **FR-4 (Alarms Page)**: Active alarms first, then historical. Show severity, description, trigger timestamp, active/cleared state, and an acknowledgement button (if supported). Include at minimum: HIGH_TEMPERATURE, ACUx_FAULT, SENSOR_STALE, DOOR_OPEN, SMOKE_ALARM, HIGH_HUMIDITY, BOTH_ACUS_FAILED, and BACKEND_OFFLINE synthetic alarm.
- **FR-5 (Logs Page)**: Paginated compact event list (timestamp, category, description). Filters: All / ACU / Alarm / System. Fetch in batches using the backend limit parameter.
- **FR-6 (Settings Page)**: Categorized settings editor for cooling, protection, alarms, and system sections. Use a touch numeric keypad for numeric fields. Validate inputs, show unsaved-vs-saved distinction, and persist only through the backend (with graceful degradation when a settings API is absent).
- **FR-7 (System Page)**: Backend connectivity status, latency/health, software versions, and diagnostic information.
- **FR-8 (Navigation)**: Fixed top header (title + alarm/badge) and bottom navigation bar with 7 page buttons using a QStackedWidget. Minimum 48x48 touch targets.
- **FR-9 (BackendClient)**: Dedicated nonblocking client using QThread/QThreadPool or QNetworkAccessManager. Handles timeouts, rejected commands, malformed JSON, and disconnections. Emits Qt signals on the UI thread. All API calls off the GUI thread.
- **FR-10 (SystemState)**: Validated snapshot type that normalizes `/api/status` output into typed sensor/ACU/mode/alarms/health fields, including STALE markers based on `updated_monotonic` + a freshness constant.
- **FR-11 (Failure Handling)**: On backend unavailable: keep last values, mark STALE, disable equipment-changing controls, show BACKEND OFFLINE banner, attempt reconnect without freezing UI, never assume ACUs stopped.
- **FR-12 (Confirmation)**: `ConfirmDialog` reusable widget for any command that changes equipment state or clears data.
- **FR-13 (Numeric Keypad)**: `NumericKeypad` touchscreen-friendly widget for numeric entry used on settings page.
- **FR-14 (Refresh)**: Poll status ~1/s; locally decrement the countdown between polls. Fetch logs only on the Logs page and when filters change.
- **FR-15 (Deployment)**: `hmi.py` entry point, desktop dev mode at 800x480 window, fullscreen kiosk mode on Pi, clean shutdown, systemd service example, requirements updates, installation instructions.

## Non-Functional Requirements
- **NFR-1 (Resolution)**: Exact 800×480 logical layout; no horizontal scrolling; all dialogs/keypads fit on screen.
- **NFR-2 (Touch)**: Every interactive element ≥48×48 px; large cards, concise labels, finger-friendly spacing.
- **NFR-3 (Style)**: Dark charcoal backgrounds, restrained blue accents; green=confirmed operation, amber=warning, red=fault. Never color alone — add text labels/icons.
- **NFR-4 (Responsiveness)**: GUI thread never blocked >100 ms. All network/JSON work off-thread.
- **NFR-5 (Readability)**: Large numeric readouts, high-contrast sans-serif fonts appropriate for 5-inch 800x480.
- **NFR-6 (Maintainability)**: Modular modules/classes; clear separation; reusable custom widgets.
- **NFR-7 (Safety by display)**: Do not show ACU as RUNNING based only on commanded output; require feedback and backend status agreement.

## Constraints
- **Technical**: Python 3, PySide6 (Qt Widgets), Raspberry Pi OS desktop, fullscreen kiosk, localhost FastAPI backend, no direct GPIO control.
- **Business**: Backend is the single source of truth for automation, safety, SSR control, and settings persistence. HMI never bypasses backend rules.
- **Dependencies**: Existing backend in [main.py](file:///home/rheg/App/main.py) (FastAPI, pydantic, SQLite); additional HMI deps: PySide6, possibly httpx or just urllib from stdlib.

## Assumptions
- Backend binds to `http://127.0.0.1:8000` (configurable via env/const).
- ACU "runtime" is not directly exposed; the HMI either computes it locally since last known transition or shows N/A.
- Alarm acknowledgement is not natively supported by the backend; the HMI will implement a local-only acknowledge UX (tracks acknowledged active alarm keys locally) and document the missing backend interface.
- Manual per-ACU start/stop commands are not supported by the current backend; the HMI will surface PAUSE as the safe global manual override and document a required backend extension for per-ACU manual mode.
- Settings API is missing; the HMI Settings page will read from an initial snapshot of `config.json` values carried in the SystemState default / derived from status, show pending edits, validate them, and for persistence either: (a) call a future PATCH `/api/settings` endpoint if added, or (b) show a clear "backend settings endpoint unavailable" message with a save-disabled UI.

## Missing Backend Interfaces (to be added, not silently assumed)
1. `GET /api/settings` and `PATCH /api/settings` (or equivalent) to read/persist cooling/protection/alarm thresholds without restart.
2. `POST /api/acu/{1|2}/command` body `{"action":"start"|"stop"}` for operator manual per-ACU control with backend-enforced safety rules, returning accepted/rejected/failed status.
3. `POST /api/alarms/{key}/acknowledge` to mark alarms acknowledged server-side with persistence in events.
4. Alarm severity metadata in the status payload (e.g., `{"alarms":[{"key":"HIGH_TEMP","severity":"critical","triggered_at":"..."}]}`).
5. `GET /api/events?kind=...` for server-side event category filtering and offset/cursor pagination.
6. `GET /api/info` returning `{version, uptime_s, backend_started_at, ...}` for System page.
7. ACU runtime counters (`acu_runtimes_s: [N,N]`) and last-transition timestamps in status.

## Acceptance Criteria

### AC-1: Dashboard fits 800x480 and shows the 10 required indicators
- **Type**: `rule`
- **Given**: A running HMI window fixed at 800x480 logical size and the default Dashboard page.
- **When**: The page renders with a fresh backend status (valid temp, humidity, lead ACU 1 running, boost off, 0 alarms, connected).
- **Then**: All of the following are visible without scrolling: temperature °C, humidity %RH, ACU1 state, ACU2 state, mode (AUTO/PAUSE), rotation countdown HH:MM:SS, boost indicator, alarm summary (count), backend status.
- **Pass Condition**: Visual inspection or automated pixel/widget enumeration confirms each of the 9 widgets/indicators exists and shows non-default values.
- **Evidence**: Screenshot of 800x480 window; or widget object names enumerated by a test showing `dashboard.temp_label`, `dashboard.humidity_label`, `dashboard.acu1_state`, `dashboard.acu2_state`, `dashboard.mode_label`, `dashboard.countdown_label`, `dashboard.boost_indicator`, `dashboard.alarm_summary`, `dashboard.backend_status`.

### AC-2: Navigation between 7 pages works via bottom bar
- **Type**: `rule`
- **Given**: HMI running, Dashboard page active.
- **When**: Operator taps each bottom-nav button in sequence.
- **Then**: QStackedWidget index transitions to the matching page; no page overflows horizontally; top header and bottom bar remain visible.
- **Pass Condition**: 7 pages each render without layout errors and become the current widget.
- **Evidence**: Navigation test log; or manual step-through with screenshots per page.

### AC-3: All interactive elements meet 48x48 minimum
- **Type**: `rule`
- **Given**: Entire HMI stylesheet applied.
- **When**: Every `QPushButton`, `QToolButton`, page-nav item, numeric keypad key, and confirmation button is measured.
- **Then**: All have sizeHint/minimum size >= 48x48 logical pixels.
- **Pass Condition**: No actionable widget with min-width or min-height < 48.
- **Evidence**: Static enumeration of button minimum sizes from a test or style inspection.

### AC-4: BackendClient calls never run on Qt GUI thread
- **Type**: `rule`
- **Given**: A small instrumentation that records `QThread.currentThread()` vs `QApplication.instance().thread()` at the moment of every HTTP/URL call in BackendClient.
- **When**: 10 status polls, 3 commands (mode auto→pause→auto, reset-faults), and 2 log fetches are executed.
- **Then**: 0 HTTP calls execute on the GUI thread; all result signals arrive marshalled to GUI thread.
- **Pass Condition**: Call-site thread != GUI thread && signal-receiver thread == GUI thread for every recorded call.
- **Evidence**: Test output listing (call_id, call_thread_is_gui, signal_thread_is_gui, ok).

### AC-5: Backend disconnection marks values STALE, disables commands, and attempts reconnect
- **Type**: `rule`
- **Given**: HMI connected to backend, data flowing. Backend process stopped.
- **When**: Next 3 poll cycles elapse.
- **Then**: (a) last values remain visible but labeled STALE; (b) BACKEND OFFLINE banner visible in header; (c) mode change, reset-faults, and any manual ACU controls are disabled (grayed); (d) reconnect attempts continue (poll calls still fire) without UI freeze.
- **Pass Condition**: Screenshot showing STALE markers + banner + disabled controls; subsequent backend restart causes HMI to return to connected state within 5 polls.
- **Evidence**: Two screenshots (offline state + recovered) + logs of poll attempts during disconnect.

### AC-6: ACU status derivation agrees with feedback, not just commanded output
- **Type**: `rule`
- **Given**: A synthetic backend status where `acu_outputs.acu1=true`, `failed[0]=false`, but `sensors.feedback1=false` and `starting_since` implies within start-confirmation window.
- **When**: Dashboard and Control page render ACU1 status.
- **Then**: ACU1 shown as STARTING/PENDING (not RUNNING) or a warning state, clearly distinguished from confirmed RUNNING.
- **Pass Condition**: ACU1 badge is not the green RUNNING state.
- **Evidence**: Test with injected mocked status payload; screenshot or assertion on rendered state label.

### AC-7: Mode-change and fault-reset require confirmation; command lifecycle PENDING→ACCEPTED/REJECTED shown
- **Type**: `rule`
- **Given**: HMI connected; Control page visible; mode AUTO, no faults.
- **When**: Operator taps PAUSE then confirms in dialog; then (separately) from PAUSE taps Reset Faults and confirms.
- **Then**: (a) ConfirmDialog appears before each command is sent; (b) after confirm, command shows PENDING until backend responds, then ACCEPTED (or REJECTED if backend returns 409 for reset-faults in wrong mode).
- **Pass Condition**: Confirmation dialog observed open; PENDING then ACCEPTED/REJECTED status label visible on Control page.
- **Evidence**: Sequence of screenshots or UI test state transitions.

### AC-8: Sensors page never shows 0.0°C or 0%RH for a missing DHT11 read
- **Type**: `rule`
- **Given**: Mocked status with `sensors.temperature_c=null`, `sensors.humidity_pct=null`, and `updated_monotonic` exceeding stale window.
- **When**: Sensors page renders.
- **Then**: Temperature and humidity cells show UNKNOWN or STALE text (not 0.0 or 0). Door/smoke/feedback cells similarly UNKNOWN when absent.
- **Pass Condition**: No numeric 0 displayed for missing sensor values.
- **Evidence**: Screenshot + DOM/text assertion of sensor value labels.

### AC-9: Alarm page lists active alarms first with BACKEND_OFFLINE synthetic
- **Type**: `rubric`
- **Dimension**: Alarm list comprehensibility and ordering
- **Scale**: 1–5
- **Anchors**: 1 = no active-first separation, missing synthetic offline alarm, no severity coloring; 3 = active first, severity color, missing at least one expected alarm type; 5 = active section clearly separated from historical, every expected key (HIGH_TEMPERATURE, ACUx_FAULT, SENSOR_STALE, DOOR_OPEN, SMOKE_ALARM, HIGH_HUMIDITY, BOTH_ACUS_FAILED, BACKEND_OFFLINE) represented with severity, non-color indicators (icon/text), and timestamps where derivable.
- **Pass Threshold**: >= 4
- **Evidence**: Screenshot with two active + some cleared alarms; check list of rendered alarm keys.

### AC-10: Logs page paginates and filters
- **Type**: `rule`
- **Given**: Backend events table with 200+ rows spanning ACU, Alarm, and System kinds.
- **When**: User opens Logs page and switches filters between All/ACU/Alarm/System and pages back/forward.
- **Then**: Filter narrows list (client-side if no server filter); page size <= ~50 rows; UI remains responsive while loading; batches load on navigation.
- **Pass Condition**: Each filter produces a filtered list; paging does not freeze the UI; no crash with large history.
- **Evidence**: Test with seeded SQLite; capture list lengths per filter + page transitions.

### AC-11: Settings validates entries and distinguishes saved vs unsaved
- **Type**: `rule`
- **Given**: Settings page open, default values loaded.
- **When**: User enters (a) `boost_on_c=22` with `boost_off_c=25` (invalid: on<off); (b) then corrects to `boost_on_c=27, boost_off_c=25` and an invalid `min_off_seconds=10` below a minimum safe threshold; (c) then enters valid values for all Cooling/Protection/Alarm numeric fields.
- **Then**: (a) inline field error + save disabled for conflicting boost pair; (b) inline error for unsafe restart delay; (c) all saved-vs-unsaved fields visually distinguished (e.g., asterisk, tinted border) until explicitly saved; save path either calls backend settings endpoint or — if missing — displays a clear "settings endpoint unavailable" message.
- **Pass Condition**: Validator blocks invalid saves; visual dirty indicators present; save flow graceful with or without endpoint.
- **Evidence**: Form screenshots for error states + unit tests on the validator function.

### AC-12: Countdown locally decrements between backend polls
- **Type**: `rule`
- **Given**: Backend status with `rotation_remaining_s=3605`; poll interval 1s.
- **When**: 3 seconds elapse without a fresh backend poll.
- **Then**: Dashboard countdown label decrements by ~3 seconds (displaying ~1:00:02) rather than remaining frozen at 1:00:05.
- **Pass Condition**: Label value changes by the expected amount when polls are artificially delayed.
- **Evidence**: Test script mocking poll interval; captured label value progression.

### AC-13: Deployment artifacts complete
- **Type**: `rubric`
- **Dimension**: Deployment completeness and clarity
- **Scale**: 1–5
- **Anchors**: 1 = missing requirements update or no dev mode; 3 = has hmi.py entry, requirements.txt updated, 800x480 dev mode; 5 = includes: hmi.py entry point, requirements.txt append with PySide6, installation shell commands for Pi, systemd `.service` example for graphical session, clean shutdown handling (SIGINT/SIGTERM → close windows and release threads), and diagnostic logger writing to a file.
- **Pass Threshold**: >= 4
- **Evidence**: File tree listing and file content inspection of deployment artifacts.

### AC-14: Dark industrial theme with green/amber/red semantics plus icons/text
- **Type**: `rubric`
- **Dimension**: Visual design quality and accessibility
- **Scale**: 1–5
- **Anchors**: 1 = default Qt Fusion look, no color semantics, relies on color alone; 3 = dark background, blue accents, colored state indicators but missing some icon/text companions; 5 = charcoal dark theme, restrained blue accents, every RUNNING (green) / WARNING (amber) / FAULT (red) state paired with a distinct icon or text badge plus color, large readable fonts, no information carried solely by color.
- **Pass Threshold**: >= 4
- **Evidence**: Full-page screenshot dashboard+alarms+controls.

### AC-15: ConfirmDialog and NumericKeypad fit 800x480 and are usable by touch
- **Type**: `rule`
- **Given**: 800x480 window.
- **When**: ConfirmDialog and NumericKeypad opened as modal dialogs.
- **Then**: Neither dialog exceeds 800x480 extents; every button/target is >=48x48; Cancel/Confirm clearly distinguishable; keypad includes digits, backspace, clear, decimal, cancel, enter.
- **Pass Condition**: Dialog geometry fits; min size checks pass; keypad contains required keys.
- **Evidence**: Screenshots of both dialogs + button size enumeration.

### AC-16: System page shows connectivity/latency and basic info
- **Type**: `rule`
- **Given**: HMI connected, System page open.
- **When**: Page renders and several status polls occur.
- **Then**: Displays: backend URL/host, connection state (ONLINE/OFFLINE), last successful poll timestamp, moving average latency for status API, software version labels (hmi, backend if /api/info present or fallback).
- **Pass Condition**: All listed items present with non-placeholder values when online.
- **Evidence**: Screenshot of System page; test enumerating displayed labels.

## Open Questions
- [ ] Confirm backend URL default: `http://127.0.0.1:8000` acceptable, or should it read an env var like `COOLSHIFT_BACKEND_URL`?
- [ ] Alarm acknowledgement: Is server-side persistence planned soon, or is local-only ack acceptable for v1?
- [ ] Manual per-ACU control: Should v1 HMI simply disable these buttons and note "requires backend endpoint", or implement them against a stub we define in the backend extension list?
- [ ] Settings persistence: Are we allowed to add `GET/PATCH /api/settings` to the existing backend as part of this delivery, or strictly document the gap and leave HMI in "read-only display of current defaults + save disabled" mode?
