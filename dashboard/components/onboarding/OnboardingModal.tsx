'use client'

import { useState } from 'react'
import { CheckCircle2, ArrowRight, ShoppingBag, Youtube, Building2, MonitorSmartphone } from 'lucide-react'

type WorkspaceType = 'd2c' | 'creator' | 'agency' | 'saas'

interface BizType {
  id: WorkspaceType
  icon: React.ElementType
  label: string
  description: string
  color: string
}

const BIZ_TYPES: BizType[] = [
  { id: 'd2c',     icon: ShoppingBag,       label: 'D2C Brand',        description: 'Selling products online via ads',          color: 'text-blue-600 bg-blue-50 border-blue-200' },
  { id: 'creator', icon: Youtube,            label: 'YouTube Creator',  description: 'Growing a channel & audience',              color: 'text-red-600 bg-red-50 border-red-200' },
  { id: 'agency',  icon: Building2,          label: 'Agency',           description: 'Managing multiple client accounts',         color: 'text-purple-600 bg-purple-50 border-purple-200' },
  { id: 'saas',    icon: MonitorSmartphone,  label: 'SaaS / App',       description: 'Driving signups and subscriptions',         color: 'text-green-600 bg-green-50 border-green-200' },
]

const CHANNELS = ['Meta Ads', 'Google Ads', 'YouTube', 'Marketplace / Amazon', 'None yet']

const FIRST_MOVES: Record<WorkspaceType, string[]> = {
  d2c:     ['Connect Meta Ads in Settings → Platform Connections', 'Upload a Google Ads report in Google Ads page', 'Run Competitor Intel to see what rivals are doing'],
  creator: ['Connect YouTube in Settings → Platform Connections', 'Run YouTube Competitor Discovery', 'Check Growth OS Command Center for your action plan'],
  agency:  ['Connect all client channels in Settings', 'Explore Growth OS Command Center', 'Upload performance reports for each client'],
  saas:    ['Connect Meta Ads in Settings → Platform Connections', 'Connect Google Ads for keyword tracking', 'Check Search Trends for high-intent terms'],
}

interface Props {
  workspaceId: string
  onComplete: () => void
}

export default function OnboardingModal({ workspaceId, onComplete }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [bizType, setBizType] = useState<WorkspaceType | null>(null)
  const [channels, setChannels] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const toggleChannel = (ch: string) => {
    setChannels(prev =>
      prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch]
    )
  }

  const handleFinish = async () => {
    if (!bizType) return
    setSaving(true)
    try {
      await fetch('/api/workspace/complete-onboarding', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          workspace_type: bizType,
          onboarding_channels: channels,
        }),
      })
    } catch { /* non-fatal */ }
    onComplete()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl overflow-hidden">

        {/* Progress bar */}
        <div className="h-1 bg-gray-100">
          <div
            className="h-1 bg-blue-600 transition-all duration-500"
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        <div className="p-6">
          {/* Step indicator */}
          <p className="text-xs font-medium text-gray-400 mb-1">Step {step} of 3</p>

          {/* ── Step 1: Business type ── */}
          {step === 1 && (
            <>
              <h2 className="text-xl font-bold text-gray-900 mb-1">Welcome to Runway Studios</h2>
              <p className="text-sm text-gray-500 mb-5">What best describes you? We'll personalise your dashboard.</p>
              <div className="grid grid-cols-2 gap-3">
                {BIZ_TYPES.map(bt => {
                  const Icon = bt.icon
                  const selected = bizType === bt.id
                  return (
                    <button
                      key={bt.id}
                      onClick={() => setBizType(bt.id)}
                      className={`relative flex flex-col items-start gap-2 rounded-xl border-2 p-4 text-left transition-all ${
                        selected
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      {selected && (
                        <CheckCircle2 className="absolute top-3 right-3 h-4 w-4 text-blue-500" />
                      )}
                      <div className={`flex h-9 w-9 items-center justify-center rounded-lg border ${bt.color}`}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-gray-900">{bt.label}</p>
                        <p className="text-xs text-gray-500 leading-tight mt-0.5">{bt.description}</p>
                      </div>
                    </button>
                  )
                })}
              </div>
              <button
                onClick={() => setStep(2)}
                disabled={!bizType}
                className="mt-5 w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue <ArrowRight className="h-4 w-4" />
              </button>
            </>
          )}

          {/* ── Step 2: Channels ── */}
          {step === 2 && (
            <>
              <h2 className="text-xl font-bold text-gray-900 mb-1">Which channels are you using?</h2>
              <p className="text-sm text-gray-500 mb-5">Select all that apply — we'll highlight the right tools for you.</p>
              <div className="flex flex-wrap gap-2">
                {CHANNELS.map(ch => {
                  const on = channels.includes(ch)
                  return (
                    <button
                      key={ch}
                      onClick={() => toggleChannel(ch)}
                      className={`rounded-full border px-4 py-2 text-sm font-medium transition-all ${
                        on
                          ? 'border-blue-500 bg-blue-50 text-blue-700'
                          : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                      }`}
                    >
                      {on && <span className="mr-1">✓</span>}
                      {ch}
                    </button>
                  )
                })}
              </div>
              <div className="mt-5 flex gap-3">
                <button
                  onClick={() => setStep(1)}
                  className="flex-1 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
                >
                  Continue <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </>
          )}

          {/* ── Step 3: First moves ── */}
          {step === 3 && bizType && (
            <>
              <h2 className="text-xl font-bold text-gray-900 mb-1">You're all set!</h2>
              <p className="text-sm text-gray-500 mb-5">Here's your personalised starting point:</p>
              <div className="space-y-3">
                {FIRST_MOVES[bizType].map((move, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl bg-gray-50 px-4 py-3">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                      {i + 1}
                    </div>
                    <p className="text-sm text-gray-700">{move}</p>
                  </div>
                ))}
              </div>
              <div className="mt-5 flex gap-3">
                <button
                  onClick={() => setStep(2)}
                  className="flex-1 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={handleFinish}
                  disabled={saving}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors"
                >
                  {saving ? 'Saving…' : "Let's go!"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
