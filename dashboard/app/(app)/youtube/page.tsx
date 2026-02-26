import Link from 'next/link'
import { fetchFromFastAPI } from '@/lib/api'
import YouTubeOverview from '@/components/youtube/YouTubeOverview'
import YouTubeGrowthPlan from '@/components/youtube/YouTubeGrowthPlan'
import YouTubeVideoTable from '@/components/youtube/YouTubeVideoTable'
import type {
  YouTubeChannelStatsResponse,
  YouTubeVideosResponse,
  YouTubeGrowthPlanResponse,
} from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string }
}

interface YouTubeStatus {
  channel_connected: boolean
  oauth_available: boolean
  analytics_available: boolean
  channel_id: string | null
}

async function fetchStatus(workspaceId: string): Promise<YouTubeStatus | null> {
  try {
    const r = await fetchFromFastAPI(`/youtube/status?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

async function fetchChannelStats(
  workspaceId: string
): Promise<YouTubeChannelStatsResponse | null> {
  try {
    const r = await fetchFromFastAPI(
      `/youtube/channel-stats?workspace_id=${workspaceId}&days=30`
    )
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

async function fetchVideos(
  workspaceId: string
): Promise<YouTubeVideosResponse | null> {
  try {
    const r = await fetchFromFastAPI(`/youtube/videos?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

async function fetchGrowthPlan(
  workspaceId: string
): Promise<YouTubeGrowthPlanResponse | null> {
  try {
    const r = await fetchFromFastAPI(
      `/youtube/growth-plan?workspace_id=${workspaceId}`
    )
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

const YTIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className ?? 'h-6 w-6 fill-white'}>
    <path d="M19.59 6.69a4.83 4.83 0 01-3.77-2.75 12.58 12.58 0 00-7.64 0A4.83 4.83 0 014.41 6.69 48.75 48.75 0 004 12a48.75 48.75 0 00.41 5.31 4.83 4.83 0 003.77 2.75 12.58 12.58 0 007.64 0 4.83 4.83 0 003.77-2.75A48.75 48.75 0 0020 12a48.75 48.75 0 00-.41-5.31zM10 15.5v-7l6 3.5-6 3.5z" />
  </svg>
)

export default async function YouTubePage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view YouTube analytics</p>
      </div>
    )
  }

  // Always check status first — it's lightweight and requires no OAuth
  const status = await fetchStatus(workspaceId)

  // State 1: Channel ID not saved yet
  if (!status?.channel_connected) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">YouTube Channel</h1>
          <p className="text-sm text-gray-500">
            Connect your channel to unlock AI growth intelligence
          </p>
        </div>
        <div className="flex flex-col items-center gap-4 rounded-xl border-2 border-dashed border-red-100 bg-red-50/40 p-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-600">
            <YTIcon className="h-7 w-7 fill-white" />
          </div>
          <div>
            <p className="text-base font-semibold text-gray-900">
              YouTube not connected
            </p>
            <p className="mt-1 text-sm text-gray-500">
              Go to Settings and add your YouTube Channel ID to enable the 7 AI
              growth levers: CTR optimization, retention analysis, SEO topics,
              upload scheduling, comment intelligence, Shorts strategy, and
              cross-channel amplification.
            </p>
          </div>
          <Link
            href={`/settings?ws=${workspaceId}`}
            className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
          >
            Connect YouTube Channel
          </Link>
        </div>
      </div>
    )
  }

  // State 2 or 3: Channel connected — fetch public data (always works via API key)
  // Analytics (watch time, CTR) only available if oauth_available
  const [channelStats, videosData, growthPlan] = await Promise.all([
    fetchChannelStats(workspaceId),
    fetchVideos(workspaceId),
    status.oauth_available ? fetchGrowthPlan(workspaceId) : Promise.resolve(null),
  ])

  if (!channelStats) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
        Failed to load YouTube channel. Check that your channel ID is correct.
      </div>
    )
  }

  const analyticsAvailable = channelStats.analytics_available ?? status.oauth_available

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-600">
            <YTIcon className="h-5 w-5 fill-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              {channelStats.channel.title}
            </h1>
            <p className="text-sm text-gray-500">
              {channelStats.channel.video_count} videos · YouTube Channel Intelligence
            </p>
          </div>
        </div>
        {!analyticsAvailable && (
          <Link
            href={`/settings?ws=${workspaceId}`}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            Connect Google for analytics
          </Link>
        )}
      </div>

      {/* Overview cards */}
      <YouTubeOverview
        channel={channelStats.channel}
        daily={channelStats.daily}
        analyticsAvailable={analyticsAvailable}
      />

      {/* AI Growth Plan — only when OAuth available */}
      {growthPlan && growthPlan.steps.length > 0 && (
        <YouTubeGrowthPlan steps={growthPlan.steps} />
      )}

      {/* Video table */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-gray-900">
          Videos{' '}
          <span className="ml-1 text-sm font-normal text-gray-400">
            {analyticsAvailable
              ? '— click a row for 30-day analytics + AI suggestions'
              : '— connect Google Ads for per-video analytics'}
          </span>
        </h2>
        <YouTubeVideoTable
          videos={videosData?.videos ?? []}
          workspaceId={workspaceId}
        />
      </div>

      {/* ── COMING SOON: DEEP ANALYTICS ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-700">Audience Retention Curves</h2>
            <p className="text-xs text-gray-400">Per-second drop-off analysis — the most underused YouTube metric</p>
          </div>
          {!analyticsAvailable && (
            <Link href={`/settings?ws=${workspaceId}`}
              className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1 hover:bg-amber-100">
              Connect Google for analytics
            </Link>
          )}
        </div>
        <div className="p-4 opacity-40 select-none">
          <div className="flex items-end gap-0.5 h-20">
            {[100,98,95,90,82,75,70,68,65,62,60,58,55,52,50,48,46,44,42,40,39,38,37,36,35,34,33,32,31,30].map((h, i) => (
              <div key={i} className="flex-1 rounded-t bg-red-400" style={{ height: `${h}%` }} />
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-gray-400 mt-1">
            <span>0:00</span><span>Avg drop-off: 45%</span><span>End</span>
          </div>
          <p className="text-xs text-gray-500 mt-2 text-center">Hook strength: <strong>Strong (98% past 0:30)</strong> · Drop-off spike at 2:15 — "edit this section"</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Traffic Source Analysis */}
        <div className="rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">Traffic Source Analysis</h2>
          <p className="text-xs text-gray-400 mb-3">Where your views come from — and where to push next</p>
          <div className="space-y-2 opacity-40 select-none">
            {[
              { source: 'YouTube Search', pct: 42, color: 'bg-blue-500' },
              { source: 'Suggested Videos', pct: 31, color: 'bg-purple-500' },
              { source: 'External (Ads)', pct: 15, color: 'bg-red-500' },
              { source: 'Browse Features', pct: 8, color: 'bg-green-500' },
              { source: 'Other', pct: 4, color: 'bg-gray-400' },
            ].map(s => (
              <div key={s.source} className="flex items-center gap-2 text-xs">
                <div className={`h-2 w-2 rounded-full ${s.color} shrink-0`} />
                <span className="flex-1 text-gray-700">{s.source}</span>
                <div className="w-24 h-1.5 rounded-full bg-gray-100">
                  <div className={`h-1.5 rounded-full ${s.color}`} style={{ width: `${s.pct * 2}%` }} />
                </div>
                <span className="font-semibold text-gray-800">{s.pct}%</span>
              </div>
            ))}
          </div>
          {!analyticsAvailable && <p className="mt-3 text-[10px] text-gray-400">Requires Google OAuth — connect in Settings</p>}
        </div>

        {/* Upload Timing Optimization */}
        <div className="rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">Upload Timing Optimization</h2>
          <p className="text-xs text-gray-400 mb-3">When to publish for maximum views in first 48 hours</p>
          <div className="opacity-40 select-none">
            <div className="grid grid-cols-7 gap-1 text-center">
              {['S','M','T','W','T','F','S'].map((d, i) => (
                <div key={i}>
                  <p className="text-[10px] text-gray-500 mb-1">{d}</p>
                  {['8am','2pm','8pm'].map(t => (
                    <div key={t} className={`rounded text-[9px] mb-0.5 py-0.5 ${
                      (i === 0 && t === '8pm') || (i === 6 && t === '8pm') ? 'bg-green-200 text-green-800 font-bold' : 'bg-gray-100 text-gray-400'
                    }`}>{t}</div>
                  ))}
                </div>
              ))}
            </div>
          </div>
          {!analyticsAvailable && <p className="mt-3 text-[10px] text-gray-400">Requires Google OAuth — connect in Settings</p>}
        </div>
      </div>

      {/* Organic → Paid Opportunities */}
      <div className="rounded-xl border border-red-100 bg-red-50/40 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-1">Organic → Paid Opportunities</h2>
        <p className="text-xs text-gray-500 mb-3">Your best-performing organic videos are the safest creative to run as paid ads — zero creative risk since real audiences already validated them</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 opacity-40 select-none">
          {[
            ['Top organic video', 'ECG demo at home', '124K views · 6.2% CTR'],
            ['Recommended ad budget', '₹10,000–₹25,000', 'Projected: 8L impressions'],
            ['Expected view-through', '2.1x hidden ROAS', 'Brand search lift included'],
          ].map(([title, value, sub]) => (
            <div key={title} className="rounded-lg bg-white border border-red-100 p-3 text-center">
              <p className="text-[10px] text-gray-500">{title}</p>
              <p className="text-sm font-bold text-gray-800 mt-1">{value}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>
            </div>
          ))}
        </div>
        {!analyticsAvailable && <p className="mt-3 text-[10px] text-gray-400 text-center">Connect Google OAuth to see which specific videos to boost and at what budget</p>}
      </div>
    </div>
  )
}
