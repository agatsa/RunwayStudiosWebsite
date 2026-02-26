'use client'

import { useEffect, useState } from 'react'
import { Clock, Loader2 } from 'lucide-react'

interface TimeSlot {
  hour: number
  day_of_week: string
  spend: number
  conversions: number
  clicks: number
  impressions: number
}

interface TimeData {
  has_data: boolean
  last_upload_date: string | null
  slots: TimeSlot[]
}

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function buildMatrix(slots: TimeSlot[]): (number | null)[][] {
  // [day][hour] = conversions
  const matrix: (number | null)[][] = DAYS.map(() => Array(24).fill(null))
  for (const s of slots) {
    const dayIdx = DAYS.findIndex(d => d.toLowerCase().startsWith(s.day_of_week.toLowerCase().slice(0, 3)))
    if (dayIdx !== -1 && s.hour >= 0 && s.hour < 24) {
      const prev = matrix[dayIdx][s.hour]
      matrix[dayIdx][s.hour] = (prev ?? 0) + s.conversions
    }
  }
  return matrix
}

function intensityColor(val: number | null, max: number): string {
  if (val === null || max === 0) return 'bg-gray-100'
  const ratio = val / max
  if (ratio >= 0.8) return 'bg-blue-600'
  if (ratio >= 0.6) return 'bg-blue-500'
  if (ratio >= 0.4) return 'bg-blue-400'
  if (ratio >= 0.2) return 'bg-blue-300'
  if (ratio > 0) return 'bg-blue-200'
  return 'bg-gray-100'
}

// Show every 4th hour label
const HOUR_LABELS = Array.from({ length: 6 }, (_, i) => i * 4)

export default function GoogleAdsTimeHeatmap({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<TimeData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/google-ads/time-of-day?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [workspaceId])

  const matrix = data?.has_data ? buildMatrix(data.slots) : null
  const maxVal = matrix
    ? Math.max(0, ...matrix.flat().filter((v): v is number => v !== null))
    : 0

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-orange-500" />
            Time of Day Heatmap
          </h2>
          <p className="text-xs text-gray-600">Conversions by hour and day</p>
        </div>
        {data?.last_upload_date && (
          <span className="text-[10px] text-gray-400">
            {new Date(data.last_upload_date).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-8">
          <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
        </div>
      ) : !data?.has_data ? (
        <div className="p-4 text-center text-xs text-gray-400">
          No time-of-day data yet — upload a Time of Day report
        </div>
      ) : (
        <div className="p-4 overflow-x-auto">
          {/* Hour labels */}
          <div className="flex mb-1 pl-9">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="flex-1 text-center">
                {HOUR_LABELS.includes(h) && (
                  <span className="text-[9px] text-gray-400">{h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`}</span>
                )}
              </div>
            ))}
          </div>

          {/* Grid */}
          {DAYS.map((day, di) => (
            <div key={day} className="flex items-center mb-0.5">
              <span className="text-[9px] text-gray-400 w-9 shrink-0">{DAY_SHORT[di]}</span>
              {Array.from({ length: 24 }, (_, h) => {
                const val = matrix![di][h]
                return (
                  <div
                    key={h}
                    className={`flex-1 h-4 rounded-sm mx-px ${intensityColor(val, maxVal)}`}
                    title={val !== null ? `${day} ${h}:00 — ${val.toFixed(1)} conv` : undefined}
                  />
                )
              })}
            </div>
          ))}

          <div className="mt-2 flex items-center gap-1.5 justify-end">
            <span className="text-[9px] text-gray-400">Low</span>
            {['bg-blue-200', 'bg-blue-300', 'bg-blue-400', 'bg-blue-500', 'bg-blue-600'].map(c => (
              <div key={c} className={`h-3 w-3 rounded-sm ${c}`} />
            ))}
            <span className="text-[9px] text-gray-400">High conversions</span>
          </div>
        </div>
      )}
    </div>
  )
}
