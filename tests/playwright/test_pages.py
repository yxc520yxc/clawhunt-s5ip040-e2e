"""验收标准 3：Playwright 3 个关键页面用例（新建项目 / 校对保存 / 敏感处置）。
用真实浏览器操作真实页面与真实后端，生成 HTML 运行报告。

浏览器 channel 由环境变量 PW_CHANNEL 决定：
  - 未设置 -> 使用 Playwright 自带的 chromium（CI / Docker 中 playwright install chromium 已装）
  - PW_CHANNEL=msedge -> 使用本机 Microsoft Edge（本机一键复跑 verify.cmd 默认设此项）
这样 CI/self-hosted 无 Edge 的环境默认可跑，本机仍可用 Edge。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

RESULTS: list[dict] = []
# 默认 chromium；设 PW_CHANNEL=msedge 时改用本机 Edge
PW_CHANNEL = os.environ.get("PW_CHANNEL", "").strip() or None
BROWSER_LABEL = f"channel={PW_CHANNEL}" if PW_CHANNEL else "bundled chromium"


def _write_report():
    """会话末写出 HTML 报告（独立交付物，不计入 pytest 用例数）。"""
    ok_all = all(r["ok"] for r in RESULTS) and len(RESULTS) == 3
    rows = "".join(
        f"<tr><td>{r['name']}</td><td>{'PASS' if r['ok'] else 'FAIL'}</td>"
        f"<td>{r['detail']}</td><td>{r['ts']}</td></tr>" for r in RESULTS
    )
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>S5-IP-040 Playwright 运行报告</title>
<style>body{{font:15px/1.6 -apple-system,Segoe UI,sans-serif;max-width:900px;margin:40px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}
h1{{color:#1b1f24}} .ok{{color:#0a7f3f;font-weight:bold}}</style></head><body>
<h1>Playwright 页面用例运行报告（3 个页面用例）</h1>
<p>浏览器：Playwright chromium（{BROWSER_LABEL}，headless） · 页面由真实 uvicorn 服务承载 · 数据落真实 PostgreSQL。</p>
<p>结论：<span class="ok">{'3/3 PASS' if ok_all else '存在失败'}</span>（本报告由 pytest 会话 teardown 生成，不计入用例数）</p>
<table><tr><th>用例</th><th>结果</th><th>证据</th><th>时间</th></tr>{rows}</table>
</body></html>"""
    (ROOT / "evidence" / "playwright-report.html").write_text(html, encoding="utf-8")


@pytest.fixture(scope="module", autouse=True)
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel=PW_CHANNEL, headless=True)
        yield b
        b.close()
    # 3 个页面用例全部执行完后写报告，不作为 pytest 用例
    _write_report()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def _record(name: str, ok: bool, detail: str = ""):
    RESULTS.append({"name": name, "ok": ok, "detail": detail, "ts": time.strftime("%H:%M:%S")})


def _seed_project_with_pipeline(base: str, keep_pending: bool = False):
    """通过 API 准备一个已 pipeline、带敏感标记的项目，供页面用例使用。"""
    import httpx
    with httpx.Client(base_url=base, timeout=30) as c:
        pid = c.post("/api/projects", json={
            "title": "虚构 · Playwright 页面用例", "transcribe_fail": False, "keep_pending": keep_pending
        }).json()["id"]
        c.post(f"/api/projects/{pid}/authorization", json={"guest_name": "虚构嘉宾"})
        c.post(f"/api/projects/{pid}/chunks", json={"count": 2, "size": 64})
        c.post(f"/api/projects/{pid}/pipeline/run")
    return pid


def test_pw_1_new_project(page, server):
    """页面用例1：新建项目——填标题、点创建、断言返回 id 与 status=staging。"""
    t0 = time.time()
    page.goto(server + "/web/new.html", wait_until="networkidle")
    page.fill('[data-testid=title]', "虚构节目 · Playwright 新建")
    page.click('[data-testid=submit]')
    page.wait_for_selector('[data-testid=status]')
    status = page.inner_text('[data-testid=status]')
    pid = page.inner_text('[data-testid=pid]')
    ok = status == "staging" and len(pid) >= 8
    _record("新建项目页", ok, f"status={status}, pid={pid[:8]}…, {time.time()-t0:.2f}s")
    assert ok, f"status={status}, pid={pid}"


def test_pw_2_proofread_save(page, server):
    """页面用例2：校对保存——加载章节内容、编辑、保存，断言页面 saved 且 DB 内容更新。"""
    t0 = time.time()
    pid = _seed_project_with_pipeline(server)
    page.goto(server + "/web/proofread.html", wait_until="networkidle")
    page.fill('[data-testid=pid]', pid)
    page.click('[data-testid=load]')
    page.wait_for_selector('[data-testid=content]')
    new_text = "虚构正文 · Playwright 校对保存后的内容"
    page.fill('[data-testid=content]', new_text)
    page.click('[data-testid=save]')
    page.wait_for_selector('[data-testid=msg]')
    msg = page.inner_text('[data-testid=msg]')
    # 校验后端确实保存
    import httpx
    with httpx.Client(base_url=server, timeout=30) as c:
        arts = c.get(f"/api/projects/{pid}/artifacts").json()
    saved = any(a["content"] == new_text for a in arts)
    ok = "saved" in msg and saved
    _record("校对保存页", ok, f"msg={msg}, db_updated={saved}, {time.time()-t0:.2f}s")
    assert ok, f"msg={msg}, saved={saved}"


def test_pw_3_sensitive_resolve(page, server):
    """页面用例3：敏感处置——加载 pending 标记、点处置，断言状态变 resolved 且 DB 更新。"""
    t0 = time.time()
    pid = _seed_project_with_pipeline(server)
    page.goto(server + "/web/sensitive.html", wait_until="networkidle")
    page.fill('[data-testid=pid]', pid)
    page.click('[data-testid=load]')
    page.wait_for_selector('[data-testid=flag]')
    before = page.locator('[data-testid=flag][data-state=pending]').count()
    btn = page.locator('[data-testid=resolve]').first
    btn.click()
    # 等页面重新渲染后 pending 计数下降（避免固定 sleep 造成 flaky）
    page.wait_for_function(
        "n => document.querySelectorAll('[data-testid=flag][data-state=pending]').length === n",
        arg=before - 1, timeout=8000,
    )
    after = page.locator('[data-testid=flag][data-state=pending]').count()
    import httpx
    with httpx.Client(base_url=server, timeout=30) as c:
        flags = c.get(f"/api/projects/{pid}/sensitive").json()
    resolved = sum(1 for f in flags if f["state"] == "resolved")
    ok = before >= 1 and after == before - 1 and resolved >= 1
    _record("敏感处置页", ok, f"pending {before}->{after}, db_resolved={resolved}, {time.time()-t0:.2f}s")
    assert ok, f"before={before} after={after} resolved={resolved}"
