'use client'

import { useState } from 'react'
import { formatNumber } from '@/lib/utils'
import type { YouTubeVideo } from '@/lib/types'
import YouTubeVideoPanel from './YouTubeVideoPanel'

interface Props {
  videos: YouTubeVideo[]
  workspaceId: string
}

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function YouTubeVideoTable({ videos, workspaceId }: Props) {
  const [selected, setSelected] = useState<YouTubeVideo | null>(null)

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
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <th className="px-4 py-3">Video</th>
              <th className="px-4 py-3 text-right">Views</th>
              <th className="hidden px-4 py-3 text-right sm:table-cell">Duration</th>
              <th className="hidden px-4 py-3 text-right md:table-cell">Likes</th>
              <th className="hidden px-4 py-3 text-right md:table-cell">Comments</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {videos.map(v => (
              <tr
                key={v.video_id}
                onClick={() => setSelected(v)}
                className="cursor-pointer transition-colors hover:bg-gray-50"
              >
                <td className="px-4 py-3">
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
                    <span className="line-clamp-2 font-medium text-gray-900">
                      {v.title}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-medium text-gray-700">
                  {formatNumber(v.view_count)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 sm:table-cell">
                  {fmtDuration(v.duration_seconds)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 md:table-cell">
                  {formatNumber(v.like_count)}
                </td>
                <td className="hidden px-4 py-3 text-right text-gray-500 md:table-cell">
                  {formatNumber(v.comment_count)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <YouTubeVideoPanel
          video={selected}
          workspaceId={workspaceId}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
