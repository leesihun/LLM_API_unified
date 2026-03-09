"""
Streaming proxy agent.
Forwards all requests to the upstream LLM API server and streams responses back.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from proxy_agent.config import UPSTREAM_HOST, UPSTREAM_PORT

app = FastAPI(title="LLM API Proxy")

# Standard hop-by-hop headers that must not be forwarded
HOP_BY_HOP = {
    "connection", "keep-alive", "transfer-encoding", "te",
    "trailer", "proxy-authorization", "proxy-authenticate",
    "upgrade",
}

client = httpx.AsyncClient(timeout=None)


def _filter_headers(headers: httpx.Headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


async def _stream_and_close(upstream: httpx.Response):
    try:
        async for chunk in upstream.aiter_bytes():
            yield chunk
    finally:
        await upstream.aclose()


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy(request: Request, path: str):
    upstream_url = f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}/{path}"

    if request.url.query:
        upstream_url += f"?{request.url.query}"

    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    }

    body = await request.body()

    req = client.build_request(
        method=request.method,
        url=upstream_url,
        headers=forward_headers,
        content=body,
    )

    upstream = await client.send(req, stream=True)

    return StreamingResponse(
        _stream_and_close(upstream),
        status_code=upstream.status_code,
        headers=_filter_headers(upstream.headers),
    )
