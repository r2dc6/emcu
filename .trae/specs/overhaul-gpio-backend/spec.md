# acuPilot GPIO Backend Overhaul Spec

## Why
The current backend assumes ACU run-feedback inputs that the installed system does not provide and lacks water detection and dedicated alarm relay outputs. Align the backend and affected HMI views with the actual hardware while retaining the existing cooling strategy.

## What Changes
- Read three digital GPIO inputs: door contact, high-water detection, and smoke detection; read temperature and humidity from one GPIO-connected DHT11.
- Control six independent relay outputs: ACU1, ACU2, water alarm, smoke alarm, temperature alarm, and humidity alarm.
- Preserve AUTO/PAUSE, lead rotation, temperature boost hysteresis, timed handover overlap, minimum restart delay, door warning delay, and stale-DHT fallback to single-unit cooling.
- **BREAKING** Remove ACU feedback inputs, run confirmation, feedback-derived ACU faults, and feedback-driven failover. Physical operation cannot be confirmed or failed equipment detected with this hardware.
- **BREAKING** Revise status/simulation fields and HMI state labels to use commanded ACU states, water status, and alarm output commands.
- Add validated, persistent runtime trigger settings with defaults and touchscreen editing.
- Separate configuration, hardware I/O, control engine, and API responsibilities into a small backend package; retain `main:app` as the launch entry point.
- Initialize and fail all six relay commands OFF; cleanly stop the worker and release hardware resources.

## Impact
- Affected specs: `coolshift-hmi` status normalization, Dashboard, Control, Sensors, Alarms, Settings, and related acceptance tests. This delta supersedes that spec's feedback/run-confirmation requirements only; unrelated unfinished HMI tasks remain out of scope.
- Affected code: `main.py`, `config.json`, `requirements.txt` if required, new backend modules and tests, `hmi/system_state.py`, `hmi/constants.py`, `hmi/backend_client.py`, `hmi/main_window.py`, affected `hmi/pages/`, `hmi/tests/smoke.py`, and `README.md`.
- Preserve acuPilot display branding, existing SQLite history, database/log/service filenames, legacy environment variables, and existing deployment commands.
- Existing worktree changes SHALL not be reverted.

## ADDED Requirements

### Requirement: Hardware Contract
The system SHALL support door, water, and smoke digital inputs plus one DHT11 data pin, and exactly six independently commanded relay channels. Use BCM numbering, explicit input active states and pull configuration, and per-output active HIGH/LOW configuration. A logical command SHALL not be represented as physical relay or ACU feedback.

Hardware mode SHALL require valid, distinct pin assignments across all inputs and outputs. Existing ACU1=17, ACU2=27, door=22, smoke=23, and DHT=4 assignments may be retained; new water and alarm pins SHALL remain unassigned until installation wiring is confirmed. Simulation SHALL remain enabled by default and work without GPIO dependencies or assigned hardware pins.

#### Scenario: Invalid wiring configuration
- **WHEN** hardware mode starts with missing, duplicate, or unsupported pins
- **THEN** startup is rejected before normal relay activation, with a clear configuration error.

#### Scenario: Input polarity
- **WHEN** an input configured active LOW reads LOW
- **THEN** its semantic condition is active; active HIGH behaves conversely, without the current polarity inversion.

### Requirement: Independent Alarm Outputs
The system SHALL map `WATER_LEVEL_ALARM`, `SMOKE_ALARM`, `HIGH_TEMPERATURE`, and `HIGH_HUMIDITY` to their respective water, smoke, temperature, and humidity relay commands. Any combination SHALL be ON simultaneously. Outputs SHALL follow qualified active conditions and clear automatically when conditions clear; no alarm latching or new ACU shutdown interlock is introduced.

Door and sensor-health alarms SHALL remain software alarms without additional dedicated relay channels. PAUSE SHALL stop ACUs but continue sensor acquisition and all alarm relay evaluation. Local HMI acknowledgement SHALL not alter relay commands.

#### Scenario: Multiple alarms in PAUSE
- **WHEN** high water, smoke, high temperature, and high humidity are simultaneously active in PAUSE
- **THEN** all four alarm relays are commanded ON and both ACU relays remain OFF.

#### Scenario: Independent clearing
- **WHEN** water clears while smoke remains active
- **THEN** only the water alarm relay clears; smoke remains ON.

### Requirement: Adjustable Triggers With Defaults
The backend SHALL expose `GET /api/settings` and `PATCH /api/settings`, with the effective merged settings returned after successful saving. Persist validated changes atomically in the existing configuration file and apply runtime-supported settings under the engine lock on the next control cycle. Failed validation or persistence SHALL leave both effective configuration and the saved file unchanged.

Missing settings SHALL resolve to defaults; invalid provided values SHALL be rejected rather than silently reset. `GET /api/settings` SHALL distinguish effective values, defaults, and restart-required hardware settings. Settings PATCH SHALL reject GPIO assignments, simulation mode, output polarity, and pull-mode changes; these remain installation settings applied only after restart.

Default runtime values:

| Setting | Default | Meaning |
| --- | --- | --- |
| `rotation_seconds` | 21600 | Lead rotation interval |
| `handover_overlap_seconds` | 15 | Actual commanded-ON overlap |
| `min_off_seconds` | 300 | Per-ACU restart delay |
| `boost_on_c` / `boost_off_c` | 27 / 25 | Cooling boost hysteresis |
| `high_temp_alarm_c` | 30 | Temperature alarm at or above threshold |
| `high_humidity_alarm_pct` | 65 | Humidity alarm at or above threshold |
| `door_alarm_seconds` | 60 | Continuous door-open delay |
| `water_alarm_seconds` | 0 | Continuous high-water delay |
| `smoke_alarm_seconds` | 0 | Continuous smoke assertion delay |
| `temperature_alarm_seconds` | 0 | Continuous high-temperature delay |
| `humidity_alarm_seconds` | 0 | Continuous high-humidity delay |
| `sensor_stale_seconds` | 30 | DHT sample expiry |
| `sensor_poll_seconds` | 3 | DHT acquisition interval |
| `control_tick_seconds` | 1 | Control cycle interval |
| Input active state: door / water / smoke | LOW / HIGH / HIGH | Electrical trigger levels |

Digital sensors SHALL offer active HIGH/LOW and continuous trigger-delay adjustment, not invented numeric water-height or smoke-concentration thresholds. Sensor-module comparator sensitivity, if present, is a hardware adjustment outside this API. Temperature and humidity SHALL offer numeric thresholds and trigger delays. Delay timers SHALL reset when their condition clears; changing a trigger setting SHALL reset that trigger's qualification timer.

Validate types, finite numeric values, temperature thresholds within DHT11's 0-50 C range, humidity thresholds within 0-100%, delays >= 0, polling >= 2 seconds, positive control/staleness intervals, staleness greater than the DHT poll interval, rotation >= 1800 seconds, restart delay >= 180 seconds, and `boost_on_c > boost_off_c`. Alarm thresholds SHALL not be unnecessarily coupled to cooling boost thresholds.

#### Scenario: No custom trigger settings
- **WHEN** an installation omits alarm settings
- **THEN** all effective defaults above are used and visible in settings.

#### Scenario: Persistent customization
- **WHEN** an operator saves a valid humidity threshold and water delay
- **THEN** the new settings take effect without restart and survive backend restart.

#### Scenario: Invalid save
- **WHEN** a save contains an invalid boost pair, nonfinite number, unknown setting, or fails to persist
- **THEN** the request fails visibly and no partial configuration is applied.

### Requirement: Sensor Acquisition and Freshness
The system SHALL poll digital inputs each control cycle and schedule DHT reads at `sensor_poll_seconds`, independently of control timing. Slow or transiently failing DHT acquisition SHALL not block ACU timing, digital alarms, API access, or shutdown. Hardware mode SHALL start with unknown DHT values until a valid sample is obtained, never fabricated 24 C / 50% readings.

Retain last valid DHT values with their own sample age and freshness. Invalid/failed samples SHALL not refresh freshness; unrelated digital changes or simulation updates SHALL not refresh DHT sample age. Stale DHT data SHALL disable boost and temperature/humidity threshold outputs, raise `SENSOR_STALE`, and leave digital alarms functioning.

#### Scenario: DHT unavailable
- **WHEN** no valid DHT sample arrives before expiry
- **THEN** readouts show UNKNOWN or retained STALE data, temperature/humidity relay commands are OFF, and smoke/water/door monitoring continues.

### Requirement: Safe Relay Lifecycle
All relay commands SHALL initialize OFF. Normal shutdown, SIGINT/SIGTERM, and an unrecoverable control-loop error SHALL attempt to command all six outputs OFF, even when logging or another channel write fails. An unrecoverable control-loop error SHALL stop automatic reactivation until backend restart.

Shutdown SHALL stop and join background work within a bounded interval and release GPIO/DHT resources. Partial hardware initialization failures SHALL release already acquired resources. Published output state SHALL update only after a successful write; a write error SHALL not be reported as a successful command.

#### Scenario: Fail OFF
- **WHEN** an unrecoverable control exception occurs while multiple outputs are ON
- **THEN** the backend attempts OFF on every channel independently and does not turn outputs back ON in the next cycle.

## MODIFIED Requirements

### Requirement: Command-Only Cooling Strategy
The system SHALL preserve the current main cooling logic except for dependencies on absent ACU feedback. AUTO maintains one lead ACU, periodically rotates lead, and enables both ACUs under temperature boost hysteresis. PAUSE commands both ACUs OFF. Minimum OFF time remains enforced per ACU.

Rotation SHALL wait until the incoming ACU is eligible and successfully commanded ON, then measure the configured overlap from that command transition, not from the original handover request. After overlap, change lead and command the previous unit OFF unless boost remains active. No fabricated run confirmation, start-failure detection, or physical-failure failover SHALL occur.

#### Scenario: Restart delay postpones rotation
- **WHEN** a rotation is requested but the incoming ACU is still inside its minimum OFF interval
- **THEN** the outgoing ACU stays commanded ON, and overlap begins only once the incoming ACU is commanded ON.

#### Scenario: No feedback hardware
- **WHEN** an ACU stays commanded ON beyond the old confirmation timeout
- **THEN** no ACU feedback fault is raised and normal rotation/boost continues.

### Requirement: API and HMI Truthful Status
`GET /api/status` SHALL retain existing mode, lead, rotation countdown, pending handover, boost, `acu_outputs`, and string-list `alarms` fields. Add `sensors.water_level_alarm`, four named `alarm_outputs` commands (`water`, `smoke`, `temperature`, `humidity`), explicit `acu_feedback_available: false`, and sensor freshness/age data that does not require comparing monotonic clocks across processes.

Remove `feedback1`, `feedback2`, and feedback-derived `failed` state. `POST /api/simulation` SHALL accept the actual digital/DHT inputs, permit explicit missing-DHT values for fault testing, reject legacy feedback/unknown fields, and remain unavailable in hardware mode. Keep `/api/status`, `/api/events`, `/api/mode`, and `main:app` launch compatibility.

Affected HMI views SHALL display `Commanded ON`, `Commanded OFF`, or UNKNOWN/offline; never RUNNING, confirmed stopped, or endless STARTING based on relay commands. Replace feedback sensor rows with high-water status and relevant relay-command visibility. Show the four alarm output commands, the new water alarm, and authoritative effective settings with touchscreen-safe numeric and HIGH/LOW controls. Retained offline values SHALL be marked stale, not shown as current physical output states.

Settings SHALL save only through the backend, handle rejection visibly, disable equipment-changing saves while offline, and retain edits made during a pending save rather than marking later edits as saved. Remove obsolete start-confirmation and feedback retry/reset controls. Manual per-ACU commands, server-side acknowledgement, new alarm interlocks, and unrelated API enhancements are out of scope.

#### Scenario: Updated HMI
- **WHEN** the backend reports ACU1 commanded ON and high water active
- **THEN** the HMI displays the command-only ACU state, high-water alarm, and water relay command without referring to ACU feedback.

#### Scenario: Touch access to simultaneous alarms
- **WHEN** active alarms or recent cleared alarms exceed the visible list at 800x480
- **THEN** an operator can reach every alarm through touch-safe scrolling with a vertical scrollbar at least 48 pixels wide and a draggable handle at least 48 pixels high.
- **THEN** alarm descriptions, acknowledgement buttons, and all four relay-command summaries remain readable within the page bounds.

### Follow-Up Scope: HMI Alignment Audit
The 2026-10-10 follow-up audit found the main backend/HMI feature alignment already implemented and the existing HMI suite passing 20/20. The remaining software delta SHALL be limited to touch-safe scrolling in the active and recent alarm lists and regression coverage using overflowing alarm fixtures. Preserve existing command-only states, water/four alarm commands, authoritative settings, pending-save edit handling, and offline safeguards. No new backend endpoints or cooling behavior are required.

## REMOVED Requirements

### Requirement: ACU Run Feedback and Fault Reset
**Reason**: There are no physical ACU feedback inputs, so start confirmation, feedback faults, both-ACUs-failed detection, and feedback failover cannot be supported.
**Migration**: Remove feedback pin/config/simulation fields, ignore legacy `start_confirmation_seconds` during startup configuration migration, and remove corresponding HMI controls and tests. Retain historical event rows without treating old faults as current.

`POST /api/reset-faults` SHALL temporarily return HTTP 410 with an explanatory message rather than silently claiming to clear nonexistent ACU faults. Document these API/configuration changes and the coordinated HMI update.

## Validation and Commissioning
- Automated tests SHALL cover configuration defaults/persistence, GPIO polarity and writes using fakes, sensor freshness, timer boundaries, rotation/boost/PAUSE, simultaneous alarms, API validation, error isolation, and shutdown cleanup.
- HMI offscreen tests SHALL cover updated command-only labels, water/alarm outputs, settings saving and failure handling, offline behavior, 800x480 layout, and >=48x48 touch targets.
- Physical commissioning SHALL confirm actual BCM assignments, pull modes, relay polarity, high-water semantics, each channel and concurrent alarm operation using dummy loads, and SIGINT/SIGTERM fail-OFF behavior.
- Physical checks unavailable in this workspace SHALL be recorded as deferred, never marked passed. This application is not a certified fire-safety or compressor-protection system; alarm indication is unavailable when the backend is stopped.
