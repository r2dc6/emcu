# Centralized acuPilot Service Control Spec

## Why
Backend and HMI lifecycle control is currently split between an installed system service, an HMI user-service template, and manual process scripts. Provide one predictable operational interface without tying cooling availability to the graphical desktop.

## What Changes
- Add a shared `service_control.sh` entry point for `start`, `stop`, `restart`, and `status`, selecting `both` (default), `backend`, or `hmi`.
- Track the existing `acupilot-backend.service` system unit in `deploy/` and update the existing `coolshift-hmi.service` user unit.
- Replace manual process discovery, termination, and detached spawning in the start/restart wrappers with shared service control.
- Add bounded startup verification, coordinated restart ordering, explicit authorization handling, and lifecycle regression tests.
- Update deployment, migration, recovery, and diagnostic instructions in `README.md` during implementation.
- **BREAKING**: With no arguments, `start_hmi.sh` and `restart_hmi.sh` will operate on both components. A component argument allows HMI-only operation. HMI CLI flags are not silently accepted by managed wrappers; manual development remains available through `python launch_hmi.py --dev` and its existing options.

## Impact
- Affected specs: deployment, process lifecycle, diagnostic logging, backend availability, HMI reconnect behavior.
- Affected code: `service_control.sh` (new), `start_hmi.sh`, `restart_hmi.sh`, `deploy/acupilot-backend.service` (new), `deploy/coolshift-hmi.service`, lifecycle tests, and `README.md`.
- Existing installed backend: `/etc/systemd/system/acupilot-backend.service`, running as `rheg`, with project working directory and loopback port 8000.
- No installed `coolshift-hmi.service` was found in the current user manager during proposal inspection.
- Preserve `main:app`, `launch_hmi.py`, installation root `/home/rheg/App`, `.venv`, `COOLSHIFT_*`, database/log paths, acuPilot branding, configuration, GPIO polarity, and current control behavior.
- The workspace currently has a corrupt Git HEAD object. Repository repair is outside this change; validation must not rely solely on Git commands.

## ADDED Requirements

### Requirement: Shared Control With Independent Ownership
The system SHALL retain the backend under the system manager and HMI under the graphical user's manager. The controller SHALL address exactly the existing unit names using their correct manager scopes. It SHALL NOT create a combined process supervisor or cross-manager systemd target.

#### Scenario: Desktop or HMI exits
- **WHEN** the HMI crashes, is stopped independently, or the graphical session ends
- **THEN** the backend remains running and continues its existing control policy.

### Requirement: Explicit Operational Interface
The controller SHALL accept `service_control.sh <start|stop|restart|status> [both|backend|hmi]`. Missing component SHALL mean `both`; invalid commands, components, or extra arguments SHALL fail before mutation and print usage. All control paths SHALL use the same unit identities and lifecycle implementation.

#### Scenario: Component-only operation
- **WHEN** `service_control.sh restart hmi` is requested
- **THEN** only the HMI is restarted, with no backend stop, restart, or equipment command.

### Requirement: Preflight and Authorization
Before a mutating operation, the controller SHALL validate relevant units, systemd connectivity, required tools, and component-specific prerequisites. HMI operations SHALL target the desktop user's manager, never root's user manager. Backend mutations SHALL use existing systemd authorization or narrowly scoped noninteractive sudo; unavailable authorization SHALL produce actionable instructions and a nonzero exit rather than hang. Both-component operations SHALL establish needed backend authorization before stopping either component.

The controller SHALL NOT install privileges, change sudoers, enable lingering, modify live units, or enable services implicitly. No user manager or absent display environment SHALL cause a clear HMI error without unnecessary backend disruption. Backend-only operations SHALL work without a graphical session.

#### Scenario: Authorization denied
- **WHEN** a coordinated restart lacks backend mutation permission
- **THEN** the operation fails before stopping the HMI or backend, identifies the required privileged action, and does not claim success.

### Requirement: Ordered and Bounded Operations
`start both` SHALL start or retain the backend, verify readiness, and then start or retain the HMI. `restart both` SHALL stop the HMI and wait for its unit to stop, restart the backend and verify readiness, then start the HMI. `stop both` SHALL stop and confirm the HMI before stopping the backend. Operations SHALL have finite deadlines and propagate errors.

Readiness SHALL require an active managed backend unit and a successful, valid `/api/status` response from the configured local backend within a documented default 30-second deadline. A fatal controller state SHALL not qualify as ready. HMI startup SHALL verify unit activation and check for immediate failure; this does not certify a visible window or physical display.

#### Scenario: Backend cannot become ready
- **WHEN** the backend fails startup, returns fatal state, or exceeds the readiness deadline during coordinated restart
- **THEN** the controller returns failure with backend diagnostics, leaves the HMI stopped, and reports the resulting partial state.

#### Scenario: HMI startup fails
- **WHEN** the backend is ready but the HMI cannot start
- **THEN** the operation reports HMI failure without stopping the healthy backend.

### Requirement: No Duplicate Ownership and Concurrent Operation Protection
Managed operations SHALL use systemd ownership, not `pgrep` or `nohup`, to start and stop services. Concurrent mutating controller invocations SHALL serialize through an installation-scoped lock with bounded acquisition. Unexpected manual processes or occupied backend ports SHALL not be killed or adopted automatically; failures SHALL identify the conflict and recovery procedure. Repeated start SHALL not restart already-running services.

#### Scenario: Repeated or concurrent start
- **WHEN** operators invoke start repeatedly or concurrently
- **THEN** at most one managed backend and one managed HMI instance exist, and timeout/conflict outcomes are explicit.

### Requirement: Status and Diagnostics
`status` SHALL be read-only and report each selected unit's scope, active/substate, failure information, and backend readiness separately. It SHALL return nonzero when a selected component is unavailable, failed, or not ready. Messages SHALL use acuPilot branding and include appropriate `journalctl` commands on failure. HTTP responsiveness alone SHALL not be treated as proof that a stopped backend unit owns an unrelated listener.

### Requirement: Safe Deployment and Recovery
The tracked backend unit SHALL preserve the installed account, working directory, Python interpreter, single Uvicorn worker, loopback binding, and journal output. Both units SHALL have explicit graceful SIGTERM shutdown, bounded stop/start behavior, restart backoff, and restart-rate limits. Preserve HMI launcher capture and its existing bounded child shutdown; keep the HMI stop budget longer than the launcher budget. Backend stop SHALL allow existing lifespan GPIO cleanup before final cgroup termination.

Backend startup SHALL remain boot-time via `multi-user.target`. HMI startup SHALL remain graphical-session dependent with documented environment import, X11/XWayland/Wayland handling, and desktop compatibility. HMI dependencies SHALL NOT stop the backend. Automatic process-failure recovery SHALL not add a health watchdog or automatically clear a latched controller fatal state.

Installation instructions SHALL distinguish system and user scopes, remove or disable competing manual/XDG autostart paths with operator confirmation, explain graphical-session activation, and require explicit administrator approval for live unit installation/reload/restart. Provide recovery instructions for rate-limited units and partial startup failures.

#### Scenario: Backend process crashes
- **WHEN** the managed backend exits unexpectedly
- **THEN** systemd attempts recovery with backoff and rate limiting; the HMI shows its existing offline state and reconnects without issuing replayed equipment commands.

## MODIFIED Requirements

### Requirement: Existing Start and Restart Scripts
`start_hmi.sh [both|backend|hmi]` SHALL delegate to shared `start` control; `restart_hmi.sh [both|backend|hmi]` SHALL delegate to shared `restart` control. Wrappers SHALL preserve the controller's exit code, resolve their installation path reliably, and work outside the project working directory. Unsupported legacy flags SHALL explain the manual-development alternative rather than be ignored.

### Requirement: Shutdown Safety and Availability
Coordinated backend stop/restart SHALL retain the existing attempt to command all seven configured outputs OFF and release hardware on graceful shutdown. Startup SHALL retain the existing control policy, including possible automatic relay activation. HMI-only restart SHALL not interrupt backend control. No new GPIO, compressor-protection, alarm, or mode-persistence behavior SHALL be introduced.

## REMOVED Requirements

### Requirement: Manual Process Management in Operational Wrappers
**Reason**: Pattern-based termination and detached spawning compete with systemd ownership and can falsely report successful startup.
**Migration**: Stop legacy manual instances through their actual owner before enabling managed operation. Retain direct `launch_hmi.py` and Uvicorn commands only for explicitly unmanaged development, never alongside the corresponding managed service.

## Validation and Boundaries
- Test command parsing, wrapper forwarding, manager scope, authorization rejection, locking, idempotence, lifecycle ordering, readiness deadlines, partial failures, and exit codes using isolated fake service managers and controlled HTTP responses.
- Run shell syntax checks, applicable shell linting when available, systemd unit validation in each correct scope, full backend tests, and HMI offscreen tests.
- Do not stop/restart live hardware services merely to validate this change. Record real graphical-session boot, hardware shutdown, and electrical recovery checks as deferred until explicitly authorized on the installation.
- SIGKILL, power loss, or electrical failure cannot guarantee software GPIO cleanup. Service status and simulation tests do not certify physical relay states.
