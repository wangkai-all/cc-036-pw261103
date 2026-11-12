import React, { useEffect, useState } from 'react'

export default function ConflictsPage({ onOpenEmail }) {
  const [items, setItems] = useState([])
  useEffect(() => {
    fetch('/api/conflicts').then((r) => r.json()).then(setItems)
  }, [])
  return (
    <div className="page">
      <h2>Message-ID 冲突记录</h2>
      <div className="card">
        <p className="hint">同一接收渠道下 Message-ID 相同但原始字节不同的邮件，拒收并记录于此。</p>
        <table className="grid">
          <thead>
            <tr><th>#</th><th>渠道</th><th>Message-ID</th><th>已收录邮件</th>
              <th>来件散列</th><th>账期</th><th>说明</th><th>时间</th></tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td className="mono">{c.id}</td>
                <td>{c.channel_code}</td>
                <td className="mono small">{c.message_id}</td>
                <td>
                  <button className="link" onClick={() => onOpenEmail(c.existing_email_id)}>
                    #{c.existing_email_id} {c.existing_subject}
                  </button>
                  <span className="hint"> {c.existing_from}</span>
                </td>
                <td className="mono small">{c.incoming_hash.slice(0, 16)}…</td>
                <td>{c.billing_period}</td>
                <td className="small">{c.note}</td>
                <td className="small">{c.created_at}</td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan="8" className="muted center">没有冲突</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
