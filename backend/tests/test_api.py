"""FastAPI 接口层测试：上传校验、下载、SPA 行为。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app import config, main  # noqa: E402
from app.database import get_conn  # noqa: E402
import make_samples  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "intake.sqlite3")
    monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "blobs" / "raw")
    monkeypatch.setattr(config, "CONTENT_DIR", tmp_path / "blobs" / "files")
    with TestClient(main.app) as c:
        yield c


def _eml_upload(client, data: bytes, name="邮件.eml",
                channel="ch-a", period="2026-10"):
    return client.post(
        "/api/uploads",
        data={"channel": channel, "billing_period": period},
        files=[("files", (name, data, "message/rfc822"))],
    )


def test_health_and_stats(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/stats").json()["emails"] == 0


def test_upload_happy_path_and_duplicate(client):
    raw = make_samples.build_01_normal(make_samples.make_msgid("api-1"))
    r1 = _eml_upload(client, raw)
    assert r1.status_code == 200
    assert r1.json()["imported"] == 1
    r2 = _eml_upload(client, raw)
    assert r2.json()["duplicate"] == 1


def test_billing_period_validation(client):
    r = client.post(
        "/api/uploads",
        data={"channel": "x", "billing_period": "2026/10"},
        files=[("files", ("a.eml", b"x", "message/rfc822"))],
    )
    assert r.status_code == 400


def test_non_eml_rejected_but_batch_continues(client):
    good = make_samples.build_07_no_received()
    r = client.post(
        "/api/uploads",
        data={"channel": "ch-a", "billing_period": "2026-10"},
        files=[
            ("files", ("好邮件.eml", good, "message/rfc822")),
            ("files", ("notes.txt", b"hello", "text/plain")),
            ("files", ("empty.eml", b"", "message/rfc822")),
        ],
    )
    body = r.json()
    assert body["total"] == 3
    assert body["imported"] == 1
    assert body["error"] == 2
    reasons = {f["filename"]: f["detail"] for f in body["files"]}
    assert ".eml" in reasons["notes.txt"] or "eml" in reasons["notes.txt"]
    assert "空" in reasons["empty.eml"]


def test_blank_received_time_serialized_as_null(client):
    _eml_upload(client, make_samples.build_07_no_received())
    items = client.get("/api/emails").json()["items"]
    row = items[0]
    assert row["received_dt"] is None
    assert row["header_dt"] is not None  # 发送时间照常展示


def test_download_headers_preserve_chinese_name(client):
    _eml_upload(client, make_samples.build_01_normal(make_samples.make_msgid("api-2")))
    email_id = client.get("/api/emails").json()["items"][0]["id"]
    att_id = client.get(f"/api/emails/{email_id}").json()["attachments"][0]["id"]
    r = client.get(f"/api/attachments/{att_id}/download")
    cd = r.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert "%E5%AF%B9%E8%B4%A6" in cd  # “对账”的百分号编码
    assert cd.split('filename="')[1].split('"')[0].endswith(".csv")


def test_unknown_api_route_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_anomaly_and_conflict_endpoints(client):
    _eml_upload(client, make_samples.build_08_type_anomaly())
    anomalies = client.get("/api/anomalies").json()
    assert len(anomalies) == 2
    mid = make_samples.make_msgid("api-conf")
    _eml_upload(client, make_samples.build_01_normal(mid))
    r = _eml_upload(client, make_samples.build_05_conflict(mid))
    assert r.json()["conflict"] == 1
    conflicts = client.get("/api/conflicts").json()
    assert len(conflicts) == 1
    assert conflicts[0]["message_id"] == mid
