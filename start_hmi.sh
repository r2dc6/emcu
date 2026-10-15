#!/bin/bash

cd /home/rheg/App || exit 1

exec /home/rheg/App/.venv/bin/python \
    /home/rheg/App/launch_hmi.py "$@"
