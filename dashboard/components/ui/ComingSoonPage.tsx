import { LucideIcon, Clock, Sparkles } from 'lucide-react'
import Link from 'next/link'

interface Feature {
  label: string
  description?: string
}

interface Props {
  icon: LucideIcon
  title: string
  subtitle: string
  description: string
  blockedBy: string       // e.g. "Google Ads API approval"
  blockedByDetail?: string
  features?: Feature[]
  etaLabel?: string       // e.g. "Coming Q2 2026"
  workspaceId?: string
  ctaLabel?: string
  ctaHref?: string
}

export default function ComingSoonPage({
  icon: Icon,
  title,
  subtitle,
  description,
  blockedBy,
  blockedByDetail,
  features = [],
  etaLabel = 'Coming Soon',
  workspaceId,
  ctaLabel,
  ctaHref,
}: Props) {
  const dest = ctaHref
    ? workspaceId ? `${ctaHref}?ws=${workspaceId}` : ctaHref
    : null

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-xl w-full text-center">

        {/* Icon */}
        <div className="flex justify-center mb-6">
          <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-br from-brand-50 to-indigo-50 border border-brand-100">
            <Icon className="h-9 w-9 text-brand-600" />
            <span className="absolute -top-2 -right-2 flex h-7 w-7 items-center justify-center rounded-full bg-amber-100 border-2 border-white">
              <Clock className="h-3.5 w-3.5 text-amber-600" />
            </span>
          </div>
        </div>

        {/* Title */}
        <h1 className="text-2xl font-bold text-gray-900 mb-1">{title}</h1>
        <p className="text-sm font-medium text-brand-600 mb-3">{subtitle}</p>
        <p className="text-sm text-gray-500 leading-relaxed mb-6 max-w-md mx-auto">{description}</p>

        {/* Blocked by banner */}
        <div className="inline-flex items-center gap-2 rounded-xl bg-amber-50 border border-amber-200 px-4 py-2.5 text-sm font-medium text-amber-700 mb-6">
          <Clock className="h-4 w-4 text-amber-500 shrink-0" />
          <span>Waiting for: <strong>{blockedBy}</strong></span>
        </div>

        {blockedByDetail && (
          <p className="text-xs text-gray-400 mb-6 max-w-sm mx-auto">{blockedByDetail}</p>
        )}

        {/* Features preview */}
        {features.length > 0 && (
          <div className="mt-2 mb-7 rounded-2xl border border-gray-100 bg-gray-50 p-5 text-left">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="h-4 w-4 text-brand-500" />
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">What you&apos;ll get</span>
            </div>
            <ul className="space-y-2.5">
              {features.map(f => (
                <li key={f.label} className="flex items-start gap-2.5">
                  <span className="mt-0.5 h-4 w-4 rounded-full bg-brand-100 text-brand-600 flex items-center justify-center text-[10px] font-bold shrink-0">✓</span>
                  <div>
                    <span className="text-sm font-medium text-gray-700">{f.label}</span>
                    {f.description && <p className="text-xs text-gray-400 mt-0.5">{f.description}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ETA + CTA */}
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <span className="rounded-full bg-gray-100 px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">
            {etaLabel}
          </span>
          {dest && ctaLabel && (
            <Link
              href={dest}
              className="rounded-full bg-brand-600 px-5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              {ctaLabel}
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
