'use client'

import { AreaChart } from '@tremor/react'
import type { DailyKpiRow } from '@/lib/types'

interface Props {
  daily: DailyKpiRow[]
}

function buildChartData(daily: DailyKpiRow[]) {
  const byDate: Record<string, { date: string; Meta: number; Google: number }> = {}
  const hasGoogle = daily.some(r => r.platform === 'google' && r.spend > 0)
  for (const row of daily) {
    if (!byDate[row.date]) byDate[row.date] = { date: row.date, Meta: 0, Google: 0 }
    if (row.platform === 'meta')   byDate[row.date].Meta   += row.spend
    if (row.platform === 'google') byDate[row.date].Google += row.spend
  }
  return {
    data: Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date)),
    hasGoogle,
  }
}

export default function SpendChart({ daily }: Props) {
  const { data, hasGoogle } = buildChartData(daily)

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400">
        No spend data for the selected period
      </div>
    )
  }

  const categories = hasGoogle ? ['Meta', 'Google'] : ['Meta']
  const colors     = hasGoogle ? ['blue', 'emerald'] : ['blue']

  return (
    <AreaChart
      data={data}
      index="date"
      categories={categories}
      colors={colors}
      valueFormatter={(v: number) =>
        new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)
      }
      yAxisWidth={80}
      showAnimation
      className="h-48"
    />
  )
}
