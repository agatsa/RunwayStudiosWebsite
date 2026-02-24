'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard,
  CheckSquare,
  Package,
  Megaphone,
  PlayCircle,
  Zap,
  Settings,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const baseNavItems = [
  { label: 'Dashboard',  href: '/dashboard',  icon: LayoutDashboard },
  { label: 'Approvals',  href: '/approvals',  icon: CheckSquare },
  { label: 'Catalog',    href: '/catalog',    icon: Package },
  { label: 'Campaigns',  href: '/campaigns',  icon: Megaphone },
]

const youtubeItem = { label: 'YouTube', href: '/youtube', icon: PlayCircle }

const settingsItem = { label: 'Settings', href: '/settings', icon: Settings }

const showYoutube = process.env.NEXT_PUBLIC_SHOW_YOUTUBE === 'true'

const navItems = showYoutube
  ? [...baseNavItems, youtubeItem, settingsItem]
  : [...baseNavItems, settingsItem]

export default function Sidebar() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const [pendingCount, setPendingCount] = useState<number | null>(null)

  useEffect(() => {
    if (!wsId) return
    const load = async () => {
      try {
        const res = await fetch(`/api/actions/list?workspace_id=${wsId}&status=pending&limit=50`)
        const data = await res.json()
        setPendingCount(data.count ?? 0)
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [wsId])

  return (
    <aside className="flex h-full w-56 flex-col bg-white border-r border-gray-200">
      <div className="flex items-center gap-2 px-4 py-5 border-b border-gray-100">
        <Zap className="h-6 w-6 text-brand-500" />
        <span className="text-sm font-bold text-gray-900 leading-tight">
          Runway<br />Studios
        </span>
      </div>

      <nav className="flex-1 px-2 py-4 space-y-1">
        {navItems.map(({ label, href, icon: Icon }) => {
          const active = pathname.startsWith(href)
          const dest = wsId ? `${href}?ws=${wsId}` : href
          const showBadge = label === 'Approvals' && pendingCount != null && pendingCount > 0
          return (
            <Link
              key={href}
              href={dest}
              className={cn(
                'flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-brand-50 text-brand-700'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
              )}
            >
              <span className="flex items-center gap-3">
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </span>
              {showBadge && (
                <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
                  {pendingCount}
                </span>
              )}
            </Link>
          )
        })}
      </nav>

      <div className="px-4 py-3 border-t border-gray-100">
        <p className="text-xs text-gray-400">AI Growth OS v1.0</p>
      </div>
    </aside>
  )
}
