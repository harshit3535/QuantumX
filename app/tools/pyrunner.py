"""Optional Python runner for the UI "Run" button. OFF by default (ENABLE_CODE_EXECUTION=false).

This is NOT a real sandbox. It only limits time, memory and environment. Do not
enable it on a public deployment unless you accept that risk.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from ..config import settings


def _limits() -> None:                                 # runs in the child before exec (POSIX only)
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (settings.code_exec_timeout, settings.code_exec_timeout))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    except Exception:
        pass


async def run_python(code: str) -> dict:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return {"status": "error", "error": f"SyntaxError on line {exc.lineno}: {exc.msg}"}
    with tempfile.TemporaryDirectory(prefix="nexus_run_") as td:
        path = Path(td) / "main.py"
        path.write_text(code, encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"}          # no API keys leak into user code
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(path), cwd=td, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limits if os.name == "posix" else None,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.code_exec_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"status": "error", "error": f"Timed out after {settings.code_exec_timeout}s"}
        return {"status": "success" if proc.returncode == 0 else "error", "stdout": out.decode(errors="replace")[-4000:],
                "stderr": err.decode(errors="replace")[-4000:], "returncode": proc.returncode}
