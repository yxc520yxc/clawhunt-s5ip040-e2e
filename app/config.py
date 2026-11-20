"""配置：全部从环境变量读取。

两种运行模式：
- 本机 verify.cmd（无 Docker）：PG 独立实例 55439，对象存储用本地目录桩，Redis 用 fakeredis 内存桩。
- CI / Docker Compose 栈：E2E_PG_DSN 指向 PG service；MINIO_ENDPOINT 指向 MinIO service，
  对象存储走真实 MinIO SDK；REDIS_URL 指向 Redis service，Redis 真实接入。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTBOX = ROOT / "fixtures" / "outbox"

PG_DSN = os.environ.get("E2E_PG_DSN", "postgresql://postgres@127.0.0.1:55439/e2e2380")
ADMIN_DSN = os.environ.get("E2E_PG_ADMIN_DSN", "postgresql://postgres@127.0.0.1:55439/postgres")
DB_NAME = "e2e2380"

# 对象存储：设置 MINIO_ENDPOINT 走真实 MinIO（CI/Docker），否则本地目录桩（本机）
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "").strip()
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "e2euser")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "e2epassword123")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "e2e-2380")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "0") == "1"

# Redis：设置 REDIS_URL 走真实 Redis（CI/Docker），否则 fakeredis 内存桩（本机）
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
