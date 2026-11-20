"""验收标准 1 + 2：主链路（上传到导出）+ 3 条异常链路。

每步同时断言接口返回与数据库状态；导出文件真实落盘并校验存在。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fixtures.fabricated import make_project_payload, make_auth_payload
from tests.conftest import step
from app import db


def _create(client, **overrides):
    r = client.post("/api/projects", json=make_project_payload(**overrides))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _authorize_upload_pipeline(client, pid):
    assert step(client, pid, "authorization", make_auth_payload()).status_code == 200
    up = step(client, pid, "chunks", {"count": 3, "size": 128})
    assert up.status_code == 200 and up.json()["chunks"] == 3
    pl = step(client, pid, "pipeline/run")
    assert pl.status_code == 200, pl.text
    return pl.json()


def test_1_main_flow_upload_to_export(client):
    """验收1：主链路从上传到导出全部通过，导出的 md/docx/srt 三种文件存在。"""
    pid = _create(client)
    result = _authorize_upload_pipeline(client, pid)
    assert result["status"] == "reviewing", result

    # 每一步的数据库状态断言
    with db.connect() as c:
        assert c.execute("SELECT status FROM project WHERE id=%s", (pid,)).fetchone()[0] == "reviewing"
        assert c.execute("SELECT count(*) FROM upload_chunk WHERE project_id=%s", (pid,)).fetchone()[0] == 3
        assert c.execute("SELECT count(*) FROM artifact WHERE project_id=%s", (pid,)).fetchone()[0] == 4
        steps = c.execute("SELECT status FROM pipeline_step WHERE project_id=%s", (pid,)).fetchall()
        assert all(s[0] == "done" for s in steps), steps
        flags = c.execute("SELECT id FROM sensitive_flag WHERE project_id=%s", (pid,)).fetchall()
        assert len(flags) == 2

    # 敏感标记全部处置
    for (fid,) in flags:
        r = step(client, pid, f"sensitive/{fid}/resolve")
        assert r.status_code == 200 and r.json()["state"] == "resolved"

    # 复核桩回调 approved -> ready -> 确认包 confirmed
    assert step(client, pid, "review/callback", {"decision": "approved"}).json()["decision"] == "approved"
    assert step(client, pid, "ready").json()["status"] == "ready"
    assert step(client, pid, "confirmation").json()["state"] == "confirmed"

    # 分片确实落进存储（MinIO 模式 stat_object / 桩模式文件存在）
    from stubs import services
    with db.connect() as c:
        chunk_keys = [r[0] for r in c.execute(
            "SELECT path FROM upload_chunk WHERE project_id=%s ORDER BY idx", (pid,)).fetchall()]
    assert all(services.chunk_exists(k) for k in chunk_keys), chunk_keys

    # 导出 3 种文件
    ex = step(client, pid, "export")
    assert ex.status_code == 200 and ex.json()["status"] == "exported", ex.text
    with db.connect() as c:
        exports = c.execute("SELECT kind,path,size FROM export_file WHERE project_id=%s", (pid,)).fetchall()
    kinds = {e[0] for e in exports}
    assert kinds == {"md", "srt", "docx"}, kinds
    for kind, object_key, size in exports:
        assert services.export_exists(object_key), f"导出文件不存在于存储: {object_key}"
        assert len(services.export_bytes(object_key)) == size and size > 0
    # docx 是真实 OOXML（zip 头）
    docx_key = [k for kd, k, _ in exports if kd == "docx"][0]
    assert services.export_bytes(docx_key)[:2] == b"PK"

    # 把三种导出物落到 evidence/exports 作为可核对 artifact（CI 会上传整个 evidence/）
    ev = ROOT / "evidence" / "exports"
    ev.mkdir(parents=True, exist_ok=True)
    for kind, object_key, _ in exports:
        suffix = {"md": ".md", "srt": ".srt", "docx": ".docx"}[kind]
        (ev / f"deliverable{suffix}").write_bytes(services.export_bytes(object_key))
    print(f"\n[EXPORT-ARTIFACT] {sorted(p.name for p in ev.iterdir())} storage={services.storage_mode()}", flush=True)


def test_2_exc_missing_authorization_409(client):
    """异常链路 A：授权缺失时上传被 409 拦截，项目状态仍为 staging。"""
    pid = _create(client)
    up = step(client, pid, "chunks", {"count": 3, "size": 64})
    assert up.status_code == 409, up.text
    assert "authorization" in up.json()["detail"].lower()
    with db.connect() as c:
        st = c.execute("SELECT status FROM project WHERE id=%s", (pid,)).fetchone()[0]
        assert st == "staging"
        assert c.execute("SELECT count(*) FROM upload_chunk WHERE project_id=%s", (pid,)).fetchone()[0] == 0


def test_3_exc_transcribe_fail_retry_then_failed(client):
    """异常链路 B：转写失败，重试 2 次后进入 failed。"""
    pid = _create(client, transcribe_fail=True)
    _ = step(client, pid, "authorization", make_auth_payload())
    _ = step(client, pid, "chunks", {"count": 1, "size": 32})
    pl = step(client, pid, "pipeline/run")
    assert pl.status_code == 200 and pl.json()["status"] == "failed", pl.text
    assert pl.json()["attempts"] == 2
    with db.connect() as c:
        assert c.execute("SELECT status FROM project WHERE id=%s", (pid,)).fetchone()[0] == "failed"
        row = c.execute(
            "SELECT status,attempts FROM pipeline_step WHERE project_id=%s AND name='transcribe'", (pid,)
        ).fetchone()
        assert row == ("failed", 2), row


def test_4_exc_pending_sensitive_blocks_ready_409(client):
    """异常链路 C：存在 pending 敏感标记时无法进入 ready。"""
    pid = _create(client, keep_pending=True)
    _authorize_upload_pipeline(client, pid)
    # 只处置部分敏感标记，保留一个 pending
    with db.connect() as c:
        flags = c.execute("SELECT id,field FROM sensitive_flag WHERE project_id=%s", (pid,)).fetchall()
    for fid, field in flags:
        if field != "mobile":
            assert step(client, pid, f"sensitive/{fid}/resolve").status_code == 200
    assert step(client, pid, "review/callback", {"decision": "approved"}).status_code == 200
    ready = step(client, pid, "ready")
    assert ready.status_code == 409, ready.text
    assert "pending" in ready.json()["detail"].lower()
    with db.connect() as c:
        assert c.execute("SELECT status FROM project WHERE id=%s", (pid,)).fetchone()[0] == "reviewing"
        pend = c.execute(
            "SELECT count(*) FROM sensitive_flag WHERE project_id=%s AND state='pending'", (pid,)
        ).fetchone()[0]
        assert pend == 1
