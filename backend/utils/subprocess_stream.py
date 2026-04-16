"""
Asynchronous subprocess execution with incremental output streaming.

Shared helper used by the Python-runner tools (code_exec, python_coder native,
python_coder opencode) so they all stream stdout/stderr chunk-by-chunk with a
shared memory cap. Keeps the writing process unblocked by continuing to read
past the cap (excess bytes are dropped, not stored).
"""
import asyncio
from dataclasses import dataclass

_READ_CHUNK = 4096


@dataclass
class StreamResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


async def _drain_into(
    stream: asyncio.StreamReader,
    buf: bytearray,
    max_bytes: int,
) -> None:
    """Drain *stream* into *buf*, capping stored bytes at max_bytes.

    Keeps reading past the cap so the writing process never blocks on a full
    pipe. Excess bytes are dropped. Appends a single "[truncated]" marker.
    """
    truncated = False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            return
        if truncated:
            continue
        room = max_bytes - len(buf)
        if room > 0:
            buf.extend(chunk[:room])
        if len(buf) >= max_bytes and not truncated:
            buf.extend(b"\n...[truncated]")
            truncated = True


async def run_streaming(
    program: str,
    args: list[str],
    cwd: str,
    timeout: int,
    max_output_size: int,
) -> StreamResult:
    """Run a program asynchronously, streaming both stdout and stderr.

    On timeout the process is killed and whatever was streamed up to that
    point is returned (timed_out=True, returncode=-1). Raises for
    subprocess-start errors — the caller decides how to handle those.
    """
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    stdout_task = asyncio.create_task(_drain_into(proc.stdout, stdout_buf, max_output_size))
    stderr_task = asyncio.create_task(_drain_into(proc.stderr, stderr_buf, max_output_size))

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        return StreamResult(
            stdout=bytes(stdout_buf).decode('utf-8', errors='replace'),
            stderr=bytes(stderr_buf).decode('utf-8', errors='replace'),
            returncode=-1,
            timed_out=True,
        )

    await asyncio.gather(stdout_task, stderr_task)
    return StreamResult(
        stdout=bytes(stdout_buf).decode('utf-8', errors='replace'),
        stderr=bytes(stderr_buf).decode('utf-8', errors='replace'),
        returncode=proc.returncode if proc.returncode is not None else -1,
    )
