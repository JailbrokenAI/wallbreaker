"""Unit tests for judge_selftest agreement metrics (no network)."""

from wallbreaker.tools.judge_selftest import _agrees, _cohen_kappa, _spearman


def test_agrees_rules():
    assert _agrees("REFUSED", "REFUSED")
    assert not _agrees("REFUSED", "GARBLED")
    assert _agrees("GARBLED", "GARBLED")
    assert _agrees("PARTIAL", "COMPLIED")
    assert _agrees("COMPLIED", "PARTIAL")


def test_cohen_kappa_perfect():
    pairs = [("A", "A"), ("B", "B"), ("A", "A"), ("B", "B")]
    assert abs(_cohen_kappa(pairs) - 1.0) < 1e-9


def test_cohen_kappa_worse_than_chance():
    pairs = [("A", "B"), ("A", "B"), ("B", "A"), ("B", "A")]
    assert _cohen_kappa(pairs) < 0


def test_spearman_monotone():
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [0.0, 1.0, 2.0, 3.0]
    assert abs(_spearman(xs, ys) - 1.0) < 1e-9
    assert abs(_spearman(xs, list(reversed(ys))) + 1.0) < 1e-9
