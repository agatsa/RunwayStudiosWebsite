'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Loader2, ExternalLink, PlayCircle } from 'lucide-react'

interface YouTubeStats {
  channel_name?: string
  subscriber_count?: number
  total_views?: number
  video_count?: number
  avg_views_per_video?: number
  avg_ctr?: number
}

interface Video {
  id: string
  title: string
  views: number
  likes: number
  ctr: number | null
  published_at: string
  is_short?: boolean
}

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString('en-IN')
}

export default function YouTubeTabContent({ wsId }: { wsId: string }) {
  const [stats, setStats] = useState<YouTubeStats | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch(`/api/youtube/channel-stats?workspace_id=${wsId}&days=30`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setStats(d)),
      fetch(`/api/youtube/videos?workspace_id=${wsId}&limit=8`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setVideos(d?.videos ?? [])),
    ])
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [wsId])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }

  if (!stats?.channel_name && videos.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">YouTube</h2>
        </div>
        <div className="rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-sm font-medium text-gray-700">No YouTube channel connected</p>
          <p className="mt-1 text-xs text-gray-500">Connect your Google account in Setup to link your YouTube channel.</p>
          <Link href={`/setup?ws=${wsId}`} className="mt-3 inline-block text-xs font-medium text-brand-600 hover:underline">
            Go to Setup →
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">YouTube</h2>
        <Link href={`/youtube?ws=${wsId}`} className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline">
          Full analytics <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Channel stat strip */}
      {stats?.channel_name && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Subscribers', value: fmt(stats.subscriber_count ?? 0) },
            { label: 'Total Views', value: fmt(stats.total_views ?? 0) },
            { label: 'Videos', value: stats.video_count?.toString() ?? '—' },
            { label: 'Avg CTR', value: stats.avg_ctr ? `${(stats.avg_ctr * 100).toFixed(1)}%` : '—' },
          ].map(s => (
            <div key={s.label} className="rounded-xl border border-gray-100 bg-white p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400">{s.label}</p>
              <p className="mt-1 text-sm font-bold text-gray-900">{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Recent videos */}
      {videos.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Video</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Views</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Likes</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">CTR</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {videos.map(v => (
                <tr key={v.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 max-w-xs">
                      {v.is_short && (
                        <span className="rounded px-1 py-0.5 text-[9px] font-bold bg-red-100 text-red-600 shrink-0">SHORT</span>
                      )}
                      <span className="truncate text-sm text-gray-800">{v.title}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{fmt(v.views)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{fmt(v.likes)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">
                    {v.ctr != null ? `${(v.ctr * 100).toFixed(1)}%` : '—'}
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
