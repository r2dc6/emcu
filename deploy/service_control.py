"""acuPilot managed lifecycle control. No service installation or process killing.

Defaults: lock 10s, command/preflight 5s, job 75s (restart includes stop
and start), backend readiness 30s, HMI observation 2s. ACUPILOT_CONTROL_
{LOCK,COMMAND,JOB,READY,HMI}_TIMEOUT may tune these finite budgets.
COOLSHIFT_BACKEND_URL selects a local HTTP backend (default loopback:8000).
"""
import contextlib
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
UNITS = {"backend": "acupilot-backend.service", "hmi": "coolshift-hmi.service"}
PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus",
              "Job", "Environment", "MainPID", "ControlGroup")
USAGE = ("Usage: service_control.sh <start|stop|restart|status> [both|backend|hmi]\n"
         "Managed wrappers do not accept HMI flags. For unmanaged development only:\n"
         "  python launch_hmi.py --dev [HMI options] (never alongside the HMI unit)")


class ControlError(Exception):
    pass


def budget(name, default):
    try:
        value = float(os.environ.get(f"ACUPILOT_CONTROL_{name}_TIMEOUT", default))
        if not math.isfinite(value) or not 0 < value <= 300:
            raise ValueError()
        return value
    except ValueError:
        raise ControlError(f"{name} timeout must be finite, greater than 0 and at most 300s")


def pending(state):
    return state.get("Job", "").split(" ", 1)[0] not in ("", "0")


def fetch_status(url):
    # Called in a disposable subprocess: its parent enforces a wall-clock bound,
    # including DNS, redirects, headers and a server that trickles response bytes.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("API requires HTTP 200 without redirection")
        data = response.read(262145)
        if len(data) > 262144:
            raise ValueError("API status exceeds size limit")
    sys.stdout.buffer.write(data)


def passwordless_listing(text, command):
    # Accept explicit narrow entries only; do not implement sudoers wildcard,
    # alias, negation or tag-precedence semantics in the controller.
    for entry in text.split("Sudoers entry:")[1:]:
        metadata, separator, commands = entry.partition("Commands:")
        fields = dict(line.strip().split(":", 1) for line in metadata.splitlines()
                      if ":" in line)
        users = fields.get("RunAsUsers", "").strip().split(", ")
        options = fields.get("Options", "").replace(" ", "").split(",")
        if separator and ("root" in users or "ALL" in users) and "!authenticate" in options:
            for line in commands.splitlines():
                if shlex.split(line.strip()) == command:
                    return True
    return False


class Controller:
    def __init__(self, action, component):
        self.action = action
        self.selected = ["backend", "hmi"] if component == "both" else [component]
        self.timeouts = {key: budget(key, default) for key, default in
                         (("LOCK", 10), ("COMMAND", 5), ("JOB", 75),
                          ("READY", 30), ("HMI", 2))}
        self.systemctl = shutil.which("systemctl")
        if not self.systemctl:
            raise ControlError("systemctl is required")
        self.systemctl = str(Path(self.systemctl).resolve())
        self.backend_prefix = []
        self.url = (os.environ.get("COOLSHIFT_BACKEND_URL", "http://127.0.0.1:8000")
                    if "backend" in self.selected and action != "stop" else "http://127.0.0.1:8000")
        try:
            parsed = urllib.parse.urlsplit(self.url)
            host = parsed.hostname
            if (parsed.scheme != "http" or not host or parsed.username or
                    parsed.password or parsed.query or parsed.fragment or
                    parsed.path not in ("", "/")):
                raise ValueError()
            address = "127.0.0.1" if host == "localhost" else host
            if not ipaddress.ip_address(address).is_loopback:
                raise ValueError()
            self.address, self.port = address, parsed.port or 80
            netloc = f"[{address}]" if ":" in address else address
            self.status_url = f"http://{netloc}:{self.port}/api/status"
        except ValueError:
            raise ControlError("COOLSHIFT_BACKEND_URL must be a local loopback HTTP origin")

    def run(self, args, timeout=None, check=True):
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=timeout or self.timeouts["COMMAND"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ControlError(f"bounded command failed: {shlex.join(args)}: {exc}")
        if check and result.returncode:
            raise ControlError(f"{shlex.join(args)}: {result.stderr.strip() or result.stdout.strip() or 'failed'}")
        return result

    def command(self, component, *args):
        return [self.systemctl, "--system" if component == "backend" else "--user",
                "--no-ask-password", *args]

    def state(self, component, timeout=None):
        result = self.run(self.command(component, "show", UNITS[component],
                                       "--property=" + ",".join(PROPERTIES)), timeout)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if any(not values.get(key) for key in ("LoadState", "ActiveState", "SubState")):
            raise ControlError(f"{component} manager returned incomplete unit state")
        return values

    def preflight(self):
        for component in self.selected:
            if component == "hmi" and os.geteuid() == 0:
                raise ControlError("HMI requires the desktop user's shell, never root's user manager")
            state = self.state(component)
            if state["LoadState"] != "loaded":
                raise ControlError(f"{UNITS[component]} is {state['LoadState']}; ask an administrator to install/unmask the unit")
            if pending(state):
                raise ControlError(f"{component} has a pending external systemd job; wait and retry")
            if self.action in ("start", "restart"):
                required = [ROOT / ".venv/bin/python", ROOT / ("main.py" if component == "backend" else "launch_hmi.py")]
                if any(not path.is_file() for path in required) or not os.access(required[0], os.X_OK):
                    raise ControlError(f"{component} requires the installation's executable .venv/bin/python and entry point")
                if component == "hmi":
                    session = self.run(self.command("hmi", "is-active", "graphical-session.target"), check=False)
                    manager = self.run(self.command("hmi", "show-environment")).stdout
                    environment = dict(line.split("=", 1) for line in manager.splitlines() if "=" in line)
                    environment.update(dict(item.split("=", 1) for item in
                                            shlex.split(state.get("Environment", "")) if "=" in item))
                    if session.stdout.strip() != "active" or not (
                            environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")):
                        raise ControlError("HMI requires an active graphical session and DISPLAY or WAYLAND_DISPLAY; import the desktop environment into systemctl --user")
        self.conflicts()
        if "backend" in self.selected:
            self.authorize()

    def authorize(self):
        if os.geteuid() == 0:
            return
        verbs = [self.action]
        systemctl_commands = [self.command("backend", "--no-block", verb, UNITS["backend"])
                              for verb in verbs]
        pkcheck = shutil.which("pkcheck")
        if pkcheck:
            allowed = all(self.run([pkcheck, "--action-id", "org.freedesktop.systemd1.manage-units",
                                   "--process", str(os.getpid()), "--detail", "unit", UNITS["backend"],
                                   "--detail", "verb", verb], check=False).returncode == 0
                          for verb in verbs)
            if allowed:
                return
        sudo = shutil.which("sudo")
        # Listing permission does not execute a job. Probe the EXACT later argv,
        # before either manager is mutated; never probe with sudo true.
        if sudo:
            permitted = all(self.run([sudo, "-n", "-l", "--", *command], check=False).returncode == 0
                            for command in systemctl_commands)
            if permitted:
                listing = self.run([sudo, "-n", "-ll"], check=False)
                if listing.returncode == 0 and all(passwordless_listing(listing.stdout, command)
                                                  for command in systemctl_commands):
                    self.backend_prefix = [sudo, "-n", "--"]
                    return
        raise ControlError("backend authorization unavailable before any stops; ask an administrator for "
                           "noninteractive permission for exactly: " + shlex.join(systemctl_commands[0]) +
                           " (explicit narrow NOPASSWD entry required for sudo). "
                           "No sudoers changes are made by this controller")

    def conflicts(self):
        deadline = time.monotonic() + self.timeouts["COMMAND"]
        for process in Path("/proc").iterdir():
            if time.monotonic() >= deadline:
                raise ControlError("manual-process conflict scan deadline exceeded; refusing mutation")
            if not process.name.isdigit():
                continue
            try:
                argv = (process / "cmdline").read_bytes().split(b"\0")
                args = [os.fsdecode(item) for item in argv if item]
                cwd = (process / "cwd").resolve(strict=True)
                cgroup = (process / "cgroup").read_text()
            except (OSError, RuntimeError):
                continue
            for component in self.selected:
                owned = any(UNITS[component] in line.split(":")[-1].split("/")
                            for line in cgroup.splitlines())
                if owned:
                    continue
                if component == "hmi":
                    matched = any((cwd / arg).resolve() in (ROOT / "hmi.py", ROOT / "launch_hmi.py")
                                  for arg in args[1:] if arg.endswith(".py"))
                else:
                    matched = cwd == ROOT and "main:app" in args and any(
                        "uvicorn" in Path(arg).name for arg in args)
                if matched:
                    raise ControlError(f"unmanaged {component} process PID {process.name}; stop it through its actual owner before retrying. Nothing was killed")
        if "backend" in self.selected and self.action in ("start", "restart"):
            if self.state("backend")["ActiveState"] != "active":
                family = socket.AF_INET6 if ":" in self.address else socket.AF_INET
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    try:
                        probe.bind((self.address, self.port))
                    except OSError as exc:
                        raise ControlError(f"backend port {self.address}:{self.port} conflict: {exc}; stop the listener through its actual owner, then retry. Nothing was killed")

    @contextlib.contextmanager
    def locked(self):
        path = ROOT / ".service_control.lock"
        flags = os.O_CREAT | os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o644)
        except OSError as exc:
            raise ControlError(f"cannot open installation lock {path}: {exc}")
        with os.fdopen(fd, "r") as lock:
            deadline = time.monotonic() + self.timeouts["LOCK"]
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ControlError(f"installation lock timeout ({path}); another operation is running")
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            yield

    def job(self, component, verb):
        prefix = self.backend_prefix if component == "backend" else []
        deadline = time.monotonic() + self.timeouts["JOB"]
        self.run([*prefix, *self.command(component, "--no-block", verb, UNITS[component])],
                 min(self.timeouts["COMMAND"], self.timeouts["JOB"]))
        desired = "inactive" if verb == "stop" else "active"
        while time.monotonic() < deadline:
            try:
                state = self.state(component, min(self.timeouts["COMMAND"], deadline - time.monotonic()))
            except ControlError as exc:
                if time.monotonic() >= deadline:
                    break
                raise ControlError(f"{component} {verb} job verification failed: {exc}; "
                                   "submitted job may still be running; inspect status before retrying")
            if not pending(state):
                if state["ActiveState"] == desired and (desired != "active" or state["SubState"] == "running"):
                    return
                if state["ActiveState"] in ("failed", "inactive"):
                    raise ControlError(f"{component} {verb} failed: {state}")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raise ControlError(f"{component} {verb} job deadline exceeded; submitted systemd job may still be running; inspect status before retrying")

    def readiness(self, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeouts["COMMAND"])
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise ControlError("API verification deadline exceeded")
            return value
        try:
            state = self.state("backend", remaining())
            if state["LoadState"] != "loaded" or state["ActiveState"] != "active" or state["SubState"] != "running":
                return False, "managed backend is not active/running (HTTP is not ownership)"
            code = ("import runpy,sys; "
                    "runpy.run_path(sys.argv[1])['fetch_status'](sys.argv[2])")
            response = self.run([sys.executable, "-B", "-c", code,
                                 str(Path(__file__).resolve()), self.status_url], remaining())
            status = json.loads(response.stdout)
            if (not isinstance(status, dict) or
                    any(key not in status for key in ("controller_error", "fatal_error")) or
                    not isinstance(status.get("sensors"), dict) or
                    not isinstance(status.get("acu_outputs"), dict) or
                    not isinstance(status.get("alarm_outputs"), dict) or
                    not isinstance(status.get("simulation"), bool) or
                    not {"temperature_c", "humidity_pct", "door_open", "smoke_alarm",
                         "water_level_alarm"}.issubset(status["sensors"]) or
                    set(status["acu_outputs"]) != {"acu1", "acu2"} or
                    set(status["alarm_outputs"]) != {"water", "smoke", "temperature", "humidity", "door"} or
                    any(type(value) is not bool for value in
                        [*status["acu_outputs"].values(), *status["alarm_outputs"].values()]) or
                    status.get("mode") not in ("auto", "manual", "pause")):
                return False, "invalid acuPilot API status schema"
            if status["controller_error"] is not None or status["fatal_error"] is not None:
                return False, "fatal controller state: " + str(status["fatal_error"] or status["controller_error"])
            final = self.state("backend", remaining())
            if (final["ActiveState"], final["SubState"]) != ("active", "running"):
                return False, "backend exited during API verification"
            return True, "ready"
        except (OSError, ValueError, ControlError) as exc:
            return False, f"API unavailable/invalid: {exc}"

    def wait_ready(self):
        deadline = time.monotonic() + self.timeouts["READY"]
        reason = "deadline expired"
        while time.monotonic() < deadline:
            ready, reason = self.readiness(min(self.timeouts["COMMAND"], deadline - time.monotonic()))
            if ready:
                print("acuPilot backend ready")
                return
            if reason.startswith("fatal controller state"):
                raise ControlError(reason + "; backend is not ready; HMI will not be started")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raise ControlError(f"backend readiness deadline ({self.timeouts['READY']}s): {reason}")

    def start(self, component, restart=False):
        state = self.state(component)
        if restart or state["ActiveState"] != "active":
            self.job(component, "restart" if restart else "start")
        if component == "backend":
            self.wait_ready()
        else:
            deadline = time.monotonic() + self.timeouts["HMI"]
            while True:
                state = self.state("hmi")
                if (state["ActiveState"], state["SubState"]) != ("active", "running"):
                    raise ControlError("HMI failed immediate activation observation")
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.1, deadline - time.monotonic()))
            print("acuPilot HMI active (window/display not certified)")

    def stop(self, component):
        if self.state(component)["ActiveState"] != "inactive":
            self.job(component, "stop")

    def status(self):
        good = True
        for component in self.selected:
            try:
                state = self.state(component)
                available = (state["LoadState"] == "loaded" and
                             (state["ActiveState"], state["SubState"]) == ("active", "running"))
                print(f"acuPilot {component} scope={'system' if component == 'backend' else 'user'} "
                      f"load={state['LoadState']} active={state['ActiveState']}/{state['SubState']} "
                      f"result={state.get('Result', '?')} exit={state.get('ExecMainStatus', '?')} "
                      f"job={state.get('Job', '?')}")
                if component == "backend":
                    ready, reason = self.readiness()
                    print(f"acuPilot backend readiness: {reason}")
                    available = available and ready
                good = good and available
            except ControlError as exc:
                good = False
                print(f"acuPilot {component} status unavailable: {exc}", file=sys.stderr)
        return good

    def diagnostics(self):
        print("acuPilot resulting partial state (no automatic rollback):", file=sys.stderr)
        self.status()
        for component in self.selected:
            scope = "--system" if component == "backend" else "--user"
            print(f"Diagnostics: journalctl {scope} -u {UNITS[component]} -n 80 --no-pager", file=sys.stderr)

    def execute(self):
        if self.action == "status":
            if "hmi" in self.selected and os.geteuid() == 0:
                raise ControlError("HMI status must run as the desktop user, not root")
            good = self.status()
            if not good:
                for component in self.selected:
                    print(f"Diagnostics: journalctl {'--system' if component == 'backend' else '--user'} -u {UNITS[component]} -n 80 --no-pager", file=sys.stderr)
            return 0 if good else 1
        with self.locked():
            self.preflight()
            try:
                if self.action == "stop":
                    for component in reversed(self.selected):
                        self.stop(component)
                elif self.action == "restart" and len(self.selected) == 2:
                    self.stop("hmi")
                    self.start("backend", restart=True)
                    self.start("hmi")
                else:
                    for component in self.selected:
                        self.start(component, restart=self.action == "restart")
                print(f"acuPilot {self.action} completed for {', '.join(self.selected)}")
                return 0
            except ControlError:
                self.diagnostics()
                raise


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if (not 1 <= len(args) <= 2 or args[0] not in ("start", "stop", "restart", "status") or
            (len(args) == 2 and args[1] not in ("both", "backend", "hmi"))):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        return Controller(args[0], args[1] if len(args) == 2 else "both").execute()
    except (ControlError, OSError) as exc:
        print(f"acuPilot service control failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
