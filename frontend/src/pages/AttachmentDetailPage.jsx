import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function AttachmentDetailPage({ attachmentId, onBack, onOpenEmail }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.attachmentDetail(attachmentId).then(setData).catch((e) => setError(e.message))
  }, [attachmentId])

  if (error) return <div className="banner danger">{error}</div>
  if (!data) return <p className="hint">加载中…</p>

  const { attachment: a, source_email: src, deliveries, all_sources: sources, anomalies } = data
  const isImage = ['png', 'jpeg', 'gif', 'webp'].includes(a.detected_type)

  return (
    <div className="page">
      <button className="link" onClick={onBack}>← 返回附件列表</button>
      <h2>📎 {a.display_name}</h2>

      <div className="card detail-grid">
        <div>
          <table className="kv">
            <tbody>
              <tr><th>内部附件编号</th><td className="mono">#{a.attachment_id}</td></tr>
              <tr><th>原文件名（仅展示/下载）</th><td>{a.display_name}</td></tr>
              <tr><th>所属邮件层</th><td>{a.att_layer_label}（MIME 路径 <span className="mono">{a.mime_path}</span>）</td></tr>
              <tr><th>声明扩展名</th><td>.{a.ext || '（无）'}</td></tr>
              <tr><th>特征识别类型</th><td>{a.detected_type}</td></tr>
              <tr><th>大小 / 散列</th><td>{a.size} 字节<br /><span className="mono small">{a.content_sha256}</span></td></tr>
              <tr><th>类型核对结果</th>
                <td><span className={`badge ${a.type_check === 'ok' ? 'ok' : 'danger'}`}>
                  {a.type_check === 'ok' ? '一致' : '不符（异常）'}</span>
                  <div className="hint small">{a.check_detail}</div></td></tr>
              <tr><th>内嵌图</th><td>{a.is_inline ? `是（Content-ID: ${a.inline_cid || '无'}）` : '否'}</td></tr>
            </tbody>
          </table>
          <a className="button primary" href={api.attachmentDownloadUrl(a.attachment_id)}
             target="_blank" rel="noreferrer">下载（使用原文件名）</a>
        </div>
        {isImage && (
          <div className="preview">
            <p className="hint">内嵌图片预览</p>
            <img src={api.attachmentDownloadUrl(a.attachment_id)} alt={a.display_name} />
          </div>
        )}
      </div>

      <div className="card">
        <h3>来源邮件与接收账期</h3>
        <table className="kv">
          <tbody>
            <tr><th>来源邮件</th>
              <td><button className="link" onClick={() => onOpenEmail(src.id)}>
                #{src.id} {src.subject || '（无主题）'}
              </button>（{src.from_addr}）</td></tr>
            <tr><th>头声明发送时间</th><td>{src.header_dt || '—'}</td></tr>
            <tr><th>可信接收时间</th><td>{src.received_dt || <em className="muted">留空</em>}</td></tr>
          </tbody>
        </table>
        <table className="grid">
          <thead><tr><th>接收渠道</th><th>接收账期</th></tr></thead>
          <tbody>
            {deliveries.map((d, i) => (
              <tr key={i}><td>{d.channel_name}（{d.channel_code}）</td>
                <td>{(d.billing_periods || '').split(',').join('、')}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>重复识别：同一内容的全部来源（{sources.length}）</h3>
        <p className="hint">附件内容按字节散列只存一份，以下是各自的来源关系：</p>
        <table className="grid">
          <thead><tr><th>附件#</th><th>所属邮件</th><th>邮件层</th><th>该邮件中的展示名</th></tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.attachment_id}>
                <td className="mono">{s.attachment_id}</td>
                <td><button className="link" onClick={() => onOpenEmail(s.email_id)}>
                  #{s.email_id} {s.subject || '（无主题）'}</button>
                  <span className="hint"> {s.from_addr}</span></td>
                <td><span className="badge">{s.layer_label}</span></td>
                <td>{s.display_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {anomalies.length > 0 && (
        <div className="card">
          <h3 className="danger-text">异常记录</h3>
          {anomalies.map((an) => (
            <div key={an.id} className="banner danger">
              .{an.ext || '?'} 与实际类型 {an.detected_type} 不符：{an.detail}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
