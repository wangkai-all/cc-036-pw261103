import React, { useRef, useState } from 'react'
import { api } from '../api.js'

const PERIODS = ['2026-09', '2026-10', '2026-11']
const STATUS_STYLE = {
  imported: 'ok',
  duplicate: 'muted',
  conflict: 'warn',
  error: 'danger',
}

export default function UploadPage({ onDone }) {
  const [channel, setChannel] = useState('partner-a')
  const [period, setPeriod] = useState('2026-10')
  const [picked, setPicked] = useState([])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef()

  const pick = (e) => {
    const files = Array.from(e.target.files || [])
    setPicked((prev) => {
      const names = new Set(prev.map((f) => f.name + f.size))
      return [...prev, ...files.filter((f) => !names.has(f.name + f.size))]
    })
    e.target.value = ''
  }

  const submit = async () => {
    if (!picked.length) return
    setBusy(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('channel', channel.trim())
      fd.append('billing_period', period)
      picked.forEach((f) => fd.append('files', f))
      const data = await api.upload(fd)
      setResult(data)
      setPicked([])
      onDone?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h2>批量上传 .eml 邮件</h2>
      <div className="card form-row">
        <label>
          接收渠道
          <input value={channel} onChange={(e) => setChannel(e.target.value)}
                 placeholder="如 partner-a" />
        </label>
        <label>
          账期
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <button className="primary" disabled={busy || !picked.length || !channel.trim()}
                onClick={submit}>
          {busy ? '导入中…' : `导入 ${picked.length} 个文件`}
        </button>
      </div>

      <div className="card dropzone" onClick={() => inputRef.current?.click()}>
        <input ref={inputRef} type="file" accept=".eml" multiple hidden onChange={pick} />
        <p className="hint">点击选择，或把多个 .eml 放到这里（支持中文文件名）</p>
        {picked.length > 0 && (
          <ul className="file-list">
            {picked.map((f, i) => (
              <li key={i}>
                {f.name}
                <button className="link danger-text"
                        onClick={(e) => { e.stopPropagation();
                          setPicked((p) => p.filter((_, idx) => idx !== i)) }}>
                  移除
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <div className="banner danger">{error}</div>}

      {result && (
        <div className="card">
          <h3>导入结果</h3>
          <div className="stats-pills">
            <span>总计 {result.total}</span>
            <span className="ok-text">新收录 {result.imported}</span>
            <span>重复 {result.duplicate}</span>
            <span className="warn-text">冲突 {result.conflict}</span>
            <span className="danger-text">错误 {result.error}</span>
          </div>
          <table className="grid">
            <thead>
              <tr><th>状态</th><th>文件</th><th>Message-ID</th><th>说明</th></tr>
            </thead>
            <tbody>
              {result.files.map((f, i) => (
                <tr key={i}>
                  <td><span className={`badge ${STATUS_STYLE[f.status] || ''}`}>{f.status}</span></td>
                  <td>{f.filename}</td>
                  <td className="mono small">{f.message_id || '—（按内容散列识别）'}</td>
                  <td className="small">{f.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
