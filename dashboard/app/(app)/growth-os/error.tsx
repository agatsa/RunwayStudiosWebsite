'use client'

import { AlertTriangle } from 'lucide-react'

export default function GrowthOSError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="rounded-xl border border-red-200 bg-red-50 p-8 text-center">
        <AlertTriangle className="h-10 w-10 text-red-400 mx-auto mb-4" />
        <h2 className="text-base font-semibold text-red-800 mb-2">Failed to load Growth OS</h2>
        <p className="text-sm text-red-600 mb-4">{error.message}</p>
        <button
          onClick={reset}
          className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-500 transition-colors"
        >
          Retry
        </button>
      </div>
    </div>
  )
}
