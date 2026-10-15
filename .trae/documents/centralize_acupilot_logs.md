# Centralize acuPilot Diagnostic Logs

## Summary

Create `Logs/` under the installation root (`/home/rheg/App/Logs` here) and route HMI diagnostics, captured HMI startup/native output, and backend application/Uvicorn diagnostics there. Preserve existing file history during migration. Apply a 1,000,000-byte rotation threshold and three backups to each active diagnostic file.

This is a plan only. Implementation requires approval.

## Current State Analysis

- `hmi/constants.py` resolves the installation root through `APP_BASE`, but `LOG_FILE` currently points directly to `coolshift_hmi.log` in that root.
- `hmi.py:setup_logging` installs a rotating HMI handler and a stderr handler. It does not create the destination directory and clears old handlers without closing them. Logging initializes after Qt construction and imports, so early failures require external capture.
- `start_hmi.sh` redirects all output to an unbounded `/home/rheg/App/hmi_startup.log`. `restart_hmi.sh` stops HMI processes by their command line and relaunches this script.
- `deploy/coolshift-hmi.service` invokes `hmi.py` directly. README XDG autostart instructions do likewise, bypassing script-based startup capture.
- `main.py` creates configuration, SQLite event storage, engine, and API for `uvicorn main:app`. It has no diagnostic-file logging setup.
- `backend/engine.py:Engine.log` stores events in SQLite and suppresses history failures so they cannot disrupt control or safety operations.
- `hmi/main_window.py` already sends backend-client diagnostic messages to the HMI logger. The System page retains a small in-memory diagnostic view.
- `coolshift.sqlite3` feeds `/api/events` and the HMI Logs page. It is application data, not a diagnostic text log.
- Existing HMI logs, rotated backups, and startup log are tracked and actively changing. The startup log is already larger than the proposed active-file limit. The repository contains no backend service unit.

## Assumptions & Decisions

- Destination is installation-root `Logs`, not filesystem-root `/Logs`. Paths must not depend on the caller's working directory.
- Preserve existing filenames (`coolshift_hmi.log`, `hmi_startup.log`) for compatibility. Use `coolshift_backend.log` for backend diagnostics. Messages and launch documentation use acuPilot branding.
- Keep `coolshift.sqlite3`, configuration paths, event APIs, HMI Logs filtering, GPIO behavior, and alarm timing unchanged.
- Preserve migrated history, but ordinary active-file rotation may subsequently expire old backups as before. Oversized startup history is retained separately under `Logs/legacy/` and is not an active log.
- Use a standard-library Python subprocess launcher for rotating startup capture, including native stdout/stderr. No new runtime dependency or logrotate installation.
- System journal copies may remain as supplemental diagnostics; do not relocate or erase OS-managed journals.
- The user authorizes a brief HMI restart during implementation for migration. Backend cooling/control remains running. Identify the actual HMI owner before stopping it: use the service manager for a service-owned process, or target only the confirmed manual-launch processes.
- Do not modify or commit live log contents or the database as source changes. No Git commit is requested.

## Proposed Changes

### 1. Shared Logging Utilities

Add `log_config.py` at the explored project root, alongside `main.py` and `hmi.py`.

- Define `APP_BASE`, `LOG_DIR`, the three diagnostic filenames, rotation constants, and UTF-8 timestamp/level/logger formatting.
- Create `Logs` on first logging initialization using the current user's permissions; do not require root or chmod the installation.
- Provide reusable rotating-handler setup that closes only previously owned handlers and avoids duplicate messages on repeated initialization.
- Handle directory/file setup failures with a clear stderr warning and console-only fallback. Never fall back to a new log file outside `Logs`.
- Use a bounded queue and `QueueListener` for backend file writes so disk I/O does not run under engine locks or delay control work. Queue overflow drops diagnostic messages without blocking; event storage remains independent. Handler write/rotation failures must not escape into control code.
- Provide explicit drain/close cleanup. Shut backend listeners down at interpreter exit, outside signal handlers and engine locks.

### 2. HMI File Logging

Update `hmi/constants.py` to obtain `LOG_FILE`, `LOG_MAX_BYTES`, and `LOG_BACKUPS` from the shared module while preserving their exported names.

Update `hmi.py:setup_logging` to use the shared handler setup while retaining its current function signature for compatibility.

- Initialize logging before Qt construction and major GUI imports so Python startup errors can be recorded.
- Record uncaught startup failures with traceback and re-raise; preserve normal exit status.
- Preserve stderr output, existing client diagnostics, and SIGINT/SIGTERM clean shutdown.
- Close/drain owned logging handlers after shutdown messages.

### 3. Rotating Startup Capture

Add `launch_hmi.py` next to `hmi.py`.

- Launch `[sys.executable, absolute_hmi_path, *forwarded_args]` with inherited environment, stdin, and installation-root working directory.
- Combine child stdout/stderr into one pipe and continuously capture output into `Logs/hmi_startup.log` with rotation. Preserve console visibility for manual launches and systemd journals.
- Consume output in bounded chunks rather than accumulating an arbitrarily long unterminated line. Continue draining the child pipe if logging fails.
- Forward SIGINT and SIGTERM to the child, wait for its clean shutdown, and return a nonzero status for failures. Do not restart the child internally; systemd or the existing restart script remains responsible for that.
- If the child does not terminate within the existing ten-second service stop budget, terminate it with a bounded cleanup path and report failure.
- Ensure pipe/handler closure and no orphan child after interruption. Do not put the launcher and child in a relationship that allows an unrelated process to be signaled.

Update `start_hmi.sh` to exec the launcher instead of using append redirection.

Update `restart_hmi.sh` to recognize both the launcher and legacy direct-HMI invocation, stop the confirmed HMI processes gracefully, wait with a bounded timeout, and launch one replacement only. Preserve detached startup semantics and leave backend processes untouched.

Update `deploy/coolshift-hmi.service` to launch `launch_hmi.py`. Keep graphical-session dependencies and `KillSignal=SIGTERM`; explicitly document launcher/child shutdown behavior under the existing service timeout.

### 4. Backend Diagnostics

Update `main.py` to initialize backend logging before configuration/engine initialization, retaining `app` and all existing configuration/database exports.

- Add an asynchronous rotating-file destination to root/application logging and `uvicorn.error` / `uvicorn.access`. Keep existing console handlers and prevent duplicate file records caused by propagation.
- Support the documented single-process `uvicorn main:app` launch. Document that shared-file multiprocess workers are unsupported for this hardware controller.
- Capture application import/initialization failures. Explain that Uvicorn failures occurring before importing `main` remain console/journal-only.

Update `backend/engine.py:Engine.log` to emit the event kind/detail to the backend diagnostic logger independently of SQLite success. Use ERROR for `engine_error` and `output_error`, WARNING for `sensor_error`, INFO otherwise.

- Retain SQLite inserts and their failure isolation.
- Emit a bounded/rate-limited diagnostic warning for event-store failures without recursion, and ensure any logging failure remains isolated from relay commands.
- Do not change control decisions, output ordering, event schemas, or `/api/events`.

### 5. Safe History Migration

Add `migrate_logs.py` as an explicit, idempotent offline migration utility; do not auto-move actively written logs during application startup.

- Inventory only known legacy HMI/startup diagnostic filenames and their numeric rotated backups; never use a broad move of root files.
- Require confirmed stopped HMI writers; abort if matching HMI writers remain. The rollout also verifies handles before moving.
- Move existing HMI active/backup files into `Logs` without overwriting a destination. If a destination already exists, preserve the source in a uniquely named `Logs/legacy` archive.
- Move the oversized historical startup log into `Logs/legacy/hmi_startup.<unique-id>.log`, keeping its bytes intact, and start a fresh bounded active startup log.
- Validate source/destination sizes and retain data on failure. Re-running after a successful migration must do nothing.
- Print an explicit migration report; never delete the database, unrelated files, or historical archives.

### 6. Documentation and Tests

Update `README.md` deployment/autostart examples to use the launcher and document:

- Exact log destinations, rotation limits, historical archive handling, console fallback, and ownership expectations.
- The distinction between text diagnostics and SQLite-backed event history.
- Direct `python hmi.py` writes the HMI diagnostic file but full native startup capture requires the launcher.
- Backend diagnostic coverage begins at application import; earlier server/bootstrap failures remain in console/journal output.
- Safe migration/restart procedure and the absence of a supplied backend service unit.

Add isolated standard-library tests in a new `tests/` directory for shared logging, launcher, and migration utilities. Update `hmi/tests/smoke.py` branding/path checks without changing the established log basename. Extend `backend/tests/test_engine.py` for diagnostic emission and failure isolation.

## Verification Steps

1. Use temporary directories for all test logs and synthetic migration histories. Never write tests to the live `Logs` directory or instantiate production GPIO.
2. Verify installation-root path resolution from another working directory, automatic directory creation, UTF-8 output, repeated initialization without duplicate handlers, and correct handler closure.
3. Force rotation with a small test threshold: verify the active file plus exactly three backups, bounded records, and no logs outside the selected directory.
4. Inject permission errors, rotation failures, queue overflow, and event-store failures. Verify console fallback, no control exception, and successful existing fail-OFF/safety tests.
5. Use a fake launcher child that emits stdout, stderr, native file-descriptor output, a long unterminated record, and a nonzero exit. Verify capture, argument/environment forwarding, exit status, SIGINT/SIGTERM forwarding, and no orphan processes.
6. Verify migration byte preservation, archive collision handling, idempotence, refusal with active writers, and no movement of SQLite/configuration.
7. Run `.venv/bin/python -m unittest discover -s tests` and `.venv/bin/python -m unittest discover -s backend/tests`.
8. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke` and `QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.output_testing`.
9. Run `bash -n start_hmi.sh restart_hmi.sh` and `systemd-analyze --user verify deploy/coolshift-hmi.service` where supported.

## Rollout

1. Implement and run isolated tests before touching live HMI writers. Record the current HMI launch owner/command/environment and backend PID so the replacement uses the same mode and backend URL.
2. Stop only the HMI using its actual launch manager. Confirm its writers have exited, then run the migration utility.
3. For a service-managed HMI, update its installed unit and reload only that user's manager; for manual startup, use the updated script. Relaunch exactly one HMI with the prior settings.
4. Confirm HMI visibility/connectivity, unchanged backend PID/control operation, migrated history, and new HMI/startup files under `Logs`. Observe that old root diagnostic files no longer grow.
5. Do not restart the backend during this HMI migration. Its new diagnostic configuration takes effect at the next separately coordinated backend restart. Verify backend logging in an isolated simulation process, and state this activation limitation in the completion report.
6. If relaunch fails, preserve all migrated files, use captured startup diagnostics to restore the prior HMI launch behavior, and leave backend control running. Do not revert unrelated user changes.
