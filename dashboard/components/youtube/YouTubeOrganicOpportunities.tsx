'use client'

import { useEffect, useState } from 'react'
import { Loader2, TrendingUp } from 'lucide-react'
import { formatNumber, formatINR } from '@/lib/utils'
import PromoteAsAdModal from './PromoteAsAdModal'

interface Opportunity {
  video_id: string
  title: string
  thumbnail_url: string | null
  view_count: number
  like_count: number
  avg_retention: number
  avg_ctr: number
  duration_seconds: number
  score: number
  budget_min: number
  budget_max: number
}

interface Props {
  workspaceId: string
}

function scoreLabel(score: number) {
  if (score >= 0.7) return { label: 'High potential', cls: 'bg-green-100 text-green-700' }
  if (score >= 0.4) return { label: 'Medium potential', cls: 'bg-yellow-100 text-yellow-700' }
  return { label: 'Low potential', cls: 'bg-gray-100 text-gray-500' }
}

export default function YouTubeOrganicOpportunities({ workspaceId }: Props) {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [available, setAvailable] = useState(true)
  const [promoting, setPromoting] = useState<Opportunity | null>(null)


  useEffect(() => {
    fetch(`/api/youtube/organic-opportunities?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(d => {
        setAvailable(d.available)
        setOpportunities(d.opportunities ?? [])
      })
      .catch(() => setAvailable(false))
      .finally(() => setLoading(false))
  }, [workspaceId])

  return (
    <div className="rounded-xl border border-red-100 bg-red-50/40 p-5">
      <div className="mb-1 flex items-center gap-2">
        <TrendingUp className="h-4 w-4 text-red-600" />
        <h2 className="text-sm font-semibold text-gray-900">Organic → Paid Opportunities</h2>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Your best organic videos are the safest paid creative — real audiences already validated them
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Analysing videos…
        </div>
      ) : !available || opportunities.length === 0 ? (
        <div className="text-sm text-gray-400 text-center py-4">
          No videos found. Sync your YouTube channel to see promotion opportunities.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {opportunities.slice(0, 3).map((opp, i) => {
            const { label, cls } = scoreLabel(opp.score)
            return (
              <div
                key={opp.video_id}
                className="rounded-xl bg-white border border-red-100 overflow-hidden flex flex-col"
              >
                {/* Thumbnail */}
                <div className="relative aspect-video bg-gray-100">
                  {opp.thumbnail_url ? (
                    <img src={opp.thumbnail_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-gray-100">
                      <span className="text-2xl text-gray-300">▶</span>
                    </div>
                  )}
                  <div className="absolute top-1.5 left-1.5">
                    <span className="rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-bold text-white">
                      #{i + 1}
                    </span>
                  </div>
                  <div className="absolute bottom-1.5 right-1.5">
                    <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
                      {label}
                    </span>
                  </div>
                </div>

                {/* Content */}
                <div className="p-3 flex-1 flex flex-col gap-2">
                  <p className="text-xs font-semibold text-gray-900 line-clamp-2 leading-tight">
                    {opp.title}
                  </p>

                  <div className="grid grid-cols-3 gap-1 text-center">
                    <div className="rounded bg-gray-50 px-1 py-1">
                      <p className="text-[9px] text-gray-400">Views</p>
                      <p className="text-xs font-bold text-gray-800">{formatNumber(opp.view_count)}</p>
                    </div>
                    <div className="rounded bg-gray-50 px-1 py-1">
                      <p className="text-[9px] text-gray-400">Avg CTR</p>
                      <p className={`text-xs font-bold ${opp.avg_ctr >= 4 ? 'text-green-700' : 'text-gray-800'}`}>
                        {opp.avg_ctr > 0 ? `${opp.avg_ctr}%` : '—'}
                      </p>
                    </div>
                    <div className="rounded bg-gray-50 px-1 py-1">
                      <p className="text-[9px] text-gray-400">Retention</p>
                      <p className={`text-xs font-bold ${opp.avg_retention >= 35 ? 'text-green-700' : 'text-gray-800'}`}>
                        {opp.avg_retention > 0 ? `${opp.avg_retention}%` : '—'}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-lg bg-red-50 border border-red-100 px-2.5 py-2 text-center">
                    <p className="text-[9px] text-gray-500">Suggested Ad Budget</p>
                    <p className="text-sm font-bold text-red-700">
                      {formatINR(opp.budget_min)} – {formatINR(opp.budget_max)}
                    </p>
                  </div>

                  <button
                    onClick={() => setPromoting(opp)}
                    className="mt-auto w-full rounded-lg bg-red-600 py-1.5 text-xs font-medium text-white hover:bg-red-700 transition-colors"
                  >
                    Promote as Ad
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {promoting && (
        <PromoteAsAdModal
          videoId={promoting.video_id}
          videoTitle={promoting.title}
          thumbnailUrl={promoting.thumbnail_url ?? undefined}
          workspaceId={workspaceId}
          onClose={() => setPromoting(null)}
        />
      )}
    </div>
  )
}
