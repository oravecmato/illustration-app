"""RunPod Serverless ComfyUI client."""

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.constants import (
    COMFYUI_POLL_INTERVAL_S,
    RUNPOD_POLL_TIMEOUT_IN_PROGRESS_S,
    RUNPOD_POLL_TIMEOUT_IN_QUEUE_S,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodError(Exception):
    pass


class RunPodTimeoutError(RunPodError):
    """Render timed out while the worker was running.

    The job was actively IN_PROGRESS (or the remote returned ``TIMED_OUT``)
    when the local IN_PROGRESS budget ran out. Callers should retry with a
    fresh seed — the workflow is fine, the worker stalled.
    """

    pass


class RunPodQueueTimeoutError(RunPodError):
    """Render never left the IN_QUEUE state within the queue budget.

    The GPU pool was fully throttled for the entire queue budget. Callers
    MUST NOT retry — re-submitting would lose the FIFO position and just
    re-queue behind every other tenant. Surface to the user as a hard
    capacity failure; refund quota as infra noise.
    """

    pass


# Type for the optional callback fired exactly once per ``run_workflow``
# call as soon as RunPod returns the job_id from ``/run``. Used by the
# orchestrator to persist the id BEFORE the long poll begins, so a process
# restart mid-poll can resume by re-polling the existing job.
JobIdCallback = Callable[[str], Awaitable[None]]

# Type for the optional callback fired whenever the observed RunPod status
# changes during the poll loop. Used to publish SSE events so the UI can
# label "v rade" vs "vytváranie obrázka". Status string is the raw RunPod
# value ("IN_QUEUE", "IN_PROGRESS", etc.).
StatusCallback = Callable[[str], Awaitable[None]]


class RunPodClient:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        poll_interval: float = float(COMFYUI_POLL_INTERVAL_S),
        poll_timeout_in_queue: float = float(RUNPOD_POLL_TIMEOUT_IN_QUEUE_S),
        poll_timeout_in_progress: float = float(RUNPOD_POLL_TIMEOUT_IN_PROGRESS_S),
    ):
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.poll_interval = poll_interval
        self.poll_timeout_in_queue = poll_timeout_in_queue
        self.poll_timeout_in_progress = poll_timeout_in_progress
        self._base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def run_workflow(
        self,
        workflow: dict,
        *,
        on_job_id: JobIdCallback | None = None,
        on_status_change: StatusCallback | None = None,
    ) -> bytes:
        """Submit a ComfyUI workflow and poll until completion.

        ``on_job_id`` fires once, right after ``/run`` returns the job id,
        before the long poll begins. Persist the id here so a process
        restart can resume polling instead of orphaning a paid render.

        ``on_status_change`` fires whenever the observed RunPod status
        changes (e.g. IN_QUEUE → IN_PROGRESS). Use to surface queue
        position to the UI via SSE.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            job_id = await self._submit(client, workflow)
            if on_job_id is not None:
                await on_job_id(job_id)
            return await self.poll_existing_job(
                job_id, client=client, on_status_change=on_status_change
            )

    async def poll_existing_job(
        self,
        job_id: str,
        *,
        client: httpx.AsyncClient | None = None,
        on_status_change: StatusCallback | None = None,
    ) -> bytes:
        """Poll an already-submitted RunPod job.

        Used by the orphan resumer in ``app/main.py`` to reattach to a
        job whose poll loop was killed by a process restart. Reuses the
        same status-aware timeout logic so a recovered job behaves
        identically to a freshly submitted one from the budgeting POV.
        """
        if client is None:
            async with httpx.AsyncClient(timeout=30.0) as c:
                return await self._poll(c, job_id, on_status_change=on_status_change)
        return await self._poll(client, job_id, on_status_change=on_status_change)

    async def get_status(self, job_id: str) -> dict[str, Any]:
        """One-shot status fetch (no polling). For orphan inspection."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self._base_url}/status/{job_id}", headers=self._headers)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def extract_image(data: dict) -> bytes:
        """Public helper: pull image bytes out of a /status response.

        Exposed so the orphan resumer can convert a COMPLETED job into
        bytes without re-polling.
        """
        return RunPodClient._extract_image(data)

    async def _submit(self, client: httpx.AsyncClient, workflow: dict) -> str:
        response = await client.post(
            f"{self._base_url}/run",
            json={"input": {"workflow": workflow}},
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["id"]

    async def _poll(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        *,
        on_status_change: StatusCallback | None = None,
    ) -> bytes:
        # Track time-in-status separately so IN_QUEUE waits don't burn
        # the IN_PROGRESS budget and vice versa. The first poll establishes
        # the initial status; transitions reset the per-status timer.
        time_in_queue = 0.0
        time_in_progress = 0.0
        last_status: str | None = None

        while True:
            response = await client.get(
                f"{self._base_url}/status/{job_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            # Surface status transitions to the caller. Fire on the very
            # first observation too so the UI can label immediately.
            if status != last_status and on_status_change is not None and status:
                try:
                    await on_status_change(status)
                except Exception:  # pragma: no cover — never let a UI hook break the poll
                    logger.exception("on_status_change callback failed")
            last_status = status

            if status == "COMPLETED":
                return self._extract_image(data)
            if status == "TIMED_OUT":
                error = data.get("error", status)
                raise RunPodTimeoutError(
                    f"RunPod job {job_id} ended with status TIMED_OUT: {error}"
                )
            if status in ("FAILED", "CANCELLED"):
                error = data.get("error", status)
                raise RunPodError(f"RunPod job {job_id} ended with status {status}: {error}")

            # Per-status budget enforcement. Anything that isn't an explicit
            # IN_PROGRESS is treated as queueing for the purposes of the
            # budget (RunPod also emits transient states like ``IN_QUEUE``
            # and occasional empty/unknown values while a worker is being
            # assigned). Only IN_PROGRESS is unambiguously "worker running".
            if status == "IN_PROGRESS":
                time_in_progress += self.poll_interval
                if time_in_progress >= self.poll_timeout_in_progress:
                    raise RunPodTimeoutError(
                        f"RunPod job {job_id} IN_PROGRESS for "
                        f"{self.poll_timeout_in_progress}s without completing"
                    )
            else:
                time_in_queue += self.poll_interval
                if time_in_queue >= self.poll_timeout_in_queue:
                    raise RunPodQueueTimeoutError(
                        f"RunPod job {job_id} stuck IN_QUEUE for "
                        f"{self.poll_timeout_in_queue}s — pool throttled"
                    )

            await asyncio.sleep(self.poll_interval)

    @staticmethod
    def _extract_image(data: dict) -> bytes:
        images = data.get("output", {}).get("images", [])
        if not images:
            raise RunPodError("RunPod response has no images in output")
        first = images[0]
        if first.get("type") == "base64":
            return base64.b64decode(first["data"])
        raise RunPodError(f"Unsupported image type: {first.get('type')}")
