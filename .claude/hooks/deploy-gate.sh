#!/usr/bin/env bash
# Deploy gate for ccgram (private, project-local).
# Blocks the deploy commands (uv tool install / systemctl restart ccgram)
# unless a fresh DoD stamp exists for the CURRENT HEAD. The stamp is only
# created by scripts/dod.sh --reviewed, which attests the full battery AND
# the review gates (/simplify, /code-review) ran on this exact tree.
# Fail-open on parse errors: never brick the session, only guard deploys.

set -u
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$REPO_DIR/.claude/.dod-stamp"
STAMP_MAX_AGE_MINUTES=30

input=$(cat)

# Only Bash commands are in scope.
tool_name=$(printf '%s' "$input" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
[ "$tool_name" = "Bash" ] || exit 0

command_str=$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)

# Deploy patterns for THIS project. Match loosely: the deploy shows up inside
# compound commands too. The systemctl pattern covers the plain, sudo, --user,
# and .service restart forms (CLAUDE.md documents `systemctl restart ccgram`).
is_deploy_pattern() {
  case "$1" in
    *"uv tool install"*|*"systemctl"*"restart"*"ccgram"*) return 0 ;;
    *) return 1 ;;
  esac
}

# The sed capture is lossy: JSON-escaped quotes truncate it (`systemctl
# restart "ccgram"` parses as `systemctl restart \`) and a mangled payload can
# defeat it entirely. Whenever the parsed command does not match, re-check the
# raw input so a deploy cannot slip through on a parse artifact.
if ! is_deploy_pattern "$command_str"; then
  printf '%s' "$input" | grep -qE 'uv tool install|systemctl.*restart.*ccgram' || exit 0
fi

if [ ! -f "$STAMP" ]; then
  echo "DEPLOY BLOCKED: no DoD stamp. Run: scripts/dod.sh --reviewed (after the review gates) then retry the deploy." >&2
  exit 2
fi

# Stamp must reference the current HEAD.
current_head=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)
stamped_head=$(sed -n 's/^head \(.*\)$/\1/p' "$STAMP" | head -1)
if [ "$stamped_head" != "$current_head" ]; then
  echo "DEPLOY BLOCKED: DoD stamp is for $stamped_head but HEAD is $current_head. New commits since the gates ran: re-run scripts/dod.sh --reviewed." >&2
  exit 2
fi

# Stamp must be fresh.
stamp_age_min=$(( ($(date +%s) - $(stat -c %Y "$STAMP" 2>/dev/null || stat -f %m "$STAMP")) / 60 ))
if [ "$stamp_age_min" -ge "$STAMP_MAX_AGE_MINUTES" ]; then
  echo "DEPLOY BLOCKED: DoD stamp is ${stamp_age_min} min old (max ${STAMP_MAX_AGE_MINUTES}). Re-run scripts/dod.sh --reviewed." >&2
  exit 2
fi

exit 0
