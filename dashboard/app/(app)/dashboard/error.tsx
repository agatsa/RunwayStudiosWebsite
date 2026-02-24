'use client'

import { useEffect } from 'react'
import { AlertCircle } from 'lucide-react'

interface Props {
  error: Error & { digest?: string }
  reset: () => void
}

export default function DashboardError({ error, reset }: Props) {
  useEffect(() => {
    console.error('[Dashboard]', error)
  }, [error])

  return (
    <div className="flex h-64 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-red-200">
      <AlertCircle className="h-8 w-8 text-red-400" />
      <div className="text-center">
        <p className="font-medium text-gray-800">Failed to load dashboard</p>
        <p className="text-sm text-gray-500">{error.message}</p>
      </div>
      <button
        onClick={reset}
        className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
      >
        Try again
      </button>
    </div>
  )
}
