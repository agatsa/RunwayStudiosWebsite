'use client'

import { useState } from 'react'
import { Loader2, ChevronDown, ChevronUp, Lightbulb, Send, CheckCircle, Sparkles, Zap } from 'lucide-react'
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
  const [open, setOpen] = useState(true)
  const [mode, setMode] = useState<Mode>('manual')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<BriefResult | null>(null)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const [editedCopy, setEditedCopy] = useState('')

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
      // Pre-fill channels from AI recommendation
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

  async function handleSubmit() {
    if (!result) return
    setSubmitting(true)
    try {
      setToastMsg('Campaign brief submitted! Redirecting to Approvals…')
      setTimeout(() => {
        router.push(workspaceId ? `/approvals?ws=${workspaceId}` : '/approvals')
      }, 1500)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-xl border border-indigo-200 overflow-hidden">
      {/* Header toggle */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between bg-indigo-50 px-5 py-4 text-left"
      >
        <div className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-indigo-600" />
          <span className="text-sm font-semibold text-indigo-900">New Campaign Brief</span>
          <AiBadge label="AI-powered" />
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-indigo-500" /> : <ChevronDown className="h-4 w-4 text-indigo-500" />}
      </button>

      {open && (
        <div className="bg-white p-5 space-y-4">
          {/* Mode selector */}
          <div className="flex gap-2 rounded-xl bg-gray-50 border border-gray-200 p-1">
            <button
              onClick={() => { setMode('manual'); setResult(null) }}
              className={`flex-1 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold transition-colors ${
                mode === 'manual'
                  ? 'bg-white text-indigo-700 shadow-sm border border-indigo-200'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Lightbulb className="h-3.5 w-3.5" /> Manual Brief
            </button>
            <button
              onClick={() => { setMode('auto'); setResult(null) }}
              className={`flex-1 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold transition-colors ${
                mode === 'auto'
                  ? 'bg-sky-600 text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Sparkles className="h-3.5 w-3.5" /> AI Auto-Plan
            </button>
          </div>

          {mode === 'auto' ? (
            /* ── AI Auto-Generate Mode ── */
            <div className="space-y-3">
              <div className="rounded-xl border border-sky-100 bg-sky-50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="h-4 w-4 text-sky-600" />
                  <p className="text-sm font-semibold text-sky-900">AI Auto-Plan</p>
                </div>
                <p className="text-xs text-sky-700">
                  Claude reads your product catalog, recent spend, ROAS, conversions and best-performing
                  campaigns — then recommends a complete multi-channel growth plan. No manual input needed.
                </p>
                <ul className="mt-2 space-y-0.5 text-xs text-sky-600">
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
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-3 text-sm font-semibold text-white hover:bg-sky-700"
                >
                  <Zap className="h-4 w-4" /> Generate AI Growth Plan
                </button>
              )}
            </div>
          ) : (
            /* ── Manual Form Mode ── */
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Product Name *</label>
                  <input
                    value={form.product_name}
                    onChange={e => setForm(f => ({ ...f, product_name: e.target.value }))}
                    placeholder="e.g. SanketLife 2.0"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Product URL</label>
                  <input
                    value={form.product_url}
                    onChange={e => setForm(f => ({ ...f, product_url: e.target.value }))}
                    placeholder="https://agatsaone.com/products/…"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Price (₹)</label>
                  <input
                    value={form.product_price}
                    onChange={e => setForm(f => ({ ...f, product_price: e.target.value }))}
                    placeholder="e.g. 15999"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Campaign Goal</label>
                  <select
                    value={form.goal}
                    onChange={e => setForm(f => ({ ...f, goal: e.target.value }))}
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  >
                    {GOALS.map(g => (
                      <option key={g} value={g}>{g.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Target Audience Description</label>
                <textarea
                  value={form.audience_description}
                  onChange={e => setForm(f => ({ ...f, audience_description: e.target.value }))}
                  rows={2}
                  placeholder="e.g. Indian males 35-60, heart disease history, tier 1-2 cities, income >₹8L"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Daily Budget: ₹{form.budget_daily.toLocaleString()}
                  </label>
                  <input
                    type="range" min={500} max={50000} step={500}
                    value={form.budget_daily}
                    onChange={e => setForm(f => ({ ...f, budget_daily: Number(e.target.value) }))}
                    className="w-full accent-indigo-600"
                  />
                  <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                    <span>₹500</span><span>₹50k</span>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Duration: {form.duration_days} days</label>
                  <input
                    type="range" min={7} max={90} step={7}
                    value={form.duration_days}
                    onChange={e => setForm(f => ({ ...f, duration_days: Number(e.target.value) }))}
                    className="w-full accent-indigo-600"
                  />
                  <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                    <span>7d</span><span>90d</span>
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-gray-700">Channels</label>
                  <button onClick={selectAllChannels} className="text-xs text-indigo-600 hover:underline">
                    Select All Platforms
                  </button>
                </div>
                <div className="flex gap-2">
                  {CHANNELS.map(ch => (
                    <button
                      key={ch}
                      onClick={() => toggleChannel(ch)}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
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
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
                >
                  <Lightbulb className="h-4 w-4" /> Generate Campaign Brief
                </button>
              )}
            </>
          )}

          {/* Generated result — same for both modes */}
          {result && !loading && (
            <AiContent className="mt-2 p-4 space-y-4" label={result.auto_generated ? 'AI Auto-Plan' : 'AI Generated'}>
              <div className="flex items-center gap-2 pt-1">
                <CheckCircle className="h-4 w-4 text-sky-600" />
                <p className="text-sm font-semibold text-sky-900">
                  {result.auto_generated ? 'AI Growth Plan' : 'AI Campaign Concept'}
                </p>
                <span className="ml-auto text-xs text-sky-500">ID: {result.plan_id.slice(0, 8)}…</span>
              </div>

              {/* Growth insights — auto mode only */}
              {result.concept.growth_insights && result.concept.growth_insights.length > 0 && (
                <div className="rounded-lg bg-white border border-sky-100 p-3">
                  <p className="text-[10px] font-semibold uppercase text-gray-400 mb-2">Key Growth Insights</p>
                  <ul className="space-y-1">
                    {result.concept.growth_insights.map((insight, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                        <span className="text-sky-500 mt-0.5 shrink-0">→</span>
                        {insight}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg bg-white border border-sky-100 p-3">
                  <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Headline</p>
                  <p className="text-sm font-bold text-gray-900">{result.concept.headline}</p>
                </div>
                <div className="rounded-lg bg-white border border-sky-100 p-3">
                  <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Format</p>
                  <p className="text-sm text-gray-800">{result.concept.recommended_format}</p>
                </div>
              </div>

              {result.concept.recommended_channels && (
                <div className="flex items-center gap-2">
                  <p className="text-[10px] font-semibold uppercase text-gray-400">Recommended Channels</p>
                  {result.concept.recommended_channels.map(ch => (
                    <span key={ch} className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-700 capitalize">{ch}</span>
                  ))}
                  {result.concept.recommended_budget_daily && (
                    <span className="ml-auto text-xs text-gray-500">₹{result.concept.recommended_budget_daily.toLocaleString()}/day recommended</span>
                  )}
                </div>
              )}

              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Hook</p>
                <p className="text-sm italic text-gray-700">&ldquo;{result.concept.hook}&rdquo;</p>
              </div>

              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Body Copy (editable)</p>
                <textarea
                  value={editedCopy}
                  onChange={e => setEditedCopy(e.target.value)}
                  rows={3}
                  className="w-full text-sm text-gray-800 border-0 bg-transparent focus:outline-none resize-none"
                />
              </div>

              <div className="rounded-lg bg-white border border-sky-100 p-3">
                <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Creative Direction</p>
                <p className="text-xs text-gray-600">{result.concept.creative_direction}</p>
              </div>

              {result.concept.kpi_targets && (
                <div className="grid grid-cols-3 gap-2">
                  {[
                    ['Expected ROAS', `${result.concept.kpi_targets.expected_roas}x`],
                    ['Expected CPA', `₹${result.concept.kpi_targets.expected_cpa}`],
                    ['Expected CTR', `${result.concept.kpi_targets.expected_ctr}%`],
                  ].map(([l, v]) => (
                    <div key={l} className="rounded-lg bg-white border border-sky-100 p-2.5 text-center">
                      <p className="text-[10px] text-gray-400">{l}</p>
                      <p className="text-sm font-bold text-sky-700">{v}</p>
                    </div>
                  ))}
                </div>
              )}

              {result.concept.rationale && (
                <div className="rounded-lg bg-white border border-sky-100 p-3">
                  <p className="text-[10px] font-semibold uppercase text-gray-400 mb-1">Rationale</p>
                  <p className="text-xs text-gray-600">{result.concept.rationale}</p>
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-60"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                Submit for Approval
              </button>

              {toastMsg && (
                <div className="rounded-lg bg-green-100 px-3 py-2 text-center text-sm text-green-700">
                  <CheckCircle className="inline h-4 w-4 mr-1" />
                  {toastMsg}
                </div>
              )}
            </AiContent>
          )}
        </div>
      )}
    </div>
  )
}
