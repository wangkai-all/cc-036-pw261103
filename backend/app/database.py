"""SQLite 连接与建表。表结构围绕六类事实：

渠道 channel -> 投递 delivery -> 邮件 email -> 附件 attachment -> 内容 content
另有 conflict 记录同 Message-ID 不同内容的冲突。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS channel (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS email (
    id              INTEGER PRIMARY KEY,
    message_id      TEXT,                    -- 邮件头 Message-ID，缺失为 NULL
    content_hash    TEXT NOT NULL UNIQUE,    -- 原始字节 sha256（顶层为上传字节，嵌套为重编码字节）
    from_addr       TEXT NOT NULL,
    subject         TEXT,
    header_date     TEXT,                    -- 邮件头 Date 声明的发送时间（原始值）
    header_dt       TEXT,                    -- 解析后的发送时间（ISO，UTC）
    received_dt     TEXT,                    -- 可信接收时间（Received 链推算，无则 NULL，绝不以 header_dt 代替）
    raw_blob_id     INTEGER REFERENCES blob(id),
    is_nested       INTEGER NOT NULL DEFAULT 0,
    parent_email_id INTEGER REFERENCES email(id),
    nesting_level   INTEGER NOT NULL DEFAULT 0,
    processed       INTEGER NOT NULL DEFAULT 0,  -- 附件/嵌套是否已展开处理
    imported_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_email_message_id ON email(message_id);
CREATE INDEX IF NOT EXISTS idx_email_parent ON email(parent_email_id);

CREATE TABLE IF NOT EXISTS delivery (
    id          INTEGER PRIMARY KEY,
    channel_id  INTEGER NOT NULL REFERENCES channel(id),
    email_id    INTEGER NOT NULL REFERENCES email(id),
    billing_period TEXT NOT NULL,           -- 账期，格式 YYYY-MM
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(channel_id, email_id, billing_period)
);
CREATE INDEX IF NOT EXISTS idx_delivery_email ON delivery(email_id);
CREATE INDEX IF NOT EXISTS idx_delivery_period ON delivery(billing_period);

CREATE TABLE IF NOT EXISTS conflict (
    id               INTEGER PRIMARY KEY,
    channel_id       INTEGER NOT NULL REFERENCES channel(id),
    message_id       TEXT NOT NULL,
    existing_email_id INTEGER NOT NULL REFERENCES email(id),
    incoming_hash    TEXT NOT NULL,
    billing_period   TEXT NOT NULL,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_conflict_mid ON conflict(message_id);

CREATE TABLE IF NOT EXISTS blob (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT NOT NULL UNIQUE,
    size        INTEGER NOT NULL,
    kind        TEXT NOT NULL,              -- 'raw' | 'content'
    relpath     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- 附件内容：按字节散列去重，不同邮件的同一附件共用一行
CREATE TABLE IF NOT EXISTS attachment_content (
    id          INTEGER PRIMARY KEY,
    blob_id     INTEGER NOT NULL REFERENCES blob(id),
    sha256      TEXT NOT NULL UNIQUE,
    size        INTEGER NOT NULL,
    ext         TEXT,                       -- 声明扩展名（小写、无点）
    detected_type TEXT NOT NULL,            -- 按文件特征识别出的真实类型
    type_check  TEXT NOT NULL,              -- 'ok' | 'mismatch'
    check_detail TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS attachment (
    id            INTEGER PRIMARY KEY,
    email_id      INTEGER NOT NULL REFERENCES email(id),
    content_id    INTEGER NOT NULL REFERENCES attachment_content(id),
    display_name  TEXT NOT NULL,            -- 展示用原文件名（中文原名）
    is_inline     INTEGER NOT NULL DEFAULT 0,
    inline_cid    TEXT,                     -- 内嵌图的 Content-ID
    mime_path     TEXT NOT NULL,            -- MIME 树路径，如 1/2/0
    nesting_level INTEGER NOT NULL DEFAULT 0,
    layer_label   TEXT NOT NULL,            -- 所属邮件层说明，如“外层邮件”“转发第1层”
    imported_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_att_email ON attachment(email_id);
CREATE INDEX IF NOT EXISTS idx_att_content ON attachment(content_id);

-- 外层邮件与其中嵌套 .eml 的展开关系（同一嵌套邮件可被多封外层邮件引用）
CREATE TABLE IF NOT EXISTS email_nesting (
    id              INTEGER PRIMARY KEY,
    parent_email_id INTEGER NOT NULL REFERENCES email(id),
    nested_email_id INTEGER NOT NULL REFERENCES email(id),
    mime_path       TEXT NOT NULL,
    nesting_level   INTEGER NOT NULL,
    layer_label     TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    UNIQUE(parent_email_id, nested_email_id, mime_path)
);
CREATE INDEX IF NOT EXISTS idx_nesting_parent ON email_nesting(parent_email_id);

CREATE TABLE IF NOT EXISTS type_anomaly (
    id            INTEGER PRIMARY KEY,
    attachment_id INTEGER NOT NULL REFERENCES attachment(id),
    ext           TEXT,
    detected_type TEXT NOT NULL,
    detail        TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""


def dict_factory(cur: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cur.description)}


def get_conn() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(SCHEMA)
