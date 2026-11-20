"""数据库层：真实 PostgreSQL，显式 DDL，测试前可 reset。"""
from __future__ import annotations

import psycopg
from psycopg.errors import DuplicateDatabase

from .config import ADMIN_DSN, DB_NAME, PG_DSN

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staging',
    guest_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    transcribe_fail BOOLEAN NOT NULL DEFAULT FALSE,
    keep_pending BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS guest_authorization (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    guest_name TEXT NOT NULL,
    authorized BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS upload_chunk (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    idx INTEGER NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pipeline_step (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS artifact (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    kind TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sensitive_flag (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    field TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    plaintext TEXT
);
CREATE TABLE IF NOT EXISTS review (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    decision TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS confirmation (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    state TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS export_file (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL
);
"""


def connect():
    return psycopg.connect(PG_DSN, autocommit=True)


def ensure_database() -> None:
    """若目标库不存在则创建（独立实例，不碰任何现有库）。"""
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
            try:
                c.execute(f"CREATE DATABASE {DB_NAME}")
            except DuplicateDatabase:
                pass
    except Exception:
        # 若权限受限，假定库已存在
        pass


def reset_schema() -> None:
    """清空并重建 public schema（每个 E2E 测试前调用，保证隔离可重复）。"""
    with connect() as c:
        c.execute("DROP SCHEMA IF EXISTS public CASCADE")
        c.execute("CREATE SCHEMA public")
        c.execute(SCHEMA_SQL)


def init_schema() -> None:
    ensure_database()
    with connect() as c:
        c.execute(SCHEMA_SQL)
