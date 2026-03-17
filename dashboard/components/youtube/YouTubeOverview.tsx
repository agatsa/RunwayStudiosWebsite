import { Users, Eye, Clock, TrendingUp } from 'lucide-react'
import { Card } from '@tremor/react'
import { formatNumber } from '@/lib/utils'
import type { YouTubeChannelInfo, YouTubeChannelStatRow } from '@/lib/types'

interface Props {
  channel: YouTubeChannelInfo
  daily: YouTubeChannelStatRow[]
  analyticsAvailable?: boolean
}

export default function YouTubeOverview({ channel, daily, analyticsAvailable = true }: Props) {
  const hasData = daily.length > 0
  const views30d = daily.reduce((s, r) => s + r.views, 0)
  const watchHours30d = Math.round(
    daily.reduce((s, r) => s + r.watch_time_minutes, 0) / 60
  )

  // Monetization: YouTube requires 1,000 subs AND 4,000 watch hours (last 12 months).
  // Estimate 12-month watch hours by scaling 30-day data (×12).
  const subsPercent = Math.min(100, Math.round((channel.subscriber_count / 1000) * 100))
  const watchHours12mEst = watchHours30d * 12
  // Only compute watch hours % when we actually have data rows
  const watchHoursPercent = (analyticsAvailable && hasData)
    ? Math.min(100, Math.round((watchHours12mEst / 4000) * 100))
    : null
  // monoPercent = min of both goals; fall back to subs-only when watch hours unavailable
  const monoPercent = (watchHoursPercent !== null && watchHours12mEst > 0)
    ? Math.min(subsPercent, watchHoursPercent)
    : subsPercent

  const monoSub = (watchHoursPercent !== null && hasData)
    ? `${formatNumber(channel.subscriber_count)}/1k subs · ~${formatNumber(watchHours12mEst)}h/4k hrs`
    : analyticsAvailable
      ? `${formatNumber(channel.subscriber_count)} / 1,000 subs · watch hours syncing`
      : `${formatNumber(channel.subscriber_count)} / 1,000 subs · connect Google for watch hours`

  // When analytics connected but no rows yet, show lifetime views rather than 0
  const viewsLabel = (!analyticsAvailable || !hasData) ? 'Views (lifetime)' : 'Views (30d)'
  const viewsValue = (!analyticsAvailable || !hasData)
    ? formatNumber(channel.view_count)
    : formatNumber(views30d)
  const viewsSub = (!analyticsAvailable || !hasData)
    ? (analyticsAvailable ? 'Analytics syncing — check back soon' : 'Connect Google for 30-day data')
    : `${formatNumber(channel.view_count)} lifetime`

  const cards = [
    {
      label: 'Subscribers',
      value: formatNumber(channel.subscriber_count),
      sub: (analyticsAvailable && hasData)
        ? `+${formatNumber(daily.reduce((s, r) => s + r.subscribers_gained, 0))} this month`
        : 'Connect Google for monthly gain',
      icon: Users,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
    {
      label: viewsLabel,
      value: viewsValue,
      sub: viewsSub,
      icon: Eye,
      color: 'text-orange-600',
      bg: 'bg-orange-50',
    },
    {
      label: 'Watch Hours (30d)',
      value: !analyticsAvailable ? '—' : hasData ? `${formatNumber(watchHours30d)}h` : '—',
      sub: !analyticsAvailable
        ? 'Connect Google for watch hours'
        : hasData ? '/4,000h/yr for monetization' : 'Analytics syncing — check back soon',
      icon: Clock,
      color: 'text-purple-600',
      bg: 'bg-purple-50',
    },
    {
      label: 'Monetization',
      value: `${monoPercent}%`,
      sub: monoSub,
      icon: TrendingUp,
      color: 'text-green-600',
      bg: 'bg-green-50',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {cards.map(({ label, value, sub, icon: Icon, color, bg }) => (
        <Card key={label} className="p-4">
          <div className={`mb-3 inline-flex rounded-lg p-2 ${bg}`}>
            <Icon className={`h-4 w-4 ${color}`} />
          </div>
          <p className="text-xs font-semibold text-gray-600">
            {label}
          </p>
          <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
          <p className="mt-0.5 text-xs text-gray-400">{sub}</p>
        </Card>
      ))}
    </div>
  )
}
