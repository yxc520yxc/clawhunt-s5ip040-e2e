"""桩服务：模型网关 / 复核队列 / 本地转写 / 对象存储（MinIO 或本地目录）。

全部返回固定虚构响应，保证 E2E 可重复；不含任何真实个人信息，不引入向境外发送数据的 SDK。

对象存储双模式：
- 设 MINIO_ENDPOINT -> 用 minio SDK 真写 MinIO分片与导出（CI/Docker Compose 栈）
- 未设 -> 本地目录桩（本机无 Docker 复跑）
Redis 双模式：
- 设 REDIS_URL -> 复核队列真写 Redis（CI/Docker Compose 栈）
- 未设 -> fakeredis 内存桩（本机）
两种模式下接口契约一致，测试可据 storage_mode() 断言真实后端被使用。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import (
    MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECURE,
    MINIO_SECRET_KEY, REDIS_URL, OUTBOX,
)

# ---------- 模型网关桩：固定虚构响应 ----------
FIXTURE_CHAPTERS = [
    {"title": "第一章 · 从场地到连接", "body": "这是一段虚构的章节正文，用于端到端测试。"},
    {"title": "第二章 · 会员数据的价值", "body": "另一段虚构正文，内容固定可重复。"},
]
FIXTURE_SHOW_NOTES = "本期节目介绍（虚构）：聚焦会员空间如何升级为产业资源连接平台。"
FIXTURE_QUOTE_CARDS = ["金句一（虚构）：连接比占有更重要。", "金句二（虚构）：数据要留在客户手里。"]
FIXTURE_CLIP_SCRIPTS = ["切片脚本一（虚构）：30 秒讲清会员中台。"]


def model_generate(kind: str) -> str:
    """模型网关桩：按 kind 返回固定虚构内容（JSON 字符串）。"""
    import json
    mapping = {
        "chapter": FIXTURE_CHAPTERS,
        "show_notes": FIXTURE_SHOW_NOTES,
        "quote_card": FIXTURE_QUOTE_CARDS,
        "clip_script": FIXTURE_CLIP_SCRIPTS,
    }
    return json.dumps(mapping[kind], ensure_ascii=False)


# ---------- 本地转写桩 ----------
def transcribe(project_id: str, should_fail: bool, attempt: int) -> dict:
    """本地转写桩：should_fail=True 时始终失败，用于异常链路。"""
    if should_fail:
        return {"ok": False, "attempt": attempt, "error": "transcribe_stub_forced_failure"}
    digest = hashlib.sha256(f"{project_id}:audio".encode()).hexdigest()[:16]
    return {"ok": True, "attempt": attempt, "transcript": f"虚构转写文本 {digest}"}


# ---------- 复核队列：Redis（真实或 fakeredis 桩） ----------
_redis_conn = None


def _redis():
    global _redis_conn
    if _redis_conn is None:
        if REDIS_URL:
            import redis
            _redis_conn = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        else:
            import fakeredis
            _redis_conn = fakeredis.FakeRedis(decode_responses=True)
    return _redis_conn


def redis_mode() -> str:
    return "real-redis" if REDIS_URL else "fakeredis-stub"


def review_callback(project_id: str) -> str:
    """复核桩：回调固定 approved，并把复核决策写入 Redis 队列（真实或桩）。"""
    r = _redis()
    r.rpush("e2e:review:queue", f"{project_id}:approved")
    r.set(f"e2e:review:{project_id}", "approved")
    return "approved"


def review_queue_len() -> int:
    """供测试断言 Redis 队列确实被写入（真实后端与桩后端一致）。"""
    return int(_redis().llen("e2e:review:queue"))


# ---------- 对象存储：MinIO（真实）或本地目录（桩） ----------
_minio_client = None


def _minio():
    global _minio_client
    if _minio_client is None:
        from minio import Minio
        endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        _minio_client = Minio(
            endpoint,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        if not _minio_client.bucket_exists(MINIO_BUCKET):
            _minio_client.make_bucket(MINIO_BUCKET)
    return _minio_client


def storage_mode() -> str:
    return "minio" if MINIO_ENDPOINT else "local-stub"


def _ensure_bucket():
    if MINIO_ENDPOINT:
        _minio()


def store_chunk(project_id: str, idx: int, payload: bytes) -> str:
    """分片上传：MinIO 模式真写对象存储；桩模式写本地目录。返回可用于断言的 object key/路径。"""
    name = f"chunks/{project_id}/part-{idx:03d}.bin"
    if MINIO_ENDPOINT:
        import io
        _minio().put_object(MINIO_BUCKET, name, io.BytesIO(payload), len(payload))
        return name
    d = OUTBOX / "chunks" / project_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"part-{idx:03d}.bin"
    p.write_bytes(payload)
    return f"chunks/{project_id}/part-{idx:03d}.bin"


def chunk_exists(key: str) -> bool:
    """供测试断言分片确实落进存储（MinIO stat_object / 本地文件存在）。"""
    if MINIO_ENDPOINT:
        try:
            _minio().stat_object(MINIO_BUCKET, key)
            return True
        except Exception:
            return False
    return (OUTBOX / key).exists()


def export_dir(project_id: str) -> Path:
    """返回导出目录。MinIO 模式下仍写本地临时目录，随后由 export 上传到 MinIO。"""
    d = OUTBOX / "exports" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def put_export(project_id: str, kind: str, local_path: Path) -> str:
    """导出文件落存储：MinIO 模式真传对象；桩模式仅保留本地文件。返回 object key。"""
    key = f"exports/{project_id}/{local_path.name}"
    if MINIO_ENDPOINT:
        _minio().fput_object(MINIO_BUCKET, key, str(local_path))
    return key


def export_exists(key: str) -> bool:
    """供测试断言导出文件确实落进存储（MinIO stat_object / 本地文件存在）。"""
    if MINIO_ENDPOINT:
        try:
            _minio().stat_object(MINIO_BUCKET, key)
            return True
        except Exception:
            return False
    return (OUTBOX / key).exists()


def export_bytes(key: str) -> bytes:
    """供测试读取导出物内容（MinIO get_object / 本地读取），用于校验 docx PK 头。"""
    import io
    if MINIO_ENDPOINT:
        resp = _minio().get_object(MINIO_BUCKET, key)
        return resp.read()
    return (OUTBOX / key).read_bytes()
