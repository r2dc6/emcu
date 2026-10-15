#!/usr/bin/env python3
"""Isolated systemctl/pkcheck/sudo executable used only by controller tests."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

root = Path(os.environ["FAKE_MANAGER"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
config = json.loads((root / "config.json").read_text())
if "--action-id" in args:
    sys.exit(0 if config.get("polkit", True) else 1)
if "-n" in args:
    if not config.get("sudo", False):
        sys.exit(1)
    if "-l" in args:
        sys.exit(0)
    if "-ll" in args:
        command = [str(root / "bin/systemctl"), "--system", "--no-ask-password", "--no-block",
                   config.get("sudo_verb", "restart"), "acupilot-backend.service"]
        print("Sudoers entry:\n    RunAsUsers: root\n    Options: " +
              ("!authenticate" if config.get("nopasswd", True) else "authenticate") +
              "\n    Commands:\n        " + shlex.join(command))
        sys.exit(0)
    sys.exit(subprocess.call(args[args.index("--") + 1:]))
if config.get("hang"):
    time.sleep(10)
if "--no-ask-password" not in args:
    sys.exit("interactive systemctl forbidden")
scope = "backend" if "--system" in args else "hmi"
if config.get("disconnected") == scope:
    sys.exit("manager unavailable")
verbs = ("show", "is-active", "show-environment", "start", "stop", "restart")
verb = next((arg for arg in args if arg in verbs), None)
if verb == "is-active":
    print("active" if config.get("session", True) else "inactive")
    sys.exit(0 if config.get("session", True) else 3)
if verb == "show-environment":
    print(config.get("environment", "DISPLAY=:99"))
    sys.exit(0)
unit = "acupilot-backend.service" if scope == "backend" else "coolshift-hmi.service"
if unit not in args:
    sys.exit("wrong manager scope or unit")
path = root / f"{scope}.json"
state = json.loads(path.read_text())
if verb == "show":
    if state.get("polls", 0):
        state["polls"] -= 1
        if not state["polls"]:
            state["ActiveState"] = state.pop("final")
            state["SubState"] = "running" if state["ActiveState"] == "active" else "dead"
            state["Job"] = ""
        path.write_text(json.dumps(state))
    for key, value in state.items():
        print(f"{key}={value}")
elif verb in ("start", "stop", "restart"):
    if config.get("reject") == f"{scope}:{verb}":
        sys.exit("injected submission failure")
    final = "inactive" if verb == "stop" else "active"
    if config.get("fail") == f"{scope}:{verb}":
        final = "failed"
    delay = config.get("polls", 0)
    state.update(ActiveState="activating" if delay else final,
                 SubState="running" if not delay and final == "active" else "dead",
                 Job="123 /job/123" if delay else "")
    if delay:
        state.update(polls=delay, final=final)
    if final == "failed":
        state.update(Result="exit-code", ExecMainStatus="1")
    path.write_text(json.dumps(state))
else:
    sys.exit("unsupported fake-manager command")
