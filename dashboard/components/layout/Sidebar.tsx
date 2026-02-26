'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, CheckSquare, Package, Megaphone, BarChart2,
  PlayCircle, Zap, Settings, ShoppingBag, TrendingUp, Crosshair,
  MessageSquare, ClipboardList, Layout, Layers, Send, Mail, Activity,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface NavItem {
  label: string
  href: string
  icon: React.ElementType
  soon?: boolean
  badge?: boolean
}

interface NavSection {
  title?: string
  items: NavItem[]
}

const navSections: NavSection[] = [
  {
    items: [
      { label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
    ],
  },
  {
    title: 'CHANNELS',
    items: [
      { label: 'Meta Ads',    href: '/campaigns',       icon: Megaphone },
      { label: 'Google Ads',  href: '/google-ads',      icon: BarChart2 },
      { label: 'YouTube',     href: '/youtube',         icon: PlayCircle },
      { label: 'Marketplace', href: '/marketplace',     icon: ShoppingBag },
    ],
  },
  {
    title: 'INTELLIGENCE',
    items: [
      { label: 'Analytics',          href: '/analytics',        icon: Activity },
      { label: 'Search Trends',      href: '/search-trends',   icon: TrendingUp },
      { label: 'Competitor Intel',   href: '/competitor-intel', icon: Crosshair },
      { label: 'Comments & Reviews', href: '/comments',        icon: MessageSquare },
    ],
  },
  {
    title: 'PLANNING',
    items: [
      { label: 'Campaign Planner', href: '/campaign-planner', icon: ClipboardList },
      { label: 'Landing Pages',    href: '/landing-pages',    icon: Layout },
      { label: 'Awareness Funnel', href: '/awareness',        icon: Layers },
    ],
  },
  {
    title: 'OPERATIONS',
    items: [
      { label: 'Organic Posts', href: '/organic-posts', icon: Send },
      { label: 'Catalog',       href: '/catalog',       icon: Package },
      { label: 'Approvals',     href: '/approvals',     icon: CheckSquare, badge: true },
      { label: 'Email',         href: '/email-intel',   icon: Mail, soon: true },
    ],
  },
]

const settingsItem: NavItem = { label: 'Settings', href: '/settings', icon: Settings }

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

  const renderItem = (item: NavItem) => {
    const active = pathname.startsWith(item.href)
    const dest = wsId ? `${item.href}?ws=${wsId}` : item.href
    const showBadge = item.badge && pendingCount != null && pendingCount > 0

    return (
      <Link
        key={item.href}
        href={dest}
        className={cn(
          'flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
          active
            ? 'bg-brand-50 text-brand-700'
            : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
        )}
      >
        <span className="flex items-center gap-2.5 min-w-0">
          <item.icon className="h-4 w-4 shrink-0" />
          <span className="truncate">{item.label}</span>
        </span>
        <span className="flex items-center gap-1 shrink-0">
          {item.soon && (
            <span className="rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide bg-gray-100 text-gray-400">
              Soon
            </span>
          )}
          {showBadge && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
              {pendingCount}
            </span>
          )}
        </span>
      </Link>
    )
  }

  return (
    <aside className="flex h-full w-56 flex-col bg-white border-r border-gray-200">
      <div className="flex items-center gap-2 px-4 py-5 border-b border-gray-100">
        <Zap className="h-6 w-6 text-brand-500" />
        <span className="text-sm font-bold text-gray-900 leading-tight">
          Runway<br />Studios
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {navSections.map((section, si) => (
          <div key={si}>
            {section.title && (
              <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                {section.title}
              </p>
            )}
            <div className="space-y-0.5">
              {section.items.map(renderItem)}
            </div>
          </div>
        ))}
      </nav>

      <div className="px-2 pb-2 border-t border-gray-100 pt-2">
        {renderItem(settingsItem)}
        <p className="mt-2 px-3 text-xs text-gray-400">AI Growth OS v2.0</p>
      </div>
    </aside>
  )
}
