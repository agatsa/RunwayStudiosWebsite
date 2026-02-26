'use client'

import { useEffect, useState } from 'react'
import { BarChart2, PlayCircle, ShoppingBag, TrendingUp, ExternalLink, Loader2 } from 'lucide-react'

function fmt(n: number, prefix = '') {
  if (n >= 1_00_00_000) return `${prefix}${(n / 1_00_00_000).toFixed(1)}Cr`
  if (n >= 1_00_000)    return `${prefix}${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000)       return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toFixed(0)}`
}

export default function ChannelHealthRow({ workspaceId, summary, days = 30 }: {
  workspaceId: string
  summary: { platform_breakdown: Record<string, { spend: number; roas: number; conversions: number; clicks: number }> }
  days?: number
}) {
  const [google, setGoogle]   = useState<{ has_data: boolean; total_spend: number; avg_roas: number; total_conversions: number } | null>(null)
  const [youtube, setYoutube] = useState<{ channel: { subscriber_count: number; view_count: number; video_count: number } } | null>(null)
  const [amazon, setAmazon]   = useState<{ summary: { total_spend: number; avg_roas: number; avg_acos: number } } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.allSettled([
      fetch(`/api/google-ads/intelligence?workspace_id=${workspaceId}&days=365`).then(r => r.json()),
      fetch(`/api/youtube/channel-stats?workspace_id=${workspaceId}`).then(r => r.json()),
      fetch(`/api/marketplace/campaigns?workspace_id=${workspaceId}&days=365`).then(r => r.json()),
    ]).then(([g, y, az]) => {
      if (g.status === 'fulfilled') setGoogle(g.value)
      if (y.status === 'fulfilled' && y.value?.channel) setYoutube(y.value)
      if (az.status === 'fulfilled' && az.value?.summary?.total_spend > 0) setAmazon(az.value)
      setLoading(false)
    })
  }, [workspaceId])

  const meta = summary.platform_breakdown['meta']

  const periodLabel = days === 1 ? 'Today' : days === 365 ? 'All time' : `Last ${days}d`

  const channels = [
    {
      id: 'meta',
      label: 'Meta Ads',
      icon: <BarChart2 className="h-4 w-4" />,
      border: 'border-blue-200',
      bg: 'bg-blue-50/50',
      href: `/campaigns?ws=${workspaceId}`,
      connected: !!meta,
      periodTag: periodLabel,
      metrics: meta ? [
        { label: 'Spend',     value: fmt(meta.spend, '₹') },
        { label: 'ROAS',      value: meta.roas > 0 ? `${meta.roas.toFixed(2)}x` : '—' },
        { label: 'Conv.',     value: fmt(meta.conversions) },
      ] : [],
      note: 'Connect Meta Ads in Settings →',
    },
    {
      id: 'google',
      label: 'Google Ads',
      icon: <TrendingUp className="h-4 w-4" />,
      border: 'border-green-200',
      bg: 'bg-green-50/50',
      href: `/google-ads?ws=${workspaceId}`,
      connected: !!google?.has_data,
      periodTag: 'All reports',
      metrics: google?.has_data ? [
        { label: 'Spend',     value: fmt(google.total_spend, '₹') },
        { label: 'ROAS',      value: google.avg_roas > 0 ? `${google.avg_roas.toFixed(2)}x` : '—' },
        { label: 'Conv.',     value: fmt(google.total_conversions) },
      ] : [],
      note: 'Upload reports in Google Ads page →',
    },
    {
      id: 'youtube',
      label: 'YouTube',
      icon: <PlayCircle className="h-4 w-4" />,
      border: 'border-red-200',
      bg: 'bg-red-50/50',
      href: `/youtube?ws=${workspaceId}`,
      connected: !!youtube?.channel,
      periodTag: 'Channel stats',
      metrics: youtube?.channel ? [
        { label: 'Subscribers', value: fmt(youtube.channel.subscriber_count) },
        { label: 'Total views',  value: fmt(youtube.channel.view_count) },
        { label: 'Videos',       value: String(youtube.channel.video_count) },
      ] : [],
      note: 'Connect YouTube in Settings →',
    },
    {
      id: 'marketplace',
      label: 'Amazon Ads',
      icon: <ShoppingBag className="h-4 w-4" />,
      border: 'border-orange-200',
      bg: 'bg-orange-50/40',
      href: `/marketplace?ws=${workspaceId}`,
      connected: !!amazon,
      periodTag: 'All reports',
      metrics: amazon ? [
        { label: 'Spend',   value: fmt(amazon.summary.total_spend, '₹') },
        { label: 'ROAS',    value: amazon.summary.avg_roas > 0 ? `${amazon.summary.avg_roas.toFixed(2)}x` : '—' },
        { label: 'ACoS',    value: amazon.summary.avg_acos > 0 ? `${amazon.summary.avg_acos.toFixed(1)}%` : '—' },
      ] : [],
      note: 'Upload reports in Marketplace page →',
    },
  ]

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Your Channels</h2>
          <p className="text-xs text-gray-600">Meta shows <span className="font-medium">{periodLabel}</span> · Google/YouTube show all-time totals</p>
        </div>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {channels.map(ch => (
          <a
            key={ch.id}
            href={ch.href}
            className={`group rounded-xl border p-4 transition-shadow hover:shadow-md ${ch.border} ${ch.bg}`}
          >
            <div className="flex items-center justify-between mb-3">
              <span className={`flex items-center gap-1.5 text-xs font-semibold ${ch.connected ? 'text-gray-800' : 'text-gray-400'}`}>
                {ch.icon}
                {ch.label}
              </span>
              <ExternalLink className="h-3 w-3 text-gray-300 group-hover:text-gray-500 transition-colors" />
            </div>

            {ch.connected && ch.metrics.length > 0 ? (
              <div className="space-y-1.5">
                {ch.metrics.map(m => (
                  <div key={m.label} className="flex items-center justify-between">
                    <span className="text-[10px] text-gray-500">{m.label}</span>
                    <span className="text-xs font-bold text-gray-800">{m.value}</span>
                  </div>
                ))}
                <div className="mt-1 flex items-center gap-1 pt-0.5">
                  <div className="h-1.5 w-1.5 rounded-full bg-green-500" />
                  <span className="text-[9px] font-medium text-green-600">Connected</span>
                  {ch.periodTag && (
                    <span className="text-[9px] text-gray-400 ml-1">· {ch.periodTag}</span>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-[10px] text-gray-400 leading-snug">{ch.note}</p>
            )}
          </a>
        ))}
      </div>
    </div>
  )
}
