"""上传与批量导入路由。"""
from __future__ import annotations

import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import config
from ..importer import import_batch

router = APIRouter(prefix="/api", tags=["upload"])

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.post("/uploads")
async def upload_emls(
    channel: str = Form(...),
    billing_period: str = Form(...),
    files: list[UploadFile] = File(...),
):
    channel = channel.strip()
    if not channel:
        raise HTTPException(400, "接收渠道不能为空")
    if not PERIOD_RE.match(billing_period):
        raise HTTPException(400, "账期格式应为 YYYY-MM")
    if not files:
        raise HTTPException(400, "未选择文件")
    if len(files) > config.MAX_UPLOAD_FILES:
        raise HTTPException(400, f"单次最多 {config.MAX_UPLOAD_FILES} 个文件")

    payload: list[tuple[str, bytes]] = []
    pre_errors: list[dict] = []
    for up in files:
        data = await up.read()
        if len(data) > config.MAX_UPLOAD_BYTES:
            pre_errors.append(_error_file(up.filename,
                f"超过大小上限 {config.MAX_UPLOAD_BYTES} 字节"))
            continue
        if not (up.filename or "").lower().endswith(".eml"):
            pre_errors.append(_error_file(up.filename, "不是 .eml 文件，已跳过"))
            continue
        payload.append((up.filename, data))

    if not payload:
        return _summarize([], pre_errors)

    result = import_batch(payload, channel, billing_period)
    return _summarize(result.files, pre_errors)


def _error_file(filename: str, detail: str) -> dict:
    return {"filename": filename, "status": "error", "email_id": None,
            "message_id": None, "content_hash": None, "detail": detail,
            "attachments": 0, "nested_emails": 0}


def _summarize(imported_files: list, extra_errors: list[dict]) -> dict:
    files = [f.__dict__ if hasattr(f, "__dict__") else f for f in imported_files]
    files.extend(extra_errors)
    summary = {"total": len(files), "imported": 0, "duplicate": 0,
               "conflict": 0, "error": 0}
    for f in files:
        summary[f["status"]] += 1
    return summary | {"files": files}
