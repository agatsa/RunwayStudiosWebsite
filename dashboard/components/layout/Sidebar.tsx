'use client'

import Link from 'next/link'
import { usePathname, useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import {
  LayoutDashboard, CheckSquare, Package, Megaphone, BarChart2,
  PlayCircle, Zap, Settings, ShoppingBag, TrendingUp, Crosshair,
  MessageSquare, ClipboardList, Layout, Layers, Send, Mail,
  Sparkles, CreditCard, LifeBuoy, Search, Smartphone,
  ChevronDown, Check, Plus,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkspace } from '@/components/layout/WorkspaceProvider'
import CreditBalance from '@/components/billing/CreditBalance'
import { useChat } from '@/components/chat/ChatContext'

interface NavItem {
  label: string
  href: string
  icon: React.ElementType
  soon?: boolean
  limited?: boolean   // amber "API Soon" badge — partial functionality
  badge?: boolean
  highlight?: boolean
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
      { label: 'Google Ads',  href: '/google-ads',      icon: BarChart2,  limited: true },
      { label: 'YouTube',     href: '/youtube',         icon: PlayCircle },
      { label: 'Marketplace', href: '/marketplace',     icon: ShoppingBag },
    ],
  },
  {
    title: 'GROWTH OS',
    items: [
      { label: 'Command Center', href: '/growth-os', icon: Sparkles, highlight: true },
      { label: 'App Growth',     href: '/app-growth', icon: Smartphone },
    ],
  },
  {
    title: 'INTELLIGENCE',
    items: [
      { label: 'Search Trends',      href: '/search-trends',    icon: TrendingUp,   soon: true },
      { label: 'Competitor Intel',   href: '/competitor-intel', icon: Crosshair },
      { label: 'Comments & Reviews', href: '/comments',         icon: MessageSquare },
      { label: 'SEO',                href: '/seo',              icon: Search },
    ],
  },
  {
    title: 'PLANNING',
    items: [
      { label: 'Campaign Planner', href: '/campaign-planner', icon: ClipboardList },
      { label: 'Landing Pages',    href: '/landing-pages',    icon: Layout,       soon: true },
      { label: 'Awareness Funnel', href: '/awareness',        icon: Layers,       soon: true },
    ],
  },
  {
    title: 'OPERATIONS',
    items: [
      { label: 'Organic Posts', href: '/organic-posts', icon: Send },
      { label: 'Products',      href: '/products',      icon: Package },
      { label: 'Approvals',     href: '/approvals',     icon: CheckSquare, badge: true },
      { label: 'Email',         href: '/email-intel',   icon: Mail },
      { label: 'Billing',       href: '/billing',       icon: CreditCard },
      { label: 'Support',       href: '/support',       icon: LifeBuoy },
    ],
  },
]

const settingsItem: NavItem = { label: 'Settings', href: '/settings', icon: Settings }

const CHANNEL_ORDER: Record<string, string[]> = {
  d2c:     ['Meta Ads', 'Google Ads', 'Marketplace', 'YouTube'],
  creator: ['YouTube', 'Competitor Intel', 'Meta Ads', 'Google Ads', 'Marketplace'],
  agency:  ['Meta Ads', 'Google Ads', 'YouTube', 'Marketplace'],
  saas:    ['Meta Ads', 'Google Ads', 'YouTube', 'Marketplace'],
  media:   ['YouTube', 'Meta Ads', 'Google Ads', 'Marketplace'],
}

function sortedChannels(items: NavItem[], wsType: string): NavItem[] {
  const order = CHANNEL_ORDER[wsType] ?? CHANNEL_ORDER['d2c']
  return [...items].sort((a, b) => {
    const ai = order.indexOf(a.label)
    const bi = order.indexOf(b.label)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
}

export default function Sidebar() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const router = useRouter()
  const wsId = searchParams.get('ws') ?? ''
  const [pendingCount, setPendingCount] = useState<number | null>(null)
  const [wsSwitcherOpen, setWsSwitcherOpen] = useState(false)
  const switcherRef = useRef<HTMLDivElement>(null)
  const { current, workspaces, setCurrent, openCreateWorkspace } = useWorkspace()
  const wsType = current?.workspace_type ?? 'd2c'
  const { setChatOpen } = useChat()

  // Close switcher on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (switcherRef.current && !switcherRef.current.contains(e.target as Node)) {
        setWsSwitcherOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSwitchWorkspace = (ws: typeof current) => {
    if (!ws) return
    setCurrent(ws)
    setWsSwitcherOpen(false)
    const params = new URLSearchParams(searchParams.toString())
    params.set('ws', ws.id)
    router.replace(`${pathname}?${params.toString()}`)
  }

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
          active && item.highlight
            ? 'bg-amber-50 text-amber-700'
            : active
            ? 'bg-brand-50 text-brand-700'
            : item.highlight
            ? 'text-amber-600 hover:bg-amber-50 hover:text-amber-700'
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
          {item.limited && (
            <span className="rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide bg-amber-100 text-amber-600">
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
      {/* Brand + Workspace Switcher */}
      <div className="px-3 py-3 border-b border-gray-100">
        {/* Logo row */}
        <div className="flex items-center gap-2 px-1 mb-2">
          <Zap className="h-5 w-5 text-brand-500 shrink-0" />
          <span className="text-xs font-bold text-gray-900 tracking-wide uppercase">Runway Studios</span>
        </div>
        {/* Workspace dropdown */}
        <div ref={switcherRef} className="relative">
          <button
            onClick={() => setWsSwitcherOpen(v => !v)}
            className="flex w-full items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-left hover:bg-gray-100 transition-colors"
          >
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-600 text-[10px] font-bold text-white uppercase">
              {current?.name?.[0] ?? '?'}
            </div>
            <span className="flex-1 truncate text-xs font-semibold text-gray-800">
              {current?.name ?? 'Select workspace'}
            </span>
            <ChevronDown className={cn('h-3.5 w-3.5 text-gray-400 transition-transform shrink-0', wsSwitcherOpen && 'rotate-180')} />
          </button>

          {wsSwitcherOpen && (
            <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-xl border border-gray-200 bg-white shadow-lg overflow-hidden">
              <div className="px-2 py-1.5">
                <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">Workspaces</p>
                {workspaces.map(ws => (
                  <button
                    key={ws.id}
                    onClick={() => handleSwitchWorkspace(ws)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-100 text-[10px] font-bold text-brand-700 uppercase">
                      {ws.name?.[0] ?? '?'}
                    </div>
                    <span className="flex-1 truncate text-xs font-medium text-gray-800">{ws.name}</span>
                    {ws.id === current?.id && <Check className="h-3.5 w-3.5 text-brand-600 shrink-0" />}
                  </button>
                ))}
              </div>
              <div className="border-t border-gray-100 px-2 py-1.5">
                <button
                  onClick={() => { setWsSwitcherOpen(false); openCreateWorkspace() }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-gray-50 transition-colors"
                >
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-dashed border-gray-300">
                    <Plus className="h-3 w-3 text-gray-400" />
                  </div>
                  <span className="text-xs font-medium text-gray-500">New workspace</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Ask ARIA button */}
      <div className="px-2 pt-3 pb-1">
        <button
          onClick={() => setChatOpen(true)}
          className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98]"
          style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}
        >
          <Sparkles className="h-4 w-4 shrink-0" />
          <span className="flex-1 text-left">Ask ARIA</span>
          <span className="rounded px-1.5 py-0.5 text-[9px] font-bold bg-white/20 text-white/80 tracking-wide">⌘K</span>
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {navSections.map((section, si) => {
          const items = section.title === 'CHANNELS'
            ? sortedChannels(section.items, wsType)
            : section.items
          const topLabel = section.title === 'CHANNELS' ? items[0]?.label : null
          return (
            <div key={si}>
              {section.title && (
                <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  {section.title}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map(item => {
                  const isTop = item.label === topLabel
                  const active = pathname.startsWith(item.href)
                  const dest = wsId ? `${item.href}?ws=${wsId}` : item.href
                  const showBadge = item.badge && pendingCount != null && pendingCount > 0
                  return (
                    <Link
                      key={item.href}
                      href={dest}
                      className={cn(
                        'flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                        active && item.highlight
                          ? 'bg-amber-50 text-amber-700'
                          : active
                          ? 'bg-brand-50 text-brand-700'
                          : item.highlight
                          ? 'text-amber-600 hover:bg-amber-50 hover:text-amber-700'
                          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
                      )}
                    >
                      <span className="flex items-center gap-2.5 min-w-0">
                        <item.icon className="h-4 w-4 shrink-0" />
                        <span className="truncate">{item.label}</span>
                        {isTop && !active && (
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />
                        )}
                      </span>
                      <span className="flex items-center gap-1 shrink-0">
                        {item.soon && (
                          <span className="rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide bg-gray-100 text-gray-400">
                            Soon
                          </span>
                        )}
                        {item.limited && (
                          <span className="rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide bg-amber-100 text-amber-600">
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
                })}
              </div>
            </div>
          )
        })}
      </nav>

      <div className="px-2 pb-2 border-t border-gray-100 pt-2">
        {wsId && <CreditBalance wsId={wsId} />}
        {renderItem(settingsItem)}
        <p className="mt-2 px-3 text-xs text-gray-400">AI Growth OS v2.0</p>
      </div>
    </aside>
  )
}
