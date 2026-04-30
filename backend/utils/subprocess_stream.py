"""
Asynchronous subprocess execution with incremental output streaming.

Shared helper used by the Python-runner tools (code_exec, python_coder native,
python_coder opencode) so they all stream stdout/stderr chunk-by-chunk with a
shared memory cap. Keeps the writing process unblocked by continuing to read
past the cap (excess bytes are dropped, not stored).

Two optional kill triggers (beyond normal exit):
  - wall-clock timeout  : process runs longer than `timeout` seconds total.
                          Disabled when `timeout` is None or <= 0.
  - idle-stdout timeout : process produces no stdout for `idle_timeout` seconds
                          (catches hangs that produce no output).
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional

_READ_CHUNK = 4096


@dataclass
class StreamResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    idle_killed: bool = False   # True when killed for stdout silence, not wall-clock


async def _drain_into(
    stream: asyncio.StreamReader,
    buf: bytearray,
    max_bytes: int,
) -> None:
    """Drain *stream* into *buf*, capping stored bytes at max_bytes."""
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


async def _drain_tracking(
    stream: asyncio.StreamReader,
    buf: bytearray,
    max_bytes: int,
    last_seen: list,  # single-element list used as mutable float ref
) -> None:
    """Like _drain_into but updates last_seen[0] on every received chunk."""
    truncated = False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            return
        last_seen[0] = asyncio.get_running_loop().time()
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
    timeout: Optional[int],
    max_output_size: int,
    idle_timeout: Optional[int] = None,
) -> StreamResult:
    """Run a program asynchronously, streaming both stdout and stderr.

    Killed when either the wall-clock `timeout` expires OR `idle_timeout`
    seconds pass with no new stdout bytes (whichever fires first). Pass
    timeout=None or timeout<=0 to disable the wall-clock kill trigger.
    Returns whatever was streamed up to that point (timed_out=True).
    """
    proc = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    loop = asyncio.get_running_loop()
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    last_stdout = [loop.time()]  # updated by _drain_tracking

    stdout_task = asyncio.create_task(
        _drain_tracking(proc.stdout, stdout_buf, max_output_size, last_stdout)
    )
    stderr_task = asyncio.create_task(
        _drain_into(proc.stderr, stderr_buf, max_output_size)
    )

    proc_task = asyncio.create_task(proc.wait())
    deadline = None if timeout is None or timeout <= 0 else loop.time() + timeout

    def _decode():
        return (
            bytes(stdout_buf).decode('utf-8', errors='replace'),
            bytes(stderr_buf).decode('utf-8', errors='replace'),
        )

    async def _kill_and_drain(idle: bool) -> StreamResult:
        proc_task.cancel()
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        out, err = _decode()
        return StreamResult(
            stdout=out, stderr=err,
            returncode=-1, timed_out=True, idle_killed=idle,
        )

    # Poll every second; check both kill conditions.
    while not proc_task.done():
        done, _ = await asyncio.wait({proc_task}, timeout=1.0)
        if proc_task in done:
            break
        now = loop.time()
        if deadline is not None and now >= deadline:
            return await _kill_and_drain(idle=False)
        if idle_timeout is not None and (now - last_stdout[0]) >= idle_timeout:
            return await _kill_and_drain(idle=True)

    await asyncio.gather(stdout_task, stderr_task)
    out, err = _decode()
    return StreamResult(
        stdout=out,
        stderr=err,
        returncode=proc.returncode if proc.returncode is not None else -1,
    )
