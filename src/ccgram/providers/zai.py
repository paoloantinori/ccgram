"""Zai provider: the user's Claude Code wrapper variant (fork-only).

zai is a wrapper script (``~/.local/bin/zai``) that points
``CLAUDE_CONFIG_DIR`` at a mirrored config dir and execs the Claude CLI:
same TUI, same transcript schema, same hooks. Only the launch command
and the config root differ. Subclassing ClaudeProvider inherits all of
it (status parsing, resume args, cc commands); the variant differs only
in the executable and its identity.

Selected from the /new provider picker (or /agent) when a zai session
should run beside an official-claude one. Sessions launched this way
are still *tracked* as claude (hooks/transcripts are claude-format);
the variant matters at launch and relaunch time.
"""

from dataclasses import replace

from .claude import ClaudeProvider


class ZaiProvider(ClaudeProvider):
    """Claude Code via the zai wrapper (mirrored config dir)."""

    _CAPS = replace(
        ClaudeProvider._CAPS,
        name="zai",
        launch_command="zai",
    )
