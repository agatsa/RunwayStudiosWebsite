'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { formatNumber } from '@/lib/utils'

interface GridSlot {
  day: number
  day_name: string
  hour: number
  label: string
  avg_views: number
  video_count: number
  heat: number
}

interface BestSlot {
  day: number
  day_name: string
  hour: number
  avg_views: number
  video_count: number
}

interface TimingData {
  available: boolean
  best_slots: BestSlot[]
  grid: GridSlot[]
}

const HOURS = [0, 3, 6, 9, 12, 15, 18, 21]
const HOUR_LABELS = ['12am', '3am', '6am', '9am', '12pm', '3pm', '6pm', '9pm']
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function heatColor(heat: number, hasData: boolean): string {
  if (!hasData) return 'bg-gray-50 text-gray-300'
  if (heat >= 0.8) return 'bg-green-500 text-white font-bold'
  if (heat >= 0.5) return 'bg-green-300 text-green-900 font-medium'
  if (heat >= 0.2) return 'bg-green-100 text-green-800'
  return 'bg-gray-100 text-gray-400'
}

interface Props {
  workspaceId: string
}

export default function YouTubeUploadTiming({ workspaceId }: Props) {
  const [data, setData] = useState<TimingData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/youtube/upload-timing?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData({ available: false, best_slots: [], grid: [] }))
      .finally(() => setLoading(false))
  }, [workspaceId])

  // Build a lookup for grid rendering
  const gridMap: Record<string, GridSlot> = {}
  if (data?.grid) {
    for (const slot of data.grid) {
      gridMap[`${slot.day}-${slot.hour}`] = slot
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-1">Upload Timing Optimisation</h2>
      <p className="text-xs text-gray-400 mb-4">
        Best times to publish based on your own video history (IST)
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Analysing…
        </div>
      ) : !data?.available || data.grid.length === 0 ? (
        <p className="text-sm text-gray-400">
          Not enough video history to compute timing patterns yet. Upload more videos to see recommendations.
        </p>
      ) : (
        <>
          {/* Best slots */}
          {data.best_slots.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {data.best_slots.map((s, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 rounded-lg bg-green-50 border border-green-200 px-2.5 py-1.5 text-xs"
                >
                  <span className="text-green-700 font-semibold">#{i + 1}</span>
                  <span className="text-green-800 font-medium">{s.day_name} {s.hour}:00</span>
                  <span className="text-green-600">~{formatNumber(s.avg_views)} avg views</span>
                </div>
              ))}
            </div>
          )}

          {/* Heatmap grid */}
          <div className="overflow-x-auto">
            <table className="w-full text-center text-[10px]">
              <thead>
                <tr>
                  <th className="w-8 text-gray-400 font-normal pb-1" />
                  {DAYS.map(d => (
                    <th key={d} className="text-gray-500 font-medium pb-1">{d}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {HOURS.map((h, hi) => (
                  <tr key={h}>
                    <td className="text-gray-400 font-normal pr-1 text-right whitespace-nowrap">
                      {HOUR_LABELS[hi]}
                    </td>
                    {DAYS.map((_, di) => {
                      const slot = gridMap[`${di}-${h}`]
                      const heat = slot?.heat ?? 0
                      const hasData = (slot?.video_count ?? 0) > 0
                      return (
                        <td key={di} className="p-0.5">
                          <div
                            title={hasData ? `${slot.day_name} ${h}:00 — avg ${formatNumber(slot.avg_views)} views (${slot.video_count} video${slot.video_count > 1 ? 's' : ''})` : ''}
                            className={`rounded text-[9px] py-1 ${heatColor(heat, hasData)} cursor-default`}
                          >
                            {hasData ? formatNumber(slot.avg_views) : '·'}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-gray-400 mt-2">
            Green = higher avg views at that upload time · Based on {data.grid.filter(s => s.video_count > 0).reduce((a, s) => a + s.video_count, 0)} videos
          </p>
        </>
      )}
    </div>
  )
}
