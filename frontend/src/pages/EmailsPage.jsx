import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function EmailsPage({ onOpen }) {
  const [data, setData] = useState({ items: [], total: 0 })
  const [channels, setChannels] = useState([])
  const [filter, setFilter] = useState({ channel: '', billing_period: '', q: '' })

  const load = () =>
    api.emails(filter).then(setData)
  useEffect(() => { api.channels().then(setChannels).catch(() => {}) }, [])
  useEffect(() => { load() }, [filter.channel, filter.billing_period])

  return (
    <div className="page">
      <h2>邮件列表</h2>
      <div className="card form-row">
        <label>渠道
          <select value={filter.channel}
                  onChange={(e) => setFilter((f) => ({ ...f, channel: e.target.value }))}>
            <option value="">全部</option>
            {channels.map((c) => <option key={c.id} value={c.code}>{c.name}</option>)}
          </select>
        </label>
        <label>账期
          <input placeholder="YYYY-MM" value={filter.billing_period}
                 onChange={(e) => setFilter((f) => ({ ...f, billing_period: e.target.value }))} />
        </label>
        <label>搜索
          <input placeholder="主题 / 发件人 / Message-ID" value={filter.q}
                 onChange={(e) => setFilter((f) => ({ ...f, q: e.target.value }))}
                 onKeyDown={(e) => e.key === 'Enter' && load()} />
        </label>
        <button onClick={load}>查询</button>
      </div>

      <div className="card">
        <p className="hint">共 {data.total} 封顶层邮件（嵌套转发的 .eml 在邮件详情中展开）</p>
        <table className="grid">
          <thead>
            <tr>
              <th>#</th><th>发件地址</th><th>主题</th><th>Message-ID</th>
              <th>头声明发送时间</th><th>可信接收时间</th><th>实际导入时间</th>
              <th>渠道/账期</th><th>附件</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((e) => (
              <tr key={e.id} className="clickable" onClick={() => onOpen(e.id)}>
                <td className="mono">{e.id}{e.is_nested ? ' 🪆' : ''}</td>
                <td>{e.from_addr || '—'}</td>
                <td>{e.subject || '（无主题）'}</td>
                <td className="mono small">{e.message_id || <em>缺失·散列识别</em>}</td>
                <td className="small">{e.header_dt || '—'}</td>
                <td className="small">{e.received_dt || <em className="muted">留空</em>}</td>
                <td className="small">{e.imported_at}</td>
                <td className="small">
                  {(e.channel_periods || '').split('|').filter(Boolean).map((cp) => {
                    const [code, period] = cp.split(':')
                    return <span key={cp} className="badge">{code}·{period}</span>
                  })}
                </td>
                <td>{e.attachment_count}</td>
              </tr>
            ))}
            {!data.items.length && <tr><td colSpan="9" className="muted center">暂无数据</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
