'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Crown, X, Zap, CheckCircle2 } from 'lucide-react'

interface Props {
  workspaceId: string
}

export default function SubscriptionUpsellBanner({ workspaceId }: Props) {
  const [visible, setVisible] = useState(false)
  const [plan, setPlan] = useState<string>('free')
  const dismissKey = `runway_upsell_dismissed_${workspaceId}`

  useEffect(() => {
    if (!workspaceId) return
    // Don't show if user already dismissed
    if (typeof window !== 'undefined' && localStorage.getItem(dismissKey)) return

    fetch(`/api/billing/status?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(d => {
        const p = d.plan ?? 'free'
        setPlan(p)
        if (p === 'free') setVisible(true)
      })
      .catch(() => {})
  }, [workspaceId, dismissKey])

  const dismiss = () => {
    setVisible(false)
    if (typeof window !== 'undefined') localStorage.setItem(dismissKey, '1')
  }

  if (!visible) return null

  const features = [
    '500 credits/month included',
    'Connect Meta + Google + GA4',
    'Unlimited Growth OS strategies',
    'Priority AI response time',
  ]

  return (
    <div className="rounded-xl border border-purple-200 bg-gradient-to-r from-purple-50 to-indigo-50 p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600">
          <Crown className="h-4.5 w-4.5 text-white" style={{ height: '18px', width: '18px' }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-semibold text-gray-900">
              You're on the Free plan
            </p>
            <span className="rounded-full bg-purple-100 border border-purple-200 px-2 py-0.5 text-xs font-medium text-purple-700">
              Upgrade for more
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Upgrade to Starter to unlock ad account connections, ongoing AI monitoring, and 500 credits/month.
          </p>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            {features.map(f => (
              <li key={f} className="flex items-center gap-1.5 text-xs text-gray-600">
                <CheckCircle2 className="h-3.5 w-3.5 text-purple-500 shrink-0" />
                {f}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            href={`/billing?ws=${workspaceId}`}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:opacity-90 transition-opacity"
          >
            <Zap className="h-3.5 w-3.5" />
            View Plans
          </Link>
          <button
            onClick={dismiss}
            className="p-1.5 rounded-lg hover:bg-purple-100 text-gray-400 hover:text-gray-600 transition-colors"
            title="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
