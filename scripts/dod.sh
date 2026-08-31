#!/usr/bin/env bash
# DoD gate runner for ccgram deploys.
#
# Usage:
#   scripts/dod.sh              run the mechanical battery, NO stamp
#   scripts/dod.sh --reviewed   run the battery AND create the deploy stamp,
#                               attesting that the review gates (/simplify
#                               and /code-review high) also ran and passed
#                               on this exact tree.
#
# The deploy hook (.claude/hooks/deploy-gate.sh) blocks uv tool install /
# systemctl restart ccgram unless a fresh stamp for the current HEAD exists.

set -eu
cd "$(dirname "$0")/.."

REVIEWED=0
[ "${1:-}" = "--reviewed" ] && REVIEWED=1

echo "== mechanical battery =="
uv run --extra dev python -m pytest tests/ccgram -q --ignore=tests/ccgram/integration
make lint
PYRIGHT_PYTHON_FORCE_VERSION=latest uv run --extra dev pyright src/ccgram
uv run --extra dev ruff format --check src/ccgram tests/ccgram
echo "== mechanical battery: green =="

if [ "$REVIEWED" -ne 1 ]; then
  echo ""
  echo "NO STAMP CREATED. The battery is green but the review gates have not"
  echo "been attested. Run /simplify and /code-review high on the diff, fix"
  echo "what they surface, then: scripts/dod.sh --reviewed"
  exit 0
fi

HEAD_SHA=$(git rev-parse HEAD)
mkdir -p .claude
{
  echo "head $HEAD_SHA"
  echo "stamped $(date -Is)"
  echo "attest: /simplify and /code-review high ran and passed on this tree"
} > .claude/.dod-stamp
echo ""
echo "STAMP CREATED for $HEAD_SHA (valid 30 min). Deploy unlocked."
