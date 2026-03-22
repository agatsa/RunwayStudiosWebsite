'use client'

import Link from 'next/link'
import { ExternalLink, MessageSquare } from 'lucide-react'

export default function CommentsContent({ wsId }: { wsId: string }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Comments & Reviews</h2>
        <Link href={`/comments?ws=${wsId}`} className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline">
          Full view <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 py-12 text-center">
        <MessageSquare className="h-8 w-8 text-gray-300" />
        <p className="text-sm font-medium text-gray-700">Comment intelligence</p>
        <p className="text-xs text-gray-500 max-w-xs">
          Auto-classifies comments on your Meta ads: trust issues, purchase intent, objections, and positive reviews.
        </p>
        <Link
          href={`/comments?ws=${wsId}`}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          View comment intelligence
        </Link>
      </div>
    </div>
  )
}
