'use client'

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import type { Workspace } from '@/lib/types'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  current: Workspace | null
  setCurrent: (ws: Workspace) => void
  loading: boolean
  refresh: () => void
}

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  current: null,
  setCurrent: () => {},
  loading: true,
  refresh: () => {},
})

export function useWorkspace() {
  return useContext(WorkspaceContext)
}

export default function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [current, setCurrent_] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Keep a ref to always read the latest searchParams without making it a dep of load()
  const searchParamsRef = useRef(searchParams)
  useEffect(() => { searchParamsRef.current = searchParams }, [searchParams])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/workspaces')
      const data = await res.json()
      const ws: Workspace[] = data.workspaces ?? []
      setWorkspaces(ws)

      // Honour ?ws= param first, then localStorage, then first workspace
      const urlWs = searchParamsRef.current.get('ws')
      const savedId = urlWs ?? (typeof window !== 'undefined' ? localStorage.getItem('runway_workspace_id') : null)
      const selected = ws.find(w => w.id === savedId) ?? ws[0] ?? null
      setCurrent_(selected)

      // If URL has no ws param but we have a workspace, inject it — preserve all other params
      if (selected && !urlWs) {
        const params = new URLSearchParams(searchParamsRef.current.toString())
        params.set('ws', selected.id)
        router.replace(`${pathname}?${params.toString()}`)
      }
    } catch {
      // silently ignore
    } finally {
      setLoading(false)
    }
  }, [pathname, router]) // searchParams intentionally excluded — read via ref to avoid re-firing on filter changes

  useEffect(() => { load() }, [load])

  const setCurrent = (ws: Workspace) => {
    setCurrent_(ws)
    if (typeof window !== 'undefined') {
      localStorage.setItem('runway_workspace_id', ws.id)
    }
  }

  return (
    <WorkspaceContext.Provider value={{ workspaces, current, setCurrent, loading, refresh: load }}>
      {children}
    </WorkspaceContext.Provider>
  )
}
