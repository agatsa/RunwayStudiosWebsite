import { cn } from '@/lib/utils'
import type { PlanName } from '@/lib/types'

const PLAN_COLORS: Record<PlanName, string> = {
  free:    'bg-gray-100 text-gray-500',
  starter: 'bg-blue-50 text-blue-600',
  growth:  'bg-purple-50 text-purple-600',
  agency:  'bg-amber-50 text-amber-700',
}

export default function PlanBadge({ plan }: { plan: PlanName }) {
  return (
    <span className={cn(
      'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide',
      PLAN_COLORS[plan]
    )}>
      {plan}
    </span>
  )
}
