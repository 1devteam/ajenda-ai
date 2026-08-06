#!/usr/bin/env bash
# Apply Wave A operator-reads matrix to a clean main checkout
set -euo pipefail
git apply --index artifacts/wave-a/0001-feat-composition-Wave-A-operator-reads-LinkedIn-GitH.patch
git commit -m "feat(composition): Wave A operator reads — LinkedIn, GitHub, Google Contacts"
