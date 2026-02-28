'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Play, Pause, Loader2 } from 'lucide-react'
import { formatINR, cn } from '@/lib/utils'
import BudgetEditDialog from './BudgetEditDialog'
import type { MetaCampaign, GoogleCampaign } from '@/lib/types'

type Campaign = (MetaCampaign | GoogleCampaign) & { _platform: 'meta' | 'google' }

interface Props {
  campaign: Campaign
  workspaceId: string
}

export default function CampaignRow({ campaign, workspaceId }: Props) {
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const isActive = campaign.status === 'ACTIVE' || campaign.status === 'active'
  const dailyBudget = campaign.daily_budget_inr

  const toggleStatus = () => {
    startTransition(async () => {
      const endpoint = isActive ? '/api/campaigns/pause' : '/api/campaigns/resume'
      const action   = isActive ? 'pause' : 'resume'
      try {
        const res  = await fetch(endpoint, {
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
      } catch (e) {
        toast.error(`Failed to ${action} campaign — check your connection`)
      }
    })
  }

  return (
    <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
      <td className="py-3 pl-4 pr-4">
        <p className="font-medium text-gray-900">{campaign.name}</p>
        <p className="text-xs text-gray-400">{campaign.id}</p>
      </td>
      <td className="py-3 pr-4">
        <span className={cn(
          'rounded-full px-2.5 py-0.5 text-xs font-medium',
          isActive ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800',
        )}>
          {campaign.status}
        </span>
      </td>
      <td className="py-3 pr-4 font-mono text-sm text-gray-700">
        {dailyBudget != null ? formatINR(dailyBudget) : '—'}
      </td>
      <td className="py-3">
        <div className="flex items-center gap-2">
          {/* Pause / Resume */}
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

          {/* Budget edit */}
          <BudgetEditDialog
            platform={campaign._platform}
            workspaceId={workspaceId}
            entityId={campaign.id}
            currentBudgetInr={dailyBudget}
          />
        </div>
      </td>
    </tr>
  )
}
