'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import Link from 'next/link'

interface TrafficSource {
  source: string
  source_type: string
  views: number
  watch_time_minutes: number
  pct: number
}

interface TrafficData {
  available: boolean
  sources: TrafficSource[]
  since?: string
  until?: string
  reason?: string
}

const SOURCE_COLORS: Record<string, string> = {
  YT_SEARCH:        'bg-blue-500',
  SUGGESTED:        'bg-purple-500',
  BROWSE_FEATURES:  'bg-orange-500',
  EXT_URL:          'bg-red-500',
  NO_LINK_EMBEDDED: 'bg-teal-500',
  NOTIFICATION:     'bg-yellow-500',
  CHANNEL:          'bg-green-500',
  ADVERTISING:      'bg-pink-500',
  END_SCREEN:       'bg-indigo-500',
  PLAYLISTS:        'bg-cyan-500',
}

function colorFor(type: string) {
  return SOURCE_COLORS[type] ?? 'bg-gray-400'
}

function fmtNum(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

interface Props {
  workspaceId: string
}

export default function YouTubeTrafficSources({ workspaceId }: Props) {
  const [data, setData] = useState<TrafficData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/youtube/traffic-sources?workspace_id=${workspaceId}&days=30`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData({ available: false, sources: [], reason: 'fetch_error' }))
      .finally(() => setLoading(false))
  }, [workspaceId])

  return (
    <div className="rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-1">Traffic Source Analysis</h2>
      <p className="text-xs text-gray-400 mb-4">Where your views come from — last 30 days</p>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : !data?.available ? (
        <div className="rounded-lg border border-amber-100 bg-amber-50 p-4 text-xs text-amber-700 space-y-1">
          <p className="font-medium">Google OAuth required</p>
          <p className="text-amber-600">Traffic source breakdown needs YouTube Analytics. Connect Google in Settings.</p>
          <Link
            href={`/settings?ws=${workspaceId}`}
            className="inline-block mt-1 rounded bg-amber-600 px-2.5 py-1 text-white font-medium hover:bg-amber-700"
          >
            Connect Google →
          </Link>
        </div>
      ) : data.sources.length === 0 ? (
        <p className="text-sm text-gray-400">No traffic data for the last 30 days.</p>
      ) : (
        <div className="space-y-2.5">
          {data.sources.slice(0, 7).map(s => (
            <div key={s.source_type} className="flex items-center gap-2 text-xs">
              <div className={`h-2 w-2 rounded-full ${colorFor(s.source_type)} shrink-0`} />
              <span className="w-36 truncate text-gray-700">{s.source}</span>
              <div className="flex-1 h-2 rounded-full bg-gray-100">
                <div
                  className={`h-2 rounded-full ${colorFor(s.source_type)} transition-all`}
                  style={{ width: `${Math.min(s.pct, 100)}%` }}
                />
              </div>
              <span className="w-8 text-right font-semibold text-gray-800">{s.pct}%</span>
              <span className="w-12 text-right text-gray-400">{fmtNum(s.views)}</span>
            </div>
          ))}
          {data.since && (
            <p className="text-[10px] text-gray-400 mt-1">
              {data.since} → {data.until}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
