'use client'

import { useState } from 'react'
import { Clock, CheckCircle, XCircle, AlertCircle, Rocket, ChevronDown, ChevronUp, Sparkles, Loader2, Image as ImageIcon, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { toast } from 'sonner'

interface Plan {
  id: string
  action_type: string
  new_value: {
    brief?: {
      product_name?: string
      goal?: string
      budget_daily?: number
      duration_days?: number
      channels?: string[]
    }
    concept?: {
      headline?: string
      recommended_format?: string
      kpi_targets?: { expected_roas?: number; expected_cpa?: number }
      body_copy?: string
      hook?: string
      creative_direction?: string
      rationale?: string
      growth_insights?: string[]
      generated_image_url?: string
    }
    meta_campaign_id?: string
    meta_adset_id?: string
    meta_ad_id?: string
    google_campaign_id?: string
  } | null
  triggered_by: string
  status: string
  ts: string
  workspace_id?: string
}

interface Props {
  plans: Plan[]
  workspaceId?: string
}


// ── Status helpers ────────────────────────────────────────────────────────────
function StatusIcon({ status }: { status: string }) {
  if (status === 'approved' || status === 'executed') return <CheckCircle className="h-5 w-5 text-green-500" />
  if (status === 'rejected') return <XCircle className="h-5 w-5 text-red-500" />
  return <AlertCircle className="h-5 w-5 text-yellow-500" />
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending:  'bg-yellow-100 text-yellow-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    executed: 'bg-blue-100 text-blue-700',
  }
  return (
    <span className={`rounded-full px-3 py-1 text-sm font-medium ${map[status] ?? 'bg-gray-100 text-gray-600'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

// ── Plan card ─────────────────────────────────────────────────────────────────
function PlanCard({ plan, workspaceId }: { plan: Plan; workspaceId?: string }) {
  const [expanded, setExpanded]         = useState(false)
  const [imageUrl, setImageUrl]         = useState(plan.new_value?.concept?.generated_image_url || '')
  const [adId, setAdId]                 = useState(plan.new_value?.meta_ad_id || '')
  const [generatingImage, setGeneratingImage] = useState(false)
  const [publishingAd, setPublishingAd]       = useState(false)

  const brief   = plan.new_value?.brief
  const concept = plan.new_value?.concept
  const productName = brief?.product_name ?? concept?.headline ?? 'Campaign Plan'
  const headline    = concept?.headline ?? ''
  const format      = concept?.recommended_format ?? ''
  const wsId        = workspaceId ?? plan.workspace_id ?? ''
  const approvalsHref = wsId ? `/approvals?ws=${wsId}` : '/approvals'

  const hasCreative     = !!(concept?.hook || concept?.body_copy || concept?.creative_direction || concept?.rationale || concept?.growth_insights?.length)
  const campaignCreated = !!(plan.new_value?.meta_campaign_id || plan.new_value?.google_campaign_id)
  const canGenerateImage = plan.status === 'executed' && campaignCreated && !!concept?.creative_direction
  const canPublishAd    = canGenerateImage && !!imageUrl && !adId

  async function handleGenerateImage() {
    setGeneratingImage(true)
    try {
      const r = await fetch('/api/campaign-planner/generate-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: plan.id, workspace_id: wsId }),
      })
      const data = await r.json()
      if (!r.ok || !data.image_url) {
        toast.error(data.detail || data.error || 'Image generation failed')
        return
      }
      setImageUrl(data.image_url)
      toast.success('Creative image generated — review and publish as ad below')
    } catch {
      toast.error('Image generation failed — try again')
    } finally {
      setGeneratingImage(false)
    }
  }

  async function handlePublishAd() {
    setPublishingAd(true)
    try {
      const r = await fetch('/api/campaign-planner/publish-ad', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: plan.id, workspace_id: wsId }),
      })
      const data = await r.json()
      if (!r.ok || !data.meta_ad_id) {
        toast.error(data.detail || data.error || 'Ad creation failed')
        return
      }
      setAdId(data.meta_ad_id)
      toast.success('✓ Ad created on Meta (PAUSED) — activate in Meta Ads Manager when ready', { duration: 7000 })
    } catch {
      toast.error('Ad creation failed — try again')
    } finally {
      setPublishingAd(false)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* ── Main card content ── */}
      <div className="p-5">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <StatusIcon status={plan.status} />
              <h3 className="text-base font-semibold text-gray-900 truncate">{productName}</h3>
            </div>
            {headline && productName !== headline && (
              <p className="text-sm text-gray-500 italic truncate">&ldquo;{headline}&rdquo;</p>
            )}
            {brief && (
              <p className="mt-1 text-sm text-gray-500">
                {brief.goal?.replace('_', ' ')} · ₹{brief.budget_daily?.toLocaleString()}/day · {brief.duration_days}d
                {brief.channels?.length ? ` · ${brief.channels.join(', ')}` : ''}
              </p>
            )}
            {format && <p className="text-sm text-gray-400 mt-0.5">Format: {format}</p>}
          </div>
          <StatusBadge status={plan.status} />
        </div>

        {concept?.kpi_targets && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 mb-4">
            {[
              { label: 'ROAS Target', value: `${concept.kpi_targets.expected_roas ?? '—'}x` },
              { label: 'CPA Target',  value: `₹${concept.kpi_targets.expected_cpa ?? '—'}` },
              { label: 'Budget/day',  value: `₹${brief?.budget_daily?.toLocaleString() ?? '—'}` },
              { label: 'Duration',    value: `${brief?.duration_days ?? '—'} days` },
            ].map(m => (
              <div key={m.label} className="rounded-lg bg-gray-50 p-3 text-center">
                <p className="text-xs text-gray-400 uppercase mb-0.5">{m.label}</p>
                <p className="text-sm font-bold text-indigo-700">{m.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Action row */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 text-sm text-gray-400">
            <Clock className="h-4 w-4" />
            {new Date(plan.ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
            <span className="mx-1">·</span>
            via {plan.triggered_by}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {hasCreative && (
              <button
                onClick={() => setExpanded(e => !e)}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
              >
                {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                {expanded ? 'Hide' : 'View'} Creative Brief
              </button>
            )}

            {plan.status === 'pending' && (
              <Link
                href={approvalsHref}
                className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-5 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-100 transition-colors"
              >
                <Rocket className="h-4 w-4" />
                Review &amp; Approve in Decision Inbox
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* ── Creative pipeline (only shown after campaign is created on Meta) ── */}
      {(canGenerateImage || imageUrl || adId) && (
        <div className="border-t border-gray-100 bg-gray-50 px-5 py-4">
          <p className="text-xs font-semibold uppercase text-gray-400 mb-3 flex items-center gap-1.5">
            <ImageIcon className="h-3.5 w-3.5" /> Creative & Ad
          </p>

          <div className="flex flex-col sm:flex-row gap-4">
            {/* Left: image preview or generate button */}
            <div className="flex-1">
              {imageUrl ? (
                <div className="space-y-2">
                  <img
                    src={imageUrl}
                    alt="Generated ad creative"
                    className="rounded-lg border border-gray-200 w-full max-w-[260px] aspect-square object-cover"
                  />
                  {!adId && (
                    <button
                      onClick={handleGenerateImage}
                      disabled={generatingImage}
                      className="flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                    >
                      {generatingImage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      Regenerate image
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-center rounded-lg border-2 border-dashed border-gray-200 bg-white w-full max-w-[260px] aspect-square">
                  <div className="text-center p-4">
                    <ImageIcon className="h-8 w-8 text-gray-300 mx-auto mb-2" />
                    <p className="text-xs text-gray-400">No creative yet</p>
                  </div>
                </div>
              )}
            </div>

            {/* Right: copy preview + action buttons */}
            <div className="flex-1 space-y-3">
              {concept?.body_copy && (
                <div className="rounded-lg bg-white border border-gray-100 px-3 py-2">
                  <p className="text-xs text-gray-400 uppercase mb-0.5">Ad Copy</p>
                  <p className="text-sm text-gray-700 leading-relaxed">{concept.body_copy}</p>
                </div>
              )}
              {concept?.hook && (
                <div className="rounded-lg bg-white border border-gray-100 px-3 py-2">
                  <p className="text-xs text-gray-400 uppercase mb-0.5">Hook</p>
                  <p className="text-sm font-medium text-gray-800 italic">&ldquo;{concept.hook}&rdquo;</p>
                </div>
              )}

              {/* Action buttons */}
              <div className="flex flex-col gap-2 pt-1">
                {!imageUrl && canGenerateImage && (
                  <button
                    onClick={handleGenerateImage}
                    disabled={generatingImage}
                    className="flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {generatingImage
                      ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating image…</>
                      : <><Sparkles className="h-4 w-4" /> Generate Creative Image</>
                    }
                  </button>
                )}

                {canPublishAd && (
                  <button
                    onClick={handlePublishAd}
                    disabled={publishingAd}
                    className="flex items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {publishingAd
                      ? <><Loader2 className="h-4 w-4 animate-spin" /> Creating Ad…</>
                      : <><Rocket className="h-4 w-4" /> Create Ad in Meta (PAUSED)</>
                    }
                  </button>
                )}

                {adId && (
                  <div className="rounded-lg bg-green-50 border border-green-200 px-3 py-2.5 flex items-center gap-2">
                    <CheckCircle className="h-4 w-4 text-green-600 shrink-0" />
                    <div>
                      <p className="text-sm font-semibold text-green-800">Ad created on Meta (PAUSED)</p>
                      <p className="text-xs text-green-600">Activate in Meta Ads Manager when ready to go live</p>
                    </div>
                    <a
                      href="https://www.facebook.com/adsmanager"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-auto shrink-0 text-green-700 hover:text-green-900"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Expandable creative brief ── */}
      {expanded && hasCreative && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4 bg-gray-50">
          <p className="text-xs font-semibold uppercase text-gray-400">Creative Brief</p>

          {concept?.hook && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-1">Hook</p>
              <p className="text-sm font-medium text-gray-800 italic">&ldquo;{concept.hook}&rdquo;</p>
            </div>
          )}

          {concept?.body_copy && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-1">Ad Copy</p>
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{concept.body_copy}</p>
            </div>
          )}

          {concept?.creative_direction && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-1">Creative Direction</p>
              <p className="text-sm text-gray-600 leading-relaxed">{concept.creative_direction}</p>
            </div>
          )}

          {concept?.growth_insights && concept.growth_insights.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-1">Growth Insights</p>
              <ul className="space-y-1">
                {concept.growth_insights.map((ins, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                    <span className="text-indigo-400 shrink-0 mt-0.5">→</span>{ins}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {concept?.rationale && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-1">Rationale</p>
              <p className="text-sm text-gray-600 leading-relaxed">{concept.rationale}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────
export default function ActivePlans({ plans, workspaceId }: Props) {
  if (!plans.length) return null

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-gray-900">
        Saved Campaign Plans <span className="ml-1 rounded-full bg-indigo-100 px-2.5 py-0.5 text-sm text-indigo-700">{plans.length}</span>
      </h2>
      <div className="space-y-3">
        {plans.map(plan => (
          <PlanCard key={plan.id} plan={plan} workspaceId={workspaceId} />
        ))}
      </div>
    </div>
  )
}
