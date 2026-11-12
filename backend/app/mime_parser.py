"""MIME 解析：递归遍历邮件层级，提取附件、内嵌图片与嵌套转发的 .eml。

设计要点：
- 只用标准库 email；中文文件名靠 RFC 2231/2047 解码（policy.default 处理）。
- 每个部件带 MIME 树路径（1/2/0），附件记录所属邮件层。
- 接收时间只取 Received 头链中可验证的时间；取不到一律 None，绝不用 Date 代替。
"""
from __future__ import annotations

import base64
import email
import email.utils
import quopri
from dataclasses import dataclass, field
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage, MIMEPart


@dataclass
class AttachmentPart:
    filename: str
    payload: bytes
    is_inline: bool
    inline_cid: str | None
    mime_path: str
    nesting_level: int
    layer_label: str
    content_type: str


@dataclass
class ParsedEmail:
    message_id: str | None
    from_addr: str
    subject: str
    header_date_raw: str | None     # Date 头原始声明
    header_dt_iso: str | None       # 解析后的发送时间
    received_dt_iso: str | None     # 可信接收时间，无则 None
    body_text: str
    body_html: str | None
    attachments: list[AttachmentPart] = field(default_factory=list)
    nested_emls: list["NestedEml"] = field(default_factory=list)


@dataclass
class NestedEml:
    filename: str
    payload: bytes
    mime_path: str
    nesting_level: int
    layer_label: str


def _layer_label(level: int) -> str:
    if level == 0:
        return "外层邮件"
    return f"转发第{level}层邮件"


def parse_message(raw: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=policy.default)
    if not isinstance(msg, EmailMessage):  # 极端坏数据时 message_from_bytes 返回 Message
        raise ValueError("无法解析为 EmailMessage")
    return _parse(msg, level=0)


def _parse(msg: EmailMessage, level: int) -> ParsedEmail:
    message_id = _clean_header(msg.get("Message-ID"))
    from_addr = _format_sender(msg)
    subject = msg.get("Subject", "") or ""
    date_raw = msg.get("Date")
    header_dt = None
    if date_raw:
        dt = email.utils.parsedate_to_datetime(date_raw)
        if dt is not None:
            header_dt = dt.astimezone().isoformat() if dt.tzinfo else dt.isoformat()

    parsed = ParsedEmail(
        message_id=message_id,
        from_addr=from_addr,
        subject=str(subject),
        header_date_raw=date_raw,
        header_dt_iso=header_dt,
        received_dt_iso=_extract_received_dt(msg),
        body_text="",
        body_html=None,
    )

    _walk_parts(msg, parsed, level, prefix="")
    return parsed


def _clean_header(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _format_sender(msg: EmailMessage) -> str:
    raw_from = msg.get("From")
    if not raw_from:
        return ""
    try:
        addresses = email.utils.getaddresses([raw_from])
        if not addresses:
            return str(raw_from)
        name, addr = addresses[0]
        return f"{name} <{addr}>" if name else addr
    except Exception:  # noqa: BLE001
        return str(raw_from)


def _extract_received_dt(msg: EmailMessage) -> str | None:
    """从 Received 头链提取可信接收时间。

    Received 头按接收顺序逆序追加：最早的在最前、最新的在最后。
    取最后一个可成功解析的时间戳（即离本系统最近的一跳接收时间）。
    解析失败、没有 Received 头时返回 None —— 不用 Date 头兜底。
    """
    received_headers = msg.get_all("Received") or []
    latest = None
    for header in received_headers:
        # 去掉 'from ... ;' 前缀，分号后是日期
        if ";" not in header:
            continue
        date_part = header.rsplit(";", 1)[1].strip()
        dt = email.utils.parsedate_to_datetime(date_part)
        if dt is not None:
            latest = dt
    if latest is None:
        return None
    if latest.tzinfo is None:
        # 没有时区信息的时间戳不可信为“绝对接收时间”，但仍记录为本地时间
        return latest.isoformat()
    return latest.astimezone().isoformat()


def _walk_parts(part: MIMEPart, parsed: ParsedEmail, level: int, prefix: str,
                force_inline: bool = False) -> None:
    mime_path = prefix or "0"
    disposition = (part.get_content_disposition() or "").lower()
    filename = part.get_filename()  # policy.default 已完成 RFC 2231/2047 中文解码
    ctype = part.get_content_type()
    cid = part.get("Content-ID")
    if cid:
        cid = cid.strip().lstrip("<").rstrip(">")

    payload = part.get_payload(decode=True) or b""

    # message/rfc822 本身 is_multipart() 为 True，必须先于普通多分支判断截获
    if ctype == "message/rfc822" or (filename or "").lower().endswith(".eml"):
        eml_bytes = _extract_forwarded_bytes(part, payload)
        parsed.nested_emls.append(
            NestedEml(
                filename=filename or "forwarded.eml",
                payload=eml_bytes,
                mime_path=mime_path,
                nesting_level=level + 1,
                layer_label=_layer_label(level + 1),
            )
        )
        return

    if part.is_multipart():
        in_related = part.get_content_type() == "multipart/related"
        for index, child in enumerate(part.iter_parts()):
            child_path = f"{prefix}{index}" if not prefix else f"{prefix}/{index}"
            _walk_parts(child, parsed, level, child_path, force_inline=in_related)
        return

    # 正文（无文件名、非附件 disposition）
    if not filename and disposition != "attachment":
        if ctype == "text/plain" and not parsed.body_text:
            parsed.body_text = _decode_text(part, payload)
        elif ctype == "text/html":
            parsed.body_html = _decode_text(part, payload)
        elif ctype.startswith("image/") and (disposition == "inline" or force_inline):
            parsed.attachments.append(
                AttachmentPart(
                    filename=filename or f"inline_{cid or mime_path.replace('/', '_')}.{_img_ext(ctype)}",
                    payload=payload, is_inline=True, inline_cid=cid,
                    mime_path=mime_path, nesting_level=level,
                    layer_label=_layer_label(level), content_type=ctype,
                )
            )
        return

    # 带文件名但通过 CID 内嵌引用的图片（部分客户端仍标 attachment）
    if ctype.startswith("image/") and cid and (force_inline or disposition != "attachment"):
        parsed.attachments.append(
            AttachmentPart(
                filename=filename, payload=payload, is_inline=True, inline_cid=cid,
                mime_path=mime_path, nesting_level=level,
                layer_label=_layer_label(level), content_type=ctype,
            )
        )
        return
    # multipart/related 内的图片即使没有 CID 也按内嵌展示
    if ctype.startswith("image/") and force_inline:
        parsed.attachments.append(
            AttachmentPart(
                filename=filename or f"inline_{mime_path.replace('/', '_')}.{_img_ext(ctype)}",
                payload=payload, is_inline=True, inline_cid=cid,
                mime_path=mime_path, nesting_level=level,
                layer_label=_layer_label(level), content_type=ctype,
            )
        )
        return

    parsed.attachments.append(
        AttachmentPart(
            filename=filename or f"unnamed_{mime_path.replace('/', '_')}.bin",
            payload=payload,
            is_inline=(disposition == "inline"),
            inline_cid=cid if disposition == "inline" else None,
            mime_path=mime_path,
            nesting_level=level,
            layer_label=_layer_label(level),
            content_type=ctype,
        )
    )


def _decode_text(part: MIMEPart, payload: bytes) -> str:
    charset = part.get_content_charset()
    for enc in filter(None, [charset, "utf-8", "gb18030"]):
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def _img_ext(ctype: str) -> str:
    return ctype.split("/", 1)[1].replace("jpeg", "jpg") if "/" in ctype else "bin"


def _extract_forwarded_bytes(part: MIMEPart, fallback: bytes) -> bytes:
    """取出嵌套邮件的原始 RFC 字节。

    message/rfc822 部件可能被施加 base64/quoted-printable 传输编码
    （Python 自己的 add_attachment 就会这么做），此时 email 库的
    get_content()/get_payload() 都无法还原内层结构。这里直接切出
    部件自身的头与实体体，按 CTE 手动解码。
    """
    raw_part = part.as_bytes()
    sep = b"\r\n\r\n" if b"\r\n\r\n" in raw_part else b"\n\n"
    if sep not in raw_part:
        return fallback
    _head, body_blob = raw_part.split(sep, 1)
    cte = (part.get("Content-Transfer-Encoding") or "7bit").lower()
    try:
        if cte == "base64":
            return base64.b64decode(b"".join(body_blob.split()))
        if cte == "quoted-printable":
            return quopri.decodestring(body_blob)
    except Exception:  # noqa: BLE001
        pass
    # 无传输编码：实体体就是内层邮件原文
    return body_blob.lstrip(b"\r\n")
