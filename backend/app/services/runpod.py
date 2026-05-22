"""RunPod Serverless ComfyUI client."""

import asyncio
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodError(Exception):
    pass


class RunPodClient:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        poll_interval: float = 3.0,
        poll_timeout: float = 600.0,
    ):
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def run_workflow(self, workflow: dict) -> bytes:
        """Submit a ComfyUI workflow and poll until completion. Returns image bytes."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            job_id = await self._submit(client, workflow)
            return await self._poll(client, job_id)

    async def _submit(self, client: httpx.AsyncClient, workflow: dict) -> str:
        response = await client.post(
            f"{self._base_url}/run",
            json={"input": {"workflow": workflow}},
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["id"]

    async def _poll(self, client: httpx.AsyncClient, job_id: str) -> bytes:
        elapsed = 0.0
        while elapsed < self.poll_timeout:
            response = await client.get(
                f"{self._base_url}/status/{job_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "COMPLETED":
                return self._extract_image(data)
            if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                error = data.get("error", status)
                raise RunPodError(f"RunPod job {job_id} ended with status {status}: {error}")

            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval

        raise RunPodError(f"RunPod job {job_id} timed out after {self.poll_timeout}s")

    def _extract_image(self, data: dict) -> bytes:
        images = data.get("output", {}).get("images", [])
        if not images:
            raise RunPodError("RunPod response has no images in output")
        first = images[0]
        if first.get("type") == "base64":
            return base64.b64decode(first["data"])
        raise RunPodError(f"Unsupported image type: {first.get('type')}")
