export default function DashboardLoading() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* KPI cards skeleton */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-gray-100" />
        ))}
      </div>
      {/* Charts skeleton */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="h-64 rounded-xl bg-gray-100" />
        <div className="h-64 rounded-xl bg-gray-100" />
      </div>
      {/* Table skeleton */}
      <div className="h-48 rounded-xl bg-gray-100" />
    </div>
  )
}
