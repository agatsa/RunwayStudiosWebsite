import Link from 'next/link'
import { Crown, Zap } from 'lucide-react'
import type { PlanName } from '@/lib/types'

const PLAN_RANK: Record<string, number> = { free: 0, starter: 1, growth: 2, agency: 3 }

interface Props {
  requiredPlan: string
  feature: string
  creditCost?: number
  wsId?: string
  currentPlan?: PlanName
}

export default function PlanGateBanner({ requiredPlan, feature, creditCost, wsId, currentPlan }: Props) {
  // Hide banner entirely if user already meets the plan requirement
  if (currentPlan && PLAN_RANK[currentPlan] >= PLAN_RANK[requiredPlan.toLowerCase()]) return null

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-center gap-3 mb-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100">
        <Crown className="h-4 w-4 text-amber-600" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-amber-800">{requiredPlan} plan feature</p>
        <p className="text-xs text-amber-700 mt-0.5">
          {feature} requires {requiredPlan} or higher.
          {currentPlan && <span className="ml-1">You're on <strong>{currentPlan}</strong>.</span>}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {creditCost != null && (
          <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">
            <Zap className="h-3 w-3" />
            {creditCost} credits/run
          </span>
        )}
        <Link
          href={wsId ? `/billing?ws=${wsId}` : '/billing'}
          className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 transition-colors"
        >
          Upgrade
        </Link>
      </div>
    </div>
  )
}
