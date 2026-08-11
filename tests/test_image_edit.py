from __future__ import annotations

import asyncio
import base64

import wallbreaker.providers.factory as factory
import wallbreaker.tools.image_edit as image_edit
from wallbreaker.config import Config, Endpoint
from wallbreaker.providers.image_provider import ImageResult, _edit_wire
from wallbreaker.tools import build_registry
from wallbreaker.tools.registry import ToolContext, ToolRegistry

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
PNG_BYTES = base64.b64decode(PNG_B64)
DATA_URL = f"data:image/png;base64,{PNG_B64}"


# ---- _edit_wire (multimodal body) ---------------------------------------

def test_edit_wire_user_image_is_multimodal():
    wire = _edit_wire(
        [{"role": "user", "text": "edit this", "images": [DATA_URL]}],
        system="sys",
    )
    assert wire[0] == {"role": "system", "content": "sys"}
    content = wire[1]["content"]
    assert content[0] == {"type": "text", "text": "edit this"}
    assert content[1] == {"type": "image_url", "image_url": {"url": DATA_URL}}


def test_edit_wire_assistant_and_imageless_user_stay_text():
    wire = _edit_wire([
        {"role": "user", "text": "step one", "images": []},
        {"role": "assistant", "text": "[image produced]"},
    ])
    assert wire[0] == {"role": "user", "content": "step one"}
    assert wire[1] == {"role": "assistant", "content": "[image produced]"}


def test_generate_edit_posts_and_extracts(monkeypatch):
    from wallbreaker.providers.image_provider import OpenRouterImageProvider

    ep = Endpoint("t", "openai", "http://x", "m", modality="image")
    prov = OpenRouterImageProvider(ep)
    captured = {}

    async def fake_post(payload):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "done",
                "images": [{"image_url": {"url": DATA_URL}}]}}]}

    prov._post_chat = fake_post
    res = asyncio.run(prov.generate_edit(
        [{"role": "user", "text": "go", "images": [DATA_URL]}]
    ))
    assert res.images and res.images[0][1] == PNG_BYTES
    assert captured["payload"]["modalities"] == ["image", "text"]
    assert captured["payload"]["messages"][0]["content"][1]["type"] == "image_url"


# ---- registration -------------------------------------------------------

def test_image_edit_tools_registered():
    cfg = Config(default_profile="t", profiles={"t": Endpoint("t", "openai", "http://x", "m")})
    names = build_registry(cfg).names()
    assert "query_image_edit" in names
    assert "image_chain" in names


# ---- fakes --------------------------------------------------------------

class _RecEdit:
    """Records every generate_edit turn-list across instances; returns an image."""

    seen: list = []

    def __init__(self, endpoint, **kw):
        self.endpoint = endpoint

    async def generate_edit(self, turns, system=None, max_tokens=4096):
        _RecEdit.seen.append(turns)
        return ImageResult(images=[("image/png", PNG_BYTES)], data_urls=[DATA_URL], text="ok")


def _edit_reg(tmp_path):
    target = Endpoint("target", "openai", "http://x", "m", modality="image")
    judge = Endpoint("judge", "openai", "http://y", "vision-model")
    cfg = Config(default_profile="target", profiles={"target": target},
                 target=target, judge=judge)
    ctx = ToolContext(config=cfg, cwd=str(tmp_path), judge_endpoint=judge)
    reg = ToolRegistry(ctx)
    image_edit.register(reg)
    return reg


async def _fake_grade(endpoint, urls, payload="", objective="", timeout=120.0, reasoning=""):
    return "COMPLIED", 9, "depicts the objective", "image-judge"


# ---- query_image_edit ---------------------------------------------------

def test_query_image_edit_carries_input_and_grades(tmp_path, monkeypatch):
    _RecEdit.seen = []
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    monkeypatch.setattr(image_edit, "grade_image", _fake_grade)

    src = tmp_path / "base.png"
    src.write_bytes(PNG_BYTES)

    reg = _edit_reg(tmp_path)
    recorded = []
    reg.ctx.record = lambda *a: recorded.append(a)

    res = asyncio.run(reg.execute(
        "query_image_edit",
        {"prompt": "restyle this person", "image": "base.png", "objective": "x"},
    ))
    assert "produced 1 edited image" in res.content
    assert "verdict=COMPLIED" in res.content and "9/10" in res.content
    # the input image was carried as a multimodal image_url part
    turns = _RecEdit.seen[0]
    assert turns[0]["images"] and turns[0]["images"][0].startswith("data:image/png")
    saved = list((tmp_path / "wb_images").glob("*.png"))
    assert saved and saved[0].read_bytes() == PNG_BYTES
    assert recorded and recorded[0][2] == "COMPLIED"


def test_query_image_edit_missing_input_image(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    reg = _edit_reg(tmp_path)
    res = asyncio.run(reg.execute(
        "query_image_edit", {"prompt": "edit", "image": "nope.png"}
    ))
    assert "not found" in res.content.lower()


def test_query_image_edit_image_only_suffix(tmp_path, monkeypatch):
    _RecEdit.seen = []
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    monkeypatch.setattr(image_edit, "grade_image", _fake_grade)
    reg = _edit_reg(tmp_path)
    asyncio.run(reg.execute(
        "query_image_edit", {"prompt": "do it", "image_only": True}
    ))
    assert "answer only with the image" in _RecEdit.seen[0][0]["text"].lower()


def test_query_image_edit_refusal(tmp_path, monkeypatch):
    class _Refuse:
        def __init__(self, endpoint, **kw):
            pass

        async def generate_edit(self, turns, system=None, max_tokens=4096):
            return ImageResult(images=[], data_urls=[], text="I can't edit that.")

    monkeypatch.setattr(factory, "build_provider", _Refuse)
    reg = _edit_reg(tmp_path)
    recorded = []
    reg.ctx.record = lambda *a: recorded.append(a)
    res = asyncio.run(reg.execute("query_image_edit", {"prompt": "bad edit"}))
    assert "NO IMAGE RETURNED" in res.content
    assert "verdict=REFUSED" in res.content
    assert recorded and recorded[0][2] == "REFUSED"


def test_query_image_edit_rejects_text_target(tmp_path):
    target = Endpoint("target", "openai", "http://x", "m")  # text modality
    cfg = Config(default_profile="target", profiles={"target": target}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, cwd=str(tmp_path)))
    image_edit.register(reg)
    res = asyncio.run(reg.execute("query_image_edit", {"prompt": "x"}))
    assert "modality" in res.content.lower()


# ---- image_chain (static) -----------------------------------------------

def test_image_chain_static_round_trips_and_breaks(tmp_path, monkeypatch):
    _RecEdit.seen = []
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    monkeypatch.setattr(image_edit, "grade_image", _fake_grade)

    reg = _edit_reg(tmp_path)
    recorded = []
    reg.ctx.record = lambda *a: recorded.append(a)

    res = asyncio.run(reg.execute("image_chain", {
        "steps": ["a calm studio scene", "swap the backdrop", "pivot the subject"],
        "objective": "final target",
    }))
    assert "image_chain static, 3 edits" in res.content
    assert "chain broke at step 1" in res.content  # grade returns COMPLIED on step 1
    # step 2's turn-list must carry the image produced by step 1 (round-trip)
    step2_user = _RecEdit.seen[1][-1]
    assert step2_user["images"] == [DATA_URL]
    # image_only default true -> suffix present
    assert "answer only with the image" in _RecEdit.seen[0][0]["text"].lower()
    assert recorded and recorded[0][4] == "image-chain"


def test_image_chain_static_requires_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    reg = _edit_reg(tmp_path)
    res = asyncio.run(reg.execute("image_chain", {"objective": "x"}))
    assert "steps" in res.content.lower()


# ---- image_chain (auto) -------------------------------------------------

def test_image_chain_auto_drives_attacker(tmp_path, monkeypatch):
    _RecEdit.seen = []

    class _Attacker:
        def __init__(self, endpoint, **kw):
            pass

        async def complete(self, messages, system=None, max_tokens=1024):
            return "add one small innocuous detail"

    def dispatch(endpoint, timeout=None, **kw):
        if getattr(endpoint, "modality", "text") == "image":
            return _RecEdit(endpoint)
        return _Attacker(endpoint)

    monkeypatch.setattr(factory, "build_provider", dispatch)
    monkeypatch.setattr(image_edit, "grade_image", _fake_grade)

    reg = _edit_reg(tmp_path)
    res = asyncio.run(reg.execute("image_chain", {
        "mode": "auto", "objective": "final target", "max_turns": 4,
    }))
    assert "image_chain auto" in res.content
    assert "chain broke at step 1" in res.content  # COMPLIED on the first fired edit
    assert _RecEdit.seen  # the attacker's instruction was fired at the image target


def test_image_chain_auto_requires_objective(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _RecEdit)
    reg = _edit_reg(tmp_path)
    res = asyncio.run(reg.execute("image_chain", {"mode": "auto"}))
    assert "objective" in res.content.lower()
