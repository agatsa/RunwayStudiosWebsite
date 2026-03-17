'use client'

import { useState } from 'react'
import { Mail, MousePointerClick, AlertTriangle, UserMinus, Send, Eye, TrendingUp, Trash2 } from 'lucide-react'
import type { EmailCampaign } from '@/lib/types'

interface Props {
  wsId: string
  campaigns: EmailCampaign[]
  onRefresh: () => void
}

function StatusBadge({ status }: { status: EmailCampaign['status'] }) {
  const map: Record<string, string> = {
    draft:     'bg-gray-100 text-gray-600',
    scheduled: 'bg-blue-100 text-blue-600',
    sending:   'bg-amber-100 text-amber-600',
    sent:      'bg-green-100 text-green-600',
    failed:    'bg-red-100 text-red-600',
  }
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${map[status] ?? 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  )
}

function MetricCard({ icon: Icon, label, value, sub }: { icon: React.ElementType; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-4 w-4 text-gray-400" />
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <p className="text-xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function CampaignStats({ wsId, campaigns, onRefresh }: Props) {
  const [selected, setSelected] = useState<EmailCampaign | null>(null)
  const [stats, setStats] = useState<{
    summary: Record<string, number>
    timeline: { hour: string; opens: number; clicks: number }[]
    top_links: { url: string; click_count: number }[]
  } | null>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const openStats = async (c: EmailCampaign) => {
    setSelected(c)
    setStats(null)
    setLoadingStats(true)
    try {
      const res = await fetch(`/api/email/campaigns/${c.id}?workspace_id=${wsId}`)
      const data = await res.json()
      if (res.ok) setStats({ summary: data.summary, timeline: data.timeline, top_links: data.top_links })
    } finally {
      setLoadingStats(false)
    }
  }

  const deleteCampaign = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this campaign?')) return
    setDeleting(id)
    await fetch(`/api/email/campaigns/${id}?workspace_id=${wsId}`, { method: 'DELETE' })
    setDeleting(null)
    if (selected?.id === id) setSelected(null)
    onRefresh()
  }

  if (selected && stats) {
    const s = stats.summary
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <button onClick={() => { setSelected(null); setStats(null) }} className="text-xs text-gray-400 hover:text-gray-700">
            ← All Campaigns
          </button>
          <span className="text-gray-300">/</span>
          <span className="text-sm font-medium text-gray-900">{selected.name}</span>
          <StatusBadge status={selected.status} />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard icon={Send} label="Sent" value={s.sent?.toLocaleString() ?? '0'} />
          <MetricCard icon={Eye} label="Opened" value={s.opened?.toLocaleString() ?? '0'} sub={`${s.open_rate ?? 0}% open rate`} />
          <MetricCard icon={MousePointerClick} label="Clicked" value={s.clicked?.toLocaleString() ?? '0'} sub={`${s.click_rate ?? 0}% click rate`} />
          <MetricCard icon={UserMinus} label="Unsubscribed" value={s.unsubscribed?.toLocaleString() ?? '0'} />
        </div>

        {stats.top_links.length > 0 && (
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-200">
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Top Clicked Links</p>
            </div>
            <div className="divide-y divide-gray-100">
              {stats.top_links.map((link, i) => (
                <div key={i} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-xs text-gray-700 truncate max-w-xs font-mono">{link.url}</span>
                  <span className="text-xs font-semibold text-indigo-600 ml-4">{link.click_count} clicks</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {stats.timeline.length > 0 && (
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-200">
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Opens & Clicks Over Time</p>
            </div>
            <div className="px-4 py-3">
              <div className="space-y-2">
                {stats.timeline.slice(-12).map((t, i) => {
                  const maxOpens = Math.max(...stats.timeline.map(x => x.opens), 1)
                  return (
                    <div key={i} className="flex items-center gap-3">
                      <span className="text-[10px] text-gray-400 w-28 shrink-0">
                        {new Date(t.hour).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <div className="flex-1 flex items-center gap-1.5">
                        <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                          <div
                            className="h-2 bg-indigo-400 rounded-full"
                            style={{ width: `${(t.opens / maxOpens) * 100}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-gray-500 w-10 text-right">{t.opens} opens</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (selected && loadingStats) {
    return (
      <div className="space-y-4">
        <button onClick={() => setSelected(null)} className="text-xs text-gray-400 hover:text-gray-700">← All Campaigns</button>
        <div className="flex items-center justify-center py-12 text-sm text-gray-400">Loading stats…</div>
      </div>
    )
  }

  if (campaigns.length === 0) {
    return (
      <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center">
        <Mail className="h-8 w-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">No campaigns yet. Create your first campaign in the New Campaign tab.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Campaigns</h3>
        <p className="text-xs text-gray-500 mt-0.5">Click a campaign to view detailed stats.</p>
      </div>

      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Name</th>
              <th className="px-4 py-2.5 text-left font-medium">Status</th>
              <th className="px-4 py-2.5 text-right font-medium">Sent</th>
              <th className="px-4 py-2.5 text-right font-medium">Opens</th>
              <th className="px-4 py-2.5 text-right font-medium">Clicks</th>
              <th className="px-4 py-2.5 text-left font-medium">Date</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {campaigns.map(c => (
              <tr
                key={c.id}
                className="hover:bg-gray-50 cursor-pointer"
                onClick={() => openStats(c)}
              >
                <td className="px-4 py-3">
                  <div>
                    <p className="font-medium text-gray-900 truncate max-w-40">{c.name}</p>
                    <p className="text-xs text-gray-400 truncate max-w-40">{c.subject}</p>
                  </div>
                </td>
                <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                <td className="px-4 py-3 text-right text-gray-700">{c.sent_count?.toLocaleString() ?? '—'}</td>
                <td className="px-4 py-3 text-right">
                  <span className="text-gray-700">{c.open_count?.toLocaleString() ?? '—'}</span>
                  {c.open_rate > 0 && <span className="ml-1 text-xs text-gray-400">({c.open_rate}%)</span>}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-gray-700">{c.click_count?.toLocaleString() ?? '—'}</span>
                  {c.click_rate > 0 && <span className="ml-1 text-xs text-gray-400">({c.click_rate}%)</span>}
                </td>
                <td className="px-4 py-3 text-xs text-gray-400">
                  {c.sent_at ? new Date(c.sent_at).toLocaleDateString() : c.created_at ? new Date(c.created_at).toLocaleDateString() : '—'}
                </td>
                <td className="px-4 py-3">
                  {(c.status === 'draft' || c.status === 'failed') && (
                    <button
                      onClick={e => deleteCampaign(c.id, e)}
                      disabled={deleting === c.id}
                      className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
