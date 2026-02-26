'use client'

export function AiThinkingLoader({ message = 'AI is thinking…' }: { message?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3.5">
      <div className="flex gap-1 shrink-0">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="h-2 w-2 rounded-full bg-sky-400 inline-block animate-bounce"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </div>
      <p className="text-sm font-medium text-sky-700">{message}</p>
    </div>
  )
}

export function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-4 space-y-2.5 animate-pulse">
      <div className="h-3 w-20 rounded bg-gray-100" />
      <div className="h-6 w-28 rounded bg-gray-200" />
      <div className="h-2.5 w-16 rounded bg-gray-100" />
    </div>
  )
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 border-b border-gray-100 px-4 py-3 animate-pulse">
      <div className="flex-1 space-y-1.5">
        <div className="h-3 w-48 rounded bg-gray-200" />
        <div className="h-2.5 w-32 rounded bg-gray-100" />
      </div>
      <div className="h-5 w-16 rounded-full bg-gray-100" />
      <div className="h-3 w-20 rounded bg-gray-100" />
    </div>
  )
}

export function SkeletonKpiCard() {
  return (
    <div className="rounded-xl border border-gray-200 p-4 animate-pulse">
      <div className="h-2.5 w-16 rounded bg-gray-100 mb-2" />
      <div className="h-7 w-24 rounded bg-gray-200 mb-1" />
      <div className="h-2 w-14 rounded bg-gray-100" />
    </div>
  )
}
