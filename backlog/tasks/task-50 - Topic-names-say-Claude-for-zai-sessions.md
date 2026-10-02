# Topic names say "Claude" for zai sessions

Reported 2026-10-02 by the maintainer (Telegram screenshot): every forum
topic is named "Claude · <window>" even for sessions that run the zai
variant (CLAUDE_CONFIG_DIR at the mirrored config root), on both bird
and Mac chats.

## Root cause (verified by code reading)

`providers/zai.py` exists but is launch-only: its own docstring says
sessions launched via zai are "still tracked as claude". Topic naming
rides the tracked provider: `handlers/status/topic_emoji.py::
_resolve_topic_name` reads `identity_state.get_provider_name(window_id)`
and `handlers/provider_display.py::provider_topic_name` prefixes the
label from `PROVIDER_LABELS`, which maps only claude/codex/gemini/pi/
antigravity/shell. So every zai window names its topic "Claude · x",
and the /names renamer re-applies the same wrong label ("6 of 6 topics
renamed" in the screenshot).

## Design sketch

- Attribution: the window already stores `transcript_path`; zai
  transcripts live under the zai mirror config root while plain claude
  ones live under ~/.claude. Derive a display variant ("zai") from the
  transcript root at topic-naming time, or extend
  `SessionManager.set_window_provider` /
  `_detect_and_apply_provider` to record the variant when the hook
  event's transcript lands in the mirror. Keep launch-time provider
  semantics unchanged (ZaiProvider stays a ClaudeProvider subclass);
  only the topic label and any user-facing provider strings change.
- `PROVIDER_LABELS` gains `"zai": "Zai"`; `strip_provider_prefix` must
  strip the legacy "Claude · " prefix so old topics converge to
  "Zai · <name>" on the next rename cycle instead of nesting.
- Respect `is_provider_manually_overridden`: a manually chosen provider
  keeps authoritative naming.
- The /names renamer inherits the fix through the same
  `provider_topic_name` call; no separate path.

## Verification bar

Unit tests for: variant derivation from transcript roots (zai mirror,
default, unknown); provider_topic_name for zai; strip of the legacy
prefix; manual-override precedence. Live check: one zai window's topic
becomes "Zai · <name>" on the bird chat after the next state transition,
and the plain-claude windows (if any) stay "Claude · ".
