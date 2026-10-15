# Manual Output Testing Spec

## Why
acuPilot needs a touchscreen commissioning tool to exercise every ACU and alarm relay independently. Manual tests must be temporary and restore the output commands that existed before testing when the user leaves Settings.

## What Changes
- Append a full-width MANUAL OUTPUT TESTING section below all existing Settings content inside the scroll area.
- List six independent ON/OFF toggles: ACU 1, ACU 2, Water Alarm, Smoke Alarm, Temperature Alarm, and Humidity Alarm.
- Add a confirmed, backend-owned test session that snapshots all six commanded states, temporarily overrides automatic output writes, and restores the snapshot on exit.
- Use direct pin testing, as selected by the user: bypass ACU minimum restart delay for test writes and snapshot restoration, with an explicit dummy-load/disconnected-ACU warning.
- Restore on page departure, provide an explicit End Test action, and expire abandoned sessions through a backend lease.
- Preserve existing Settings Save/Revert, normal AUTO/MANUAL/PAUSE behavior outside testing, configuration, wiring, and acuPilot branding.
- No breaking changes to existing endpoint shapes; new API routes and additive status metadata only.

## Impact
- Affected specs: settings UI, relay control, manual ACU commands, alarm outputs, status API, HMI lifecycle, shutdown safety.
- Affected code: `backend/engine.py`, `backend/api.py`, `backend/io.py` (reuse existing named writes), `hmi/pages/settings.py`, `hmi/backend_client.py`, `hmi/main_window.py`, `hmi/system_state.py`, backend tests, HMI smoke tests, and commissioning guidance in `README.md`.
- Existing specifications cover GPIO control but not this temporary test-session capability. This is a separate change; existing worktree changes SHALL remain intact.

## ADDED Requirements

### Requirement: Settings Output Test Section
The HMI SHALL place a full-width manual testing section below the existing two-column Settings content, not within one existing column. It SHALL display all six named outputs with backend-authoritative Commanded ON/OFF states and independent toggle buttons, a Start Test action, an End Test action, and a visible test-status banner. Every interactive target and scrolling handle SHALL be at least 48x48 pixels and reachable at 800x480 without horizontal scrolling.

#### Scenario: Open Settings without testing
- **WHEN** the user opens Settings
- **THEN** the six outputs are listed with current command states; no output is changed and no snapshot is taken merely by viewing the page.
- **THEN** toggles remain disabled until a test session has been accepted.

#### Scenario: Confirm direct pin testing
- **WHEN** the user selects Start Test
- **THEN** a warning states that actual relays will be energized, automatic relay control is temporarily overridden, and compressor restart protection is bypassed; ACUs must be disconnected or replaced with dummy loads.
- **WHEN** the user cancels
- **THEN** no session starts and no outputs change.

### Requirement: Exclusive Temporary Session
The backend SHALL create at most one active test session under the engine lock. It SHALL atomically capture all six current commanded output states before any test write and return an opaque session identifier. Session start SHALL leave outputs unchanged and preserve the existing operating mode. Starting a test SHALL be rejected when the controller is stopped, closed, or in fatal error.

#### Scenario: Snapshot and ownership
- **WHEN** a confirmed test starts while outputs have mixed ON/OFF states
- **THEN** the backend stores that exact six-output snapshot, marks testing active, and leaves every output unchanged.
- **WHEN** another session is requested while one is active
- **THEN** the backend rejects it without replacing the original snapshot.

### Requirement: Independent Direct Output Commands
An active session SHALL accept exactly one named output and a strict boolean ON/OFF value per command, using the existing GPIO abstraction and installed polarity. ACU test writes and restoration SHALL deliberately bypass `min_off_seconds`. Writes SHALL be serialized with session start/end and control ticks. Automatic cooling and alarm evaluation SHALL continue monitoring inputs, freshness, and alarm conditions but SHALL not overwrite any relay while testing is active. Mode changes, ordinary ACU commands, and runtime settings writes SHALL be rejected during testing to avoid competing control changes.

#### Scenario: All six outputs independently
- **WHEN** the owner toggles any of the six outputs ON or OFF
- **THEN** only that output changes, including repeated ACU OFF/ON commands inside the normal restart delay.
- **THEN** subsequent control ticks do not undo the test state, and sensor/alarm reporting continues without fabricating sensor alarms from test writes.

#### Scenario: Invalid or stale command
- **WHEN** a command uses an unknown channel, non-boolean state, expired session, or wrong session identifier
- **THEN** the backend rejects it without changing outputs or renewing that session.

### Requirement: Restore Original States Before Page Departure
Ending a healthy test session SHALL attempt restoration of every saved output independently under the engine lock, using direct writes even if cached state matches. The HMI SHALL disable toggles, stop issuing new test commands, and request session end before completing navigation away from Settings. On successful restoration, the backend SHALL release the override and preserve the pre-test operating mode; normal control may change outputs on subsequent ticks according to current conditions. The snapshot SHALL not remain a permanent override.

#### Scenario: Leave Settings after testing
- **WHEN** the user selects any other page while testing is active
- **THEN** the HMI displays Restoring outputs and waits asynchronously for the backend end response before switching pages.
- **THEN** every output is restored to its pre-test commanded state before automatic control resumes, with no ACU restart-delay postponement.

#### Scenario: End Test or revisit Settings
- **WHEN** the user selects End Test
- **THEN** all six original states are restored while the user remains on Settings.
- **WHEN** a new test is later started
- **THEN** a new snapshot is captured; no old test toggles or late responses can reactivate an ended session.
- **WHEN** an end request is retried for an already-ended session
- **THEN** it is harmless and cannot restore an old snapshot over newer normal control or a newer session.

### Requirement: Abandoned Session Recovery
The backend SHALL use a monotonic 10-second session lease. The HMI SHALL renew it every 2 seconds only while Settings is active and testing has not begun ending. Valid output commands may also renew the lease. On expiry, the running backend SHALL restore the snapshot and release the session at the next control tick. The HMI SHALL attempt session end on graceful close/SIGINT/SIGTERM before network teardown within a bounded shutdown window; lease expiry is the fallback for client crashes or network loss.

#### Scenario: HMI disconnects during testing
- **WHEN** heartbeats stop due to disconnect, crash, or page departure
- **THEN** the backend restores the snapshot after the lease expires, no later than the next configured control tick after expiry.
- **THEN** the HMI shows UNKNOWN/OFFLINE and Restoration unconfirmed rather than claiming successful restoration without an acknowledgement.
- **WHEN** connectivity recovers
- **THEN** the HMI reconciles authoritative status without restarting the old test.

#### Scenario: Navigation restoration cannot be confirmed
- **WHEN** an end request fails or times out
- **THEN** Settings remains visible with a clear restoration-unconfirmed error, toggles disabled, and no further lease renewals; the UI remains responsive.
- **WHEN** status later confirms the session has ended
- **THEN** the pending navigation may complete.

### Requirement: Fatal Error and Shutdown Priority
Controller fatal errors and backend shutdown SHALL supersede snapshot restoration: cancel testing and independently attempt all six outputs OFF, never restoring pre-test ON states during shutdown or after a fatal error. A failed test write or restore write SHALL enter the existing fatal-error handling path; restoration SHALL attempt the other saved outputs before invoking all-six-OFF. Cached command states SHALL update only after successful physical writes.

#### Scenario: Output restoration fails
- **WHEN** one restore write fails
- **THEN** the backend attempts the remaining five restorations, reports failure, enters fatal state, and attempts all-six-OFF; the HMI does not show Restored.

#### Scenario: Backend exits while testing
- **WHEN** backend SIGINT/SIGTERM or fatal error occurs
- **THEN** all-six-OFF safety takes precedence over the snapshot, and no later session request can reactivate outputs.

### Requirement: API and Truthful Status
The backend SHALL add `POST /api/output-test/start`, `POST /api/output-test/output`, `POST /api/output-test/heartbeat`, and `POST /api/output-test/end`. Session mutations SHALL require the identifier; output requests SHALL require a known channel and strict boolean value, reject extra fields, and return authoritative status. Start SHALL return the owner identifier, original states, and lease duration. Status SHALL add `output_test` metadata with active state, remaining lease time, restoration outcome/error, and original command states when active, without exposing the owner identifier through general status polling. Use HTTP 422 for malformed requests and 409 for lifecycle/ownership/conflict rejections; write failures SHALL be explicit non-success responses.

#### Scenario: Pending and offline UI
- **WHEN** a request is pending, rejected, fails, or returns malformed data
- **THEN** the HMI shows the appropriate visible result without optimistic ON/OFF success; duplicate toggles and stale replies cannot race session end.
- **WHEN** offline
- **THEN** testing controls are disabled and output states are UNKNOWN or explicitly retained/stale, not physically confirmed.

## MODIFIED Requirements

### Requirement: Ordinary Output Ownership
Outside a manual output-test session, the current AUTO/MANUAL/PAUSE cooling behavior, protected ordinary ACU commands, independently controlled alarm relays, validated Settings Save/Revert flow, and fatal/shutdown all-six-OFF policy SHALL remain unchanged. During testing, the exclusive temporary override and conflict rejections described above apply. The HMI SHALL clearly indicate testing so manually forced alarm relay states are not mistaken for sensor-triggered alarm conditions.

#### Scenario: Regression behavior
- **WHEN** no test session is active
- **THEN** normal ACU restart protection, cooling rotation/boost, alarm qualification, mode changes, and settings persistence behave as before.

## REMOVED Requirements
None.

## Scope and Safety Limits
- Only the six configured relay outputs are included; door, water, smoke, and DHT input/data pins are never toggled.
- Test states and snapshots are runtime-only and SHALL NOT be written to `config.json` or restored after a backend restart.
- Software status describes commands, not measured relay contact or compressor operation.
- Exact restoration is guaranteed only for a reachable, healthy running backend with successful GPIO writes. Network loss uses lease recovery; backend exit uses all-six-OFF; power loss and electrical failure cannot be solved by this feature.
- Physical commissioning must use dummy loads/disconnected ACUs because the user explicitly chose direct pin testing.
