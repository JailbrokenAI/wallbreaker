"""Product-layer Daedalus branding helpers."""

from wallbreaker.branding import (
    cli_description,
    desktop_product_name,
    notify_title,
    product_codename,
    product_mark,
    product_wordmark_parts,
)
from wallbreaker.config import Config, DaedalusSettings, Endpoint


def test_default_codename_is_daedalus():
    assert product_codename(None) == "Daedalus"
    assert product_mark(None) == "D"
    prefix, rest = product_wordmark_parts(None)
    assert prefix == "DAE"
    assert rest == "DALUS"


def test_config_codename_override():
    cfg = Config(
        default_profile="x",
        profiles={
            "x": Endpoint(name="x", protocol="openai", base_url="http://x", model="m")
        },
        daedalus=DaedalusSettings(codename="Icarus"),
    )
    assert product_codename(cfg) == "Icarus"
    assert product_mark(cfg) == "I"
    assert "Icarus" in cli_description(cfg)
    assert desktop_product_name(cfg) == "Icarus Desktop"
    assert notify_title(cfg, "COMPLIED") == "Icarus · COMPLIED"


def test_cli_parser_mentions_daedalus():
    from wallbreaker.cli import build_main_parser

    p = build_main_parser()
    assert "Daedalus" in (p.description or "")
    # package CLI name stays wallbreaker
    assert p.prog == "wallbreaker"


def test_crescendo_default_mode_is_auto():
    text = open("wallbreaker/tools/crescendo.py", encoding="utf-8").read()
    assert 'args.get("mode", "auto")' in text
