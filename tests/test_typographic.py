from __future__ import annotations

import pytest; pytest.importorskip('PIL', reason='Pillow not installed')

import asyncio

from PIL import Image

import wallbreaker.tools.typographic as typo
from wallbreaker.config import Config, Endpoint
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _reg(tmp_path):
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep})
    ctx = ToolContext(config=cfg, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    typo.register(reg)
    return reg


def _path_from(content: str) -> str:
    return content.rsplit(": ", 1)[-1].strip().splitlines()[0]


def test_tool_registered(tmp_path):
    reg = _reg(tmp_path)
    assert "build_typographic_image" in reg.names()


def test_build_single_produces_valid_png(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(reg.execute("build_typographic_image", {"text": "hello world"}))
    assert not res.is_error
    path = _path_from(res.content)
    saved = list((tmp_path / "wb_images").glob("typo_*.png"))
    assert len(saved) == 1
    assert str(saved[0]) == path
    with Image.open(saved[0]) as img:
        img.verify()
    with Image.open(saved[0]) as img:
        assert img.format == "PNG"
        assert img.width > 0 and img.height > 0


def test_all_three_layouts_produce_files(tmp_path):
    reg = _reg(tmp_path)
    text = "first step here. second step there. third final step"
    for layout in ("single", "numbered_list", "subfigure_split"):
        res = asyncio.run(
            reg.execute("build_typographic_image", {"text": text, "layout": layout})
        )
        assert not res.is_error, res.content
        path = _path_from(res.content)
        with Image.open(path) as img:
            img.verify()
    files = list((tmp_path / "wb_images").glob("typo_*.png"))
    assert len(files) == 3


def test_content_hash_is_stable(tmp_path):
    reg = _reg(tmp_path)
    a = asyncio.run(reg.execute("build_typographic_image", {"text": "same text"}))
    b = asyncio.run(reg.execute("build_typographic_image", {"text": "same text"}))
    assert _path_from(a.content) == _path_from(b.content)
    assert len(list((tmp_path / "wb_images").glob("typo_*.png"))) == 1


def test_unknown_layout_errors(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(
        reg.execute("build_typographic_image", {"text": "x", "layout": "spiral"})
    )
    assert "unknown layout" in res.content.lower()


def test_empty_text_errors(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(reg.execute("build_typographic_image", {"text": "   "}))
    assert "required" in res.content.lower()


def test_custom_colors_and_font_size(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(reg.execute(
        "build_typographic_image",
        {"text": "colored", "font_size": 40, "bg": "black", "fg": "white"},
    ))
    assert not res.is_error
    with Image.open(_path_from(res.content)) as img:
        assert img.mode == "RGB"


def test_smuggle_helper_wraps_builder(tmp_path):
    reg = _reg(tmp_path)
    out = asyncio.run(typo.smuggle_image_of_text(reg.ctx, "carry these words"))
    path = _path_from(out)
    with Image.open(path) as img:
        img.verify()
    assert (tmp_path / "wb_images").exists()
