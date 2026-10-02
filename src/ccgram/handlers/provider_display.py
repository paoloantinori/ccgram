"""Small, searchable provider labels for Telegram's constrained topic headers."""

PROVIDER_LABELS = {
    "claude": "Claude",
    "zai": "Zai",
    "codex": "Codex",
    "gemini": "Gemini",
    "pi": "Pi",
    "antigravity": "Antigravity",
    "shell": "Terminal",
}
PROVIDER_SEPARATOR = " · "

# Claude-variant sessions (tracked as claude because hooks and transcripts
# share the Claude Code schema) live under the zai mirrored config root on
# every machine; their topics must still show the variant, not "Claude".
ZAI_TRANSCRIPT_MARKER = ".cc-mirror/zai/"


def provider_label(name: str, *, compact: bool = False) -> str:
    if compact and name == "shell":
        return "Term"
    return PROVIDER_LABELS.get(name, name.capitalize())


def display_variant(provider: str, transcript_path: str | None) -> str:
    """Resolve the topic-label provider, promoting tracked-claude zai windows.

    Launch-time detection deliberately maps every Claude Code wrapper to
    ``claude``; only naming needs the variant, and only the persisted
    transcript root tells them apart. Anything but a plain-claude provider
    passes through untouched.
    """
    if provider != "claude" or not transcript_path:
        return provider
    if ZAI_TRANSCRIPT_MARKER in transcript_path.replace("\\", "/").lower():
        return "zai"
    return provider


def strip_provider_prefix(name: str, *, legacy: bool = False) -> str:
    """Strip only our delimited labels, including the existing Herdr format."""
    separators = (PROVIDER_SEPARATOR, " ▸ ") if legacy else (PROVIDER_SEPARATOR,)
    for label in (*PROVIDER_LABELS.values(), "Term", "Shell"):
        for separator in separators:
            if name.startswith(label + separator):
                return name[len(label + separator) :]
    return name


def provider_topic_name(
    name: str,
    provider: str,
    transcript_path: str | None = None,
) -> str:
    provider = display_variant(provider, transcript_path)
    if not provider:
        return name
    return (
        provider_label(provider, compact=True)
        + PROVIDER_SEPARATOR
        + strip_provider_prefix(name, legacy=True)
    )
