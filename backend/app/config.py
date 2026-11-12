"""运行期配置：所有路径可通过环境变量覆盖，默认落在工作目录下。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(os.environ.get("MAIL_INTAKE_HOME", Path.cwd() / "data"))

DB_PATH = Path(os.environ.get("MAIL_INTAKE_DB", BASE_DIR / "intake.sqlite3"))
BLOB_DIR = Path(os.environ.get("MAIL_INTAKE_BLOBS", BASE_DIR / "blobs"))
RAW_DIR = BLOB_DIR / "raw"        # 顶层导入的原始 .eml
CONTENT_DIR = BLOB_DIR / "files"  # 内容寻址的附件内容

# 单次批量上传允许的大小 / 数量上限
MAX_UPLOAD_BYTES = int(os.environ.get("MAIL_INTAKE_MAX_BYTES", 100 * 1024 * 1024))
MAX_UPLOAD_FILES = int(os.environ.get("MAIL_INTAKE_MAX_FILES", 200))


def ensure_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
