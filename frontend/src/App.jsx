import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import UploadPage from './pages/UploadPage.jsx'
import EmailsPage from './pages/EmailsPage.jsx'
import EmailDetailPage from './pages/EmailDetailPage.jsx'
import AttachmentsPage from './pages/AttachmentsPage.jsx'
import AttachmentDetailPage from './pages/AttachmentDetailPage.jsx'
import AnomaliesPage from './pages/AnomaliesPage.jsx'
import ConflictsPage from './pages/ConflictsPage.jsx'

const TABS = [
  { key: 'upload', label: '批量上传' },
  { key: 'emails', label: '邮件列表' },
  { key: 'attachments', label: '附件' },
  { key: 'anomalies', label: '异常列表' },
  { key: 'conflicts', label: '冲突记录' },
]

export default function App() {
  const [tab, setTab] = useState('upload')
  const [emailId, setEmailId] = useState(null)
  const [attachmentId, setAttachmentId] = useState(null)
  const [stats, setStats] = useState(null)

  const refreshStats = () => api.stats().then(setStats).catch(() => {})
  useEffect(refreshStats, [tab])

  const go = (next) => {
    setEmailId(null)
    setAttachmentId(null)
    setTab(next)
  }

  let view
  if (emailId != null) {
    view = <EmailDetailPage emailId={emailId} onBack={() => setEmailId(null)}
             onOpenAttachment={(id) => setAttachmentId(id)} />
  } else if (attachmentId != null) {
    view = <AttachmentDetailPage attachmentId={attachmentId}
             onBack={() => setAttachmentId(null)}
             onOpenEmail={(id) => { setAttachmentId(null); setEmailId(id) }} />
  } else if (tab === 'upload') {
    view = <UploadPage onDone={() => { refreshStats(); setTab('emails') }} />
  } else if (tab === 'emails') {
    view = <EmailsPage onOpen={(id) => setEmailId(id)} />
  } else if (tab === 'attachments') {
    view = <AttachmentsPage onOpen={(id) => setAttachmentId(id)} />
  } else if (tab === 'anomalies') {
    view = <AnomaliesPage onOpenAttachment={(id) => setAttachmentId(id)} />
  } else {
    view = <ConflictsPage onOpenEmail={(id) => setEmailId(id)} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">📬 邮件接收台</div>
        <nav>
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? 'nav active' : 'nav'}
                    onClick={() => go(t.key)}>{t.label}</button>
          ))}
        </nav>
        {stats && (
          <div className="stats-pills">
            <span title="顶层 + 嵌套邮件总数">邮件 {stats.top_level_emails + stats.nested_emails}</span>
            <span title="投递记录">投递 {stats.deliveries}</span>
            <span title="附件引用（含内嵌图）">附件 {stats.attachments}</span>
            <span title="去重后的附件内容">内容 {stats.unique_contents}</span>
            <span className={stats.anomalies ? 'warn' : ''}>异常 {stats.anomalies}</span>
            <span className={stats.conflicts ? 'warn' : ''}>冲突 {stats.conflicts}</span>
          </div>
        )}
      </header>
      <main className="content">{view}</main>
    </div>
  )
}
