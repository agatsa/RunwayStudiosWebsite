'use client'

import { useState, useEffect, useRef } from 'react'
import {
  CheckCircle2, ArrowRight, ShoppingBag, Youtube, Building2,
  MonitorSmartphone, Sparkles, Search, Globe, ChevronRight,
  Loader2, Users,
} from 'lucide-react'

type WorkspaceType = 'd2c' | 'creator' | 'agency' | 'saas'

interface BizType {
  id: WorkspaceType
  icon: React.ElementType
  label: string
  description: string
  urlLabel: string
  urlPlaceholder: string
  accent: string
  border: string
  bg: string
}

const BIZ_TYPES: BizType[] = [
  {
    id: 'd2c', icon: ShoppingBag, label: 'D2C Brand', description: 'Selling products online via ads',
    urlLabel: 'Your store URL', urlPlaceholder: 'https://yourstore.com',
    accent: 'text-blue-400', border: 'border-blue-500/60', bg: 'bg-blue-500/10',
  },
  {
    id: 'creator', icon: Youtube, label: 'YouTube Creator', description: 'Growing a channel & audience',
    urlLabel: 'Your YouTube channel URL', urlPlaceholder: 'https://youtube.com/@yourchannel',
    accent: 'text-red-400', border: 'border-red-500/60', bg: 'bg-red-500/10',
  },
  {
    id: 'saas', icon: MonitorSmartphone, label: 'SaaS / App', description: 'Driving signups and subscriptions',
    urlLabel: 'Your app or website URL', urlPlaceholder: 'https://yourapp.com',
    accent: 'text-emerald-400', border: 'border-emerald-500/60', bg: 'bg-emerald-500/10',
  },
  {
    id: 'agency', icon: Building2, label: 'Agency', description: 'Managing multiple client accounts',
    urlLabel: 'Your agency website', urlPlaceholder: 'https://youragency.com',
    accent: 'text-purple-400', border: 'border-purple-500/60', bg: 'bg-purple-500/10',
  },
]

const SCAN_STEPS: Record<WorkspaceType, string[]> = {
  d2c:     ['Fetching your product catalog…', 'Scanning competitor brands…', 'Building your Growth OS brief…'],
  creator: ['Analysing your channel…', 'Discovering competitor channels…', 'Preparing Growth Plan…'],
  saas:    ['Analysing your app listing…', 'Finding competitor apps…', 'Building your first strategy…'],
  agency:  ['Setting up your workspace…', 'Configuring multi-brand tools…', 'Ready to manage clients…'],
}

// ── Starfield canvas ─────────────────────────────────────────────────────────
function StarCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const W = canvas.width = canvas.offsetWidth
    const H = canvas.height = canvas.offsetHeight
    type Star = { x: number; y: number; r: number; speed: number; opacity: number; twinkle: number; phase: number }
    const allStars: Star[] = Array.from({ length: 180 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      r: Math.random() * 2 + 0.3, speed: Math.random() * 0.25 + 0.05,
      opacity: Math.random() * 0.6 + 0.3, twinkle: Math.random() * 0.015 + 0.005,
      phase: Math.random() * Math.PI * 2,
    }))
    let frame = 0; let raf: number
    const draw = () => {
      ctx.clearRect(0, 0, W, H); frame++
      for (const s of allStars) {
        s.y -= s.speed
        if (s.y < -4) { s.y = H + 4; s.x = Math.random() * W }
        const alpha = s.opacity * (0.6 + 0.4 * Math.sin(frame * s.twinkle + s.phase))
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255,255,255,${alpha})`; ctx.fill()
        if (s.r > 1.5) {
          const grd = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 5)
          grd.addColorStop(0, `rgba(180,200,255,${alpha * 0.4})`); grd.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.beginPath(); ctx.arc(s.x, s.y, s.r * 5, 0, Math.PI * 2)
          ctx.fillStyle = grd; ctx.fill()
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
  onComplete: (bizType?: WorkspaceType) => void
}

export default function OnboardingModal({ workspaceId, onComplete }: Props) {
  const [step, setStep]               = useState<1 | 2 | 3>(1)
  const [bizType, setBizType]         = useState<WorkspaceType | null>(null)
  const [brandUrl, setBrandUrl]       = useState('')
  const [competitors, setCompetitors] = useState(['', '', ''])
  const [budget, setBudget]           = useState('')
  const [scanning, setScanning]       = useState(false)
  const [scanIdx, setScanIdx]         = useState(0)
  const [done, setDone]               = useState(false)

  const biz = BIZ_TYPES.find(b => b.id === bizType)

  // Animate scan steps
  useEffect(() => {
    if (step !== 3 || done) return
    const steps = SCAN_STEPS[bizType!] ?? []
    if (scanIdx < steps.length - 1) {
      const t = setTimeout(() => setScanIdx(i => i + 1), 1200)
      return () => clearTimeout(t)
    } else {
      // All steps shown — finish
      const t = setTimeout(() => { setDone(true) }, 900)
      return () => clearTimeout(t)
    }
  }, [step, scanIdx, done, bizType])

  // Once done, call onComplete
  useEffect(() => {
    if (done && bizType) onComplete(bizType)
  }, [done, bizType, onComplete])

  const handleStartScan = async () => {
    if (!bizType) return
    setScanning(true)
    setStep(3)
    setScanIdx(0)
    setDone(false)
    try {
      await fetch('/api/workspace/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          workspace_type: bizType,
          brand_url: brandUrl.trim(),
          competitors: competitors.filter(c => c.trim()),
          monthly_budget: budget ? Number(budget) : 0,
        }),
      })
    } catch { /* non-fatal — background task */ }
    setScanning(false)
  }

  const updateCompetitor = (i: number, val: string) => {
    setCompetitors(prev => { const next = [...prev]; next[i] = val; return next })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,5,0.88)' }}>
      <div className="absolute inset-0 overflow-hidden"><StarCanvas /></div>

      <div className="relative w-full max-w-2xl rounded-3xl overflow-hidden shadow-2xl"
           style={{ background: 'linear-gradient(145deg, #0f1729 0%, #111827 60%, #0a0f1e 100%)', border: '1px solid rgba(255,255,255,0.08)' }}>

        <div className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-48 w-96 rounded-full opacity-30"
             style={{ background: 'radial-gradient(ellipse, #6366f1 0%, transparent 70%)' }} />

        {/* Progress bar */}
        <div className="h-0.5 bg-white/10">
          <div className="h-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-700"
               style={{ width: step === 3 ? '100%' : `${((step - 1) / 2) * 100}%` }} />
        </div>

        <div className="px-8 py-8">
          {/* Step pill */}
          {step < 3 && (
            <div className="flex items-center justify-between mb-6">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/60">
                <Sparkles className="h-3 w-3 text-amber-400" />
                Step {step} of 2
              </span>
              <div className="flex gap-1.5">
                {[1, 2].map(n => (
                  <div key={n} className={`h-1.5 w-8 rounded-full transition-all duration-500 ${n <= step ? 'bg-indigo-400' : 'bg-white/15'}`} />
                ))}
              </div>
            </div>
          )}

          {/* ── Step 1: Business type ── */}
          {step === 1 && (
            <>
              <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-1">Welcome to Runway Studios 🚀</h2>
                <p className="text-sm text-white/50">What best describes you? ARIA will personalise your entire dashboard.</p>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-6">
                {BIZ_TYPES.map(bt => {
                  const Icon = bt.icon
                  const selected = bizType === bt.id
                  return (
                    <button key={bt.id} onClick={() => setBizType(bt.id)}
                      className={`relative flex flex-col items-start gap-3 rounded-2xl border p-5 text-left transition-all duration-200 ${
                        selected ? `${bt.border} ${bt.bg} ring-1 ring-inset ${bt.border}` : 'border-white/10 bg-white/5 hover:bg-white/8 hover:border-white/20'
                      }`}>
                      {selected && <CheckCircle2 className={`absolute top-4 right-4 h-4 w-4 ${bt.accent}`} />}
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
              <button onClick={() => setStep(2)} disabled={!bizType}
                className="w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                Continue <ArrowRight className="h-4 w-4" />
              </button>
            </>
          )}

          {/* ── Step 2: Brand context ── */}
          {step === 2 && biz && (
            <>
              <div className="mb-5">
                <h2 className="text-2xl font-bold text-white mb-1">Tell ARIA about your brand</h2>
                <p className="text-sm text-white/50">The more context you give, the smarter your first strategy will be.</p>
              </div>

              <div className="space-y-4 mb-5">
                {/* Brand URL */}
                <div>
                  <label className="block text-xs font-semibold text-white/60 mb-1.5 flex items-center gap-1.5">
                    <Globe className="h-3.5 w-3.5" /> {biz.urlLabel}
                  </label>
                  <input
                    type="url"
                    value={brandUrl}
                    onChange={e => setBrandUrl(e.target.value)}
                    placeholder={biz.urlPlaceholder}
                    className="w-full rounded-xl border border-white/15 bg-white/8 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-indigo-500/60 focus:bg-white/10"
                  />
                </div>

                {/* Competitors */}
                <div>
                  <label className="block text-xs font-semibold text-white/60 mb-1 flex items-center gap-1.5">
                    <Users className="h-3.5 w-3.5" /> Competitors
                    <span className="text-white/30 font-normal">(optional — ARIA will auto-find if blank)</span>
                  </label>
                  <div className="space-y-2">
                    {competitors.map((c, i) => (
                      <input
                        key={i}
                        type="text"
                        value={c}
                        onChange={e => updateCompetitor(i, e.target.value)}
                        placeholder={`Competitor ${i + 1} — URL or brand name`}
                        className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/25 focus:outline-none focus:border-indigo-500/50 focus:bg-white/8"
                      />
                    ))}
                  </div>
                  <p className="mt-1.5 text-[11px] text-white/30 flex items-center gap-1">
                    <Search className="h-3 w-3" /> Left blank? ARIA will automatically discover your top competitors.
                  </p>
                </div>

                {/* Budget */}
                <div>
                  <label className="block text-xs font-semibold text-white/60 mb-1.5">
                    Monthly ad budget <span className="text-white/30 font-normal">(optional)</span>
                  </label>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-sm text-white/40">₹</span>
                    <input
                      type="number"
                      value={budget}
                      onChange={e => setBudget(e.target.value)}
                      placeholder="50,000"
                      className="w-full rounded-xl border border-white/10 bg-white/5 pl-8 pr-4 py-2.5 text-sm text-white placeholder-white/25 focus:outline-none focus:border-indigo-500/50 focus:bg-white/8"
                    />
                  </div>
                </div>
              </div>

              <div className="flex gap-3">
                <button onClick={() => setStep(1)}
                  className="flex-1 rounded-xl border border-white/15 px-4 py-3 text-sm font-medium text-white/60 hover:bg-white/5 hover:text-white/80 transition-colors">
                  Back
                </button>
                <button onClick={handleStartScan}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                  Launch ARIA <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </>
          )}

          {/* ── Step 3: Scanning ── */}
          {step === 3 && bizType && (
            <div className="py-6 text-center">
              <div className="mb-8">
                <div className="flex h-16 w-16 items-center justify-center rounded-2xl mx-auto mb-4"
                     style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                  {done
                    ? <CheckCircle2 className="h-8 w-8 text-white" />
                    : <Sparkles className="h-8 w-8 text-white animate-pulse" />}
                </div>
                <h2 className="text-2xl font-bold text-white mb-1">
                  {done ? 'ARIA is ready! 🚀' : 'ARIA is scanning…'}
                </h2>
                <p className="text-sm text-white/50">
                  {done
                    ? 'Your intelligence brief is building in the background.'
                    : 'Building your competitive intelligence. This takes just a moment.'}
                </p>
              </div>

              <div className="space-y-3 mb-8 text-left">
                {(SCAN_STEPS[bizType] ?? []).map((s, i) => (
                  <div key={i} className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition-all duration-500 ${
                    i < scanIdx ? 'border-green-500/30 bg-green-500/10' :
                    i === scanIdx ? 'border-indigo-500/40 bg-indigo-500/10' :
                    'border-white/8 bg-white/3 opacity-40'
                  }`}>
                    {i < scanIdx
                      ? <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0" />
                      : i === scanIdx
                      ? <Loader2 className="h-4 w-4 text-indigo-400 animate-spin shrink-0" />
                      : <div className="h-4 w-4 rounded-full border border-white/20 shrink-0" />}
                    <span className={`text-sm ${i <= scanIdx ? 'text-white/80' : 'text-white/30'}`}>{s}</span>
                  </div>
                ))}
              </div>

              {done && (
                <button onClick={() => onComplete(bizType)}
                  className="w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                  Enter Dashboard <ArrowRight className="h-4 w-4" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
