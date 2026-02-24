export default function CatalogLoading() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-8 w-48 rounded-lg bg-gray-100" />
        <div className="h-9 w-44 rounded-lg bg-gray-100" />
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-16 rounded-xl bg-gray-100" />
      ))}
    </div>
  )
}
