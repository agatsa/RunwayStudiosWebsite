'use client'

import { useState } from 'react'
import { Loader2, ChevronUp, Lightbulb, Rocket, CheckCircle, Sparkles, Zap, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { AiBadge, AiContent } from '@/components/ui/AiBadge'
import { AiThinkingLoader } from '@/components/ui/AiThinkingLoader'

interface BriefFormProps {
  workspaceId: string
}

interface KpiTargets {
  expected_roas: number
  expected_cpa: number
  expected_ctr: number
}

interface Concept {
  headline: string
  body_copy: string
  hook: string
  creative_direction: string
  recommended_format: string
  recommended_channels?: string[]
  recommended_budget_daily?: number
  recommended_duration_days?: number
  kpi_targets: KpiTargets
  rationale: string
  growth_insights?: string[]
}

interface BriefResult {
  plan_id: string
  concept: Concept
  status: string
  auto_generated?: boolean
  context_used?: boolean
}

const GOALS = ['conversions', 'awareness', 'traffic', 'leads', 'video_views']
const CHANNELS = ['meta', 'google', 'youtube']

type Mode = 'manual' | 'auto'


export default function BriefForm({ workspaceId }: BriefFormProps) {
  const router = useRouter()
  // Collapsed by default — shows "+ New Campaign Brief" button
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('auto')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BriefResult | null>(null)
  const [editedCopy, setEditedCopy] = useState('')

  const [sentToApprovals, setSentToApprovals] = useState(false)

  const [form, setForm] = useState({
    product_name: '',
    product_url: '',
    product_price: '',
    audience_description: '',
    goal: 'conversions',
    budget_daily: 1000,
    duration_days: 14,
    channels: ['meta'] as string[],
  })

  function toggleChannel(ch: string) {
    setForm(f => ({
      ...f,
      channels: f.channels.includes(ch)
        ? f.channels.filter(c => c !== ch)
        : [...f.channels, ch],
    }))
  }

  function selectAllChannels() {
    setForm(f => ({ ...f, channels: [...CHANNELS] }))
  }

  async function handleAutoGenerate() {
    if (!workspaceId) { alert('No workspace selected.'); return }
    setLoading(true)
    setResult(null)
    setSentToApprovals(false)
    try {
      const res = await fetch('/api/campaign-planner/auto-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Auto-generation failed')
      setResult(data)
      setEditedCopy(data.concept?.body_copy ?? '')
      if (data.concept?.recommended_channels?.length) {
        setForm(f => ({ ...f, channels: data.concept.recommended_channels }))
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    if (!workspaceId) { alert('No workspace selected.'); return }
    if (!form.product_name.trim()) { alert('Please enter a product name.'); return }
    setLoading(true)
    setResult(null)
    setSentToApprovals(false)
    try {
      const res = await fetch('/api/campaign-planner/create-brief', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, ...form }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to generate brief')
      setResult(data)
      setEditedCopy(data.concept?.body_copy ?? '')
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  function handleSendToApprovals() {
    setSentToApprovals(true)
    // Plan is already saved as pending in action_log — just navigate to approvals
    setTimeout(() => {
      router.push(workspaceId ? `/approvals?ws=${workspaceId}` : '/approvals')
    }, 1200)
  }

  // ── Collapsed state — just a button ──────────────────────────────────────
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-3 rounded-xl border-2 border-dashed border-indigo-200 bg-indigo-50 px-6 py-4 text-base font-semibold text-indigo-700 hover:border-indigo-400 hover:bg-indigo-100 transition-colors w-full"
      >
        <Plus className="h-5 w-5" />
        New Campaign Brief
        <AiBadge label="AI-powered" />
      </button>
    )
  }

  return (
    <div className="rounded-xl border border-indigo-200 overflow-hidden">
      {/* Header toggle */}
      <button
        onClick={() => { setOpen(false); setResult(null) }}
        className="w-full flex items-center justify-between bg-indigo-50 px-5 py-4 text-left"
      >
        <div className="flex items-center gap-2">
          <Lightbulb className="h-5 w-5 text-indigo-600" />
          <span className="text-base font-semibold text-indigo-900">New Campaign Brief</span>
          <AiBadge label="AI-powered" />
        </div>
        <ChevronUp className="h-5 w-5 text-indigo-500" />
      </button>

      <div className="bg-white p-5 space-y-5">
        {/* Mode selector */}
        <div className="flex gap-2 rounded-xl bg-gray-50 border border-gray-200 p-1">
          <button
            onClick={() => { setMode('manual'); setResult(null) }}
            className={`flex-1 flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold transition-colors ${
              mode === 'manual'
                ? 'bg-white text-indigo-700 shadow-sm border border-indigo-200'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Lightbulb className="h-4 w-4" /> Manual Brief
          </button>
          <button
            onClick={() => { setMode('auto'); setResult(null) }}
            className={`flex-1 flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold transition-colors ${
              mode === 'auto'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Sparkles className="h-4 w-4" /> AI Auto-Plan
          </button>
        </div>

        {mode === 'auto' ? (
          /* ── AI Auto-Generate Mode ── */
          <div className="space-y-4">
            <div className="rounded-xl border border-sky-100 bg-sky-50 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles className="h-5 w-5 text-sky-600" />
                <p className="text-base font-semibold text-sky-900">AI Auto-Plan</p>
              </div>
              <p className="text-sm text-sky-700">
                Claude reads your product catalog, recent spend, ROAS, conversions and best-performing
                campaigns — then recommends a complete multi-channel growth plan. No manual input needed.
              </p>
              <ul className="mt-3 space-y-1 text-sm text-sky-600">
                <li>• Recommends which channels to scale</li>
                <li>• Sets budget based on your actual spend history</li>
                <li>• Surfaces specific growth levers from your data</li>
              </ul>
            </div>

            {loading ? (
              <AiThinkingLoader message="Claude is analysing your workspace data…" />
            ) : (
              <button
                onClick={handleAutoGenerate}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-3 text-base font-semibold text-white hover:bg-sky-700"
              >
                <Zap className="h-5 w-5" /> Generate AI Growth Plan
              </button>
            )}
          </div>
        ) : (
          /* ── Manual Form Mode ── */
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Product Name *</label>
                <input
                  value={form.product_name}
                  onChange={e => setForm(f => ({ ...f, product_name: e.target.value }))}
                  placeholder="e.g. SanketLife 2.0"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Product URL</label>
                <input
                  value={form.product_url}
                  onChange={e => setForm(f => ({ ...f, product_url: e.target.value }))}
                  placeholder="https://agatsaone.com/products/…"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Price (₹)</label>
                <input
                  value={form.product_price}
                  onChange={e => setForm(f => ({ ...f, product_price: e.target.value }))}
                  placeholder="e.g. 15999"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Campaign Goal</label>
                <select
                  value={form.goal}
                  onChange={e => setForm(f => ({ ...f, goal: e.target.value }))}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                >
                  {GOALS.map(g => (
                    <option key={g} value={g}>{g.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Target Audience Description</label>
              <textarea
                value={form.audience_description}
                onChange={e => setForm(f => ({ ...f, audience_description: e.target.value }))}
                rows={2}
                placeholder="e.g. Indian males 35-60, heart disease history, tier 1-2 cities, income >₹8L"
                className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Daily Budget: ₹{form.budget_daily.toLocaleString()}
                </label>
                <input
                  type="range" min={500} max={50000} step={500}
                  value={form.budget_daily}
                  onChange={e => setForm(f => ({ ...f, budget_daily: Number(e.target.value) }))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                  <span>₹500</span><span>₹50k</span>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Duration: {form.duration_days} days</label>
                <input
                  type="range" min={7} max={90} step={7}
                  value={form.duration_days}
                  onChange={e => setForm(f => ({ ...f, duration_days: Number(e.target.value) }))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                  <span>7d</span><span>90d</span>
                </div>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-gray-700">Channels</label>
                <button onClick={selectAllChannels} className="text-sm text-indigo-600 hover:underline">
                  Select All
                </button>
              </div>
              <div className="flex gap-2">
                {CHANNELS.map(ch => (
                  <button
                    key={ch}
                    onClick={() => toggleChannel(ch)}
                    className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                      form.channels.includes(ch)
                        ? 'border-indigo-500 bg-indigo-100 text-indigo-700'
                        : 'border-gray-200 bg-gray-50 text-gray-500 hover:border-gray-300'
                    }`}
                  >
                    {ch.charAt(0).toUpperCase() + ch.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {loading ? (
              <AiThinkingLoader message="Claude is generating your campaign brief…" />
            ) : (
              <button
                onClick={handleGenerate}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-3 text-base font-semibold text-white hover:bg-indigo-700"
              >
                <Lightbulb className="h-5 w-5" /> Generate Campaign Brief
              </button>
            )}
          </>
        )}

        {/* Generated result — same for both modes */}
        {result && !loading && (
          <AiContent className="mt-2 p-4 space-y-4" label={result.auto_generated ? 'AI Auto-Plan' : 'AI Generated'}>
            <div className="flex items-center gap-2 pt-1">
              <CheckCircle className="h-5 w-5 text-sky-600" />
              <p className="text-base font-semibold text-sky-900">
                {result.auto_generated ? 'AI Growth Plan Ready' : 'AI Campaign Concept Ready'}
              </p>
              <span className="ml-auto text-sm text-sky-500">ID: {result.plan_id.slice(0, 8)}…</span>
            </div>

            {/* Growth insights — auto mode only */}
            {result.concept.growth_insights && result.concept.growth_insights.length > 0 && (
              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Key Growth Insights</p>
                <ul className="space-y-1.5">
                  {result.concept.growth_insights.map((insight, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="text-sky-500 mt-0.5 shrink-0">→</span>
                      {insight}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Headline</p>
                <p className="text-base font-bold text-gray-900">{result.concept.headline}</p>
              </div>
              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Format</p>
                <p className="text-sm text-gray-800">{result.concept.recommended_format}</p>
              </div>
            </div>

            {result.concept.recommended_channels && (
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-xs font-semibold uppercase text-gray-400">Recommended Channels</p>
                {result.concept.recommended_channels.map(ch => (
                  <span key={ch} className="rounded-full bg-sky-100 px-3 py-1 text-sm font-semibold text-sky-700 capitalize">{ch}</span>
                ))}
                {result.concept.recommended_budget_daily && (
                  <span className="ml-auto text-sm text-gray-500">₹{result.concept.recommended_budget_daily.toLocaleString()}/day recommended</span>
                )}
              </div>
            )}

            <div className="rounded-lg bg-white border border-sky-100 p-3">
              <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Hook</p>
              <p className="text-sm italic text-gray-700">&ldquo;{result.concept.hook}&rdquo;</p>
            </div>

            <div className="rounded-lg bg-white border border-sky-100 p-3">
              <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Body Copy (editable)</p>
              <textarea
                value={editedCopy}
                onChange={e => setEditedCopy(e.target.value)}
                rows={3}
                className="w-full text-sm text-gray-800 border-0 bg-transparent focus:outline-none resize-none"
              />
            </div>

            <div className="rounded-lg bg-white border border-sky-100 p-3">
              <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Creative Direction</p>
              <p className="text-sm text-gray-600">{result.concept.creative_direction}</p>
            </div>

            {result.concept.kpi_targets && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  ['Expected ROAS', `${result.concept.kpi_targets.expected_roas}x`],
                  ['Expected CPA', `₹${result.concept.kpi_targets.expected_cpa}`],
                  ['Expected CTR', `${result.concept.kpi_targets.expected_ctr}%`],
                ].map(([l, v]) => (
                  <div key={l} className="rounded-lg bg-white border border-sky-100 p-2.5 text-center">
                    <p className="text-xs text-gray-400">{l}</p>
                    <p className="text-base font-bold text-sky-700">{v}</p>
                  </div>
                ))}
              </div>
            )}

            {result.concept.rationale && (
              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-xs font-semibold uppercase text-gray-400 mb-1">Rationale</p>
                <p className="text-sm text-gray-600">{result.concept.rationale}</p>
              </div>
            )}

            {sentToApprovals ? (
              <div className="rounded-xl bg-green-50 border border-green-200 px-4 py-3 flex items-center gap-3">
                <CheckCircle className="h-5 w-5 text-green-600 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-green-800">Plan sent to Decision Inbox</p>
                  <p className="text-xs text-green-600">Redirecting to Approvals — review the plan and click "Approve &amp; Launch on Meta" to create the campaign.</p>
                </div>
              </div>
            ) : (
              <>
                <button
                  onClick={handleSendToApprovals}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-3 text-base font-semibold text-white hover:bg-indigo-700 transition-colors"
                >
                  <Rocket className="h-5 w-5" />
                  Send to Approvals
                </button>
                <p className="text-center text-xs text-gray-400">Review the full plan in Decision Inbox and approve to launch as a PAUSED campaign on Meta.</p>
              </>
            )}
          </AiContent>
        )}
      </div>
    </div>
  )
}
