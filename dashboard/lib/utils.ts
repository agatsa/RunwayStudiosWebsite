import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatINR(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value == null || isNaN(value)) return '—'
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: decimals,
  }).format(value)
}

export function formatROAS(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '—'
  return `${value.toFixed(2)}x`
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '—'
  return `${value.toFixed(2)}%`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export function statusColor(status: string): string {
  const s = status?.toLowerCase()
  if (s === 'active')    return 'text-green-600'
  if (s === 'paused')    return 'text-yellow-600'
  if (s === 'pending')   return 'text-blue-600'
  if (s === 'approved')  return 'text-green-600'
  if (s === 'rejected')  return 'text-red-600'
  if (s === 'failed')    return 'text-red-600'
  return 'text-gray-500'
}

/**
 * Parse **bold** markdown in AI-generated text into React elements.
 * Usage: {renderBold(text)} inside JSX.
 */
export function renderBold(text: string): (string | { bold: string; key: number })[] {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? { bold: part, key: i } : part
  )
}

export function fillDateRange(
  daily: import('./types').DailyKpiRow[],
  days: number,
  platforms: string[] = ['meta'],
): import('./types').DailyKpiRow[] {
  const filled: import('./types').DailyKpiRow[] = []
  const today = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setUTCDate(d.getUTCDate() - i)
    const dateStr = d.toISOString().split('T')[0]
    for (const platform of platforms) {
      const existing = daily.find(r => r.date === dateStr && r.platform === platform)
      filled.push(existing ?? {
        date: dateStr, platform,
        spend: 0, impressions: 0, clicks: 0,
        conversions: 0, revenue: 0, roas: 0, ctr: 0,
      })
    }
  }
  return filled
}
