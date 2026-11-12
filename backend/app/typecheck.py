"""按扩展名 + 文件格式特征双重核对附件类型。

扩展名只代表“声明”，真实类型由字节特征/结构解析决定；两者不一致即 mismatch，
由导入流程写入 type_anomaly 异常列表。
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from openpyxl import load_workbook
from pypdf import PdfReader

IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # 需配合尾部 WEBP 标记二次确认
}

# 扩展名 -> 期望的真实类型族
EXPECTED_TYPES = {
    "pdf": {"pdf"},
    "xlsx": {"xlsx"},
    "csv": {"csv"},
    "eml": {"eml"},
    "png": {"png"},
    "jpg": {"jpeg"},
    "jpeg": {"jpeg"},
    "gif": {"gif"},
    "webp": {"webp"},
}


@dataclass
class TypeCheckResult:
    detected_type: str
    type_check: str          # 'ok' | 'mismatch'
    detail: str


def _sniff(data: bytes) -> str:
    """只看字节特征，给出真实类型。"""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06"):
        # ZIP 容器：进一步区分 xlsx
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "xl/workbook.xml" in names or any(
                    n.startswith("xl/worksheets/") for n in names
                ):
                    return "xlsx"
            return "zip"
        except zipfile.BadZipFile:
            return "binary"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"  # 老式 Office .xls/.doc 等复合文档
    for magic, label in IMAGE_MAGIC.items():
        if data.startswith(magic):
            if label == "webp":
                return "webp" if data[8:12] == b"WEBP" else "binary"
            return label
    # 文本类：可解码且不含 NUL
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            try:
                data.decode("gb18030")
                return "text"
            except UnicodeDecodeError:
                pass
    return "binary"


def _check_pdf(data: bytes) -> str | None:
    try:
        reader = PdfReader(io.BytesIO(data))
        return f"PDF {len(reader.pages)} 页"
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都视为特征不符
        return f"PDF 头存在但结构解析失败: {exc.__class__.__name__}"


def _check_xlsx(data: bytes) -> str | None:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
        sheets = wb.sheetnames
        wb.close()
        return f"XLSX 工作簿，工作表: {', '.join(sheets) or '(空)'}"
    except Exception as exc:  # noqa: BLE001
        return f"ZIP 容器但不是有效 XLSX: {exc.__class__.__name__}"


def _check_csv(data: bytes) -> str | None:
    if b"\x00" in data:
        return "含 NUL 字节，不是文本 CSV"
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return "无法按 UTF-8/GB18030 解码为文本"
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        return f"CSV 解析失败: {exc}"
    if not rows or all(not any(cell.strip() for cell in row) for row in rows):
        return "CSV 无有效数据行"
    width = max(len(row) for row in rows)
    return f"CSV 文本，{len(rows)} 行，最大 {width} 列"


def check_file(filename: str | None, data: bytes) -> TypeCheckResult:
    """对外主入口：结合声明扩展名与真实特征给出核对结论。"""
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].strip().lower()

    detected = _sniff(data)
    detail = f"特征识别: {detected}"

    # 结构级二次校验
    structural: str | None = None
    if detected == "pdf":
        structural = _check_pdf(data)
    elif detected == "xlsx":
        structural = _check_xlsx(data)
    elif ext == "csv":
        structural = _check_csv(data)
    if structural:
        detail += f"；{structural}"

    # CSV 特征上是 text，需要结构校验确认
    if ext == "csv":
        ok = structural is not None and structural.startswith("CSV")
        detected = "csv" if ok else ("text" if detected == "text" else detected)
        return TypeCheckResult(
            detected, "ok" if ok else "mismatch",
            detail if ok else f"扩展名 .csv 与内容不符；{detail}",
        )

    if ext in EXPECTED_TYPES:
        ok = detected in EXPECTED_TYPES[ext]
        # 结构校验报错（如伪 PDF、伪 XLSX）也算不符
        if ok and structural and not structural.startswith(("PDF", "XLSX")):
            ok = False
        if not ok:
            return TypeCheckResult(
                detected, "mismatch",
                f"扩展名 .{ext} 与实际类型 {detected} 不符；{detail}",
            )
    return TypeCheckResult(detected, "ok", detail)


def check_eml(data: bytes) -> TypeCheckResult:
    """嵌套 .eml 附件的专用校验。"""
    import email
    from email import policy

    try:
        msg = email.message_from_bytes(data, policy=policy.default)
        if not isinstance(msg, email.message.Message):
            raise ValueError("解析结果不是 Message")
        return TypeCheckResult("eml", "ok", "可解析的 RFC 5322 邮件")
    except Exception as exc:  # noqa: BLE001
        sniffed = _sniff(data)
        return TypeCheckResult(sniffed, "mismatch", f".eml 无法解析为邮件: {exc}")
