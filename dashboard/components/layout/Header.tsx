'use client'

import { useRouter, usePathname } from 'next/navigation'
import { UserButton } from '@clerk/nextjs'
import { useWorkspace } from './WorkspaceProvider'
import type { Workspace } from '@/lib/types'

export default function Header() {
  const { workspaces, current, setCurrent, loading } = useWorkspace()
  const router = useRouter()
  const pathname = usePathname()

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const ws = workspaces.find((w: Workspace) => w.id === e.target.value)
    if (!ws) return
    setCurrent(ws)
    // Push workspace into URL so server components re-fetch with new ID
    router.push(`${pathname}?ws=${ws.id}`)
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-6">
      <div className="flex items-center gap-3">
        <label htmlFor="ws-select" className="text-sm text-gray-500 shrink-0">
          Workspace
        </label>
        {loading ? (
          <div className="h-8 w-44 animate-pulse rounded bg-gray-100" />
        ) : (
          <select
            id="ws-select"
            className="h-8 rounded border border-gray-200 bg-white px-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={current?.id ?? ''}
            onChange={handleChange}
          >
            {workspaces.length === 0 && (
              <option value="">No workspaces found</option>
            )}
            {workspaces.map((ws: Workspace) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <UserButton afterSignOutUrl="/sign-in" />
    </header>
  )
}
