export default function Loading() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-1.5 animate-pulse">
        <div className="h-6 w-32 rounded bg-gray-200" />
        <div className="h-3.5 w-56 rounded bg-gray-100" />
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border border-gray-200 bg-white p-4 space-y-2 animate-pulse">
            <div className="flex items-center justify-between">
              <div className="h-2.5 w-16 rounded bg-gray-100" />
              <div className="h-7 w-7 rounded-lg bg-gray-100" />
            </div>
            <div className="h-7 w-24 rounded bg-gray-200" />
            <div className="h-2 w-20 rounded bg-gray-100" />
          </div>
        ))}
      </div>

      {/* Campaign table skeleton */}
      <div className="space-y-3">
        <div className="h-4 w-36 rounded bg-gray-200 animate-pulse" />
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 animate-pulse">
            <div className="h-3 w-full rounded bg-gray-100" />
          </div>
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex items-center gap-4 border-b border-gray-100 px-4 py-3.5 animate-pulse">
              <div className="flex-1 space-y-1.5">
                <div className="h-3.5 w-52 rounded bg-gray-200" />
                <div className="h-2.5 w-36 rounded bg-gray-100" />
              </div>
              <div className="h-5 w-16 rounded-full bg-gray-100" />
              <div className="h-4 w-20 rounded bg-gray-100" />
              <div className="h-4 w-16 rounded bg-gray-100" />
              <div className="h-8 w-20 rounded-lg bg-gray-100" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
