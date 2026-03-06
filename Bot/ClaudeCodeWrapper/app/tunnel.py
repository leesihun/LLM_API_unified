from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


class CloudflareTunnel:
    """Manages a cloudflared quick-tunnel subprocess."""

    def __init__(self, cmd: str, local_url: str):
        self._cmd = cmd
        self._local_url = local_url
        self._process: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task | None = None
        self.public_url: str | None = None

    async def start(self, timeout: float = 30.0) -> str:
        """Start cloudflared and return the public tunnel URL."""
        logger.info(f"Starting cloudflare tunnel to {self._local_url} ...")
        self._process = await asyncio.create_subprocess_exec(
            self._cmd, "tunnel", "--url", self._local_url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self.public_url = await self._read_url(timeout)
        self._drain_task = asyncio.create_task(self._drain_stderr())
        logger.info(f"Tunnel active: {self.public_url}")
        return self.public_url

    async def _read_url(self, timeout: float) -> str:
        """Read stderr lines until the tunnel URL appears."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise RuntimeError(
                    f"Timed out waiting for cloudflared tunnel URL ({timeout}s)"
                )
            line = await asyncio.wait_for(
                self._process.stderr.readline(), timeout=remaining
            )
            if not line:
                raise RuntimeError("cloudflared exited before providing a tunnel URL")
            text = line.decode().strip()
            logger.debug(f"cloudflared: {text}")
            match = URL_PATTERN.search(text)
            if match:
                return match.group(0)

    async def _drain_stderr(self) -> None:
        """Keep reading stderr so the pipe buffer doesn't fill up."""
        while self._process and self._process.returncode is None:
            line = await self._process.stderr.readline()
            if not line:
                break
            logger.debug(f"cloudflared: {line.decode().strip()}")

    async def stop(self) -> None:
        if self._drain_task:
            self._drain_task.cancel()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            logger.info("Cloudflare tunnel stopped")
