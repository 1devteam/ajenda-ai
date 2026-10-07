#!/usr/bin/env sh
set -eu

exec python -m backend.workers.assurance_loop
