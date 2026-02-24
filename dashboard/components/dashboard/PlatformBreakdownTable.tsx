import { formatINR, formatROAS, formatNumber, formatPercent } from '@/lib/utils'
import type { KpiSummary } from '@/lib/types'

interface Props {
  summary: KpiSummary
}

const rows = [
  { label: 'Spend',       key: 'spend',       fmt: formatINR },
  { label: 'ROAS',        key: 'roas',        fmt: formatROAS },
  { label: 'Impressions', key: 'impressions', fmt: (v: number) => formatNumber(v) },
  { label: 'Clicks',      key: 'clicks',      fmt: (v: number) => formatNumber(v) },
  { label: 'Conversions', key: 'conversions', fmt: (v: number) => formatNumber(v) },
  { label: 'CTR',         key: 'ctr',         fmt: formatPercent },
]

export default function PlatformBreakdownTable({ summary }: Props) {
  const meta   = summary.platform_breakdown?.meta
  const google = summary.platform_breakdown?.google

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="py-2 pr-4 text-left font-medium text-gray-500">Metric</th>
            <th className="py-2 pr-4 text-right font-medium text-blue-600">Meta</th>
            <th className="py-2 pr-4 text-right font-medium text-emerald-600">Google</th>
            <th className="py-2 text-right font-medium text-gray-700">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, key, fmt }) => (
            <tr key={key} className="border-b border-gray-100 last:border-0">
              <td className="py-2 pr-4 text-gray-600">{label}</td>
              <td className="py-2 pr-4 text-right font-mono text-gray-800">
                {meta ? fmt(meta[key as keyof typeof meta] as number) : '—'}
              </td>
              <td className="py-2 pr-4 text-right font-mono text-gray-800">
                {google ? fmt(google[key as keyof typeof google] as number) : '—'}
              </td>
              <td className="py-2 text-right font-mono font-semibold text-gray-900">
                {fmt(summary[key as keyof KpiSummary] as number)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
