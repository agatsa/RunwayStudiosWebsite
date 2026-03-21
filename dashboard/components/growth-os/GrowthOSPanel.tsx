'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  RefreshCw, CheckCircle2, AlertTriangle, Sparkles,
  Youtube, Megaphone, BarChart2, Globe, Target, Zap, Rocket,
  TrendingUp, Calendar, Pencil, X, ChevronRight,
  Loader2, CheckCircle, Circle, Link2, ExternalLink, ArrowRight,
} from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { cn } from '@/lib/utils'
import BoldText from '@/components/ui/BoldText'

// ── Types ──────────────────────────────────────────────────────────────────────

interface GrowthAction {
  id: string
  platform: 'youtube' | 'meta' | 'google' | 'all'
  action_type: 'new_creative' | 'create_campaign' | 'keyword_addition' | 'review'
  title: string
  rationale: string
  source: string
  source_detail: string
  impact: 'high' | 'medium' | 'low'
  effort: 'low' | 'medium' | 'high'
  creative_brief?: string
  setup_guide?: string
  done?: boolean
  action_data?: Record<string, unknown>
}

interface GrowthOSPlan {
  plan_id: string | null
  generated_at: string | null
  actions: GrowthAction[]
  sources_used: Record<string, boolean>
  directive?: string
  strategy_mode?: string
  relevant_modules?: string[]
}

interface Props {
  workspaceId: string
  initialPlan?: GrowthOSPlan | null
}

// ── Strategy modes ─────────────────────────────────────────────────────────────

const STRATEGY_MODES = [
  {
    id: 'scale',
    label: 'Scale',
    icon: Rocket,
    color: 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100',
    selectedColor: 'border-blue-500 bg-blue-600 text-white',
    description: 'Maximise installs, reach, and revenue. Aggressive spend.',
    defaultDirective: 'Focus on maximising growth at scale — increase ad spend, expand reach to new audiences, launch new campaigns across all channels, and double down on whatever is currently working. Prioritise volume over efficiency.',
  },
  {
    id: 'efficiency',
    label: 'Efficiency',
    icon: Zap,
    color: 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100',
    selectedColor: 'border-amber-500 bg-amber-600 text-white',
    description: 'Reduce CPA/CAC, cut waste, optimise ROAS.',
    defaultDirective: 'Focus on improving efficiency — reduce cost per acquisition, cut underperforming ad sets, improve ROAS across Meta and Google, and optimise bids. Every action should reduce waste or improve unit economics.',
  },
  {
    id: 'launch',
    label: 'Product Launch',
    icon: TrendingUp,
    color: 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100',
    selectedColor: 'border-green-500 bg-green-600 text-white',
    description: 'Drive awareness + demand for a new product or feature.',
    defaultDirective: 'We are launching a new product. Focus all actions on building awareness, generating early demand, and capturing high-intent buyers. Prioritise top-of-funnel content, launch campaigns, and keyword capturing for the new product.',
  },
  {
    id: 'seasonal',
    label: 'Seasonal Push',
    icon: Calendar,
    color: 'border-pink-200 bg-pink-50 text-pink-700 hover:bg-pink-100',
    selectedColor: 'border-pink-500 bg-pink-600 text-white',
    description: 'Capitalise on an upcoming event, season, or sale.',
    defaultDirective: 'We have an upcoming seasonal event or sale. Focus all actions on capitalising on this window — create seasonal creatives, build urgency campaigns, push high-velocity content before the event, and prepare remarketing audiences.',
  },
  {
    id: 'custom',
    label: 'Custom',
    icon: Pencil,
    color: 'border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100',
    selectedColor: 'border-purple-500 bg-purple-600 text-white',
    description: 'Write your own strategic directive.',
    defaultDirective: '',
  },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

const PLATFORM_ICONS: Record<string, React.ElementType> = {
  youtube: Youtube,
  meta: Megaphone,
  google: BarChart2,
  all: Globe,
}

const PLATFORM_COLORS: Record<string, string> = {
  youtube: 'bg-red-100 text-red-700',
  meta: 'bg-blue-100 text-blue-700',
  google: 'bg-green-100 text-green-700',
  all: 'bg-purple-100 text-purple-700',
}

const IMPACT_DOTS: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-400',
  low: 'bg-slate-400',
}

const EFFORT_LABELS: Record<string, string> = {
  low: 'Easy',
  medium: 'Medium effort',
  high: 'High effort',
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  new_creative: '✨ New Creative',
  create_campaign: '🚀 Campaign',
  keyword_addition: '# Keywords',
  review: '👁 Review',
}

const SOURCE_LABELS: Record<string, string> = {
  yt_competitor_intel: 'YT Intel',
  meta_performance: 'Meta',
  google_ads: 'Google Ads',
  search_trends: 'Search',
  comment_intel: 'Comments',
  all: 'All Sources',
}

const MODE_ICONS: Record<string, React.ElementType> = {
  scale: Rocket,
  efficiency: Zap,
  launch: TrendingUp,
  seasonal: Calendar,
  custom: Pencil,
}

const MODE_COLORS: Record<string, string> = {
  scale: 'bg-blue-100 text-blue-700',
  efficiency: 'bg-amber-100 text-amber-700',
  launch: 'bg-green-100 text-green-700',
  seasonal: 'bg-pink-100 text-pink-700',
  custom: 'bg-purple-100 text-purple-700',
}

// ── Setup Checklist (workspace-type-aware) ─────────────────────────────────

interface SetupStep {
  id: string
  title: string
  description: string
  actionLabel: string
  actionHref?: string
  actionKey?: string   // used to check if already connected
  wsTypes: string[]    // which workspace types see this step
}

const SETUP_STEPS: SetupStep[] = [
  {
    id: 'youtube',
    title: 'Connect YouTube Channel',
    description: 'Pull video analytics, comments, and run competitor intelligence.',
    actionLabel: 'Connect YouTube',
    actionHref: '/settings',
    actionKey: 'youtube',
    wsTypes: ['creator', 'd2c', 'saas', 'agency'],
  },
  {
    id: 'shopify',
    title: 'Connect Shopify Store',
    description: 'Sync your product catalog for AI-powered campaign briefs.',
    actionLabel: 'Connect Shopify',
    actionHref: '/settings',
    actionKey: 'shopify',
    wsTypes: ['d2c'],
  },
  {
    id: 'app_growth',
    title: 'Set Up App Growth / ASO',
    description: 'Track keyword ranks, pull reviews, and reply from the dashboard.',
    actionLabel: 'Go to App Growth',
    actionHref: '/app-growth',
    wsTypes: ['saas'],
  },
  {
    id: 'google_upload',
    title: 'Upload Google Ads Report',
    description: 'Upload an Excel export from Google Ads to unlock campaign analysis.',
    actionLabel: 'Upload Report',
    actionHref: '/google-ads',
    wsTypes: ['d2c', 'saas', 'agency'],
  },
  {
    id: 'competitor_yt',
    title: 'Run YouTube Competitor Analysis',
    description: 'ARIA discovers your top competitors and analyses what makes them win.',
    actionLabel: 'Start Analysis',
    actionHref: '/youtube',
    wsTypes: ['creator'],
  },
  {
    id: 'meta',
    title: 'Meta Ads (Facebook & Instagram)',
    description: 'API approval in progress — you\'ll be notified when live connection is ready.',
    actionLabel: 'Coming Soon',
    wsTypes: ['d2c', 'saas', 'agency', 'creator'],
  },
  {
    id: 'seo',
    title: 'Connect Google Search Console',
    description: 'Track organic search performance and brand keyword lift.',
    actionLabel: 'Go to SEO',
    actionHref: '/seo',
    wsTypes: ['d2c', 'saas'],
  },
]

function timeAgo(isoStr: string | null): string {
  if (!isoStr) return 'never'
  const ms = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// ── ARIA Generating Overlay ────────────────────────────────────────────────────

function StarCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let animId: number
    const stars: { x: number; y: number; r: number; speed: number; opacity: number }[] = []
    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)
    for (let i = 0; i < 120; i++) {
      stars.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.3,
        speed: Math.random() * 0.4 + 0.1,
        opacity: Math.random() * 0.7 + 0.3,
      })
    }
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      stars.forEach(s => {
        s.opacity += (Math.random() - 0.5) * 0.05
        s.opacity = Math.max(0.1, Math.min(1, s.opacity))
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255,255,255,${s.opacity})`
        ctx.fill()
        s.y -= s.speed
        if (s.y < -5) { s.y = canvas.height + 5; s.x = Math.random() * canvas.width }
      })
      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(animId); window.removeEventListener('resize', resize) }
  }, [])
  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
}

function ARIAGeneratingOverlay() {
  return (
    <div className="fixed inset-0 z-[9998] bg-gradient-to-br from-gray-950 via-indigo-950 to-purple-950 flex items-center justify-center">
      <StarCanvas />
      <div className="relative z-10 text-center px-6 max-w-md">
        <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-white/10 backdrop-blur-sm mx-auto mb-6 border border-white/20">
          <Sparkles className="h-10 w-10 text-amber-400 animate-pulse" />
        </div>
        <h2 className="text-2xl font-bold text-white mb-3">ARIA is building your strategy</h2>
        <p className="text-white/60 text-sm leading-relaxed mb-6">
          Scanning your brand, discovering competitors, and synthesising a personalised growth plan across all channels…
        </p>
        <div className="flex items-center justify-center gap-2 text-white/40 text-xs">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          This takes about 30–60 seconds
        </div>
        <div className="mt-8 flex flex-col gap-2 text-left">
          {['Analysing competitor intelligence…', 'Scanning search trends…', 'Synthesising growth actions…'].map((msg, i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg bg-white/5 border border-white/10 px-4 py-2">
              <div className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" style={{ animationDelay: `${i * 0.4}s` }} />
              <span className="text-white/50 text-xs">{msg}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Strategy Directive Modal ───────────────────────────────────────────────────

function StrategyDirectiveModal({
  currentDirective,
  currentMode,
  onConfirm,
  onCancel,
}: {
  currentDirective: string
  currentMode: string
  onConfirm: (directive: string, mode: string) => void
  onCancel: () => void
}) {
  const [selectedMode, setSelectedMode] = useState(currentMode || '')
  const [directive, setDirective] = useState(currentDirective || '')

  const handleModeSelect = (mode: typeof STRATEGY_MODES[number]) => {
    setSelectedMode(mode.id)
    // Pre-fill directive from mode default, but only if user hasn't typed something custom
    if (mode.id !== 'custom') {
      setDirective(mode.defaultDirective)
    } else if (!directive) {
      setDirective('')
    }
  }

  const canConfirm = true // directive is optional — can generate without one

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-amber-500" />
            <h2 className="text-base font-bold text-gray-900">Set Strategic Directive</h2>
          </div>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <p className="text-sm text-gray-600">
            Tell the AI what you want the growth strategy to focus on.
            Claude will shape all 12–15 actions to serve your directive — weighting channels,
            priorities, and action types accordingly.
          </p>

          {/* Mode cards */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">
              Choose a strategy mode
            </p>
            <div className="grid grid-cols-5 gap-2">
              {STRATEGY_MODES.map(mode => {
                const Icon = mode.icon
                const isSelected = selectedMode === mode.id
                return (
                  <button
                    key={mode.id}
                    onClick={() => handleModeSelect(mode)}
                    className={cn(
                      'flex flex-col items-center gap-2 rounded-xl border-2 p-3 text-center transition-all',
                      isSelected ? mode.selectedColor : mode.color,
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    <span className="text-xs font-semibold leading-tight">{mode.label}</span>
                  </button>
                )
              })}
            </div>
            {selectedMode && (
              <p className="mt-2 text-xs text-gray-500 text-center">
                {STRATEGY_MODES.find(m => m.id === selectedMode)?.description}
              </p>
            )}
          </div>

          {/* Directive text area */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                Strategic directive
                <span className="ml-1 normal-case font-normal text-gray-400">(optional — edit or write your own)</span>
              </p>
              {directive && (
                <button onClick={() => setDirective('')} className="text-xs text-gray-400 hover:text-gray-600">
                  Clear
                </button>
              )}
            </div>
            <textarea
              value={directive}
              onChange={e => setDirective(e.target.value)}
              rows={4}
              placeholder="e.g. Focus on reducing CPA below ₹200 for SanketLife ECG targeting cardiologists in metro cities. Prioritise Google UAC and YouTube over Meta which has been underperforming this month..."
              className="w-full rounded-xl border border-gray-200 px-4 py-3 text-sm text-gray-700 outline-none focus:border-amber-400 resize-none placeholder:text-gray-300"
            />
            <p className="mt-1 text-right text-[10px] text-gray-400">{directive.length} chars</p>
          </div>

          {/* No directive note */}
          {!directive.trim() && (
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-xs text-gray-500">
              No directive set — AI will generate a balanced strategy based on all available data signals.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-6 py-4 flex items-center justify-between gap-4">
          <button onClick={onCancel}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={() => onConfirm(directive.trim(), selectedMode)}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-400 transition-colors"
          >
            <Sparkles className="h-4 w-4" />
            Generate Strategy
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Source Badges ──────────────────────────────────────────────────────────────

function SourceBadges({ sources }: { sources: Record<string, boolean> }) {
  const SOURCE_DISPLAY: [string, string][] = [
    ['yt_competitor_intel', 'YouTube Intel'],
    ['meta_performance', 'Meta'],
    ['google_ads', 'Google'],
    ['yt_growth_recipe', 'Growth Recipe'],
    ['competitor_auction', 'Auction Intel'],
    ['search_trends', 'Search Trends'],
    ['comment_intel', 'Comments'],
  ]

  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {SOURCE_DISPLAY.map(([key, label]) => {
        const has = sources[key]
        return (
          <span
            key={key}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium border',
              has
                ? 'bg-green-50 text-green-700 border-green-200'
                : 'bg-gray-50 text-gray-400 border-gray-200',
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', has ? 'bg-green-500' : 'bg-gray-300')} />
            {label}
          </span>
        )
      })}
    </div>
  )
}

// ── Action Card ────────────────────────────────────────────────────────────────

function ActionCard({
  action,
  done,
  onMarkDone,
}: {
  action: GrowthAction
  done: boolean
  onMarkDone: (action: GrowthAction, done: boolean) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const PlatformIcon = PLATFORM_ICONS[action.platform] ?? Globe
  const hasBrief = !!(action.creative_brief || action.setup_guide)

  return (
    <div className={cn("rounded-xl border bg-white shadow-sm hover:shadow-md transition-all", done && "opacity-60")}>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className={cn('inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', PLATFORM_COLORS[action.platform])}>
                <PlatformIcon className="h-3 w-3" />
                {action.platform.toUpperCase()}
              </span>
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600 font-medium">
                {ACTION_TYPE_LABELS[action.action_type] ?? action.action_type}
              </span>
              {done && (
                <span className="inline-flex items-center gap-1 rounded-md bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-700">
                  <CheckCircle2 className="h-3 w-3" /> Done
                </span>
              )}
            </div>

            <h3 className={cn("text-sm font-semibold text-gray-900 leading-tight mb-1.5", done && "line-through")}>
              <BoldText text={action.title} />
            </h3>

            <p className="text-xs text-gray-600 leading-relaxed mb-2">
              <BoldText text={action.rationale} />
            </p>

            {action.source_detail && (
              <p className="text-[11px] text-gray-400 mb-2">
                📍 {SOURCE_LABELS[action.source] ?? action.source} — {action.source_detail}
              </p>
            )}

            <p className="text-[11px] text-gray-500">
              Effort: <span className="font-medium text-gray-700">{EFFORT_LABELS[action.effort] ?? action.effort}</span>
            </p>
          </div>

          <div className="shrink-0 flex flex-col items-end gap-2">
            <button
              onClick={() => onMarkDone(action, !done)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors",
                done
                  ? "bg-green-50 text-green-700 border border-green-200 hover:bg-green-100"
                  : "bg-gray-900 text-white hover:bg-gray-700"
              )}
            >
              {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
              {done ? 'Done' : 'Mark Done'}
            </button>
            {hasBrief && (
              <button
                onClick={() => setExpanded(e => !e)}
                className="inline-flex items-center gap-1 text-[11px] text-indigo-600 hover:text-indigo-800 font-medium"
              >
                {expanded ? 'Hide brief' : 'View brief'}
                <ChevronRight className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Expandable creative brief + setup guide */}
      {expanded && hasBrief && (
        <div className="border-t border-gray-100 bg-gray-50 rounded-b-xl p-4 space-y-4">
          {action.creative_brief && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 mb-2">✨ Creative Brief</p>
              <div className="text-xs text-gray-700 leading-relaxed whitespace-pre-line bg-white rounded-lg border border-gray-200 px-3 py-2.5">
                {action.creative_brief}
              </div>
            </div>
          )}
          {action.setup_guide && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-green-600 mb-2">📋 Setup Guide</p>
              <div className="text-xs text-gray-700 leading-relaxed whitespace-pre-line bg-white rounded-lg border border-gray-200 px-3 py-2.5">
                {action.setup_guide}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Impact Section ─────────────────────────────────────────────────────────────

function ImpactSection({
  impact, actions, doneIds, onMarkDone,
}: {
  impact: 'high' | 'medium' | 'low'
  actions: GrowthAction[]
  doneIds: Set<string>
  onMarkDone: (action: GrowthAction, done: boolean) => void
}) {
  if (actions.length === 0) return null
  const labels = { high: 'HIGH IMPACT', medium: 'MEDIUM IMPACT', low: 'LOW IMPACT' }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={cn('h-2 w-2 rounded-full shrink-0', IMPACT_DOTS[impact])} />
        <span className="text-[11px] font-bold uppercase tracking-widest text-gray-500">{labels[impact]}</span>
        <div className="flex-1 h-px bg-gray-100" />
        <span className="text-[11px] text-gray-400">{actions.length} action{actions.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="space-y-3">
        {actions.map(a => (
          <ActionCard key={a.id} action={a} done={doneIds.has(a.id)} onMarkDone={onMarkDone} />
        ))}
      </div>
    </div>
  )
}

// ── Setup Checklist ────────────────────────────────────────────────────────

function SetupChecklist({ workspaceId, wsType, connections }: {
  workspaceId: string
  wsType: string
  connections: string[]   // list of connected platform keys
}) {
  const steps = SETUP_STEPS.filter(s => s.wsTypes.includes(wsType))
  const allDone = steps.every(s => !s.actionKey || connections.includes(s.actionKey) || s.id === 'meta')

  if (allDone) return null

  return (
    <div className="rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-purple-50 p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-900">ARIA Setup Checklist</h3>
          <p className="text-xs text-gray-500">Complete these to unlock your full intelligence brief</p>
        </div>
      </div>
      <div className="space-y-2">
        {steps.map(step => {
          const done = step.actionKey ? connections.includes(step.actionKey) : (step.id === 'meta')
          const isComingSoon = step.id === 'meta'
          return (
            <div key={step.id} className={`flex items-center gap-3 rounded-xl px-4 py-3 ${
              done ? 'bg-green-50 border border-green-200' : 'bg-white border border-gray-200'
            }`}>
              {done
                ? <CheckCircle className="h-5 w-5 text-green-500 shrink-0" />
                : <Circle className="h-5 w-5 text-gray-300 shrink-0" />}
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-semibold ${done ? 'text-green-800 line-through opacity-60' : 'text-gray-800'}`}>
                  {step.title}
                </p>
                <p className="text-xs text-gray-500 leading-tight">{step.description}</p>
              </div>
              {!done && (
                isComingSoon ? (
                  <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-400 font-medium">
                    Coming Soon
                  </span>
                ) : step.actionHref ? (
                  <a
                    href={`${step.actionHref}?ws=${workspaceId}`}
                    className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
                  >
                    {step.actionLabel}
                    <ArrowRight className="h-3 w-3" />
                  </a>
                ) : null
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main Panel ─────────────────────────────────────────────────────────────────

export default function GrowthOSPanel({ workspaceId, initialPlan }: Props) {
  const [plan, setPlan] = useState<GrowthOSPlan | null>(initialPlan ?? null)
  const [generating, setGenerating] = useState(false)
  const [doneIds, setDoneIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [showDirectiveModal, setShowDirectiveModal] = useState(false)
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  const searchParams = useSearchParams()
  const isWelcome = searchParams.get('welcome') === '1'
  const [wsType, setWsType] = useState<string>('d2c')
  const [connections, setConnections] = useState<string[]>([])
  const [autoPolling, setAutoPolling] = useState(isWelcome && !initialPlan?.plan_id)
  const autoRef = useRef<NodeJS.Timeout | null>(null)

  const fetchLatest = useCallback(async () => {
    try {
      const res = await fetch(`/api/growth-os/latest?workspace_id=${workspaceId}`, { cache: 'no-store' })
      if (!res.ok) return
      const data: GrowthOSPlan = await res.json()
      setPlan(data)
      return data
    } catch {
      return null
    }
  }, [workspaceId])

  useEffect(() => {
    if (!initialPlan || !initialPlan.plan_id) {
      fetchLatest()
    }
  }, [initialPlan, fetchLatest])

  // Initialize doneIds from plan actions that have done=true
  useEffect(() => {
    if (plan?.actions) {
      const ids = new Set(plan.actions.filter(a => a.done).map(a => a.id))
      setDoneIds(ids)
    }
  }, [plan])

  // Fetch workspace type + connections
  useEffect(() => {
    if (!workspaceId) return
    fetch(`/api/workspace?workspace_id=${workspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.workspace_type) setWsType(d.workspace_type) })
      .catch(() => {})
    fetch(`/api/settings?ws=${workspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.connections) {
          const connected = (d.connections as {platform: string, has_token: boolean}[])
            .filter(c => c.has_token).map(c => c.platform)
          setConnections(connected)
        }
      })
      .catch(() => {})
  }, [workspaceId])

  // Auto-poll for first plan when welcome=1 and no plan yet
  // Also triggers generation immediately if no plan exists yet
  useEffect(() => {
    if (!autoPolling) return

    // Trigger generation immediately (fire and forget)
    fetch('/api/growth-os/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId }),
    }).catch(() => {})

    // Poll for the result — keep polling until plan arrives
    autoRef.current = setInterval(async () => {
      const data = await fetchLatest()
      if (data?.plan_id) {
        setAutoPolling(false)
        if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null }
      }
    }, 4000)

    // 120s timeout — only hide overlay, keep polling in background via startPolling
    const timeout = setTimeout(() => {
      setAutoPolling(false)
      // Don't stop the interval — keep polling silently for another 60s
      const fallbackTimeout = setTimeout(() => {
        if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null }
        // One final fetch to catch any late plan
        fetchLatest()
      }, 60000)
      return () => clearTimeout(fallbackTimeout)
    }, 120000)

    return () => {
      if (autoRef.current) clearInterval(autoRef.current)
      clearTimeout(timeout)
    }
  }, [autoPolling, fetchLatest, workspaceId])

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPolling = (prevGeneratedAt: string | null) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      const data = await fetchLatest()
      if (data?.plan_id && data.generated_at !== prevGeneratedAt) {
        stopPolling()
        setGenerating(false)
      }
    }, 3000)
  }

  useEffect(() => () => stopPolling(), [])

  // Open the directive modal when user clicks generate/regenerate
  const handleRegenerateClick = () => {
    setShowDirectiveModal(true)
  }

  // Called when user confirms from modal
  const handleDirectiveConfirm = async (directive: string, strategyMode: string) => {
    setShowDirectiveModal(false)
    setGenerating(true)
    setError(null)
    const prevAt = plan?.generated_at ?? null
    try {
      const res = await fetch('/api/growth-os/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          directive: directive || undefined,
          strategy_mode: strategyMode || undefined,
        }),
      })
      if (res.status === 402) {
        const d = await res.json().catch(() => ({}))
        setError(`Insufficient credits — need ${d.required ?? 10} credits but have ${d.balance ?? 0}. Top up from the Billing page.`)
        setGenerating(false)
        return
      }
      startPolling(prevAt)
    } catch {
      setError('Failed to start generation. Please try again.')
      setGenerating(false)
    }
  }

  const handleMarkDone = async (action: GrowthAction, done: boolean) => {
    // Optimistic update
    setDoneIds(prev => {
      const s = new Set(prev)
      if (done) s.add(action.id)
      else s.delete(action.id)
      return s
    })
    try {
      await fetch('/api/growth-os/mark-done', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, action_id: action.id, done }),
      })
    } catch {
      // silent — optimistic update stays
    }
  }

  const highActions = plan?.actions.filter(a => a.impact === 'high') ?? []
  const mediumActions = plan?.actions.filter(a => a.impact === 'medium') ?? []
  const lowActions = plan?.actions.filter(a => a.impact === 'low') ?? []
  const totalActions = plan?.actions.length ?? 0

  const activeMode = STRATEGY_MODES.find(m => m.id === (plan?.strategy_mode || ''))
  const ActiveModeIcon = activeMode ? activeMode.icon : null

  return (
    <div className="space-y-6">

      {/* ── ARIA Generating Overlay ──────────────────────────────────────────── */}
      {autoPolling && <ARIAGeneratingOverlay />}

      {/* ── Strategy Directive Modal ──────────────────────────────────────────── */}
      {showDirectiveModal && (
        <StrategyDirectiveModal
          currentDirective={plan?.directive ?? ''}
          currentMode={plan?.strategy_mode ?? ''}
          onConfirm={handleDirectiveConfirm}
          onCancel={() => setShowDirectiveModal(false)}
        />
      )}

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <h1 className="text-xl font-bold text-gray-900">Growth OS — Command Center</h1>
          </div>
          {plan?.plan_id ? (
            <p className="text-sm text-gray-500">
              {totalActions} action{totalActions !== 1 ? 's' : ''} ·{' '}
              {highActions.length} High Impact ·{' '}
              Generated {timeAgo(plan.generated_at)}
            </p>
          ) : (
            <p className="text-sm text-gray-400">No plan generated yet</p>
          )}
        </div>
        <button
          onClick={handleRegenerateClick}
          disabled={generating}
          className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-400 disabled:opacity-60 transition-colors"
        >
          <RefreshCw className={cn('h-4 w-4', generating && 'animate-spin')} />
          {generating ? 'Generating…' : plan?.plan_id ? 'Regenerate' : 'Generate'}
          {!generating && <span className="ml-1 rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-semibold">10 cr</span>}
        </button>
      </div>

      {/* ── Active Directive Banner ─────────────────────────────────────────── */}
      {plan?.directive && (
        <div className={cn(
          'rounded-xl border px-4 py-3 flex items-start gap-3',
          plan.strategy_mode ? (MODE_COLORS[plan.strategy_mode] ? 'bg-amber-50 border-amber-200' : 'bg-gray-50 border-gray-200') : 'bg-amber-50 border-amber-200'
        )}>
          <div className={cn('flex h-7 w-7 items-center justify-center rounded-lg shrink-0 mt-0.5',
            plan.strategy_mode && MODE_COLORS[plan.strategy_mode] ? MODE_COLORS[plan.strategy_mode] : 'bg-amber-100 text-amber-700')}>
            {ActiveModeIcon ? <ActiveModeIcon className="h-4 w-4" /> : <Target className="h-4 w-4" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <p className="text-xs font-bold uppercase tracking-wide text-gray-600">
                Active Strategic Directive
              </p>
              {plan.strategy_mode && (
                <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold capitalize',
                  plan.strategy_mode && MODE_COLORS[plan.strategy_mode] ? MODE_COLORS[plan.strategy_mode] : 'bg-gray-100 text-gray-600')}>
                  {plan.strategy_mode}
                </span>
              )}
            </div>
            <p className="text-sm text-gray-700 leading-relaxed">{plan.directive}</p>
          </div>
          <button
            onClick={handleRegenerateClick}
            className="shrink-0 text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1 mt-1"
          >
            <Pencil className="h-3 w-3" /> Edit
          </button>
        </div>
      )}

      {/* ── No directive nudge (when plan exists but no directive) ─────────── */}
      {plan?.plan_id && !plan.directive && !generating && (
        <button
          onClick={handleRegenerateClick}
          className="w-full rounded-xl border-2 border-dashed border-amber-200 bg-amber-50 px-4 py-3 text-left hover:border-amber-300 transition-colors group"
        >
          <div className="flex items-center gap-3">
            <Target className="h-5 w-5 text-amber-400 group-hover:text-amber-600" />
            <div>
              <p className="text-sm font-semibold text-amber-700">Set a Strategic Directive</p>
              <p className="text-xs text-amber-600">Tell AI what to focus on — Scale, Efficiency, Product Launch, Seasonal, or Custom. Makes the plan 10x more relevant.</p>
            </div>
            <ChevronRight className="h-4 w-4 text-amber-400 ml-auto shrink-0" />
          </div>
        </button>
      )}

      {/* ── Source Badges ───────────────────────────────────────────────────── */}
      {plan?.sources_used && Object.keys(plan.sources_used).length > 0 && (
        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Intelligence Sources</p>
          <SourceBadges sources={plan.sources_used} />
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────────────────────── */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-center gap-2 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Generating state ─────────────────────────────────────────────────── */}
      {generating && (
        <div className="rounded-xl border bg-amber-50 border-amber-200 p-6 text-center">
          <RefreshCw className="h-8 w-8 text-amber-500 animate-spin mx-auto mb-3" />
          <p className="text-sm font-semibold text-amber-800">Synthesising all intelligence sources…</p>
          <p className="text-xs text-amber-600 mt-1">Claude is analysing YouTube, Meta, Google, and more. This takes ~30–60 seconds.</p>
        </div>
      )}

      {/* ── Empty state (no plan, not auto-polling) ───────────────────────────── */}
      {!generating && totalActions === 0 && !autoPolling && (
        <div className="rounded-xl border bg-white p-10 text-center">
          <Sparkles className="h-10 w-10 text-amber-300 mx-auto mb-4" />
          <h3 className="text-base font-semibold text-gray-700 mb-2">
            {isWelcome ? 'ARIA is still building your strategy…' : 'No plan generated yet'}
          </h3>
          <p className="text-sm text-gray-500 max-w-md mx-auto mb-4">
            {isWelcome
              ? 'ARIA is generating your personalised strategy in the background. It takes 60–90 seconds. Refresh to check.'
              : <>Set a strategic directive to focus the AI, then click <strong>Generate</strong> to synthesise all intelligence into an action plan.</>
            }
          </p>
          {isWelcome ? (
            <button
              onClick={() => fetchLatest()}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Check for Strategy
            </button>
          ) : (
          <button
            onClick={handleRegenerateClick}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-400 transition-colors"
          >
            <Target className="h-4 w-4" />
            Set Directive & Generate
            <span className="ml-1 rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-semibold">10 cr</span>
          </button>
          )}
        </div>
      )}

      {/* ── Setup Checklist ──────────────────────────────────────────────────── */}
      {!generating && <SetupChecklist workspaceId={workspaceId} wsType={wsType} connections={connections} />}

      {/* ── Action sections ──────────────────────────────────────────────────── */}
      {!generating && totalActions > 0 && (
        <div className="space-y-8">
          <ImpactSection impact="high" actions={highActions} doneIds={doneIds} onMarkDone={handleMarkDone} />
          <ImpactSection impact="medium" actions={mediumActions} doneIds={doneIds} onMarkDone={handleMarkDone} />
          <ImpactSection impact="low" actions={lowActions} doneIds={doneIds} onMarkDone={handleMarkDone} />
        </div>
      )}
    </div>
  )
}
