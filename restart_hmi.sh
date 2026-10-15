#!/bin/bash

# Stop only this installation's launcher or legacy direct HMI.
pattern='[p]ython[^ ]* /home/rheg/App/(launch_hmi|hmi)\.py([ ]|$)'
mapfile -t pids < <(pgrep -f "$pattern")
if ((${#pids[@]})); then
    kill -TERM "${pids[@]}" || true
    for ((attempt=0; attempt<50; attempt++)); do
        if ! pgrep -f "$pattern" >/dev/null; then
            break
        fi
        sleep 0.2
    done
    if pgrep -f "$pattern" >/dev/null; then
        echo "acuPilot HMI did not stop; refusing to launch a duplicate" >&2
        exit 1
    fi
fi

# Restart HMI
nohup /home/rheg/App/start_hmi.sh "$@" \
    >/dev/null 2>&1 </dev/null &
