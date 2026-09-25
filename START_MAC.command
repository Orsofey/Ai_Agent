#!/bin/bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./SETUP_MAC.sh
exec .venv/bin/python main.py "$@"
