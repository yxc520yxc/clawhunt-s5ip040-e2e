# -*- coding: utf-8 -*-
"""一键复跑全部验收，真实 stdout 写入 RUN_LOG.txt。

流程：建库 -> pytest tests/e2e (4 条) -> pytest tests/playwright (4 条)
      -> 汇总计数与总耗时 -> RUN_LOG.txt / SUMMARY.txt。
依赖：真实 PostgreSQL（E2E_PG_DSN）、Playwright Edge 浏览器。
用法：run_all.py  或  verify.cmd
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)

LOG: list[str] = []


def _run(label: str, cmd: list[str]) -> int:
    LOG.append(f"$ {' '.join(cmd)}")
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=str(ROOT), env=os.environ.copy(), capture_output=True, text=True)
    dt = time.perf_counter() - t0
    LOG.append(f"[{label} exit={p.returncode} elapsed={dt:.2f}s]")
    if p.stdout.strip():
        LOG.append("--- stdout ---\n" + p.stdout.rstrip())
    if p.stderr.strip():
        LOG.append("--- stderr ---\n" + p.stderr.rstrip())
    LOG.append("")
    return p.returncode, dt


def main() -> int:
    import psycopg
    from app import db

    from stubs import services
    dsn = os.environ.get("E2E_PG_DSN", "postgresql://postgres@127.0.0.1:55439/e2e2380")
    LOG.append("ENV Python=" + sys.version.split()[0])
    LOG.append("ENV PG_DSN=" + dsn.replace(":" + "postgres" + "@", ":****@"))
    LOG.append(f"ENV storage_mode={services.storage_mode()}  redis_mode={services.redis_mode()}")
    try:
        c = psycopg.connect(os.environ.get("E2E_PG_ADMIN_DSN", "postgresql://postgres@127.0.0.1:55439/postgres"),
                            autocommit=True, connect_timeout=5)
        LOG.append("ENV PG=" + c.execute("select version()").fetchone()[0][:60])
        c.close()
    except Exception as e:
        LOG.append("ENV PG connect FAILED: " + str(e)[:200])
    LOG.append("")

    db.ensure_database()
    LOG.append("$ ensure_database(e2e2380) [ok]\n")

    t0 = time.perf_counter()
    rc1, d1 = _run("E2E-API", [sys.executable, "-m", "pytest", "-v", "-s", "tests/e2e/"])
    rc2, d2 = _run("E2E-PLAYWRIGHT", [sys.executable, "-m", "pytest", "-v", "-s", "tests/playwright/"])
    total = time.perf_counter() - t0

    # 验收汇总
    checks = [
        ("验收1 主链路上传→导出+3文件存在", rc1 == 0),
        ("验收2 3条异常链路状态码/状态断言", rc1 == 0),
        ("验收3 Playwright 3页面用例+报告", rc2 == 0),
        ("验收4 整套E2E耗时<=15分钟", total <= 900),
    ]
    LOG.append("=== SUMMARY ===")
    for name, ok in checks:
        LOG.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
    LOG.append(f"TOTAL_SECONDS={total:.2f} (API={d1:.2f}s BROWSER={d2:.2f}s)  LIMIT=900s")
    failed = [n for n, ok in checks if not ok]
    LOG.append(f"RESULT: {len(checks)-len(failed)}/{len(checks)} checks passed; failed={failed}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = "\n".join(LOG)
    (ROOT / "RUN_LOG.txt").write_text(text, encoding="utf-8")
    (EVIDENCE / f"RUN_LOG_{ts}.txt").write_text(text, encoding="utf-8")
    (ROOT / "SUMMARY.txt").write_text(text[text.find("=== SUMMARY ==="):], encoding="utf-8")
    print(text[text.find("=== SUMMARY ==="):])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
