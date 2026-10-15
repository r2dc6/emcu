# Software Acceptance

- [x] Backend remains a boot-time system service; HMI remains a graphical user service; HMI exit/logout does not stop the backend.
  - Independent unit-definition evidence (2026-10-15): backend WantedBy=multi-user.target; HMI WantedBy/PartOf=graphical-session.target; no cross-manager/backend dependencies. Both scoped verify commands below exited 0. Actual boot/logout remains deferred.
- [x] Unit names, scopes, account, project paths, single-worker Uvicorn binding, legacy environment names, database/log files, and acuPilot branding are preserved.
  - Independent inspection: tracked backend matches installed /etc/systemd/system/acupilot-backend.service account rheg:rheg, /home/rheg/App, .venv, main:app, 127.0.0.1:8000 and journal sinks; explicitly --workers 1. HMI retains launch_hmi.py; main.py, hmi.py, hmi/constants.py and log_config.py retain coolshift.sqlite3, config.json, COOLSHIFT_BACKEND_URL/COOLSHIFT_DEV, existing log filenames and acuPilot branding.
- [x] Units define bounded SIGTERM shutdown, process-failure backoff, restart-rate limits, and suitable start/stop budgets.
  - Independent commands: `systemd-analyze --system --generators=no verify deploy/acupilot-backend.service` and `systemd-analyze --user --generators=no verify deploy/coolshift-hmi.service`, both exit 0. Both use SIGTERM, KillMode=mixed, Restart=on-failure, RestartSec=5, StartLimitIntervalSec=120/StartLimitBurst=5; start budgets 30s, backend stop 30s with Uvicorn drain 20s, HMI stop 10s. `.venv/bin/python -B -m uvicorn --help` confirms worker/drain options (exit 0).
- [x] HMI uses the existing launcher and log capture; its stop budget exceeds the launcher shutdown budget.
  - Independent source inspection: ExecStart uses .venv/bin/python launch_hmi.py; launch_hmi.run_child captures stdout/stderr through the existing rotating startup log, forwards SIGINT/SIGTERM to its child, and waits up to 8s; unit TimeoutStopSec=10 exceeds that budget. No live launch/stop performed.
- [ ] Shared controller accepts exactly the specified commands/components and rejects invalid input before mutation.
- [ ] Wrappers default to both components, forward component selection and exit codes, work outside the project directory, and explain unsupported CLI flags.
- [ ] Start is idempotent and performs backend readiness verification before HMI startup.
- [ ] Coordinated restart stops and confirms HMI, restarts and verifies backend, then starts HMI; stop confirms HMI shutdown before backend stop.
- [ ] Component-only HMI operations never mutate the backend; backend-only operations work without a desktop.
- [ ] Authorization and prerequisite failures are bounded and actionable; denied backend authorization precedes any coordinated stop.
- [ ] HMI operations use the intended user's manager and fail clearly on unavailable graphical environment or user manager.
- [ ] Mutating invocations use bounded installation-scoped locking; managed wrappers do not use process-pattern killing or detached manual spawning.
- [ ] Manual-owner/port conflicts are reported without killing unrelated processes or silently adopting an unmanaged backend.
- [ ] Backend readiness requires managed unit activation, valid status, and nonfatal controller state within the documented deadline.
- [ ] Backend readiness failure leaves coordinated HMI startup unperformed; HMI failure leaves a healthy backend running; partial state is reported.
- [ ] Read-only status reports manager scope, unit state/failure, and backend readiness accurately, with meaningful nonzero exit codes.
- [ ] Failure diagnostics include scoped journal commands; existing rolling application/startup logs remain intact.
- [ ] No implicit installation, sudoers change, lingering enablement, live service restart, or hardware configuration change occurs.
- [ ] Existing graceful backend cleanup attempts all seven configured outputs OFF; signal handling, door active-HIGH polarity, automation, and restart protection are unchanged.
- [ ] Deployment/migration guidance covers ownership conflicts, changed wrapper defaults, graphical-session setup, privilege requirements, cooling interruption, and recovery.
- [ ] Controller regressions and shell syntax checks pass; available linting and scoped systemd validation have recorded outcomes.
- [ ] Full backend and HMI offscreen regression outcomes are recorded; any pre-existing failures or unavailable tools are identified explicitly.

# Deferred On-Device Commissioning

These are not software acceptance passes. Leave them explicitly deferred until an operator authorizes installation and physical testing; automated completion does not certify them.

- Deferred: verify backend boot before login and HMI graphical-session autostart on the actual Raspberry Pi desktop.
- Deferred: verify HMI-only restart/logout preserves uninterrupted backend control and that crash recovery behaves correctly on the installed managers.
- Deferred: verify graceful coordinated stop/restart, physical seven-output OFF attempts, restart timing, and GPIO resource release with suitable commissioning loads.
- Deferred: confirm display permissions, touch operation, installed authorization, power-cycle behavior, and recovery from startup/rate-limit failures.
