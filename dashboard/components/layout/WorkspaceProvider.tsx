'use client'

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import type { Workspace } from '@/lib/types'
import OnboardingModal from '@/components/onboarding/OnboardingModal'
import SetupWorkspaceModal from '@/components/onboarding/SetupWorkspaceModal'
import AIChatPanel from '@/components/chat/AIChatPanel'
import PageLoader from '@/components/ui/PageLoader'
import { ChatProvider } from '@/components/chat/ChatContext'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  current: Workspace | null
  setCurrent: (ws: Workspace) => void
  loading: boolean
  refresh: () => void
  openCreateWorkspace: () => void
}

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  current: null,
  setCurrent: () => {},
  loading: true,
  refresh: () => {},
  openCreateWorkspace: () => {},
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

  const [showCreateWorkspace, setShowCreateWorkspace] = useState(false)

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

  const handleOnboardingComplete = () => {
    load().then(() => {
      // Get workspace ID from current state after reload
      // Use the URL param approach — redirect to growth-os with welcome flag
      if (typeof window !== 'undefined') {
        const params = new URLSearchParams(window.location.search)
        const wsId = params.get('ws') ?? localStorage.getItem('runway_workspace_id') ?? ''
        if (wsId) {
          window.location.href = `/growth-os?ws=${wsId}&welcome=1`
        } else {
          load()
        }
      }
    })
  }

  return (
    <ChatProvider>
    <WorkspaceContext.Provider value={{ workspaces, current, setCurrent, loading, refresh: load, openCreateWorkspace: () => setShowCreateWorkspace(true) }}>
      {children}

      {/* Full-screen loading overlay — fixed so it covers everything, fades out when done */}
      {loading && workspaces.length === 0 && (
        <div className="fixed inset-0 z-[9999] bg-gray-50 flex items-center justify-center">
          <PageLoader section="Dashboard" />
        </div>
      )}
      {/* New user — no workspace yet, OR manually triggered from switcher */}
      {!loading && (workspaces.length === 0 || showCreateWorkspace) && (
        <SetupWorkspaceModal
          onCreated={() => { setShowCreateWorkspace(false); load() }}
          onCancel={workspaces.length > 0 ? () => setShowCreateWorkspace(false) : undefined}
        />
      )}
      {/* Existing workspace needs onboarding */}
      {!loading && workspaces.length > 0 && current && current.onboarding_complete === false && (
        <OnboardingModal workspaceId={current.id} onComplete={handleOnboardingComplete} />
      )}
      {/* AI Contextual Chat — visible on all pages when workspace is loaded */}
      {current && <AIChatPanel workspaceId={current.id} />}
    </WorkspaceContext.Provider>
    </ChatProvider>
  )
}
