'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Pencil, X, Loader2 } from 'lucide-react'

interface Props {
  platform: 'meta' | 'google'
  workspaceId: string
  entityId: string
  currentBudgetInr?: number | null
}

export default function BudgetEditDialog({ platform, workspaceId, entityId, currentBudgetInr }: Props) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(currentBudgetInr?.toString() ?? '')
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const budget = parseFloat(value)
    if (isNaN(budget) || budget <= 0) {
      toast.error('Enter a valid budget amount')
      return
    }
    startTransition(async () => {
      try {
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
        setOpen(false)
        router.refresh()
      } catch {
        toast.error('Failed to update budget')
      }
    })
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-800"
      >
        <Pencil className="h-3 w-3" />
        Edit
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-gray-900">Edit Daily Budget</h3>
              <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Daily Budget (INR)
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
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
