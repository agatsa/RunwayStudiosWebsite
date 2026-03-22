'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Loader2, ExternalLink, AlertCircle } from 'lucide-react'

interface GoogleCampaign {
  id?: string
  name: string
  status: string
  spend: number
  clicks: number
  impressions: number
  conversions: number
  ctr: number
}

function fmt(n: number, prefix = '') {
  if (n >= 100_000) return `${prefix}${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString('en-IN')}`
}

export default function GoogleTabContent({ wsId }: { wsId: string }) {
  const [campaigns, setCampaigns] = useState<GoogleCampaign[]>([])
  const [loading, setLoading] = useState(true)
  const [apiBlocked, setApiBlocked] = useState(false)

  useEffect(() => {
    // Try uploaded Excel data first (Google uploads are platform=google in kpi_hourly)
    fetch(`/api/upload/campaigns?workspace_id=${wsId}&days=365`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.campaigns?.length) {
          setCampaigns(d.campaigns)
        } else {
          // Try live Google Ads API
          return fetch(`/api/campaigns/google?workspace_id=${wsId}`)
            .then(r => r.ok ? r.json() : null)
            .then(d2 => {
              if (d2?.campaigns?.length) {
                setCampaigns(d2.campaigns)
              } else if (d2?.error?.includes('DEVELOPER_TOKEN_NOT_APPROVED')) {
                setApiBlocked(true)
              }
            })
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [wsId])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Google Ads Campaigns</h2>
        <Link href={`/google-ads?ws=${wsId}`} className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline">
          Full report <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      {apiBlocked && (
        <div className="flex items-start gap-3 rounded-xl border border-yellow-200 bg-yellow-50 p-4">
          <AlertCircle className="h-4 w-4 text-yellow-600 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-yellow-800">Google Ads API pending approval</p>
            <p className="text-xs text-yellow-700 mt-0.5">
              Upload a Google Ads Excel report in the Upload tab to see your data while API approval is pending.
            </p>
          </div>
        </div>
      )}

      {campaigns.length === 0 && !apiBlocked ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-sm font-medium text-gray-700">No Google Ads data yet</p>
          <p className="mt-1 text-xs text-gray-500">
            Connect Google Ads in Setup or upload an Excel report in the Upload tab.
          </p>
        </div>
      ) : campaigns.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Campaign</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Spend</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Clicks</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Conv.</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {campaigns.slice(0, 10).map((c, i) => (
                <tr key={c.id ?? i} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">{c.name}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">₹{fmt(c.spend ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{fmt(c.clicks ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{c.conversions ?? 0}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                      c.status === 'ENABLED' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {(c.status || 'UNKNOWN').toLowerCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
