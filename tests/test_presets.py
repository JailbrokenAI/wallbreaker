import asyncio

from wallbreaker.config import Config, load_config
from wallbreaker.presets import PRESETS, get_preset, list_presets
from wallbreaker.tools import build_registry, presets_tool
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_all_presets_have_placeholder():
    assert PRESETS
    for p in list_presets():
        assert "{request}" in p.template, f"{p.name} missing placeholder"
        assert p.template.format(request="X")  # formats cleanly


def test_get_preset_case_insensitive():
    assert get_preset("DAN") is not None
    assert get_preset("nope") is None


def test_preset_registered():
    assert "preset" in build_registry(load_config()).names()


def test_preset_tool_list_and_get():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    presets_tool.register(reg)
    listed = asyncio.run(reg.execute("preset", {"action": "list"}))
    assert "dan" in listed.content
    got = asyncio.run(reg.execute("preset", {"action": "get", "name": "refusal_suppress"}))
    assert "{request}" in got.content
    miss = asyncio.run(reg.execute("preset", {"action": "get", "name": "zzz"}))
    assert "No preset" in miss.content


def test_2026_presets_present_and_formattable():
    for name in (
        "policy_puppetry", "bad_likert", "cot_hijack", "lego_decompose",
        "judge_spoof", "self_jailbreak", "first_person", "echo_chamber",
        "defender_re", "completeness_force", "continue_complete",
        "response_prime", "flip_attack", "past_tense", "immersive_world",
        "math_encode", "cot_safety_hijack", "deceptive_delight", "deep_inception",
        "logic_encode", "adversarial_poetry", "math_problem",
        "haunt_attack", "rationalization_seed",
        "academic_encyclopedia", "expert_witness", "ctf_answer_key",
        "patent_filing", "declassified_doc", "peer_review",
        "variable_z", "vq_sentinel", "newresponseformat",
        "ptsd_rule", "refusal_invert", "new_law",
        "output_leet", "lowresource_translate", "plinian_omniverse",
        "cot_channel_split", "cot_gradient",
    ):
        p = get_preset(name)
        assert p is not None, f"missing preset {name}"
        assert "{request}" in p.template
        assert p.template.format(request="X")


# ── external presets (.toml files in presets/) ──

import os
import tempfile
from pathlib import Path

from wallbreaker.presets import _load_preset_file, load_external_presets, reload_presets


def _write_toml(dirpath: Path, filename: str, name: str, desc: str, template: str) -> Path:
    p = dirpath / filename
    p.write_text(
        f'name = "{name}"\n'
        f'description = "{desc}"\n'
        f'template = """\n{template}\n"""\n',
        encoding="utf-8",
    )
    return p


def test_external_preset_loaded(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    _write_toml(
        presets_dir, "my_custom.toml", "my_custom",
        "A custom technique", "Do the thing.\n\nRequest: {request}",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    ext = load_external_presets()
    assert "my_custom" in ext
    assert ext["my_custom"].description == "A custom technique"
    assert "{request}" in ext["my_custom"].template


def test_external_overrides_builtin(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    _write_toml(
        presets_dir, "dan.toml", "dan",
        "Overridden DAN", "Custom DAN template.\n\n{request}",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    p = get_preset("dan")
    assert p is not None
    assert p.description == "Overridden DAN"


def test_external_preset_list_merged(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    _write_toml(
        presets_dir, "zzz_test_xyz.toml", "zzz_test_xyz",
        "Only in external", "Ext template.\n\n{request}",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    all_presets = list_presets()
    names = {p.name for p in all_presets}
    assert "zzz_test_xyz" in names
    assert "dan" in names  # built-in still present


def test_malformed_toml_skipped(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / "bad.toml").write_text("not valid toml {{{", encoding="utf-8")
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    ext = load_external_presets()
    assert "bad" not in ext  # skipped, not crashed


def test_missing_placeholder_skipped(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    _write_toml(
        presets_dir, "no_request.toml", "no_request",
        "Missing placeholder", "This template has no placeholder.",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    ext = load_external_presets()
    assert "no_request" not in ext


def test_missing_name_skipped(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    p = presets_dir / "no_name.toml"
    p.write_text(
        'description = "no name"\n'
        'template = """\n{request}\n"""\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    ext = load_external_presets()
    assert len(ext) == 0


def test_no_presets_dir_graceful(monkeypatch):
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", "/tmp/nonexistent_dir_xyz")
    reload_presets()
    ext = load_external_presets()
    assert ext == {}


def test_reload_invalidates_cache(tmp_path, monkeypatch):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    _write_toml(
        presets_dir, "a.toml", "a_first", "First", "First.\n\n{request}",
    )
    monkeypatch.setenv("WALLBREAKER_PRESETS_DIR", str(presets_dir))
    reload_presets()
    assert "a_first" in load_external_presets()

    # write a second file — shouldn't appear until reload
    _write_toml(
        presets_dir, "b.toml", "b_second", "Second", "Second.\n\n{request}",
    )
    assert "b_second" not in load_external_presets()  # cached
    reload_presets()
    assert "b_second" in load_external_presets()  # now visible


def test_preset_tool_reload_action():
    import asyncio
    from wallbreaker.config import Config
    from wallbreaker.tools.registry import ToolContext, ToolRegistry

    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    from wallbreaker.tools import presets_tool
    presets_tool.register(reg)
    result = asyncio.run(reg.execute("preset", {"action": "reload"}))
    assert "reloaded" in result.content.lower()


def test_load_preset_file_directly(tmp_path):
    p = _write_toml(
        tmp_path, "direct.toml", "direct_test", "Direct load", "Direct.\n\n{request}",
    )
    preset = _load_preset_file(p)
    assert preset is not None
    assert preset.name == "direct_test"
    assert preset.template.startswith("Direct.")


def test_load_preset_file_braces_in_template(tmp_path):
    p = tmp_path / "braces.toml"
    p.write_text(
        'name = "braces"\n'
        'description = "Has literal braces"\n'
        'template = """\nUse {request} safely.\n"""\n',
        encoding="utf-8",
    )
    preset = _load_preset_file(p)
    assert preset is not None
    assert preset.name == "braces"
