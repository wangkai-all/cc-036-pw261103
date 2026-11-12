import React, { useEffect, useState } from 'react'

export default function AnomaliesPage({ onOpenAttachment }) {
  const [items, setItems] = useState([])
  useEffect(() => {
    fetch('/api/anomalies').then((r) => r.json()).then(setItems)
  }, [])
  return (
    <div className="page">
      <h2>类型异常列表</h2>
      <div className="card">
        <p className="hint">扩展名与文件格式特征核对不符的附件都留在这里，不参与正常附件统计口径。</p>
        <table className="grid">
          <thead>
            <tr><th>附件#</th><th>展示名</th><th>声明扩展名</th><th>实际类型</th>
              <th>来源邮件</th><th>核对详情</th><th></th></tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id}>
                <td className="mono">{t.attachment_id}</td>
                <td>{t.display_name}</td>
                <td>.{t.ext || '?'}</td>
                <td><span className="badge danger">{t.detected_type}</span></td>
                <td className="small">#{t.email_id} {t.subject}</td>
                <td className="small">{t.detail}</td>
                <td><button className="link" onClick={() => onOpenAttachment(t.attachment_id)}>查看</button></td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan="7" className="muted center">没有异常 🎉</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
