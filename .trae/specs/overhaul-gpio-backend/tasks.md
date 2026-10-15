# Tasks

- [x] Task 1: Establish configuration and hardware contracts.
  - Introduce a small backend package with validated defaults and injectable I/O/clock dependencies; preserve `main:app`.
  - Migrate legacy feedback configuration without modifying unrelated settings; keep simulation default ON and require confirmed pins only for hardware mode.
  - Define actual inputs, six outputs, explicit polarity/pulls, runtime-editable settings, and restart-only wiring configuration.
  - Test omitted defaults, invalid types/ranges, pin conflicts, and legacy migration.
- [x] Task 2: Implement actual GPIO and simulated sensor/relay I/O.
  - Read door/water/smoke with correct active-state semantics; acquire DHT samples on their own schedule without blocking control.
  - Implement independent named relay writes with per-output polarity, state updates only after successful writes, and safe partial-initialization cleanup.
  - Track DHT freshness independently of digital inputs and support explicit missing/stale simulation data.
  - Test polarity, DHT failures, simultaneous relay commands, write errors, and resource cleanup using fake devices.
- [x] Task 3: Preserve cooling logic without feedback and add independent alarm outputs.
  - Retain AUTO/PAUSE, restart delay, lead rotation, boost hysteresis, and stale-DHT single-unit fallback.
  - Time overlap from the incoming ACU's successful ON command; remove feedback confirmation/failure/failover.
  - Add high-water detection, configurable trigger qualification, four alarm relay mappings, automatic independent clearing, and alarm transition logging.
  - Keep alarm evaluation active in PAUSE and attempt all-six-OFF independently on shutdown/fatal errors; prevent automatic fatal-error reactivation.
  - Test timer boundaries, delayed rotation, boost during handover, PAUSE, simultaneous alarms, setting-change timer reset, stale DHT, logging failures, and fatal/shutdown behavior.
- [x] Task 4: Expose revised API and persistent runtime settings.
  - Retain supported endpoint paths, event history, and deployment entry point; revise status and simulation contracts with command-only ACU semantics and sensor ages.
  - Add GET/PATCH settings with effective/default/restart-only metadata, atomic persistence, all-or-nothing validation/application, and explicit errors.
  - Return explanatory HTTP 410 for legacy fault reset; reject simulation mutations in hardware mode and unsupported fields.
  - Stop/join background work and release hardware on FastAPI shutdown.
  - Test API payloads, defaults, restart persistence, rejected writes, concurrent status/settings access, and lifecycle handling.
- [x] Task 5: Align the HMI with the real hardware and editable triggers.
  - Update SystemState, alarm definitions, Dashboard/Control/Sensors/Alarms to show command-only ACU states, high-water input, four alarm outputs, and per-sensor freshness.
  - Remove feedback/start-confirmation/fault-reset controls; retain unsupported manual command behavior.
  - Load authoritative backend settings and support numeric thresholds/delays plus digital HIGH/LOW editing, Save/Revert, visible errors, pending-save snapshots, and offline save disabling.
  - Update offscreen fixtures/tests for command-only states, unknown/stale sensors, concurrent alarms, settings responses, offline behavior, 800x480 layout, and touch targets.
- [x] Task 6: Validate the integrated overhaul and update deployment guidance.
  - Run backend tests and HMI smoke tests; exercise simulation across all input/output combinations and shutdown/error cases.
  - Update README wiring/configuration/API migration and commissioning instructions, preserving internal compatibility identifiers and acuPilot branding.
  - Verify every automated checklist item; record exact test evidence and explicitly defer physical commissioning where hardware is unavailable.
  - Final evidence (2026-10-10): after Task 10, backend full suites passed 47/47 twice in 8.670s and 7.477s; HMI offscreen passed 20/20, with relay/alarm geometry 54/54 and 19/19 px. All 23 software/documentation checkpoints are checked. Parent reported successful full backend/HMI integration, systemd validation, and diff checks. README prototype version matches API 0.2.0.
  - Physical limits: all three commissioning gates remain unchecked and explicitly deferred. Real subprocess SIGINT/SIGTERM tests verify software shutdown and simulated OFF commands, not electrical fail-OFF, physical relay/ACU operation, or installation restart behavior.

- [x] Task 7: Fix verification finding in DHT teardown.
  - Read tasks.md again and use the backend sub-agent to isolate process teardown errors from all-six-OFF and GPIO cleanup.
  - Cover process startup failure and join/teardown exceptions with regression tests; re-verify the lifecycle checkpoint after the fix.

- [x] Task 8: Fix HMI verification findings.
  - Read tasks.md again and use the HMI sub-agent to fix clipped dashboard alarm/relay text, touch-safe settings scrolling, backend-compatible numeric ranges, and configured freshness rendering.
  - Replace the obsolete backend-construction smoke assertion; add regression evidence and re-verify the affected checkpoints.
  - Evidence: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke` passed 20/20 on 2026-10-10. T20 verifies four relay lines actual/required height 54/54 px, alarm summary 19/19 px within Dashboard bounds, 48 px scrollbar and 80x48 Up/Down buttons reaching water and HIGH/LOW controls, backend-valid 200 h rotation / 120 min restart / 180 s overlap, and immediate configured freshness changes. T16 verifies extracted API branding plus real SIGINT/SIGTERM HMI shutdown; T18/T19 verify pending-save snapshots, offline disabling and authoritative GET/PATCH settings. Physical commissioning remains deferred.

- [x] Task 9: Fix engine worker startup cleanup.
  - Read tasks.md again and use the backend sub-agent to prevent joining unstarted threads and guarantee I/O cleanup when thread startup fails.
  - Add a thread-start failure regression and re-verify the lifecycle checkpoint.

- [x] Task 10: Remove the event-history test's newest-row race.
  - Check retained-row membership in event history rather than assuming the live worker cannot append newer output events; preserve response-schema and error assertions.
  - Make no application code changes; repeat the full backend suite twice and rerun the HMI offscreen suite before final acceptance.
  - Evidence (2026-10-10): two consecutive backend runs passed 47/47 (8.670s, 7.477s), and HMI offscreen passed 20/20. Only the history test assertion changed; no application defect was established.

# Task Dependencies
- Task 2 depends on Task 1.
- Task 3 depends on Tasks 1 and 2.
- Task 4 depends on Tasks 1 and 3.
- Task 5 depends on the API contract in Task 1; HMI work can run in parallel with Tasks 2-4 using contract fixtures, with integration validation after Task 4.
- Task 6 depends on Tasks 2-5.
- Implementation and verification SHALL be delegated to specialized sub-agents after specification approval.

## HMI Alignment Follow-Up (2026-10-10)

- [x] Task 11: Audit the current HMI against the backend overhaul's main requirements.
  - Delegated source verification confirmed command-only ACU states, water/four alarm outputs, freshness/offline behavior, backend-authoritative settings, pending-save edit preservation, and removal of obsolete feedback controls.
  - Current offscreen smoke suite passed 20/20. Overflowing active alarms exposed a 10-pixel-wide scrollbar not covered by button-only touch checks.
- [x] Task 12: Make both alarm lists touch-safe without changing backend behavior.
  - Provide vertical scrollbar width and draggable-handle height of at least 48 pixels for active and recent alarm lists.
  - Preserve readable alarm rows, acknowledgement targets, relay summaries, and 800x480 bounds.
  - Add offscreen regressions with overflowing active and recent alarm lists; verify reaching the last row and rendered scrollbar/handle dimensions.
  - Implementation evidence (2026-10-10): `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke` passed 21/21, zero failures. T21 overflows 8 active and 50 recent rows, measures actual QStyle slider rectangles (both 48x48 px) and visible scrollbar widths (both 48 px), and uses mouse drags to reach each final row at maximum scroll. Active/recent viewports are 718x150 and 718x69 px; a 10 px active-height reduction leaves a full 60 px recent row and slider travel. Assertions preserve readable descriptions, >=48x48 ACK controls, final active-row acknowledgement, all four relay summaries and 800x480 bounds. Changes are limited to `hmi/pages/alarms.py`, `hmi/tests/smoke.py`, and this task record; no backend behavior changes. Task 13 and checklist remain pending independent verification.
- [x] Task 13: Independently verify the HMI follow-up.
  - Run the complete offscreen HMI suite and re-check affected checklist items using delegated verification.
  - Record current results separately from previous completion evidence; leave physical commissioning deferred.
  - Independent verification (2026-10-10): read the approved spec/tasks/checklist and current `hmi/pages/alarms.py` / `hmi/tests/smoke.py`, then ran `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke`: exit 0, 21/21 passed, zero failures. T21 independently reproduced 8 active / 50 recent overflowing rows, 48 px visible bars and actual 48x48 px QStyle handles, maximum-scroll final-row access, readable descriptions/ACK controls, and four relay summaries at 800x480. T04/T14/T17-T20 passed the unchanged command-only, water/four-output, freshness/offline, authoritative GET/PATCH settings, pending-save and offline-save contracts.
  - Additional independent in-memory Qt probe (same offscreen interpreter, application theme, no saved script or code edits): bottom/top/bottom mouse drags reached both extrema; active range 0..330, bar 48x150, final slider QRect(0,102,48,48), viewport 718x150, final row QRect(0,90,718,60); recent range 0..2931, bar 48x69, final slider QRect(0,21,48,48), viewport 718x69, final row QRect(0,9,718,60). Final active description/status heights were 32/32 and 28/28 px actual/required; recent description was 16/16 px. Rendered ACK controls were 102x50 px, their text fit, the final active ACK emitted its key and left relay commands unchanged, and recent ACK stayed disabled. Mixed ON/OFF and four UNKNOWN (STALE) relay summaries each fit at 776x14 px (required height 14); window/page were 800x480 / 800x360. Cleared-row keys vary because history insertion iterates a set; final-row identity was determined from each list, not assumed.
  - Acceptance: all four follow-up checks and the reopened general HMI software target checkpoint pass. Historical unaffected software evidence is retained, not claimed as rerun. Both inspected files are untracked, so no tracked baseline diff is available; current source and regressions were inspected directly. Application/test files were not edited. Physical commissioning and real touchscreen/electrical validation remain DEFERRED; all three physical gates stay unchecked.

### Follow-Up Dependencies
- Task 12 depends on Task 11 and approval of this follow-up specification.
- Task 13 depends on Task 12.
