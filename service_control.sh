#!/bin/bash
# Python's standard library supplies bounded jobs, locking and HTTP validation.
set -eu
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$ROOT/deploy/service_control.py" "$@"
