'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Sparkles, Loader2, CheckCircle2, AlertCircle, RefreshCw,
  ChevronDown, ChevronRight, ChevronUp, Send, Mail, MessageSquare,
  Smartphone, Target, Zap, TrendingUp, ShoppingCart, Globe, Megaphone,
  BarChart2, Package, Layout, Users, ArrowRight, Clock, Calendar,
  ExternalLink, Copy, Check, History, X,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface LogEntry {
  ts: string
  phase: string
  type: string
  msg: string
  source?: string
}

interface StrategySummary {
  headline: string
  key_insight: string
  primary_opportunity: string
  '90_day_revenue_target': string
  biggest_risk: string
}

interface Action {
  id: string
  period: string
  dimension: string
  channel: string
  priority: 'P0' | 'P1' | 'P2'
  title: string
  rationale: string
  exact_next_step: string
  kpi_target: string
  effort_days: number
  budget_recommendation?: string
  creative_brief?: string
  copy_template?: string
  setup_guide?: string
  source?: string
}

interface CRMMessage {
  day: number
  subject?: string
  body: string
  cta: string
  goal: string
}

interface CRMSequence {
  name: string
  channel: string
  trigger: string
  messages: CRMMessage[]
}

interface ProductBrief {
  hero_feature_recommendation: string
  rationale: string
  positioning_angle: string
  pricing_suggestion: string
  implementation_steps: string
}

interface IntelCoverage {
  sources_used: string[]
  sources_missing: string[]
  coverage_pct: number
}

interface GrowthPlan {
  plan_id?: string
  strategy_summary?: StrategySummary
  actions?: Action[]
  crm_sequences?: CRMSequence[]
  product_brief?: ProductBrief
  intelligence_coverage?: IntelCoverage
}

interface JobState {
  job_id: string | null
  status: 'none' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  logs: LogEntry[]
  plan: GrowthPlan
  credits_charged: number
  created_at: string | null
  completed_at: string | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTIVE_JOB_KEY = 'runway_gos_active_job_'

const DIMENSION_META: Record<string, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  paid:         { label: 'Paid Acquisition',       icon: Megaphone,     color: 'text-blue-600',   bg: 'bg-blue-50' },
  organic:      { label: 'Organic Content',         icon: TrendingUp,    color: 'text-green-600',  bg: 'bg-green-50' },
  product:      { label: 'Product & Offer',         icon: Package,       color: 'text-orange-600', bg: 'bg-orange-50' },
  landing_page: { label: 'Landing Pages',           icon: Layout,        color: 'text-purple-600', bg: 'bg-purple-50' },
  crm:          { label: 'Email / SMS / WhatsApp',  icon: Mail,          color: 'text-rose-600',   bg: 'bg-rose-50' },
  competitive:  { label: 'Competitive Positioning', icon: Target,        color: 'text-indigo-600', bg: 'bg-indigo-50' },
  brand:        { label: 'Brand & PR',              icon: Users,         color: 'text-amber-600',  bg: 'bg-amber-50' },
}

const CHANNEL_META: Record<string, { label: string; color: string }> = {
  meta:           { label: 'Meta',      color: 'bg-blue-100 text-blue-700' },
  google:         { label: 'Google',    color: 'bg-green-100 text-green-700' },
  youtube:        { label: 'YouTube',   color: 'bg-red-100 text-red-700' },
  email:          { label: 'Email',     color: 'bg-rose-100 text-rose-700' },
  sms:            { label: 'SMS',       color: 'bg-violet-100 text-violet-700' },
  whatsapp:       { label: 'WhatsApp',  color: 'bg-emerald-100 text-emerald-700' },
  seo:            { label: 'SEO',       color: 'bg-cyan-100 text-cyan-700' },
  organic_social: { label: 'Organic',   color: 'bg-lime-100 text-lime-700' },
  shopify:        { label: 'Shopify',   color: 'bg-orange-100 text-orange-700' },
  all:            { label: 'All',       color: 'bg-gray-100 text-gray-700' },
}

const CRM_CHANNEL_ICON: Record<string, React.ElementType> = {
  email:    Mail,
  whatsapp: MessageSquare,
  sms:      Smartphone,
}

const PERIOD_ORDER = ['Week 1', 'Week 2', 'Month 2', 'Month 3']

const STRATEGY_MODES = [
  { id: 'scale',      label: '🚀 Scale',      desc: 'Maximise revenue at all costs' },
  { id: 'efficiency', label: '⚡ Efficiency',  desc: 'Cut waste, improve ROAS' },
  { id: 'launch',     label: '🆕 Launch',      desc: 'Drive awareness & first purchases' },
  { id: 'seasonal',   label: '📅 Seasonal',    desc: 'Capitalise on seasonal demand' },
  { id: 'custom',     label: '🎯 Custom',      desc: 'Enter your own directive' },
]

// ── Log line colours ──────────────────────────────────────────────────────────

function logColor(entry: LogEntry): string {
  if (entry.type === 'found')       return 'text-emerald-400'
  if (entry.type === 'missing')     return 'text-amber-400'
  if (entry.type === 'error')       return 'text-red-400'
  if (entry.type === 'phase')       return 'text-violet-300 font-semibold'
  if (entry.type === 'header')      return 'text-white font-bold tracking-wide'
  if (entry.type === 'separator' || entry.type === 'divider') return 'text-gray-600'
  if (entry.type === 'done')        return 'text-emerald-300 font-semibold'
  if (entry.type === 'auto_trigger') return 'text-cyan-300'
  if (entry.type === 'thinking')    return 'text-sky-400'
  return 'text-gray-300'
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDT(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <button onClick={copy} className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors">
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

// ── ActionCard ────────────────────────────────────────────────────────────────

function ActionCard({ action }: { action: Action }) {
  const [open, setOpen] = useState(false)
  const dim = DIMENSION_META[action.dimension] ?? DIMENSION_META.paid
  const DimIcon = dim.icon
  const ch = CHANNEL_META[action.channel] ?? CHANNEL_META.all
  const priorityColor = action.priority === 'P0'
    ? 'bg-red-100 text-red-700 border-red-200'
    : action.priority === 'P1'
    ? 'bg-amber-100 text-amber-700 border-amber-200'
    : 'bg-gray-100 text-gray-600 border-gray-200'

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden transition-shadow hover:shadow-sm">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-3 p-4 text-left"
      >
        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${dim.bg}`}>
          <DimIcon className={`h-3.5 w-3.5 ${dim.color}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${priorityColor}`}>
              {action.priority}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${ch.color}`}>
              {ch.label}
            </span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">
              {action.period}
            </span>
            {action.effort_days && (
              <span className="text-[10px] text-gray-400">{action.effort_days}d effort</span>
            )}
          </div>
          <p className="text-sm font-semibold text-gray-900 leading-snug">{action.title}</p>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{action.rationale}</p>
        </div>
        <ChevronDown className={`h-4 w-4 text-gray-400 shrink-0 mt-0.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 pb-4 pt-3 space-y-3">
          {/* Next step */}
          <div className="rounded-lg bg-blue-50 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-blue-600 mb-1">
              → Next step (do this tomorrow)
            </p>
            <p className="text-xs text-blue-800">{action.exact_next_step}</p>
          </div>

          {/* KPI */}
          {action.kpi_target && (
            <div className="rounded-lg bg-green-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wide text-green-600 mb-1">
                🎯 KPI Target
              </p>
              <p className="text-xs text-green-800">{action.kpi_target}</p>
            </div>
          )}

          {/* Budget */}
          {action.budget_recommendation && (
            <div className="flex items-center gap-2 text-xs text-gray-600">
              <span className="font-medium">Budget:</span>
              <span>{action.budget_recommendation}</span>
            </div>
          )}

          {/* Creative brief */}
          {action.creative_brief && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-gray-500 mb-1.5">
                Creative Brief
              </p>
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans bg-gray-50 rounded-lg p-3 leading-relaxed">
                {action.creative_brief}
              </pre>
            </div>
          )}

          {/* Copy template */}
          {action.copy_template && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-gray-500">
                  Message Template
                </p>
                <CopyButton text={action.copy_template} />
              </div>
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans bg-gray-50 rounded-lg p-3 leading-relaxed border border-gray-100">
                {action.copy_template}
              </pre>
            </div>
          )}

          {/* Setup guide */}
          {action.setup_guide && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-gray-500 mb-1.5">
                Setup Guide
              </p>
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                {action.setup_guide}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── CRMSequenceCard ───────────────────────────────────────────────────────────

function CRMSequenceCard({ seq }: { seq: CRMSequence }) {
  const [open, setOpen] = useState(false)
  const [msgOpen, setMsgOpen] = useState<number | null>(null)
  const Icon = CRM_CHANNEL_ICON[seq.channel] ?? Mail
  const channelColor = seq.channel === 'email'
    ? 'bg-rose-50 text-rose-600 border-rose-100'
    : seq.channel === 'whatsapp'
    ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
    : 'bg-violet-50 text-violet-600 border-violet-100'

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 p-4 text-left"
      >
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${channelColor}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">{seq.name}</p>
          <p className="text-xs text-gray-500">{seq.trigger} · {seq.messages?.length ?? 0} messages</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold capitalize ${channelColor}`}>
          {seq.channel}
        </span>
        <ChevronDown className={`h-4 w-4 text-gray-400 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 pb-4 pt-3 space-y-2">
          {(seq.messages ?? []).map((msg, i) => (
            <div key={i} className="rounded-lg border border-gray-100 overflow-hidden">
              <button
                onClick={() => setMsgOpen(msgOpen === i ? null : i)}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-gray-50 transition-colors"
              >
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-600">
                  {msg.day}
                </div>
                <div className="flex-1 min-w-0">
                  {msg.subject && (
                    <p className="text-xs font-semibold text-gray-800 truncate">
                      Subject: {msg.subject}
                    </p>
                  )}
                  <p className="text-[11px] text-gray-500 truncate">{msg.goal}</p>
                </div>
                <ChevronDown className={`h-3.5 w-3.5 text-gray-400 shrink-0 transition-transform ${msgOpen === i ? 'rotate-180' : ''}`} />
              </button>
              {msgOpen === i && (
                <div className="border-t border-gray-100 px-3 pb-3 pt-2 space-y-2">
                  {msg.subject && (
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-0.5">Subject line</p>
                        <p className="text-xs font-semibold text-gray-800">{msg.subject}</p>
                      </div>
                      <CopyButton text={msg.subject} />
                    </div>
                  )}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Message body</p>
                      <CopyButton text={msg.body} />
                    </div>
                    <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans bg-gray-50 rounded p-2.5 border border-gray-100 leading-relaxed max-h-64 overflow-y-auto">
                      {msg.body}
                    </pre>
                  </div>
                  <div className="rounded bg-blue-50 px-3 py-2 text-xs text-blue-700">
                    <span className="font-semibold">CTA:</span> {msg.cta}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── TerminalLog ───────────────────────────────────────────────────────────────

function TerminalLog({ logs, status }: { logs: LogEntry[]; status: string }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs.length])

  return (
    <div className="rounded-xl bg-gray-950 border border-gray-800 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-800 bg-gray-900">
        <div className="flex gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
          <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
          <div className="h-2.5 w-2.5 rounded-full bg-green-500/80" />
        </div>
        <span className="text-[11px] text-gray-500 font-mono ml-1">aria-growth-os</span>
        <div className="ml-auto flex items-center gap-2">
          {(status === 'pending' || status === 'running') && (
            <span className="flex items-center gap-1.5 text-[11px] text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Running
            </span>
          )}
          {status === 'completed' && (
            <span className="text-[11px] text-emerald-400">● Done</span>
          )}
          {status === 'failed' && (
            <span className="text-[11px] text-red-400">● Failed</span>
          )}
        </div>
      </div>
      <div className="p-4 h-72 overflow-y-auto font-mono text-xs space-y-0.5">
        {logs.map((entry, i) => (
          <div key={i} className={logColor(entry)}>
            <span className="text-gray-600 mr-2">
              {new Date(entry.ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
            {entry.msg}
          </div>
        ))}
        {(status === 'pending' || status === 'running') && (
          <div className="flex items-center gap-2 text-gray-500">
            <span className="animate-pulse">█</span>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

interface Props {
  workspaceId: string
}

export default function GrowthOSPanel({ workspaceId }: Props) {
  const [job, setJob] = useState<JobState>({
    job_id: null,
    status: 'none',
    logs: [],
    plan: {},
    credits_charged: 0,
    created_at: null,
    completed_at: null,
  })
  const [directive, setDirective] = useState('')
  const [brandUrl, setBrandUrl] = useState('')
  const [strategyMode, setStrategyMode] = useState('scale')
  const [starting, setStarting] = useState(false)
  const [showRunDialog, setShowRunDialog] = useState(false)
  const [activeTab, setActiveTab] = useState<'actions' | 'crm' | 'product'>('actions')
  const [activeDimension, setActiveDimension] = useState<string | null>(null)
  const [activePeriod, setActivePeriod] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<Array<{ plan_id: string; generated_at: string; strategy_mode: string; action_count: number }>>([])
  const [loadingHistoryPlan, setLoadingHistoryPlan] = useState<string | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const localKey = ACTIVE_JOB_KEY + workspaceId

  // ── Load on mount ──────────────────────────────────────────────────────────

  useEffect(() => {
    // Check localStorage for an active job first (survives navigation)
    const savedJobId = typeof window !== 'undefined' ? localStorage.getItem(localKey) : null
    if (savedJobId) {
      pollJob(savedJobId)
    } else {
      // Otherwise load the most recent job/plan
      loadActiveJob()
    }
  }, [workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Poll while running ─────────────────────────────────────────────────────

  useEffect(() => {
    if (job.status === 'running' || job.status === 'pending') {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(() => {
        if (job.job_id) pollJob(job.job_id)
      }, 3000)
    } else {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      // Clear localStorage when job is done/failed/cancelled
      if ((job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') && job.job_id) {
        if (typeof window !== 'undefined') localStorage.removeItem(localKey)
      }
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [job.status, job.job_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadActiveJob = async () => {
    try {
      const res = await fetch(`/api/growth-os/active-job?workspace_id=${workspaceId}`)
      if (!res.ok) return
      const data = await res.json()
      if (data.job_id && data.status !== 'none') {
        setJob(data)
        if (data.status === 'running' || data.status === 'pending') {
          if (typeof window !== 'undefined') localStorage.setItem(localKey, data.job_id)
        }
      }
    } catch { /* ignore */ }
  }

  const pollJob = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`/api/growth-os/job-status/${jobId}?workspace_id=${workspaceId}`)
      if (!res.ok) return
      const data = await res.json()
      setJob(data)
    } catch { /* ignore */ }
  }, [workspaceId])

  // ── Start job ──────────────────────────────────────────────────────────────

  const startJob = async () => {
    setStarting(true)
    setShowRunDialog(false)
    try {
      const res = await fetch('/api/growth-os/run-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          directive: directive.trim() || null,
          brand_url: brandUrl.trim() || null,
          strategy_mode: strategyMode,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Failed to start')
      const jobId = data.job_id
      if (typeof window !== 'undefined') localStorage.setItem(localKey, jobId)
      setJob({ job_id: jobId, status: 'pending', logs: [], plan: {}, credits_charged: 0, created_at: null, completed_at: null })
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to start strategy generation')
    } finally {
      setStarting(false)
    }
  }

  // ── Cancel / force-stop running job ────────────────────────────────────────

  const [cancelling, setCancelling] = useState(false)

  const cancelJob = async () => {
    if (!job.job_id) return
    setCancelling(true)
    try {
      const res = await fetch(
        `/api/growth-os/cancel-job/${job.job_id}?workspace_id=${workspaceId}`,
        { method: 'POST' },
      )
      if (res.ok) {
        setJob(prev => ({ ...prev, status: 'cancelled' }))
        if (typeof window !== 'undefined') localStorage.removeItem(localKey)
      }
    } catch { /* ignore */ } finally {
      setCancelling(false)
    }
  }

  // ── Load history plan ──────────────────────────────────────────────────────

  const loadHistoryList = async () => {
    try {
      const res = await fetch(`/api/growth-os/history?workspace_id=${workspaceId}`)
      if (!res.ok) return
      const data = await res.json()
      setHistory(data.plans ?? [])
    } catch { /* ignore */ }
  }

  const loadHistoryPlan = async (planId: string) => {
    setLoadingHistoryPlan(planId)
    try {
      const res = await fetch(`/api/growth-os/plan?workspace_id=${workspaceId}&plan_id=${planId}`)
      if (!res.ok) return
      const data = await res.json()
      setJob(prev => ({
        ...prev,
        plan: data,
        status: 'completed',
        created_at: data.generated_at ?? null,
      }))
    } catch { /* ignore */ } finally {
      setLoadingHistoryPlan(null)
      setShowHistory(false)
    }
  }

  // ── Derived ────────────────────────────────────────────────────────────────

  const plan = job.plan
  const actions = plan.actions ?? []
  const isRunning = job.status === 'pending' || job.status === 'running'
  const isDone = job.status === 'completed'

  const filteredActions = actions.filter(a => {
    if (activeDimension && a.dimension !== activeDimension) return false
    if (activePeriod && a.period !== activePeriod) return false
    return true
  })

  const dimensionCounts = Object.keys(DIMENSION_META).reduce((acc, k) => {
    acc[k] = actions.filter(a => a.dimension === k).length
    return acc
  }, {} as Record<string, number>)

  const periodCounts = PERIOD_ORDER.reduce((acc, p) => {
    acc[p] = actions.filter(a => a.period === p).length
    return acc
  }, {} as Record<string, number>)

  const coverage = plan.intelligence_coverage

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Growth OS Command Center</h1>
          <p className="text-sm text-gray-500">
            World-class 90-day growth strategy · 7 dimensions · Real copy included
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isDone && (
            <button
              onClick={() => { setShowHistory(true); loadHistoryList() }}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <History className="h-3.5 w-3.5" />
              History
            </button>
          )}
          {isRunning && (
            <button
              onClick={cancelJob}
              disabled={cancelling}
              className="flex items-center gap-2 rounded-xl bg-red-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50 transition-colors shadow-sm"
            >
              {cancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              Force Stop
            </button>
          )}
          {!isRunning && (
            <button
              onClick={() => setShowRunDialog(true)}
              disabled={starting}
              className="flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50 transition-colors shadow-sm"
            >
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {isDone ? 'Regenerate Strategy' : 'Generate Strategy'}
            </button>
          )}
        </div>
      </div>

      {/* ── Run Dialog (modal gate before starting) ── */}
      {showRunDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500">
                  <Sparkles className="h-4 w-4 text-white" />
                </div>
                <div>
                  <p className="text-sm font-bold text-gray-900">Configure Strategy</p>
                  <p className="text-xs text-gray-400">Tell ARIA what to optimise for — 10 credits</p>
                </div>
              </div>
              <button onClick={() => setShowRunDialog(false)} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {/* Brand / Website URL */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Brand website URL <span className="font-normal text-gray-400">(used for competitor analysis)</span>
                </label>
                <div className="relative">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                  <input
                    type="url"
                    value={brandUrl}
                    onChange={e => setBrandUrl(e.target.value)}
                    placeholder="https://yourbrand.com"
                    className="w-full rounded-xl border border-gray-200 pl-9 pr-4 py-2.5 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  />
                </div>
                <p className="mt-1 text-[11px] text-gray-400">ARIA will scrape your site + competitor sites to inform the strategy. Skip if already set up.</p>
              </div>

              {/* Strategy mode */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-2">Primary objective</label>
                <div className="grid grid-cols-3 gap-2">
                  {STRATEGY_MODES.map(m => (
                    <button
                      key={m.id}
                      onClick={() => setStrategyMode(m.id)}
                      className={`rounded-xl border px-3 py-2.5 text-xs font-medium text-left transition-all ${
                        strategyMode === m.id
                          ? 'border-amber-300 bg-amber-50 text-amber-700 shadow-sm'
                          : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                      title={m.desc}
                    >
                      <span className="block">{m.label}</span>
                      <span className="block text-[10px] text-gray-400 mt-0.5 font-normal leading-tight">{m.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Custom directive */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Specific goal or constraint <span className="font-normal text-gray-400">(optional but recommended)</span>
                </label>
                <textarea
                  value={directive}
                  onChange={e => setDirective(e.target.value)}
                  placeholder={
                    strategyMode === 'scale'      ? 'e.g. Scale revenue to ₹50L/month by July. Prioritise Meta retargeting and email automation.' :
                    strategyMode === 'efficiency' ? 'e.g. Cut wasted ad spend. Target ROAS > 3.0 within 60 days. Pause campaigns below 1.5x.' :
                    strategyMode === 'launch'     ? 'e.g. Launch new product. Target urban women 25-35. ₹2L budget, first 30 days.' :
                    strategyMode === 'seasonal'   ? 'e.g. Diwali campaign. Drive gifting purchases Oct-Nov. Bundle offers focus.' :
                    'Describe your exact goal, key constraints, monthly budget, and what ARIA should optimise for...'
                  }
                  rows={3}
                  className="w-full rounded-xl border border-gray-200 px-4 py-3 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-300 resize-none"
                />
              </div>

              {/* Footer */}
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => setShowRunDialog(false)}
                  className="flex-1 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={startJob}
                  disabled={starting}
                  className="flex flex-[2] items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
                >
                  {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Generate Strategy · 10 credits
                </button>
              </div>
              <p className="text-[11px] text-center text-gray-400 -mt-2">
                ARIA gathers intelligence from all your connected channels, then builds a 7-dimension 90-day growth plan with real copy. <strong className="text-amber-600">Takes 3–8 minutes.</strong>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Terminal log (shown while running, or when just completed) ── */}
      {(isRunning || (isDone && job.logs.length > 0)) && (
        <TerminalLog logs={job.logs} status={job.status} />
      )}

      {/* ── Completed state ── */}
      {isDone && plan.strategy_summary && (
        <>
          {/* Strategy summary card */}
          <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-5">
            <div className="flex items-start gap-3 mb-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-base font-bold text-gray-900 leading-snug">
                  {plan.strategy_summary.headline}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Generated {formatDT(job.created_at)} · {actions.length} actions · {plan.crm_sequences?.length ?? 0} CRM sequences
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-xl bg-white border border-amber-100 p-3.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-amber-600 mb-1">🔑 Key Insight</p>
                <p className="text-xs text-gray-700 leading-relaxed">{plan.strategy_summary.key_insight}</p>
              </div>
              <div className="rounded-xl bg-white border border-green-100 p-3.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-green-600 mb-1">🚀 Primary Opportunity</p>
                <p className="text-xs text-gray-700 leading-relaxed">{plan.strategy_summary.primary_opportunity}</p>
              </div>
              <div className="rounded-xl bg-white border border-blue-100 p-3.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-blue-600 mb-1">💰 90-Day Revenue Target</p>
                <p className="text-xs text-gray-700 leading-relaxed">{plan.strategy_summary['90_day_revenue_target']}</p>
              </div>
              <div className="rounded-xl bg-white border border-red-100 p-3.5">
                <p className="text-[10px] font-bold uppercase tracking-wide text-red-600 mb-1">⚠️ Biggest Risk</p>
                <p className="text-xs text-gray-700 leading-relaxed">{plan.strategy_summary.biggest_risk}</p>
              </div>
            </div>
          </div>

          {/* Intelligence coverage */}
          {coverage && (
            <div className="rounded-xl border border-gray-200 bg-white px-4 py-3.5">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-semibold text-gray-700">Intelligence Coverage</p>
                <span className={`text-sm font-bold ${coverage.coverage_pct >= 70 ? 'text-green-600' : coverage.coverage_pct >= 40 ? 'text-amber-600' : 'text-red-600'}`}>
                  {coverage.coverage_pct}%
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 mb-3">
                <div
                  className={`h-1.5 rounded-full transition-all ${coverage.coverage_pct >= 70 ? 'bg-green-500' : coverage.coverage_pct >= 40 ? 'bg-amber-400' : 'bg-red-400'}`}
                  style={{ width: `${coverage.coverage_pct}%` }}
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {coverage.sources_used.map(s => (
                  <span key={s} className="flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-[11px] font-medium text-green-700">
                    <CheckCircle2 className="h-3 w-3" />{s}
                  </span>
                ))}
                {coverage.sources_missing.map(s => (
                  <span key={s} className="flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-0.5 text-[11px] text-gray-500">
                    <AlertCircle className="h-3 w-3" />{s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tab switcher */}
          <div className="flex gap-1 rounded-xl bg-gray-100 p-1">
            {[
              { id: 'actions', label: `Actions (${actions.length})` },
              { id: 'crm',     label: `CRM Sequences (${plan.crm_sequences?.length ?? 0})` },
              { id: 'product', label: 'Product Brief' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                className={`flex-1 rounded-lg py-2 text-xs font-semibold transition-all ${
                  activeTab === tab.id
                    ? 'bg-white shadow-sm text-gray-900'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* ── Actions tab ── */}
          {activeTab === 'actions' && (
            <div className="space-y-4">
              {/* Filters */}
              <div className="flex flex-wrap gap-2">
                {/* Dimension filter */}
                <div className="flex flex-wrap gap-1.5">
                  <button
                    onClick={() => setActiveDimension(null)}
                    className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-all ${
                      !activeDimension ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 text-gray-500 hover:border-gray-300'
                    }`}
                  >
                    All
                  </button>
                  {Object.entries(DIMENSION_META).map(([k, d]) => {
                    const count = dimensionCounts[k]
                    if (!count) return null
                    const Icon = d.icon
                    return (
                      <button
                        key={k}
                        onClick={() => setActiveDimension(activeDimension === k ? null : k)}
                        className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-all ${
                          activeDimension === k
                            ? `border-transparent ${d.bg} ${d.color}`
                            : 'border-gray-200 text-gray-500 hover:border-gray-300'
                        }`}
                      >
                        <Icon className="h-3 w-3" />
                        {d.label.split('/')[0].trim()} ({count})
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Period filter */}
              <div className="flex gap-1.5 overflow-x-auto pb-0.5">
                <button
                  onClick={() => setActivePeriod(null)}
                  className={`shrink-0 rounded-full border px-3 py-1 text-[11px] font-medium transition-all ${
                    !activePeriod ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 text-gray-500 hover:border-gray-300'
                  }`}
                >
                  All periods
                </button>
                {PERIOD_ORDER.map(p => {
                  const count = periodCounts[p]
                  if (!count) return null
                  return (
                    <button
                      key={p}
                      onClick={() => setActivePeriod(activePeriod === p ? null : p)}
                      className={`shrink-0 flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-medium transition-all ${
                        activePeriod === p
                          ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
                          : 'border-gray-200 text-gray-500 hover:border-gray-300'
                      }`}
                    >
                      <Calendar className="h-3 w-3" />
                      {p} ({count})
                    </button>
                  )
                })}
              </div>

              {/* Action cards by period */}
              {(activePeriod ? [activePeriod] : PERIOD_ORDER).map(period => {
                const periodActions = filteredActions.filter(a => a.period === period)
                if (!periodActions.length) return null
                return (
                  <div key={period}>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-2">
                      <Calendar className="h-3.5 w-3.5" />
                      {period} — {periodActions.length} action{periodActions.length !== 1 ? 's' : ''}
                    </h3>
                    <div className="space-y-2">
                      {periodActions.map(a => <ActionCard key={a.id} action={a} />)}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* ── CRM tab ── */}
          {activeTab === 'crm' && (
            <div className="space-y-3">
              {!plan.crm_sequences?.length && (
                <p className="text-sm text-gray-500 py-8 text-center">No CRM sequences in this plan.</p>
              )}
              {(plan.crm_sequences ?? []).map((seq, i) => (
                <CRMSequenceCard key={i} seq={seq} />
              ))}
            </div>
          )}

          {/* ── Product brief tab ── */}
          {activeTab === 'product' && plan.product_brief && (
            <div className="rounded-2xl border border-orange-200 bg-orange-50 p-5 space-y-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-orange-500">
                  <Package className="h-5 w-5 text-white" />
                </div>
                <div>
                  <p className="text-sm font-bold text-gray-900">Product Strategy Brief</p>
                  <p className="text-xs text-orange-700">Based on competitor analysis and market gaps</p>
                </div>
              </div>
              <div className="rounded-xl bg-white border border-orange-100 p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-orange-600 mb-1.5">
                  🔥 Hero Feature Recommendation
                </p>
                <p className="text-sm font-semibold text-gray-900">{plan.product_brief.hero_feature_recommendation}</p>
              </div>
              <div className="rounded-xl bg-white border border-orange-100 p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-orange-600 mb-1.5">Why This Feature</p>
                <p className="text-sm text-gray-700 leading-relaxed">{plan.product_brief.rationale}</p>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-white border border-orange-100 p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-orange-600 mb-1.5">Positioning Angle</p>
                  <p className="text-sm text-gray-700 leading-relaxed">{plan.product_brief.positioning_angle}</p>
                </div>
                <div className="rounded-xl bg-white border border-orange-100 p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-orange-600 mb-1.5">Pricing Suggestion</p>
                  <p className="text-sm text-gray-700 leading-relaxed">{plan.product_brief.pricing_suggestion}</p>
                </div>
              </div>
              {plan.product_brief.implementation_steps && (
                <div className="rounded-xl bg-white border border-orange-100 p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-orange-600 mb-1.5">Implementation Steps</p>
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {plan.product_brief.implementation_steps}
                  </pre>
                </div>
              )}
            </div>
          )}
          {activeTab === 'product' && !plan.product_brief && (
            <p className="text-sm text-gray-500 py-8 text-center">No product brief in this plan.</p>
          )}
        </>
      )}

      {/* ── Failed state ── */}
      {job.status === 'failed' && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-800">Strategy generation failed</p>
            <p className="text-xs text-red-600 mt-0.5">Check the terminal log above for details. You can try again.</p>
          </div>
        </div>
      )}

      {/* ── Cancelled state ── */}
      {job.status === 'cancelled' && (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 flex items-start gap-3">
          <X className="h-5 w-5 text-gray-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-gray-700">Strategy generation stopped</p>
            <p className="text-xs text-gray-500 mt-0.5">Job was cancelled. Click Generate Strategy to start a new run.</p>
          </div>
        </div>
      )}

      {/* ── Empty state (no job yet) ── */}
      {job.status === 'none' && !isRunning && (
        <div className="rounded-2xl border-2 border-dashed border-amber-200 bg-amber-50/50 py-12 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-500 mx-auto mb-4">
            <Sparkles className="h-7 w-7 text-white" />
          </div>
          <p className="text-base font-bold text-gray-900 mb-1">No strategy yet</p>
          <p className="text-sm text-gray-500 mb-5 max-w-sm mx-auto">
            Set your strategic directive above and click Generate Strategy.
            ARIA will gather data from all connected channels and build a complete 90-day playbook.
          </p>
          <button
            onClick={startJob}
            disabled={starting}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-6 py-3 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
          >
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Generate My First Strategy
          </button>
        </div>
      )}

      {/* ── History Modal ── */}
      {showHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setShowHistory(false)}>
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <p className="text-sm font-bold text-gray-900">Strategy History</p>
              <button onClick={() => setShowHistory(false)} className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors">
                <X className="h-4 w-4 text-gray-400" />
              </button>
            </div>
            <div className="p-4 space-y-2 max-h-96 overflow-y-auto">
              {!history.length && <p className="text-sm text-gray-500 py-4 text-center">No history found.</p>}
              {history.map(h => (
                <button
                  key={h.plan_id}
                  onClick={() => loadHistoryPlan(h.plan_id)}
                  disabled={!!loadingHistoryPlan}
                  className="w-full flex items-center gap-3 rounded-xl border border-gray-200 p-3 text-left hover:border-amber-200 hover:bg-amber-50/50 transition-all"
                >
                  {loadingHistoryPlan === h.plan_id
                    ? <Loader2 className="h-4 w-4 animate-spin text-amber-500 shrink-0" />
                    : <History className="h-4 w-4 text-gray-400 shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-gray-800">
                      {h.strategy_mode || 'custom'} · {h.action_count ?? 0} actions
                    </p>
                    <p className="text-[11px] text-gray-500">{formatDT(h.generated_at)}</p>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
