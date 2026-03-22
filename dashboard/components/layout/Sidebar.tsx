'use client'

import Link from 'next/link'
import { usePathname, useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import {
  Home, BarChart2, Zap, Settings,
  Sparkles, ChevronDown, Check, Plus, Trash2,
  Target, Brain,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWorkspace } from '@/components/layout/WorkspaceProvider'
import CreditBalance from '@/components/billing/CreditBalance'
import { useChat } from '@/components/chat/ChatContext'

interface NavItem {
  label: string
  href: string
  icon: React.ElementType
  // Routes that count as "active" for this item
  activeRoutes?: string[]
}

const NAV_ITEMS: NavItem[] = [
  {
    label: 'Home',
    href: '/home',
    icon: Home,
    activeRoutes: ['/home', '/dashboard'],
  },
  {
    label: 'Data',
    href: '/data',
    icon: BarChart2,
    activeRoutes: ['/data', '/campaigns', '/google-ads', '/youtube', '/marketplace', '/analytics'],
  },
  {
    label: 'Plan',
    href: '/plan',
    icon: Target,
    activeRoutes: ['/plan', '/growth-os', '/campaign-planner', '/approvals', '/organic-posts'],
  },
  {
    label: 'Intel',
    href: '/intel',
    icon: Brain,
    activeRoutes: ['/intel', '/competitor-intel', '/landing-pages', '/comments', '/search-trends', '/seo', '/app-growth'],
  },
  {
    label: 'Setup',
    href: '/setup',
    icon: Settings,
    activeRoutes: ['/setup', '/settings', '/billing', '/products', '/email-intel', '/support'],
  },
]

export default function Sidebar() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const router = useRouter()
  const wsId = searchParams.get('ws') ?? ''
  const [wsSwitcherOpen, setWsSwitcherOpen] = useState(false)
  const switcherRef = useRef<HTMLDivElement>(null)
  const { current, workspaces, setCurrent, openCreateWorkspace } = useWorkspace()
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

  const isActive = (item: NavItem) => {
    const routes = item.activeRoutes ?? [item.href]
    return routes.some(r => pathname === r || pathname.startsWith(r + '/') || pathname.startsWith(r + '?'))
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
              {workspaces.length > 1 && current && (
                <div className="border-t border-gray-100 px-2 py-1.5">
                  <button
                    onClick={() => {
                      setWsSwitcherOpen(false)
                      if (!confirm(`Delete workspace "${current.name}"? This cannot be undone.`)) return
                      fetch('/api/workspace/delete', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workspace_id: current.id }),
                      }).then(r => r.json()).then(d => {
                        if (d.ok) {
                          const other = workspaces.find(w => w.id !== current.id)
                          if (other) {
                            setCurrent(other)
                            const params = new URLSearchParams()
                            params.set('ws', other.id)
                            window.location.href = `/home?${params.toString()}`
                          }
                        } else {
                          alert(d.detail ?? 'Failed to delete workspace')
                        }
                      })
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-red-50 transition-colors group"
                  >
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-red-200 group-hover:border-red-300">
                      <Trash2 className="h-3 w-3 text-red-400" />
                    </div>
                    <span className="text-xs font-medium text-red-400">Delete &quot;{current.name}&quot;</span>
                  </button>
                </div>
              )}
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

      {/* 5-item nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-4">
        <div className="space-y-1">
          {NAV_ITEMS.map(item => {
            const active = isActive(item)
            const dest = wsId ? `${item.href}?ws=${wsId}` : item.href
            return (
              <Link
                key={item.href}
                href={dest}
                className={cn(
                  'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                  active
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
                )}
              >
                <item.icon className={cn('h-4.5 w-4.5 shrink-0', active ? 'text-brand-600' : 'text-gray-400')} style={{ width: '1.125rem', height: '1.125rem' }} />
                <span>{item.label}</span>
                {active && (
                  <span className="ml-auto h-1.5 w-1.5 rounded-full bg-brand-500 shrink-0" />
                )}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* Footer */}
      <div className="px-2 pb-3 border-t border-gray-100 pt-2">
        {wsId && <CreditBalance wsId={wsId} />}
        <p className="mt-2 px-3 text-[10px] text-gray-400">AI Growth OS v2.0</p>
      </div>
    </aside>
  )
}
