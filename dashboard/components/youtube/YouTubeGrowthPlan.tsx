interface Props {
  steps: string[]
}

export default function YouTubeGrowthPlan({ steps }: Props) {
  if (!steps.length) return null

  return (
    <div className="rounded-xl border border-red-100 bg-white p-5">
      <div className="mb-4 flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-red-600">
          <span className="text-xs font-bold text-white">AI</span>
        </div>
        <h2 className="text-sm font-semibold text-gray-900">
          5-Step YouTube Growth Plan
        </h2>
      </div>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-600 text-xs font-bold text-white">
              {i + 1}
            </span>
            <p className="text-sm leading-relaxed text-gray-700">{step}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}
