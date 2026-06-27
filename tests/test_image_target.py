from __future__ import annotations

import asyncio
import base64

import pytest

import rtharness.providers.factory as factory
import rtharness.tools.image as image_tool
from rtharness.config import ConfigError, Endpoint, _endpoint_from_table
from rtharness.providers.factory import build_provider
from rtharness.providers.image_provider import (
    ImageResult,
    OpenRouterImageProvider,
    _decode_data_url,
    _extract_images,
)
from rtharness.tools import build_registry
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.config import Config

# 1x1 transparent PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
PNG_BYTES = base64.b64decode(PNG_B64)
DATA_URL = f"data:image/png;base64,{PNG_B64}"


# ---- config -------------------------------------------------------------

def test_config_parses_image_modality():
    ep = _endpoint_from_table(
        "target",
        {"protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
         "model": "google/gemini-2.5-flash-image-preview", "modality": "image"},
    )
    assert ep.modality == "image"


def test_config_defaults_to_text_modality():
    ep = _endpoint_from_table(
        "p", {"protocol": "openai", "base_url": "http://x", "model": "m"}
    )
    assert ep.modality == "text"


def test_config_rejects_bad_modality():
    with pytest.raises(ConfigError):
        _endpoint_from_table(
            "p", {"protocol": "openai", "base_url": "http://x", "model": "m",
                  "modality": "video"},
        )


def test_config_rejects_image_on_anthropic():
    with pytest.raises(ConfigError):
        _endpoint_from_table(
            "p", {"protocol": "anthropic", "base_url": "http://x", "model": "m",
                  "modality": "image"},
        )


# ---- factory ------------------------------------------------------------

def test_factory_routes_image_modality():
    ep = Endpoint("t", "openai", "http://x", "m", modality="image")
    prov = build_provider(ep)
    assert type(prov).__name__ == "OpenRouterImageProvider"


def test_factory_text_still_openai():
    ep = Endpoint("t", "openai", "http://x", "m")
    assert type(build_provider(ep)).__name__ == "OpenAIProvider"


# ---- response parsing ---------------------------------------------------

def test_decode_data_url():
    mime, raw = _decode_data_url(DATA_URL)
    assert mime == "image/png"
    assert raw == PNG_BYTES


def test_extract_images_chat_shape():
    data = {
        "choices": [
            {
                "message": {
                    "content": "here you go",
                    "images": [
                        {"type": "image_url", "image_url": {"url": DATA_URL}}
                    ],
                }
            }
        ]
    }
    images, urls, text = _extract_images(data)
    assert len(images) == 1
    assert images[0][1] == PNG_BYTES
    assert urls == [DATA_URL]
    assert text == "here you go"


def test_extract_images_b64json_shape():
    data = {"data": [{"b64_json": PNG_B64}]}
    images, urls, text = _extract_images(data)
    assert len(images) == 1
    assert images[0][1] == PNG_BYTES
    assert urls[0].startswith("data:image/png;base64,")


def test_extract_images_refusal_text_only():
    data = {"choices": [{"message": {"content": "I can't create that image."}}]}
    images, urls, text = _extract_images(data)
    assert images == []
    assert "can't" in text


# ---- tool registration --------------------------------------------------

def test_image_tools_registered():
    cfg = Config(default_profile="t", profiles={"t": Endpoint("t", "openai", "http://x", "m")})
    names = build_registry(cfg).names()
    assert "query_image_target" in names
    assert "judge_image_file" in names


# ---- tool flow ----------------------------------------------------------

class _FakeImageProvider:
    def __init__(self, endpoint, **kw):
        self.endpoint = endpoint

    async def generate(self, messages, system=None, max_tokens=4096):
        return ImageResult(images=[("image/png", PNG_BYTES)], data_urls=[DATA_URL], text="ok")


def _img_reg(tmp_path):
    target = Endpoint("target", "openai", "http://x", "m", modality="image")
    judge = Endpoint("judge", "openai", "http://y", "vision-model")
    cfg = Config(default_profile="target", profiles={"target": target},
                 target=target, judge=judge)
    ctx = ToolContext(config=cfg, cwd=str(tmp_path), judge_endpoint=judge)
    reg = ToolRegistry(ctx)
    image_tool.register(reg)
    return reg


def test_query_image_target_saves_and_grades(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeImageProvider)

    async def fake_grade(endpoint, urls, payload="", objective="", timeout=120.0):
        return "COMPLIED", 9, "depicts the objective", "image-judge"

    monkeypatch.setattr(image_tool, "grade_image", fake_grade)

    recorded = []
    reg = _img_reg(tmp_path)
    reg.ctx.record = lambda *a: recorded.append(a)

    res = asyncio.run(reg.execute("query_image_target", {"prompt": "draw x", "objective": "x"}))
    assert "generated 1 image" in res.content
    assert "verdict=COMPLIED" in res.content
    assert "9/10" in res.content
    saved = list((tmp_path / "rth_images").glob("*.png"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == PNG_BYTES
    assert recorded and recorded[0][2] == "COMPLIED"


def _refusing_provider(text):
    class _P:
        def __init__(self, endpoint, **kw):
            pass

        async def generate(self, messages, system=None, max_tokens=4096):
            return ImageResult(images=[], data_urls=[], text=text)

    return _P


def test_query_image_target_no_image_is_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _refusing_provider("I won't make that."))
    recorded = []
    reg = _img_reg(tmp_path)
    reg.ctx.record = lambda *a: recorded.append(a)
    res = asyncio.run(reg.execute("query_image_target", {"prompt": "bad"}))
    assert "NO IMAGE RETURNED" in res.content
    assert "I won't make that." in res.content  # the model's actual words are surfaced
    assert "verdict=REFUSED" in res.content
    # no rth_images dir created when nothing came back
    assert not (tmp_path / "rth_images").exists()
    assert recorded and recorded[0][2] == "REFUSED"


def test_query_image_target_empty_response(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _refusing_provider(""))
    reg = _img_reg(tmp_path)
    res = asyncio.run(reg.execute("query_image_target", {"prompt": "x"}))
    assert "NO IMAGE RETURNED" in res.content
    assert "retry" in res.content.lower()


def test_analyze_refusal_hard():
    reason, hint = image_tool._analyze_refusal("I'm sorry, I cannot create that image.")
    assert reason.startswith("hard refusal")
    assert "reframe" in hint


def test_analyze_refusal_soft():
    reason, hint = image_tool._analyze_refusal(
        "I can't depict a real person, but I can make a stylized fictional character instead."
    )
    assert reason.startswith("soft refusal")
    assert "push" in hint.lower()


def test_analyze_refusal_empty():
    reason, hint = image_tool._analyze_refusal("")
    assert "empty" in reason.lower()
    assert "retry" in hint.lower()


def test_query_image_target_rejects_text_target(tmp_path, monkeypatch):
    target = Endpoint("target", "openai", "http://x", "m")  # text modality
    cfg = Config(default_profile="target", profiles={"target": target}, target=target)
    ctx = ToolContext(config=cfg, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    image_tool.register(reg)
    res = asyncio.run(reg.execute("query_image_target", {"prompt": "x"}))
    assert "modality" in res.content.lower()


def test_text_target_steers_away_from_image_model(tmp_path, monkeypatch):
    from rtharness.tools import target as target_mod

    target = Endpoint("target", "openai", "http://x", "m", modality="image")
    cfg = Config(default_profile="target", profiles={"target": target}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, cwd=str(tmp_path)))
    target_mod.register(reg)
    res = asyncio.run(reg.execute("query_target", {"prompt": "x"}))
    assert "image-generation model" in res.content
    assert "query_image_target" in res.content


def test_judge_image_file(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(PNG_BYTES)

    async def fake_grade(endpoint, urls, payload="", objective="", timeout=120.0):
        assert urls and urls[0].startswith("data:image/png;base64,")
        return "PARTIAL", 5, "partial render", "image-judge"

    monkeypatch.setattr(image_tool, "grade_image", fake_grade)
    judge = Endpoint("judge", "openai", "http://y", "vision-model")
    cfg = Config(default_profile="judge", profiles={"judge": judge}, judge=judge)
    ctx = ToolContext(config=cfg, cwd=str(tmp_path), judge_endpoint=judge)
    reg = ToolRegistry(ctx)
    image_tool.register(reg)
    res = asyncio.run(reg.execute("judge_image_file", {"path": "shot.png", "objective": "x"}))
    assert "verdict=PARTIAL" in res.content
    assert "5/10" in res.content


# ---- provider stream() shim --------------------------------------------

def test_image_provider_stream_summarizes(monkeypatch):
    ep = Endpoint("t", "openai", "http://x", "m", modality="image")
    prov = OpenRouterImageProvider(ep)

    async def fake_generate(messages, system=None, max_tokens=4096):
        return ImageResult(images=[("image/png", PNG_BYTES)], data_urls=[DATA_URL], text="hi")

    prov.generate = fake_generate

    async def collect():
        out = []
        async for ev in prov.stream([]):
            out.append(ev)
        return out

    events = asyncio.run(collect())
    texts = [e.text for e in events if hasattr(e, "text")]
    assert any("1 image" in t for t in texts)
