# Tasks

- [x] Task 1: Track and harden independent systemd units.
  - Add `deploy/acupilot-backend.service` based on the installed system unit; retain identity, account, loopback binding, and single-worker entry point.
  - Update `deploy/coolshift-hmi.service` while preserving graphical user ownership, startup logging, launcher forwarding, and backend independence.
  - Define bounded shutdown/startup, backoff, and restart-rate limits; validate both unit definitions in their correct manager scope.
  - Do not install units or mutate live services without explicit administrator approval.
  - Evidence: delegated unit implementation passed `systemd-analyze --system --generators=no verify deploy/acupilot-backend.service` and `systemd-analyze --user --generators=no verify deploy/coolshift-hmi.service` (exit 0). Uvicorn CLI confirms worker/drain options. No live manager mutation.

- [ ] Task 2: Implement centralized service control and update wrappers.
  - Implement the command/component contract, read-only status, bounded mutation lock, preflight, correct system/user scopes, and noninteractive authorization errors.
  - Implement idempotent start, coordinated stop/restart ordering, bounded managed-backend readiness, activation checks, and actionable partial-failure diagnostics.
  - Replace wrapper process matching/detached spawning with controller delegation and reliable path/exit-code handling.
  - Test parsing, scope, ordering, denied authorization before mutation, locking, occupied ports, readiness/fatal-state failures, and wrapper behavior using isolated fakes.

- [ ] Task 3: Update deployment and migration guidance.
  - Document installation in system/user scopes, backend boot independence, graphical environment/session setup, and explicit privileged actions.
  - Explain changed wrapper defaults, component-only commands, unmanaged development flags, removal of competing launch owners, status/journal commands, and rate-limit/partial-failure recovery.
  - State that restart interrupts cooling/alarm availability and startup can energize outputs under the existing policy.

- [ ] Task 4: Independently verify software acceptance.
  - Read every software checkpoint in `checklist.md`; delegate verification and record commands/results next to passed items.
  - Run lifecycle/controller regressions, shell syntax checks, available shell linting, scoped systemd verification, `.venv/bin/python -B -m unittest discover -s backend/tests -v`, and `QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m hmi.tests.smoke`.
  - Verify signal/shutdown coverage preserves existing seven-output cleanup and HMI reconnect behavior without restarting live services.
  - Add explicit fix tasks for failed checkpoints and reverify after delegated implementation; distinguish pre-existing failures and unavailable tools.
  - Record on-device commissioning as deferred rather than claim physical success.

# Task Dependencies

- Tasks 1 and 2 can be implemented in parallel against the fixed unit names and interface in `spec.md`.
- Task 3 follows Tasks 1 and 2 so documented commands match implementation.
- Task 4 follows Tasks 1, 2, and 3 and must use independent verification.
- Live installation and physical commissioning are separate, explicitly authorized operational steps, not prerequisites for software-only delivery.
