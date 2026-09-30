"""Safe, real-world read-only tools used by Astra's operator agent.

The v2.7 operator layer deliberately starts with read-only actions that are safe to
run in a public hackathon deployment: public web search and public URL diagnostics.
No arbitrary shell, filesystem writes, deployments, or credentialed mutations live here.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx

from ..errors import NetworkError
try:
    from ..agents.web_agent import search_web
except Exception:  # pragma: no cover - import is resolved normally
    search_web = None

DEFAULT_TIMEOUT = 8.0
MAX_BODY = 200_000


def _public_url(url: str) -> tuple[str, str]:
    value = url.strip()
    if not value:
        raise ValueError("A URL is required")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http:// or https:// URLs are supported")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise NetworkError(f"Could not resolve {host}") from exc
    addresses = {info[4][0] for info in infos}
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Private or local network targets are blocked")
    return value, host


def _title(html: str) -> str:
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()[:180] if m else ""


async def check_url(url: str) -> dict:
    target, host = await asyncio.to_thread(_public_url, url)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True, headers={"User-Agent": "Astra/2.7 public diagnostic"}) as client:
            try:
                response = await client.get(target, headers={"Range": "bytes=0-199999"})
            except httpx.HTTPError as exc:
                raise NetworkError(f"Could not reach {host} ({type(exc).__name__})") from exc
    finally:
        elapsed = int((time.monotonic() - started) * 1000)
    text = response.text[:MAX_BODY] if response.content else ""
    return {
        "url": target,
        "final_url": str(response.url),
        "hostname": host,
        "reachable": True,
        "status_code": response.status_code,
        "status_class": f"{response.status_code // 100}xx",
        "latency_ms": elapsed,
        "content_type": response.headers.get("content-type", ""),
        "title": _title(text),
        "server": response.headers.get("server", ""),
    }


async def run_public_search(query: str) -> dict:
    if search_web is None:
        raise NetworkError("Web search is unavailable")
    results = await search_web(query)
    return {"query": query, "results": results}
