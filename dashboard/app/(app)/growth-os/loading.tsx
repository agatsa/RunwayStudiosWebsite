import { Sparkles } from 'lucide-react'

export default function GrowthOSLoading() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-300 animate-pulse" />
            <div className="h-7 w-64 bg-gray-100 rounded animate-pulse" />
          </div>
          <div className="h-4 w-40 bg-gray-100 rounded animate-pulse" />
        </div>
        <div className="h-9 w-32 bg-gray-100 rounded-xl animate-pulse" />
      </div>

      {/* Source badges skeleton */}
      <div className="rounded-xl border bg-white p-4 space-y-2">
        <div className="h-3 w-32 bg-gray-100 rounded animate-pulse" />
        <div className="flex gap-2">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="h-6 w-20 bg-gray-100 rounded-full animate-pulse" />
          ))}
        </div>
      </div>

      {/* Action card skeletons */}
      {['HIGH IMPACT', 'MEDIUM IMPACT'].map(label => (
        <div key={label} className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-gray-200" />
            <div className="h-3 w-24 bg-gray-100 rounded animate-pulse" />
          </div>
          {[1, 2, 3].map(i => (
            <div key={i} className="rounded-xl border bg-white p-4 space-y-2 animate-pulse">
              <div className="flex gap-2">
                <div className="h-5 w-16 bg-gray-100 rounded-md" />
                <div className="h-5 w-20 bg-gray-100 rounded-md" />
              </div>
              <div className="h-4 w-3/4 bg-gray-100 rounded" />
              <div className="h-3 w-full bg-gray-50 rounded" />
              <div className="h-3 w-1/2 bg-gray-50 rounded" />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
