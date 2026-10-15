# Remove ACU Feedback and Enforce GPIO Levels

## Summary

Remove remaining ACU feedback compatibility code and terminology. Accepted ACU ON/OFF commands must drive the configured ACU GPIO HIGH/LOW respectively, without sensor confirmation. Preserve MANUAL-mode requirements, minimum restart delay, automatic cooling, alarms, simulation, and safe shutdown.

## Current State Analysis

- `backend/engine.py` already controls ACUs without feedback checks. `command_acu()` requires MANUAL mode, enforces restart delay, calls `set_output()`, and returns status after a successful write.
- `backend/io.py` routes named ACU channels through `OUTPUT_GPIO_KEYS` to configured BCM pins. GPIO devices honor `output_active_high`, which currently allows ACU ON to mean electrical LOW.
- `backend/config.py` retains feedback-key/start-confirmation migration. Its edited defaults use ACU1=21 and ACU2=36, although validation rejects BCM36. Actual `config.json` and existing mapping tests use BCM17/27.
- `backend/engine.py` still publishes `acu_feedback_available: false`; `backend/api.py` retains a feedback-related `/api/reset-faults` tombstone.
- Dashboard and Control cards contain "No physical run feedback" text. Tests retain feedback-specific fixtures, names, and assertions.
- Generic request/write failures, controller errors, minimum OFF timers, sensor alarms, and event history are not ACU feedback checks and must remain.

## Assumptions & Decisions

- User selected removal of all feedback compatibility references, including migration. Older feedback configurations will no longer be silently migrated.
- User selected retaining MANUAL-mode and restart-delay protections. Rejected requests must not change GPIO; accepted requests must apply the requested level before returning.
- ACU1/ACU2 must be active HIGH. Reject conflicting active-LOW configuration rather than overriding it silently. Alarm relay polarity remains configurable.
- Restore fallback ACU pins to BCM17/27, matching saved configuration. Preserve explicit valid installation overrides and do not assign unconfirmed alarm/water pins.
- Preserve `main:app`, ACU command endpoint/action schema, other settings/status fields, and historical database rows.
- Removing the feedback status field and obsolete reset route is an intentional API cleanup. The reset URL will return normal HTTP 404.
- Simulation must remain nonphysical. Automated GPIO tests use mock pins only; no live relay activation or service restart is authorized by this plan.
- Historical `.trae/specs` and prior plans remain intact as records. No broad deletion of generic fault handling or historical event filters.

## Proposed Changes

### 1. Configuration: `backend/config.py`

- Restore `DEFAULTS["gpio"]["acu1"]` and `["acu2"]` to 17 and 27.
- Validate `output_active_high.acu1` and `.acu2` as exactly `True`, in both simulation and hardware configuration, with clear errors identifying the conflicting channel.
- Keep independent alarm-output polarity and current restart-required settings behavior.
- Remove migration branches explicitly stripping feedback pin/polarity keys and `start_confirmation_seconds`.
- Retain unrelated legacy boolean-to-map output-polarity conversion if still needed; reject a resulting active-LOW ACU configuration.
- Explicitly reject unknown startup configuration keys, instead of silently retaining obsolete start-confirmation settings. Existing nested GPIO/key validation continues to reject obsolete sensor entries.
- Do not rewrite `config.json` unnecessarily; its current ACU pins and polarities already comply.

### 2. GPIO Contract: `backend/io.py`

- Keep explicit channel-to-pin mapping and successful-write-before-state-update behavior.
- Construct ACU output devices with enforced active-HIGH semantics after validation; alarm devices retain configured polarity.
- Ensure initialization and OFF cleanup leave ACU mock pins LOW.
- Keep the same write path for automatic cooling, manual commands, fatal OFF, and normal shutdown. No feedback input reads or waiting are added.
- Reissuing an accepted manual command must apply its requested GPIO level even when the cached command matches. Adapt `set_output()` with an explicit force-write option used by manual commands, retaining transition-only timing/history updates and avoiding redundant automatic-cycle writes.
- Preserve all-channel cleanup attempts and error isolation.

### 3. API/Status: `backend/engine.py`, `backend/api.py`

- Remove `acu_feedback_available` from status.
- Remove `/api/reset-faults` route and its feedback explanation.
- Preserve `acu_outputs` as the authoritative last successfully applied command, not physical operation telemetry.
- Retain `/api/acu/{acu}/command` with `{"action":"on"|"off"}`, existing MANUAL-mode/restart-delay rejection, and fatal handling for real GPIO write errors.
- A successful accepted command returns after the GPIO write; a failed write must not falsely update commanded state.

### 4. HMI: `hmi/pages/dashboard.py`, `hmi/pages/control.py`

- Replace feedback-related explanatory text with "Relay command only" while retaining Commanded ON/OFF and UNKNOWN/STALE behavior.
- Preserve current layout, touch dimensions, command progress, manual controls, alarms, and settings.
- Inspect `hmi/system_state.py`, `hmi/backend_client.py`, and remaining production HMI modules for obsolete feedback handling; remove only actual remaining references, not generic failed-command states or historical-event classifications.

### 5. Tests

- `backend/tests/test_config.py`: update migration tests to supported unrelated compatibility and generic unknown-key rejection; assert BCM17/27 defaults, both ACU active-LOW rejection paths, and retained alarm active-LOW support.
- `backend/tests/test_io.py`: replace the test expecting active-LOW ACU2 with gpiozero MockFactory tests proving both named ACUs initialize LOW, write HIGH on ON, write LOW on OFF, and use explicit configured BCM overrides. Test alarm active-LOW independently.
- `backend/tests/test_engine.py`: remove feedback-specific assertions/names; verify manual accepted/rejected commands, repeated command force-write behavior, unchanged restart timers/history for repeated commands, and failed-write state integrity.
- `backend/tests/test_api.py`: remove feedback flag expectations and reset-tombstone tests; verify reset path 404, current status schema, generic unknown-field rejection, and manual GPIO contract via injected mocked hardware.
- `hmi/tests/smoke.py`: remove feedback fields/terminology and obsolete confirmation-setting assertions; preserve positive command-only ON/OFF and missing-command UNKNOWN tests, all recent manual controls and alarm-scroll regressions.
- Use a targeted source search to confirm no feedback-related symbols or terminology remain in application Python or test files. Do not remove generic `failed`, hardware-write failures, or controller safety checks.

### 6. Documentation: `README.md`

- Document ACU ON=electrical HIGH and OFF=electrical LOW, required active-HIGH ACU configuration, valid BCM17/27 defaults, and configurable alarm polarity.
- Replace outdated feedback migration/status/reset descriptions with the current command-only contract and explicit legacy configuration rejection.
- State that commanded state is not proof of physical ACU operation, without retaining feedback-specific API concepts.
- Retain installation identifiers, historical event/database compatibility, and physical commissioning warnings.

## Verification

1. Run configuration and GPIO test modules first, including gpiozero mock-pin electrical assertions.
2. Run `.venv/bin/python -m unittest discover -s backend/tests` and repeat if any concurrency-sensitive tests fail.
3. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke`, retaining current manual-mode, alarm scrolling, settings, and lifecycle coverage.
4. Verify accepted manual ON/OFF and repeated commands write the correct configured mock pin immediately; mode/restart rejections perform no write.
5. Verify ACU active-LOW configuration is rejected, alarm active-LOW still works, valid named pin overrides are respected, and saved `config.json` loads unchanged.
6. Verify API status contains no feedback field and obsolete fault reset returns 404.
7. Search production/test Python for obsolete feedback/start-confirmation references; inspect every match rather than deleting unrelated failure handling.
8. Run `git diff --check`; review changes against this plan and preserve unrelated user changes.

## Acceptance Criteria

- No ACU feedback checks, compatibility migrations, status flags, reset route, or feedback-specific HMI/test references remain in active code.
- Both ACUs use configured BCM pins with ON=HIGH/OFF=LOW, including repeated manual commands, initialization, and shutdown.
- Conflicting ACU active-LOW configuration fails clearly; alarm polarity remains independent.
- ACU mode/restart protections, automatic cooling, independent alarms, and truthful command/error states remain unchanged.
- Fallback pin defaults match BCM17/27 and existing installation configuration is not silently changed.
- Backend and current HMI test suites pass. Electrical behavior is verified with mocks only; real installation commissioning remains outstanding.
