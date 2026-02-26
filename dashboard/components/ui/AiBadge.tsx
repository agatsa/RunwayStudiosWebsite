import { Sparkles } from 'lucide-react'

export function AiBadge({ label = 'AI' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-700 border border-sky-200">
      <Sparkles className="h-2.5 w-2.5" />
      {label}
    </span>
  )
}

export function AiContent({
  children,
  className = '',
  label,
}: {
  children: React.ReactNode
  className?: string
  label?: string
}) {
  return (
    <div className={`relative rounded-xl border border-sky-200 bg-sky-50 ${className}`}>
      <div className="absolute top-2.5 right-3 z-10">
        <AiBadge label={label} />
      </div>
      {children}
    </div>
  )
}
