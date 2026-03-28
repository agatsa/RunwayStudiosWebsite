'use client'

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import type { Workspace } from '@/lib/types'
import OnboardingModal from '@/components/onboarding/OnboardingModal'
import ConnectAccountsStepper from '@/components/onboarding/ConnectAccountsStepper'
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

/** Redirects new users (no workspace) to the /onboard scan flow. */
function RedirectToOnboard() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/onboard')
  }, [router])
  return null
}

export default function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [current, setCurrent_] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const [showCreateWorkspace, setShowCreateWorkspace] = useState(false)
  const [showStepper, setShowStepper] = useState(false)
  const [stepperBizType, setStepperBizType] = useState<'d2c' | 'creator' | 'agency' | 'saas'>('d2c')
  const [stepperWsId, setStepperWsId] = useState('')
  const [stepperStartStep, setStepperStartStep] = useState(0)

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
      // Always keep localStorage in sync so handleOnboardingComplete can read it
      if (selected && typeof window !== 'undefined') {
        localStorage.setItem('runway_workspace_id', selected.id)
      }

      // If URL has no ws param but we have a workspace, inject it — preserve all other params
      if (selected && !urlWs) {
        const params = new URLSearchParams(searchParamsRef.current.toString())
        params.set('ws', selected.id)
        router.replace(`${pathname}?${params.toString()}`)
      }

      // Resume ConnectAccountsStepper if user returned from OAuth mid-flow
      if (typeof window !== 'undefined') {
        const raw = sessionStorage.getItem('runway_connect_stepper')
        if (raw) {
          try {
            const { wsId, bizType, nextStepIdx } = JSON.parse(raw)
            const match = ws.find(w => w.id === wsId)
            if (match) {
              sessionStorage.removeItem('runway_connect_stepper')
              setStepperWsId(wsId)
              setStepperBizType(bizType ?? 'd2c')
              setStepperStartStep(nextStepIdx ?? 0)
              setShowStepper(true)
            }
          } catch { /* malformed — ignore */ }
        }
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

  const handleOnboardingComplete = (bizType?: string) => {
    load().then(() => {
      if (typeof window !== 'undefined') {
        // After load(), localStorage is guaranteed to have the workspace id
        const wsId = localStorage.getItem('runway_workspace_id') ?? ''
        if (wsId && bizType) {
          // Show ConnectAccountsStepper before redirecting to dashboard
          setStepperWsId(wsId)
          setStepperBizType((bizType as 'd2c' | 'creator' | 'agency' | 'saas') ?? 'd2c')
          setShowStepper(true)
        } else {
          // Fallback — navigate to dashboard
          const dest = wsId ? `/dashboard?ws=${wsId}` : '/dashboard'
          window.location.href = dest
        }
      }
    })
  }

  const handleStepperDone = () => {
    setShowStepper(false)
    setStepperStartStep(0)
    if (typeof window !== 'undefined') {
      const wsId = stepperWsId
      if (stepperBizType === 'creator') {
        window.location.href = `/youtube?ws=${wsId}`
      } else {
        window.location.href = `/dashboard?ws=${wsId}`
      }
    }
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
      {/* New user — no workspace yet: redirect to /onboard scan flow instead of modal */}
      {!loading && workspaces.length === 0 && pathname !== '/onboard' && (
        <RedirectToOnboard />
      )}
      {/* Manually triggered from workspace switcher — show modal */}
      {!loading && workspaces.length > 0 && showCreateWorkspace && (
        <SetupWorkspaceModal
          onCreated={() => { setShowCreateWorkspace(false); load() }}
          onCancel={() => setShowCreateWorkspace(false)}
        />
      )}
      {/* Existing workspace needs onboarding */}
      {!loading && workspaces.length > 0 && current && current.onboarding_complete === false && !showStepper && (
        <OnboardingModal workspaceId={current.id} onComplete={handleOnboardingComplete} />
      )}
      {/* Connect accounts stepper — shown after onboarding modal */}
      {showStepper && stepperWsId && (
        <ConnectAccountsStepper
          workspaceId={stepperWsId}
          bizType={stepperBizType}
          startStep={stepperStartStep}
          onDone={handleStepperDone}
        />
      )}
      {/* AI Contextual Chat — visible on all pages when workspace is loaded */}
      {current && <AIChatPanel workspaceId={current.id} />}
    </WorkspaceContext.Provider>
    </ChatProvider>
  )
}
