'use client'

import { Crown, Zap } from 'lucide-react'
import Link from 'next/link'

type Plan = 'free' | 'starter' | 'growth' | 'agency'

const PLAN_RANK: Record<Plan, number> = {
  free: 0, starter: 1, growth: 2, agency: 3,
}

const PLAN_COLOR: Record<Plan, string> = {
  free: 'bg-gray-600',
  starter: 'bg-blue-600',
  growth: 'bg-violet-600',
  agency: 'bg-amber-600',
}

interface Props {
  /** Plan required to access this content */
  requiredPlan: Plan
  /** Current user plan */
  currentPlan?: Plan
  /** Optional: workspace ID for billing link */
  wsId?: string
  /** Optional: feature name shown in the overlay */
  feature?: string
  /** Optional: credit cost per use */
  creditCost?: number
  /** Content to blur */
  children: React.ReactNode
  /** Minimum height of the blurred area (default 200px) */
  minHeight?: number
}

/**
 * Wraps content in a blur overlay when the user's plan doesn't meet requirements.
 * Shows the content dimmed + blurred with an upgrade CTA on top.
 * If the user meets the plan requirement, renders children normally.
 */
export default function PremiumBlur({
  requiredPlan,
  currentPlan = 'free',
  wsId,
  feature,
  creditCost,
  children,
  minHeight = 200,
}: Props) {
  // If user meets the plan requirement, render normally
  if (PLAN_RANK[currentPlan] >= PLAN_RANK[requiredPlan]) {
    return <>{children}</>
  }

  const billingHref = wsId ? `/billing?ws=${wsId}` : '/billing'
  const planLabel = requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1)
  const planColorClass = PLAN_COLOR[requiredPlan]

  return (
    <div className="relative overflow-hidden rounded-xl" style={{ minHeight }}>
      {/* Blurred content underneath */}
      <div className="pointer-events-none select-none blur-sm opacity-40">
        {children}
      </div>

      {/* Upgrade overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white/60 backdrop-blur-sm">
        <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${planColorClass}`}>
          <Crown className="h-6 w-6 text-white" />
        </div>
        <div className="text-center px-4">
          <p className="text-sm font-bold text-gray-900">
            {feature ? `${feature} requires ${planLabel} plan` : `${planLabel} plan required`}
          </p>
          {creditCost && (
            <p className="flex items-center justify-center gap-1 text-xs text-gray-500 mt-0.5">
              <Zap className="h-3 w-3 text-amber-400" />
              {creditCost} credits per run
            </p>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Upgrade to unlock real-time data, AI insights, and more.
          </p>
        </div>
        <Link
          href={billingHref}
          className={`rounded-lg px-5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 ${planColorClass}`}
        >
          Upgrade to {planLabel}
        </Link>
      </div>
    </div>
  )
}
