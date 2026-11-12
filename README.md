# 邮件接收台（Mail Intake）

批量上传 `.eml` 邮件，自动解析 MIME 层级、整理 CSV/XLSX/PDF 等附件，并完成投递去重、
类型核对与来源溯源。技术栈：Python 标准 `email` 库 + FastAPI + SQLite + React(Vite)。

## 目录结构

```
backend/
  app/
    config.py        运行期配置（路径均可用环境变量覆盖）
    database.py      SQLite 建表与连接
    storage.py       内容寻址存储（按 sha256 分桶落盘，原文件名不参与路径）
    mime_parser.py   MIME 递归解析（层级、中文名、内嵌图、嵌套 .eml、可信接收时间）
    typecheck.py     扩展名 + 字节特征双重核对（PDF/XLSX/CSV/图片/EML）
    importer.py      导入流水线（投递去重、冲突、附件内容复用、嵌套递归）
    routers/         FastAPI 路由（上传、查询、下载、异常、冲突）
  tests/             pytest：15 条业务规则测试 + 8 条接口测试
scripts/
  make_samples.py    生成 9 个覆盖全部场景的样例邮件 -> samples/
frontend/            React + Vite 单页应用（构建产物由 FastAPI 托管）
samples/             样例 .eml（中文附件名/嵌套转发/内嵌图/重复投递/类型异常/同名附件）
```

## 快速开始

```bash
# 1. 后端依赖
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. 生成样例邮件
.venv/bin/python -I scripts/make_samples.py

# 3. 启动后端（同时托管 frontend/dist）
.venv/bin/uvicorn --app-dir backend app.main:app --reload --port 8000

# 4. 前端开发模式（可选，热更新；生产用 npm run build 后由后端托管）
cd frontend && npm install --cache /tmp/npm-cache && npm run dev
```

打开 http://127.0.0.1:8000 ，在“批量上传”页选择 `samples/` 下的 `.eml`，
指定接收渠道（如 `partner-a`）和账期（`YYYY-MM`）后导入。

测试：

```bash
.venv/bin/python -I -m pytest backend/tests/ -q
```

## 核心业务规则

### 邮件识别与投递

- **去重**：同一接收渠道下，Message-ID 相同且原始字节 sha256 相同 → 只增加一条
  `delivery` 投递记录，附件不重复处理；换账期再投则补该账期的投递记录。
- **冲突**：同渠道 Message-ID 相同但字节不同 → 拒收并写入 `conflict`，前端“冲突记录”可查。
- **无 Message-ID**：以原始字节内容散列作为身份，重复投递同样识别。
- **跨渠道同字节**：邮件只存一份，新增渠道投递；附件内容存储共用、来源关系各自保留。

### 时间字段（严格区分）

- 列表/详情展示：发件地址、主题、Message-ID、**邮件头 Date 声明的发送时间**、**实际导入时间**。
- **可信接收时间**仅从 `Received` 头链解析；没有可信接收时间时字段留空（JSON `null`），
  绝不用 Date 发送时间代替。

### MIME 与附件

- 递归解析 multipart，每个附件带 MIME 树路径（如 `0/1/1`）和所属邮件层标签
  （“外层邮件”/“转发第1层邮件”…）。
- 中文文件名按 RFC 2231/2047 解码；同名附件各自成行，以 MIME 路径区分。
- 内嵌图片（CID 引用或 multipart/related 内图片）单独标记 `is_inline` 展示，可预览。
- 转发邮件中的 `message/rfc822` / `.eml` 递归展开（含带 base64 传输编码的情况），
  .eml 本身也留痕可下载。

### 类型核对

- 按扩展名声明与魔数/结构特征双重核对：PDF（`%PDF-` + pypdf 结构校验）、
  XLSX（ZIP 容器 + `xl/workbook.xml` + openpyxl 校验）、CSV（UTF-8/GB18030 文本 + csv 解析）、
  图片（PNG/JPEG/GIF/WEBP 魔数）、EML（可解析为 RFC 5322）。
- 不符的附件保留在系统中但进入“异常列表”，标明声明扩展名、实际类型与原因。

### 存储与下载

- 所有文件按内容 sha256 分桶存于 `data/blobs/`，数据库内部编号关联；
  原文件名只用于界面展示和下载响应头（RFC 5987 `filename*` 支持中文）。
- 原始 `.eml` 可在邮件详情页下载。
- 附件详情页可查看：来源邮件、接收渠道与账期、类型核对结论、同一内容的全部来源关系。

## 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/uploads` | multipart 批量上传，表单字段 `channel`、`billing_period`、`files` |
| GET | `/api/emails` | 邮件列表，支持 `channel`/`billing_period`/`q` 过滤 |
| GET | `/api/emails/{id}` | 邮件详情（投递、附件、嵌套邮件、内容共用关系） |
| GET | `/api/emails/{id}/raw` | 下载原始 .eml |
| GET | `/api/attachments` | 附件列表，支持 `only_anomaly`、`inline` 过滤 |
| GET | `/api/attachments/{id}` | 附件溯源详情 |
| GET | `/api/attachments/{id}/download` | 按原文件名下载 |
| GET | `/api/anomalies` | 类型异常列表 |
| GET | `/api/conflicts` | Message-ID 冲突列表 |
| GET | `/api/stats` | 汇总统计 |

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAIL_INTAKE_HOME` | `./data` | 数据根目录 |
| `MAIL_INTAKE_DB` | `$HOME/intake.sqlite3` | SQLite 路径 |
| `MAIL_INTAKE_BLOBS` | `$HOME/blobs` | blob 存储根 |
| `MAIL_INTAKE_MAX_BYTES` | 104857600 | 单文件大小上限 |
| `MAIL_INTAKE_MAX_FILES` | 200 | 单次上传文件数上限 |

## 样例场景对照（samples/）

| 文件 | 覆盖点 |
| --- | --- |
| 01_正常邮件_中文附件名 | 中文 CSV/XLSX/PDF 附件名 |
| 02_内嵌图片邮件 | CID 内嵌图与普通附件分离 |
| 03_嵌套转发邮件 | 嵌套 .eml 展开、层级标签、内层附件 |
| 04_重复投递_与01同字节 | 同渠道同字节重复，仅增投递记录 |
| 05_MessageID冲突_内容不同 | 同 Message-ID 不同字节 → 冲突 |
| 06_无MessageID邮件 | 内容散列去重 |
| 07_无接收时间邮件 | 接收时间留空、不拿发送时间代替 |
| 08_附件类型异常 | 伪 PDF / 伪 XLSX 进入异常列表 |
| 09_同名附件邮件 | 同名附件分别保留 |
