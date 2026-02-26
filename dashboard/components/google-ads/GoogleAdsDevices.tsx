'use client'

import { useEffect, useState } from 'react'
import { Smartphone, Loader2 } from 'lucide-react'

interface DeviceRow {
  device: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  cpa: number | null
  spend_pct: number
}

interface DeviceData {
  has_data: boolean
  last_upload_date: string | null
  devices: DeviceRow[]
}

const DEVICE_COLORS: Record<string, string> = {
  mobile: 'bg-blue-500',
  desktop: 'bg-green-500',
  tablet: 'bg-purple-500',
}

function getColor(device: string) {
  const lower = device.toLowerCase()
  for (const [key, cls] of Object.entries(DEVICE_COLORS)) {
    if (lower.includes(key)) return cls
  }
  return 'bg-gray-400'
}

function fmt(n: number) {
  return n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

export default function GoogleAdsDevices({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<DeviceData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/google-ads/devices?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [workspaceId])

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
            <Smartphone className="h-3.5 w-3.5 text-blue-600" />
            Device Breakdown
          </h2>
          <p className="text-xs text-gray-600">Mobile vs desktop vs tablet</p>
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
          No device data yet — upload a Device report
        </div>
      ) : (
        <div className="p-4 space-y-4">
          {data.devices.map((d, i) => (
            <div key={i}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-gray-800">{d.device}</span>
                <div className="flex items-center gap-2 text-xs text-gray-600">
                  <span>₹{fmt(d.spend)}</span>
                  <span className="font-semibold text-gray-800">{d.roas.toFixed(1)}x ROAS</span>
                  <span className="text-gray-400">{d.spend_pct}%</span>
                </div>
              </div>
              <div className="h-2.5 rounded-full bg-gray-100">
                <div
                  className={`h-2.5 rounded-full ${getColor(d.device)}`}
                  style={{ width: `${Math.min(d.spend_pct, 100)}%` }}
                />
              </div>
              {d.cpa !== null && (
                <p className="mt-1 text-[10px] text-gray-400">
                  CPA ₹{fmt(d.cpa)} · {d.conversions.toFixed(0)} conv
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
