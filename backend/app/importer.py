"""导入流水线：投递去重、冲突识别、附件内容寻址、嵌套邮件递归展开。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import storage, typecheck
from .database import get_conn
from .mime_parser import AttachmentPart, NestedEml, parse_message

PERIODS = ("2026-09", "2026-10", "2026-11")  # 账期候选，前端下拉使用


@dataclass
class FileResult:
    filename: str
    status: str                  # imported | duplicate | conflict | error
    email_id: int | None = None
    message_id: str | None = None
    content_hash: str | None = None
    detail: str = ""
    attachments: int = 0
    nested_emails: int = 0


@dataclass
class BatchResult:
    total: int = 0
    imported: int = 0
    duplicate: int = 0
    conflict: int = 0
    error: int = 0
    files: list[FileResult] = field(default_factory=list)


def get_or_create_channel(conn: sqlite3.Connection, code: str, name: str | None = None) -> int:
    row = conn.execute("SELECT id FROM channel WHERE code=?", (code,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO channel(code, name) VALUES(?,?)", (code, name or code)
    )
    return cur.lastrowid


def _get_or_create_content(conn: sqlite3.Connection, payload: bytes, filename: str) -> dict:
    """附件内容按散列复用；返回 attachment_content 行。"""
    digest = storage.sha256_hex(payload)
    row = conn.execute(
        "SELECT * FROM attachment_content WHERE sha256=?", (digest,)
    ).fetchone()
    if row:
        return row

    is_eml = filename.lower().endswith(".eml")
    result = typecheck.check_eml(payload) if is_eml else typecheck.check_file(filename, payload)
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else None

    blob = storage.store_blob(payload, kind="content", conn=conn)
    cur = conn.execute(
        """INSERT INTO attachment_content
           (blob_id, sha256, size, ext, detected_type, type_check, check_detail)
           VALUES(?,?,?,?,?,?,?)""",
        (blob["id"], digest, len(payload), ext,
         result.detected_type, result.type_check, result.detail),
    )
    return conn.execute(
        "SELECT * FROM attachment_content WHERE id=?", (cur.lastrowid,)
    ).fetchone()


def _record_attachment(conn: sqlite3.Connection, email_id: int, part: AttachmentPart) -> int:
    content = _get_or_create_content(conn, part.payload, part.filename)
    # 同名附件天然各自成行（display_name 相同但 mime_path 不同）
    cur = conn.execute(
        """INSERT INTO attachment
           (email_id, content_id, display_name, is_inline, inline_cid, mime_path,
            nesting_level, layer_label)
           VALUES(?,?,?,?,?,?,?,?)""",
        (email_id, content["id"], part.filename, int(part.is_inline),
         part.inline_cid, part.mime_path, part.nesting_level, part.layer_label),
    )
    att_id = cur.lastrowid
    if content["type_check"] == "mismatch":
        # 异常挂到具体附件行；占位行（content 先建时的 NULL）补登
        conn.execute(
            """INSERT INTO type_anomaly(attachment_id, ext, detected_type, detail)
               VALUES(?,?,?,?)""",
            (att_id, content["ext"], content["detected_type"], content["check_detail"]),
        )
    return att_id


def _record_nesting(conn: sqlite3.Connection, parent_id: int, nested_id: int,
                    nest: NestedEml) -> None:
    exists = conn.execute(
        "SELECT 1 FROM email_nesting WHERE parent_email_id=? AND nested_email_id=? AND mime_path=?",
        (parent_id, nested_id, nest.mime_path),
    ).fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO email_nesting(parent_email_id, nested_email_id, mime_path,
               nesting_level, layer_label, display_name)
               VALUES(?,?,?,?,?,?)""",
            (parent_id, nested_id, nest.mime_path, nest.nesting_level,
             nest.layer_label, nest.filename),
        )


def _insert_email_row(conn: sqlite3.Connection, raw: bytes, parsed, level: int,
                      parent_id: int | None) -> tuple[int, str]:
    digest = storage.sha256_hex(raw)
    existing = conn.execute(
        "SELECT id FROM email WHERE content_hash=?", (digest,)
    ).fetchone()
    if existing:
        return existing["id"], digest
    blob = storage.store_blob(raw, kind="raw", conn=conn)
    cur = conn.execute(
        """INSERT INTO email(message_id, content_hash, from_addr, subject, header_date,
           header_dt, received_dt, raw_blob_id, is_nested, parent_email_id, nesting_level)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (parsed.message_id, digest, parsed.from_addr, parsed.subject,
         parsed.header_date_raw, parsed.header_dt_iso, parsed.received_dt_iso,
         blob["id"], int(level > 0), parent_id, level),
    )
    return cur.lastrowid, digest


def _process_email_contents(conn: sqlite3.Connection, email_id: int, raw: bytes,
                            level: int) -> tuple[int, int]:
    """解析并落库一个邮件层级的附件与嵌套邮件，返回 (附件数, 嵌套数)。

    level 为该邮件在整体转发链中的绝对层级（0=外层），内层邮件解析出的
    附件标签要按绝对层级重写，而不是各自从“外层邮件”重新计数。
    """
    parsed = parse_message(raw)
    label = "外层邮件" if level == 0 else f"转发第{level}层邮件"
    att_count = 0
    for part in parsed.attachments:
        part.nesting_level = level
        part.layer_label = label
        _record_attachment(conn, email_id, part)
        att_count += 1

    nested_count = 0
    for nest in parsed.nested_emls:
        # .eml 本身也作为附件留痕，可单独下载；归属当前层
        eml_part = AttachmentPart(
            filename=nest.filename, payload=nest.payload, is_inline=False,
            inline_cid=None, mime_path=nest.mime_path,
            nesting_level=level, layer_label=label,
            content_type="message/rfc822",
        )
        _record_attachment(conn, email_id, eml_part)
        att_count += 1

        nested_parsed = parse_message(nest.payload)
        nested_id, _ = _insert_email_row(
            conn, nest.payload, nested_parsed, nest.nesting_level, email_id
        )
        _record_nesting(conn, email_id, nested_id, nest)
        sub_att, sub_nested = _process_email_contents(
            conn, nested_id, nest.payload, nest.nesting_level
        )
        nested_count += 1 + sub_nested
        att_count += sub_att

    conn.execute("UPDATE email SET processed=1 WHERE id=?", (email_id,))
    return att_count, nested_count


def import_eml(conn: sqlite3.Connection, raw: bytes, filename: str,
               channel_code: str, billing_period: str) -> FileResult:
    """单个 .eml 的导入入口，在调用方事务内执行。"""
    channel_id = get_or_create_channel(conn, channel_code)

    if not raw:
        return FileResult(filename=filename, status="error",
                          detail="文件为空，无法解析为邮件")

    try:
        parsed = parse_message(raw)
    except Exception as exc:  # noqa: BLE001
        return FileResult(filename=filename, status="error",
                          detail=f"MIME 解析失败: {exc.__class__.__name__}: {exc}")

    digest = storage.sha256_hex(raw)

    # —— 同渠道去重 / 冲突判定 ——
    if parsed.message_id:
        conflict_row = conn.execute(
            """SELECT e.id, e.content_hash FROM email e
               JOIN delivery d ON d.email_id = e.id
               WHERE e.message_id = ? AND d.channel_id = ? AND e.content_hash != ?
               LIMIT 1""",
            (parsed.message_id, channel_id, digest),
        ).fetchone()
        if conflict_row:
            conn.execute(
                """INSERT INTO conflict(channel_id, message_id, existing_email_id,
                   incoming_hash, billing_period, note)
                   VALUES(?,?,?,?,?,?)""",
                (channel_id, parsed.message_id, conflict_row["id"], digest,
                 billing_period, f"来源文件 {filename} 与已收录邮件字节不同"),
            )
            return FileResult(
                filename=filename, status="conflict", message_id=parsed.message_id,
                content_hash=digest,
                detail=f"Message-ID {parsed.message_id} 在该渠道已存在但内容不同，已记入冲突",
            )

    existing_email = conn.execute(
        "SELECT * FROM email WHERE content_hash=?", (digest,)
    ).fetchone()

    if existing_email:
        email_id = existing_email["id"]
        same_channel_delivery = conn.execute(
            "SELECT 1 FROM delivery WHERE channel_id=? AND email_id=? LIMIT 1",
            (channel_id, email_id),
        ).fetchone()
        if same_channel_delivery:
            same_period = conn.execute(
                "SELECT 1 FROM delivery WHERE channel_id=? AND email_id=? AND billing_period=?",
                (channel_id, email_id, billing_period),
            ).fetchone()
            if same_period:
                return FileResult(
                    filename=filename, status="duplicate", email_id=email_id,
                    message_id=parsed.message_id, content_hash=digest,
                    detail="同一渠道、同一 Message-ID/内容散列的重复投递，附件未重复处理",
                )
            conn.execute(
                "INSERT INTO delivery(channel_id, email_id, billing_period) VALUES(?,?,?)",
                (channel_id, email_id, billing_period),
            )
            return FileResult(
                filename=filename, status="duplicate", email_id=email_id,
                message_id=parsed.message_id, content_hash=digest,
                detail=f"重复邮件，新增 {billing_period} 账期投递记录，附件未重复处理",
            )
        # 同样的字节首次走本渠道：补投递；附件通常已处理，未处理则补处理（内容仍只存一份）
        conn.execute(
            "INSERT INTO delivery(channel_id, email_id, billing_period) VALUES(?,?,?)",
            (channel_id, email_id, billing_period),
        )
        att_count = nested_count = 0
        if not existing_email["processed"]:
            att_count, nested_count = _process_email_contents(conn, email_id, raw, 0)
        return FileResult(
            filename=filename, status="imported", email_id=email_id,
            message_id=parsed.message_id, content_hash=digest,
            attachments=att_count, nested_emails=nested_count,
            detail="邮件已存在，新增本渠道投递记录",
        )

    # —— 全新邮件 ——
    email_id, _ = _insert_email_row(conn, raw, parsed, level=0, parent_id=None)
    conn.execute(
        "INSERT INTO delivery(channel_id, email_id, billing_period) VALUES(?,?,?)",
        (channel_id, email_id, billing_period),
    )
    att_count, nested_count = _process_email_contents(conn, email_id, raw, 0)
    return FileResult(
        filename=filename, status="imported", email_id=email_id,
        message_id=parsed.message_id, content_hash=digest,
        attachments=att_count, nested_emails=nested_count,
        detail="新邮件已收录",
    )


def import_batch(files: list[tuple[str, bytes]], channel_code: str,
                 billing_period: str) -> BatchResult:
    """批量导入入口。files 为 (原始文件名, 字节) 列表。"""
    result = BatchResult(total=len(files))
    conn = get_conn()
    try:
        for filename, raw in files:
            fr = import_eml(conn, raw, filename, channel_code, billing_period)
            setattr(result, fr.status, getattr(result, fr.status) + 1)
            result.files.append(fr)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return result
