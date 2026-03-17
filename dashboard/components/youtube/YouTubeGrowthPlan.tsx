'use client'

import { useState } from 'react'
import { CheckCircle2, PlusCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { AiBadge } from '@/components/ui/AiBadge'
import BoldText from '@/components/ui/BoldText'
import type { YouTubeGrowthPlanHistoryItem } from '@/lib/types'

interface Props {
  planId: string
  steps: string[]
  history: YouTubeGrowthPlanHistoryItem[]
  workspaceId: string
}

export default function YouTubeGrowthPlan({ planId, steps, history, workspaceId }: Props) {
  const [taskCreated, setTaskCreated] = useState<Record<number, boolean>>({})
  const [taskLoading, setTaskLoading] = useState<Record<number, boolean>>({})
  const [showHistory, setShowHistory] = useState(false)

  const createTask = async (step: string, idx: number) => {
    setTaskLoading(prev => ({ ...prev, [idx]: true }))
    try {
      const res = await fetch('/api/youtube/growth-plan/create-task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          plan_id: planId || null,
          step_text: step,
          lever: 'growth_plan',
        }),
      })
      if (res.ok) {
        setTaskCreated(prev => ({ ...prev, [idx]: true }))
      }
    } catch {
      // silently fail
    } finally {
      setTaskLoading(prev => ({ ...prev, [idx]: false }))
    }
  }

  if (!steps.length) return null

  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 p-5">
      <div className="mb-4 flex items-center gap-2">
        <AiBadge label="AI Growth Plan" />
        <h2 className="text-sm font-semibold text-gray-900">5-Step YouTube Growth Plan</h2>
      </div>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-600 text-xs font-bold text-white">
              {i + 1}
            </span>
            <p className="flex-1 text-sm leading-relaxed text-gray-700"><BoldText text={step} /></p>
            {taskCreated[i] ? (
              <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-green-600">
                <CheckCircle2 className="h-3.5 w-3.5" /> Added
              </span>
            ) : (
              <button
                onClick={() => createTask(step, i)}
                disabled={taskLoading[i]}
                className="shrink-0 flex items-center gap-1 rounded-lg border border-sky-300 bg-white px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 transition-colors disabled:opacity-50"
              >
                <PlusCircle className="h-3 w-3" />
                {taskLoading[i] ? '…' : 'Add Task'}
              </button>
            )}
          </li>
        ))}
      </ol>

      {history.length > 0 && (
        <div className="mt-4 border-t border-sky-100 pt-3">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800"
          >
            {showHistory ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {showHistory ? 'Hide' : 'Show'} {history.length} past plan{history.length !== 1 ? 's' : ''}
          </button>
          {showHistory && (
            <div className="mt-3 space-y-4">
              {history.map(plan => (
                <div key={plan.id} className="rounded-lg border border-sky-100 bg-white/60 p-3">
                  <p className="mb-2 text-[10px] text-gray-400">
                    Generated{' '}
                    {new Date(plan.created_at).toLocaleDateString('en-IN', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })}
                  </p>
                  <ol className="space-y-1.5">
                    {(plan.steps as string[]).map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                        <span className="shrink-0 font-bold text-sky-400">{i + 1}.</span>
                        <BoldText text={s} />
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
