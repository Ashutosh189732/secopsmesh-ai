#!/usr/bin/env bash
# Fire one (or all) demo scenarios at a running backend.
#
# Usage:
#   ./demo/run_scenario.sh <scenario-name|all> [api_base]
#
# Examples:
#   ./demo/run_scenario.sh 03_investigating_gdpr
#   ./demo/run_scenario.sh 03                       # numeric prefix also matches
#   ./demo/run_scenario.sh all
#   ./demo/run_scenario.sh all http://127.0.0.1:8000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIOS_DIR="$SCRIPT_DIR/scenarios"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <scenario-name|all> [api_base]" >&2
  echo >&2
  echo "Available scenarios:" >&2
  for f in "$SCENARIOS_DIR"/*.json; do
    echo "  $(basename "${f%.json}")" >&2
  done
  exit 1
fi

REQUESTED="$1"
API_BASE="${2:-http://127.0.0.1:8000}"

if command -v python >/dev/null 2>&1; then
  PYTHON=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "No python or python3 found on PATH." >&2
  exit 1
fi

if [ "$REQUESTED" = "all" ]; then
  exec "$PYTHON" "$SCRIPT_DIR/run_scenario.py" all --api-base "$API_BASE"
fi

# Allow a bare numeric prefix ("03") to resolve to its full filename.
MATCH=""
if [ -f "$SCENARIOS_DIR/$REQUESTED.json" ]; then
  MATCH="$REQUESTED"
else
  for f in "$SCENARIOS_DIR"/"$REQUESTED"*.json; do
    [ -e "$f" ] || continue
    MATCH="$(basename "${f%.json}")"
    break
  done
fi

if [ -z "$MATCH" ]; then
  echo "No scenario matches '$REQUESTED'." >&2
  echo >&2
  echo "Available scenarios:" >&2
  for f in "$SCENARIOS_DIR"/*.json; do
    echo "  $(basename "${f%.json}")" >&2
  done
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/run_scenario.py" "$MATCH" --api-base "$API_BASE"
