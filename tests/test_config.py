import pytest

from wallbreaker.config import ConfigError, Endpoint, _endpoint_from_table, load_config


def test_xai_protocol_defaults_base_url_and_key_env():
    ep = _endpoint_from_table("xai", {"protocol": "xai", "model": "grok-4.5"})
    assert ep.protocol == "xai"
    assert ep.base_url == "https://api.x.ai/v1"
    assert ep.api_key_env == "XAI_API_KEY"


def test_xai_explicit_overrides_win():
    ep = _endpoint_from_table(
        "xai",
        {
            "protocol": "xai",
            "model": "grok-4.3",
            "base_url": "https://proxy.example/v1/",
            "api_key": "inline-key",
        },
    )
    assert ep.base_url == "https://proxy.example/v1"  # trailing slash stripped
    assert ep.api_key == "inline-key"
    assert ep.api_key_env == ""  # inline key means no env default


def test_xai_routes_to_openai_provider():
    from wallbreaker.providers.factory import build_provider
    from wallbreaker.providers.openai_provider import OpenAIProvider

    ep = _endpoint_from_table("xai", {"protocol": "xai", "model": "grok-4.5", "api_key": "k"})
    assert isinstance(build_provider(ep), OpenAIProvider)


def test_xai_rejects_image_modality():
    with pytest.raises(ConfigError):
        _endpoint_from_table(
            "xai", {"protocol": "xai", "model": "grok-4.5", "modality": "image"}
        )


def test_invalid_protocol_message_lists_xai():
    with pytest.raises(ConfigError, match="xai"):
        _endpoint_from_table("bad", {"protocol": "nope", "base_url": "x", "model": "m"})


def test_load_example_config():
    cfg = load_config("config.example.toml")
    assert cfg.default_profile == "openrouter"
    assert "zai" in cfg.profiles
    assert cfg.profiles["zai"].protocol == "anthropic"
    assert cfg.target is not None


def test_profile_lookup_and_unknown():
    cfg = load_config("config.example.toml")
    assert cfg.profile("openrouter").base_url == "https://openrouter.ai/api/v1"
    with pytest.raises(ConfigError):
        cfg.profile("does-not-exist")


def test_require_key_errors_without_env(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    ep = Endpoint("t", "openai", "http://x", "m", api_key_env="MISSING_KEY")
    with pytest.raises(ConfigError):
        ep.require_key()


def test_resolved_key_from_env(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "secret-123")
    ep = Endpoint("t", "openai", "http://x", "m", api_key_env="SOME_KEY")
    assert ep.require_key() == "secret-123"


def test_apply_target_overrides_model_and_profile():
    from argparse import Namespace

    from wallbreaker.cli import apply_target_overrides

    cfg = load_config("config.example.toml")
    apply_target_overrides(cfg, Namespace(target="zai", target_model=None))
    assert cfg.target.protocol == "anthropic" and cfg.target.model == "glm-4.6"

    apply_target_overrides(cfg, Namespace(target=None, target_model="x-ai/grok-2"))
    assert cfg.target.model == "x-ai/grok-2"
    assert cfg.target.base_url == "https://api.z.ai/api/anthropic"
