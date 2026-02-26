'use client'

import { useState, useEffect, useCallback } from 'react'
import { CheckCircle2, Upload, RefreshCw } from 'lucide-react'
import GoogleAdsReportUploadModal, { type ReportType } from './GoogleAdsReportUploadModal'

interface ReportStatus {
  has_data: boolean
  last_upload_date: string | null
}

type StatusMap = Partial<Record<ReportType, ReportStatus>>

interface ReportCard {
  type: ReportType
  label: string
  tip: string
  statusKey?: ReportType   // which key to check in the status map (defaults to type)
}

const REPORTS: ReportCard[] = [
  { type: 'campaign',                label: 'Campaigns',             tip: 'Spend, ROAS, conversions per campaign' },
  { type: 'keyword',                 label: 'Keywords',              tip: 'QS audit, wasted spend, match types' },
  { type: 'search_term',             label: 'Search Terms',          tip: 'What users typed — find negatives' },
  { type: 'geo',                     label: 'Geographic',            tip: 'ROAS and CPA by city/region' },
  { type: 'device',                  label: 'Device',                tip: 'Mobile vs desktop conversion split' },
  { type: 'hour_of_day',             label: 'Time of Day',           tip: '24×7 conversion heatmap' },
  { type: 'asset',                   label: 'Ad Assets (RSA)',       tip: 'BEST/GOOD/LOW headline performance' },
  { type: 'auction_insight',         label: 'Search Auction',        tip: 'Search competitor overlap & IS' },
  { type: 'auction_insight_shopping',label: 'Shopping Auction',      tip: 'Shopping competitor overlap & IS', statusKey: 'auction_insight' },
]

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit' })
}

export default function GoogleAdsReportManager({ workspaceId }: { workspaceId: string }) {
  const [status, setStatus] = useState<StatusMap>({})
  const [openModal, setOpenModal] = useState<ReportType | null>(null)
  const [loadingStatus, setLoadingStatus] = useState(true)

  const fetchStatus = useCallback(() => {
    setLoadingStatus(true)
    fetch(`/api/upload/google-report-status?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(d => setStatus(d ?? {}))
      .catch(() => {})
      .finally(() => setLoadingStatus(false))
  }, [workspaceId])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  function handleSuccess() {
    setOpenModal(null)
    // Small delay so the backend has committed before re-fetch
    setTimeout(fetchStatus, 800)
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3.5">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Google Ads Report Center</h2>
          <p className="text-xs text-gray-600">Upload each report individually for richer intelligence</p>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loadingStatus}
          className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
          title="Refresh status"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loadingStatus ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-4">
        {REPORTS.map(({ type, label, tip, statusKey }) => {
          const s = status[statusKey ?? type]
          const hasData = s?.has_data ?? false
          const lastDate = s?.last_upload_date ?? null

          return (
            <div
              key={type}
              className={`rounded-xl border p-3 transition-colors ${
                hasData
                  ? 'border-green-200 bg-green-50/60'
                  : 'border-gray-200 bg-gray-50/60 hover:border-blue-200 hover:bg-blue-50/40'
              }`}
            >
              <div className="flex items-start justify-between gap-1 mb-2">
                <span className="text-xs font-semibold text-gray-800 leading-snug">{label}</span>
                {hasData
                  ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600 mt-0.5" />
                  : <Upload className="h-3.5 w-3.5 shrink-0 text-blue-400 mt-0.5" />
                }
              </div>

              {hasData && lastDate ? (
                <p className="text-[10px] text-gray-500 mb-2">{fmtDate(lastDate)}</p>
              ) : (
                <p className="text-[10px] text-gray-400 mb-2">{tip}</p>
              )}

              <button
                onClick={() => setOpenModal(type)}
                className={`w-full rounded-lg py-1 text-[11px] font-medium transition-colors ${
                  hasData
                    ? 'border border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                {hasData ? 'Re-upload' : 'Upload'}
              </button>
            </div>
          )
        })}
      </div>

      {openModal && (
        <GoogleAdsReportUploadModal
          reportType={openModal}
          workspaceId={workspaceId}
          onClose={() => setOpenModal(null)}
          onSuccess={handleSuccess}
        />
      )}
    </div>
  )
}
