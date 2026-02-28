'use client'

import { useState } from 'react'
import { Megaphone } from 'lucide-react'
import { formatNumber } from '@/lib/utils'
import type { YouTubeVideo } from '@/lib/types'
import YouTubeVideoPanel from './YouTubeVideoPanel'
import PromoteAsAdModal from './PromoteAsAdModal'

interface Props {
  videos: YouTubeVideo[]
  workspaceId: string
}

type Filter = 'all' | 'shorts' | 'longform'

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function YouTubeVideoTable({ videos, workspaceId }: Props) {
  const [selected, setSelected] = useState<YouTubeVideo | null>(null)
  const [promoting, setPromoting] = useState<YouTubeVideo | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = videos.filter(v => {
    if (filter === 'shorts') return v.is_short === true
    if (filter === 'longform') return v.is_short !== true
    return true
  })

  if (!videos.length) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-400">
        No videos found. Upload a video to your YouTube channel to see it here.
      </div>
    )
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {/* Filter tabs */}
        <div className="flex items-center gap-1 border-b border-gray-100 bg-gray-50 px-4 py-2">
          {(['all', 'shorts', 'longform'] as Filter[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
                filter === f
                  ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {f === 'all' ? `All (${videos.length})` : f === 'shorts' ? `Shorts (${videos.filter(v => v.is_short).length})` : `Long-form (${videos.filter(v => !v.is_short).length})`}
            </button>
          ))}
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-semibold text-gray-600">
              <th className="px-4 py-3">Video</th>
              <th className="px-4 py-3 text-right">Views</th>
              <th className="hidden px-4 py-3 text-right sm:table-cell">Duration</th>
              <th className="hidden px-4 py-3 text-right md:table-cell">Likes</th>
              <th className="hidden px-4 py-3 text-right md:table-cell">Comments</th>
              <th className="px-4 py-3 text-right">Promote</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {filtered.map(v => (
              <tr
                key={v.video_id}
                className="cursor-pointer transition-colors hover:bg-gray-50"
              >
                <td className="px-4 py-3" onClick={() => setSelected(v)}>
                  <div className="flex items-center gap-3">
                    {v.thumbnail_url ? (
                      <img
                        src={v.thumbnail_url}
                        alt=""
                        className="h-10 w-16 shrink-0 rounded object-cover"
                      />
                    ) : (
                      <div className="h-10 w-16 shrink-0 rounded bg-gray-100" />
                    )}
                    <div className="min-w-0">
                      <span className="line-clamp-2 font-medium text-gray-900">
                        {v.title}
                      </span>
                      {v.is_short && (
                        <span className="inline-flex items-center rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700 mt-0.5">
                          SHORT
                        </span>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-medium text-gray-700" onClick={() => setSelected(v)}>
                  {formatNumber(v.view_count)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 sm:table-cell" onClick={() => setSelected(v)}>
                  {fmtDuration(v.duration_seconds)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 md:table-cell" onClick={() => setSelected(v)}>
                  {formatNumber(v.like_count)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 md:table-cell" onClick={() => setSelected(v)}>
                  {formatNumber(v.comment_count)}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={e => { e.stopPropagation(); setPromoting(v) }}
                    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
                  >
                    <Megaphone className="h-3 w-3" /> Promote
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="p-6 text-center text-sm text-gray-400">
            No {filter === 'shorts' ? 'Shorts' : 'long-form'} videos found.
          </div>
        )}
      </div>

      {selected && (
        <YouTubeVideoPanel
          video={selected}
          workspaceId={workspaceId}
          onClose={() => setSelected(null)}
        />
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
    </>
  )
}
