"""端到端业务规则测试。每个测试用独立临时目录，互不污染。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app import config  # noqa: E402
from app.database import get_conn, init_db  # noqa: E402
from app.importer import import_batch  # noqa: E402
from app.mime_parser import parse_message  # noqa: E402
from app.typecheck import check_file  # noqa: E402
import make_samples  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "intake.sqlite3")
    monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "blobs" / "raw")
    monkeypatch.setattr(config, "CONTENT_DIR", tmp_path / "blobs" / "files")
    init_db()
    return tmp_path


@pytest.fixture()
def samples():
    return {
        "normal": make_samples.build_01_normal(make_samples.make_msgid("t1")),
        "inline": make_samples.build_02_inline_image(),
        "nested": make_samples.build_03_nested_forward(),
        "no_msgid": make_samples.build_06_no_msgid(),
        "no_received": make_samples.build_07_no_received(),
        "anomaly": make_samples.build_08_type_anomaly(),
        "same_name": make_samples.build_09_same_name(),
    }


def _import(home, data, channel="ch-a", period="2026-10", name="x.eml"):
    return import_batch([(name, data)], channel, period)


# ---------- MIME 解析 ----------

def test_chinese_filenames_decoded(home, samples):
    parsed = parse_message(samples["normal"])
    names = {a.filename for a in parsed.attachments}
    assert names == {"十月对账明细.csv", "结算汇总表.xlsx", "电子发票.pdf"}


def test_inline_image_separated_from_attachments(home, samples):
    parsed = parse_message(samples["inline"])
    inline = [a for a in parsed.attachments if a.is_inline]
    normal = [a for a in parsed.attachments if not a.is_inline]
    assert len(inline) == 1
    assert inline[0].inline_cid == "diagram-001"
    assert inline[0].filename == "示意图.png"
    assert len(normal) == 1


def test_nested_eml_expanded_with_layer(home, samples):
    parsed = parse_message(samples["nested"])
    assert len(parsed.nested_emls) == 1
    inner = parse_message(parsed.nested_emls[0].payload)
    assert inner.subject.startswith("转发")
    assert inner.attachments[0].filename == "九月补单.csv"


def test_received_time_blank_never_falls_back_to_date(home, samples):
    parsed = parse_message(samples["no_received"])
    assert parsed.received_dt_iso is None          # 无 Received 头
    assert parsed.header_dt_iso is not None        # Date 仍然展示为发送时间
    with_header = parse_message(samples["normal"])
    assert with_header.received_dt_iso is not None


# ---------- 去重与冲突 ----------

def test_duplicate_delivery_single_processing(home, samples):
    raw = samples["normal"]
    r1 = _import(home, raw)
    r2 = _import(home, raw)
    assert r1.files[0].status == "imported"
    assert r2.files[0].status == "duplicate"

    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) n FROM email").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) n FROM delivery").fetchone()["n"] == 1
    # 附件只处理一次：3 个附件 + 3 个内容 blob
    assert conn.execute("SELECT COUNT(*) n FROM attachment").fetchone()["n"] == 3
    assert conn.execute("SELECT COUNT(*) n FROM attachment_content").fetchone()["n"] == 3


def test_same_bytes_other_channel_creates_delivery_shares_content(home, samples):
    raw = samples["normal"]
    _import(home, raw, channel="ch-a")
    r = _import(home, raw, channel="ch-b")
    assert r.files[0].status == "imported"
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) n FROM email").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) n FROM delivery").fetchone()["n"] == 2
    assert conn.execute("SELECT COUNT(*) n FROM attachment_content").fetchone()["n"] == 3


def test_message_id_conflict(home, samples):
    mid = make_samples.make_msgid("conflict-t")
    first = make_samples.build_01_normal(mid)
    second = make_samples.build_05_conflict(mid)
    _import(home, first)
    r = _import(home, second)
    assert r.files[0].status == "conflict"
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) n FROM conflict").fetchone()["n"] == 1
    # 冲突邮件不入库、不处理附件
    assert conn.execute("SELECT COUNT(*) n FROM email").fetchone()["n"] == 1


def test_no_message_id_uses_content_hash(home, samples):
    raw = samples["no_msgid"]
    assert parse_message(raw).message_id is None
    r1 = _import(home, raw)
    r2 = _import(home, raw)
    assert r1.files[0].status == "imported"
    assert r2.files[0].status == "duplicate"


def test_different_period_adds_delivery(home, samples):
    raw = samples["normal"]
    _import(home, raw, period="2026-10")
    r = _import(home, raw, period="2026-11")
    assert r.files[0].status == "duplicate"
    conn = get_conn()
    periods = {
        row["billing_period"]
        for row in conn.execute("SELECT billing_period FROM delivery")
    }
    assert periods == {"2026-10", "2026-11"}


# ---------- 附件与类型核对 ----------

def test_type_mismatch_goes_to_anomaly(home, samples):
    _import(home, samples["anomaly"])
    conn = get_conn()
    anomalies = conn.execute("SELECT * FROM type_anomaly").fetchall()
    assert len(anomalies) == 2
    exts = {row["ext"] for row in anomalies}
    assert exts == {"pdf", "xlsx"}
    # 同邮件内真实 PDF 不受影响
    ok = conn.execute(
        "SELECT COUNT(*) n FROM attachment_content WHERE type_check='ok'"
    ).fetchone()["n"]
    assert ok == 1


def test_same_named_attachments_both_kept(home, samples):
    _import(home, samples["same_name"])
    conn = get_conn()
    rows = conn.execute(
        "SELECT display_name, mime_path FROM attachment ORDER BY mime_path"
    ).fetchall()
    assert [r["display_name"] for r in rows] == ["对账明细.csv", "对账明细.csv"]
    assert rows[0]["mime_path"] != rows[1]["mime_path"]


def test_shared_attachment_content(home, samples):
    # 两封不同邮件带同一份 CSV 字节：内容共用、来源关系各自保留
    csv_data = make_samples.csv_bytes([["a"], ["1"]])
    m1 = make_samples.base_msg("邮件甲", "a@x.example", msg_id=make_samples.make_msgid("s1"))
    m1.set_content("x")
    make_samples.add_attachment(m1, "shared.csv", csv_data, "text", "csv")
    m2 = make_samples.base_msg("邮件乙", "b@x.example", msg_id=make_samples.make_msgid("s2"))
    m2.set_content("y")
    make_samples.add_attachment(m2, "别名.csv", csv_data, "text", "csv")
    import_batch([("a.eml", m1.as_bytes()), ("b.eml", m2.as_bytes())], "ch-a", "2026-10")

    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) n FROM attachment").fetchone()["n"] == 2
    contents = conn.execute(
        "SELECT COUNT(*) n FROM attachment_content WHERE ext='csv'"
    ).fetchone()["n"]
    assert contents == 1
    refs = conn.execute(
        """SELECT COUNT(*) n FROM attachment a
           JOIN attachment_content ac ON ac.id=a.content_id
           WHERE ac.sha256=(SELECT sha256 FROM attachment_content LIMIT 1)"""
    ).fetchone()["n"]
    assert refs == 2


def test_nested_attachment_layer_label(home, samples):
    _import(home, samples["nested"])
    conn = get_conn()
    labels = {
        row["layer_label"]
        for row in conn.execute("SELECT DISTINCT layer_label FROM attachment")
    }
    assert "外层邮件" in labels
    assert "转发第1层邮件" in labels
    inner = conn.execute(
        """SELECT display_name FROM attachment
           WHERE layer_label='转发第1层邮件' AND display_name='九月补单.csv'"""
    ).fetchone()
    assert inner is not None


# ---------- 存储与原文件名 ----------

def test_files_stored_by_internal_hash_not_original_name(home, samples):
    _import(home, samples["normal"])
    # blob 路径中不应出现原始文件名
    for path in (home / "blobs").rglob("*"):
        if path.is_file():
            assert "对账" not in path.name and ".csv" not in path.name
    conn = get_conn()
    row = conn.execute(
        "SELECT display_name FROM attachment WHERE display_name='电子发票.pdf'"
    ).fetchone()
    assert row is not None


# ---------- 类型检查单元 ----------

def test_typecheck_signatures():
    assert check_file("a.pdf", make_samples.pdf_bytes("x")).type_check == "ok"
    assert check_file("a.xlsx", make_samples.xlsx_bytes("s", [["x"]])).type_check == "ok"
    assert check_file("a.csv", make_samples.csv_bytes([["x"], ["1"]])).type_check == "ok"
    assert check_file("a.pdf", b"not a pdf at all").type_check == "mismatch"
    assert check_file("a.xlsx", b"plain text only").type_check == "mismatch"
    png = make_samples.PNG_1X1
    assert check_file("a.png", png).detected_type == "png"
    assert check_file("a.pdf", png).type_check == "mismatch"
