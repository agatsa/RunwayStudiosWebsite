'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { TrendingUp, X, Loader2 } from 'lucide-react'

interface Props {
  platform: 'meta' | 'google'
  workspaceId: string
  entityId: string
  entityName?: string
  currentBudgetInr?: number | null
  isUploaded?: boolean
}

export default function BudgetEditDialog({
  platform, workspaceId, entityId, entityName, currentBudgetInr, isUploaded,
}: Props) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(currentBudgetInr?.toString() ?? '')
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const current = currentBudgetInr ?? 0

  const setPreset = (pct: number) => {
    const next = Math.round(current * (1 + pct / 100))
    setValue(next.toString())
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const budget = parseFloat(value)
    if (isNaN(budget) || budget <= 0) {
      toast.error('Enter a valid budget amount')
      return
    }
    startTransition(async () => {
      try {
        if (isUploaded) {
          // For uploaded campaigns: create a pending action request
          const res = await fetch('/api/actions/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              workspace_id: workspaceId,
              platform,
              entity_id: entityId,
              entity_name: entityName || entityId,
              entity_level: 'campaign',
              action_type: budget > current ? 'increase_budget' : 'reduce_budget',
              description: `Change daily budget from ₹${current.toLocaleString('en-IN')} to ₹${budget.toLocaleString('en-IN')}`,
              suggested_value: `₹${budget.toLocaleString('en-IN')}/day`,
              triggered_by: 'dashboard_user',
            }),
          })
          if (!res.ok) throw new Error('Failed')
          toast.success('Budget request added to Approvals queue')
        } else {
          // For live campaigns: update directly via API
          const res = await fetch('/api/campaigns/budget', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              platform,
              workspace_id: workspaceId,
              entity_id: entityId,
              daily_budget_inr: budget,
            }),
          })
          if (!res.ok) throw new Error('Failed')
          toast.success(`Budget updated to ₹${budget.toLocaleString('en-IN')}`)
          router.refresh()
        }
        setOpen(false)
      } catch {
        toast.error(isUploaded ? 'Failed to create budget request' : 'Failed to update budget')
      }
    })
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1 rounded-lg bg-sky-50 border border-sky-200 px-2.5 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-100 transition-colors"
      >
        <TrendingUp className="h-3 w-3" />
        Budget
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">
                  {isUploaded ? 'Request Budget Change' : 'Edit Daily Budget'}
                </h3>
                {isUploaded && (
                  <p className="text-xs text-gray-500 mt-0.5">Creates a pending task in your Approvals queue</p>
                )}
              </div>
              <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>

            {current > 0 && (
              <div className="mb-4">
                <p className="text-xs text-gray-500 mb-2">Quick adjust from ₹{current.toLocaleString('en-IN')}/day</p>
                <div className="flex gap-2">
                  {[10, 25, 50].map(pct => (
                    <button
                      key={pct}
                      type="button"
                      onClick={() => setPreset(pct)}
                      className="flex-1 rounded-lg border border-green-200 bg-green-50 py-1.5 text-xs font-semibold text-green-700 hover:bg-green-100"
                    >
                      +{pct}%
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setPreset(-20)}
                    className="flex-1 rounded-lg border border-red-200 bg-red-50 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100"
                  >
                    -20%
                  </button>
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  {isUploaded ? 'Requested Budget (INR)' : 'Daily Budget (INR)'}
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-medium text-gray-500">₹</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={value}
                    onChange={e => setValue(e.target.value)}
                    placeholder={currentBudgetInr?.toString() ?? '0'}
                    className="w-full rounded-lg border border-gray-200 py-2 pl-7 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                  />
                </div>
                {value && current > 0 && (
                  <p className="mt-1 text-xs text-gray-500">
                    {parseFloat(value) > current
                      ? `+₹${(parseFloat(value) - current).toLocaleString('en-IN')}/day (+${Math.round((parseFloat(value)/current-1)*100)}%)`
                      : `-₹${(current - parseFloat(value)).toLocaleString('en-IN')}/day (-${Math.round((1-parseFloat(value)/current)*100)}%)`}
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="flex-1 rounded-lg border border-gray-200 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-brand-600 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isUploaded ? 'Request Change' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
