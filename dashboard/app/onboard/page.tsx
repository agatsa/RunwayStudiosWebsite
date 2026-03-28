'use client'

import { useState, useEffect, useRef, useCallback, Suspense } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { useUser, SignIn } from '@clerk/nextjs'
import {
  Search, Zap, CheckCircle, ArrowRight, Youtube, Globe,
  ChevronRight, Loader2, Lock, Star, Users, TrendingUp,
  CreditCard, Shield, AlertCircle,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

type Stage =
  | 'input'         // entering URL
  | 'signin'        // clerk sign-in
  | 'previewing'    // free preview running
  | 'preview_ready' // preview done, show results + pay CTA
  | 'paying'        // razorpay modal open
  | 'chain_running' // paid, full analysis running
  | 'complete'      // done → go to dashboard
  | 'failed'

interface LogEntry {
  ts: string
  msg: string
  type: string
  source: string
}

interface PreviewData {
  url_type: string
  // website
  competitors?: Array<{ name?: string; domain?: string; confidence_pct?: number }>
  own_keywords?: string[]
  bi_job_id?: string
  error?: string
  // youtube
  channel_id?: string
  title?: string
  description?: string
  subscribers?: number
  views?: number
  video_count?: number
  thumbnail?: string
  top_videos?: Array<{ title: string; video_id: string }>
}

interface JobState {
  job_id: string
  status: string
  logs: LogEntry[]
  preview_data: PreviewData | null
  url: string
  url_type: string
  bi_job_id: string | null
  yt_job_id: string | null
  gos_job_id: string | null
  paid: boolean
}

// ── Razorpay window type (extend if not already declared) ─────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RazorpayConstructor = new (options: Record<string, unknown>) => { open(): void }

// ── Terminal Component ─────────────────────────────────────────────────────────

function Terminal({ logs }: { logs: LogEntry[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs.length])

  const color = (type: string) => {
    if (type === 'success') return 'text-green-400'
    if (type === 'error') return 'text-red-400'
    if (type === 'missing') return 'text-yellow-400'
    if (type === 'phase' || type === 'header') return 'text-cyan-300 font-semibold'
    if (type === 'separator' || type === 'divider') return 'text-gray-600'
    return 'text-gray-300'
  }

  return (
    <div className="bg-gray-950 rounded-xl border border-gray-800 p-4 font-mono text-xs leading-relaxed max-h-64 overflow-y-auto">
      {logs.length === 0 ? (
        <span className="text-gray-600">Initialising ARIA…</span>
      ) : (
        logs.map((l, i) => (
          <div key={i} className={color(l.type)}>
            {l.msg}
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  )
}

// ── Extended competitor type (includes topic_space from backend) ──────────────
interface CompetitorCandidate {
  name?: string
  domain?: string
  confidence_pct?: number
  reason?: string
  topic_space?: string[]
  hit_count?: number
}

// ── Preview Results Component ─────────────────────────────────────────────────

function PreviewResults({ data }: { data: PreviewData & { competitors?: CompetitorCandidate[] } }) {
  if (data.url_type === 'youtube') {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-4 p-4 bg-red-950/30 border border-red-800/40 rounded-xl">
          {data.thumbnail && (
            <img src={data.thumbnail} alt={data.title} className="w-16 h-16 rounded-lg object-cover" />
          )}
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Youtube className="h-4 w-4 text-red-400" />
              <span className="font-semibold text-white">{data.title || 'Channel Detected'}</span>
            </div>
            <div className="flex gap-4 text-xs text-gray-400">
              <span>{(data.subscribers || 0).toLocaleString()} subscribers</span>
              <span>{(data.views || 0).toLocaleString()} views</span>
              <span>{data.video_count || 0} videos</span>
            </div>
            {data.description && (
              <p className="text-xs text-gray-500 mt-2 line-clamp-2">{data.description}</p>
            )}
          </div>
        </div>
        {data.top_videos && data.top_videos.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-400 mb-2">TOP VIDEOS DETECTED</p>
            {data.top_videos.slice(0, 3).map((v, i) => (
              <div key={i} className="flex items-center gap-2 py-1.5 border-b border-gray-800 last:border-0">
                <TrendingUp className="h-3 w-3 text-red-400 shrink-0" />
                <span className="text-sm text-gray-300 line-clamp-1">{v.title}</span>
              </div>
            ))}
          </div>
        )}

        {/* What you unlock — YouTube */}
        <div className="p-4 bg-gray-900 border border-gray-700 rounded-xl space-y-3">
          <p className="text-xs font-bold text-white uppercase tracking-wide">After payment, ARIA will:</p>
          {[
            { icon: '🔍', title: 'Find your 5 closest YouTube competitors', detail: 'Channels making similar content — by topic, format, and audience size' },
            { icon: '📊', title: 'Show you exactly what\'s working for them', detail: 'Which video styles get the most views, which titles hook people, what thumbnails they use' },
            { icon: '⚡', title: 'Write your 15-day sprint plan', detail: 'Specific video ideas with hooks, titles, and thumbnail direction — ready to shoot' },
            { icon: '🗺️', title: 'Build your 30-day growth roadmap', detail: 'A step-by-step plan to grow subscribers, increase watch time, and beat the algorithm' },
          ].map(({ icon, title, detail }) => (
            <div key={title} className="flex items-start gap-3">
              <span className="text-base shrink-0">{icon}</span>
              <div>
                <p className="text-sm font-medium text-white">{title}</p>
                <p className="text-xs text-gray-400 mt-0.5">{detail}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // website
  const competitors = (data.competitors || []) as CompetitorCandidate[]
  return (
    <div className="space-y-4">
      {competitors.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">
            Direct competitors ARIA found
          </p>
          {competitors.slice(0, 5).map((c, i) => {
            const domain = c.domain || ''
            const faviconUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=32` : null
            const sharedKw = (c.topic_space || []).slice(0, 3)
            const strength = (c.confidence_pct || 0) >= 80 ? 'Strong match' : (c.confidence_pct || 0) >= 60 ? 'Good match' : 'Possible match'
            const strengthColor = (c.confidence_pct || 0) >= 80 ? 'text-red-400' : (c.confidence_pct || 0) >= 60 ? 'text-amber-400' : 'text-gray-400'
            return (
              <div key={i} className="p-3 bg-gray-800/50 border border-gray-700/50 rounded-xl mb-2 last:mb-0">
                <div className="flex items-center gap-2.5 mb-1.5">
                  {faviconUrl && (
                    <img src={faviconUrl} alt="" className="w-4 h-4 rounded shrink-0" onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                  )}
                  <span className="font-semibold text-sm text-white">{c.name || domain}</span>
                  <span className={`ml-auto text-xs font-medium ${strengthColor}`}>{strength}</span>
                </div>
                {c.reason && (
                  <p className="text-xs text-gray-400 mb-1.5 leading-relaxed">{c.reason}</p>
                )}
                {sharedKw.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    <span className="text-xs text-gray-600 mr-0.5">Competes on:</span>
                    {sharedKw.map((kw, j) => (
                      <span key={j} className="px-1.5 py-0.5 bg-brand-900/40 border border-brand-800/40 rounded text-xs text-brand-400">
                        {kw}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {data.own_keywords && data.own_keywords.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">
            What your brand is known for
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.own_keywords.slice(0, 10).map((kw, i) => (
              <span key={i} className="px-2 py-0.5 bg-brand-900/40 border border-brand-700/40 rounded-full text-xs text-brand-300">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* What you unlock — website */}
      <div className="p-4 bg-gray-900 border border-gray-700 rounded-xl space-y-3">
        <p className="text-xs font-bold text-white uppercase tracking-wide">After payment, ARIA will:</p>
        {[
          { icon: '🔬', title: 'Study each competitor in detail', detail: 'What ads they\'re running, what messaging is working, what their customers love and hate — all in one report' },
          { icon: '🚪', title: 'Tell you why people are leaving your site without buying', detail: 'ARIA checks your website like a real buyer would — load speed, pricing, trust signals, buttons, and more — then gives you a fix for each problem' },
          { icon: '📋', title: 'Write your 90-day step-by-step growth plan', detail: 'Exactly which ads to run, which pages to fix, which offers to test — in order of what will make the most money first' },
          { icon: '💡', title: 'Find the gaps your competitors are missing', detail: 'The audience they\'re ignoring, the messages they haven\'t tried, the products they haven\'t built — yours to capture' },
        ].map(({ icon, title, detail }) => (
          <div key={title} className="flex items-start gap-3">
            <span className="text-base shrink-0">{icon}</span>
            <div>
              <p className="text-sm font-medium text-white">{title}</p>
              <p className="text-xs text-gray-400 mt-0.5">{detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Chain Progress Component ───────────────────────────────────────────────────

function ChainProgress({ job, gosJobId }: { job: JobState; gosJobId: string | null }) {
  const steps = job.url_type === 'youtube'
    ? ['YT Competitor Discovery', 'Deep Analysis', 'Growth Recipe']
    : ['Brand Intel Phase 2', 'Reddit VoC', 'LP Audit', 'Growth OS Strategy']

  const done = job.status === 'complete'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-400">Analysis chain</span>
        {done
          ? <span className="text-xs font-medium text-green-400 flex items-center gap-1"><CheckCircle className="h-3.5 w-3.5" /> Complete</span>
          : <span className="text-xs font-medium text-amber-400 flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Running…</span>
        }
      </div>
      <div className="flex items-center gap-2">
        {steps.map((s, i) => {
          const logHint = s.toLowerCase().split(' ')[0]
          const isDone = done || job.logs.some(l => l.type === 'success' && l.msg.toLowerCase().includes(logHint))
          return (
            <div key={i} className="flex items-center gap-2 flex-1">
              <div className={`flex-1 flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs
                ${isDone ? 'bg-green-950/40 border border-green-800/40 text-green-300' : 'bg-gray-800/40 border border-gray-700/40 text-gray-500'}`}>
                {isDone ? <CheckCircle className="h-3 w-3 shrink-0" /> : <Loader2 className="h-3 w-3 shrink-0 animate-spin" />}
                <span className="truncate">{s}</span>
              </div>
              {i < steps.length - 1 && <ChevronRight className="h-3 w-3 text-gray-600 shrink-0" />}
            </div>
          )
        })}
      </div>
      <Terminal logs={job.logs} />
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function OnboardPageInner() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { isLoaded, isSignedIn, user } = useUser()

  const [url, setUrl] = useState(searchParams.get('url') || '')
  const [urlType, setUrlType] = useState<'website' | 'youtube'>('website')
  const [stage, setStage] = useState<Stage>('input')
  const [job, setJob] = useState<JobState | null>(null)
  const [workspaceId, setWorkspaceId] = useState('')
  const [directive, setDirective] = useState('')
  const [showDirective, setShowDirective] = useState(false)
  const [error, setError] = useState('')
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)
  const [rzpLoaded, setRzpLoaded] = useState(false)
  // 90-second countdown timer
  const [countdown, setCountdown] = useState(90)
  const [timerDone, setTimerDone] = useState(false)
  const scanDoneRef = useRef(false)   // preview_ready from API
  const timerDoneRef = useRef(false)  // timer hit 0

  // Load Razorpay script
  useEffect(() => {
    if (typeof window === 'undefined') return
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => setRzpLoaded(true)
    document.body.appendChild(script)
    return () => {
      try { document.body.removeChild(script) } catch { /* ignore */ }
    }
  }, [])

  // Detect URL type on change
  useEffect(() => {
    if (!url.trim()) return
    const lower = url.toLowerCase()
    if (lower.includes('youtube.com/@') || lower.includes('youtube.com/channel/') ||
        lower.includes('youtube.com/c/') || lower.includes('youtu.be/')) {
      setUrlType('youtube')
    } else {
      setUrlType('website')
    }
  }, [url])

  // Ensure workspace exists for signed-in users
  const ensureWorkspace = useCallback(async (): Promise<string> => {
    if (workspaceId) return workspaceId
    // Try to get existing workspaces
    const res = await fetch('/api/workspaces')
    const data = await res.json()
    const ws = (data.workspaces ?? []) as Array<{ id: string; name: string }>
    if (ws.length > 0) {
      setWorkspaceId(ws[0].id)
      return ws[0].id
    }
    // Auto-create workspace
    const brand = url ? new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace('www.', '') : 'My Brand'
    const cr = await fetch('/api/workspace/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: brand, workspace_type: urlType === 'youtube' ? 'creator' : 'd2c' }),
    })
    const cd = await cr.json()
    const wsId = cd.workspace_id || ''
    setWorkspaceId(wsId)
    return wsId
  }, [workspaceId, url, urlType])

  // Start the 90-second countdown
  const startCountdown = useCallback(() => {
    scanDoneRef.current = false
    timerDoneRef.current = false
    setTimerDone(false)
    setCountdown(90)
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(timerRef.current!)
          timerDoneRef.current = true
          setTimerDone(true)
          // If scan was already done, advance to preview_ready
          if (scanDoneRef.current) setStage('preview_ready')
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }, [])

  // Start free preview
  const startPreview = useCallback(async () => {
    setError('')
    try {
      const wsId = await ensureWorkspace()
      if (!wsId) throw new Error('Could not create workspace')

      const res = await fetch('/api/onboard/free-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, url }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to start preview')

      setJob({
        job_id: data.job_id,
        status: 'previewing',
        logs: [],
        preview_data: null,
        url,
        url_type: data.url_type,
        bi_job_id: null,
        yt_job_id: null,
        gos_job_id: null,
        paid: false,
      })
      setStage('previewing')
      startCountdown()
      startPolling(data.job_id, wsId)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [url, ensureWorkspace, startCountdown])

  // Polling
  const startPolling = (jobId: string, wsId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/onboard/preview-status?job_id=${jobId}&workspace_id=${wsId}`)
        if (!r.ok) return
        const d: JobState = await r.json()
        setJob(d)
        if (d.status === 'preview_ready') {
          scanDoneRef.current = true
          clearInterval(pollRef.current!)
          // Only advance stage if the 90s timer has also finished
          if (timerDoneRef.current) setStage('preview_ready')
        } else if (d.status === 'complete') {
          setStage('complete')
          clearInterval(pollRef.current!)
          setTimeout(() => router.push(`/growth-os?ws=${wsId}`), 3000)
        } else if (d.status === 'failed') {
          setStage('failed')
          clearInterval(pollRef.current!)
        }
      } catch { /* ignore poll errors */ }
    }, 2000)
  }

  const startChainPolling = (jobId: string, wsId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/onboard/chain-status?job_id=${jobId}&workspace_id=${wsId}`)
        if (!r.ok) return
        const d: JobState = await r.json()
        setJob(d)
        if (d.status === 'complete') {
          setStage('complete')
          clearInterval(pollRef.current!)
          setTimeout(() => router.push(`/growth-os?ws=${wsId}`), 4000)
        } else if (d.status === 'failed') {
          setStage('failed')
          clearInterval(pollRef.current!)
        }
      } catch { /* ignore */ }
    }, 2000)
  }

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (timerRef.current) clearInterval(timerRef.current)
  }, [])

  // Handle sign-in complete (after Clerk redirects back)
  useEffect(() => {
    if (isLoaded && isSignedIn && stage === 'signin') {
      startPreview()
    }
  }, [isLoaded, isSignedIn, stage])

  // Auto-advance: URL in query string + already signed in → skip input stage entirely
  const autoStartedRef = useRef(false)
  useEffect(() => {
    if (!isLoaded || !isSignedIn || autoStartedRef.current) return
    const urlFromQuery = searchParams.get('url')
    if (urlFromQuery && stage === 'input') {
      autoStartedRef.current = true
      startPreview()
    }
  }, [isLoaded, isSignedIn, stage])

  // Payment flow
  const handlePay = async () => {
    if (!job || !workspaceId) return
    setError('')
    setStage('paying')
    try {
      const r = await fetch('/api/onboard/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, job_id: job.job_id }),
      })
      const order = await r.json()
      if (!r.ok) throw new Error(order.detail || 'Failed to create order')

      if (order.order_id.startsWith('stub_')) {
        // Test mode — skip real payment
        await confirmStubPayment(order.order_id)
        return
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const RazorpayClass = (window as any).Razorpay as RazorpayConstructor | undefined
      if (!rzpLoaded || !RazorpayClass) throw new Error('Payment SDK not loaded')

      const rzp = new RazorpayClass({
        key: order.razorpay_key_id,
        amount: order.amount_paise,
        currency: 'INR',
        order_id: order.order_id,
        name: 'Runway Studios',
        description: 'AI Growth Strategy Report',
        theme: { color: '#6366f1' },
        handler: async (response: Record<string, string>) => {
          await confirmPayment(
            order.order_id,
            response.razorpay_payment_id,
            response.razorpay_signature,
          )
        },
        modal: {
          ondismiss: () => setStage('preview_ready'),
        },
      })
      rzp.open()
    } catch (e) {
      setError((e as Error).message)
      setStage('preview_ready')
    }
  }

  const confirmStubPayment = async (orderId: string) => {
    if (!job) return
    const r = await fetch('/api/onboard/confirm-purchase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: workspaceId,
        job_id: job.job_id,
        razorpay_order_id: orderId,
        razorpay_payment_id: 'stub_pay_0',
        razorpay_signature: 'stub_sig',
        directive,
      }),
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || 'Payment confirmation failed')
    setStage('chain_running')
    startChainPolling(job.job_id, workspaceId)
  }

  const confirmPayment = async (orderId: string, paymentId: string, signature: string) => {
    if (!job) return
    const r = await fetch('/api/onboard/confirm-purchase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: workspaceId,
        job_id: job.job_id,
        razorpay_order_id: orderId,
        razorpay_payment_id: paymentId,
        razorpay_signature: signature,
        directive,
      }),
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || 'Payment confirmation failed')
    setStage('chain_running')
    startChainPolling(job.job_id, workspaceId)
  }

  const handleStart = () => {
    if (!url.trim()) return
    if (!isLoaded) return
    if (!isSignedIn) {
      setStage('signin')
      return
    }
    startPreview()
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-brand-600 rounded-lg flex items-center justify-center">
            <Zap className="h-4 w-4 text-white" />
          </div>
          <span className="font-bold text-white">Runway Studios</span>
        </div>
        <a href="https://runwaystudios.co" target="_blank" rel="noopener noreferrer"
           className="text-xs text-gray-400 hover:text-white transition-colors">
          Back to website
        </a>
      </header>

      <div className="max-w-2xl mx-auto px-4 py-12">

        {/* ── Stage: sign-in ─────────────────────────────────────────────────── */}
        {stage === 'signin' && (
          <div className="flex flex-col items-center gap-6">
            <div className="text-center">
              <h1 className="text-2xl font-bold">Sign in to continue</h1>
              <p className="text-sm text-gray-400 mt-1">Create a free account to see your analysis for <strong className="text-white">{url}</strong></p>
            </div>
            <div className="w-full">
              <SignIn
                afterSignInUrl={`/onboard?url=${encodeURIComponent(url)}`}
                afterSignUpUrl={`/onboard?url=${encodeURIComponent(url)}`}
                appearance={{
                  elements: {
                    rootBox: 'w-full',
                    card: 'rounded-2xl bg-gray-900 border border-gray-700 shadow-none',
                    headerTitle: 'text-white',
                    socialButtonsBlockButton: 'bg-gray-800 border border-gray-600 text-white hover:bg-gray-700',
                    formFieldInput: 'bg-gray-800 border-gray-600 text-white',
                    formButtonPrimary: 'bg-brand-600 hover:bg-brand-700',
                    footerActionLink: 'text-brand-400',
                  }
                }}
              />
            </div>
          </div>
        )}

        {/* ── Stage: input ───────────────────────────────────────────────────── */}
        {stage === 'input' && (
          <div className="space-y-8">
            {/* Hero */}
            <div className="text-center space-y-3">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-brand-900/40 border border-brand-700/40 rounded-full text-xs text-brand-300 font-medium">
                <Zap className="h-3 w-3" />
                Free competitor analysis — powered by ARIA
              </div>
              <h1 className="text-3xl font-bold leading-tight">
                Drop your URL.<br />
                <span className="text-brand-400">Get a free preview</span> in 30 seconds.
              </h1>
              <p className="text-gray-400 text-sm max-w-md mx-auto">
                YouTube channel, product page, app, or website — ARIA analyses your brand
                and finds your competitors for free. Pay ₹499 to unlock the full 9-layer
                deep-dive + Growth OS strategy.
              </p>
            </div>

            {/* URL Input */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-1 bg-gray-900 border border-gray-700 rounded-xl focus-within:border-brand-500 transition-colors">
                {urlType === 'youtube'
                  ? <Youtube className="h-5 w-5 text-red-400 ml-3 shrink-0" />
                  : <Globe className="h-5 w-5 text-brand-400 ml-3 shrink-0" />
                }
                <input
                  type="url"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleStart()}
                  placeholder="https://yourwebsite.com or youtube.com/@yourchannel"
                  className="flex-1 bg-transparent px-2 py-3 text-sm text-white placeholder-gray-500 outline-none"
                  autoFocus
                />
                {url && (
                  <span className={`px-2 py-0.5 rounded-md text-xs font-medium mr-1 ${
                    urlType === 'youtube' ? 'bg-red-900/40 text-red-300' : 'bg-brand-900/40 text-brand-300'
                  }`}>
                    {urlType === 'youtube' ? 'YouTube' : 'Website'}
                  </span>
                )}
              </div>

              {error && (
                <div className="flex items-center gap-2 p-3 bg-red-950/40 border border-red-800/40 rounded-lg text-xs text-red-300">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {error}
                </div>
              )}

              <button
                onClick={handleStart}
                disabled={!url.trim()}
                className="w-full flex items-center justify-center gap-2 px-6 py-3.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl font-semibold text-sm transition-colors"
              >
                <Search className="h-4 w-4" />
                Analyse for Free
                <ArrowRight className="h-4 w-4" />
              </button>

              <p className="text-center text-xs text-gray-500">
                Free preview • No credit card required • Sign in with Google in 5 seconds
              </p>
            </div>

            {/* What you get */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { icon: Users, label: 'Competitor mapping', detail: 'Up to 5 competitors found' },
                { icon: TrendingUp, label: 'LP Audit', detail: 'Conversion score + fixes' },
                { icon: Zap, label: 'Growth OS', detail: '90-day strategy plan' },
              ].map(({ icon: Icon, label, detail }) => (
                <div key={label} className="p-3 bg-gray-900 border border-gray-800 rounded-xl text-center">
                  <Icon className="h-5 w-5 text-brand-400 mx-auto mb-1.5" />
                  <p className="text-xs font-medium text-white">{label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{detail}</p>
                </div>
              ))}
            </div>

            {/* Proof */}
            <div className="flex items-center justify-center gap-6 text-xs text-gray-500">
              <span className="flex items-center gap-1"><Star className="h-3 w-3 text-amber-400" /> 4.9/5 rating</span>
              <span className="flex items-center gap-1"><Shield className="h-3 w-3 text-green-400" /> Secure payment</span>
              <span className="flex items-center gap-1"><CheckCircle className="h-3 w-3 text-brand-400" /> Instant results</span>
            </div>
          </div>
        )}

        {/* ── Stage: previewing ──────────────────────────────────────────────── */}
        {stage === 'previewing' && (
          <div className="space-y-6">
            <div className="text-center space-y-3">
              {/* 90-second circular countdown */}
              <div className="relative inline-flex items-center justify-center">
                <svg className="h-20 w-20 -rotate-90" viewBox="0 0 80 80">
                  <circle cx="40" cy="40" r="34" fill="none" stroke="#1f2937" strokeWidth="6" />
                  <circle
                    cx="40" cy="40" r="34" fill="none"
                    stroke="#6366f1" strokeWidth="6" strokeLinecap="round"
                    strokeDasharray={`${2 * Math.PI * 34}`}
                    strokeDashoffset={`${2 * Math.PI * 34 * countdown / 90}`}
                    style={{ transition: 'stroke-dashoffset 1s linear' }}
                  />
                </svg>
                <span className="absolute text-xl font-bold text-white">{countdown}</span>
              </div>
              <div>
                <div className="flex items-center justify-center gap-2 text-brand-400">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="font-semibold">Scanning {url}</span>
                </div>
                <p className="text-sm text-gray-400 mt-1">ARIA is building your intelligence profile — sit tight</p>
              </div>
            </div>
            <Terminal logs={job?.logs ?? []} />
          </div>
        )}

        {/* ── Stage: preview_ready ───────────────────────────────────────────── */}
        {stage === 'preview_ready' && job?.preview_data && (
          <div className="space-y-6">
            <div className="text-center space-y-2">
              <div className="flex items-center justify-center gap-2 text-green-400">
                <CheckCircle className="h-5 w-5" />
                <span className="font-semibold">Preview ready for {url}</span>
              </div>
              <p className="text-sm text-gray-400">Free analysis complete. Pay ₹499 to run the full deep-dive.</p>
            </div>

            <div className="p-4 bg-gray-900 border border-gray-800 rounded-xl">
              <PreviewResults data={job.preview_data} />
            </div>

            {/* Optional directive */}
            <div>
              <button
                onClick={() => setShowDirective(!showDirective)}
                className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
              >
                <ChevronRight className={`h-3 w-3 transition-transform ${showDirective ? 'rotate-90' : ''}`} />
                Add a specific goal (optional)
              </button>
              {showDirective && (
                <input
                  type="text"
                  value={directive}
                  onChange={e => setDirective(e.target.value)}
                  placeholder="e.g. Grow YouTube to 10K subscribers, increase ROAS to 4x…"
                  className="mt-2 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 outline-none focus:border-brand-500"
                />
              )}
            </div>

            {error && (
              <div className="flex items-center gap-2 p-3 bg-red-950/40 border border-red-800/40 rounded-lg text-xs text-red-300">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            {/* Pay CTA */}
            <div className="p-4 bg-gradient-to-br from-brand-900/40 to-purple-900/40 border border-brand-700/40 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-bold text-white">Get the Full Report</p>
                  <p className="text-xs text-gray-400 mt-0.5">Competitor deep-dive · Website fix list · 90-day growth plan</p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold text-white">₹499</p>
                  <p className="text-xs text-gray-400 line-through">₹4,999</p>
                </div>
              </div>
              <ul className="text-xs text-gray-300 space-y-1">
                <li className="flex items-center gap-1.5"><CheckCircle className="h-3 w-3 text-green-400 shrink-0" />What each competitor is doing — and what you should steal from them</li>
                <li className="flex items-center gap-1.5"><CheckCircle className="h-3 w-3 text-green-400 shrink-0" />What real customers say about your category (mined from Reddit)</li>
                <li className="flex items-center gap-1.5"><CheckCircle className="h-3 w-3 text-green-400 shrink-0" />Why people leave your site without buying, and how to fix it</li>
                <li className="flex items-center gap-1.5"><CheckCircle className="h-3 w-3 text-green-400 shrink-0" />A 90-day plan with specific ads, pages, and offers — written for your brand</li>
              </ul>
              <button
                onClick={handlePay}
                className="w-full flex items-center justify-center gap-2 px-6 py-3.5 bg-brand-600 hover:bg-brand-700 rounded-xl font-semibold text-sm transition-colors"
              >
                <CreditCard className="h-4 w-4" />
                Get My Full Report — ₹499
                <ArrowRight className="h-4 w-4" />
              </button>
              <div className="flex items-center justify-center gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1"><Lock className="h-3 w-3" /> Secured by Razorpay</span>
                <span className="flex items-center gap-1"><Shield className="h-3 w-3 text-green-400" /> Pay once, results ready in ~5 min</span>
              </div>
            </div>
          </div>
        )}

        {/* ── Stage: paying ─────────────────────────────────────────────────── */}
        {stage === 'paying' && (
          <div className="flex flex-col items-center gap-4 py-12">
            <Loader2 className="h-8 w-8 animate-spin text-brand-400" />
            <p className="text-gray-300">Opening payment…</p>
          </div>
        )}

        {/* ── Stage: chain_running ───────────────────────────────────────────── */}
        {stage === 'chain_running' && job && (
          <div className="space-y-6">
            <div className="text-center space-y-2">
              <div className="flex items-center justify-center gap-2 text-brand-400">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="font-semibold">Running full analysis…</span>
              </div>
              <p className="text-sm text-gray-400">This takes 3–5 minutes. You can close this and check your dashboard later.</p>
            </div>
            <ChainProgress job={job} gosJobId={job.gos_job_id} />
          </div>
        )}

        {/* ── Stage: complete ────────────────────────────────────────────────── */}
        {stage === 'complete' && (
          <div className="flex flex-col items-center gap-6 py-12 text-center">
            <div className="w-16 h-16 rounded-full bg-green-900/40 border border-green-700/40 flex items-center justify-center">
              <CheckCircle className="h-8 w-8 text-green-400" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">Analysis Complete!</h2>
              <p className="text-sm text-gray-400 mt-1">Redirecting you to your dashboard…</p>
            </div>
            <button
              onClick={() => router.push(`/growth-os?ws=${workspaceId}`)}
              className="flex items-center gap-2 px-6 py-3 bg-brand-600 hover:bg-brand-700 rounded-xl font-semibold text-sm transition-colors"
            >
              View My Growth Strategy <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* ── Stage: failed ─────────────────────────────────────────────────── */}
        {stage === 'failed' && (
          <div className="flex flex-col items-center gap-4 py-12 text-center">
            <AlertCircle className="h-8 w-8 text-red-400" />
            <div>
              <h2 className="text-xl font-bold text-white">Something went wrong</h2>
              <p className="text-sm text-gray-400 mt-1">The analysis timed out or encountered an error.</p>
            </div>
            <button
              onClick={() => { setStage('input'); setJob(null); setError('') }}
              className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 rounded-xl text-sm font-medium transition-colors"
            >
              Try again
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function OnboardPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-400" />
      </div>
    }>
      <OnboardPageInner />
    </Suspense>
  )
}
