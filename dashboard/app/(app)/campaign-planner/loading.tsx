export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-xl bg-gray-200" />
        <div className="space-y-2">
          <div className="h-5 w-48 rounded bg-gray-200" />
          <div className="h-3 w-72 rounded bg-gray-100" />
        </div>
      </div>
      {/* Main content block */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="h-12 bg-gray-50 border-b border-gray-200" />
        <div className="p-4 space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-10 rounded-lg bg-gray-100" />
          ))}
        </div>
      </div>
      {/* Cards */}
      <div className="grid grid-cols-2 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border border-gray-200 p-5 space-y-3">
            <div className="h-4 w-32 rounded bg-gray-200" />
            <div className="h-3 w-full rounded bg-gray-100" />
            <div className="h-3 w-3/4 rounded bg-gray-100" />
          </div>
        ))}
      </div>
    </div>
  )
}
