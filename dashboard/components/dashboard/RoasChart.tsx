'use client'

import { LineChart } from '@tremor/react'
import type { DailyKpiRow } from '@/lib/types'

const TARGET_ROAS = 2.5

interface Props {
  daily: DailyKpiRow[]
}

function buildChartData(daily: DailyKpiRow[]) {
  const byDate: Record<string, { date: string; Meta: number; Google: number; Target: number }> = {}
  const hasGoogle = daily.some(r => r.platform === 'google' && r.roas > 0)
  for (const row of daily) {
    if (!byDate[row.date]) byDate[row.date] = { date: row.date, Meta: 0, Google: 0, Target: TARGET_ROAS }
    if (row.platform === 'meta')   byDate[row.date].Meta   = row.roas
    if (row.platform === 'google') byDate[row.date].Google = row.roas
  }
  return {
    data: Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date)),
    hasGoogle,
  }
}

export default function RoasChart({ daily }: Props) {
  const { data, hasGoogle } = buildChartData(daily)

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400">
        No ROAS data for the selected period
      </div>
    )
  }

  const categories = hasGoogle ? ['Meta', 'Google', 'Target'] : ['Meta', 'Target']
  const colors     = hasGoogle ? ['blue', 'emerald', 'rose']  : ['blue', 'rose']

  return (
    <LineChart
      data={data}
      index="date"
      categories={categories}
      colors={colors}
      valueFormatter={(v: number) => `${v.toFixed(2)}x`}
      yAxisWidth={60}
      showAnimation
      className="h-48"
    />
  )
}
