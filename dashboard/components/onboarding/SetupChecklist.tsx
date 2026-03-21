'use client'

import { useState, useEffect } from 'react'
import { CheckCircle2, Circle, ChevronRight, X, Megaphone, BarChart2, PlayCircle, Crosshair, Sparkles, ShoppingBag, ChevronDown } from 'lucide-react'
import Link from 'next/link'

interface Step {
  id: string
  icon: React.ElementType
  iconColor: string
  label: string
  description: string
  href: string
  done: boolean
}

interface Props {
  workspaceId: string
}

const DISMISS_KEY = 'runway_setup_checklist_dismissed'

export default function SetupChecklist({ workspaceId: wsId }: Props) {
  const [steps, setSteps] = useState<Step[]>([])
  const [loading, setLoading] = useState(true)
  const [dismissed, setDismissed] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const d = localStorage.getItem(DISMISS_KEY)
      if (d === wsId) { setDismissed(true); setLoading(false); return }
    }
    fetchStatus()
  }, [wsId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchStatus() {
    try {
      const [connRes, biRes, gosRes] = await Promise.allSettled([
        fetch(`/api/settings/connections?workspace_id=${wsId}`),
        fetch(`/api/brand-intel/status?workspace_id=${wsId}`),
        fetch(`/api/growth-os/latest?workspace_id=${wsId}`),
      ])

      const conn  = connRes.status === 'fulfilled' && connRes.value.ok  ? await connRes.value.json()  : null
      const bi    = biRes.status === 'fulfilled'   && biRes.value.ok    ? await biRes.value.json()    : null
      const gos   = gosRes.status === 'fulfilled'  && gosRes.value.ok   ? await gosRes.value.json()   : null

      const metaConnected    = !!(conn?.meta?.has_token)
      const googleConnected  = !!(conn?.google?.has_token)
      const youtubeConnected = !!(conn?.youtube?.has_token)
      const shopifyConnected = !!(conn?.shopify?.connected)
      const brandIntelDone   = bi?.exists && bi?.status === 'completed'
      const growthOsDone     = !!(gos?.plan?.id)

      const newSteps: Step[] = [
        {
          id: 'meta', icon: Megaphone, iconColor: 'text-blue-600',
          label: 'Connect Meta Ads',
          description: 'See Facebook & Instagram campaign ROAS, spend, and audience data.',
          href: `/settings?ws=${wsId}`,
          done: metaConnected,
        },
        {
          id: 'google', icon: BarChart2, iconColor: 'text-green-600',
          label: 'Connect Google',
          description: 'One click connects Google Ads, YouTube Analytics, and GA4.',
          href: `/settings?ws=${wsId}`,
          done: googleConnected,
        },
        {
          id: 'youtube', icon: PlayCircle, iconColor: 'text-red-600',
          label: 'Connect YouTube Channel',
          description: 'Track video performance, shorts, and grow your channel with AI.',
          href: `/settings?ws=${wsId}`,
          done: youtubeConnected,
        },
        {
          id: 'shopify', icon: ShoppingBag, iconColor: 'text-orange-600',
          label: 'Connect Shopify Store',
          description: 'Sync your product catalog and attribution data automatically.',
          href: `/settings?ws=${wsId}`,
          done: shopifyConnected,
        },
        {
          id: 'brand_intel', icon: Crosshair, iconColor: 'text-indigo-600',
          label: 'Run Competitor Intelligence',
          description: 'ARIA auto-discovers competitors and builds a full intelligence brief.',
          href: `/competitor-intel?ws=${wsId}&tab=brand`,
          done: brandIntelDone,
        },
        {
          id: 'growth_os', icon: Sparkles, iconColor: 'text-amber-600',
          label: 'Generate Your First Growth Plan',
          description: 'ARIA analyses all your data and creates a 12-15 action growth roadmap.',
          href: `/growth-os?ws=${wsId}`,
          done: growthOsDone,
        },
      ]

      setSteps(newSteps)
    } catch {
      // silently ignore
    } finally {
      setLoading(false)
    }
  }

  const dismiss = () => {
    if (typeof window !== 'undefined') localStorage.setItem(DISMISS_KEY, wsId)
    setDismissed(true)
  }

  const doneCount = steps.filter(s => s.done).length
  const total = steps.length
  const allDone = doneCount === total && total > 0
  const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0

  // Auto-dismiss when all done (after a short delay)
  useEffect(() => {
    if (allDone) {
      const t = setTimeout(dismiss, 4000)
      return () => clearTimeout(t)
    }
  }, [allDone]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading || dismissed) return null

  const nextStep = steps.find(s => !s.done)

  return (
    <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white overflow-hidden mb-2">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-indigo-100/60">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-bold text-gray-900">
              {allDone ? '🎉 All set! ARIA is ready.' : `Get Started — ${doneCount} of ${total} complete`}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex-1 h-1.5 rounded-full bg-indigo-100 max-w-[200px]">
              <div
                className="h-1.5 rounded-full bg-indigo-500 transition-all duration-700"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-xs text-indigo-500 font-semibold">{pct}%</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-white/70 transition-colors"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            <ChevronDown className={`h-4 w-4 transition-transform duration-200 ${collapsed ? '-rotate-90' : ''}`} />
          </button>
          <button
            onClick={dismiss}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-white/70 transition-colors"
            title="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Steps grid */}
      {!collapsed && (
        <div className="p-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {steps.map(step => {
            const Icon = step.icon
            const isNext = step.id === nextStep?.id
            return (
              <Link
                key={step.id}
                href={step.done ? '#' : step.href}
                className={`flex items-start gap-3 rounded-xl px-3.5 py-3 transition-all ${
                  step.done
                    ? 'bg-green-50 border border-green-100 pointer-events-none'
                    : isNext
                    ? 'bg-white border border-indigo-200 shadow-sm hover:shadow-md hover:border-indigo-300'
                    : 'bg-white/60 border border-gray-100 hover:bg-white hover:border-gray-200'
                }`}
              >
                {/* Status icon */}
                <div className="shrink-0 mt-0.5">
                  {step.done
                    ? <CheckCircle2 className="h-5 w-5 text-green-500" />
                    : <Circle className={`h-5 w-5 ${isNext ? 'text-indigo-400' : 'text-gray-300'}`} />
                  }
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <Icon className={`h-3.5 w-3.5 shrink-0 ${step.done ? 'text-green-500' : step.iconColor}`} />
                    <span className={`text-xs font-semibold truncate ${step.done ? 'text-green-700 line-through' : 'text-gray-800'}`}>
                      {step.label}
                    </span>
                    {isNext && !step.done && (
                      <span className="shrink-0 rounded-full bg-indigo-100 px-1.5 py-0.5 text-[9px] font-bold text-indigo-600 uppercase tracking-wide">
                        Next
                      </span>
                    )}
                  </div>
                  {!step.done && (
                    <p className="text-[11px] text-gray-500 mt-0.5 leading-relaxed line-clamp-2">{step.description}</p>
                  )}
                </div>

                {/* Arrow */}
                {!step.done && (
                  <ChevronRight className={`h-3.5 w-3.5 shrink-0 mt-0.5 ${isNext ? 'text-indigo-400' : 'text-gray-300'}`} />
                )}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
