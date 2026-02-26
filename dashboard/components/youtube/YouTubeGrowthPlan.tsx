import { AiBadge } from '@/components/ui/AiBadge'

interface Props {
  steps: string[]
}

export default function YouTubeGrowthPlan({ steps }: Props) {
  if (!steps.length) return null

  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 p-5">
      <div className="mb-4 flex items-center gap-2">
        <AiBadge label="AI Growth Plan" />
        <h2 className="text-sm font-semibold text-gray-900">
          5-Step YouTube Growth Plan
        </h2>
      </div>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-600 text-xs font-bold text-white">
              {i + 1}
            </span>
            <p className="text-sm leading-relaxed text-gray-700">{step}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}
