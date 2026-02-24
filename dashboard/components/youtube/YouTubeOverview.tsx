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
  const views30d = daily.reduce((s, r) => s + r.views, 0)
  const watchHours30d = Math.round(
    daily.reduce((s, r) => s + r.watch_time_minutes, 0) / 60
  )
  const monoPercent = Math.min(
    100,
    Math.round((channel.subscriber_count / 1000) * 100)
  )

  const noData = '—'

  const cards = [
    {
      label: 'Subscribers',
      value: formatNumber(channel.subscriber_count),
      sub: analyticsAvailable
        ? `+${formatNumber(daily.reduce((s, r) => s + r.subscribers_gained, 0))} this month`
        : 'Connect Google for monthly gain',
      icon: Users,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
    {
      label: 'Views (30d)',
      value: analyticsAvailable ? formatNumber(views30d) : noData,
      sub: `${formatNumber(channel.view_count)} lifetime`,
      icon: Eye,
      color: 'text-orange-600',
      bg: 'bg-orange-50',
    },
    {
      label: 'Watch Hours (30d)',
      value: analyticsAvailable ? `${formatNumber(watchHours30d)}h` : noData,
      sub: '/4000h for monetization',
      icon: Clock,
      color: 'text-purple-600',
      bg: 'bg-purple-50',
    },
    {
      label: 'Monetization',
      value: `${monoPercent}%`,
      sub: `${formatNumber(channel.subscriber_count)} / 1,000 subs`,
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
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
            {label}
          </p>
          <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
          <p className="mt-0.5 text-xs text-gray-400">{sub}</p>
        </Card>
      ))}
    </div>
  )
}
