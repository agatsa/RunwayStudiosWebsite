'use client'

import { AreaChart } from '@tremor/react'
import type { DailyKpiRow } from '@/lib/types'

interface Props {
  daily: DailyKpiRow[]
}

function buildChartData(daily: DailyKpiRow[]) {
  const byDate: Record<string, { date: string; Meta: number; Google: number }> = {}
  for (const row of daily) {
    if (!byDate[row.date]) byDate[row.date] = { date: row.date, Meta: 0, Google: 0 }
    if (row.platform === 'meta')   byDate[row.date].Meta   += row.spend
    if (row.platform === 'google') byDate[row.date].Google += row.spend
  }
  return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date))
}

export default function SpendChart({ daily }: Props) {
  const data = buildChartData(daily)

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400">
        No spend data for the selected period
      </div>
    )
  }

  return (
    <AreaChart
      data={data}
      index="date"
      categories={['Meta', 'Google']}
      colors={['blue', 'emerald']}
      valueFormatter={(v: number) =>
        new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)
      }
      yAxisWidth={80}
      showAnimation
      className="h-48"
    />
  )
}
