'use client'

import { useState } from 'react'
import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Play, Pause, Loader2 } from 'lucide-react'
import { cn, formatINR } from '@/lib/utils'
import BudgetEditDialog from './BudgetEditDialog'
import CampaignDetailPanel from './CampaignDetailPanel'
import type { MetaCampaign, GoogleCampaign } from '@/lib/types'

type EnrichedCampaign = (MetaCampaign | GoogleCampaign) & { _platform: 'meta' | 'google'; _source?: 'excel_upload' }

interface Props {
  title: string
  campaigns: EnrichedCampaign[]
  workspaceId: string
  emptyMessage?: string
}

function CampaignRow({
  campaign,
  workspaceId,
  selected,
  onSelect,
}: {
  campaign: EnrichedCampaign
  workspaceId: string
  selected: boolean
  onSelect: () => void
}) {
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const isUploaded = campaign._source === 'excel_upload'
  const isActive =
    campaign.status === 'ACTIVE' ||
    (campaign as MetaCampaign).effective_status === 'ACTIVE'
  const dailyBudget = (campaign as MetaCampaign).daily_budget_inr

  const toggleStatus = (e: React.MouseEvent) => {
    e.stopPropagation()
    startTransition(async () => {
      const endpoint = isActive ? '/api/campaigns/pause' : '/api/campaigns/resume'
      const action   = isActive ? 'pause' : 'resume'
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            platform: campaign._platform,
            workspace_id: workspaceId,
            entity_id: campaign.id,
          }),
        })
        const data = await res.json()

        if (!res.ok || data.ok === false) {
          const errMsg = data.error || data.detail || `Failed to ${action} campaign`
          toast.error(`Could not ${action} campaign`, {
            description: errMsg,
            duration: 8000,
          })
          return
        }

        toast.success(isActive ? 'Campaign paused' : 'Campaign resumed')
        router.refresh()
      } catch {
        toast.error(`Failed to ${action} campaign — check your connection`)
      }
    })
  }

  return (
    <tr
      onClick={onSelect}
      className={cn(
        'border-b border-gray-100 last:border-0 cursor-pointer transition-colors',
        selected ? 'bg-blue-50' : 'hover:bg-gray-50',
      )}
    >
      <td className="py-3 pl-4 pr-4">
        <p className="font-medium text-gray-900">{campaign.name}</p>
        <p className="text-xs text-gray-400">
          {(campaign as MetaCampaign).objective ?? campaign._platform} · {campaign.id}
        </p>
      </td>
      <td className="py-3 pr-4">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              'rounded-full px-2.5 py-0.5 text-xs font-medium',
              isActive
                ? 'bg-green-100 text-green-800'
                : 'bg-yellow-100 text-yellow-800',
            )}
          >
            {campaign.status}
          </span>
          {isUploaded && (
            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
              Uploaded
            </span>
          )}
        </div>
      </td>
      <td className="py-3 pr-4 font-mono text-sm text-gray-700">
        {dailyBudget != null ? formatINR(dailyBudget) : '—'}
      </td>
      <td className="py-3 pr-4 text-xs text-blue-500 font-medium">
        View details →
      </td>
      <td className="py-3" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          {!isUploaded && (
            <button
              onClick={toggleStatus}
              disabled={isPending}
              className={cn(
                'flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50',
                isActive
                  ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
                  : 'bg-green-100 text-green-700 hover:bg-green-200',
              )}
            >
              {isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : isActive ? (
                <Pause className="h-3 w-3" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              {isActive ? 'Pause' : 'Resume'}
            </button>
          )}
          <BudgetEditDialog
            platform={campaign._platform}
            workspaceId={workspaceId}
            entityId={campaign.id}
            entityName={campaign.name}
            currentBudgetInr={dailyBudget}
            isUploaded={isUploaded}
          />
        </div>
      </td>
    </tr>
  )
}

export default function CampaignSection({
  title,
  campaigns,
  workspaceId,
  emptyMessage,
}: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = campaigns.find(c => c.id === selectedId) ?? null

  return (
    <>
      <div>
        <h2 className="mb-3 text-sm font-semibold text-gray-700">{title}</h2>
        {campaigns.length === 0 ? (
          <div className="flex h-32 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
            <p className="text-sm text-gray-400">{emptyMessage ?? 'No campaigns'}</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="py-3 pl-4 pr-4 text-left text-xs font-medium uppercase text-gray-500">
                    Campaign
                  </th>
                  <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">
                    Status
                  </th>
                  <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">
                    Daily Budget
                  </th>
                  <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">
                    Insights
                  </th>
                  <th className="py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map(c => (
                  <CampaignRow
                    key={`${c._platform}-${c.id}`}
                    campaign={c}
                    workspaceId={workspaceId}
                    selected={selectedId === c.id}
                    onSelect={() => setSelectedId(selectedId === c.id ? null : c.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <CampaignDetailPanel
          campaign={selected}
          workspaceId={workspaceId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  )
}
