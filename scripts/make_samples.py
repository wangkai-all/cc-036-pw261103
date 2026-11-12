"""生成覆盖各业务场景的 .eml 样例邮件。

场景：
  01 正常邮件（中文 CSV/XLSX/PDF 附件名）
  02 内嵌图片邮件（HTML 正文引用 CID）
  03 嵌套转发（.eml 附件，内层再带附件）
  04 重复投递（与 01 同 Message-ID、同字节）
  05 同 Message-ID 但内容不同（冲突）
  06 无 Message-ID（靠内容散列识别）
  07 无 Received 头（接收时间留空，不用 Date 代替）
  08 类型异常（.pdf 扩展名但内容是文本、.xlsx 扩展名但不是 zip）
  09 同名附件（一封邮件两个“对账明细.csv”）

运行：python -I scripts/make_samples.py   （输出到 samples/）
"""
from __future__ import annotations

import csv
import io
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parents[1] / "samples"


# ---------- 附件内容构造 ----------

def csv_bytes(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def xlsx_bytes(sheet: str, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf_bytes(title: str) -> bytes:
    # 最小可用单页 PDF（纯标准库拼出合法结构）
    content = f"BT /F1 18 Tf 72 720 Td ({title}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return out


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfab4100"
    "00000049454e44ae426082"
)


# ---------- 邮件构造 ----------

def base_msg(subject: str, sender: str, to: str = "intake@example.cn",
             msg_id: str | None = None, with_received: bool = True) -> EmailMessage:
    msg = EmailMessage()
    if msg_id is not None:
        msg["Message-ID"] = msg_id
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    if with_received:
        # 两跳 Received，最后一跳即本系统的可信接收时间
        msg["Received"] = (
            "from mail-gateway.example.cn (10.20.0.1) by mx.example.cn "
            f"with ESMTP; {formatdate(localtime=False)}"
        )
    return msg


def add_attachment(msg: EmailMessage, filename: str, data: bytes,
                   maintype: str, subtype: str) -> None:
    msg.add_attachment(
        data, maintype=maintype, subtype=subtype, filename=filename
    )


def build_01_normal(msg_id: str) -> bytes:
    msg = base_msg("2026年10月渠道对账单", "billing-partner-a@vendor.example",
                   msg_id=msg_id)
    msg.set_content("您好，附件为本月对账文件，请查收。")
    add_attachment(msg, "十月对账明细.csv",
                   csv_bytes([["日期", "金额"], ["2026-10-01", "1280.50"]]),
                   "text", "csv")
    add_attachment(msg, "结算汇总表.xlsx",
                   xlsx_bytes("汇总", [["项目", "值"], ["合计", 9999]]),
                   "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    add_attachment(msg, "电子发票.pdf", pdf_bytes("Invoice 2026-10"),
                   "application", "pdf")
    return msg.as_bytes()


def build_02_inline_image() -> bytes:
    msg = base_msg("图文说明邮件", "ops@vendor.example", msg_id=make_msgid("inline-02"))
    msg.set_content("纯文本正文（无图版本）。")
    html = (
        '<html><body><p>请看下图中的数据说明：</p>'
        '<img src="cid:diagram-001" alt="示意图"/></body></html>'
    )
    msg.add_alternative(html, subtype="html")
    part = msg.get_payload()[1]
    part.add_related(PNG_1X1, maintype="image", subtype="png",
                     cid="<diagram-001>", filename="示意图.png")
    # 同时带一个普通附件，区分内嵌与普通附件
    add_attachment(msg, "附图数据.csv",
                   csv_bytes([["k", "v"], ["a", "1"]]), "text", "csv")
    return msg.as_bytes()


def build_inner_eml() -> bytes:
    inner = base_msg("转发：九月补充账单", "finance@inner.example",
                     msg_id=make_msgid("inner-03"))
    inner.set_content("这是被转发的原始邮件，内含一份 CSV。")
    add_attachment(inner, "九月补单.csv",
                   csv_bytes([["id"], ["X-1"], ["X-2"]]), "text", "csv")
    return inner.as_bytes()


def build_03_nested_forward() -> bytes:
    msg = base_msg("转发：九月补充账单（嵌套 .eml）", "relay@vendor.example",
                   msg_id=make_msgid("forward-03"))
    msg.set_content("见下方转发邮件。")
    add_attachment(msg, "原始邮件.eml", build_inner_eml(),
                   "message", "rfc822")
    add_attachment(msg, "转发说明.pdf", pdf_bytes("Forward note"),
                   "application", "pdf")
    return msg.as_bytes()


def build_05_conflict(original_msgid: str) -> bytes:
    # 复用 01 的 Message-ID，但替换正文使字节不同
    msg = base_msg("2026年10月渠道对账单（修订版）",
                   "billing-partner-a@vendor.example",
                   msg_id=original_msgid)
    msg.set_content("此为修订版本，正文与首封不同。")
    add_attachment(msg, "十月对账明细_修订.csv",
                   csv_bytes([["日期", "金额"], ["2026-10-01", "9999.99"]]),
                   "text", "csv")
    return msg.as_bytes()


def build_06_no_msgid() -> bytes:
    msg = base_msg("无 Message-ID 的系统导出邮件", "system@vendor.example",
                   msg_id=None)
    msg.set_content("由旧系统生成，缺少 Message-ID，依靠内容散列去重。")
    add_attachment(msg, "系统导出.xlsx",
                   xlsx_bytes("导出", [["a"], [1]]),
                   "application",
                   "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return msg.as_bytes()


def build_07_no_received() -> bytes:
    msg = base_msg("缺少接收时间信息的邮件", "legacy@vendor.example",
                   msg_id=make_msgid("no-rcvd-07"), with_received=False)
    msg.set_content("本邮件没有任何 Received 头，接收时间应留空。")
    add_attachment(msg, "历史单据.pdf", pdf_bytes("Legacy"),
                   "application", "pdf")
    return msg.as_bytes()


def build_08_type_anomaly() -> bytes:
    msg = base_msg("附件类型核对测试", "qa@vendor.example",
                   msg_id=make_msgid("anomaly-08"))
    msg.set_content("附件扩展名与真实格式不符，应进入异常列表。")
    # 伪 PDF：扩展名 .pdf，内容其实是 CSV 文本
    add_attachment(msg, "伪造单据.pdf",
                   csv_bytes([["fake"], [1]]), "application", "pdf")
    # 伪 XLSX：扩展名 .xlsx，内容是纯文本
    add_attachment(msg, "损坏工作簿.xlsx",
                   "这根本不是一个压缩包".encode("utf-8"),
                   "application",
                   "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    # 对照组：真正的 PDF
    add_attachment(msg, "真实单据.pdf", pdf_bytes("Real"),
                   "application", "pdf")
    return msg.as_bytes()


def build_09_same_name() -> bytes:
    msg = base_msg("同名附件测试", "dup-name@vendor.example",
                   msg_id=make_msgid("same-name-09"))
    msg.set_content("两个附件同名，应分别保留并标注 MIME 路径。")
    add_attachment(msg, "对账明细.csv",
                   csv_bytes([["版本"], ["A"]]), "text", "csv")
    add_attachment(msg, "对账明细.csv",
                   csv_bytes([["版本"], ["B"]]), "text", "csv")
    return msg.as_bytes()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    normal_id = make_msgid("normal-01")
    normal = build_01_normal(normal_id)
    samples: dict[str, bytes] = {
        "01_正常邮件_中文附件名.eml": normal,
        "02_内嵌图片邮件.eml": build_02_inline_image(),
        "03_嵌套转发邮件.eml": build_03_nested_forward(),
        "04_重复投递_与01同字节.eml": normal,  # 字节完全一致
        "05_MessageID冲突_内容不同.eml": build_05_conflict(normal_id),
        "06_无MessageID邮件.eml": build_06_no_msgid(),
        "07_无接收时间邮件.eml": build_07_no_received(),
        "08_附件类型异常.eml": build_08_type_anomaly(),
        "09_同名附件邮件.eml": build_09_same_name(),
    }
    for name, data in samples.items():
        (OUT / name).write_bytes(data)
        print(f"written {name} ({len(data)} bytes)")
    print(f"\n共 {len(samples)} 个样例 -> {OUT}")


if __name__ == "__main__":
    main()
