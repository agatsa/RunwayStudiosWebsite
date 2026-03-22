'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Loader2, ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface Campaign {
  id: string
  name: string
  status: string
  effective_status: string
  spend: number
  clicks: number
  roas: number
  impressions: number
  platform?: string
  _source?: string
}

function fmt(n: number, prefix = '') {
  if (n >= 100_000) return `${prefix}${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString('en-IN')}`
}

function RoasIcon({ roas }: { roas: number }) {
  if (roas >= 3) return <TrendingUp className="h-3.5 w-3.5 text-green-500" />
  if (roas >= 1.5) return <Minus className="h-3.5 w-3.5 text-yellow-500" />
  return <TrendingDown className="h-3.5 w-3.5 text-red-500" />
}

export default function MetaTabContent({ wsId }: { wsId: string }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch(`/api/campaigns/list?workspace_id=${wsId}&days=365`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        const all: Campaign[] = [
          ...(d?.campaigns ?? []),
          ...(d?.uploaded_campaigns ?? []),
        ]
        setCampaigns(all)
      })
      .catch(() => setError(true))
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
        <h2 className="text-base font-semibold text-gray-900">Meta Ads Campaigns</h2>
        <Link
          href={`/campaigns?ws=${wsId}`}
          className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline"
        >
          Full report <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      {campaigns.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
          <p className="text-sm font-medium text-gray-700">No Meta Ads data yet</p>
          <p className="mt-1 text-xs text-gray-500">
            Connect your Meta account in Setup or upload an Excel report in the Upload tab.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Campaign</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Spend</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Clicks</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">ROAS</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {campaigns.slice(0, 10).map((c, i) => (
                <tr key={c.id ?? i} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">{c.name}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">₹{fmt(c.spend ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">{fmt(c.clicks ?? 0)}</td>
                  <td className="px-4 py-3 text-right">
                    {c.roas > 0 ? (
                      <span className="inline-flex items-center gap-1 font-medium text-sm">
                        <RoasIcon roas={c.roas} />
                        {c.roas.toFixed(2)}x
                      </span>
                    ) : (
                      <span className="text-gray-400 text-sm">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                      (c.effective_status || c.status) === 'ACTIVE'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-500'
                    }`}>
                      {(c.effective_status || c.status || 'UNKNOWN').toLowerCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {campaigns.length > 10 && (
            <div className="border-t border-gray-100 px-4 py-3 text-center">
              <Link href={`/campaigns?ws=${wsId}`} className="text-xs font-medium text-brand-600 hover:underline">
                {campaigns.length - 10} more campaigns — view full report <ArrowRight className="inline h-3 w-3" />
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
