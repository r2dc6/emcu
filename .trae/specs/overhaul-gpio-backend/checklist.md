# Verification Checklist

## Automated and Source/Documentation Checks

These passes concern software behavior, simulation, GPIO fakes, and source/documentation review, not physical commissioning.

- [x] Only door, high-water, smoke, and DHT11 inputs are configured; no ACU feedback is required or simulated.
- [x] Six relay commands exist with independent output polarity; missing/duplicate/invalid pins prevent hardware activation.
- [x] Simulation is default ON and runs without GPIO dependencies or commissioned new pin assignments.
- [x] Active HIGH/LOW and pull configuration produce correct logical digital states without inverted semantics.
- [x] DHT polling respects its interval, does not block control/API access, starts unknown in hardware mode, and preserves valid-sample freshness on errors.
- [x] Digital/simulation updates do not falsely refresh DHT samples; stale DHT disables boost and environmental alarm outputs while digital alarms continue.
- [x] AUTO lead cooling, rotation, boost hysteresis, minimum OFF delay, PAUSE, and stale-DHT single-unit fallback remain operational.
- [x] Handover overlap starts only after the incoming ACU's successful ON command and lasts the configured duration even after restart-delay postponement.
- [x] No run-confirmation timeout, feedback-derived faults, or fabricated physical-failure failover remains.
- [x] Water/smoke/temperature/humidity alarms independently drive their corresponding relays, including all four simultaneously and while PAUSED.
- [x] Trigger delays reset on condition clear/settings change; clearing or locally acknowledging one alarm cannot clear another active relay.
- [x] Numeric thresholds and digital active levels/delays have visible defaults, validated runtime editing, and no invented analog water/smoke measurements.
- [x] GET/PATCH settings return authoritative effective values and defaults; hardware-only settings are clearly restart-required and rejected by runtime PATCH.
- [x] Valid settings persist atomically and survive restart; invalid fields, nonfinite values, persistence failures, and concurrent access cause no partial changes.
- [x] Status/simulation expose water, four named alarm commands, command-only ACUs, and independent sensor ages; legacy feedback mutations are rejected.
- [x] Supported API paths, `main:app`, SQLite history, legacy identifiers, and acuPilot display branding are preserved; fault reset returns explanatory HTTP 410.
- [x] HMI shows Commanded ON/OFF or UNKNOWN without implying confirmed running/stopped and replaces feedback rows with actual hardware information.
- [x] HMI settings support numeric and HIGH/LOW editing, backend-loaded defaults, Save/Revert, visible failure handling, pending-save snapshots, and offline save disabling.
- [x] HMI retains truthful offline/stale displays, fits 800x480, and keeps all interactive targets >=48x48. Reopened by the 2026-10-10 follow-up for the previously 10-pixel-wide active alarm scrollbar; closed by independent Task 13 verification below.
- [x] Initialization, shutdown, SIGINT/SIGTERM, and fatal control errors attempt all-six-OFF independently; failed writes do not claim success and fatal errors do not automatically reactivate outputs.
- [x] Background work terminates within a bounded interval and acquired GPIO/DHT resources are released even after partial initialization or logging failure.
- [x] Backend automated tests and updated HMI smoke tests pass with recorded evidence.
- [x] README documents wiring prerequisites, defaults, breaking migration, command-only limitations, all-relays-OFF policy, and dummy-load commissioning.

## Final Verification Evidence

Final completion verification on 2026-10-10 supersedes the interim 42-test evidence and resolved thread-start cleanup blocker. The approved spec, full checklist/tasks, current backend source/tests, HMI state contract/regression assertions, and README were reviewed against these checkpoints. All 23 software/documentation checkpoints pass after Task 10's test-only history race fix and repeated full runs; the three physical gates below remain explicitly deferred.

- `.venv/bin/python -m unittest discover -s backend/tests`: two consecutive post-fix full runs passed 47/47 in 8.670s and 7.477s, zero failures. Covers configuration/defaults/migration, atomic persistence/rejection/concurrency, fake GPIO polarity/writes, DHT scheduling/freshness, timer boundaries, rotation/boost/PAUSE, API contracts, error isolation, and lifecycle cleanup.
- Task 10 resolved the auditor-reported flaky history assertion: a live worker can legitimately append an ACU output event after the retained row. The test now checks retained-row membership and each returned row's schema, retaining invalid-limit and history-error checks. No application code defect was established or application code changed.
- `test_all_sixteen_alarm_combinations_auto_and_pause` passed all 16 alarm combinations in both AUTO and PAUSE, including independent clearing and both ACUs OFF in PAUSE.
- Tasks 7/9 regressions passed: process/resource creation and first/second thread-start failures release acquired hardware; worker-join and DHT teardown exceptions do not skip OFF/close; blocked real DHT child teardown stays within the test's two-second bound. The obsolete thread-start cleanup blocker is resolved.
- `test_sigint_sigterm_fail_off_and_join` passed with actual SIGINT/SIGTERM delivered to real Uvicorn subprocesses, without mocking signal handling. Assertions verify closed engine, all six simulated commands OFF, and stopped worker threads; they do not establish electrical relay states or physical ACU operation.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke`: 20/20 passed, zero failures. T04/T17 verify command-only states, water/four alarm commands, independent freshness, local acknowledgement, and offline truth; T18/T19 verify authoritative GET/PATCH settings, rejection, defaults, HIGH/LOW editing, Save/Revert, pending-save snapshots, and offline disabling.
- HMI T20 passed relay text actual/required height 54/54 px and alarm summary 19/19 px within Dashboard bounds, touch-safe scrolling to lower settings, backend-compatible numeric ranges, and configured freshness updates. T08/T14 cover >=48x48 targets and 800x480 layout; T16 verifies actual HMI SIGINT/SIGTERM clean exit.
- Parent reported the final HMI auditor also passed actual backend/HMI integration across the 16-combination alarm matrix, persistence/settings, offline behavior, and shutdown. This is separately reported evidence, not an additional run by the completion editor.
- Current source/README preserve `main:app`, supported paths, SQLite history, `coolshift.sqlite3`, `COOLSHIFT_*`, service/log filenames, and acuPilot branding, and document wiring, defaults, migration, command-only limitations, OFF policy, and dummy loads. Parent separately reported successful systemd validation and `git diff --check`; these were not rerun by the completion editor.

## Physical Commissioning Gate

DEFERRED: actual installation hardware is unavailable in this workspace. Physical evidence is required before hardware deployment. These three checkpoints remain unchecked; automated simulation/fakes and real process signals cannot certify wiring, electrical fail-OFF, relay/ACU operation, or physical restart behavior.

- [ ] Confirm new BCM pin assignments, input pull modes, digital active levels, and every relay's active polarity against actual wiring.
- [ ] Verify each input/output and simultaneous alarm relays with dummy loads, including alarm operation in PAUSE.
- [ ] Confirm all-six-OFF behavior on real hardware for SIGINT/SIGTERM and injected fatal error, plus clean service restart.

## HMI Alignment Follow-Up (2026-10-10)

The previous final evidence remains a historical record. A new delegated source audit and offscreen run passed 20/20 and confirmed main backend-feature alignment, but found that overflow scrolling was not covered by the existing touch checks. Independent Task 13 verification now closes the following checks and the reopened software acceptance item above.

- [x] Overflowing active and recent alarm lists each have a rendered vertical scrollbar width and draggable-handle height of at least 48 pixels.
- [x] Touch-safe scrolling reaches the final active and recent row while descriptions, acknowledgement controls, and relay summaries remain readable within 800x480.
- [x] New regression checks and the complete HMI offscreen suite pass, with independently verified results recorded.
- [x] Command-only states, water/four alarm commands, freshness/offline behavior, and authoritative settings remain unchanged and pass regression checks.

### Independent Task 13 Evidence

- On 2026-10-10 the independent verifier read the approved spec/tasks/checklist and current alarm page/smoke source. `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke` exited 0: 21 passed, 0 failed, 21 total. T21 measured actual QStyle handles, not merely QSS or size hints: both 48x48 px; visible bars were 48x150 px active and 48x69 px recent, with 8 and 50 rows respectively. Viewports were 718x150 and 718x69 px. Both drags reached maximum scroll and fully exposed the last 60 px row.
- A separate in-memory Qt probe using the application theme independently passed bottom/top/bottom drags: active range 0..330 with final slider QRect(0,102,48,48) and final row QRect(0,90,718,60); recent range 0..2931 with final slider QRect(0,21,48,48) and final row QRect(0,9,718,60). Both final rows, descriptions, status labels and ACK controls were fully inside their viewports. Active description/status actual/required heights were 32/32 and 28/28 px; recent description was 16/16 px. Rendered ACK controls were 102x50 px with fitting text. Clicking the final active ACK emitted its key, acknowledged the row and preserved relay commands; recent ACK remained disabled.
- The same probe verified all four mixed ON/OFF relay commands and all four offline UNKNOWN (STALE) summaries at 776x14 px, required height 14, inside the 800x360 page of an unchanged 800x480 window. Offline active-count indication was STALE / OFFLINE. Cleared-row ordering is set-dependent, so each run checked its actual final item rather than a fixed key.
- T07/T08/T13/T14 passed page/dialog bounds and touch targets; T04/T14/T17 passed command-only states, water/four-output visibility, independent freshness, local ACK and offline truth; T18/T19 passed authoritative defaults/GET/PATCH, HIGH/LOW editing, rejection, pending-save snapshots and offline safeguards; T20 passed configured freshness, lower-settings touch access and Dashboard text heights (relay 54/54 px, alarm 19/19 px). Source inspection confirms local ACK has no backend mutation and no feature-contract change is required for list scrolling.
- This verification edited only acceptance records, not application code or tests. The two inspected files are untracked, so a tracked baseline diff is unavailable; direct current-source inspection and regression runs establish the affected behavior. Unaffected historical software evidence was trusted rather than rerun. Real touchscreen behavior and physical commissioning remain DEFERRED; all three physical gates above remain unchecked.
