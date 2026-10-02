"""Topic-label provider display: variant promotion for zai windows."""

from ccgram.handlers.provider_display import (
    display_variant,
    provider_topic_name,
)

ZAI = "/home/pantinor/.cc-mirror/zai/config/projects/p/-/session.jsonl"
ZAI_MAC = "/Users/pantinor/.cc-mirror/zai/config/projects/p/session.jsonl"
CLAUDE = "/home/pantinor/.claude/projects/p/-/session.jsonl"


class TestDisplayVariant:
    def test_zai_transcript_root_promotes_claude_to_zai(self):
        assert display_variant("claude", ZAI) == "zai"

    def test_zai_marker_matches_on_the_mac_root_and_case(self):
        assert display_variant("claude", ZAI_MAC) == "zai"
        assert display_variant("claude", ZAI.upper()) == "zai"

    def test_plain_claude_transcript_stays_claude(self):
        assert display_variant("claude", CLAUDE) == "claude"

    def test_no_transcript_or_empty_provider_untouched(self):
        assert display_variant("claude", "") == "claude"
        assert display_variant("claude", None) == "claude"
        assert display_variant("", ZAI) == ""

    def test_other_providers_pass_through_even_with_zai_marker(self):
        assert display_variant("codex", ZAI) == "codex"


class TestProviderTopicName:
    def test_zai_window_gets_zai_prefix(self):
        assert provider_topic_name("antiwire", "claude", ZAI) == "Zai · antiwire"

    def test_legacy_claude_prefix_converges_to_zai(self):
        assert (
            provider_topic_name("Claude · antiwire", "claude", ZAI) == "Zai · antiwire"
        )

    def test_plain_claude_window_keeps_claude_prefix(self):
        assert provider_topic_name("antiwire", "claude", CLAUDE) == "Claude · antiwire"

    def test_manual_zai_provider_names_directly(self):
        assert provider_topic_name("antiwire", "zai", "") == "Zai · antiwire"

    def test_no_transcript_keeps_current_behavior(self):
        assert provider_topic_name("antiwire", "claude") == "Claude · antiwire"
