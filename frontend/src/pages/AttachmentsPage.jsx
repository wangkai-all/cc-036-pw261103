import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function AttachmentsPage({ onOpen }) {
  const [items, setItems] = useState([])
  const [onlyAnomaly, setOnlyAnomaly] = useState(false)
  const [inline, setInline] = useState('')

  useEffect(() => {
    const params = {}
    if (onlyAnomaly) params.only_anomaly = true
    if (inline !== '') params.inline = inline
    api.attachments(params).then(setItems)
  }, [onlyAnomaly, inline])

  return (
    <div className="page">
      <h2>附件</h2>
      <div className="card form-row">
        <label className="check"><input type="checkbox" checked={onlyAnomaly}
          onChange={(e) => setOnlyAnomaly(e.target.checked)} /> 只看类型异常</label>
        <label>内嵌图
          <select value={inline} onChange={(e) => setInline(e.target.value)}>
            <option value="">全部</option>
            <option value="true">仅内嵌图片</option>
            <option value="false">仅普通附件</option>
          </select>
        </label>
      </div>
      <div className="card">
        <table className="grid">
          <thead>
            <tr><th>内部附件#</th><th>展示名</th><th>所属邮件层</th><th>来源邮件</th>
              <th>扩展名/实际类型</th><th>核对</th><th>引用次数</th><th></th></tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id} className="clickable" onClick={() => onOpen(a.id)}>
                <td className="mono">{a.id}</td>
                <td>{a.is_inline ? '🖼️ ' : '📎 '}{a.display_name}</td>
                <td><span className="badge">{a.layer_label}</span></td>
                <td className="small">#{a.email_id} {a.email_subject}</td>
                <td className="small">.{a.ext || '?'} → {a.detected_type}</td>
                <td><span className={`badge ${a.type_check === 'ok' ? 'ok' : 'danger'}`}>
                  {a.type_check === 'ok' ? '一致' : '异常'}</span></td>
                <td>{a.reference_count}</td>
                <td><button className="link">详情</button></td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan="8" className="muted center">暂无数据</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
