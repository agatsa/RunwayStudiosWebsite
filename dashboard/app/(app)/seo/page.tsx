'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Search, TrendingUp, FileText, Zap, AlertTriangle,
  CheckCircle, Info, ChevronDown, ChevronUp, RefreshCw,
  ExternalLink, Globe, BarChart2,
} from 'lucide-react'
import { toast } from 'sonner'

// ── Types ────────────────────────────────────────────────────────────────────

interface KeywordRow {
  keyword: string
  clicks: number
  impressions: number
  ctr: number
  position: number
}

interface PageRow {
  page: string
  clicks: number
  impressions: number
  ctr: number
  position: number
}

interface AuditIssue {
  severity: 'critical' | 'warning' | 'info'
  title: string
  detail: string
  fix: string
}

interface AuditResult {
  url: string
  audit: {
    overall_score: number
    grade: string
    summary: string
    issues: AuditIssue[]
    strengths: string[]
    quick_wins: string[]
  }
  signals: Record<string, any>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function ScoreBadge({ score, grade }: { score: number; grade: string }) {
  const color = score >= 80 ? 'bg-green-100 text-green-700' :
                score >= 60 ? 'bg-yellow-100 text-yellow-700' :
                              'bg-red-100 text-red-700'
  return (
    <div className={`flex items-center gap-2 rounded-xl px-4 py-2 ${color}`}>
      <span className="text-3xl font-bold">{score}</span>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide">SEO Score</p>
        <p className="text-xl font-bold leading-none">Grade {grade}</p>
      </div>
    </div>
  )
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'critical') return <AlertTriangle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
  if (severity === 'warning')  return <AlertTriangle className="h-4 w-4 text-yellow-500 shrink-0 mt-0.5" />
  return <Info className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
}

function PositionBadge({ pos }: { pos: number }) {
  const color = pos <= 3  ? 'bg-green-100 text-green-700' :
                pos <= 10 ? 'bg-blue-100 text-blue-700' :
                pos <= 20 ? 'bg-yellow-100 text-yellow-700' :
                            'bg-gray-100 text-gray-500'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${color}`}>
      #{Math.round(pos)}
    </span>
  )
}

// ── On-Page Auditor ───────────────────────────────────────────────────────────

function OnPageAuditor({ wsId }: { wsId: string }) {
  const [url, setUrl]         = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState<AuditResult | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [sending, setSending] = useState<number | null>(null)
  const [sent, setSent]       = useState<Set<number>>(new Set())

  const audit = async () => {
    if (!url.trim()) return
    setLoading(true)
    setResult(null)
    try {
      const r = await fetch('/api/seo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'audit', url: url.trim(), workspace_id: wsId }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail ?? 'Audit failed')
      setResult(d)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Audit failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
      <div>
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Zap className="h-4 w-4 text-indigo-500" />
          On-Page Auditor
        </h3>
        <p className="text-xs text-gray-500 mt-0.5">
          AI scans any URL — title, meta, headings, schema, images — and gives a scored report with fixes.
        </p>
      </div>

      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && audit()}
          placeholder="https://yourstore.com/products/product-name"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <button
          onClick={audit}
          disabled={loading || !url.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 shrink-0"
        >
          {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Audit
        </button>
      </div>

      {result && (
        <div className="space-y-4 pt-2 border-t border-gray-100">
          {/* Score + summary */}
          <div className="flex items-start gap-4 flex-wrap">
            <ScoreBadge score={result.audit.overall_score} grade={result.audit.grade} />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-700">{result.audit.summary}</p>
              <a href={result.url} target="_blank" rel="noopener noreferrer"
                 className="text-xs text-indigo-500 hover:underline flex items-center gap-1 mt-1">
                <ExternalLink className="h-3 w-3" /> {result.url}
              </a>
            </div>
          </div>

          {/* Quick wins */}
          {result.audit.quick_wins?.length > 0 && (
            <div className="rounded-lg bg-indigo-50 p-3">
              <p className="text-xs font-semibold text-indigo-700 mb-2">⚡ Quick Wins</p>
              <ul className="space-y-1">
                {result.audit.quick_wins.map((w, i) => (
                  <li key={i} className="text-xs text-indigo-800 flex items-start gap-1.5">
                    <span className="font-bold mt-0.5">→</span> {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Strengths */}
          {result.audit.strengths?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 mb-1.5">Strengths</p>
              <div className="flex flex-wrap gap-1.5">
                {result.audit.strengths.map((s, i) => (
                  <span key={i} className="flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-xs text-green-700">
                    <CheckCircle className="h-3 w-3" /> {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Issues */}
          {result.audit.issues?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 mb-1.5">Issues ({result.audit.issues.length})</p>
              <div className="space-y-2">
                {result.audit.issues.map((issue, i) => (
                  <div key={i}
                    className={`rounded-lg border p-3 cursor-pointer ${
                      issue.severity === 'critical' ? 'border-red-200 bg-red-50' :
                      issue.severity === 'warning'  ? 'border-yellow-200 bg-yellow-50' :
                                                      'border-blue-100 bg-blue-50'
                    }`}
                    onClick={() => setExpanded(expanded === i ? null : i)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-start gap-2">
                        <SeverityIcon severity={issue.severity} />
                        <span className="text-sm font-medium text-gray-800">{issue.title}</span>
                      </div>
                      {expanded === i ? <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" /> :
                                        <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />}
                    </div>
                    {expanded === i && (
                      <div className="mt-2 pt-2 border-t border-gray-200 space-y-2">
                        <p className="text-xs text-gray-600">{issue.detail}</p>
                        <p className="text-xs font-medium text-gray-700">Fix: {issue.fix}</p>
                        <button
                          onClick={async (e) => {
                            e.stopPropagation()
                            setSending(i)
                            try {
                              const r = await fetch('/api/seo/approvals', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ workspace_id: wsId, issue, url: result!.url, signals: result!.signals }),
                              })
                              if (r.ok) { setSent(prev => { const s = new Set(prev); s.add(i); return s }); toast.success('Sent to Approvals!') }
                              else toast.error('Failed to send')
                            } catch { toast.error('Failed to send') }
                            finally { setSending(null) }
                          }}
                          disabled={sending === i || sent.has(i)}
                          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {sending === i ? <RefreshCw className="h-3 w-3 animate-spin" /> : sent.has(i) ? <CheckCircle className="h-3 w-3" /> : <Zap className="h-3 w-3" />}
                          {sent.has(i) ? 'Sent to Approvals' : 'Generate Fix & Send to Approvals'}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Raw signals */}
          <details className="text-xs text-gray-400">
            <summary className="cursor-pointer hover:text-gray-600">Raw signals</summary>
            <pre className="mt-2 overflow-x-auto rounded bg-gray-50 p-2 text-[10px]">
              {JSON.stringify(result.signals, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  )
}

// ── Keywords Table ────────────────────────────────────────────────────────────

function KeywordsTable({ keywords }: { keywords: KeywordRow[] }) {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<keyof KeywordRow>('clicks')
  const [dir, setDir] = useState<'asc'|'desc'>('desc')

  const filtered = keywords
    .filter(k => k.keyword.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => dir === 'desc' ? (b[sort] as number) - (a[sort] as number) : (a[sort] as number) - (b[sort] as number))

  const toggleSort = (col: keyof KeywordRow) => {
    if (sort === col) setDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSort(col); setDir('desc') }
  }

  const Th = ({ col, label }: { col: keyof KeywordRow; label: string }) => (
    <th
      onClick={() => toggleSort(col)}
      className="cursor-pointer select-none whitespace-nowrap px-3 py-2 text-left text-xs font-semibold text-gray-500 hover:text-gray-800"
    >
      {label} {sort === col ? (dir === 'desc' ? '↓' : '↑') : ''}
    </th>
  )

  return (
    <div className="space-y-3">
      <input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Filter keywords…"
        className="w-full max-w-xs rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />
      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <Th col="keyword"     label="Keyword" />
              <Th col="clicks"      label="Clicks" />
              <Th col="impressions" label="Impressions" />
              <Th col="ctr"         label="CTR %" />
              <Th col="position"    label="Position" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.slice(0, 50).map((k, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-medium text-gray-800">{k.keyword}</td>
                <td className="px-3 py-2 text-gray-600">{k.clicks.toLocaleString()}</td>
                <td className="px-3 py-2 text-gray-500">{k.impressions.toLocaleString()}</td>
                <td className="px-3 py-2 text-gray-500">{k.ctr}%</td>
                <td className="px-3 py-2"><PositionBadge pos={k.position} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="p-6 text-center text-sm text-gray-400">No keywords found</p>
        )}
      </div>
    </div>
  )
}

// ── Pages Table ───────────────────────────────────────────────────────────────

function PagesTable({ pages }: { pages: PageRow[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Page URL</th>
            <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Clicks</th>
            <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Impressions</th>
            <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">CTR %</th>
            <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Position</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {pages.map((p, i) => (
            <tr key={i} className="hover:bg-gray-50">
              <td className="px-3 py-2 max-w-xs">
                <a href={p.page} target="_blank" rel="noopener noreferrer"
                   className="text-indigo-600 hover:underline truncate block text-xs">
                  {p.page.replace(/^https?:\/\/[^/]+/, '') || '/'}
                </a>
              </td>
              <td className="px-3 py-2 text-gray-600">{p.clicks.toLocaleString()}</td>
              <td className="px-3 py-2 text-gray-500">{p.impressions.toLocaleString()}</td>
              <td className="px-3 py-2 text-gray-500">{p.ctr}%</td>
              <td className="px-3 py-2"><PositionBadge pos={p.position} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {pages.length === 0 && (
        <p className="p-6 text-center text-sm text-gray-400">No page data yet</p>
      )}
    </div>
  )
}

// ── Backlinks Tab ─────────────────────────────────────────────────────────────

interface Backlink {
  id: string
  source_url: string
  source_domain: string
  target_url: string
  anchor_text: string
  status: string
  domain_authority: number | null
  notes: string
  created_at: string | null
}

const STATUS_COLORS: Record<string, string> = {
  prospect:       'bg-gray-100 text-gray-600',
  outreach_sent:  'bg-blue-100 text-blue-700',
  acquired:       'bg-green-100 text-green-700',
  lost:           'bg-red-100 text-red-600',
  rejected:       'bg-orange-100 text-orange-600',
}

function BacklinksTab({ wsId }: { wsId: string }) {
  const [backlinks, setBacklinks] = useState<Backlink[]>([])
  const [loading, setLoading]     = useState(true)
  const [adding, setAdding]       = useState(false)
  const [newUrl, setNewUrl]       = useState('')
  const [newStatus, setNewStatus] = useState('prospect')
  const [newAnchor, setNewAnchor] = useState('')
  const [newNotes, setNewNotes]   = useState('')

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/seo/backlinks?workspace_id=${wsId}`)
      const d = await r.json()
      setBacklinks(d.backlinks ?? [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [wsId])

  useEffect(() => { load() }, [load])

  const addBacklink = async () => {
    if (!newUrl.trim()) return
    setAdding(true)
    try {
      const r = await fetch('/api/seo/backlinks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, source_url: newUrl.trim(), status: newStatus, anchor_text: newAnchor, notes: newNotes }),
      })
      if (r.ok) { setNewUrl(''); setNewAnchor(''); setNewNotes(''); toast.success('Backlink added'); load() }
      else toast.error('Failed to add')
    } catch { toast.error('Failed to add') }
    setAdding(false)
  }

  const updateStatus = async (id: string, status: string) => {
    await fetch(`/api/seo/backlinks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, status }),
    })
    setBacklinks(prev => prev.map(b => b.id === id ? { ...b, status } : b))
  }

  const deleteBacklink = async (id: string) => {
    await fetch(`/api/seo/backlinks/${id}?workspace_id=${wsId}`, { method: 'DELETE' })
    setBacklinks(prev => prev.filter(b => b.id !== id))
    toast.success('Removed')
  }

  const counts = {
    acquired: backlinks.filter(b => b.status === 'acquired').length,
    outreach_sent: backlinks.filter(b => b.status === 'outreach_sent').length,
    prospect: backlinks.filter(b => b.status === 'prospect').length,
  }

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Acquired', value: counts.acquired, color: 'text-green-600' },
          { label: 'Outreach Sent', value: counts.outreach_sent, color: 'text-blue-600' },
          { label: 'Prospects', value: counts.prospect, color: 'text-gray-600' },
        ].map(s => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4 text-center">
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Info banner */}
      <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 flex items-start gap-2">
        <Info className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
        <span><strong>Backlinks</strong> are links from other websites pointing to yours — the #1 off-page ranking factor. Track your outreach and link-building progress here. For automated discovery, use the <strong>Off-Page</strong> tab to get AI-suggested targets.</span>
      </div>

      {/* Add form */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-800">Add Backlink / Prospect</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <input value={newUrl} onChange={e => setNewUrl(e.target.value)} placeholder="https://healthline.com/article/..." className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
          <input value={newAnchor} onChange={e => setNewAnchor(e.target.value)} placeholder="Anchor text (e.g. ECG monitor)" className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>
        <div className="flex gap-2 flex-wrap">
          <select value={newStatus} onChange={e => setNewStatus(e.target.value)} className="rounded-lg border border-gray-200 px-2 py-2 text-sm focus:outline-none">
            <option value="prospect">Prospect</option>
            <option value="outreach_sent">Outreach Sent</option>
            <option value="acquired">Acquired ✅</option>
            <option value="rejected">Rejected</option>
            <option value="lost">Lost</option>
          </select>
          <input value={newNotes} onChange={e => setNewNotes(e.target.value)} placeholder="Notes (optional)" className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none" />
          <button onClick={addBacklink} disabled={adding || !newUrl.trim()} className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {adding ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null} Add
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-8 text-sm text-gray-400"><RefreshCw className="h-4 w-4 animate-spin mr-2" /> Loading…</div>
      ) : backlinks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 p-10 text-center">
          <p className="text-sm text-gray-500">No backlinks tracked yet.</p>
          <p className="text-xs text-gray-400 mt-1">Go to <strong>Off-Page</strong> tab to get AI-suggested link-building targets.</p>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Source Domain</th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Anchor Text</th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Notes</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {backlinks.map(b => (
                <tr key={b.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <a href={b.source_url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline text-xs font-medium">{b.source_domain || b.source_url}</a>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600">{b.anchor_text || '—'}</td>
                  <td className="px-3 py-2">
                    <select value={b.status} onChange={e => updateStatus(b.id, e.target.value)}
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold border-0 focus:outline-none cursor-pointer ${STATUS_COLORS[b.status] || 'bg-gray-100 text-gray-600'}`}>
                      <option value="prospect">Prospect</option>
                      <option value="outreach_sent">Outreach Sent</option>
                      <option value="acquired">Acquired ✅</option>
                      <option value="rejected">Rejected</option>
                      <option value="lost">Lost</option>
                    </select>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500 max-w-xs truncate">{b.notes || '—'}</td>
                  <td className="px-3 py-2">
                    <button onClick={() => deleteBacklink(b.id)} className="text-xs text-red-400 hover:text-red-600">Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


// ── Off-Page Tab ──────────────────────────────────────────────────────────────

function OffPageTab({ wsId, activeSite }: { wsId: string; activeSite: string }) {
  const [plan, setPlan]       = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [createdAt, setCreatedAt]   = useState<string | null>(null)

  const loadLatest = useCallback(async () => {
    try {
      const r = await fetch(`/api/seo/offpage?workspace_id=${wsId}`)
      const d = await r.json()
      if (d.plan) { setPlan(d.plan); setCreatedAt(d.created_at ?? null) }
    } catch { /* ignore */ }
    setLoading(false)
  }, [wsId])

  useEffect(() => { loadLatest() }, [loadLatest])

  const generate = async () => {
    setGenerating(true)
    try {
      const r = await fetch('/api/seo/offpage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, active_site: activeSite }),
      })
      const d = await r.json()
      if (r.ok && d.plan) { setPlan(d.plan); setCreatedAt(new Date().toISOString()); toast.success('Off-page strategy generated!') }
      else toast.error(d.detail ?? 'Failed to generate')
    } catch { toast.error('Failed to generate') }
    setGenerating(false)
  }

  const PRIORITY_COLOR: Record<string, string> = {
    high: 'bg-red-100 text-red-700',
    medium: 'bg-yellow-100 text-yellow-700',
    low: 'bg-gray-100 text-gray-500',
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h3 className="font-semibold text-gray-900">Off-Page SEO Strategy</h3>
          <p className="text-xs text-gray-500 mt-0.5">AI-generated backlink targets, PR opportunities, and outreach plan specific to your niche.</p>
          {createdAt && <p className="text-xs text-gray-400 mt-0.5">Generated {new Date(createdAt).toLocaleDateString()}</p>}
        </div>
        <button onClick={generate} disabled={generating}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {generating ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
          {plan ? 'Regenerate' : 'Generate Strategy'} {!plan && '(AI)'}
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-10 text-sm text-gray-400"><RefreshCw className="h-4 w-4 animate-spin mr-2" /> Loading…</div>
      ) : generating ? (
        <div className="flex flex-col items-center gap-3 py-16 text-gray-500">
          <RefreshCw className="h-8 w-8 animate-spin text-indigo-400" />
          <p className="text-sm font-medium">Analysing your niche and generating strategy…</p>
          <p className="text-xs text-gray-400">This takes ~15 seconds</p>
        </div>
      ) : !plan ? (
        <div className="rounded-xl border border-dashed border-gray-200 p-12 text-center space-y-3">
          <Globe className="h-10 w-10 mx-auto text-gray-300" />
          <p className="text-sm font-medium text-gray-700">No off-page strategy yet</p>
          <p className="text-xs text-gray-400">Click Generate Strategy — AI will analyse your niche and suggest specific websites for backlinks, guest posts, PR, and more.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Summary */}
          <div className="rounded-xl bg-indigo-50 border border-indigo-100 p-4">
            <p className="text-sm text-indigo-800">{plan.summary}</p>
          </div>

          {/* Quick wins */}
          {plan.quick_wins?.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-800 mb-3">⚡ Quick Wins — Do These This Week</p>
              <div className="space-y-2">
                {plan.quick_wins.map((w: any, i: number) => (
                  <div key={i} className="flex items-start gap-3 rounded-lg bg-gray-50 p-3">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-bold text-white shrink-0 mt-0.5">{i+1}</span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800">{w.action}</p>
                      <p className="text-xs text-indigo-600 font-medium">{w.target}</p>
                      <p className="text-xs text-gray-500">{w.why}</p>
                    </div>
                    <button
                      onClick={async () => {
                        const r = await fetch('/api/seo/backlinks', {
                          method: 'POST', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ workspace_id: wsId, source_url: w.target.startsWith('http') ? w.target : `https://${w.target}`, status: 'prospect', notes: w.action }),
                        })
                        if (r.ok) toast.success('Added to Backlinks tracker')
                      }}
                      className="shrink-0 text-xs text-indigo-600 hover:underline whitespace-nowrap"
                    >+ Track</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Strategies */}
          {plan.strategies?.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-800 mb-3">Link Building Strategies</p>
              <div className="space-y-3">
                {plan.strategies.map((s: any, i: number) => (
                  <div key={i} className="rounded-lg border border-gray-100 p-4">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="flex items-start gap-2">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide shrink-0 mt-0.5 ${PRIORITY_COLOR[s.priority] || 'bg-gray-100 text-gray-500'}`}>{s.priority}</span>
                        <div>
                          <p className="text-sm font-semibold text-gray-800">{s.title}</p>
                          <p className="text-xs text-indigo-500 font-medium uppercase tracking-wide">{s.category}</p>
                        </div>
                      </div>
                      <div className="flex gap-2 text-xs text-gray-400">
                        <span>⏱ {s.effort}</span>
                      </div>
                    </div>
                    <p className="text-xs text-gray-600 mt-2">{s.description}</p>
                    <p className="text-xs text-green-700 mt-1">📈 {s.expected_impact}</p>
                    {s.targets?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {s.targets.map((t: string, ti: number) => (
                          <button key={ti}
                            onClick={async () => {
                              const r = await fetch('/api/seo/backlinks', {
                                method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ workspace_id: wsId, source_url: t.startsWith('http') ? t : `https://${t}`, status: 'prospect', notes: s.title }),
                              })
                              if (r.ok) toast.success(`${t} added to tracker`)
                            }}
                            className="rounded-full bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 text-xs text-indigo-700 hover:bg-indigo-100 transition-colors"
                          >{t}</button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Outreach template */}
          {plan.outreach_template && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-800 mb-2">📧 Outreach Email Template</p>
              <pre className="text-xs text-gray-600 whitespace-pre-wrap bg-gray-50 rounded-lg p-3">{plan.outreach_template}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Automate Tab ──────────────────────────────────────────────────────────────

function AutomateTab({ wsId }: { wsId: string }) {
  const [shopifyIssues, setShopifyIssues]   = useState<any[]>([])
  const [wpIssues, setWpIssues]             = useState<any[]>([])
  const [shopifyConnected, setShopifyConnected] = useState(false)
  const [wpConnected, setWpConnected]       = useState(false)
  const [wpUrl, setWpUrl]                   = useState('')
  const [wpUser, setWpUser]                 = useState('')
  const [wpPass, setWpPass]                 = useState('')
  const [scanning, setScanning]             = useState(false)
  const [fixingAlts, setFixingAlts]         = useState(false)
  const [connecting, setConnecting]         = useState(false)
  const [pushing, setPushing]               = useState<string | null>(null)
  const [schemaProduct, setSchemaProduct]   = useState<any>(null)
  const [showSchema, setShowSchema]         = useState(false)
  const [loading, setLoading]               = useState(true)

  useEffect(() => {
    const init = async () => {
      try {
        const [shopR, wpR] = await Promise.all([
          fetch(`/api/shopify/status?workspace_id=${wsId}`),
          fetch(`/api/seo/wordpress?workspace_id=${wsId}&action=status`),
        ])
        const shopD = await shopR.json()
        const wpD = await wpR.json()
        setShopifyConnected(shopD.connected ?? false)
        setWpConnected(wpD.connected ?? false)
      } catch { /* ignore */ }
      setLoading(false)
    }
    init()
  }, [wsId])

  const scanShopify = async () => {
    setScanning(true)
    try {
      const r = await fetch(`/api/seo/shopify?workspace_id=${wsId}&action=scan`)
      const d = await r.json()
      if (r.ok) { setShopifyIssues(d.issues ?? []); toast.success(`Scanned ${d.products_scanned} products`) }
      else toast.error(d.detail ?? 'Scan failed')
    } catch { toast.error('Scan failed') }
    setScanning(false)
  }

  const fixAllAlts = async () => {
    setFixingAlts(true)
    try {
      const r = await fetch('/api/seo/shopify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, action: 'fix-alts' }),
      })
      const d = await r.json()
      if (r.ok) toast.success(`Fixed alt text on ${d.fixed} images!`)
      else toast.error(d.detail ?? 'Failed')
    } catch { toast.error('Failed') }
    setFixingAlts(false)
  }

  const pushShopifyFix = async (productId: number, fixType: string, value: string, imageId?: number) => {
    const key = `${productId}-${fixType}`
    setPushing(key)
    try {
      const r = await fetch('/api/seo/shopify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, action: 'push-fix', product_id: productId, fix_type: fixType, value, image_id: imageId }),
      })
      if (r.ok) {
        toast.success('Pushed to Shopify live!')
        setShopifyIssues(prev => prev.map(p => p.product_id === productId
          ? { ...p, issues: p.issues.filter((i: any) => i.type !== fixType) }
          : p
        ).filter(p => p.issues.length > 0))
      } else {
        const d = await r.json()
        toast.error(d.detail ?? 'Push failed')
      }
    } catch { toast.error('Push failed') }
    setPushing(null)
  }

  const generateSchema = async (productId: number) => {
    try {
      const r = await fetch('/api/seo/shopify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, action: 'generate-schema', product_id: productId }),
      })
      const d = await r.json()
      if (r.ok) { setSchemaProduct(d); setShowSchema(true) }
      else toast.error(d.detail ?? 'Failed')
    } catch { toast.error('Failed') }
  }

  const connectWordPress = async () => {
    if (!wpUrl || !wpUser || !wpPass) { toast.error('Fill all fields'); return }
    setConnecting(true)
    try {
      const r = await fetch('/api/seo/wordpress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', workspace_id: wsId, wp_url: wpUrl, wp_username: wpUser, app_password: wpPass }),
      })
      const d = await r.json()
      if (r.ok) { setWpConnected(true); toast.success(`WordPress connected as ${d.user}`) }
      else toast.error(d.detail ?? 'Connection failed')
    } catch { toast.error('Connection failed') }
    setConnecting(false)
  }

  const scanWordPress = async () => {
    setScanning(true)
    try {
      const r = await fetch(`/api/seo/wordpress?workspace_id=${wsId}&action=scan`)
      const d = await r.json()
      if (r.ok) { setWpIssues(d.issues ?? []); toast.success(`Found ${d.total} issues`) }
      else toast.error(d.detail ?? 'Scan failed')
    } catch { toast.error('Scan failed') }
    setScanning(false)
  }

  if (loading) return <div className="flex justify-center py-12 text-gray-400"><RefreshCw className="h-5 w-5 animate-spin" /></div>

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="rounded-xl bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-100 p-5">
        <h3 className="font-semibold text-gray-900 text-base">SEO Automation</h3>
        <p className="text-sm text-gray-600 mt-1">AI scans your website, generates fixes, and pushes them live — no copy-pasting needed.</p>
        <div className="flex flex-wrap gap-3 mt-3 text-xs">
          {[
            { label: 'Meta titles & descriptions', done: true },
            { label: 'Image alt text (bulk)', done: true },
            { label: 'Product schema markup', done: true },
            { label: 'WordPress direct push', done: true },
            { label: 'Webflow (coming soon)', done: false },
          ].map(f => (
            <span key={f.label} className={`flex items-center gap-1 rounded-full px-2.5 py-1 font-medium ${f.done ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
              {f.done ? <CheckCircle className="h-3 w-3" /> : <Info className="h-3 w-3" />} {f.label}
            </span>
          ))}
        </div>
      </div>

      {/* Shopify Section */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <div className={`h-2.5 w-2.5 rounded-full ${shopifyConnected ? 'bg-green-500' : 'bg-gray-300'}`} />
            <h4 className="font-semibold text-gray-900">Shopify</h4>
            {shopifyConnected && <span className="text-xs text-green-600 font-medium">Connected</span>}
          </div>
          {shopifyConnected ? (
            <div className="flex gap-2 flex-wrap">
              <button onClick={fixAllAlts} disabled={fixingAlts}
                className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">
                {fixingAlts ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                Fix All Alt Text
              </button>
              <button onClick={scanShopify} disabled={scanning}
                className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                {scanning ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
                Scan Products
              </button>
            </div>
          ) : (
            <a href={`/settings?ws=${wsId}`} className="text-xs text-indigo-600 hover:underline">Connect Shopify in Settings →</a>
          )}
        </div>

        {shopifyIssues.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs font-semibold text-gray-500">{shopifyIssues.length} products need SEO fixes</p>
            {shopifyIssues.map(p => (
              <div key={p.product_id} className="rounded-lg border border-gray-100 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-gray-800 truncate">{p.product_title}</p>
                  <button onClick={() => generateSchema(p.product_id)} className="text-xs text-indigo-600 hover:underline shrink-0">Schema →</button>
                </div>
                {p.issues.map((issue: any) => (
                  <ShopifyFixRow key={issue.type} issue={issue} product={p}
                    pushing={pushing} onPush={pushShopifyFix} wsId={wsId} />
                ))}
              </div>
            ))}
          </div>
        )}

        {shopifyConnected && shopifyIssues.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-4">Click &quot;Scan Products&quot; to find SEO issues</p>
        )}
      </div>

      {/* Schema Modal */}
      {showSchema && schemaProduct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white p-5 space-y-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">Schema Markup — {schemaProduct.product_title}</h3>
              <button onClick={() => setShowSchema(false)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-xs font-semibold text-gray-500 mb-1">Option 1 — Google Tag Manager (paste in GTM Custom HTML tag)</p>
                <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">{schemaProduct.gtm_snippet}</pre>
                <button onClick={() => { navigator.clipboard.writeText(schemaProduct.gtm_snippet); toast.success('Copied!') }}
                  className="mt-1 text-xs text-indigo-600 hover:underline">Copy GTM snippet</button>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-500 mb-1">Option 2 — Shopify Theme (add to product.liquid)</p>
                <pre className="text-xs bg-gray-50 rounded-lg p-3 overflow-x-auto text-gray-700">{schemaProduct.shopify_liquid}</pre>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* WordPress Section */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
        <div className="flex items-center gap-2">
          <div className={`h-2.5 w-2.5 rounded-full ${wpConnected ? 'bg-green-500' : 'bg-gray-300'}`} />
          <h4 className="font-semibold text-gray-900">WordPress</h4>
          {wpConnected && <span className="text-xs text-green-600 font-medium">Connected</span>}
        </div>

        {!wpConnected ? (
          <div className="space-y-3">
            <p className="text-xs text-gray-500">Connect your WordPress site to auto-push title tags, meta descriptions, and alt text fixes directly.</p>
            <div className="grid gap-2 sm:grid-cols-3">
              <input value={wpUrl} onChange={e => setWpUrl(e.target.value)} placeholder="https://yoursite.com" className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
              <input value={wpUser} onChange={e => setWpUser(e.target.value)} placeholder="WordPress username" className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
              <input value={wpPass} onChange={e => setWpPass(e.target.value)} placeholder="Application password" type="password" className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
            </div>
            <div className="flex items-start gap-2">
              <button onClick={connectWordPress} disabled={connecting}
                className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                {connecting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null} Connect WordPress
              </button>
              <p className="text-xs text-gray-400 mt-2">Get Application Password: WordPress Admin → Users → Profile → Application Passwords</p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <button onClick={scanWordPress} disabled={scanning}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {scanning ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />} Scan Posts &amp; Pages
            </button>
            {wpIssues.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-gray-500">{wpIssues.length} posts/pages need SEO fixes</p>
                {wpIssues.map(p => (
                  <div key={p.post_id} className="rounded-lg border border-gray-100 p-3 space-y-2">
                    <p className="text-sm font-medium text-gray-800 truncate">{p.title}</p>
                    {p.issues.map((issue: any) => (
                      <WPFixRow key={issue.type} issue={issue} post={p} wsId={wsId} />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* GTM Info */}
      <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 space-y-2">
        <p className="text-sm font-semibold text-amber-800">Other platforms (Lovable, PHP, custom sites)</p>
        <p className="text-xs text-amber-700">For platforms without an API, use the <strong>Schema →</strong> button on any Shopify product to get a ready-to-paste GTM tag. If GTM is installed on your custom site, paste it there — schema goes live without touching code.</p>
        <p className="text-xs text-amber-600 font-medium">For title/meta fixes on non-Shopify sites → use the On-Page Audit tab → &quot;Generate Fix &amp; Send to Approvals&quot; → copy the fix text from the Approvals page.</p>
      </div>
    </div>
  )
}

// Helper components for fix rows
function ShopifyFixRow({ issue, product, pushing, onPush, wsId }: any) {
  const [editValue, setEditValue] = useState(
    issue.type === 'seo_title' ? product.seo_title :
    issue.type === 'seo_desc' ? product.seo_desc : ''
  )
  const key = `${product.product_id}-${issue.type}`

  if (issue.type === 'alt_text') {
    return (
      <div className="text-xs text-amber-700 bg-amber-50 rounded p-2">
        {issue.detail} — use &quot;Fix All Alt Text&quot; button above to auto-fix all at once.
      </div>
    )
  }

  return (
    <div className="flex items-start gap-2">
      <div className={`mt-1 h-1.5 w-1.5 rounded-full shrink-0 ${issue.severity === 'critical' ? 'bg-red-500' : 'bg-yellow-400'}`} />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-500 mb-1">{issue.detail}</p>
        <div className="flex gap-2">
          <input value={editValue} onChange={e => setEditValue(e.target.value)}
            className="flex-1 rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
            placeholder={issue.type === 'seo_title' ? 'New SEO title (50-60 chars)' : 'New meta description (140-160 chars)'}
          />
          <button
            onClick={() => onPush(product.product_id, issue.type, editValue)}
            disabled={pushing === key || !editValue.trim()}
            className="shrink-0 flex items-center gap-1 rounded bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {pushing === key ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
            Push Live
          </button>
        </div>
      </div>
    </div>
  )
}

function WPFixRow({ issue, post, wsId }: any) {
  const [editValue, setEditValue] = useState(issue.type === 'seo_title' ? post.seo_title : post.seo_desc)
  const [pushing, setPushing] = useState(false)
  const [done, setDone] = useState(false)

  const push = async () => {
    setPushing(true)
    try {
      const r = await fetch('/api/seo/wordpress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'push-fix', workspace_id: wsId, post_id: post.post_id, fix_type: issue.type, value: editValue, post_type: post.post_type }),
      })
      if (r.ok) { setDone(true); toast.success('Pushed to WordPress!') }
      else { const d = await r.json(); toast.error(d.detail ?? 'Failed') }
    } catch { toast.error('Failed') }
    setPushing(false)
  }

  if (done) return <p className="text-xs text-green-600 font-medium">✓ Pushed to WordPress</p>

  return (
    <div className="flex items-start gap-2">
      <div className={`mt-1 h-1.5 w-1.5 rounded-full shrink-0 ${issue.severity === 'critical' ? 'bg-red-500' : 'bg-yellow-400'}`} />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-500 mb-1">{issue.detail}</p>
        <div className="flex gap-2">
          <input value={editValue} onChange={e => setEditValue(e.target.value)}
            className="flex-1 rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
          <button onClick={push} disabled={pushing || !editValue.trim()}
            className="shrink-0 flex items-center gap-1 rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {pushing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />} Push
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SEOPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <SEOContent />
    </Suspense>
  )
}

function SEOContent() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''

  const [tab, setTab]           = useState<'keywords'|'pages'|'backlinks'|'offpage'|'audit'|'automate'>('keywords')
  const [days, setDays]         = useState(28)
  const [status, setStatus]     = useState<any>(null)
  const [keywords, setKeywords] = useState<KeywordRow[]>([])
  const [pages, setPages]       = useState<PageRow[]>([])
  const [devices, setDevices]   = useState<any[]>([])
  const [loading, setLoading]   = useState(true)
  const [activeSite, setActiveSite] = useState('')

  const loadStatus = useCallback(async () => {
    if (!wsId) return
    try {
      const r = await fetch(`/api/seo?action=status&workspace_id=${wsId}`)
      const d = await r.json()
      if (r.ok) { setStatus(d); setActiveSite(d.active_site ?? '') }
    } catch { /* ignore */ }
    setLoading(false)
  }, [wsId])

  const loadKeywords = useCallback(async (site = activeSite) => {
    if (!wsId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/seo?action=keywords&workspace_id=${wsId}&days=${days}${site ? `&site_url=${encodeURIComponent(site)}` : ''}`)
      const d = await r.json()
      if (r.ok) setKeywords(d.keywords ?? [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [wsId, days, activeSite])

  const loadPages = useCallback(async (site = activeSite) => {
    if (!wsId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/seo?action=pages&workspace_id=${wsId}&days=${days}${site ? `&site_url=${encodeURIComponent(site)}` : ''}`)
      const d = await r.json()
      if (r.ok) { setPages(d.pages ?? []); setDevices(d.devices ?? []) }
    } catch { /* ignore */ }
    setLoading(false)
  }, [wsId, days, activeSite])

  useEffect(() => { loadStatus() }, [loadStatus])

  useEffect(() => {
    if (!status?.gsc_ready) return
    if (tab === 'keywords') loadKeywords()
    else if (tab === 'pages') loadPages()
  }, [tab, days, status])

  const switchSite = async (siteUrl: string) => {
    setActiveSite(siteUrl)
    await fetch('/api/seo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'set-site', workspace_id: wsId, site_url: siteUrl }),
    })
    if (tab === 'keywords') loadKeywords(siteUrl)
    else loadPages(siteUrl)
  }

  // ── Google not connected at all ──────────────────────────────────────────
  if (!loading && status && !status.connected) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16 text-center space-y-4">
        <Globe className="h-12 w-12 mx-auto text-gray-300" />
        <h2 className="text-xl font-bold text-gray-800">Connect Google Account</h2>
        <p className="text-sm text-gray-500">
          Go to <strong>Settings</strong> and connect your Google account to enable SEO data.
        </p>
        <a
          href={`/settings?ws=${wsId}`}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Go to Settings
        </a>
        <div className="mt-8 text-left">
          <OnPageAuditor wsId={wsId} />
        </div>
      </div>
    )
  }

  const totalClicks      = keywords.reduce((s, k) => s + k.clicks, 0)
  const totalImpressions = keywords.reduce((s, k) => s + k.impressions, 0)
  const avgPosition      = keywords.length
    ? keywords.reduce((s, k) => s + k.position, 0) / keywords.length
    : 0
  const top10Keywords = keywords.filter(k => k.position <= 10).length

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Search className="h-6 w-6 text-indigo-500" />
            SEO Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Organic search performance from Google Search Console
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Site picker */}
          {status?.sites?.length > 1 && (
            <select
              value={activeSite}
              onChange={e => switchSite(e.target.value)}
              className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:outline-none"
            >
              {status.sites.map((s: any) => (
                <option key={s.url} value={s.url}>{s.url}</option>
              ))}
            </select>
          )}
          {activeSite && (
            <span className="text-xs text-gray-500 flex items-center gap-1">
              <Globe className="h-3 w-3" /> {activeSite.replace('sc-domain:', '')}
            </span>
          )}
          {/* Days filter */}
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:outline-none"
          >
            {[7, 14, 28, 90].map(d => (
              <option key={d} value={d}>Last {d} days</option>
            ))}
          </select>
        </div>
      </div>

      {/* GSC setup guide when Google is connected but no verified sites */}
      {status?.connected && !status?.gsc_ready && (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-5 space-y-4">
          <div className="flex items-start gap-3">
            <Globe className="h-5 w-5 text-indigo-500 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-indigo-900">One more step to unlock keyword &amp; page rankings</p>
              <p className="text-sm text-indigo-700 mt-0.5">
                Keywords and page data come from Google Search Console. Your Google account is connected but hasn't granted Search Console access yet.
              </p>
            </div>
          </div>

          {/* Primary action */}
          <div className="rounded-lg bg-white border border-indigo-200 p-4 flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="font-medium text-gray-900 text-sm">Already have Search Console set up?</p>
              <p className="text-xs text-gray-500 mt-0.5">Just reconnect your Google account — takes 30 seconds. Your existing verified site will be picked up automatically.</p>
            </div>
            <a
              href={`/api/google/oauth/start?ws=${wsId}`}
              className="shrink-0 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Reconnect Google
            </a>
          </div>

          {/* Secondary: not set up yet */}
          <details className="rounded-lg bg-white border border-gray-100">
            <summary className="px-4 py-3 text-sm font-medium text-gray-700 cursor-pointer select-none">
              Don't have Search Console yet? Set it up →
            </summary>
            <div className="px-4 pb-4 grid gap-3 sm:grid-cols-3 mt-2">
              {[
                {
                  step: '1', title: 'Open Search Console',
                  desc: 'Go to search.google.com/search-console and sign in with the same Google account.',
                  href: 'https://search.google.com/search-console', cta: 'Open Search Console →',
                },
                {
                  step: '2', title: 'Add your property',
                  desc: 'Click "+ Add property", enter your domain (e.g. yourstore.com), choose "Domain" type.',
                  href: null, cta: null,
                },
                {
                  step: '3', title: 'Verify via DNS',
                  desc: 'Add the TXT record Google gives you to your domain registrar (GoDaddy / Namecheap), then click Verify.',
                  href: 'https://support.google.com/webmasters/answer/9008080', cta: 'Verification guide →',
                },
              ].map(({ step, title, desc, href, cta }) => (
                <div key={step} className="rounded-lg bg-gray-50 border border-gray-100 p-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-bold text-white shrink-0">{step}</span>
                    <p className="font-medium text-gray-900 text-xs">{title}</p>
                  </div>
                  <p className="text-xs text-gray-500">{desc}</p>
                  {href && cta && <a href={href} target="_blank" rel="noopener noreferrer" className="text-xs font-medium text-indigo-600 hover:underline">{cta}</a>}
                </div>
              ))}
            </div>
          </details>

          <p className="text-xs text-gray-400 flex items-center gap-1.5">
            <Info className="h-3 w-3" />
            After reconnecting, this page refreshes automatically and shows your keyword rankings.
          </p>
        </div>
      )}

      {/* KPI cards — only when on keywords tab */}
      {tab === 'keywords' && keywords.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Clicks',    value: totalClicks.toLocaleString(),      icon: TrendingUp, color: 'text-indigo-600' },
            { label: 'Impressions',     value: totalImpressions.toLocaleString(), icon: BarChart2,  color: 'text-blue-600' },
            { label: 'Avg Position',    value: `#${avgPosition.toFixed(1)}`,      icon: Search,     color: 'text-green-600' },
            { label: 'Top-10 Keywords', value: top10Keywords.toString(),          icon: CheckCircle, color: 'text-emerald-600' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-2 mb-1">
                <Icon className={`h-4 w-4 ${color}`} />
                <p className="text-xs text-gray-500">{label}</p>
              </div>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {([
          { key: 'keywords', label: 'Keywords',     icon: Search },
          { key: 'pages',    label: 'Top Pages',    icon: FileText },
          { key: 'backlinks',label: 'Backlinks',    icon: TrendingUp },
          { key: 'offpage',  label: 'Off-Page',     icon: Globe },
          { key: 'audit',    label: 'On-Page Audit',icon: Zap },
          { key: 'automate', label: 'Automate',     icon: Zap },
        ] as const).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              tab === key
                ? 'border-indigo-500 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {loading && tab !== 'backlinks' && tab !== 'offpage' && tab !== 'audit' && tab !== 'automate' ? (
        <div className="flex items-center gap-2 py-10 text-sm text-gray-400 justify-center">
          <RefreshCw className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : tab === 'keywords' ? (
        <KeywordsTable keywords={keywords} />
      ) : tab === 'pages' ? (
        <div className="space-y-6">
          <PagesTable pages={pages} />
          {devices.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="text-sm font-semibold text-gray-700 mb-3">Device breakdown</p>
              <div className="flex gap-4 flex-wrap">
                {devices.map(d => (
                  <div key={d.device} className="text-center">
                    <p className="text-lg font-bold text-gray-800">{d.clicks.toLocaleString()}</p>
                    <p className="text-xs text-gray-500 capitalize">{d.device}</p>
                    <p className="text-[10px] text-gray-400">#{Math.round(d.position)} avg</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : tab === 'backlinks' ? (
        <BacklinksTab wsId={wsId} />
      ) : tab === 'offpage' ? (
        <OffPageTab wsId={wsId} activeSite={activeSite} />
      ) : tab === 'automate' ? (
        <AutomateTab wsId={wsId} />
      ) : (
        <OnPageAuditor wsId={wsId} />
      )}
    </div>
  )
}
