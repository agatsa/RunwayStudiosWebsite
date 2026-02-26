'use client'

import { Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react'

interface Plan {
  id: string
  action_type: string
  new_value: {
    brief?: {
      product_name?: string
      goal?: string
      budget_daily?: number
      duration_days?: number
      channels?: string[]
    }
    concept?: {
      headline?: string
      recommended_format?: string
      kpi_targets?: { expected_roas?: number; expected_cpa?: number }
    }
  } | null
  triggered_by: string
  status: string
  ts: string
}

interface Props {
  plans: Plan[]
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'approved') return <CheckCircle className="h-4 w-4 text-green-500" />
  if (status === 'rejected') return <XCircle className="h-4 w-4 text-red-500" />
  return <AlertCircle className="h-4 w-4 text-yellow-500" />
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    executed: 'bg-blue-100 text-blue-700',
  }
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${map[status] ?? 'bg-gray-100 text-gray-600'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

export default function ActivePlans({ plans }: Props) {
  if (!plans.length) return null

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold text-gray-900">Campaign Plans</h2>
      <div className="space-y-3">
        {plans.map(plan => {
          const brief = plan.new_value?.brief
          const concept = plan.new_value?.concept
          const productName = brief?.product_name ?? 'Campaign'
          const headline = concept?.headline ?? ''
          const format = concept?.recommended_format ?? ''

          return (
            <div key={plan.id} className="rounded-xl border border-gray-200 p-4">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <StatusIcon status={plan.status} />
                    <h3 className="text-sm font-semibold text-gray-900">{productName}</h3>
                    {headline && (
                      <span className="text-xs text-gray-400 truncate max-w-[200px]">&ldquo;{headline}&rdquo;</span>
                    )}
                  </div>
                  {brief && (
                    <p className="mt-0.5 text-xs text-gray-500">
                      {brief.goal?.replace('_', ' ')} · ₹{brief.budget_daily?.toLocaleString()}/day · {brief.duration_days}d
                      {brief.channels?.length ? ` · ${brief.channels.join(', ')}` : ''}
                    </p>
                  )}
                  {format && <p className="text-xs text-gray-400 mt-0.5">Format: {format}</p>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <StatusBadge status={plan.status} />
                </div>
              </div>

              {concept?.kpi_targets && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    { label: 'ROAS Target', value: `${concept.kpi_targets.expected_roas ?? '—'}x` },
                    { label: 'CPA Target', value: `₹${concept.kpi_targets.expected_cpa ?? '—'}` },
                    { label: 'Budget/day', value: `₹${brief?.budget_daily?.toLocaleString() ?? '—'}` },
                    { label: 'Duration', value: `${brief?.duration_days ?? '—'} days` },
                  ].map(m => (
                    <div key={m.label} className="rounded-lg bg-gray-50 p-2.5 text-center">
                      <p className="text-[10px] text-gray-400 uppercase">{m.label}</p>
                      <p className="text-sm font-bold text-indigo-700">{m.value}</p>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center gap-1 mt-2 text-[10px] text-gray-400">
                <Clock className="h-3 w-3" />
                {new Date(plan.ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                <span className="mx-1">·</span>
                via {plan.triggered_by}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
