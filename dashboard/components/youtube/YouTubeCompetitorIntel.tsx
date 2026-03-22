'use client'

import { useState, useEffect, useCallback } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Competitor {
  channel_id: string
  title: string
  handle: string
  subscriber_count: number
  video_count: number
  similarity_score: number | null
  rank: number | null
  source: 'auto' | 'manual'
  last_analyzed_at: string | null
  topic_space?: string[]
}

interface DiscoveryCandidate {
  channel_id: string
  title: string
  handle: string
  subscriber_count: number | null
  similarity_score: number
  confidence_pct: number
  topic_space: string[]
}

interface DiscoveryLogEntry {
  ts: string
  type: 'keyword' | 'channel_found' | 'own_topic_space' | 'info' | 'complete' | 'error'
  msg: string
  data?: unknown
}

interface DiscoveryState {
  has_job: boolean
  job_id: number | null
  discovery_status: 'idle' | 'discovering' | 'awaiting_confirmation' | 'analyzing' | 'completed' | 'error'
  discovery_log: DiscoveryLogEntry[]
  discovery_candidates: DiscoveryCandidate[]
  own_topic_space: string[]
}

interface JobStatus {
  job_id: number | null
  status: 'pending' | 'running' | 'completed' | 'failed' | null
  started_at: string | null
  completed_at: string | null
  channels_analyzed: number
  channels_total: number
  videos_analyzed: number
  error: string | null
  phase: 'competitor_analysis' | 'own_channel_analysis' | 'growth_recipe' | 'completed' | null
}

interface OwnVideo {
  video_id: string
  title: string
  views: number
  velocity: number
  engagement_rate: number
  format_label: string | null
  title_patterns: string[]
  thumb_face: boolean | null
  thumb_emotion: string | null
  thumb_text: boolean | null
  is_short: boolean
  published_at: string | null
}

interface OwnAnalysis {
  has_data: boolean
  not_enough_videos?: boolean
  video_count?: number
  message?: string
  own_avg_velocity?: number
  own_velocity_percentile?: number
  comp_p25?: number
  comp_p50?: number
  comp_p75?: number
  comp_p90?: number
  videos?: OwnVideo[]
}

interface GrowthRecipe {
  has_data: boolean
  not_enough_videos?: boolean
  video_count?: number
  message?: string
  workspace_type?: string
  own_video_count?: number
  own_velocity_avg?: number
  own_velocity_percentile?: number
  content_gaps?: Record<string, unknown>
  plan_15d?: string
  plan_30d?: string
  thumbnail_brief?: string
  hooks_library?: string
  emerging_topics?: string
  recipe_text?: string
  generated_at?: string
}

const WORKSPACE_TYPES = [
  { value: 'd2c',     label: 'D2C Brand',         desc: 'Focus: sales + brand equity growth' },
  { value: 'creator', label: 'Content Creator',    desc: 'Focus: monetisation + subscriber growth' },
  { value: 'saas',    label: 'SaaS / B2B',         desc: 'Focus: thought leadership + leads' },
  { value: 'agency',  label: 'Agency',             desc: 'Focus: case studies + client acquisition' },
  { value: 'media',   label: 'Media / Publisher',  desc: 'Focus: reach + engagement + ad revenue' },
]

interface TopicCluster {
  channel_id: string
  channel_title: string
  topic_cluster_id: number
  topic_name: string
  subthemes: string[]
  cluster_size: number
  avg_velocity: number
  median_velocity: number
  hit_rate: number
  trs_score: number
  shelf_life: 'evergreen' | 'trend' | null
  half_life_weeks: number | null
}

interface FormatRow {
  format_label: string
  avg_velocity: number
  avg_hit_rate: number
  video_count: number
  sample_titles: string[]
}

interface TitlePatternRow {
  pattern: string
  video_count: number
  avg_velocity: number
  uplift_pct: number
}

interface ThumbnailData {
  face_vs_no_face?: {
    face: number
    no_face: number
    face_avg_velocity: number
    no_face_avg_velocity: number
  } | null
  emotion_breakdown?: Array<{ emotion: string; count: number; avg_velocity: number }> | null
  top_combos?: Array<{ face: boolean; text: boolean; emotion: string; avg_velocity: number; count: number }> | null
}

interface RhythmRow {
  channel_id: string
  channel_title: string
  cadence_pattern: string
  median_gap_days: number
  breakout_rate: number
  risk_profile: string
  pre_breakout_momentum: number | null
}

interface LifecycleRow {
  channel_id: string
  channel_title: string
  topic_name: string
  shelf_life: string
  half_life_weeks: number | null
  avg_velocity: number
  cluster_size: number
}

interface ChannelProfile {
  channel_id: string
  channel_title: string
  p25_velocity: number
  p75_velocity: number
  p90_velocity: number
  iqr: number
  std_velocity: number
  hit_rate: number
  underperform_rate: number
  breakout_rate: number
  risk_profile: string
  cadence_pattern: string
  median_gap_days: number
}

interface BreakoutRecipe {
  has_recipe: boolean
  playbook_text: string | null
  top_features: Record<string, number>
  p90_threshold: number | null
  breakout_count: number
  trained_at: string | null
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'overview',     label: 'Overview' },
  { id: 'topics',       label: 'Topic Intelligence' },
  { id: 'formats',      label: 'Format & Title' },
  { id: 'thumbnails',   label: 'Thumbnail DNA' },
  { id: 'rhythm',       label: 'Rhythm & Timing' },
  { id: 'breakout',     label: 'Breakout Recipe' },
  { id: 'my-channel',   label: 'My Channel' },
  { id: 'growth-plan',  label: 'Growth Plan' },
] as const

type TabId = typeof TABS[number]['id']

// How many minutes per channel to estimate remaining time
const MIN_PER_CHANNEL = 3
// Must match YT_INTEL_COMPETITORS in config.py
const TOTAL_COMPETITORS = 5

function fmt(n: number | null | undefined, decimals = 1) {
  if (n == null) return '—'
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals })
}

function fmtK(n: number | null | undefined) {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function etaText(job: JobStatus | null) {
  const phase = job?.phase
  if (phase === 'own_channel_analysis') return '~3 min · analysing your channel'
  if (phase === 'growth_recipe') return '~1 min · writing growth plan'
  const done  = job?.channels_analyzed ?? 0
  const total = job?.channels_total || TOTAL_COMPETITORS
  const remaining = Math.max(0, total - done)
  const mins = remaining * MIN_PER_CHANNEL
  if (mins <= 0) return 'almost done…'
  return `~${mins} min · ${done}/${total} channels`
}

function UpliftBadge({ v }: { v: number }) {
  const pos = v >= 0
  return (
    <span className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-semibold ${pos ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
      {pos ? '▲' : '▼'} {Math.abs(v).toFixed(1)}%
    </span>
  )
}

function RiskBadge({ profile }: { profile: string }) {
  const map: Record<string, string> = {
    low_variance:    'bg-green-50 text-green-700',
    medium_variance: 'bg-yellow-50 text-yellow-700',
    high_variance:   'bg-red-50 text-red-700',
  }
  const cls   = map[profile] ?? 'bg-gray-100 text-gray-600'
  const label = profile === 'low_variance'
    ? 'Very Consistent'
    : profile === 'medium_variance'
    ? 'Moderately Consistent'
    : profile === 'high_variance'
    ? 'Unpredictable'
    : profile.replace(/_/g, ' ')
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
}

function ShelfBadge({ shelf }: { shelf: string | null }) {
  if (!shelf) return <span className="text-gray-300 text-xs">—</span>
  const isEvergreen = shelf === 'evergreen'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${isEvergreen ? 'bg-emerald-50 text-emerald-700' : 'bg-orange-50 text-orange-700'}`}>
      {isEvergreen ? '🌿' : '📈'} {shelf}
    </span>
  )
}

function CadenceBadge({ cadence }: { cadence: string }) {
  const map: Record<string, string> = {
    burst:    'bg-red-50 text-red-700',
    weekly:   'bg-blue-50 text-blue-700',
    biweekly: 'bg-purple-50 text-purple-700',
    monthly:  'bg-gray-100 text-gray-600',
  }
  const cls = map[cadence] ?? 'bg-gray-100 text-gray-600'
  const label = cadence === 'burst' ? 'Burst (daily+)'
    : cadence === 'weekly' ? 'Weekly'
    : cadence === 'biweekly' ? 'Bi-weekly'
    : cadence === 'monthly' ? 'Monthly'
    : cadence
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
}

function EmptyState({ msg }: { msg: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-3 text-4xl opacity-30">📊</div>
      <p className="text-sm font-medium text-gray-500">{msg}</p>
      <p className="mt-1 text-xs text-gray-400">Run an analysis first to populate this section.</p>
    </div>
  )
}

function AnalysisRunningState({ job, customMsg }: { job: JobStatus | null; customMsg?: string }) {
  const phase = job?.phase
  const total = job?.channels_total || TOTAL_COMPETITORS
  const phaseLabel = customMsg
    ?? (phase === 'own_channel_analysis' ? 'Analysing your channel…'
     : phase === 'growth_recipe' ? 'Generating growth recipe…'
     : `${job?.channels_analyzed ?? 0} of ${total} channels complete`)
  return (
    <div className="flex flex-col items-center justify-center py-14 text-center">
      <div className="mb-4 h-12 w-12 rounded-full border-4 border-gray-100 border-t-red-500 animate-spin" />
      <p className="text-sm font-semibold text-gray-700">Analysis in progress</p>
      <p className="mt-1 text-xs text-gray-500">{phaseLabel} · {etaText(job)}</p>
      <p className="mt-3 text-xs text-gray-400">This tab will refresh automatically when done</p>
    </div>
  )
}

function NotEnoughVideos({ count, msg }: { count: number; msg?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-3 text-4xl">📹</div>
      <p className="text-sm font-semibold text-gray-700">
        {msg || `You have ${count} video${count !== 1 ? 's' : ''} — post more to unlock this feature`}
      </p>
      <p className="mt-1 text-xs text-gray-400">At least 5 videos needed for channel comparison & growth plan.</p>
    </div>
  )
}

function CompetitorCard({ c, onRemove, showRemove = true }: { c: Competitor; onRemove: (id: string) => void; showRemove?: boolean }) {
  return (
    <div className="rounded-xl border border-gray-200 p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-gray-900">{c.title || c.channel_id}</p>
          {c.handle && <p className="text-xs text-gray-400 truncate">{c.handle}</p>}
        </div>
        {showRemove && (
          <button
            onClick={() => onRemove(c.channel_id)}
            className="shrink-0 text-gray-300 hover:text-red-500 text-xs"
            title="Remove"
          >
            ✕
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{fmtK(c.subscriber_count)} subs</span>
        {c.similarity_score != null && (
          <>
            <span>·</span>
            <span className="font-medium text-blue-600">{(c.similarity_score * 100).toFixed(0)}% topic match</span>
          </>
        )}
      </div>
      {/* Topic space pills */}
      {c.topic_space && c.topic_space.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {c.topic_space.slice(0, 6).map((kw, i) => (
            <span key={i} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{kw}</span>
          ))}
          {c.topic_space.length > 6 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">+{c.topic_space.length - 6}</span>
          )}
        </div>
      )}
      <div className="flex items-center justify-between text-xs">
        <span className={`rounded-full px-2 py-0.5 font-medium ${c.source === 'auto' ? 'bg-blue-50 text-blue-700' : 'bg-purple-50 text-purple-700'}`}>
          {c.source === 'manual' ? 'Added manually' : 'Auto-discovered'}
        </span>
        {c.last_analyzed_at ? (
          <span className="text-gray-400">
            Analysed {new Date(c.last_analyzed_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
          </span>
        ) : <span className="text-gray-300">Not yet analysed</span>}
      </div>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function YouTubeCompetitorIntel({ workspaceId }: { workspaceId: string }) {
  const [tab, setTab] = useState<TabId>('overview')

  // Data states
  const [competitors, setCompetitors] = useState<Competitor[]>([])
  const [job, setJob]                 = useState<JobStatus | null>(null)
  const [topics, setTopics]           = useState<TopicCluster[]>([])
  const [formats, setFormats]         = useState<FormatRow[]>([])
  const [titlePatterns, setTitlePatterns] = useState<TitlePatternRow[]>([])
  const [thumbnails, setThumbnails]   = useState<ThumbnailData | null>(null)
  const [thumbError, setThumbError]   = useState<string | null>(null)
  const [rhythm, setRhythm]           = useState<RhythmRow[]>([])
  const [lifecycle, setLifecycle]     = useState<LifecycleRow[]>([])
  const [channels, setChannels]       = useState<ChannelProfile[]>([])
  const [recipe, setRecipe]           = useState<BreakoutRecipe | null>(null)
  const [ownAnalysis, setOwnAnalysis] = useState<OwnAnalysis | null>(null)
  const [growthRecipe, setGrowthRecipe] = useState<GrowthRecipe | null>(null)
  const [workspaceType, setWorkspaceType] = useState('d2c')
  const [regenLoading, setRegenLoading] = useState(false)

  // Discovery state (live stream + confirmation step)
  const [discovery, setDiscovery]         = useState<DiscoveryState | null>(null)
  const [confirmedIds, setConfirmedIds]   = useState<string[]>([])
  const [manualUrls, setManualUrls]       = useState<string[]>(['', '', ''])
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [reDiscoverLoading, setReDiscoverLoading] = useState(false)

  // UI states
  const [loading, setLoading]       = useState(false)
  const [analyzing, setAnalyzing]   = useState(false)
  const [addUrl, setAddUrl]         = useState('')
  const [addLoading, setAddLoading] = useState(false)
  const [addError, setAddError]     = useState('')

  // ── Fetch helpers ──────────────────────────────────────────────────────────

  const get = useCallback(async (path: string) => {
    try {
      const r = await fetch(`/api/youtube/competitor-intel/${path}?workspace_id=${workspaceId}`, { cache: 'no-store' })
      if (!r.ok) return null
      return r.json()
    } catch {
      return null
    }
  }, [workspaceId])

  const loadDiscovery = useCallback(async () => {
    const d = await get('discovery-status')
    if (d) {
      setDiscovery(d)
      // When awaiting_confirmation, pre-select all candidates
      if (d.discovery_status === 'awaiting_confirmation' && d.discovery_candidates?.length) {
        setConfirmedIds(d.discovery_candidates.map((c: DiscoveryCandidate) => c.channel_id))
      }
      // If analysis is running, trigger the job status poller too
      if (d.discovery_status === 'analyzing') setAnalyzing(true)
    }
  }, [get])

  const loadOverview = useCallback(async () => {
    setLoading(true)
    const [c, s, d] = await Promise.all([get('competitors'), get('status'), get('discovery-status')])
    setCompetitors(c?.competitors ?? [])
    setJob(s)
    if (d) {
      setDiscovery(d)
      if (d.discovery_status === 'awaiting_confirmation' && d.discovery_candidates?.length) {
        setConfirmedIds(d.discovery_candidates.map((c: DiscoveryCandidate) => c.channel_id))
      }
    }
    // Auto-start polling if a job is already running (e.g. after page refresh)
    if (s?.status === 'running') setAnalyzing(true)
    setLoading(false)
  }, [get])

  const loadTopics = useCallback(async () => {
    const d = await get('topics')
    setTopics(d?.clusters ?? [])
  }, [get])

  const loadFormats = useCallback(async () => {
    const [f, t] = await Promise.all([get('formats'), get('title-patterns')])
    setFormats(f?.formats ?? [])
    setTitlePatterns(t?.patterns ?? [])
  }, [get])

  const loadThumbnails = useCallback(async () => {
    setThumbError(null)
    try {
      const d = await get('thumbnails')
      setThumbnails(d ?? null)
    } catch (e) {
      setThumbError('Failed to load thumbnail data')
      setThumbnails(null)
    }
  }, [get])

  const loadRhythm = useCallback(async () => {
    const d = await get('rhythm')
    setRhythm(d?.channels ?? [])
  }, [get])

  const loadLifecycle = useCallback(async () => {
    const d = await get('lifecycle')
    setLifecycle(d?.topics ?? [])
  }, [get])

  const loadChannels = useCallback(async () => {
    const d = await get('channels')
    setChannels(d?.channels ?? [])
  }, [get])

  const loadRecipe = useCallback(async () => {
    const d = await get('breakout-recipe')
    setRecipe(d ?? null)
  }, [get])

  const loadOwnAnalysis = useCallback(async () => {
    const d = await fetch(`/api/youtube/competitor-intel/own-analysis?workspace_id=${workspaceId}`, { cache: 'no-store' })
    const j = d.ok ? await d.json() : null
    setOwnAnalysis(j)
  }, [workspaceId])

  const loadGrowthRecipe = useCallback(async () => {
    const d = await fetch(`/api/youtube/competitor-intel/growth-recipe-v2?workspace_id=${workspaceId}`, { cache: 'no-store' })
    const j = d.ok ? await d.json() : null
    setGrowthRecipe(j)
    if (j?.workspace_type) setWorkspaceType(j.workspace_type)
  }, [workspaceId])

  // ── Tab → data loader map ──────────────────────────────────────────────────

  useEffect(() => {
    if (!workspaceId) return
    if (tab === 'overview')       loadOverview()
    else if (tab === 'topics')      loadTopics()
    else if (tab === 'formats')     loadFormats()
    else if (tab === 'thumbnails')  loadThumbnails()
    else if (tab === 'rhythm')      { loadRhythm(); loadChannels() }
    else if (tab === 'breakout')    { loadRecipe(); loadLifecycle() }
    else if (tab === 'my-channel')  loadOwnAnalysis()
    else if (tab === 'growth-plan') loadGrowthRecipe()
  }, [tab, workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll discovery status during live discovery phase (every 2s)
  useEffect(() => {
    const ds = discovery?.discovery_status
    if (ds !== 'discovering') return
    const iv = setInterval(async () => {
      const d = await get('discovery-status')
      if (d) {
        setDiscovery(d)
        if (d.discovery_status === 'awaiting_confirmation') {
          setConfirmedIds(d.discovery_candidates?.map((c: DiscoveryCandidate) => c.channel_id) ?? [])
          clearInterval(iv)
        }
        if (d.discovery_status === 'error') clearInterval(iv)
      }
    }, 2000)
    return () => clearInterval(iv)
  }, [discovery?.discovery_status, get]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll job status while analysis is running
  useEffect(() => {
    if (!analyzing) return
    const iv = setInterval(async () => {
      const [s, d] = await Promise.all([get('status'), get('discovery-status')])
      setJob(s)
      if (d) setDiscovery(d)
      if (s?.status === 'completed' || s?.status === 'failed') {
        setAnalyzing(false)
        loadOverview()
        // Reload current tab data after completion
        if (tab === 'topics')          loadTopics()
        else if (tab === 'formats')    loadFormats()
        else if (tab === 'thumbnails') loadThumbnails()
        else if (tab === 'rhythm')     { loadRhythm(); loadChannels() }
        else if (tab === 'breakout')   { loadRecipe(); loadLifecycle() }
        else if (tab === 'my-channel') loadOwnAnalysis()
        else if (tab === 'growth-plan') loadGrowthRecipe()
      }
    }, 4000)
    return () => clearInterval(iv)
  }, [analyzing, get, loadOverview, tab]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ────────────────────────────────────────────────────────────────

  async function runAnalysis() {
    // Start discovery phase (Phase 1)
    setDiscovery({ has_job: true, job_id: null, discovery_status: 'discovering', discovery_log: [], discovery_candidates: [], own_topic_space: [] })
    const r = await fetch('/api/youtube/competitor-intel/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId }),
    })
    const d = await r.json()
    setJob({ job_id: d.job_id, status: 'pending', started_at: null, completed_at: null, channels_analyzed: 0, channels_total: TOTAL_COMPETITORS, videos_analyzed: 0, error: null, phase: 'competitor_analysis' })
  }

  async function confirmDiscovery() {
    setConfirmLoading(true)
    const filledUrls = manualUrls.filter(u => u.trim() !== '')
    const r = await fetch('/api/youtube/competitor-intel/confirm-discovery', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: workspaceId,
        confirmed_channel_ids: confirmedIds,
        manual_channel_urls: filledUrls,
      }),
    })
    if (r.ok) {
      const d = await r.json()
      setDiscovery(prev => prev ? { ...prev, discovery_status: 'analyzing' } : prev)
      setJob({ job_id: d.job_id, status: 'running', started_at: null, completed_at: null, channels_analyzed: 0, channels_total: confirmedIds.length + filledUrls.length, videos_analyzed: 0, error: null, phase: 'competitor_analysis' })
      setAnalyzing(true)
    }
    setConfirmLoading(false)
  }

  async function reDiscover() {
    setReDiscoverLoading(true)
    setDiscovery({ has_job: true, job_id: null, discovery_status: 'discovering', discovery_log: [], discovery_candidates: [], own_topic_space: [] })
    setConfirmedIds([])
    setManualUrls(['', '', ''])
    await fetch('/api/youtube/competitor-intel/re-discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId }),
    })
    setReDiscoverLoading(false)
  }

  async function addCompetitor() {
    if (!addUrl.trim()) return
    setAddLoading(true)
    setAddError('')
    const r = await fetch('/api/youtube/competitor-intel/competitors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId, channel_url: addUrl.trim() }),
    })
    const d = await r.json()
    if (!r.ok) {
      setAddError(d.detail ?? 'Failed to add channel')
    } else {
      setAddUrl('')
      loadOverview()
    }
    setAddLoading(false)
  }

  async function removeCompetitor(channelId: string) {
    await fetch('/api/youtube/competitor-intel/competitors', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId, channel_id: channelId }),
    })
    loadOverview()
  }

  async function saveWorkspaceType(type: string) {
    setWorkspaceType(type)
    await fetch('/api/workspace/type', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId, workspace_type: type }),
    })
  }

  async function regenerateRecipe() {
    setRegenLoading(true)
    try {
      await fetch('/api/youtube/competitor-intel/growth-recipe-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      // Poll for completion (~60s)
      let tries = 0
      const iv = setInterval(async () => {
        tries++
        const d = await fetch(`/api/youtube/competitor-intel/growth-recipe-v2?workspace_id=${workspaceId}`, { cache: 'no-store' })
        const j = d.ok ? await d.json() : null
        if (j?.generated_at && j.plan_15d) {
          setGrowthRecipe(j)
          setRegenLoading(false)
          clearInterval(iv)
        }
        if (tries > 20) { setRegenLoading(false); clearInterval(iv) }
      }, 5000)
    } catch {
      setRegenLoading(false)
    }
  }

  const discoveryStatus = discovery?.discovery_status ?? 'idle'
  const isDiscovering = discoveryStatus === 'discovering'
  const isRunning = analyzing || job?.status === 'running' || isDiscovering

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      {/* Section header */}
      <div className="flex items-center gap-3 border-b border-gray-200 bg-gray-50 px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-600">
          <svg viewBox="0 0 24 24" className="h-4 w-4 fill-white">
            <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path fillRule="evenodd" d="M1.323 11.447C2.811 6.976 7.028 3.75 12.001 3.75c4.97 0 9.185 3.223 10.675 7.69.12.362.12.752 0 1.113-1.487 4.471-5.705 7.697-10.677 7.697-4.97 0-9.186-3.223-10.675-7.69a1.762 1.762 0 010-1.113zM17.25 12a5.25 5.25 0 11-10.5 0 5.25 5.25 0 0110.5 0z" clipRule="evenodd" />
          </svg>
        </div>
        <div>
          <h2 className="text-sm font-semibold text-gray-900">YouTube Competitor Intelligence</h2>
          <p className="text-xs text-gray-500">9-layer AI · topics · formats · thumbnails · timing · breakout recipe</p>
        </div>
        {isRunning && (
          <div className="ml-auto flex items-center gap-2 rounded-full bg-yellow-50 border border-yellow-200 px-3 py-1">
            <div className="h-2 w-2 rounded-full bg-yellow-400 animate-pulse" />
            <span className="text-xs font-medium text-yellow-700">
              {isDiscovering ? 'Discovering competitors…' : etaText(job)}
            </span>
          </div>
        )}
        {discoveryStatus === 'awaiting_confirmation' && (
          <div className="ml-auto flex items-center gap-2 rounded-full bg-amber-50 border border-amber-200 px-3 py-1">
            <div className="h-2 w-2 rounded-full bg-amber-400" />
            <span className="text-xs font-medium text-amber-700">Review competitors → Overview tab</span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex overflow-x-auto border-b border-gray-200 bg-white">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`shrink-0 px-4 py-3 text-xs font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'border-red-600 text-red-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-white p-5">

        {/* ── Tab: Overview ─────────────────────────────────────────────── */}
        {tab === 'overview' && (() => {
          const ds = discovery?.discovery_status ?? 'idle'

          // ── State: IDLE — no analysis yet ────────────────────────────────
          // Treat as completed if a previous job finished (legacy: discovery_status NULL → 'idle')
          const hasCompletedJob = job?.status === 'completed' && competitors.length > 0
          if ((ds === 'idle' || !discovery?.has_job) && !hasCompletedJob) {
            return (
              <div className="space-y-5">
                {/* Last run info */}
                {job?.status === 'completed' && (
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="h-2 w-2 rounded-full bg-green-500" />
                    Last analysis: {job.channels_analyzed} channels · {job.videos_analyzed} videos
                    <button onClick={reDiscover} disabled={reDiscoverLoading} className="ml-2 text-blue-600 hover:underline disabled:opacity-40">
                      Re-discover
                    </button>
                  </div>
                )}
                {/* Failed info */}
                {job?.status === 'failed' && (
                  <div className="flex items-center gap-2 text-xs text-red-600">
                    <span className="h-2 w-2 rounded-full bg-red-500" />
                    Last run failed: {job.error ?? 'unknown error'}
                  </div>
                )}

                {/* Start discovery button */}
                <div className="flex flex-col items-center py-12 text-center space-y-4">
                  <div className="w-14 h-14 rounded-full bg-red-50 flex items-center justify-center text-2xl">🔍</div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">Discover Your Competitors</h3>
                    <p className="mt-1 text-xs text-gray-500 max-w-xs mx-auto">
                      AI scans YouTube using your channel's topic fingerprint, shows you what it finds, and lets you confirm before running the 9-layer deep analysis.
                    </p>
                  </div>
                  <button
                    onClick={runAnalysis}
                    className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-red-700 shadow-sm"
                  >
                    Start Competitor Discovery
                  </button>
                  <p className="text-xs text-gray-400">~2 min to discover · then you confirm · then ~15 min for full analysis</p>
                </div>

                {/* Existing competitors (from previous analysis) */}
                {competitors.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Currently Tracked Competitors</h4>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {competitors.map(c => (
                        <CompetitorCard key={c.channel_id} c={c} onRemove={removeCompetitor} />
                      ))}
                    </div>
                    <div className="mt-3 rounded-lg bg-blue-50 border border-blue-100 px-4 py-3 text-xs text-blue-700">
                      Run a new discovery to refresh competitor list with updated topic matching.
                    </div>
                  </div>
                )}
              </div>
            )
          }

          // ── State: DISCOVERING — live log feed ────────────────────────────
          if (ds === 'discovering') {
            const logs = discovery?.discovery_log ?? []
            const ownTopicSpace = discovery?.own_topic_space ?? []
            return (
              <div className="space-y-4">
                {/* Own Topic Space */}
                {ownTopicSpace.length > 0 && (
                  <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <p className="text-xs font-semibold text-blue-700 mb-2">Your Channel's Topic Fingerprint</p>
                    <div className="flex flex-wrap gap-1.5">
                      {ownTopicSpace.map((kw, i) => (
                        <span key={i} className="rounded-full bg-blue-100 border border-blue-200 px-2.5 py-0.5 text-xs font-medium text-blue-800">{kw}</span>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-blue-500">This is what YouTube's algorithm sees as your content niche. Competitors are scored against this fingerprint.</p>
                  </div>
                )}

                {/* Live log */}
                <div className="rounded-xl border border-gray-200 overflow-hidden">
                  <div className="flex items-center gap-2 border-b border-gray-100 bg-gray-50 px-4 py-2.5">
                    <div className="h-2 w-2 rounded-full bg-yellow-400 animate-pulse" />
                    <span className="text-xs font-semibold text-gray-700">Live Discovery Log</span>
                    <span className="ml-auto text-xs text-gray-400">Searching YouTube for competitors…</span>
                  </div>
                  <div className="max-h-72 overflow-y-auto p-3 space-y-1 bg-gray-900 font-mono">
                    {logs.length === 0 && (
                      <p className="text-xs text-gray-500 py-2 text-center">Initialising discovery…</p>
                    )}
                    {logs.map((entry, i) => (
                      <div key={i} className={`text-xs leading-relaxed ${
                        entry.type === 'error'         ? 'text-red-400' :
                        entry.type === 'complete'      ? 'text-green-400 font-semibold' :
                        entry.type === 'channel_found' ? 'text-yellow-300' :
                        entry.type === 'keyword'       ? 'text-blue-300' :
                        entry.type === 'own_topic_space' ? 'text-cyan-300' :
                        'text-gray-400'
                      }`}>
                        <span className="opacity-50 mr-2">{new Date(entry.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                        {entry.type === 'keyword' && <span className="text-gray-500 mr-1">›</span>}
                        {entry.type === 'channel_found' && <span className="text-yellow-500 mr-1">✦</span>}
                        {entry.type === 'complete' && <span className="text-green-500 mr-1">✓</span>}
                        {entry.msg}
                      </div>
                    ))}
                  </div>
                </div>

                <p className="text-xs text-center text-gray-400">Results will appear automatically when discovery completes…</p>
              </div>
            )
          }

          // ── State: AWAITING_CONFIRMATION — candidate cards + confirm ──────
          if (ds === 'awaiting_confirmation') {
            const candidates = discovery?.discovery_candidates ?? []
            const ownTopicSpace = discovery?.own_topic_space ?? []
            return (
              <div className="space-y-5">
                {/* Own Topic Space */}
                {ownTopicSpace.length > 0 && (
                  <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <p className="text-xs font-semibold text-blue-700 mb-2">Your Channel's Topic Fingerprint</p>
                    <div className="flex flex-wrap gap-1.5">
                      {ownTopicSpace.map((kw, i) => (
                        <span key={i} className="rounded-full bg-blue-100 border border-blue-200 px-2.5 py-0.5 text-xs font-medium text-blue-800">{kw}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Instruction */}
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800">
                  <strong>Review found competitors.</strong> Uncheck any that don't belong to your niche. Optionally add up to 3 manual channels. Then click <strong>Confirm & Start Deep Analysis</strong>.
                </div>

                {/* Candidate cards */}
                <div>
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                    Discovered {candidates.length} Competitor{candidates.length !== 1 ? 's' : ''} — select which to analyse
                  </h4>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {candidates.map(c => {
                      const selected = confirmedIds.includes(c.channel_id)
                      return (
                        <div
                          key={c.channel_id}
                          onClick={() => setConfirmedIds(prev =>
                            selected ? prev.filter(id => id !== c.channel_id) : [...prev, c.channel_id]
                          )}
                          className={`cursor-pointer rounded-xl border p-4 space-y-2 transition-all ${
                            selected
                              ? 'border-red-300 bg-red-50 ring-1 ring-red-200'
                              : 'border-gray-200 bg-white opacity-50'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className={`h-4 w-4 rounded border flex-shrink-0 flex items-center justify-center text-xs ${selected ? 'bg-red-600 border-red-600 text-white' : 'border-gray-300'}`}>
                                  {selected ? '✓' : ''}
                                </span>
                                <p className="truncate text-sm font-semibold text-gray-900">{c.title || c.channel_id}</p>
                              </div>
                              {c.handle && <p className="text-xs text-gray-400 truncate mt-0.5 pl-6">{c.handle}</p>}
                            </div>
                            <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${
                              c.confidence_pct >= 70 ? 'bg-green-100 text-green-700' :
                              c.confidence_pct >= 40 ? 'bg-yellow-100 text-yellow-700' :
                              'bg-gray-100 text-gray-500'
                            }`}>{c.confidence_pct}% match</span>
                          </div>

                          <div className="text-xs text-gray-500">
                            {fmtK(c.subscriber_count)} subscribers
                          </div>

                          {c.topic_space?.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {c.topic_space.slice(0, 6).map((kw, i) => (
                                <span key={i} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{kw}</span>
                              ))}
                              {c.topic_space.length > 6 && (
                                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">+{c.topic_space.length - 6} more</span>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Manual channels */}
                <div>
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Add up to 3 manual competitors</h4>
                  <div className="space-y-2">
                    {manualUrls.map((url, i) => (
                      <input
                        key={i}
                        type="text"
                        value={url}
                        onChange={e => setManualUrls(prev => { const n = [...prev]; n[i] = e.target.value; return n })}
                        placeholder={`Channel URL or @handle (optional)`}
                        className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500/30"
                      />
                    ))}
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex flex-wrap items-center gap-3 pt-2">
                  <button
                    onClick={confirmDiscovery}
                    disabled={confirmLoading || confirmedIds.length === 0}
                    className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 shadow-sm"
                  >
                    {confirmLoading ? (
                      <>
                        <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                        Starting analysis…
                      </>
                    ) : `Confirm & Start Deep Analysis (${confirmedIds.length} channel${confirmedIds.length !== 1 ? 's' : ''})`}
                  </button>
                  <button
                    onClick={reDiscover}
                    disabled={reDiscoverLoading}
                    className="text-sm text-gray-500 hover:text-gray-700 underline"
                  >
                    Re-discover instead
                  </button>
                </div>
              </div>
            )
          }

          // ── State: ANALYZING — deep analysis in progress ──────────────────
          if (ds === 'analyzing') {
            return (
              <div className="space-y-4">
                <AnalysisRunningState job={job} />

                {/* Show the confirmed competitor list during analysis */}
                {competitors.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Analysing These Channels</h4>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {competitors.map(c => (
                        <CompetitorCard key={c.channel_id} c={c} onRemove={() => {}} showRemove={false} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Live log during analysis */}
                {(discovery?.discovery_log?.length ?? 0) > 0 && (
                  <div className="rounded-xl border border-gray-200 overflow-hidden">
                    <div className="border-b border-gray-100 bg-gray-50 px-4 py-2.5 text-xs font-semibold text-gray-700">Activity Log</div>
                    <div className="max-h-48 overflow-y-auto p-3 space-y-1 bg-gray-900 font-mono">
                      {(discovery?.discovery_log ?? []).slice(-20).map((entry, i) => (
                        <div key={i} className={`text-xs ${entry.type === 'error' ? 'text-red-400' : entry.type === 'complete' ? 'text-green-400' : 'text-gray-400'}`}>
                          <span className="opacity-40 mr-2">{new Date(entry.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                          {entry.msg}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          }

          // ── State: COMPLETED — show analysed competitor cards ─────────────
          return (
            <div className="space-y-5">
              {/* Status + actions */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  {job?.status === 'completed'
                    ? `Analysis complete: ${job.channels_analyzed} channels · ${job.videos_analyzed} videos`
                    : 'Analysis complete'
                  }
                </div>
                <button
                  onClick={reDiscover}
                  disabled={reDiscoverLoading}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                >
                  {reDiscoverLoading ? '…' : '🔍 Re-discover Competitors'}
                </button>
              </div>

              {/* Competitor cards */}
              {loading ? (
                <p className="text-sm text-gray-400 py-8 text-center">Loading competitors…</p>
              ) : competitors.length === 0 ? (
                <EmptyState msg="No competitors tracked yet." />
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {competitors.map(c => (
                    <CompetitorCard key={c.channel_id} c={c} onRemove={removeCompetitor} />
                  ))}
                </div>
              )}

              {/* Info note */}
              <div className="rounded-lg bg-blue-50 border border-blue-100 px-4 py-3 text-xs text-blue-700">
                <strong>How analysis works:</strong> For each competitor, we fetch 30 recent videos, then select the 6 highest-viewed (what works) + 4 lowest-viewed (what doesn't) for deep AI analysis — giving you both playbook and pitfalls.
              </div>
            </div>
          )
        })()}

        {/* ── Tab: Topic Intelligence ───────────────────────────────────── */}
        {tab === 'topics' && (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <p className="text-xs font-semibold text-emerald-700 mb-1">🌿 Evergreen clusters</p>
                <p className="text-2xl font-bold text-emerald-900">
                  {topics.filter(t => t.shelf_life === 'evergreen').length}
                </p>
                <p className="text-xs text-emerald-600 mt-0.5">Long-term content pillars</p>
              </div>
              <div className="rounded-xl border border-orange-200 bg-orange-50 p-4">
                <p className="text-xs font-semibold text-orange-700 mb-1">📈 Trend clusters</p>
                <p className="text-2xl font-bold text-orange-900">
                  {topics.filter(t => t.shelf_life === 'trend').length}
                </p>
                <p className="text-xs text-orange-600 mt-0.5">Time-sensitive opportunities</p>
              </div>
            </div>

            {topics.length === 0
              ? (isRunning ? <AnalysisRunningState job={job} /> : <EmptyState msg="No topic clusters yet." />)
              : (
              <div className="space-y-3">
                {topics.map((c, i) => (
                  <div key={i} className="rounded-xl border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div>
                        <p className="text-sm font-semibold text-gray-900">{c.topic_name}</p>
                        <p className="text-xs text-gray-400">{c.channel_title}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <ShelfBadge shelf={c.shelf_life ?? null} />
                      </div>
                    </div>

                    {c.subthemes?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {c.subthemes.map((s, j) => (
                          <span key={j} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{s}</span>
                        ))}
                      </div>
                    )}

                    <div className="grid grid-cols-4 gap-2 text-center text-xs">
                      <div className="rounded-lg bg-gray-50 p-2">
                        <p className="font-semibold text-gray-900">{fmt(c.avg_velocity)}</p>
                        <p className="text-gray-400">views/day avg</p>
                      </div>
                      <div className="rounded-lg bg-gray-50 p-2">
                        <p className="font-semibold text-gray-900">{fmt(c.hit_rate * 100)}%</p>
                        <p className="text-gray-400">hit rate</p>
                      </div>
                      <div className="rounded-lg bg-gray-50 p-2">
                        <p className="font-semibold text-gray-900">{c.trs_score}</p>
                        <p className="text-gray-400">recent score</p>
                      </div>
                      <div className="rounded-lg bg-gray-50 p-2">
                        <p className="font-semibold text-gray-900">{c.half_life_weeks ?? '∞'}</p>
                        <p className="text-gray-400">weeks shelf life</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Format & Title ───────────────────────────────────────── */}
        {tab === 'formats' && (
          <div className="space-y-6">
            {/* Format table */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-gray-900">Content Formats — sorted by daily views</h3>
              {formats.length === 0
                ? (isRunning ? <AnalysisRunningState job={job} /> : <EmptyState msg="No format data yet." />)
                : (
                <div className="overflow-x-auto rounded-xl border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                        <th className="px-4 py-3">Format Type</th>
                        <th className="px-4 py-3 text-right">Avg Daily Views</th>
                        <th className="px-4 py-3 text-right">Hit Rate</th>
                        <th className="px-4 py-3 text-right">Videos</th>
                        <th className="px-4 py-3">Example Titles</th>
                      </tr>
                    </thead>
                    <tbody>
                      {formats.map((f, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="px-4 py-3">
                            <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                              {f.format_label.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-semibold text-gray-900">{fmt(f.avg_velocity)}</td>
                          <td className="px-4 py-3 text-right text-gray-600">{fmt(f.avg_hit_rate * 100)}%</td>
                          <td className="px-4 py-3 text-right text-gray-500">{f.video_count}</td>
                          <td className="px-4 py-3">
                            <div className="space-y-0.5">
                              {(f.sample_titles ?? []).slice(0, 2).map((t, j) => (
                                <p key={j} className="truncate text-xs text-gray-500 max-w-[240px]">{t}</p>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Title pattern table */}
            <div>
              <h3 className="mb-1 text-sm font-semibold text-gray-900">Title Patterns — impact vs average</h3>
              <p className="mb-3 text-xs text-gray-400">Green = this pattern boosts views above average · Red = it underperforms</p>
              {titlePatterns.length === 0
                ? (isRunning ? <AnalysisRunningState job={job} /> : <EmptyState msg="No title pattern data yet." />)
                : (
                <div className="overflow-x-auto rounded-xl border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                        <th className="px-4 py-3">Title Pattern</th>
                        <th className="px-4 py-3 text-right">Avg Daily Views</th>
                        <th className="px-4 py-3 text-right">vs Average</th>
                        <th className="px-4 py-3 text-right">Videos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {titlePatterns
                        .sort((a, b) => b.uplift_pct - a.uplift_pct)
                        .map((p, i) => (
                          <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                            <td className="px-4 py-3 font-medium text-gray-800">{p.pattern.replace(/_/g, ' ')}</td>
                            <td className="px-4 py-3 text-right text-gray-700">{fmt(p.avg_velocity)}</td>
                            <td className="px-4 py-3 text-right"><UpliftBadge v={p.uplift_pct} /></td>
                            <td className="px-4 py-3 text-right text-gray-500">{p.video_count}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Tab: Thumbnail DNA ────────────────────────────────────────── */}
        {tab === 'thumbnails' && (
          <div className="space-y-6">
            {thumbError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{thumbError}</div>
            ) : !thumbnails ? (
              isRunning ? <AnalysisRunningState job={job} /> : <EmptyState msg="No thumbnail analysis yet." />
            ) : (
              <>
                {/* Face vs No Face */}
                {thumbnails.face_vs_no_face ? (
                  <div>
                    <h3 className="mb-1 text-sm font-semibold text-gray-900">Face vs No-Face Performance</h3>
                    <p className="mb-3 text-xs text-gray-400">Do thumbnails with a human face get more daily views?</p>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-xl border border-gray-200 p-4 text-center">
                        <p className="text-3xl font-bold text-gray-900">{fmt(thumbnails.face_vs_no_face.face_avg_velocity)}</p>
                        <p className="text-xs text-gray-500 mt-1">👤 With face — avg daily views</p>
                        <p className="text-xs text-gray-400">{thumbnails.face_vs_no_face.face} videos</p>
                      </div>
                      <div className="rounded-xl border border-gray-200 p-4 text-center">
                        <p className="text-3xl font-bold text-gray-900">{fmt(thumbnails.face_vs_no_face.no_face_avg_velocity)}</p>
                        <p className="text-xs text-gray-500 mt-1">🖼️ No face — avg daily views</p>
                        <p className="text-xs text-gray-400">{thumbnails.face_vs_no_face.no_face} videos</p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg bg-gray-50 px-4 py-3 text-xs text-gray-500">Face data not yet available</div>
                )}

                {/* Emotion breakdown */}
                {Array.isArray(thumbnails.emotion_breakdown) && thumbnails.emotion_breakdown.length > 0 ? (
                  <div>
                    <h3 className="mb-1 text-sm font-semibold text-gray-900">Thumbnail Emotion → Daily Views</h3>
                    <p className="mb-3 text-xs text-gray-400">Which facial expression in thumbnails drives the most views?</p>
                    <div className="overflow-x-auto rounded-xl border border-gray-200">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                            <th className="px-4 py-3">Emotion</th>
                            <th className="px-4 py-3 text-right">Avg Daily Views</th>
                            <th className="px-4 py-3 text-right">Videos</th>
                          </tr>
                        </thead>
                        <tbody>
                          {thumbnails.emotion_breakdown
                            .sort((a, b) => b.avg_velocity - a.avg_velocity)
                            .map((e, i) => (
                              <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                                <td className="px-4 py-3 font-medium text-gray-800">{e.emotion || '—'}</td>
                                <td className="px-4 py-3 text-right font-semibold text-gray-900">{fmt(e.avg_velocity)}</td>
                                <td className="px-4 py-3 text-right text-gray-500">{e.count}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg bg-gray-50 px-4 py-3 text-xs text-gray-500">Emotion breakdown not yet available</div>
                )}

                {/* Top combos */}
                {Array.isArray(thumbnails.top_combos) && thumbnails.top_combos.length > 0 && (
                  <div>
                    <h3 className="mb-1 text-sm font-semibold text-gray-900">Winning Thumbnail Combinations</h3>
                    <p className="mb-3 text-xs text-gray-400">Best-performing combos of face + on-screen text + emotion</p>
                    <div className="overflow-x-auto rounded-xl border border-gray-200">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                            <th className="px-4 py-3">Has Face</th>
                            <th className="px-4 py-3">Has Text</th>
                            <th className="px-4 py-3">Emotion</th>
                            <th className="px-4 py-3 text-right">Avg Daily Views</th>
                            <th className="px-4 py-3 text-right">Videos</th>
                          </tr>
                        </thead>
                        <tbody>
                          {thumbnails.top_combos.map((c, i) => (
                            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                              <td className="px-4 py-3 text-center">{c.face ? '✅' : '❌'}</td>
                              <td className="px-4 py-3 text-center">{c.text ? '✅' : '❌'}</td>
                              <td className="px-4 py-3 text-gray-700">{c.emotion || '—'}</td>
                              <td className="px-4 py-3 text-right font-semibold text-gray-900">{fmt(c.avg_velocity)}</td>
                              <td className="px-4 py-3 text-right text-gray-500">{c.count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Tab: Rhythm & Timing ──────────────────────────────────────── */}
        {tab === 'rhythm' && (
          <div className="space-y-6">
            {/* Cadence table */}
            <div>
              <h3 className="mb-1 text-sm font-semibold text-gray-900">Upload Rhythm & Consistency</h3>
              <p className="mb-3 text-xs text-gray-400">How often does each competitor post, and how consistent are they?</p>
              {rhythm.length === 0
                ? (isRunning ? <AnalysisRunningState job={job} /> : <EmptyState msg="No cadence data yet." />)
                : (
                <div className="overflow-x-auto rounded-xl border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                        <th className="px-4 py-3">Channel</th>
                        <th className="px-4 py-3">Upload Frequency</th>
                        <th className="px-4 py-3 text-right">Days Between Videos</th>
                        <th className="px-4 py-3 text-right">% Breakout Videos</th>
                        <th className="px-4 py-3">Consistency</th>
                        <th className="px-4 py-3 text-right">Days Before Big Hit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rhythm.map((r, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="px-4 py-3 font-medium text-gray-900 max-w-[150px] truncate">{r.channel_title || r.channel_id}</td>
                          <td className="px-4 py-3"><CadenceBadge cadence={r.cadence_pattern} /></td>
                          <td className="px-4 py-3 text-right text-gray-600">{fmt(r.median_gap_days)} days</td>
                          <td className="px-4 py-3 text-right font-semibold text-gray-900">{fmt(r.breakout_rate * 100)}%</td>
                          <td className="px-4 py-3"><RiskBadge profile={r.risk_profile} /></td>
                          <td className="px-4 py-3 text-right text-gray-500">
                            {r.pre_breakout_momentum != null ? `${fmt(r.pre_breakout_momentum)} days` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Velocity distribution table */}
            {channels.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-semibold text-gray-900">Views Distribution</h3>
                <p className="mb-3 text-xs text-gray-400">
                  Typical Low = bottom 25% of videos · Typical High = top 25% · Breakout = top 10%
                </p>
                <div className="overflow-x-auto rounded-xl border border-gray-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                        <th className="px-4 py-3">Channel</th>
                        <th className="px-4 py-3 text-right">Typical Low</th>
                        <th className="px-4 py-3 text-right">Typical High</th>
                        <th className="px-4 py-3 text-right">Breakout</th>
                        <th className="px-4 py-3 text-right">View Spread</th>
                        <th className="px-4 py-3 text-right">% High Performers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {channels.map((c, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="px-4 py-3 font-medium text-gray-900 max-w-[150px] truncate">{c.channel_title || c.channel_id}</td>
                          <td className="px-4 py-3 text-right text-gray-500">{fmt(c.p25_velocity)}</td>
                          <td className="px-4 py-3 text-right text-gray-700">{fmt(c.p75_velocity)}</td>
                          <td className="px-4 py-3 text-right font-semibold text-blue-700">{fmt(c.p90_velocity)}</td>
                          <td className="px-4 py-3 text-right text-gray-500">{fmt(c.iqr)}</td>
                          <td className="px-4 py-3 text-right text-gray-700">{fmt(c.hit_rate * 100)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Breakout Recipe ──────────────────────────────────────── */}
        {tab === 'breakout' && (
          <div className="space-y-6">
            {/* Lifecycle top topics */}
            {lifecycle.length === 0 && isRunning ? (
              <AnalysisRunningState job={job} />
            ) : lifecycle.length > 0 ? (
              <div>
                <h3 className="mb-1 text-sm font-semibold text-gray-900">Topic Lifespan — what stays relevant vs fades</h3>
                <p className="mb-3 text-xs text-gray-400">Evergreen topics keep earning views for months. Trend topics spike then fade.</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                    <p className="text-xs font-semibold text-emerald-700 mb-2">🌿 Evergreen Topics (invest now)</p>
                    <ul className="space-y-1.5">
                      {lifecycle.filter(l => l.shelf_life === 'evergreen').slice(0, 5).map((l, i) => (
                        <li key={i} className="flex items-center justify-between text-xs">
                          <span className="truncate text-gray-700 max-w-[160px]">{l.topic_name}</span>
                          <span className="ml-2 shrink-0 font-semibold text-emerald-700">{fmt(l.avg_velocity)}/day</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="rounded-xl border border-orange-200 bg-orange-50 p-4">
                    <p className="text-xs font-semibold text-orange-700 mb-2">📈 Trend Topics (act fast)</p>
                    <ul className="space-y-1.5">
                      {lifecycle.filter(l => l.shelf_life === 'trend').slice(0, 5).map((l, i) => (
                        <li key={i} className="flex items-center justify-between text-xs">
                          <span className="truncate text-gray-700 max-w-[160px]">{l.topic_name}</span>
                          <span className="ml-2 shrink-0 font-semibold text-orange-700">
                            {l.half_life_weeks != null ? `${l.half_life_weeks}wk shelf life` : fmt(l.avg_velocity)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Breakout model stats */}
            {recipe?.has_recipe && (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-gray-200 p-4 text-center">
                  <p className="text-2xl font-bold text-gray-900">{recipe.breakout_count}</p>
                  <p className="text-xs text-gray-500 mt-1">Breakout videos in dataset</p>
                </div>
                <div className="rounded-xl border border-gray-200 p-4 text-center">
                  <p className="text-2xl font-bold text-gray-900">{fmt(recipe.p90_threshold)}</p>
                  <p className="text-xs text-gray-500 mt-1">Daily views to break out</p>
                </div>
                <div className="rounded-xl border border-gray-200 p-4 text-center">
                  <p className="text-2xl font-bold text-gray-900">
                    {recipe.trained_at
                      ? new Date(recipe.trained_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
                      : '—'}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Model last trained</p>
                </div>
              </div>
            )}

            {/* Feature importance */}
            {recipe?.has_recipe && Object.keys(recipe.top_features ?? {}).length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-semibold text-gray-900">What predicts a breakout video</h3>
                <p className="mb-3 text-xs text-gray-400">Green = increases breakout chance · Red = decreases it</p>
                <div className="space-y-2">
                  {Object.entries(recipe.top_features)
                    .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                    .slice(0, 10)
                    .map(([feature, coef], i) => {
                      const pos    = coef >= 0
                      const maxAbs = Math.max(...Object.values(recipe.top_features).map(Math.abs))
                      const pct    = Math.abs(coef) / maxAbs * 100
                      // Make feature names human-readable
                      const label  = feature.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                      return (
                        <div key={i} className="flex items-center gap-3">
                          <span className="w-44 shrink-0 truncate text-xs text-gray-600">{label}</span>
                          <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${pos ? 'bg-green-500' : 'bg-red-400'}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className={`w-12 text-right text-xs font-semibold ${pos ? 'text-green-700' : 'text-red-600'}`}>
                            {coef >= 0 ? '+' : ''}{coef.toFixed(2)}
                          </span>
                        </div>
                      )
                    })}
                </div>
              </div>
            )}

            {/* Playbook */}
            {recipe?.has_recipe && recipe.playbook_text ? (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  <h3 className="text-sm font-semibold text-blue-900">AI Breakout Playbook</h3>
                  <span className="ml-auto rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                    Generated by ARIA
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-blue-900 whitespace-pre-wrap">{recipe.playbook_text}</p>
              </div>
            ) : !isRunning ? (
              <EmptyState msg="No breakout recipe yet. Run full analysis — needs 5+ breakout videos to train the model." />
            ) : null}
          </div>
        )}

        {/* ── Tab: My Channel ───────────────────────────────────────────── */}
        {tab === 'my-channel' && (
          <div className="space-y-6">
            {!ownAnalysis ? (
              isRunning
                ? <AnalysisRunningState job={job} customMsg="Own channel analysis runs after competitor pipeline" />
                : <EmptyState msg="No channel data yet. Run full analysis to compare your channel against competitors." />
            ) : ownAnalysis.not_enough_videos ? (
              <NotEnoughVideos count={ownAnalysis.video_count ?? 0} msg={ownAnalysis.message} />
            ) : (
              <>
                {/* Velocity scorecard */}
                <div>
                  <h3 className="mb-1 text-sm font-semibold text-gray-900">Your Channel vs Competitor Benchmarks</h3>
                  <p className="mb-3 text-xs text-gray-400">Views per day averaged across your recent videos, compared to the competitor distribution</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Your avg views/day',    val: ownAnalysis.own_avg_velocity ?? 0,    highlight: true },
                      { label: 'Competitor median',      val: ownAnalysis.comp_p50 ?? 0 },
                      { label: 'Competitor top 25%',     val: ownAnalysis.comp_p75 ?? 0 },
                      { label: 'Competitor top 10%',     val: ownAnalysis.comp_p90 ?? 0 },
                    ].map((item, i) => (
                      <div key={i} className={`rounded-xl border p-4 text-center ${item.highlight ? 'border-blue-300 bg-blue-50' : 'border-gray-200'}`}>
                        <p className={`text-2xl font-bold ${item.highlight ? 'text-blue-700' : 'text-gray-900'}`}>{fmt(item.val)}</p>
                        <p className="text-xs text-gray-500 mt-1">{item.label}</p>
                      </div>
                    ))}
                  </div>
                  {/* Percentile bar */}
                  <div className="mt-3 rounded-xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-gray-600">Your percentile rank among competitors</span>
                      <span className="text-sm font-bold text-blue-700">{fmt(ownAnalysis.own_velocity_percentile ?? 0)}th percentile</span>
                    </div>
                    <div className="h-3 rounded-full bg-gray-100 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-blue-500"
                        style={{ width: `${Math.min(ownAnalysis.own_velocity_percentile ?? 0, 100)}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                      <span>Bottom</span>
                      <span>Median</span>
                      <span>Top 10%</span>
                    </div>
                  </div>
                </div>

                {/* Your videos sorted by velocity */}
                {(ownAnalysis.videos ?? []).length > 0 && (
                  <div>
                    <h3 className="mb-1 text-sm font-semibold text-gray-900">Your Recent Videos</h3>
                    <p className="mb-3 text-xs text-gray-400">Sorted by views/day — AI-labelled with format and thumbnail type</p>
                    <div className="overflow-x-auto rounded-xl border border-gray-200">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                            <th className="px-4 py-3">Video</th>
                            <th className="px-4 py-3 text-right">Views/day</th>
                            <th className="px-4 py-3">Format</th>
                            <th className="px-4 py-3">Face</th>
                            <th className="px-4 py-3">Emotion</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(ownAnalysis.videos ?? []).map((v, i) => (
                            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                              <td className="px-4 py-3">
                                <p className="truncate text-xs font-medium text-gray-800 max-w-[220px]">{v.title}</p>
                                {v.is_short && <span className="text-xs text-red-500 font-semibold">#Shorts</span>}
                              </td>
                              <td className="px-4 py-3 text-right font-semibold text-gray-900">{fmt(v.velocity)}</td>
                              <td className="px-4 py-3">
                                {v.format_label && (
                                  <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                                    {v.format_label.replace(/_/g, ' ')}
                                  </span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-center text-xs">{v.thumb_face === true ? '✅' : v.thumb_face === false ? '❌' : '—'}</td>
                              <td className="px-4 py-3 text-xs text-gray-600">{v.thumb_emotion || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Tab: Growth Plan ──────────────────────────────────────────── */}
        {tab === 'growth-plan' && (
          <div className="space-y-6">
            {/* Workspace type selector */}
            <div>
              <h3 className="mb-1 text-sm font-semibold text-gray-900">What best describes your channel?</h3>
              <p className="mb-3 text-xs text-gray-400">This shapes the growth recipe — D2C focuses on sales, Creator on monetisation, SaaS on leads</p>
              <div className="flex flex-wrap gap-2">
                {WORKSPACE_TYPES.map(wt => (
                  <button
                    key={wt.value}
                    onClick={() => saveWorkspaceType(wt.value)}
                    className={`rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                      workspaceType === wt.value
                        ? 'border-red-500 bg-red-50 text-red-700'
                        : 'border-gray-200 text-gray-600 hover:border-gray-300'
                    }`}
                    title={wt.desc}
                  >
                    {wt.label}
                  </button>
                ))}
              </div>
              {workspaceType && (
                <p className="mt-2 text-xs text-gray-400 italic">
                  {WORKSPACE_TYPES.find(w => w.value === workspaceType)?.desc}
                </p>
              )}
            </div>

            {/* No growth recipe yet */}
            {!growthRecipe || !growthRecipe.has_data ? (
              isRunning
                ? <AnalysisRunningState job={job} customMsg="Growth plan generates after your channel is analysed" />
                : <EmptyState msg="No growth plan yet. Run full analysis first — this tab generates automatically after completion." />
            ) : growthRecipe.not_enough_videos ? (
              <NotEnoughVideos count={growthRecipe.video_count ?? 0} msg={growthRecipe.message} />
            ) : (
              <>
                {/* Meta + Regenerate */}
                <div className="flex items-center justify-between">
                  <p className="text-xs text-gray-400">
                    {growthRecipe.own_video_count} own videos · {fmt(growthRecipe.own_velocity_avg)} views/day avg ·
                    {' '}{fmt(growthRecipe.own_velocity_percentile)}th percentile vs competitors ·
                    {' '}Generated {growthRecipe.generated_at ? new Date(growthRecipe.generated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—'}
                  </p>
                  <button
                    onClick={regenerateRecipe}
                    disabled={regenLoading}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                  >
                    {regenLoading ? (
                      <>
                        <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                        Regenerating…
                      </>
                    ) : '↺ Regenerate Plan'}
                  </button>
                </div>

                {/* If sections parsed correctly, show structured view */}
                {growthRecipe.plan_15d && (
                  <div className="rounded-xl border border-red-200 bg-red-50 p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-base">🚀</span>
                      <h3 className="text-sm font-bold text-red-900">15-Day Sprint Plan</h3>
                      <span className="ml-auto rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Quick wins</span>
                    </div>
                    <div className="text-sm leading-relaxed text-red-900 whitespace-pre-wrap">{growthRecipe.plan_15d}</div>
                  </div>
                )}

                {growthRecipe.plan_30d && (
                  <div className="rounded-xl border border-purple-200 bg-purple-50 p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-base">🗺️</span>
                      <h3 className="text-sm font-bold text-purple-900">30-Day Roadmap</h3>
                      <span className="ml-auto rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">Sustained growth</span>
                    </div>
                    <div className="text-sm leading-relaxed text-purple-900 whitespace-pre-wrap">{growthRecipe.plan_30d}</div>
                  </div>
                )}

                {(growthRecipe.thumbnail_brief || growthRecipe.hooks_library) && (
                  <div className="grid sm:grid-cols-2 gap-4">
                    {growthRecipe.thumbnail_brief && (
                      <div className="rounded-xl border border-orange-200 bg-orange-50 p-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-base">🖼️</span>
                          <h3 className="text-sm font-bold text-orange-900">Thumbnail Creative Brief</h3>
                        </div>
                        <div className="text-xs leading-relaxed text-orange-900 whitespace-pre-wrap">{growthRecipe.thumbnail_brief}</div>
                      </div>
                    )}
                    {growthRecipe.hooks_library && (
                      <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-base">🎣</span>
                          <h3 className="text-sm font-bold text-green-900">10 Hook Lines</h3>
                        </div>
                        <div className="text-xs leading-relaxed text-green-900 whitespace-pre-wrap">{growthRecipe.hooks_library}</div>
                      </div>
                    )}
                  </div>
                )}

                {growthRecipe.emerging_topics && (
                  <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-base">🔭</span>
                      <h3 className="text-sm font-bold text-blue-900">5 Emerging Topics to Cover Now</h3>
                    </div>
                    <div className="text-sm leading-relaxed text-blue-900 whitespace-pre-wrap">{growthRecipe.emerging_topics}</div>
                  </div>
                )}

                {/* Fallback: show full Claude response if sections didn't parse */}
                {!growthRecipe.plan_15d && !growthRecipe.plan_30d && growthRecipe.recipe_text && (
                  <div className="rounded-xl border border-gray-200 bg-white p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-base">📋</span>
                      <h3 className="text-sm font-bold text-gray-900">Full Growth Plan</h3>
                      <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                        Generated by ARIA
                      </span>
                    </div>
                    <div className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">{growthRecipe.recipe_text}</div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

      </div>
    </div>
  )
}
