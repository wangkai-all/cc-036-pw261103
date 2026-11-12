import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function EmailDetailPage({ emailId, onBack, onOpenAttachment }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.emailDetail(emailId).then(setData).catch((e) => setError(e.message))
  }, [emailId])

  if (error) return <div className="banner danger">{error}</div>
  if (!data) return <p className="hint">加载中…</p>

  const { email: e, deliveries, attachments, nested_emails: nested, shared_content_sources: shared } = data

  return (
    <div className="page">
      <button className="link" onClick={onBack}>← 返回邮件列表</button>
      <h2>{e.subject || '（无主题）'} {e.is_nested ? <span className="badge">嵌套第{e.nesting_level}层</span> : null}</h2>

      <div className="card">
        <table className="kv">
          <tbody>
            <tr><th>内部编号</th><td className="mono">#{e.id}</td></tr>
            <tr><th>发件地址</th><td>{e.from_addr || '—'}</td></tr>
            <tr><th>Message-ID</th><td className="mono small">{e.message_id || <em>缺失，按内容散列 {e.content_hash.slice(0, 16)}… 识别</em>}</td></tr>
            <tr><th>内容散列</th><td className="mono small">{e.content_hash}</td></tr>
            <tr><th>头声明发送时间</th><td>{e.header_dt || '—'} <span className="hint">（原始值：{e.header_date_raw || '无'}）</span></td></tr>
            <tr><th>可信接收时间</th><td>{e.received_dt || <em className="muted">留空（无可信 Received 时间，未用发送时间代替）</em>}</td></tr>
            <tr><th>实际导入时间</th><td>{e.imported_at}</td></tr>
          </tbody>
        </table>
        <a className="button" href={api.rawEmailUrl(e.id)} target="_blank" rel="noreferrer">下载原始 .eml</a>
      </div>

      <div className="card">
        <h3>投递记录（{deliveries.length}）</h3>
        <table className="grid">
          <thead><tr><th>接收渠道</th><th>账期</th><th>导入时间</th></tr></thead>
          <tbody>
            {deliveries.map((d) => (
              <tr key={d.id}>
                <td>{d.channel_name}（{d.channel_code}）</td>
                <td>{d.billing_period}</td>
                <td className="small">{d.imported_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {nested.length > 0 && (
        <div className="card">
          <h3>嵌套转发的 .eml（{nested.length}）</h3>
          {nested.map((n) => (
            <div key={n.id} className="nested-row">
              <span className="badge warn">{n.layer_label}</span>
              <span className="mono small">{n.display_name} @ MIME {n.mime_path}</span>
              <span>主题：{n.subject || '（无主题）'}；发件人：{n.from_addr}</span>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h3>附件与内嵌图片（{attachments.length}）</h3>
        <table className="grid">
          <thead>
            <tr><th>展示名（原文件名）</th><th>所属邮件层</th><th>MIME 路径</th>
              <th>类型</th><th>核对</th><th>来源共用</th><th></th></tr>
          </thead>
          <tbody>
            {attachments.map((a) => (
              <tr key={a.id}>
                <td>
                  {a.is_inline ? '🖼️ [内嵌] ' : '📎 '}{a.display_name}
                  {a.inline_cid && <span className="hint"> cid:{a.inline_cid}</span>}
                </td>
                <td><span className="badge">{a.layer_label}</span></td>
                <td className="mono small">{a.mime_path}</td>
                <td className="small">声明 .{a.ext || '?'} → 实际 {a.detected_type}</td>
                <td>
                  <span className={`badge ${a.type_check === 'ok' ? 'ok' : 'danger'}`}>
                    {a.type_check === 'ok' ? '一致' : '异常'}
                  </span>
                  <div className="hint small">{a.check_detail}</div>
                </td>
                <td>{a.other_sources > 0 ? <span className="badge">另有 {a.other_sources} 封邮件引用同一内容</span> : '—'}</td>
                <td><button className="link" onClick={() => onOpenAttachment(a.id)}>溯源详情</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {shared.length > 0 && (
        <div className="card">
          <h3>附件内容重复识别</h3>
          <p className="hint">以下邮件与本邮件存在字节完全相同的附件（共用内容存储，各自保留来源关系）：</p>
          <ul>{shared.map((s) => <li key={s.id} className="mono small">#{s.id} {s.from_addr} — {s.subject}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
