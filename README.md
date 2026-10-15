# acuPilot — Raspberry Pi 4B Backend (Prototype v0.2.0)

A FastAPI-based prototype for two ACUs with six-hour rotation, overlap handover,
temperature boost, door/high-water/smoke monitoring, five independent alarm
relay commands, and SQLite event history. ACU status is command-only: there are
no physical-operation telemetry, equipment-failure detection, or physical-failure
failover. Commanded ON/OFF is not proof that equipment is running or stopped.
**Simulation mode is ON by default.** Not commissioned or certified for direct ACU power switching.

This guidance describes the approved GPIO backend overhaul. Backend/HMI contract
integration and Task 6 acceptance remain pending until the integrated tests are
verified; this document is not evidence of successful hardware commissioning.

The app is branded **acuPilot**. Existing `COOLSHIFT_*` environment variables,
`coolshift-hmi.service`, `coolshift.sqlite3`, and `coolshift_hmi.log` names are
retained for compatibility with installed systems and existing history.

## Install (Raspberry Pi OS, Python 3.11+)

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev libgpiod3 \
    build-essential swig liblgpio-dev
cd /home/rheg/App
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Visit http://127.0.0.1:8000/docs for interactive API documentation.

These package commands target Raspberry Pi OS / Debian Trixie. On Bookworm,
use `libgpiod2` instead of `libgpiod3` and `libqt6core6` instead of
`libqt6core6t64`. The libgpiod package name alone does not establish compatibility
with hardware drivers; verify DHT11/GPIO operation separately before commissioning.
On Python 3.13 ARM64, pip may build the `lgpio` dependency from source:
`swig` generates its Python wrapper and `liblgpio-dev` provides the linker library.

## Test (simulation mode)

```bash
curl http://127.0.0.1:8000/api/status
curl -X POST http://127.0.0.1:8000/api/simulation -H 'Content-Type: application/json' -d '{"temperature_c":29,"humidity_pct":55}'
curl -X POST http://127.0.0.1:8000/api/mode -H 'Content-Type: application/json' -d '{"mode":"pause"}'
curl http://127.0.0.1:8000/api/events
```

Runtime validation also applies in simulation: `rotation_seconds` must be at
least 1800 and `min_off_seconds` at least 180. Use an injected test clock in
automated backend tests rather than reducing production settings below these limits.

## Wiring and Commissioning

Use BCM numbering, not physical header numbers. The installed `config.json`
pin mapping matches `backend/config.py`:

| Channel | BCM pin | Installed active level |
| --- | --- | --- |
| DHT11 data | 4 | DHT11 data protocol |
| ACU1 relay command | 16, 11 | Fixed HIGH for ON, LOW for OFF |
| ACU2 relay command | 9, 10 | Fixed HIGH for ON, LOW for OFF |
| Door contact | 24 | LOW means door open; input pull-up |
| High-water input | 23 | LOW means high water; input pull-up |
| Smoke input | 25 | LOW means smoke asserted; input pull-up |
| Water alarm relay command | 26 | HIGH (configurable) |
| Smoke alarm relay command | 19 | HIGH (configurable) |
| Temperature alarm relay command | 13 | HIGH (configurable) |
| Humidity alarm relay command | 6 | HIGH (configurable) |
| Door alarm relay command | 0 | Fixed HIGH for ON, LOW for OFF |

There are seven logical relay outputs, with paired physical outputs for each ACU.
Keep every installed GPIO assignment synchronized with `backend/config.py`.
Door, water, and smoke use `input_pull: "up"`; DHT11 BCM4 is managed separately
by its sensor driver and is not a digital input channel. Input polarity remains
independently configurable; all three installed digital inputs are active-LOW.
The water and smoke fallback polarity defaults are active-HIGH.
An input pull-up biases an undriven pin HIGH; a connected sensor or short to GND
can still hold the pin LOW. A LOW voltage does not mean the pull-up is disabled.
Simulation needs neither assigned hardware pins nor GPIO dependencies.

Before enabling hardware mode in `config.json`, choose and validate supported,
distinct BCM pins across all thirteen physical channels. Missing, duplicate, or unsupported
assignments must reject hardware startup before normal relay activation. Confirm
each digital input's active HIGH/LOW level and explicit pull-up, pull-down, or
no-pull configuration against its electrical interface. ACU outputs require
`output_active_high.acu1`, `.acu2`, and `.door` to be exactly `true`: ON drives
electrical HIGH and OFF drives electrical LOW. Active-LOW configuration for these
outputs is rejected in both simulation and hardware mode. Other alarm output
polarities remain independently configurable; their logical OFF is not
necessarily electrical LOW.
Use a 3.3V-compatible DHT11 data interface and common GND where appropriate.

BCM GPIO0 is physical header pin 27, not BCM27. GPIO0 is commonly reserved for
HAT EEPROM identification: confirm no HAT, overlay, or other peripheral owns it
before connecting the door alarm driver. Application OFF cannot guarantee LOW
during boot, power loss, or electrical failure.

**IMPORTANT:** PC817 boards vary in active polarity, LED drive requirements,
isolation and output capabilities. Never connect GPIO directly to SSR-100 control
terminals without an engineered driver. Verify SSR model, ACU load, heat sinking,
protection, contactor/remote-control compatibility, and electrical code compliance.

Physical commissioning is **deferred, not passed** in this workspace. With ACUs
disconnected and suitable dummy loads, record the actual pin map, pulls, polarity,
high-water semantics, each of the seven output channels, and concurrent operation
of all five alarm relays in AUTO and PAUSE. For the door, verify LOW before
3 continuous seconds open, HIGH at the first eligible control tick, LOW on close,
and a fresh timer on reopening. Check independent alarm clearing,
SIGINT/SIGTERM all-seven-OFF behavior, and hardware fail-safe behavior on reboot or
power loss before connecting equipment. Automated fakes/simulation do not
establish electrical safety or physical relay/ACU operation.

### Manual Output Testing

**Direct pin test hazard:** actual relays are energized in hardware mode.
Test commands and snapshot restoration bypass ACU minimum restart delay.
Disconnect ACUs and use suitable dummy loads before testing; never use this
feature to cycle connected compressors. Simulation does not exercise hardware.

1. Open Settings and scroll below the existing settings to MANUAL OUTPUT TESTING.
   Viewing the section changes nothing. Select Start Test and confirm the warning.
2. Independently toggle ACU 1, ACU 2, Water Alarm, Smoke Alarm, Temperature Alarm,
   Humidity Alarm, and Door Alarm ON/OFF. Only these seven configured output pins are tested;
   input and DHT pins are never toggled. Automatic relay writes are temporarily
   overridden while sensor/alarm monitoring continues. Mode changes, ordinary
   ACU commands, and Settings Save are unavailable during testing.
3. Select End Test to stay in Settings, or navigate away. Navigation waits for
   restoration acknowledgement: a healthy backend restores all seven pre-test
   commands before releasing the override. The operating mode is preserved;
   subsequent normal control ticks may change outputs for current conditions.

The backend lease is 10 seconds, renewed by a 2-second HMI heartbeat only while
testing on Settings; valid test commands also renew it. End/departure/disconnect
stops heartbeats. After client crash or network loss, a healthy running backend
restores the snapshot on the next control tick after lease expiry. Graceful HMI
close/SIGINT/SIGTERM attempts bounded End Test before network teardown.
UNKNOWN/OFFLINE or Restoration unconfirmed is not a restoration acknowledgement.

All displayed states are commands only, not measured relay contacts or ACU
operation. Backend shutdown or fatal error cancels testing and independently
attempts all seven outputs OFF, never restoring pre-test ON states. Write/restore
failure enters fatal fail-OFF handling. Sessions/snapshots are runtime-only and
are not restored after backend restart. Power loss or electrical failure cannot
guarantee restoration or physical OFF; independent hardware fail-safe protection
and on-device dummy-load commissioning are required.

## Cooling, Alarms, and Fail-OFF

AUTO maintains a lead ACU, rotates it periodically, and commands both ACUs under
temperature boost hysteresis. Minimum OFF time applies to each ACU. If the incoming
unit is not yet eligible during rotation, the outgoing unit stays commanded ON;
handover overlap starts only after the incoming unit is successfully commanded ON.
Commands cannot confirm that an ACU actually runs or stops.

| Qualified alarm | Dedicated relay command |
| --- | --- |
| `WATER_LEVEL_ALARM` | `water` |
| `SMOKE_ALARM` | `smoke` |
| `HIGH_TEMPERATURE` | `temperature` |
| `HIGH_HUMIDITY` | `humidity` |
| `DOOR_OPEN` | `door` |

All five alarm relays can be commanded ON concurrently, including in PAUSE.
PAUSE commands only the ACUs OFF while acquisition and alarm evaluation continue.
MANUAL disables automatic rotation and temperature boost, retaining the current
ACU commands until changed individually with ON/OFF. Select MANUAL on the Control
page, then use each ACU's ON or OFF button. Minimum OFF time still applies:
an early ON request is rejected with the remaining delay and must be retried.
Alarm acquisition and all five alarm relay commands remain active in MANUAL.
Returning to AUTO resumes automatic cooling with a fresh rotation interval.
`POST /api/acu/{1|2}/command` accepts `{"action":"on"}` or `{"action":"off"}`
only in MANUAL; commands in AUTO/PAUSE or after controller shutdown are rejected.
An accepted command applies the requested GPIO level before returning, including
repeated ON/OFF requests; reissuing a command does not restart transition timers
or add transition history. Rejected mode/restart-delay requests do not write GPIO.
Simulation remains nonphysical.
Each alarm relay clears automatically when its own condition clears; there is no
latching or new alarm-driven ACU shutdown interlock. The door relay drives HIGH
after `door_alarm_seconds` (default and installed value: 3) of continuously open
door input, and LOW on close, resetting the timer. Alarm and relay qualification
use the same adjustable delay. With the default 1-second control tick, transitions
occur on the next eligible tick. Manual output testing temporarily overrides this
relay like the other outputs. Sensor-health alarms remain software-only.
HMI acknowledgement is local and never changes relay commands.

DHT reads are scheduled separately from control cycles. Hardware starts with
unknown temperature/humidity until a valid sample arrives. Failed samples and
digital-input changes do not refresh DHT age. Stale DHT data raises `SENSOR_STALE`,
disables boost and temperature/humidity alarm outputs, and retains single-unit
cooling in AUTO; digital monitoring remains active.

All seven relay commands initialize OFF. Normal shutdown, SIGINT/SIGTERM, or a fatal
control-loop error attempts OFF independently on every output even if another
write or logging fails. Fatal errors inhibit automatic reactivation until backend
restart. Shutdown stops/joins background work within a bounded interval and
releases GPIO/DHT resources. A failed write is not published as a successful
command; these OFF attempts are not proof of physical operation or a safety guarantee.

## Runtime Settings and Defaults

`GET /api/settings` distinguishes `effective` merged values, `defaults`, and
`restart_required` installation settings in a response object with those three
keys. `PATCH /api/settings` accepts a partial runtime-settings object and returns
authoritative merged settings after saving.
For example:

```bash
curl http://127.0.0.1:8000/api/settings
curl -X PATCH http://127.0.0.1:8000/api/settings \
    -H 'Content-Type: application/json' \
    -d '{"high_humidity_alarm_pct":70,"water_alarm_seconds":5}'
```

Validated changes persist atomically in the existing `config.json` and apply
under the engine lock on the next control cycle without restart. Missing settings
use defaults; invalid supplied values are rejected, not silently reset. Unknown
fields, invalid types/ranges, nonfinite numbers, or persistence failures reject
the whole update and leave effective configuration and the saved file unchanged.

GPIO assignments, simulation mode, output polarity, and input pull modes are
restart-required installation settings and are rejected by runtime PATCH. Digital
input active HIGH/LOW levels and continuous assertion delays are runtime triggers.
`effective.input_active_high` is a dictionary for `door`, `water`, and `smoke`;
`false` selects active LOW and `true` selects active HIGH. It is runtime-adjustable
through PATCH, unlike input pulls and output polarity. Its default is
`{"door":false,"water":true,"smoke":true}`.
Water and smoke are digital conditions, not numeric height/concentration readings;
any sensor-module comparator sensitivity is an external hardware adjustment.

| Runtime setting | Default |
| --- | --- |
| `rotation_seconds` | 21600 |
| `handover_overlap_seconds` | 15 |
| `min_off_seconds` | 300 |
| `boost_on_c` / `boost_off_c` | 27 / 25 |
| `high_temp_alarm_c` | 30 |
| `high_humidity_alarm_pct` | 65 |
| `door_alarm_seconds` | 3 |
| `water_alarm_seconds` | 0 |
| `smoke_alarm_seconds` | 0 |
| `temperature_alarm_seconds` | 0 |
| `humidity_alarm_seconds` | 0 |
| `sensor_stale_seconds` | 30 |
| `sensor_poll_seconds` | 3 |
| `control_tick_seconds` | 1 |
| Door / water / smoke active levels | LOW / HIGH / HIGH |

Temperature and humidity alarms qualify at or above their thresholds. Delays
measure continuous assertion and reset on clearing or changing that trigger's
setting. Temperature thresholds must be within 0-50 C, humidity within 0-100%,
and delays nonnegative. DHT polling must be at least 2 seconds; control and
staleness intervals must be positive, with staleness greater than polling.
Rotation must be at least 1800 seconds, restart delay at least 180 seconds, and
`boost_on_c > boost_off_c`. Alarm thresholds are independent of boost thresholds.

## API and Configuration Contract

Keep `main:app`, `/api/status`, `/api/events`, and `/api/mode` deployment
compatibility. Update backend and HMI together for these breaking changes:

- Status retains mode, lead, rotation countdown, pending handover, boost,
  `acu_outputs`, and string-list `alarms`. It adds `sensors.water_level_alarm`,
  named `alarm_outputs` (`water`, `smoke`, `temperature`, `humidity`, `door`),
  and top-level `sensor_age_s` with keys
  `temperature_c`, `humidity_pct`, `door_open`, `smoke_alarm`, and
  `water_level_alarm`. These per-sensor ages are in seconds and do not require
  comparing monotonic clocks across processes. `acu_outputs` records the last
  successfully applied relay command, not physical-operation telemetry.
- Simulation accepts digital/DHT inputs and explicit missing DHT values for fault
  tests; it rejects unknown fields and is unavailable in hardware mode.
- Legacy ACU sensor/confirmation configuration keys are rejected, not silently
  migrated or ignored. Unknown startup keys are also rejected. Update installation
  configuration explicitly and validate wiring before reusing any old pins.
  Existing SQLite history is retained; historical fault events are not current
  equipment faults. Generic command/write failures remain visible.
- The obsolete `POST /api/reset-faults` route is absent and returns normal HTTP
  **404 Not Found**.

## Limitations / next phase

- This is a prototype; do not deploy unattended until commissioning and fault injection tests.
- No physical relay or ACU telemetry is available; commanded ON/OFF is not proof of running/stopped.
- No remote authentication; bind API to localhost until auth and TLS are added.
- `pause` is a software command, not a safety-rated emergency stop.
- DHT11 accuracy/reliability is limited; add independent high-temp protection.
- This is not a certified fire-safety or compressor-protection system; independent protections must be code compliant.
- Alarm indication is unavailable when the backend is stopped, including shutdown/fatal fail-OFF.
- GPIO outputs may glitch on reboot; use hardware fail-safe output design.

## acuPilot HMI (PySide6 Frontend)

A full-screen industrial touchscreen HMI for the acuPilot backend, written in PySide6 Qt
Widgets and targeted at a Raspberry Pi 4B with a 5-inch 800×480 capacitive touchscreen.

### Pages
- **Dashboard** — Prominent °C / %RH readouts, ACU status cards, mode, rotation countdown,
  boost state, active alarm summary, backend connection status.
- **Control** — Mode selector (AUTO / MANUAL / PAUSE), independent ACU ON/OFF
  buttons enabled only in MANUAL, and command-only ACU status cards labelled
  Commanded ON/OFF or UNKNOWN/offline, not RUNNING or STARTING. Dashboard and
  Control cards say "Relay command only"; unavailable commands remain UNKNOWN/STALE.
- **Sensors** — DHT11 temperature & humidity with freshness, door contact,
  high-water input, smoke detector, and relevant alarm relay commands.
- **Alarms** — Active alarms first with local acknowledgement, including high water;
  four independent relay commands and recent cleared alarms.
- **Logs** — Paginated event history with filters (All, ACU, Alarm, System).
- **Settings** — Backend-loaded effective/default values, numeric thresholds/delays,
  digital HIGH/LOW controls, and Save/Revert with visible validation/save errors.
  Saves go only through the backend and are disabled offline; edits made while a
  save is pending remain unsaved rather than being overwritten by its response.
- **System** — Backend connectivity stats, software versions, diagnostic log viewer.

### Install

```bash
# 1. System packages on Raspberry Pi OS 64-bit Desktop (Trixie)
sudo apt update
sudo apt install -y python3-venv python3-dev libgpiod3 \
    build-essential swig liblgpio-dev \
    libqt6gui6 libqt6widgets6 libqt6core6t64 libqt6network6 \
    qt6-qpa-plugins libxcb-cursor0 xserver-xorg-input-libinput

# 2. Virtualenv with PySide6 and backend deps
cd /home/rheg/App
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Run — Desktop Development Mode (800×480 window)

```bash
cd /home/rheg/App
source .venv/bin/activate
python launch_hmi.py --dev
# or: COOLSHIFT_BACKEND_URL=http://127.0.0.1:8000 python hmi.py --dev
```

### Run — Backend + HMI together (simulation)

```bash
# Terminal A (backend)
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000

# Terminal B (HMI dev window)
source .venv/bin/activate
python launch_hmi.py --dev
```

### Run — Raspberry Pi Kiosk Fullscreen

Make sure the Raspberry Pi boots into a graphical desktop session with auto-login
enabled (use `raspi-config` → System → Boot / Auto login → Desktop Autologin).

**Option A — systemd user service (recommended for graphical session):**
```bash
mkdir -p ~/.config/systemd/user
cp deploy/coolshift-hmi.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user import-environment DISPLAY XAUTHORITY XDG_RUNTIME_DIR
systemctl --user enable coolshift-hmi.service
systemctl --user start  coolshift-hmi.service
# Logs:
journalctl --user -u coolshift-hmi.service -f
```

**Option B — XDG autostart:**
```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/coolshift-hmi.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=acuPilot HMI
Exec=/home/rheg/App/.venv/bin/python /home/rheg/App/launch_hmi.py
X-GNOME-Autostart-enabled=true
EOF
```

Fullscreen mode is frameless, always-on-top, and fills the native 800×480 display.
Press Alt+F4 to quit (or `systemctl --user stop coolshift-hmi.service` / SIGTERM).

This unit is an X11 **user** service, not a system service. Run the commands from
the logged-in graphical desktop. Start the backend separately; the HMI remains
usable offline and reconnects automatically. Change `/home/rheg/App` in the unit
if installed elsewhere. Do not enable user lingering to start the GUI before login.
Some desktops do not activate `graphical-session.target`; use Option B in that case.
On a Wayland desktop, use XWayland with `DISPLAY` available, or override
`QT_QPA_PLATFORM=wayland` and import `WAYLAND_DISPLAY` into the user manager.
Qt 6 enables high-DPI scaling by default; use the screen's native 800x480 mode and
100% desktop scaling for the intended logical touchscreen layout.

### Diagnostic Logs

Diagnostic files live in `Logs/` under the installation root, independent of the
launch working directory. acuPilot creates it using the launching user's permissions:

- `Logs/coolshift_hmi.log`: HMI application and backend-client diagnostics.
- `Logs/hmi_startup.log`: launcher-captured stdout/stderr, including native Qt errors.
- `Logs/coolshift_backend.log`: backend events, errors, and Uvicorn diagnostics.

Each active file rotates at 1,000,000 bytes with three backups (`.1` through `.3`).
Records from startup capture are chunked to bound very long native output.
Existing oversized startup history is preserved in `Logs/legacy/`; those archives
are not automatically deleted and should be reviewed periodically for disk usage.
If file setup or writing fails, acuPilot warns on stderr and keeps console output
available; it never creates fallback files outside `Logs`. Backend file writes use
a bounded asynchronous queue, dropping diagnostics rather than blocking control
when overloaded. SQLite event storage remains independent.

`coolshift.sqlite3` remains in the installation root and supplies the HMI Logs page.
The System page's diagnostic viewer remains an in-memory recent-message view.
Direct `python hmi.py` still writes HMI diagnostics, but use `launch_hmi.py` or
`start_hmi.sh` for full native/startup capture. Console/journal copies remain available.
Backend file logging begins when `main` is imported; earlier Uvicorn bootstrap
failures remain console/journal-only. Run one backend process, not multiple workers
sharing hardware or rotating log files. No backend service unit is supplied here.
Existing running backends activate new logging only at their next coordinated restart.

Before migrating legacy root logs, stop the HMI with its actual launch manager
(`systemctl --user stop coolshift-hmi.service` for a user service, or SIGTERM for a
confirmed manual HMI process). Leave backend control running, then run:

```bash
/home/rheg/App/.venv/bin/python /home/rheg/App/migrate_logs.py
```

The migration refuses active HMI/log writers, preserves history and collisions
without overwriting, and is safe to rerun. Relaunch via `start_hmi.sh`, or copy the
updated user service unit, reload the user manager, and start that service.
Do not use the manual restart script for a service-owned HMI.
The launcher forwards SIGINT/SIGTERM and waits up to eight seconds for shutdown;
systemd's ten-second stop budget provides final cgroup cleanup.
System page in the HMI also shows the last 100 diagnostic lines.

### Verify the HMI

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m hmi.tests.smoke
systemd-analyze --user verify deploy/coolshift-hmi.service
```

The smoke suite needs PySide6 installed, but no display, GPIO, backend process, or
internet connection. It prints per-page widget inventories and checks navigation,
rendered bounds, touch targets, state derivation, validation, dialogs, countdown,
asynchronous HTTP signals, timeout/recovery, and SIGINT/SIGTERM shutdown.
Physical touchscreen calibration and Raspberry Pi graphical autostart still need
an on-device check. `COOLSHIFT_DEV=1` is equivalent to `--dev`; `--backend-url`
overrides `COOLSHIFT_BACKEND_URL`.

### Integration Verification

Task 6 remains open until backend tests, the HMI offscreen suite, and integrated
simulation checks have recorded evidence for configuration/persistence, GPIO
fakes, freshness, timer boundaries, rotation/boost/PAUSE, all alarm combinations,
API rejection, failure isolation, and shutdown cleanup. Verify command-only HMI
labels, settings save/rejection/offline behavior, 800x480 layout, and at least
48x48 touch targets. No integrated test pass is claimed by this documentation edit.

The settings endpoints are part of this overhaul, not a future extension. Manual
per-ACU commands are now supported as described above. Server-side acknowledgement, richer alarm payloads,
additional event pagination/filter APIs, `/api/info`, and ACU runtime counters
remain outside its scope. Do not assume those endpoints exist or enable unsupported
controls. Alarm acknowledgement remains local to the HMI.

### Limitations / HMI Safety Contract

- The HMI never drives GPIO or implements automation: only the backend does.
- ACU and alarm labels show commands only; retained offline values are marked stale,
  not presented as current physical output states.
- No physical-operation verification or new alarm interlock is provided.
- Manual per-ACU control requires MANUAL mode and does not bypass restart delays.
- `PAUSE` mode is a software override — not a safety-rated emergency stop.
- Use independent fire safety and high-temperature protection systems per code.
