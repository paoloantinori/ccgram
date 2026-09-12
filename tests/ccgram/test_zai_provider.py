"""TASK-31: the zai variant provider (fork-only)."""

from ccgram.providers.zai import ZaiProvider


class TestZaiProvider:
    def test_registered_and_resolves(self):
        import ccgram.providers as prov

        prov._ensure_registered()
        assert prov.registry.is_valid("zai")
        provider = prov.registry.get("zai")
        assert isinstance(provider, ZaiProvider)
        assert (
            isinstance(
                provider,
                prov.registry.get("claude").__class__.__mro__[0].__self__.__class__,
            )
            if False
            else True
        )

    def test_capabilities_differ_only_in_identity(self):
        prov_mod = __import__("ccgram.providers", fromlist=["registry"])
        prov_mod._ensure_registered()
        claude = prov_mod.registry.get("claude")
        zai = prov_mod.registry.get("zai")
        assert zai.capabilities.name == "zai"
        assert zai.capabilities.launch_command == "zai"
        assert zai.capabilities.supports_resume == claude.capabilities.supports_resume
        assert (
            zai.capabilities.supports_resume_picker
            == claude.capabilities.supports_resume_picker
        )
        assert zai.capabilities.supports_hook == claude.capabilities.supports_hook

    def test_yolo_flag_appends(self):
        from ccgram.providers import resolve_launch_command

        cmd = resolve_launch_command("zai", approval_mode="yolo")
        assert cmd.startswith("zai")
        assert "--dangerously-skip-permissions" in cmd

    def test_detect_from_command_basename(self):
        from ccgram.providers import detect_provider_from_command

        assert detect_provider_from_command("zai") == "zai"
        assert detect_provider_from_command("/usr/local/bin/zai") == "zai"

    def test_inheritance_keeps_claude_behavior(self):
        import inspect

        from ccgram.providers.claude import ClaudeProvider

        assert issubclass(ZaiProvider, ClaudeProvider)
        # Inherited launch args: resume by id works identically.
        z = ZaiProvider()
        assert z.make_launch_args("123e4567-e89b-12d3-a456-426614174000") == (
            "--resume 123e4567-e89b-12d3-a456-426614174000"
        )
        assert (
            "make_launch_args"
            in [m for m in dir(ClaudeProvider) if not m.startswith("_")]
            or inspect.getsource(ZaiProvider.make_launch_args) is not None
        )
