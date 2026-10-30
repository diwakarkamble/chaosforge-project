from chaosforge.interfaces.cli.session import (
    PlatformContext,
    context,
)


def test_platform_context_default_region():
    ctx = PlatformContext()

    assert ctx.region is None


def test_global_context_instance():
    assert isinstance(context, PlatformContext)

    assert context.region is None


def test_update_region():
    ctx = PlatformContext()

    ctx.region = "eu-central-1"

    assert ctx.region == "eu-central-1"
