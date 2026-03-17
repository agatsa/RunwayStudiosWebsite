'use client'

import { useState, useEffect, useRef } from 'react'
import { CheckCircle2, ArrowRight, ShoppingBag, Youtube, Building2, MonitorSmartphone, Sparkles } from 'lucide-react'

type WorkspaceType = 'd2c' | 'creator' | 'agency' | 'saas'

interface BizType {
  id: WorkspaceType
  icon: React.ElementType
  label: string
  description: string
  accent: string
  border: string
  bg: string
}

const BIZ_TYPES: BizType[] = [
  { id: 'd2c',     icon: ShoppingBag,      label: 'D2C Brand',       description: 'Selling products online via ads',          accent: 'text-blue-400',   border: 'border-blue-500/60',   bg: 'bg-blue-500/10' },
  { id: 'creator', icon: Youtube,           label: 'YouTube Creator', description: 'Growing a channel & audience',              accent: 'text-red-400',    border: 'border-red-500/60',    bg: 'bg-red-500/10' },
  { id: 'agency',  icon: Building2,         label: 'Agency',          description: 'Managing multiple client accounts',         accent: 'text-purple-400', border: 'border-purple-500/60', bg: 'bg-purple-500/10' },
  { id: 'saas',    icon: MonitorSmartphone, label: 'SaaS / App',      description: 'Driving signups and subscriptions',         accent: 'text-emerald-400',border: 'border-emerald-500/60',bg: 'bg-emerald-500/10' },
]

const CHANNELS = ['Meta Ads', 'Google Ads', 'YouTube', 'Marketplace / Amazon', 'None yet']

const FIRST_MOVES: Record<WorkspaceType, string[]> = {
  d2c:     ['Connect Meta Ads in Settings → Platform Connections', 'Upload a Google Ads report in Google Ads page', 'Run Competitor Intel to see what rivals are doing'],
  creator: ['Connect YouTube in Settings → Platform Connections', 'Run YouTube Competitor Discovery', 'Check Growth OS Command Center for your action plan'],
  agency:  ['Connect all client channels in Settings', 'Explore Growth OS Command Center', 'Upload performance reports for each client'],
  saas:    ['Connect Meta Ads in Settings → Platform Connections', 'Connect Google Ads for keyword tracking', 'Check Search Trends for high-intent terms'],
}

// ── Starfield canvas ─────────────────────────────────────────────────────────
function StarCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const W = canvas.width  = canvas.offsetWidth
    const H = canvas.height = canvas.offsetHeight

    type Star = { x: number; y: number; r: number; speed: number; opacity: number; twinkle: number; phase: number }
    const stars: Star[] = Array.from({ length: 160 }, () => ({
      x:       Math.random() * W,
      y:       Math.random() * H,
      r:       Math.random() * 1.8 + 0.3,
      speed:   Math.random() * 0.25 + 0.05,
      opacity: Math.random() * 0.6 + 0.3,
      twinkle: Math.random() * 0.015 + 0.005,
      phase:   Math.random() * Math.PI * 2,
    }))

    // A few bigger "bright" stars
    const bright: Star[] = Array.from({ length: 12 }, () => ({
      x:       Math.random() * W,
      y:       Math.random() * H,
      r:       Math.random() * 2.5 + 1.5,
      speed:   Math.random() * 0.15 + 0.02,
      opacity: 0.9,
      twinkle: Math.random() * 0.03 + 0.01,
      phase:   Math.random() * Math.PI * 2,
    }))

    let frame = 0
    let raf: number

    const draw = () => {
      ctx.clearRect(0, 0, W, H)
      frame++

      const allStars = [...stars, ...bright]
      for (const s of allStars) {
        // Move upward (reaching for stars)
        s.y -= s.speed
        if (s.y < -4) { s.y = H + 4; s.x = Math.random() * W }

        // Twinkle
        const alpha = s.opacity * (0.6 + 0.4 * Math.sin(frame * s.twinkle + s.phase))

        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255,255,255,${alpha})`
        ctx.fill()

        // Glow on bigger stars
        if (s.r > 1.5) {
          const grd = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 5)
          grd.addColorStop(0, `rgba(180,200,255,${alpha * 0.4})`)
          grd.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.r * 5, 0, Math.PI * 2)
          ctx.fillStyle = grd
          ctx.fill()
        }
      }
      raf = requestAnimationFrame(draw)
    }

    draw()
    return () => cancelAnimationFrame(raf)
  }, [])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
}

interface Props {
  workspaceId: string
  onComplete: (bizType: WorkspaceType) => void
}

export default function OnboardingModal({ workspaceId, onComplete }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [bizType, setBizType] = useState<WorkspaceType | null>(null)
  const [channels, setChannels] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const toggleChannel = (ch: string) => {
    setChannels(prev => prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch])
  }

  const handleFinish = async () => {
    if (!bizType) return
    setSaving(true)
    try {
      await fetch('/api/workspace/complete-onboarding', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, workspace_type: bizType, onboarding_channels: channels }),
      })
    } catch { /* non-fatal */ }
    onComplete(bizType!)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,5,0.88)' }}>

      {/* Starfield — fills the whole backdrop */}
      <div className="absolute inset-0 overflow-hidden">
        <StarCanvas />
      </div>

      {/* Modal card */}
      <div className="relative w-full max-w-2xl rounded-3xl overflow-hidden shadow-2xl"
           style={{ background: 'linear-gradient(145deg, #0f1729 0%, #111827 60%, #0a0f1e 100%)', border: '1px solid rgba(255,255,255,0.08)' }}>

        {/* Soft glow behind card */}
        <div className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-48 w-96 rounded-full opacity-30"
             style={{ background: 'radial-gradient(ellipse, #6366f1 0%, transparent 70%)' }} />

        {/* Progress bar */}
        <div className="h-0.5 bg-white/10">
          <div className="h-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-700"
               style={{ width: `${(step / 3) * 100}%` }} />
        </div>

        <div className="px-8 py-8">
          {/* Step pill */}
          <div className="flex items-center justify-between mb-6">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/60">
              <Sparkles className="h-3 w-3 text-amber-400" />
              Step {step} of 3
            </span>
            <div className="flex gap-1.5">
              {[1,2,3].map(n => (
                <div key={n} className={`h-1.5 w-6 rounded-full transition-all duration-500 ${n <= step ? 'bg-indigo-400' : 'bg-white/15'}`} />
              ))}
            </div>
          </div>

          {/* ── Step 1: Business type ── */}
          {step === 1 && (
            <>
              <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-1">Welcome to Runway Studios 🚀</h2>
                <p className="text-sm text-white/50">What best describes you? We'll personalise your entire dashboard.</p>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-6">
                {BIZ_TYPES.map(bt => {
                  const Icon = bt.icon
                  const selected = bizType === bt.id
                  return (
                    <button
                      key={bt.id}
                      onClick={() => setBizType(bt.id)}
                      className={`relative flex flex-col items-start gap-3 rounded-2xl border p-5 text-left transition-all duration-200 ${
                        selected
                          ? `${bt.border} ${bt.bg} ring-1 ring-inset ${bt.border}`
                          : 'border-white/10 bg-white/5 hover:bg-white/8 hover:border-white/20'
                      }`}
                    >
                      {selected && (
                        <CheckCircle2 className={`absolute top-4 right-4 h-4 w-4 ${bt.accent}`} />
                      )}
                      <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${bt.bg} ${bt.border} border`}>
                        <Icon className={`h-5 w-5 ${bt.accent}`} />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-white">{bt.label}</p>
                        <p className="text-xs text-white/45 leading-tight mt-0.5">{bt.description}</p>
                      </div>
                    </button>
                  )
                })}
              </div>
              <button
                onClick={() => setStep(2)}
                disabled={!bizType}
                className="w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
              >
                Continue <ArrowRight className="h-4 w-4" />
              </button>
            </>
          )}

          {/* ── Step 2: Channels ── */}
          {step === 2 && (
            <>
              <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-1">Which channels are you using?</h2>
                <p className="text-sm text-white/50">Select all that apply — we'll highlight the right tools for you.</p>
              </div>
              <div className="flex flex-wrap gap-2 mb-6">
                {CHANNELS.map(ch => {
                  const on = channels.includes(ch)
                  return (
                    <button
                      key={ch}
                      onClick={() => toggleChannel(ch)}
                      className={`rounded-full border px-4 py-2 text-sm font-medium transition-all ${
                        on
                          ? 'border-indigo-500/70 bg-indigo-500/20 text-indigo-300'
                          : 'border-white/15 bg-white/5 text-white/60 hover:border-white/30 hover:text-white/80'
                      }`}
                    >
                      {on && <span className="mr-1.5">✓</span>}
                      {ch}
                    </button>
                  )
                })}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(1)}
                  className="flex-1 rounded-xl border border-white/15 px-4 py-3 text-sm font-medium text-white/60 hover:bg-white/5 hover:text-white/80 transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                >
                  Continue <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </>
          )}

          {/* ── Step 3: First moves ── */}
          {step === 3 && bizType && (
            <>
              <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-1">You're all set! 🌟</h2>
                <p className="text-sm text-white/50">Here's your personalised starting point:</p>
              </div>
              <div className="space-y-2.5 mb-6">
                {FIRST_MOVES[bizType].map((move, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl border border-white/8 bg-white/5 px-4 py-3.5">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                         style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                      {i + 1}
                    </div>
                    <p className="text-sm text-white/75 leading-relaxed">{move}</p>
                  </div>
                ))}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(2)}
                  className="flex-1 rounded-xl border border-white/15 px-4 py-3 text-sm font-medium text-white/60 hover:bg-white/5 hover:text-white/80 transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={handleFinish}
                  disabled={saving}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all disabled:opacity-60"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                >
                  {saving ? 'Saving…' : "Let's blast off 🚀"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
