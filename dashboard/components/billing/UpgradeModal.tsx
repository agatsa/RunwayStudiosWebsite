'use client'

import { X, Zap, Crown } from 'lucide-react'
import Link from 'next/link'

interface Props {
  feature: string
  required: number
  balance: number
  wsId: string
  onClose: () => void
  onTopUp: () => void
}

const FEATURE_LABELS: Record<string, string> = {
  yt_competitor_intel: 'YouTube Competitor Intelligence',
  growth_os:          'Growth OS Command Center',
  video_ai_insights:  'Video AI Insights',
  campaign_brief:     'Campaign AI Brief',
  competitor_ai:      'Competitor Intel AI Analysis',
  growth_recipe_regen:'Growth Recipe Regeneration',
}

export default function UpgradeModal({ feature, required, balance, wsId, onClose, onTopUp }: Props) {
  const label = FEATURE_LABELS[feature] ?? feature
  const shortfall = required - balance

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-amber-500" />
            <h2 className="text-base font-bold text-gray-900">Not enough credits</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5">
          <p className="text-sm text-gray-600 mb-4">
            <strong>{label}</strong> costs <strong>{required} credits</strong>, but you only have{' '}
            <strong>{balance} credits</strong>. You need{' '}
            <span className="text-red-600 font-semibold">{shortfall} more credits</span> to continue.
          </p>

          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 mb-5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-amber-800">Current balance</span>
              <span className="font-bold text-amber-700 flex items-center gap-1">
                <Zap className="h-3.5 w-3.5" />{balance}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm mt-1">
              <span className="text-amber-800">Required</span>
              <span className="font-bold text-amber-700">{required}</span>
            </div>
            <div className="border-t border-amber-200 mt-2 pt-2 flex items-center justify-between text-sm">
              <span className="text-red-700 font-medium">Shortfall</span>
              <span className="font-bold text-red-600">{shortfall}</span>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={onTopUp}
              className="flex-[2] flex items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 transition-colors"
            >
              <Zap className="h-4 w-4" />
              Top Up Credits
            </button>
            <Link
              href={`/billing?ws=${wsId}`}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <Crown className="h-4 w-4" />
              Upgrade Plan
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
