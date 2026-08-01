import asyncio

import pytest

from wallbreaker.executions import ExecutionManager


@pytest.mark.asyncio
async def test_execution_lifecycle_and_resumable_events():
    manager = ExecutionManager()

    async def runner(ctx):
        ctx.emit("progress", text="one")
        await asyncio.sleep(0)
        ctx.emit("progress", text="two")
        return {"ok": True}

    execution = manager.create("demo", {}, runner)
    await execution.task
    assert execution.status == "succeeded"
    events, terminal = await manager.events_after(execution.id, 3)
    assert [event.data.get("text") for event in events if event.type == "progress"] == ["two"]
    assert terminal is True


@pytest.mark.asyncio
async def test_pause_steer_resume_at_checkpoint():
    manager = ExecutionManager()
    reached = asyncio.Event()

    async def runner(ctx):
        reached.set()
        await asyncio.sleep(0.02)
        await ctx.checkpoint()
        return {"feedback": ctx.drain_feedback()}

    execution = manager.create("demo", {}, runner, mode="interactive")
    await reached.wait()
    manager.pause(execution.id)
    manager.steer(execution.id, "pivot")
    for _ in range(20):
        if execution.status == "paused":
            break
        await asyncio.sleep(0.01)
    assert execution.status == "paused"
    manager.resume(execution.id)
    await execution.task
    assert execution.result == {"feedback": ["pivot"]}


@pytest.mark.asyncio
async def test_hard_cancel_reaches_terminal_state():
    manager = ExecutionManager()
    started = asyncio.Event()

    async def runner(_ctx):
        started.set()
        await asyncio.Event().wait()

    execution = manager.create("demo", {}, runner)
    await started.wait()
    manager.cancel(execution.id)
    await execution.task
    assert execution.status == "cancelled"
    assert execution.events[-1].data["state"] == "cancelled"


@pytest.mark.asyncio
async def test_interactive_executions_queue_serially():
    manager = ExecutionManager()
    release = asyncio.Event()
    order = []

    async def first(_ctx):
        order.append("first-start")
        await release.wait()
        order.append("first-end")

    async def second(_ctx):
        order.append("second-start")

    one = manager.create("one", {}, first, mode="interactive")
    two = manager.create("two", {}, second, mode="interactive")
    await asyncio.sleep(0.02)
    assert order == ["first-start"]
    assert two.status == "queued"
    release.set()
    await asyncio.gather(one.task, two.task)
    assert order == ["first-start", "first-end", "second-start"]
