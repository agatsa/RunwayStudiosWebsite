export default function Loading() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-red-100 animate-pulse" />
          <div className="space-y-2">
            <div className="h-5 w-40 rounded bg-gray-200 animate-pulse" />
            <div className="h-3 w-60 rounded bg-gray-100 animate-pulse" />
          </div>
        </div>
        <div className="h-8 w-40 rounded-lg bg-amber-50 animate-pulse" />
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border border-gray-200 p-4 space-y-2 animate-pulse">
            <div className="h-2.5 w-16 rounded bg-gray-100" />
            <div className="h-7 w-20 rounded bg-gray-200" />
            <div className="h-2 w-12 rounded bg-gray-100" />
          </div>
        ))}
      </div>

      {/* Fetching notice */}
      <div className="flex items-center gap-3 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3">
        <div className="flex gap-1">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="h-2 w-2 rounded-full bg-sky-400 inline-block animate-bounce"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </div>
        <p className="text-sm text-sky-700 font-medium">Loading YouTube channel data…</p>
        <p className="ml-auto text-xs text-sky-500">Results cached for 4 hours after first load</p>
      </div>

      {/* Video table skeleton */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 animate-pulse">
          <div className="h-4 w-32 rounded bg-gray-200" />
        </div>
        {[...Array(6)].map((_, i) => (
          <div key={i} className="flex items-center gap-4 border-b border-gray-100 px-4 py-3 animate-pulse">
            <div className="h-12 w-20 rounded bg-gray-100 shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3.5 w-56 rounded bg-gray-200" />
              <div className="h-2.5 w-32 rounded bg-gray-100" />
            </div>
            <div className="h-4 w-16 rounded bg-gray-100" />
            <div className="h-4 w-12 rounded bg-gray-100" />
          </div>
        ))}
      </div>
    </div>
  )
}
