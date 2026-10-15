# Door Alarm Output on BCM GPIO0

## Summary

Add a seventh relay output named `door`, mapped separately from the door input through `gpio.alarm_door = 0`. Set `door_alarm_seconds` to 3 in application defaults, HMI fallback defaults, and the installed configuration. When the door remains continuously open for at least 3 seconds, qualify `DOOR_OPEN` and command the output HIGH. Closing the door clears the alarm, resets its timer, and commands LOW on the next control tick.

## Current State Analysis

- `backend/config.py` separates logical input and output mappings. The door input uses `gpio.door`; there is no door output. Six outputs currently exist, and BCM0 is accepted by validation.
- `backend/engine.py` already times `DOOR_OPEN` using `door_alarm_seconds`, but its `TRIGGERS` output is `None`. The timer defaults to 60 seconds. Alarm qualification uses monotonic elapsed time and `>=`.
- `backend/io.py` constructs outputs from `OUTPUT_GPIO_KEYS`, initializes them OFF, and closes them OFF. Alarm polarities are configurable; ACU polarities are required to be active-HIGH.
- `config.json` explicitly selects hardware mode, door input BCM22 with active-LOW semantics, ACUs BCM9/16, and four alarm output assignments. No current assignment uses BCM0.
- `backend/api.py`, `hmi/output_test.py`, and `hmi/system_state.py` explicitly enumerate the existing output channels.
- Manual testing owns all outputs temporarily, snapshots/restores their states, and suppresses normal relay writes while continuing alarm qualification. Fatal errors and shutdown independently attempt every output OFF.
- `hmi/pages/settings.py` generates test controls from `OUTPUT_CHANNELS`; `hmi/pages/dashboard.py` generates its relay summary from `SystemState.alarm_outputs`.
- `hmi/constants.py` contains a separate fallback door delay of 60 seconds.
- The worktree already contains extensive uncommitted changes. Some `backend/tests/test_config.py` expectations and README pin descriptions predate the current configuration. Preserve existing implementation and installed wiring.

## Assumptions and Decisions

- User-confirmed timing: the door must remain open for 3 continuous seconds, not a check that the configured setting exceeds a threshold.
- Pin numbering is BCM: GPIO0 is physical header pin 27, not BCM27. Keep the door input separate and unchanged.
- Use the existing adjustable `door_alarm_seconds` setting rather than a second timer or a hard-coded delay. Its initial/default value becomes 3; future settings edits intentionally affect both the alarm and relay.
- Require `output_active_high.door` to be exactly `true` so commanded ON always means electrical HIGH. Existing water/smoke/temperature/humidity polarity flexibility remains unchanged.
- Normal alarm output behavior applies in AUTO, MANUAL, and PAUSE. Existing exclusive manual output testing can override the door output until end or lease expiry; restore the seven-output snapshot before normal control resumes.
- With a 1-second control tick, activation occurs on the first tick at or after 3 seconds since open was first observed. Closing is likewise acted upon on the next tick. Do not promise asynchronous or sub-tick response.
- No new API endpoints, database migrations, alarm identifiers, input-polarity changes, service changes, or automatic application/service startup.
- GPIO0 is commonly reserved for HAT EEPROM identification. Physical commissioning must confirm no HAT/overlay/other peripheral owns this pin. Software cannot guarantee its level during boot, power loss, or electrical failure.

## Proposed Changes

### 1. Configuration and Physical Output

- `backend/config.py`: append `"door": "alarm_door"` to `OUTPUT_GPIO_KEYS`, add `gpio.alarm_door = 0`, change the door delay default to 3, and extend exact-true polarity validation to `door`. The generated `OUTPUTS` and default polarity dictionary then include seven channels.
- `config.json`: add only `gpio.alarm_door: 0` and `output_active_high.door: true`, and change `door_alarm_seconds` from 60 to 3. Preserve all other current values.
- `backend/io.py`: treat door like ACU outputs for explicit active-HIGH device construction. Retain generic write, initialization, failure cleanup, and close loops, which already use the output mappings.
- Existing configurations missing the new keys inherit the new pin and polarity through the current defaults merge. Explicit older delay overrides remain honored. A duplicate BCM0 assignment is rejected in hardware mode; do not silently remap pins.

### 2. Alarm Control and API

- `backend/engine.py`: map `DOOR_OPEN` to output `door`; include `door` in `status()["alarm_outputs"]`. Reuse qualification, timer reset, setting/polarity reset, event logging, test suppression, snapshot restoration, and fail-OFF paths.
- `backend/api.py`: add `door` to `OutputTestCommand.channel`. It denotes the new alarm output, never the door input. Preserve strict boolean, ownership, lease, and extra-field validation.
- Status gains the additive `alarm_outputs.door` boolean; output-test snapshots contain all seven output commands.

### 3. HMI Integration

- `hmi/constants.py`: change fallback `door_alarm_seconds` to 3.
- `hmi/system_state.py`: parse the door alarm command with the other alarm outputs, keeping missing/invalid data UNKNOWN.
- `hmi/output_test.py`: add `"door": "Door Alarm"` to `OUTPUT_CHANNELS` and require the door output in valid test-status payloads. This deliberately disables test controls against an older six-output backend.
- Reuse generated Settings test rows and Dashboard relay summary without adding new pages or changing the door sensor display. Modify `hmi/pages/settings.py` or `hmi/pages/dashboard.py` only if seven-row rendering verification exposes a necessary integration issue.
- Preserve backend-authoritative commands, warning confirmation, asynchronous navigation/restoration, and at least 48-pixel touch targets with scrolling at 800x480.

### 4. Regression Tests

- `backend/tests/test_config.py`: cover new default pin/delay, legacy six-output dictionary merging, exact-true door polarity, BCM0 validity/conflict detection, and unchanged unrelated installed values. Replace hard-coded ten-pin fixture generation with `len(PIN_KEYS)` and reconcile stale assertions with the currently inspected wiring, without modifying that wiring.
- `backend/tests/test_io.py`: extend configured-pin fixtures and binding expectations with door BCM0; assert startup LOW, ON HIGH, OFF LOW, cleanup LOW, and separate read-only door input.
- `backend/tests/test_engine.py`: add fake-clock tests for closed, opening, 2.999 seconds, exactly 3 seconds, continued open, close, reopen, and close-before-delay reset. Cover all operating modes, delay edits, input polarity, independent alarms, and fatal/shutdown OFF. Expand alarm combinations to all five alarms or explicitly assert door separately where other tests previously assumed four.
- `backend/tests/test_api.py`: assert the five-key alarm output contract and settings delay of 3.
- `backend/tests/test_output_test.py`: use `repeat=len(OUTPUTS)` for all 128 snapshots across modes; include the door in independent writes, restoration, lease recovery, and failures. Keep door active-HIGH in mixed-polarity tests and replace previously invalid `door` test channels with a genuinely unknown name.
- `backend/tests/test_output_test_api.py`: accept strict door-output commands; preserve rejection of unknown/input-only/data channels and invalid values.
- `backend/tests/test_signals.py`: verify the seventh output participates in signal-triggered fail-OFF where fixtures/assertions enumerate outputs.
- `hmi/tests/smoke.py` and `hmi/tests/output_testing.py`: add door commands to payloads and original-state fixtures, test UNKNOWN handling, accepted door toggles and restoration, and verify every seven-channel row is reachable/readable at 800x480.

### 5. Documentation

- `README.md`: document five alarm relays/seven total outputs, door alarm BCM0 active-HIGH, the 3-second continuous-open delay, LOW on close, the additive status field, manual testing/restoration, and all-seven-OFF handling.
- Update related channel counts to eleven total GPIO assignments and align pin tables with the current defaults versus installed configuration without changing assignments.
- Include the BCM0/HAT EEPROM caution, commissioning steps, and boot/power-loss limits.
- Leave completed historical `.trae/specs/add-manual-output-testing/` evidence unchanged; its six-output results describe the earlier implementation.

## Verification

1. Before editing, reread touched files and preserve existing user changes. Confirm the implementation diff only adds the agreed door output and required integration/regression updates.
2. Run `.venv/bin/python -B -m unittest discover -s backend/tests -v`, using temporary configuration/databases in test fixtures. Do not instantiate the real installed hardware controller for automated verification.
3. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m hmi.tests.smoke`; ensure test logs/screenshots/caches go outside the project where the harness permits.
4. Verify mock GPIO0 is LOW initially, remains LOW before 3 seconds, becomes HIGH at 3 seconds, returns LOW on close, and remains independent of door input GPIO22.
5. Verify all 128 seven-output test snapshots restore exactly, door sensing/qualification continues during test override, and normal door control resumes after restoration. Confirm fatal errors and shutdown attempt door OFF.
6. Inspect 800x480 Qt rendering: Door Alarm name/state/toggle reachable, no horizontal scrolling, preserved contrast and touch targets. Run backend and HMI together only with explicitly simulated, temporary configuration.
7. Report any pre-existing or environment-dependent test failures separately; do not claim physical commissioning.
8. Deployment requires a backend/HMI restart after approval and implementation. Physical acceptance with a suitable dummy load: confirm GPIO0 is available, open for less than 3 seconds (LOW), hold open through qualification (HIGH), close (LOW), reopen (fresh timer), and verify shutdown LOW. Do not modify boot overlays or restart services automatically.

## Acceptance Criteria

- Installed and default door delay is 3 seconds.
- A continuously open door qualifies `DOOR_OPEN` and drives BCM0 HIGH at the first eligible tick; closing clears both and drives LOW.
- `alarm_outputs.door`, the Door Alarm HMI row, and manual test commands refer to the new output, not the input pin.
- Seven outputs participate in initialization, testing, restoration, and fail-OFF; unrelated cooling, alarms, input semantics, and wiring remain unchanged.
- Automated mock/simulation verification passes or any remaining blockers are explicitly reported.
