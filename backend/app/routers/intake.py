"""邮件、附件、异常、冲突的查询与下载路由。"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Response

from ..database import get_conn
from ..storage import read_blob

router = APIRouter(prefix="/api", tags=["intake"])


def _one(conn, sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


def _download_headers(filename: str) -> dict[str, str]:
    # RFC 5987：ASCII 回退名（保留扩展名）+ 中文原名（filename* 优先）
    stem, dot, ext = filename.rpartition(".")
    ascii_stem = (stem if dot else filename).encode("ascii", "ignore").decode().strip()
    ascii_name = (ascii_stem or "download") + (f".{ext}" if dot else "")
    quoted = urllib.parse.quote(filename)
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
        )
    }


# ---------------- 渠道 / 账期 ----------------

@router.get("/channels")
def list_channels():
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT c.*, COUNT(d.id) AS delivery_count
               FROM channel c LEFT JOIN delivery d ON d.channel_id = c.id
               GROUP BY c.id ORDER BY c.id"""
        ).fetchall()
        return rows
    finally:
        conn.close()


# ---------------- 邮件列表 ----------------

@router.get("/emails")
def list_emails(channel: str | None = None, billing_period: str | None = None,
                q: str | None = None, limit: int = 100, offset: int = 0):
    conn = get_conn()
    try:
        where, params = [], []
        if channel:
            where.append("d.channel_id = (SELECT id FROM channel WHERE code=?)")
            params.append(channel)
        if billing_period:
            where.append("d.billing_period = ?")
            params.append(billing_period)
        if q:
            where.append("(e.subject LIKE ? OR e.from_addr LIKE ? OR e.message_id LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        total = conn.execute(
            f"""SELECT COUNT(DISTINCT e.id) AS n FROM email e
                JOIN delivery d ON d.email_id=e.id {where_sql}""", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT e.id, e.message_id, e.content_hash, e.from_addr, e.subject,
                       e.header_date AS header_date_raw, e.header_dt, e.received_dt,
                       e.imported_at, e.is_nested, e.nesting_level,
                       (SELECT GROUP_CONCAT(c.code || ':' || d.billing_period, '|')
                          FROM delivery d JOIN channel c ON c.id=d.channel_id
                         WHERE d.email_id=e.id) AS channel_periods,
                       (SELECT COUNT(*) FROM attachment a WHERE a.email_id=e.id) AS attachment_count
                FROM email e
                JOIN delivery d ON d.email_id=e.id
                {where_sql}
                GROUP BY e.id ORDER BY e.imported_at DESC, e.id DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        return {"total": total, "items": rows}
    finally:
        conn.close()


@router.get("/emails/{email_id}")
def email_detail(email_id: int):
    conn = get_conn()
    try:
        email = _one(conn, "SELECT * FROM email WHERE id=?", (email_id,))
        deliveries = conn.execute(
            """SELECT d.*, c.code AS channel_code, c.name AS channel_name
               FROM delivery d JOIN channel c ON c.id=d.channel_id
               WHERE d.email_id=? ORDER BY d.imported_at""",
            (email_id,),
        ).fetchall()
        attachments = conn.execute(
            """SELECT a.*, ac.sha256 AS content_sha256, ac.size, ac.ext,
                      ac.detected_type, ac.type_check, ac.check_detail,
                      (SELECT COUNT(*) FROM attachment a2
                       WHERE a2.content_id=a.content_id AND a2.email_id!=?) AS other_sources
               FROM attachment a
               JOIN attachment_content ac ON ac.id=a.content_id
               WHERE a.email_id=? ORDER BY a.nesting_level, a.mime_path""",
            (email_id, email_id),
        ).fetchall()
        nested = conn.execute(
            """SELECT n.*, e.message_id, e.subject, e.from_addr, e.header_dt,
                      e.received_dt, e.content_hash
               FROM email_nesting n JOIN email e ON e.id=n.nested_email_id
               WHERE n.parent_email_id=? ORDER BY n.nesting_level""",
            (email_id,),
        ).fetchall()
        # 同内容被哪些邮件引用（重复识别结果）
        shared = conn.execute(
            """SELECT DISTINCT e.id, e.subject, e.from_addr
               FROM attachment a
               JOIN attachment a2 ON a2.content_id=a.content_id
               JOIN email e ON e.id=a2.email_id
               WHERE a.email_id=? AND e.id!=?""",
            (email_id, email_id),
        ).fetchall()
        return {
            "email": email, "deliveries": deliveries,
            "attachments": attachments, "nested_emails": nested,
            "shared_content_sources": shared,
        }
    finally:
        conn.close()


@router.get("/emails/{email_id}/raw")
def download_raw_email(email_id: int):
    conn = get_conn()
    try:
        email = _one(conn, "SELECT * FROM email WHERE id=?", (email_id,))
        if not email["raw_blob_id"]:
            raise HTTPException(404, "原始邮件未留存")
        data = read_blob(email["raw_blob_id"])
        fname = f"email_{email_id}_{email['content_hash'][:12]}.eml"
        return Response(
            content=data, media_type="message/rfc822",
            headers=_download_headers(fname),
        )
    finally:
        conn.close()


# ---------------- 附件 ----------------

@router.get("/attachments")
def list_attachments(only_anomaly: bool = False, inline: bool | None = None,
                     limit: int = 200):
    conn = get_conn()
    try:
        where, params = [], []
        if only_anomaly:
            where.append("ac.type_check='mismatch'")
        if inline is not None:
            where.append("a.is_inline=?")
            params.append(int(inline))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"""SELECT a.id, a.email_id, a.display_name, a.is_inline, a.inline_cid,
                       a.mime_path, a.nesting_level, a.layer_label, a.imported_at,
                       ac.sha256 AS content_sha256, ac.size, ac.ext,
                       ac.detected_type, ac.type_check, ac.check_detail,
                       e.subject AS email_subject, e.from_addr AS email_from,
                       (SELECT COUNT(*) FROM attachment x WHERE x.content_id=a.content_id)
                           AS reference_count
                FROM attachment a
                JOIN attachment_content ac ON ac.id=a.content_id
                JOIN email e ON e.id=a.email_id
                {where_sql}
                ORDER BY a.imported_at DESC, a.id DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return rows
    finally:
        conn.close()


@router.get("/attachments/{attachment_id}")
def attachment_detail(attachment_id: int):
    conn = get_conn()
    try:
        att = _one(
            conn,
            """SELECT a.id AS attachment_id, a.email_id, a.display_name,
                      a.is_inline, a.inline_cid, a.mime_path, a.nesting_level,
                      a.layer_label AS att_layer_label, a.imported_at AS att_imported_at,
                      a.content_id AS content_row_id, ac.sha256 AS content_sha256,
                      ac.size, ac.ext, ac.detected_type, ac.type_check,
                      ac.check_detail, ac.blob_id, b.relpath AS blob_relpath
               FROM attachment a
               JOIN attachment_content ac ON ac.id=a.content_id
               JOIN blob b ON b.id=ac.blob_id
               WHERE a.id=?""",
            (attachment_id,),
        )
        # 来源邮件（含多层：直接所属 + 外层链）
        source_email = conn.execute(
            "SELECT * FROM email WHERE id=?", (att["email_id"],)
        ).fetchone()
        deliveries = conn.execute(
            """SELECT c.code AS channel_code, c.name AS channel_name,
                      GROUP_CONCAT(d.billing_period) AS billing_periods
               FROM delivery d JOIN channel c ON c.id=d.channel_id
               WHERE d.email_id=? GROUP BY c.id""",
            (att["email_id"],),
        ).fetchall()
        # 同一附件内容的全部来源关系（内容共用）
        sources = conn.execute(
            """SELECT a.id AS attachment_id, a.email_id, a.display_name,
                      a.layer_label, e.subject, e.from_addr
               FROM attachment a JOIN email e ON e.id=a.email_id
               WHERE a.content_id=? ORDER BY a.id""",
            (att["content_row_id"],),
        ).fetchall()
        anomalies = conn.execute(
            "SELECT * FROM type_anomaly WHERE attachment_id=?", (attachment_id,)
        ).fetchall()
        return {
            "attachment": att, "source_email": source_email,
            "deliveries": deliveries, "all_sources": sources,
            "anomalies": anomalies,
        }
    finally:
        conn.close()


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int):
    conn = get_conn()
    try:
        att = _one(
            conn,
            """SELECT a.display_name, a.is_inline, ac.blob_id, ac.detected_type
               FROM attachment a JOIN attachment_content ac ON ac.id=a.content_id
               WHERE a.id=?""",
            (attachment_id,),
        )
        data = read_blob(att["blob_id"])
        media = "application/octet-stream"
        if att["detected_type"] in ("png", "jpeg", "gif", "webp"):
            media = f"image/{att['detected_type'].replace('jpeg', 'jpeg')}"
        headers = _download_headers(att["display_name"])
        if att["is_inline"]:
            headers["Content-Disposition"] = headers["Content-Disposition"].replace(
                "attachment;", "inline;")
        return Response(content=data, media_type=media, headers=headers)
    finally:
        conn.close()


# ---------------- 异常与冲突 ----------------

@router.get("/anomalies")
def list_anomalies():
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT t.*, a.display_name, a.email_id, e.subject, e.from_addr
               FROM type_anomaly t
               JOIN attachment a ON a.id=t.attachment_id
               JOIN email e ON e.id=a.email_id
               ORDER BY t.id DESC"""
        ).fetchall()
    finally:
        conn.close()


@router.get("/conflicts")
def list_conflicts():
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT cf.*, c.code AS channel_code,
                      e.subject AS existing_subject, e.from_addr AS existing_from
               FROM conflict cf
               JOIN channel c ON c.id=cf.channel_id
               JOIN email e ON e.id=cf.existing_email_id
               ORDER BY cf.id DESC"""
        ).fetchall()
    finally:
        conn.close()


@router.get("/stats")
def stats():
    conn = get_conn()
    try:
        def scalar(sql):
            return conn.execute(sql).fetchone()["n"]
        return {
            "emails": scalar("SELECT COUNT(*) n FROM email"),
            "top_level_emails": scalar("SELECT COUNT(*) n FROM email WHERE is_nested=0"),
            "nested_emails": scalar("SELECT COUNT(*) n FROM email WHERE is_nested=1"),
            "deliveries": scalar("SELECT COUNT(*) n FROM delivery"),
            "attachments": scalar("SELECT COUNT(*) n FROM attachment"),
            "unique_contents": scalar("SELECT COUNT(*) n FROM attachment_content"),
            "anomalies": scalar("SELECT COUNT(*) n FROM type_anomaly"),
            "conflicts": scalar("SELECT COUNT(*) n FROM conflict"),
            "inline_images": scalar("SELECT COUNT(*) n FROM attachment WHERE is_inline=1"),
        }
    finally:
        conn.close()
