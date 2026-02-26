import { BarChart2, TrendingUp, ShoppingCart, AlertTriangle } from 'lucide-react'
import { Card } from '@tremor/react'
import { formatINR, formatNumber } from '@/lib/utils'
import type { GoogleIntelligenceData } from '@/app/(app)/google-ads/page'

interface Props {
  data: GoogleIntelligenceData
}

export default function GoogleAdsOverview({ data }: Props) {
  const cards = [
    {
      label: 'Total Spend',
      value: formatINR(data.total_spend),
      sub: `${formatNumber(data.total_clicks)} clicks`,
      icon: BarChart2,
      color: 'text-blue-600',
      bg: 'bg-blue-50',
    },
    {
      label: 'Avg ROAS',
      value: `${data.avg_roas.toFixed(2)}x`,
      sub: data.avg_roas >= 2.5 ? '✅ Above 2.5x target' : '⚠️ Below 2.5x target',
      icon: TrendingUp,
      color: data.avg_roas >= 2.5 ? 'text-green-600' : 'text-yellow-600',
      bg: data.avg_roas >= 2.5 ? 'bg-green-50' : 'bg-yellow-50',
    },
    {
      label: 'Conversions',
      value: formatNumber(data.total_conversions),
      sub: data.total_spend > 0
        ? `₹${(data.total_spend / Math.max(data.total_conversions, 1)).toFixed(0)} CPA`
        : '—',
      icon: ShoppingCart,
      color: 'text-purple-600',
      bg: 'bg-purple-50',
    },
    {
      label: 'Wasted Spend',
      value: formatINR(data.wasted_spend_total),
      sub: `on 0-conv keywords`,
      icon: AlertTriangle,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {cards.map(({ label, value, sub, icon: Icon, color, bg }) => (
        <Card key={label} className="p-4">
          <div className={`mb-3 inline-flex rounded-lg p-2 ${bg}`}>
            <Icon className={`h-4 w-4 ${color}`} />
          </div>
          <p className="text-xs font-semibold text-gray-600">{label}</p>
          <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
          <p className="mt-0.5 text-xs text-gray-400">{sub}</p>
        </Card>
      ))}
    </div>
  )
}
