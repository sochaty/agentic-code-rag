#!/bin/sh
# Get the corpus and its index ready (fast after the first start: everything lives in /data),
# then serve the API and the web UI on :8000.
set -e
acr setup "${ACR_INDEX:-flask}"
exec acr serve --host 0.0.0.0 --port "${PORT:-8000}"
