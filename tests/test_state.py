from rtharness.config import (
    load_config,
    looks_like_image_model,
    resolve_target_modality,
)
from rtharness.state import apply_attacker, apply_target, load_state, save_state


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / ".rth_state.json"
    save_state(p, {"profile": "glm", "auto": False, "rounds": 5})
    loaded = load_state(p)
    assert loaded["profile"] == "glm" and loaded["auto"] is False
    assert loaded["rounds"] == 5


def test_load_missing_returns_empty(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}


def test_apply_attacker_profile_and_model():
    cfg = load_config("config.example.toml")
    base = cfg.profile("openrouter")
    ep = apply_attacker(cfg, base, {"profile": "zai", "attacker_model": "glm-9"})
    assert ep.protocol == "anthropic"
    assert ep.model == "glm-9"


def test_apply_target_profile_then_model():
    cfg = load_config("config.example.toml")
    apply_target(cfg, {"target_profile": "zai", "target_model": "glm-4.6-air"})
    assert cfg.target.base_url == "https://api.z.ai/api/anthropic"
    assert cfg.target.model == "glm-4.6-air"


def test_apply_empty_prefs_is_noop():
    cfg = load_config("config.example.toml")
    before = cfg.target.model
    apply_target(cfg, {})
    assert cfg.target.model == before


# ---- modality on runtime target override (the gemini-3-pro-image bug) ----

def test_looks_like_image_model():
    assert looks_like_image_model("google/gemini-3-pro-image")
    assert looks_like_image_model("black-forest-labs/flux.2-pro")
    assert looks_like_image_model("openai/gpt-5.4-image-2")
    assert not looks_like_image_model("openai/gpt-4o-mini")
    assert not looks_like_image_model("anthropic/claude-sonnet-4.5")


def test_resolve_modality_autodetects_image():
    assert resolve_target_modality("google/gemini-3-pro-image") == "image"
    assert resolve_target_modality("openai/gpt-4o-mini") == "text"


def test_resolve_modality_explicit_wins():
    # a custom image model whose id has no hint can be forced
    assert resolve_target_modality("my-org/custom-renderer", "image") == "image"
    # and an image-named model can be forced back to text
    assert resolve_target_modality("foo/gpt-image", "text") == "text"


def test_apply_target_model_swap_to_image_sets_modality():
    # This is the exact failure: state pointed the target at an image model but the
    # override only swapped the model id, leaving modality='text' -> image tools refused.
    cfg = load_config("config.example.toml")
    assert cfg.target.modality == "text"
    apply_target(cfg, {"target_model": "google/gemini-3-pro-image"})
    assert cfg.target.model == "google/gemini-3-pro-image"
    assert cfg.target.modality == "image"


def test_apply_target_explicit_modality_override():
    cfg = load_config("config.example.toml")
    apply_target(cfg, {"target_model": "my-org/secret-image-gen", "target_modality": "image"})
    assert cfg.target.modality == "image"


def test_apply_target_model_swap_to_text_stays_text():
    cfg = load_config("config.example.toml")
    apply_target(cfg, {"target_model": "openai/gpt-4o-mini"})
    assert cfg.target.modality == "text"


def test_cli_target_model_flag_sets_image_modality():
    import argparse

    from rtharness.cli import apply_target_overrides

    cfg = load_config("config.example.toml")
    args = argparse.Namespace(
        target=None, target_model="google/gemini-3-pro-image", target_modality=None
    )
    apply_target_overrides(cfg, args)
    assert cfg.target.model == "google/gemini-3-pro-image"
    assert cfg.target.modality == "image"


def test_cli_force_modality_without_model_swap():
    import argparse

    from rtharness.cli import apply_target_overrides

    cfg = load_config("config.example.toml")  # [target] is a text model
    args = argparse.Namespace(target=None, target_model=None, target_modality="image")
    apply_target_overrides(cfg, args)
    assert cfg.target.modality == "image"
