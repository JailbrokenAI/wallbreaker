import asyncio
import pytest

from wallbreaker.tools._util import await_llm, _MIN_OUTER_LLM_TIMEOUT


async def _slow(seconds: float, value: str = "ok"):
    await asyncio.sleep(seconds)
    return value


def test_await_llm_no_timeout_plain_await():
    assert asyncio.run(await_llm(_slow(0.01, "x"))) == "x"


def test_await_llm_floors_short_timeout():
    # 0.05s requested would have cancelled under old wait_for; floor keeps it alive.
    assert asyncio.run(await_llm(_slow(0.05, "y"), timeout=0.05)) == "y"


def test_await_llm_zero_timeout_disables_outer():
    assert asyncio.run(await_llm(_slow(0.01, "z"), timeout=0)) == "z"


def test_min_outer_floor_is_at_least_120():
    assert _MIN_OUTER_LLM_TIMEOUT >= 120.0
