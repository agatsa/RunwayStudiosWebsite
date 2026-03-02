import Link from 'next/link'
import { fetchFromFastAPI, fetchBillingPlan } from '@/lib/api'
import YouTubeOverview from '@/components/youtube/YouTubeOverview'
import YouTubeGrowthPlan from '@/components/youtube/YouTubeGrowthPlan'
import YouTubeVideoTable from '@/components/youtube/YouTubeVideoTable'
import YouTubeTrafficSources from '@/components/youtube/YouTubeTrafficSources'
import YouTubeUploadTiming from '@/components/youtube/YouTubeUploadTiming'
import YouTubeOrganicOpportunities from '@/components/youtube/YouTubeOrganicOpportunities'
import PlanGateBanner from '@/components/billing/PlanGateBanner'
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

  // Check billing plan — YouTube requires Growth+
  const plan = await fetchBillingPlan(workspaceId)
  const planRank: Record<string, number> = { free: 0, starter: 1, growth: 2, agency: 3 }
  if (planRank[plan] < planRank['growth']) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">YouTube Channel</h1>
          <p className="text-sm text-gray-500">AI-powered YouTube growth intelligence</p>
        </div>
        <div className="flex flex-col items-center gap-5 rounded-xl border-2 border-dashed border-amber-200 bg-amber-50/40 p-12 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-100">
            <YTIcon className="h-7 w-7 fill-amber-600" />
          </div>
          <div>
            <p className="text-base font-semibold text-gray-900">Growth Plan Required</p>
            <p className="mt-1 text-sm text-gray-500 max-w-sm">
              YouTube Channel Intelligence & AI Growth Recipe requires the Growth plan or higher.
              You&apos;re currently on the <strong className="capitalize">{plan}</strong> plan.
            </p>
          </div>
          <Link
            href={`/billing?ws=${workspaceId}`}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-600"
          >
            Upgrade to Growth
          </Link>
        </div>
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
      {/* Plan gate banner — hidden for Growth+ users (they already qualify) */}
      <PlanGateBanner
        requiredPlan="Growth"
        feature="YouTube Competitor Intelligence & AI Growth Recipe"
        creditCost={20}
        wsId={workspaceId}
        currentPlan={plan as 'free' | 'starter' | 'growth' | 'agency'}
      />

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
        <YouTubeGrowthPlan
          planId={growthPlan.plan_id ?? ''}
          steps={growthPlan.steps}
          history={growthPlan.history ?? []}
          workspaceId={workspaceId}
        />
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

      {/* Audience Retention note — actual curve is inside the video panel (click any video) */}
      <div className="rounded-xl border border-gray-200 bg-gray-50/60 px-5 py-4 flex items-center gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-100">
          <svg className="h-4 w-4 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-800">Audience Retention Curves</p>
          <p className="text-xs text-gray-500">
            Click any video in the table above to see its per-second drop-off curve, hook strength, and where to edit.
            {!analyticsAvailable && (
              <span className="ml-1 text-amber-600">
                Requires Google OAuth —{' '}
                <Link href={`/settings?ws=${workspaceId}`} className="underline hover:text-amber-700">
                  connect in Settings
                </Link>
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Traffic Source + Upload Timing */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <YouTubeTrafficSources workspaceId={workspaceId} />
        <YouTubeUploadTiming workspaceId={workspaceId} />
      </div>

      {/* Organic → Paid Opportunities */}
      <YouTubeOrganicOpportunities workspaceId={workspaceId} />
    </div>
  )
}
