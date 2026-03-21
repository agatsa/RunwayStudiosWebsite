import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'

interface Action {
  label: string
  href: string
  primary?: boolean
}

interface Props {
  icon: LucideIcon
  iconBg?: string
  title: string
  description: string
  actions?: Action[]
  hint?: string
}

export default function EmptyStateCard({ icon: Icon, iconBg = 'bg-gray-100', title, description, actions = [], hint }: Props) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50/50 px-6 py-14 text-center">
      <div className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl ${iconBg}`}>
        <Icon className="h-7 w-7 text-white" />
      </div>
      <h3 className="text-base font-bold text-gray-900 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 max-w-sm mb-6 leading-relaxed">{description}</p>
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-3 justify-center">
          {actions.map(a => (
            <Link
              key={a.href}
              href={a.href}
              className={
                a.primary
                  ? 'inline-flex items-center gap-1.5 rounded-xl bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-gray-700 transition-colors'
                  : 'inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors'
              }
            >
              {a.label}
            </Link>
          ))}
        </div>
      )}
      {hint && <p className="mt-4 text-xs text-gray-400">{hint}</p>}
    </div>
  )
}
