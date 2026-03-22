'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import BriefForm from '@/components/campaign-planner/BriefForm'
import ActivePlans from '@/components/campaign-planner/ActivePlans'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Plan = any

export default function CampaignPlannerTab({ wsId }: { wsId: string }) {
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)

  const loadPlans = () => {
    fetch(`/api/campaign-planner/plans?workspace_id=${wsId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setPlans(d?.plans ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadPlans() }, [wsId])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <BriefForm workspaceId={wsId} />
      {plans.length > 0 && <ActivePlans plans={plans} workspaceId={wsId} />}
    </div>
  )
}
