'use client'

import { useState } from 'react'
import { formatINR, formatNumber, formatPercent } from '@/lib/utils'
import CampaignDetailPanel from '@/components/campaigns/CampaignDetailPanel'
import type { GoogleAdsCampaign } from '@/app/(app)/google-ads/page'

interface Props {
  campaigns: GoogleAdsCampaign[]
  workspaceId: string
}

function HealthBadge({ health, reason }: { health: string; reason: string }) {
  const styles = {
    good:     'bg-green-100 text-green-700',
    warning:  'bg-yellow-100 text-yellow-700',
    critical: 'bg-red-100 text-red-700',
  }[health] ?? 'bg-gray-100 text-gray-600'

  const labels = { good: '✅ Good', warning: '⚠️ Warning', critical: '🚨 Critical' }

  return (
    <span
      title={reason}
      className={`inline-flex cursor-help items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {labels[health as keyof typeof labels] ?? health}
    </span>
  )
}

export default function GoogleAdsCampaignTable({ campaigns, workspaceId }: Props) {
  const [selected, setSelected] = useState<GoogleAdsCampaign | null>(null)

  if (!campaigns.length) return null

  // Build a campaign shape compatible with CampaignDetailPanel (GoogleCampaign union)
  const toPanelCampaign = (c: GoogleAdsCampaign) => ({
    id: c.id,
    name: c.name,
    status: 'ACTIVE',
    channel_type: 'SEARCH',
    _platform: 'google' as const,
    _source: 'excel_upload' as const,
  })

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Campaigns{' '}
        <span className="ml-1 text-sm font-normal text-gray-400">
          — click a row for keyword breakdown &amp; AI suggestions
        </span>
      </h2>

      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
              <th className="px-4 py-3 font-medium">Campaign</th>
              <th className="px-4 py-3 font-medium">Health</th>
              <th className="px-4 py-3 font-medium text-right">Spend</th>
              <th className="px-4 py-3 font-medium text-right">ROAS</th>
              <th className="px-4 py-3 font-medium text-right">Clicks</th>
              <th className="px-4 py-3 font-medium text-right">Conv</th>
              <th className="px-4 py-3 font-medium text-right">CPC</th>
            </tr>
          </thead>
          <tbody>
            {campaigns.map((c) => (
              <tr
                key={c.id}
                onClick={() => setSelected(c)}
                className="cursor-pointer border-b border-gray-100 hover:bg-blue-50/40 transition-colors"
              >
                <td className="px-4 py-3 font-medium text-gray-900 max-w-[200px]">
                  <span className="block truncate">{c.name}</span>
                </td>
                <td className="px-4 py-3">
                  <HealthBadge health={c.health} reason={c.health_reason} />
                </td>
                <td className="px-4 py-3 text-right text-gray-700">{formatINR(c.spend)}</td>
                <td className={`px-4 py-3 text-right font-semibold ${
                  c.roas >= 2.5 ? 'text-green-700' : c.roas < 1 ? 'text-red-700' : 'text-yellow-700'
                }`}>
                  {c.roas.toFixed(2)}x
                </td>
                <td className="px-4 py-3 text-right text-gray-700">{formatNumber(c.clicks)}</td>
                <td className="px-4 py-3 text-right text-gray-700">{formatNumber(c.conversions)}</td>
                <td className="px-4 py-3 text-right text-gray-700">{formatINR(c.cpc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <CampaignDetailPanel
          campaign={toPanelCampaign(selected)}
          workspaceId={workspaceId}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
