'use client'

import { useEffect, useState } from 'react'
import { X, Lightbulb, Loader2 } from 'lucide-react'
import { AreaChart } from '@tremor/react'
import BoldText from '@/components/ui/BoldText'
import { formatNumber } from '@/lib/utils'
import type { YouTubeVideo, YouTubeVideoInsightsResponse } from '@/lib/types'

interface Props {
  video: YouTubeVideo
  workspaceId: string
  onClose: () => void
}

function MetricTile({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}

export default function YouTubeVideoPanel({ video, workspaceId, onClose }: Props) {
  const [insights, setInsights] = useState<YouTubeVideoInsightsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(
      `/api/youtube/video-insights/${video.video_id}?workspace_id=${workspaceId}&days=30`
    )
      .then(r => r.json())
      .then(d => {
        if (d.detail) throw new Error(d.detail)
        setInsights(d)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [video.video_id, workspaceId])

  const chartData = (insights?.daily ?? []).map(d => ({
    date: d.date.slice(5),
    Views: d.views,
  }))

  // Audience retention curve: sample every 5th point to keep chart clean
  const retentionData = (insights?.retention_curve ?? [])
    .filter((_: unknown, i: number) => i % 5 === 0 || i === 0)
    .map((p: { elapsed_ratio: number; watch_pct: number }) => ({
      pct: `${Math.round(p.elapsed_ratio * 100)}%`,
      Retention: Math.round(p.watch_pct),
    }))

  const isShort: boolean = insights?.is_short ?? video.is_short ?? false
  const hasRetention = retentionData.length > 0
  // For Shorts, end drop-off is normal (they loop) — only show it for long-form
  const dropOff50 = hasRetention && !isShort
    ? (insights?.retention_curve ?? []).find(p => p.watch_pct < 50)
    : null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Slide panel */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 p-5">
          <div className="flex min-w-0 flex-1 items-start gap-3 pr-3">
            {video.thumbnail_url && (
              <img
                src={video.thumbnail_url}
                alt=""
                className="h-14 w-24 shrink-0 rounded-lg object-cover"
              />
            )}
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-gray-900">
                {video.title}
              </p>
              <p className="mt-0.5 text-xs text-gray-400">
                {formatNumber(video.view_count)} views ·{' '}
                {fmtDuration(video.duration_seconds)}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        {loading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading analytics…
          </div>
        ) : error ? (
          <div className="p-5 text-sm text-red-500">{error}</div>
        ) : (
          <div className="flex-1 space-y-6 p-5">
            {/* Metrics grid */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-gray-700">
                Last 30 Days
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <MetricTile
                  label="Views"
                  value={formatNumber(insights?.total_views ?? 0)}
                />
                <MetricTile
                  label="Watch Hours"
                  value={`${Math.round((insights?.total_watch_minutes ?? 0) / 60)}h`}
                />
                <MetricTile
                  label="Avg View %"
                  value={`${insights?.avg_view_percentage?.toFixed(1) ?? 0}%`}
                  sub="target > 35%"
                />
                <MetricTile
                  label="Impression CTR"
                  value={`${insights?.avg_ctr?.toFixed(2) ?? 0}%`}
                  sub="target > 4%"
                />
                <MetricTile
                  label="Avg Duration"
                  value={fmtDuration(Math.round(insights?.avg_duration_seconds ?? 0))}
                />
                <MetricTile
                  label="Subs Gained"
                  value={`+${formatNumber(insights?.subscribers_gained ?? 0)}`}
                />
              </div>
            </div>

            {/* Views trend */}
            {chartData.length > 0 && (
              <div>
                <h3 className="mb-3 text-sm font-semibold text-gray-700">
                  Daily Views Trend
                </h3>
                <AreaChart
                  data={chartData}
                  index="date"
                  categories={['Views']}
                  colors={['red']}
                  valueFormatter={(v: number) => formatNumber(v)}
                  showLegend={false}
                  yAxisWidth={60}
                  className="h-36"
                />
              </div>
            )}

            {/* Audience Retention Curve */}
            {hasRetention ? (
              <div>
                <h3 className="mb-1 text-sm font-semibold text-gray-700">
                  Audience Retention
                  {isShort && (
                    <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
                      SHORT
                    </span>
                  )}
                </h3>
                <p className="mb-3 text-xs text-gray-400">
                  % of viewers still watching at each point in the video
                  {dropOff50 && (
                    <span className="ml-1 text-orange-600 font-medium">
                      · 50% drop-off at {Math.round((dropOff50.elapsed_ratio ?? 0) * (insights?.avg_duration_seconds ?? 0))}s
                    </span>
                  )}
                  {isShort && (
                    <span className="ml-1 text-red-500 font-medium">
                      · Shorts loop — end drop is expected
                    </span>
                  )}
                </p>
                <AreaChart
                  data={retentionData}
                  index="pct"
                  categories={['Retention']}
                  colors={['red']}
                  valueFormatter={(v: number) => `${v}%`}
                  showLegend={false}
                  yAxisWidth={40}
                  minValue={0}
                  maxValue={100}
                  className="h-36"
                />
                <div className="mt-2 flex gap-3 text-xs">
                  {retentionData[0] && (
                    <span className={`rounded-full px-2 py-0.5 font-medium ${
                      retentionData[0].Retention >= 85
                        ? 'bg-green-100 text-green-700'
                        : retentionData[0].Retention >= 70
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-red-100 text-red-700'
                    }`}>
                      Hook: {retentionData[0].Retention >= 85 ? 'Strong' : retentionData[0].Retention >= 70 ? 'Average' : 'Weak'} ({retentionData[0].Retention}% at start)
                    </span>
                  )}
                  {!isShort && retentionData[retentionData.length - 1] && (
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600 font-medium">
                      End: {retentionData[retentionData.length - 1].Retention}% finish
                    </span>
                  )}
                  {isShort && (
                    <span className="rounded-full bg-red-50 px-2 py-0.5 text-red-500 font-medium">
                      Shorts loop — 100% end drop is normal
                    </span>
                  )}
                </div>
              </div>
            ) : insights && !hasRetention && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 p-3 text-xs text-amber-700">
                {isShort
                  ? 'Shorts audience retention requires Google OAuth — connect in Settings.'
                  : 'Audience retention curve requires Google OAuth — connect in Settings for per-second drop-off analysis.'}
              </div>
            )}

            {/* AI suggestions */}
            {(insights?.suggestions?.length ?? 0) > 0 && (
              <div>
                <div className="mb-3 flex items-center gap-1.5">
                  <Lightbulb className="h-3.5 w-3.5 text-yellow-500" />
                  <h3 className="text-sm font-semibold text-gray-700">
                    AI Suggestions
                  </h3>
                </div>
                <ul className="space-y-2">
                  {(insights?.suggestions ?? []).map((s, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg bg-yellow-50 px-3 py-2.5 text-sm text-gray-700"
                    >
                      <span className="mt-0.5 shrink-0 text-xs font-bold text-yellow-600">
                        {i + 1}
                      </span>
                      <BoldText text={s} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
