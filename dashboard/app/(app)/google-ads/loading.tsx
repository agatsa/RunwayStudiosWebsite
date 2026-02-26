export default function GoogleAdsLoading() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gray-200" />
          <div className="space-y-1.5">
            <div className="h-5 w-48 rounded bg-gray-200" />
            <div className="h-3 w-64 rounded bg-gray-100" />
          </div>
        </div>
        <div className="h-8 w-32 rounded-lg bg-gray-100" />
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-gray-100 bg-gray-50 p-4 space-y-3">
            <div className="h-8 w-8 rounded-lg bg-gray-200" />
            <div className="h-3 w-20 rounded bg-gray-200" />
            <div className="h-6 w-28 rounded bg-gray-200" />
            <div className="h-2.5 w-16 rounded bg-gray-100" />
          </div>
        ))}
      </div>

      {/* Action plan */}
      <div className="rounded-xl border border-yellow-100 bg-yellow-50/50 p-5 space-y-3">
        <div className="h-4 w-36 rounded bg-yellow-200" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-start gap-3">
            <div className="h-5 w-5 rounded-full bg-yellow-200 shrink-0" />
            <div className="h-4 rounded bg-yellow-100" style={{ width: `${75 + (i % 3) * 8}%` }} />
          </div>
        ))}
      </div>

      {/* Campaign table */}
      <div className="space-y-2">
        <div className="h-5 w-32 rounded bg-gray-200" />
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="h-10 bg-gray-50 border-b border-gray-200" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-12 border-b border-gray-100 bg-white" />
          ))}
        </div>
      </div>

      {/* Keywords */}
      <div className="space-y-2">
        <div className="h-5 w-36 rounded bg-gray-200" />
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="h-10 bg-gray-50 border-b border-gray-200" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-10 border-b border-gray-100 bg-white" />
          ))}
        </div>
      </div>
    </div>
  )
}
