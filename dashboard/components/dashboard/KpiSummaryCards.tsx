import { Card } from '@tremor/react'
import { TrendingUp, DollarSign, MousePointer, Eye, ShoppingCart } from 'lucide-react'
import { formatINR, formatROAS, formatNumber, formatPercent } from '@/lib/utils'
import type { KpiSummary } from '@/lib/types'

interface Props {
  summary: KpiSummary
}

const cards = [
  {
    label: 'Total Spend',
    key: 'spend' as const,
    format: formatINR,
    icon: DollarSign,
    color: 'text-blue-600',
    bg: 'bg-blue-50',
  },
  {
    label: 'ROAS',
    key: 'roas' as const,
    format: formatROAS,
    icon: TrendingUp,
    color: 'text-green-600',
    bg: 'bg-green-50',
  },
  {
    label: 'Impressions',
    key: 'impressions' as const,
    format: (v: number) => formatNumber(v),
    icon: Eye,
    color: 'text-purple-600',
    bg: 'bg-purple-50',
  },
  {
    label: 'Clicks',
    key: 'clicks' as const,
    format: (v: number) => formatNumber(v),
    icon: MousePointer,
    color: 'text-orange-600',
    bg: 'bg-orange-50',
  },
  {
    label: 'Conversions',
    key: 'conversions' as const,
    format: (v: number) => formatNumber(v),
    icon: ShoppingCart,
    color: 'text-pink-600',
    bg: 'bg-pink-50',
  },
  {
    label: 'CTR',
    key: 'ctr' as const,
    format: formatPercent,
    icon: MousePointer,
    color: 'text-teal-600',
    bg: 'bg-teal-50',
  },
]

export default function KpiSummaryCards({ summary }: Props) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
      {cards.map(({ label, key, format, icon: Icon, color, bg }) => (
        <Card key={key} className="p-4">
          <div className={`mb-3 inline-flex rounded-lg p-2 ${bg}`}>
            <Icon className={`h-4 w-4 ${color}`} />
          </div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
          <p className="mt-1 text-xl font-bold text-gray-900">{format(summary[key] as number)}</p>
        </Card>
      ))}
    </div>
  )
}
