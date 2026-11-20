"""最小可跑被测系统（SUT）：个人 IP 全链路助手。

交付的是「端到端测试」，但为了让测试真正可跑、可断言数据库状态，
本包自带这个最小实现 + 全部桩服务（见 stubs/）。题目声明依赖为无、
可先用桩或 mock，故此处所有外部依赖均为桩，状态落真实 PostgreSQL。

状态机：
  staging --authorize--> authorized --upload--> uploading --pipeline--> reviewing
    --sensitive-resolved--> reviewing --review approved + ready--> ready
    --confirm--> ready --export--> exported
异常：
  - 未授权上传 -> 409
  - 转写失败重试后 -> failed
  - 存在 pending 敏感标记时进入 ready -> 409
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db
from .config import OUTBOX, ROOT
from stubs import services

app = FastAPI(title="IP E2E SUT", version="1.0.0")


@app.on_event("startup")
def _startup():
    db.init_schema()


# ---------- 请求模型 ----------
class ProjectIn(BaseModel):
    title: str
    transcribe_fail: bool = False
    keep_pending: bool = False


class AuthIn(BaseModel):
    guest_name: str


class ChunksIn(BaseModel):
    count: int = 3
    size: int = 4096


class ReviewIn(BaseModel):
    decision: str = "approved"


def _newid() -> str:
    return str(uuid.uuid4())


def _get_project(c, pid: str):
    row = c.execute("SELECT * FROM project WHERE id=%s", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "project not found")
    cols = [d.name for d in row.cursor.description] if hasattr(row, "cursor") else None
    return row


def _proj(c, pid: str) -> dict:
    r = c.execute(
        "SELECT id,title,status,guest_authorized,transcribe_fail,keep_pending "
        "FROM project WHERE id=%s", (pid,)
    ).fetchone()
    if r is None:
        raise HTTPException(404, "project not found")
    return dict(zip(("id", "title", "status", "guest_authorized", "transcribe_fail", "keep_pending"), r))


# ---------- 主链路接口 ----------
@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn):
    pid = _newid()
    with db.connect() as c:
        c.execute(
            "INSERT INTO project(id,title,transcribe_fail,keep_pending) VALUES(%s,%s,%s,%s)",
            (pid, body.title, body.transcribe_fail, body.keep_pending),
        )
    return {"id": pid, "status": "staging"}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    with db.connect() as c:
        p = _proj(c, pid)
        chunks = c.execute("SELECT count(*) FROM upload_chunk WHERE project_id=%s", (pid,)).fetchone()[0]
        steps = c.execute(
            "SELECT name,status,attempts FROM pipeline_step WHERE project_id=%s ORDER BY name", (pid,)
        ).fetchall()
        artifacts = c.execute("SELECT kind FROM artifact WHERE project_id=%s ORDER BY kind", (pid,)).fetchall()
        sensitive = c.execute("SELECT field,state FROM sensitive_flag WHERE project_id=%s ORDER BY field", (pid,)).fetchall()
        review = c.execute("SELECT decision FROM review WHERE project_id=%s", (pid,)).fetchone()
        confirm = c.execute("SELECT state FROM confirmation WHERE project_id=%s", (pid,)).fetchone()
        exports = c.execute("SELECT kind,path,size FROM export_file WHERE project_id=%s ORDER BY kind", (pid,)).fetchall()
    return {
        **p,
        "chunks": chunks,
        "steps": [dict(zip(("name", "status", "attempts"), s)) for s in steps],
        "artifacts": [a[0] for a in artifacts],
        "sensitive": [dict(zip(("field", "state"), s)) for s in sensitive],
        "review": review[0] if review else None,
        "confirmation": confirm[0] if confirm else None,
        "exports": [dict(zip(("kind", "path", "size"), e)) for e in exports],
        "storage_mode": services.storage_mode(),
        "redis_mode": services.redis_mode(),
    }


@app.post("/api/projects/{pid}/authorization")
def authorize(pid: str, body: AuthIn):
    with db.connect() as c:
        _proj(c, pid)
        c.execute(
            "INSERT INTO guest_authorization(id,project_id,guest_name,authorized) VALUES(%s,%s,%s,TRUE)",
            (_newid(), pid, body.guest_name),
        )
        c.execute("UPDATE project SET guest_authorized=TRUE WHERE id=%s", (pid,))
    return {"guest_authorized": True}


@app.post("/api/projects/{pid}/chunks")
def upload(pid: str, body: ChunksIn):
    with db.connect() as c:
        p = _proj(c, pid)
        # 异常链路 A：授权缺失 -> 409
        if not p["guest_authorized"]:
            raise HTTPException(409, "guest authorization required before upload")
        keys = []
        for i in range(body.count):
            payload = (f"虚构音频分片 {pid} #{i}").encode() + bytes([0]) * body.size
            path = services.store_chunk(pid, i, payload)
            keys.append(path)
            c.execute(
                "INSERT INTO upload_chunk(id,project_id,idx,size,path) VALUES(%s,%s,%s,%s,%s)",
                (_newid(), pid, i, len(payload), path),
            )
        c.execute("UPDATE project SET status='uploading' WHERE id=%s", (pid,))
    return {"status": "uploading", "chunks": body.count, "storage_mode": services.storage_mode(), "keys": keys}


@app.post("/api/projects/{pid}/pipeline/run")
def run_pipeline(pid: str):
    with db.connect() as c:
        p = _proj(c, pid)
        if p["status"] not in ("uploading", "failed"):
            raise HTTPException(409, "pipeline requires uploaded project")
        # 转写步骤：失败则重试 2 次后 failed
        attempts = 0
        last = services.transcribe(pid, p["transcribe_fail"], 1)
        attempts = 1
        if not last["ok"]:
            last = services.transcribe(pid, p["transcribe_fail"], 2)
            attempts = 2
        c.execute(
            "INSERT INTO pipeline_step(id,project_id,name,status,attempts) VALUES(%s,%s,%s,%s,%s)",
            (_newid(), pid, "transcribe", "done" if last["ok"] else "failed", attempts),
        )
        if not last["ok"]:
            # 异常链路 B：转写失败重试后 failed
            c.execute("UPDATE project SET status='failed' WHERE id=%s", (pid,))
            return {"status": "failed", "step": "transcribe", "attempts": attempts}

        # 生成章节/节目介绍/金句/切片
        for kind in ("chapter", "show_notes", "quote_card", "clip_script"):
            content = services.model_generate(kind)
            c.execute(
                "INSERT INTO artifact(id,project_id,kind,content) VALUES(%s,%s,%s,%s)",
                (_newid(), pid, kind, content),
            )
            c.execute(
                "INSERT INTO pipeline_step(id,project_id,name,status,attempts) VALUES(%s,%s,%s,'done',1)",
                (_newid(), pid, f"generate_{kind}"),
            )
        # 敏感标记：两条均初始 pending。"保留某条 pending 不处置"由测试端在处置阶段
        # 跳过对应字段实现（见 test_4_exc_pending_sensitive_blocks_ready_409 跳过 mobile）。
        # project.keep_pending 仅作为虚构夹具的意图标记被记录，不在此处改变初始状态。
        flags = [("guest_name", "虚构嘉宾姓名"), ("mobile", "13800000000")]
        for field, plaintext in flags:
            c.execute(
                "INSERT INTO sensitive_flag(id,project_id,field,state,plaintext) VALUES(%s,%s,%s,%s,%s)",
                (_newid(), pid, field, "pending", plaintext),
            )
        c.execute(
            "INSERT INTO pipeline_step(id,project_id,name,status,attempts) VALUES(%s,%s,'sensitive_scan','done',1)",
            (_newid(), pid),
        )
        c.execute("UPDATE project SET status='reviewing' WHERE id=%s", (pid,))
    return {"status": "reviewing", "artifacts": 4, "sensitive_pending": 2}


@app.post("/api/projects/{pid}/sensitive/{fid}/resolve")
def resolve_sensitive(pid: str, fid: str):
    with db.connect() as c:
        _proj(c, pid)
        r = c.execute(
            "UPDATE sensitive_flag SET state='resolved' WHERE id=%s AND project_id=%s", (fid, pid)
        )
        if r.rowcount == 0:
            raise HTTPException(404, "sensitive flag not found")
    return {"state": "resolved"}


@app.post("/api/projects/{pid}/review/callback")
def review_callback(pid: str, body: ReviewIn):
    with db.connect() as c:
        _proj(c, pid)
        decision = services.review_callback(pid)  # 桩回调固定 approved
        c.execute("INSERT INTO review(id,project_id,decision) VALUES(%s,%s,%s)", (_newid(), pid, decision))
    return {"decision": decision}


@app.post("/api/projects/{pid}/ready")
def mark_ready(pid: str):
    with db.connect() as c:
        p = _proj(c, pid)
        pend = c.execute(
            "SELECT count(*) FROM sensitive_flag WHERE project_id=%s AND state='pending'", (pid,)
        ).fetchone()[0]
        # 异常链路 C：存在 pending 敏感标记 -> 409
        if pend > 0:
            raise HTTPException(409, f"cannot ready: {pend} pending sensitive flag(s)")
        review = c.execute("SELECT decision FROM review WHERE project_id=%s", (pid,)).fetchone()
        if not review or review[0] != "approved":
            raise HTTPException(409, "review not approved")
        c.execute("UPDATE project SET status='ready' WHERE id=%s", (pid,))
    return {"status": "ready"}


@app.post("/api/projects/{pid}/confirmation")
def confirm(pid: str):
    with db.connect() as c:
        p = _proj(c, pid)
        if p["status"] != "ready":
            raise HTTPException(409, "confirmation requires ready project")
        c.execute("INSERT INTO confirmation(id,project_id,state) VALUES(%s,%s,'confirmed')", (_newid(), pid))
    return {"state": "confirmed"}


@app.post("/api/projects/{pid}/export")
def export(pid: str):
    with db.connect() as c:
        p = _proj(c, pid)
        conf = c.execute("SELECT state FROM confirmation WHERE project_id=%s", (pid,)).fetchone()
        if not conf or conf[0] != "confirmed":
            raise HTTPException(409, "export requires confirmed confirmation")
        arts = dict(c.execute("SELECT kind,content FROM artifact WHERE project_id=%s", (pid,)).fetchall())
        d = services.export_dir(pid)

        # md
        md = d / "deliverable.md"
        md.write_text(
            "# 嘉宾确认包（虚构）\n\n" + arts.get("show_notes", "") + "\n\n" +
            "\n".join(arts.get("chapter", "[]").strip("[]").split("},"))[:2000],
            encoding="utf-8",
        )
        # srt
        srt = d / "captions.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n虚构字幕第一行\n\n"
            "2\n00:00:05,000 --> 00:00:10,000\n虚构字幕第二行\n",
            encoding="utf-8",
        )
        # docx（python-docx 真实生成）
        from docx import Document
        doc = Document()
        doc.add_heading("嘉宾确认包（虚构）", 0)
        doc.add_paragraph(arts.get("show_notes", ""))
        for q in ["金句一（虚构）：连接比占有更重要。", "金句二（虚构）：数据要留在客户手里。"]:
            doc.add_paragraph(q, style="List Bullet")
        docx_path = d / "deliverable.docx"
        doc.save(str(docx_path))

        for kind, path in (("md", md), ("srt", srt), ("docx", docx_path)):
            object_key = services.put_export(pid, kind, path)
            c.execute(
                "INSERT INTO export_file(id,project_id,kind,path,size) VALUES(%s,%s,%s,%s,%s)",
                (_newid(), pid, kind, object_key, path.stat().st_size),
            )
        c.execute("UPDATE project SET status='exported' WHERE id=%s", (pid,))
    return {"status": "exported", "files": ["md", "srt", "docx"], "storage_mode": services.storage_mode()}


# ---------- Playwright 页面支撑接口 ----------
@app.get("/api/projects/{pid}/artifacts")
def get_artifacts(pid: str):
    with db.connect() as c:
        _proj(c, pid)
        rows = c.execute("SELECT kind,content FROM artifact WHERE project_id=%s ORDER BY kind", (pid,)).fetchall()
    return [{"kind": r[0], "content": r[1]} for r in rows]


@app.put("/api/projects/{pid}/artifacts/{kind}")
def save_artifact(pid: str, kind: str, body: dict):
    with db.connect() as c:
        _proj(c, pid)
        content = body.get("content", "")
        r = c.execute(
            "UPDATE artifact SET content=%s WHERE project_id=%s AND kind=%s", (content, pid, kind)
        )
        if r.rowcount == 0:
            raise HTTPException(404, "artifact not found")
    return {"saved": True, "kind": kind}


@app.get("/api/projects/{pid}/sensitive")
def get_sensitive(pid: str):
    with db.connect() as c:
        _proj(c, pid)
        rows = c.execute("SELECT id,field,state FROM sensitive_flag WHERE project_id=%s ORDER BY field", (pid,)).fetchall()
    return [{"id": r[0], "field": r[1], "state": r[2]} for r in rows]


WEB_DIR = ROOT / "web"


@app.get("/web/{name}")
def web_page(name: str):
    p = WEB_DIR / name
    if not p.exists() or p.suffix != ".html":
        raise HTTPException(404, "page not found")
    return FileResponse(str(p))
