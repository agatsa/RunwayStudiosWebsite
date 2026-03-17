'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { X, Send, Loader2, Sparkles, Zap, RotateCcw, ChevronRight } from 'lucide-react'
import BoldText from '@/components/ui/BoldText'
import { useChat } from '@/components/chat/ChatContext'

interface Message {
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}

interface Props {
  workspaceId: string
}

function formatTime(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })
}

function formatDateLabel(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const msgDate = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = (today.getTime() - msgDate.getTime()) / 86400000
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

const SUGGESTED = [
  'How are my Meta campaigns doing?',
  'What should I focus on this week?',
  'Which campaign has the best ROAS?',
  'Why is my CTR dropping?',
]

export default function AIChatPanel({ workspaceId }: Props) {
  const { chatOpen, setChatOpen } = useChat()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [thinkingMsg, setThinkingMsg] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [creditBalance, setCreditBalance] = useState<number | null>(null)
  const [sessionCredits, setSessionCredits] = useState(0)
  const [showCreditFlash, setShowCreditFlash] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const loadedRef = useRef(false)

  const loadCredits = useCallback(async () => {
    if (!workspaceId) return
    try {
      const r = await fetch(`/api/billing/status?workspace_id=${workspaceId}`)
      if (r.ok) {
        const d = await r.json()
        setCreditBalance(d.credit_balance ?? null)
      }
    } catch { /* ignore */ }
  }, [workspaceId])

  const loadHistory = useCallback(async () => {
    if (!workspaceId) return
    setHistoryLoading(true)
    try {
      const r = await fetch(`/api/chat/history?workspace_id=${workspaceId}`)
      const data = await r.json()
      setMessages(data.messages ?? [])
    } catch {
      // ignore
    } finally {
      setHistoryLoading(false)
    }
  }, [workspaceId])

  useEffect(() => {
    if (chatOpen && !loadedRef.current) {
      loadedRef.current = true
      loadHistory()
      loadCredits()
    }
    if (chatOpen) {
      setTimeout(() => inputRef.current?.focus(), 150)
    }
  }, [chatOpen, loadHistory])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Cmd+K / Ctrl+K global shortcut
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setChatOpen(!chatOpen)
      }
      if (e.key === 'Escape' && chatOpen) {
        setChatOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [chatOpen, setChatOpen])

  async function send() {
    const msg = input.trim()
    if (!msg || loading) return
    setInput('')
    setError(null)
    setThinkingMsg(null)

    const now = new Date().toISOString()
    const userMsg: Message = { role: 'user', content: msg, created_at: now }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    // Thinking stage messages
    const t1 = setTimeout(() => setThinkingMsg('Fetching live campaign data...'), 8000)
    const t2 = setTimeout(() => setThinkingMsg('Analysing your metrics...'), 18000)
    const t3 = setTimeout(() => setThinkingMsg('Almost ready...'), 30000)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, message: msg }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(res.status === 402
          ? 'Not enough credits. Top up from the Billing page.'
          : data.detail ?? 'Something went wrong.')
        setMessages(prev => prev.filter(m => m !== userMsg))
        return
      }
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply,
        created_at: new Date().toISOString(),
      }])
      const used = data.credits_used ?? 1
      setSessionCredits(prev => prev + used)
      setCreditBalance(prev => prev !== null ? prev - used : null)
      setShowCreditFlash(true)
      setTimeout(() => setShowCreditFlash(false), 2500)
    } catch {
      setError('Network error. Please try again.')
      setMessages(prev => prev.filter(m => m !== userMsg))
    } finally {
      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3)
      setLoading(false)
      setThinkingMsg(null)
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
  }

  if (!workspaceId || !chatOpen) return null

  // Group messages by date
  const grouped: { label: string; msgs: Message[] }[] = []
  let lastLabel = ''
  for (const m of messages) {
    const label = formatDateLabel(m.created_at)
    if (label !== lastLabel) {
      grouped.push({ label, msgs: [m] })
      lastLabel = label
    } else {
      grouped[grouped.length - 1].msgs.push(m)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="flex-1 bg-black/50 backdrop-blur-sm"
        onClick={() => setChatOpen(false)}
      />

      {/* Panel */}
      <div
        className="flex flex-col h-full w-[720px] max-w-[92vw] shadow-2xl"
        style={{ background: '#111118', borderLeft: '1px solid #2a2a3d' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 shrink-0"
          style={{ background: '#16161f', borderBottom: '1px solid #2a2a3d' }}
        >
          <div className="flex items-center gap-3.5">
            <div
              className="flex h-9 w-9 items-center justify-center rounded-xl"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}
            >
              <Sparkles className="h-4.5 w-4.5 text-white" style={{ height: 18, width: 18 }} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold text-white">ARIA</span>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                <span className="text-xs text-white/40">online</span>
              </div>
              <p className="text-xs text-white/40 mt-0.5">AI Growth Advisor · Runway Studios</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Credit balance */}
            {creditBalance !== null && (
              <a
                href={`/billing?ws=${workspaceId}`}
                className="hidden sm:flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium text-white/60 hover:text-white/90 transition-colors"
                style={{ background: '#2a2a3d' }}
              >
                <Zap className="h-3 w-3 text-amber-400" />
                <span className="font-semibold text-white/80">{creditBalance.toLocaleString()}</span>
                <span>cr</span>
                {showCreditFlash && (
                  <span className="text-red-400 font-semibold animate-pulse">−1</span>
                )}
              </a>
            )}
            {sessionCredits > 0 && (
              <span
                className="hidden sm:flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-white/30"
                style={{ background: '#1e1e2e' }}
                title="Credits used this session"
              >
                <span>−{sessionCredits} this session</span>
              </span>
            )}
            <span
              className="hidden sm:flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-white/30"
              style={{ background: '#2a2a3d' }}
            >
              <span>⌘K</span>
              <span>to toggle</span>
            </span>
            <button
              onClick={() => { loadedRef.current = false; loadHistory() }}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
              title="Reload history"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setChatOpen(false)}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
              title="Close (Esc)"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto min-h-0 px-5 py-5 space-y-1"
          style={{ scrollbarWidth: 'thin', scrollbarColor: '#2a2a3d transparent' }}
        >
          {historyLoading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <Loader2 className="h-6 w-6 animate-spin text-violet-500" />
              <span className="text-sm text-white/40">Loading conversation...</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div
                className="flex h-16 w-16 items-center justify-center rounded-2xl mb-5"
                style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.2), rgba(79,70,229,0.2))', border: '1px solid rgba(124,58,237,0.3)' }}
              >
                <Sparkles className="h-8 w-8 text-violet-400" />
              </div>
              <p className="text-base font-semibold text-white">Hi, I&apos;m ARIA</p>
              <p className="text-sm text-white/40 mt-1.5 max-w-[320px] leading-relaxed">
                Your AI growth advisor. I have live access to your campaigns, spend, ROAS, and YouTube data.
              </p>
              <div className="mt-7 grid grid-cols-2 gap-2.5 w-full max-w-[480px]">
                {SUGGESTED.map(q => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); inputRef.current?.focus() }}
                    className="rounded-xl px-4 py-3 text-left text-sm text-white/70 hover:text-white transition-all text-[13px]"
                    style={{ background: '#1e1e2e', border: '1px solid #2a2a3d' }}
                    onMouseEnter={e => (e.currentTarget.style.borderColor = '#4c4cff55')}
                    onMouseLeave={e => (e.currentTarget.style.borderColor = '#2a2a3d')}
                  >
                    {q}
                  </button>
                ))}
              </div>
              <p className="mt-6 flex items-center gap-1.5 text-xs text-white/25">
                <Zap className="h-3 w-3 text-amber-500/60" />
                1 credit per message · full history saved
              </p>
            </div>
          ) : (
            <>
              {grouped.map(({ label, msgs }) => (
                <div key={label}>
                  {label && (
                    <div className="flex items-center gap-3 py-4">
                      <div className="h-px flex-1" style={{ background: '#2a2a3d' }} />
                      <span className="text-[10px] font-medium text-white/25 uppercase tracking-widest">{label}</span>
                      <div className="h-px flex-1" style={{ background: '#2a2a3d' }} />
                    </div>
                  )}
                  {msgs.map((m, i) => (
                    <div
                      key={i}
                      className={`flex gap-3.5 mb-5 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      {m.role === 'assistant' && (
                        <div
                          className="flex h-8 w-8 shrink-0 mt-0.5 items-center justify-center rounded-xl"
                          style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.25), rgba(79,70,229,0.25))', border: '1px solid rgba(124,58,237,0.2)' }}
                        >
                          <Sparkles className="h-3.5 w-3.5 text-violet-400" />
                        </div>
                      )}
                      <div className={`flex flex-col gap-1.5 max-w-[82%] ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                        {m.role === 'user' ? (
                          <div
                            className="rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed text-white"
                            style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}
                          >
                            {m.content}
                          </div>
                        ) : (
                          <div
                            className="rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed text-white/85"
                            style={{ background: '#1e1e2e', border: '1px solid #2a2a3d' }}
                          >
                            <BoldText text={m.content} />
                          </div>
                        )}
                        {m.created_at && (
                          <span className="text-[10px] text-white/20 px-1">{formatTime(m.created_at)}</span>
                        )}
                      </div>
                      {m.role === 'user' && (
                        <div
                          className="flex h-8 w-8 shrink-0 mt-0.5 items-center justify-center rounded-xl text-xs font-semibold text-white/60"
                          style={{ background: '#2a2a3d' }}
                        >
                          You
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </>
          )}

          {/* Typing indicator */}
          {loading && (
            <div className="flex gap-3.5 mb-5 justify-start">
              <div
                className="flex h-8 w-8 shrink-0 mt-0.5 items-center justify-center rounded-xl"
                style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.25), rgba(79,70,229,0.25))', border: '1px solid rgba(124,58,237,0.2)' }}
              >
                <Sparkles className="h-3.5 w-3.5 text-violet-400" />
              </div>
              <div
                className="rounded-2xl rounded-tl-sm px-4 py-3"
                style={{ background: '#1e1e2e', border: '1px solid #2a2a3d' }}
              >
                {thinkingMsg ? (
                  <span className="text-sm text-white/40 italic">{thinkingMsg}</span>
                ) : (
                  <div className="flex gap-1.5 items-center py-0.5">
                    <span className="h-2 w-2 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="h-2 w-2 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '160ms' }} />
                    <span className="h-2 w-2 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '320ms' }} />
                  </div>
                )}
              </div>
            </div>
          )}

          {error && (
            <div
              className="rounded-xl px-4 py-3 text-sm text-red-400 mb-3"
              style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}
            >
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div
          className="px-4 py-4 shrink-0"
          style={{ background: '#16161f', borderTop: '1px solid #2a2a3d' }}
        >
          <div
            className="flex items-end gap-3 rounded-xl px-4 py-3 transition-all"
            style={{ background: '#0d0d15', border: '1px solid #2a2a3d' }}
            onFocus={e => (e.currentTarget.style.borderColor = '#7c3aed55')}
            onBlur={e => (e.currentTarget.style.borderColor = '#2a2a3d')}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKey}
              placeholder="Ask ARIA anything about your campaigns..."
              rows={1}
              className="flex-1 resize-none bg-transparent text-sm text-white placeholder-white/25 focus:outline-none"
              style={{ lineHeight: '1.6', minHeight: '24px', maxHeight: '140px' }}
            />
            <button
              onClick={send}
              disabled={!input.trim() || loading}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-all disabled:opacity-25 disabled:cursor-not-allowed hover:scale-105"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}
            >
              {loading
                ? <Loader2 className="h-3.5 w-3.5 text-white animate-spin" />
                : <Send className="h-3.5 w-3.5 text-white" />
              }
            </button>
          </div>
          <div className="flex items-center justify-between mt-2 px-1">
            <p className="text-[10px] text-white/20">Enter to send · Shift+Enter for new line</p>
            <p className="text-[10px] text-white/20">
              {creditBalance !== null
                ? `${creditBalance.toLocaleString()} credits remaining`
                : '1 credit/message'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
