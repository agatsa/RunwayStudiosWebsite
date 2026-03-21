'use client'

import { useState, useEffect, useRef } from 'react'
import {
  CheckCircle2, ArrowRight, ShoppingBag, Youtube, Building2,
  MonitorSmartphone, Sparkles, Globe, ChevronRight,
  Loader2, Search, BarChart2, Megaphone,
} from 'lucide-react'

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
  {
    id: 'd2c', icon: ShoppingBag, label: 'D2C Brand', description: 'Selling products online via ads',
    accent: 'text-blue-400', border: 'border-blue-500/60', bg: 'bg-blue-500/10',
  },
  {
    id: 'creator', icon: Youtube, label: 'YouTube Creator', description: 'Growing a channel & audience',
    accent: 'text-red-400', border: 'border-red-500/60', bg: 'bg-red-500/10',
  },
  {
    id: 'saas', icon: MonitorSmartphone, label: 'SaaS / App', description: 'Driving signups and subscriptions',
    accent: 'text-emerald-400', border: 'border-emerald-500/60', bg: 'bg-emerald-500/10',
  },
  {
    id: 'agency', icon: Building2, label: 'Agency', description: 'Managing multiple client accounts',
    accent: 'text-purple-400', border: 'border-purple-500/60', bg: 'bg-purple-500/10',
  },
]

// What ARIA can analyse — multi-select cards
interface AnalysisChannel {
  id: string
  icon: React.ElementType
  label: string
  description: string
  hasInput?: boolean
  inputLabel?: string
  inputPlaceholder?: string
  comingSoon?: boolean
}

const ANALYSIS_CHANNELS: AnalysisChannel[] = [
  {
    id: 'brand_intel',
    icon: Search,
    label: 'Brand & Competitor Intel',
    description: 'ARIA scrapes competitor websites, pulls their Meta ads, pricing, reviews & tech stack',
    hasInput: true,
    inputLabel: 'Your website / brand URL',
    inputPlaceholder: 'https://yourwebsite.com',
  },
  {
    id: 'youtube',
    icon: Youtube,
    label: 'YouTube Intelligence',
    description: '9-layer competitor analysis — topics, formats, thumbnails, upload rhythm, growth recipe',
    hasInput: true,
    inputLabel: 'Your YouTube channel URL or handle',
    inputPlaceholder: 'https://youtube.com/@yourchannel',
  },
  {
    id: 'meta',
    icon: Megaphone,
    label: 'Meta Ads',
    description: 'Facebook & Instagram campaign analytics — spend, ROAS, audience breakdowns',
    hasInput: false,
  },
  {
    id: 'google',
    icon: BarChart2,
    label: 'Google Ads',
    description: 'Google Ads + YouTube Analytics + GA4 — one OAuth click connects all',
    hasInput: false,
  },
]

const SCAN_STEPS_BY_CHANNELS: Record<string, string[]> = {
  brand_intel: ['Fetching your brand page…', 'Discovering competitors…', 'Building Brand Intel brief…'],
  youtube:     ['Scanning your channel…', 'Discovering competitor channels…', 'Building YouTube Growth Plan…'],
  default:     ['Setting up your workspace…', 'Configuring ARIA…', 'Building your first strategy…'],
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
  const [step, setStep]                   = useState<1 | 2 | 3>(1)
  const [bizType, setBizType]             = useState<WorkspaceType | null>(null)
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['brand_intel'])
  const [channelInputs, setChannelInputs] = useState<Record<string, string>>({})
  const [budget, setBudget]               = useState('')
  const [scanIdx, setScanIdx]             = useState(0)
  const [done, setDone]                   = useState(false)

  const biz = BIZ_TYPES.find(b => b.id === bizType)

  // Pre-select channels based on biz type
  useEffect(() => {
    if (!bizType) return
    if (bizType === 'creator') {
      setSelectedChannels(['youtube'])
    } else {
      setSelectedChannels(['brand_intel'])
    }
  }, [bizType])

  // Build scan steps from selected channels
  const scanSteps = (() => {
    const steps: string[] = []
    if (selectedChannels.includes('brand_intel')) steps.push(...SCAN_STEPS_BY_CHANNELS.brand_intel)
    else if (selectedChannels.includes('youtube')) steps.push(...SCAN_STEPS_BY_CHANNELS.youtube)
    else steps.push(...SCAN_STEPS_BY_CHANNELS.default)
    return [...new Set(steps)].slice(0, 4)
  })()

  // Animate scan steps
  useEffect(() => {
    if (step !== 3 || done) return
    if (scanIdx < scanSteps.length - 1) {
      const t = setTimeout(() => setScanIdx(i => i + 1), 1300)
      return () => clearTimeout(t)
    } else {
      const t = setTimeout(() => setDone(true), 900)
      return () => clearTimeout(t)
    }
  }, [step, scanIdx, done, scanSteps.length])

  useEffect(() => {
    if (done && bizType) onComplete(bizType)
  }, [done, bizType, onComplete])

  const toggleChannel = (id: string) => {
    setSelectedChannels(prev =>
      prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]
    )
  }

  const handleStartScan = async () => {
    if (!bizType) return
    setStep(3)
    setScanIdx(0)
    setDone(false)
    try {
      await fetch('/api/workspace/onboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id:        workspaceId,
          workspace_type:      bizType,
          brand_url:           channelInputs['brand_intel']?.trim() || '',
          youtube_channel_url: channelInputs['youtube']?.trim() || '',
          selected_channels:   selectedChannels,
          monthly_budget:      budget ? Number(budget) : 0,
        }),
      })
    } catch { /* non-fatal — background task */ }
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
                <h2 className="text-2xl font-bold text-white mb-1">Welcome to Runway Studios</h2>
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

          {/* ── Step 2: What should ARIA analyse ── */}
          {step === 2 && biz && (
            <>
              <div className="mb-5">
                <h2 className="text-2xl font-bold text-white mb-1">What should ARIA analyse?</h2>
                <p className="text-sm text-white/50">Select what intelligence you want ARIA to gather for you. You can always add more in Settings.</p>
              </div>

              <div className="space-y-3 mb-5">
                {ANALYSIS_CHANNELS.map(ch => {
                  const Icon  = ch.icon
                  const sel   = selectedChannels.includes(ch.id)
                  return (
                    <div key={ch.id}>
                      <button
                        onClick={() => toggleChannel(ch.id)}
                        className={`w-full flex items-start gap-3 rounded-2xl border p-4 text-left transition-all duration-200 ${
                          sel
                            ? 'border-indigo-500/50 bg-indigo-500/10 ring-1 ring-inset ring-indigo-500/30'
                            : 'border-white/10 bg-white/5 hover:bg-white/8 hover:border-white/20'
                        }`}
                      >
                        <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
                          sel ? 'bg-indigo-500/20 border border-indigo-500/40' : 'bg-white/10 border border-white/15'
                        }`}>
                          <Icon className={`h-4 w-4 ${sel ? 'text-indigo-300' : 'text-white/50'}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold text-white">{ch.label}</p>
                            {!ch.hasInput && sel && (
                              <span className="rounded-full bg-amber-500/20 border border-amber-500/30 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                                Connect in Settings
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-white/45 mt-0.5 leading-relaxed">{ch.description}</p>
                        </div>
                        <div className={`mt-1 h-4 w-4 shrink-0 rounded-full border-2 transition-all ${
                          sel ? 'border-indigo-400 bg-indigo-400' : 'border-white/25'
                        }`}>
                          {sel && <CheckCircle2 className="h-3 w-3 text-white -translate-x-px -translate-y-px" />}
                        </div>
                      </button>

                      {/* Input shown when channel is selected and has an input */}
                      {sel && ch.hasInput && (
                        <div className="mt-1.5 ml-11">
                          <div className="relative">
                            <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-white/30" />
                            <input
                              type="url"
                              value={channelInputs[ch.id] || ''}
                              onChange={e => setChannelInputs(prev => ({ ...prev, [ch.id]: e.target.value }))}
                              placeholder={ch.inputPlaceholder}
                              className="w-full rounded-xl border border-white/15 bg-white/8 pl-9 pr-4 py-2.5 text-sm text-white placeholder-white/25 focus:outline-none focus:border-indigo-500/60"
                            />
                          </div>
                          <p className="mt-1 text-[11px] text-white/30">{ch.inputLabel}</p>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Optional budget */}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-white/40 mb-1.5">
                  Monthly ad budget <span className="font-normal">(optional)</span>
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-sm text-white/35">₹</span>
                  <input
                    type="number"
                    value={budget}
                    onChange={e => setBudget(e.target.value)}
                    placeholder="50,000"
                    className="w-full rounded-xl border border-white/10 bg-white/5 pl-8 pr-4 py-2.5 text-sm text-white placeholder-white/20 focus:outline-none focus:border-indigo-500/50"
                  />
                </div>
              </div>

              <div className="flex gap-3">
                <button onClick={() => setStep(1)}
                  className="flex-1 rounded-xl border border-white/15 px-4 py-3 text-sm font-medium text-white/60 hover:bg-white/5 hover:text-white/80 transition-colors">
                  Back
                </button>
                <button onClick={handleStartScan} disabled={selectedChannels.length === 0}
                  className="flex-[2] flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all disabled:opacity-30"
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
                  {done ? 'ARIA is ready!' : 'ARIA is scanning…'}
                </h2>
                <p className="text-sm text-white/50">
                  {done
                    ? 'Your intelligence brief is building in the background.'
                    : 'Building your competitive intelligence. This takes just a moment.'}
                </p>
              </div>

              <div className="space-y-3 mb-8 text-left">
                {scanSteps.map((s, i) => (
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
