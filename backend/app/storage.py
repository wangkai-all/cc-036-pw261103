"""内容寻址存储：同一份字节只落盘一次，内部编号入库，原文件名不参与路径。"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from . import config
from .database import get_conn


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sharded_path(root: Path, digest: str) -> Path:
    # 两级分桶，避免单目录文件过多
    return root / digest[:2] / digest[2:4] / digest


def store_blob(data: bytes, kind: str,
               conn: sqlite3.Connection | None = None) -> dict:
    """写入一个内容寻址 blob。已存在则直接复用。返回 blob 行（含 id、relpath）。

    传入 conn 时复用调用方事务；否则自开连接（独立提交）。
    """
    digest = sha256_hex(data)
    root = config.RAW_DIR if kind == "raw" else config.CONTENT_DIR
    abs_path = _sharded_path(root, digest)
    relpath = str(abs_path.relative_to(config.BLOB_DIR))

    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM blob WHERE sha256=?", (digest,)).fetchone()
        if row is not None:
            return row
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if not abs_path.exists():
            tmp = abs_path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(abs_path)
        cur = conn.execute(
            "INSERT INTO blob(sha256, size, kind, relpath) VALUES(?,?,?,?)",
            (digest, len(data), kind, relpath),
        )
        if own_conn:
            conn.commit()
        return conn.execute("SELECT * FROM blob WHERE id=?", (cur.lastrowid,)).fetchone()
    finally:
        if own_conn:
            conn.close()


def read_blob(blob_id: int) -> bytes:
    conn = get_conn()
    try:
        row = conn.execute("SELECT relpath FROM blob WHERE id=?", (blob_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise FileNotFoundError(f"blob {blob_id}")
    return (config.BLOB_DIR / row["relpath"]).read_bytes()
