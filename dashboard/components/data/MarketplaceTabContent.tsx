'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ExternalLink, Loader2, ShoppingBag } from 'lucide-react'

interface AmazonCampaign {
  name: string
  spend: number
  sales: number
  acos: number
  impressions: number
  clicks: number
}

function fmt(n: number, prefix = '') {
  if (n >= 100_000) return `${prefix}${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString('en-IN')}`
}

export default function MarketplaceTabContent({ wsId }: { wsId: string }) {
  const [campaigns, setCampaigns] = useState<AmazonCampaign[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/marketplace/campaigns?workspace_id=${wsId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setCampaigns(d?.campaigns ?? []))
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
        <h2 className="text-base font-semibold text-gray-900">Marketplace (Amazon)</h2>
        <Link href={`/marketplace?ws=${wsId}`} className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline">
          Full report <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      {campaigns.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
          <ShoppingBag className="h-8 w-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm font-medium text-gray-700">No marketplace data yet</p>
          <p className="mt-1 text-xs text-gray-500">Upload an Amazon Ads CSV in the Upload tab to see your SP/SB/SD campaign data.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Campaign</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Spend</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">Sales</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">ACoS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {campaigns.slice(0, 10).map((c, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">{c.name}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">₹{fmt(c.spend ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-700">₹{fmt(c.sales ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm">
                    <span className={c.acos > 0.4 ? 'text-red-600 font-medium' : c.acos > 0.25 ? 'text-yellow-600' : 'text-green-600'}>
                      {c.acos > 0 ? `${(c.acos * 100).toFixed(1)}%` : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
