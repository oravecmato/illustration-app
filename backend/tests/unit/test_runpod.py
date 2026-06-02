"""Unit tests for RunPod client (§11.1) with HTTP mocked via respx."""

import base64

import httpx
import pytest
import respx

from app.services.runpod import (
    RunPodClient,
    RunPodError,
    RunPodQueueTimeoutError,
    RunPodTimeoutError,
)

ENDPOINT_ID = "test-endpoint-123"
API_KEY = "test-api-key"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()


@pytest.fixture
def client():
    return RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout_in_queue=1.0,
        poll_timeout_in_progress=1.0,
    )


@pytest.mark.asyncio
@respx.mock
async def test_run_returns_job_id(client):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": "job-abc-123"}))
    respx.get(f"{BASE_URL}/status/job-abc-123").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                },
            },
        )
    )
    result = await client.run_workflow({"node": "workflow"})
    assert isinstance(result, bytes)
    assert result[:4] == b"\x89PNG"


@pytest.mark.asyncio
@respx.mock
async def test_status_polled_until_completed(client):
    job_id = "job-polling"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    # First call returns IN_QUEUE, second returns COMPLETED
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        side_effect=[
            httpx.Response(200, json={"status": "IN_QUEUE"}),
            httpx.Response(200, json={"status": "IN_PROGRESS"}),
            httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "output": {
                        "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                    },
                },
            ),
        ]
    )
    result = await client.run_workflow({"node": "workflow"})
    assert isinstance(result, bytes)


@pytest.mark.asyncio
@respx.mock
async def test_timeout_raises_error():
    client = RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout_in_queue=10.0,
        poll_timeout_in_progress=0.05,  # Very short IN_PROGRESS timeout
    )
    job_id = "job-timeout"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "IN_PROGRESS"})
    )
    with pytest.raises(RunPodTimeoutError):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_failed_status_raises_error(client):
    job_id = "job-failed"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "FAILED", "error": "OOM"})
    )
    with pytest.raises(RunPodError):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_cancelled_status_raises_error(client):
    job_id = "job-cancelled"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "CANCELLED"})
    )
    with pytest.raises(RunPodError):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_in_queue_timeout_raises_queue_timeout_error():
    """IN_QUEUE budget exhaustion must surface RunPodQueueTimeoutError so the
    branch's no-retry logic kicks in (re-submitting loses FIFO position)."""
    client = RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout_in_queue=0.05,
        poll_timeout_in_progress=10.0,
    )
    job_id = "job-stuck-queue"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "IN_QUEUE"})
    )
    with pytest.raises(RunPodQueueTimeoutError):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_in_queue_does_not_burn_in_progress_budget():
    """A long IN_QUEUE wait must NOT consume the IN_PROGRESS budget — the two
    timers are independent so an idle queue doesn't pre-fail a future render."""
    client = RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout_in_queue=10.0,
        poll_timeout_in_progress=0.05,
    )
    job_id = "job-queue-then-done"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    # 10 IN_QUEUE polls (~0.10s, well over the 0.05s IN_PROGRESS budget)
    # then COMPLETED — must NOT raise RunPodTimeoutError.
    queue_responses = [httpx.Response(200, json={"status": "IN_QUEUE"}) for _ in range(10)]
    completed = httpx.Response(
        200,
        json={
            "status": "COMPLETED",
            "output": {"images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]},
        },
    )
    respx.get(f"{BASE_URL}/status/{job_id}").mock(side_effect=[*queue_responses, completed])
    result = await client.run_workflow({"node": "workflow"})
    assert isinstance(result, bytes)


@pytest.mark.asyncio
@respx.mock
async def test_on_job_id_fires_before_polling(client):
    """The on_job_id callback must fire as soon as /run returns, BEFORE the
    poll loop starts — so the orchestrator can persist the id for orphan
    recovery even if the process dies during the first poll iteration."""
    job_id = "job-callback-order"
    events: list[str] = []

    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))

    def _record_status_call(_request):
        events.append("status")
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                },
            },
        )

    respx.get(f"{BASE_URL}/status/{job_id}").mock(side_effect=_record_status_call)

    async def on_job_id(jid: str) -> None:
        events.append(f"job_id:{jid}")

    await client.run_workflow({"node": "workflow"}, on_job_id=on_job_id)
    assert events[0] == f"job_id:{job_id}"
    assert "status" in events
    assert events.index(f"job_id:{job_id}") < events.index("status")


@pytest.mark.asyncio
@respx.mock
async def test_on_status_change_emits_distinct_transitions(client):
    """on_status_change fires once per *transition* (including the first
    observation), so the SSE label flips IN_QUEUE → IN_PROGRESS exactly once."""
    job_id = "job-transitions"
    statuses: list[str] = []

    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        side_effect=[
            httpx.Response(200, json={"status": "IN_QUEUE"}),
            httpx.Response(200, json={"status": "IN_QUEUE"}),
            httpx.Response(200, json={"status": "IN_PROGRESS"}),
            httpx.Response(200, json={"status": "IN_PROGRESS"}),
            httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "output": {
                        "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                    },
                },
            ),
        ]
    )

    async def on_status(s: str) -> None:
        statuses.append(s)

    await client.run_workflow({"node": "workflow"}, on_status_change=on_status)
    assert statuses == ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]


@pytest.mark.asyncio
@respx.mock
async def test_poll_existing_job_resumes_completed(client):
    """The orphan resumer uses poll_existing_job to reattach to a job whose
    poll loop was killed by a uvicorn restart. A COMPLETED job recovers bytes
    on the first poll."""
    job_id = "job-orphan-completed"
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                },
            },
        )
    )
    result = await client.poll_existing_job(job_id)
    assert isinstance(result, bytes)
    assert result[:4] == b"\x89PNG"


@pytest.mark.asyncio
@respx.mock
async def test_get_status_one_shot(client):
    """get_status() is the orphan resumer's classification probe — single
    fetch, no polling, returns the raw payload so the resumer can branch on
    status without committing to the long poll."""
    job_id = "job-probe"
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "IN_QUEUE"})
    )
    data = await client.get_status(job_id)
    assert data == {"status": "IN_QUEUE"}
