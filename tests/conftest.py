"""E2E conftest：启动真实 uvicorn 服务（真实 HTTP 端口），
每个用例前 reset 真实 PG schema，保证端到端、隔离、可重复。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]  # delivery-2380-v1
sys.path.insert(0, str(ROOT))

PY = sys.executable


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session", autouse=True)
def server():
    from app import db
    db.ensure_database()
    port = _free_port()
    env = os.environ.copy()
    env["E2E_PG_DSN"] = os.environ.get("E2E_PG_DSN", "postgresql://postgres@127.0.0.1:55439/e2e2380")
    env["E2E_PG_ADMIN_DSN"] = os.environ.get("E2E_PG_ADMIN_DSN", "postgresql://postgres@127.0.0.1:55439/postgres")
    log = open(str(ROOT / "evidence" / "uvicorn-server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            r = httpx.get(base + "/openapi.json", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("uvicorn failed to start: " + (ROOT / "evidence" / "uvicorn-server.log").read_text(encoding="utf-8")[-1500:])
    setattr(server, "base", base)
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(autouse=True)
def clean_db():
    from app import db
    db.reset_schema()
    yield


@pytest.fixture
def client(server):
    with httpx.Client(base_url=server, timeout=30) as c:
        yield c


def step(c: httpx.Client, pid: str, suffix: str, json=None):
    return c.post(f"/api/projects/{pid}/{suffix}", json=json)


# 逐用例名可读输出：RUN_LOG / CI 日志里能看到每条用例名 + PASS/FAIL，而非只有 "N passed" 汇总。
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        status = "PASS" if rep.passed else ("FAIL" if rep.failed else "SKIP")
        print(f"\n[CASE] {item.nodeid} -> {status}", flush=True)
