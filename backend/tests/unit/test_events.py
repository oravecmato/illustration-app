"""Unit tests for SSE event bus (§11.1)."""

import pytest

from app.orchestrator.events import EventBus


@pytest.mark.asyncio
async def test_snapshot_emitted_first_to_new_subscriber():
    bus = EventBus()
    snapshot_data = {"run": {"status": "RUNNING"}, "illustrations": []}
    bus.set_snapshot(snapshot_data)

    queue = bus.subscribe()

    # First event should be snapshot
    event = queue.get_nowait()
    assert event["type"] == "snapshot"
    assert event["data"] == snapshot_data


@pytest.mark.asyncio
async def test_events_broadcast_to_multiple_subscribers():
    bus = EventBus()
    bus.set_snapshot({})

    q1 = bus.subscribe()
    q2 = bus.subscribe()

    # Drain snapshots
    q1.get_nowait()
    q2.get_nowait()

    await bus.publish("illustration_state", {"scene_index": 0, "state": "RENDERING"})

    e1 = q1.get_nowait()
    e2 = q2.get_nowait()

    assert e1["type"] == "illustration_state"
    assert e2["type"] == "illustration_state"
    assert e1["data"] == e2["data"]


@pytest.mark.asyncio
async def test_stream_closes_on_run_completed():
    bus = EventBus()
    bus.set_snapshot({})
    q = bus.subscribe()
    q.get_nowait()  # drain snapshot

    await bus.publish("run_completed", {"completed": 3, "failed": 0})

    # Terminal event should be in queue
    event = q.get_nowait()
    assert event["type"] == "run_completed"


@pytest.mark.asyncio
async def test_stream_closes_on_run_failed():
    bus = EventBus()
    bus.set_snapshot({})
    q = bus.subscribe()
    q.get_nowait()

    await bus.publish("run_failed", {"error_message": "Something went wrong"})
    event = q.get_nowait()
    assert event["type"] == "run_failed"


@pytest.mark.asyncio
async def test_stream_closes_on_run_cancelled():
    bus = EventBus()
    bus.set_snapshot({})
    q = bus.subscribe()
    q.get_nowait()

    await bus.publish("run_cancelled", {})
    event = q.get_nowait()
    assert event["type"] == "run_cancelled"


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    bus.set_snapshot({})
    q = bus.subscribe()
    q.get_nowait()

    bus.unsubscribe(q)

    await bus.publish("illustration_state", {"state": "RENDERING"})
    assert q.empty()
