'use client'

import { useState, useEffect, useRef } from 'react'
import {
  CheckCircle, Clock, AlertCircle, Plus, Trash2, RefreshCw,
  Copy, Check, ExternalLink, ChevronDown, ChevronUp,
  Loader2, Zap, Link2Off, ShieldCheck, ChevronRight,
} from 'lucide-react'
import type { EmailDomain } from '@/lib/types'

interface DnsRecordCheck {
  record: string
  type: string
  name: string
  fqdn: string
  expected: string
  found: string[]
  match: boolean
  status: string
}

// ── Per-provider manual guides ────────────────────────────────────────────────

const MANUAL_GUIDES = {
  godaddy: {
    name: 'GoDaddy', logo: '🌐',
    steps: [
      { title: 'Open DNS Manager', desc: 'Sign in to GoDaddy → My Products → find your domain → click DNS.', url: 'https://dcc.godaddy.com/manage/dns', urlLabel: 'Open GoDaddy DNS →' },
      { title: 'Add each record below', desc: 'Click "Add" for each record. Select the Type (CNAME / TXT / MX), paste the Name and Value exactly as shown, leave TTL as default, then Save.' },
      { title: 'Done — we\'ll verify automatically', desc: 'After saving all records, come back here. We check every 20 seconds and will mark the domain verified automatically.' },
    ],
  },
  namecheap: {
    name: 'Namecheap', logo: '🔖',
    steps: [
      { title: 'Open Advanced DNS', desc: 'Sign in → Domain List → click Manage next to your domain → Advanced DNS tab.', url: 'https://ap.www.namecheap.com/domains/list/', urlLabel: 'Open Namecheap →' },
      { title: 'Add each record below', desc: 'Click "Add New Record". Select the Type, enter Host (the Name column) and Value. For CNAME, Namecheap automatically appends your domain — enter only the subdomain part. Save all.' },
      { title: 'Done — we\'ll verify automatically', desc: 'After saving, come back here. We check every 20 seconds and will mark the domain verified automatically.' },
    ],
  },
  cloudflare: {
    name: 'Cloudflare', logo: '☁️',
    steps: [
      { title: 'Open DNS Records', desc: 'Sign in → select your domain → DNS → Records.', url: 'https://dash.cloudflare.com/', urlLabel: 'Open Cloudflare →' },
      { title: 'Add each record below', desc: 'Click "Add record". Set Type, Name, and Content exactly as shown. Set Proxy status to "DNS only" (grey cloud — not orange). Save.' },
      { title: 'Done — we\'ll verify automatically', desc: 'Cloudflare usually propagates in under 5 minutes. We\'ll detect it automatically.' },
    ],
  },
  hostinger: {
    name: 'Hostinger', logo: '🅷',
    steps: [
      { title: 'Open DNS Zone', desc: 'Sign in → Domains → click Manage → DNS / Nameservers tab.', url: 'https://hpanel.hostinger.com/domains', urlLabel: 'Open Hostinger →' },
      { title: 'Add each record below', desc: 'Click "Add Record". Select Type, fill Name and Value. For MX records also enter the priority shown. Save.' },
      { title: 'Done — we\'ll verify automatically', desc: 'After saving, we check every 20 seconds and will mark the domain verified automatically.' },
    ],
  },
  bigrock: {
    name: 'BigRock', logo: '🪨',
    steps: [
      { title: 'Open DNS Management', desc: 'Sign in → My Orders → Active Domain Orders → click your domain → DNS Management.', url: 'https://manage.bigrock.in/user/login', urlLabel: 'Open BigRock →' },
      { title: 'Add each record below', desc: 'Click "Add DNS Records". Select Type, enter Host (relative name) and Value. Save.' },
      { title: 'Done — we\'ll verify automatically', desc: 'After saving, we check every 20 seconds. Allow 30–60 minutes for propagation.' },
    ],
  },
  other: {
    name: 'Other / cPanel', logo: '⚙️',
    steps: [
      { title: 'Open your DNS panel', desc: 'Log in to your registrar or hosting panel and find the DNS / Zone Editor section.' },
      { title: 'Add each record below', desc: 'Add CNAME, TXT, and MX records exactly as listed. "Name" is the subdomain/host and "Value" is the destination.' },
      { title: 'Done — we\'ll verify automatically', desc: 'After saving, come back here. We check every 20 seconds and will mark it verified automatically.' },
    ],
  },
} as const

type ManualProvider = keyof typeof MANUAL_GUIDES

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status, checking }: { status: EmailDomain['status'], checking?: boolean }) {
  if (status === 'verified')
    return <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"><CheckCircle className="h-3 w-3" />Verified</span>
  if (status === 'failure')
    return <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"><AlertCircle className="h-3 w-3" />Failed — recheck DNS</span>
  if (checking)
    return <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700"><Loader2 className="h-3 w-3 animate-spin" />Checking…</span>
  return <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700"><Clock className="h-3 w-3" />Pending</span>
}

function CopyBtn({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      className="ml-1.5 shrink-0 text-gray-400 hover:text-indigo-600 transition-colors">
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

// ── DNS Records + Provider Guide ───────────────────────────────────────────────

function DnsGuide({ domain, wsId, cfConnected, onVerify }: {
  domain: EmailDomain; wsId: string; cfConnected: boolean; onVerify: () => void
}) {
  const [provider, setProvider] = useState<ManualProvider>('godaddy')
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [applyResults, setApplyResults] = useState<{ ok: boolean; name: string; type: string; error?: string }[] | null>(null)

  const handleApplyCf = async () => {
    setApplying(true); setApplyError(''); setApplyResults(null)
    try {
      const res = await fetch('/api/email/domain/auto-dns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, domain_id: domain.id, provider: 'cloudflare' }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Failed')
      setApplyResults(data.results ?? [])
      if (data.ok) setTimeout(onVerify, 2000)
    } catch (e: unknown) {
      setApplyError(e instanceof Error ? e.message : String(e))
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="border-t border-gray-100">
      <div className="flex overflow-x-auto border-b border-gray-100 bg-gray-50/80 px-4 gap-0.5 pt-2">
        {(Object.keys(MANUAL_GUIDES) as ManualProvider[]).map(pid => (
          <button key={pid}
            onClick={() => { setProvider(pid); setApplyResults(null); setApplyError('') }}
            className={`flex items-center gap-1.5 shrink-0 rounded-t-lg px-3 py-2 text-xs font-medium transition-colors ${
              provider === pid ? 'bg-white border border-b-white border-gray-200 text-indigo-700 -mb-px z-10' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <span>{MANUAL_GUIDES[pid].logo}</span>
            <span>{MANUAL_GUIDES[pid].name}</span>
            {pid === 'cloudflare' && cfConnected && (
              <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[9px] font-bold text-green-700">API</span>
            )}
          </button>
        ))}
      </div>

      <div className="p-4 space-y-5">
        <div className="space-y-3">
          {MANUAL_GUIDES[provider].steps.map((step, i) => (
            <div key={i} className="flex gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-700 mt-0.5">{i + 1}</span>
              <div className="flex-1">
                <p className="text-xs font-semibold text-gray-800">{step.title}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{step.desc}</p>
                {'url' in step && step.url && (
                  <a href={step.url as string} target="_blank" rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors">
                    {(step as { urlLabel: string }).urlLabel}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>

        {provider === 'cloudflare' && cfConnected && !applyResults && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-3 space-y-2">
            <p className="text-xs font-semibold text-indigo-700 flex items-center gap-1.5"><Zap className="h-3.5 w-3.5" /> Cloudflare API connected — skip manual steps</p>
            <button onClick={handleApplyCf} disabled={applying}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
              {applying ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Applying…</> : <><Zap className="h-3.5 w-3.5" />Auto-apply DNS via Cloudflare</>}
            </button>
            {applyError && <p className="text-xs text-red-600">{applyError}</p>}
          </div>
        )}

        {applyResults && (
          <div className="space-y-1.5">
            {applyResults.map((r, i) => (
              <div key={i} className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs ${r.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                {r.ok ? <CheckCircle className="h-3.5 w-3.5 shrink-0" /> : <AlertCircle className="h-3.5 w-3.5 shrink-0" />}
                <span className="font-mono">{r.type} {r.name}</span>
                {!r.ok && r.error && <span className="ml-1 truncate">{r.error}</span>}
              </div>
            ))}
            {applyResults.length > 0 && applyResults.every(r => r.ok) && (
              <p className="text-xs text-green-600 font-medium pt-1">✓ All records pushed — verifying…</p>
            )}
          </div>
        )}

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-2">DNS Records to add</p>
          <div className="space-y-2">
            {domain.dns_records.map((rec, i) => (
              <div key={i} className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 uppercase">{rec.type}</span>
                  {rec.priority != null && <span className="text-xs text-gray-400">Priority: <span className="font-mono font-semibold text-gray-600">{rec.priority}</span></span>}
                </div>
                <div className="grid grid-cols-[56px_1fr] gap-y-1.5 text-xs">
                  <span className="text-gray-400 self-start pt-0.5">Name</span>
                  <div className="flex items-start gap-0.5 font-mono text-gray-800 break-all leading-relaxed">
                    <span>{rec.name}</span><CopyBtn value={rec.name} />
                  </div>
                  <span className="text-gray-400 self-start pt-0.5">Value</span>
                  <div className="flex items-start gap-0.5 font-mono text-gray-800 break-all leading-relaxed">
                    <span>{rec.value}</span><CopyBtn value={rec.value} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Cloudflare API connect ────────────────────────────────────────────────────

function CloudflareApiConnect({ wsId, connected, onStatusChange }: {
  wsId: string; connected: boolean; onStatusChange: (v: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    setSaving(true); setError('')
    const res = await fetch('/api/email/dns-provider', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, provider: 'cloudflare', api_token: token }),
    })
    const data = await res.json()
    setSaving(false)
    if (!res.ok) { setError(data.detail ?? 'Failed'); return }
    onStatusChange(true); setOpen(false); setToken('')
  }

  const disconnect = async () => {
    if (!confirm('Disconnect Cloudflare API?')) return
    await fetch(`/api/email/dns-provider/cloudflare?workspace_id=${wsId}`, { method: 'DELETE' })
    onStatusChange(false)
  }

  if (connected) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-green-200 bg-green-50 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">☁️</span>
          <div>
            <p className="text-xs font-semibold text-gray-800">Cloudflare API</p>
            <p className="text-xs text-green-600">Connected — one-click DNS apply available on each domain</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"><CheckCircle className="h-3 w-3" />Connected</span>
          <button onClick={disconnect} className="flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-500 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors">
            <Link2Off className="h-3 w-3" /> Disconnect
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
      <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 w-full text-left">
        <span className="text-base">☁️</span>
        <div className="flex-1">
          <p className="text-xs font-semibold text-gray-700">Cloudflare users: connect API for one-click DNS</p>
          <p className="text-[11px] text-gray-400">Optional — skip manual copy-paste entirely for Cloudflare-managed domains</p>
        </div>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2.5 pt-3 border-t border-gray-200">
          <p className="text-xs text-gray-500">
            Create a token at{' '}
            <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noreferrer" className="text-indigo-500 underline">
              dash.cloudflare.com/profile/api-tokens
            </a>
            {' '}→ Create Token → "Edit zone DNS" template → All zones → Create Token.
          </p>
          <input type="password" value={token} onChange={e => setToken(e.target.value)}
            placeholder="Paste your Cloudflare API token"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none" />
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2">
              <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-xs text-red-600">{error}</p>
            </div>
          )}
          <button onClick={save} disabled={saving || !token.trim()}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {saving ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Verifying…</> : <><ShieldCheck className="h-3.5 w-3.5" />Verify & Connect</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  wsId: string
  domains: EmailDomain[]
  onRefresh: () => void
}

export default function DomainSetupWizard({ wsId, domains, onRefresh }: Props) {
  const [cfConnected, setCfConnected] = useState(false)
  const [adding, setAdding] = useState(false)
  const [domain, setDomain] = useState('')
  const [loading, setLoading] = useState(false)
  const [addError, setAddError] = useState('')
  const [verifying, setVerifying] = useState<string[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showDnsFor, setShowDnsFor] = useState<string[]>([])
  const [dnsChecks, setDnsChecks] = useState<Record<string, DnsRecordCheck[]>>({})
  const [dnsChecking, setDnsChecking] = useState<string[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load Cloudflare connection status
  useEffect(() => {
    if (!wsId) return
    fetch(`/api/email/dns-provider?workspace_id=${wsId}`)
      .then(r => r.json())
      .then(d => {
        const providers = (d.providers ?? []).map((p: { provider: string }) => p.provider)
        setCfConnected(providers.includes('cloudflare'))
      })
      .catch(() => {})
  }, [wsId])

  // Auto-verify pending domains on mount + whenever domains list changes
  const autoVerifyPending = useRef(false)
  useEffect(() => {
    if (!wsId || autoVerifyPending.current) return
    const pending = domains.filter(d => !d.verified)
    if (pending.length === 0) return
    autoVerifyPending.current = true
    // Mark all pending as "checking"
    setVerifying(pending.map(d => d.id))
    Promise.all(
      pending.map(d =>
        fetch('/api/email/domain/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: wsId, domain_id: d.id }),
        }).catch(() => null)
      )
    ).then(() => {
      setVerifying([])
      onRefresh()
      autoVerifyPending.current = false
    })
  }, [wsId, domains.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-poll every 20s while any domain is pending
  useEffect(() => {
    const hasPending = domains.some(d => !d.verified)
    if (pollRef.current) clearInterval(pollRef.current)
    if (!hasPending || !wsId) return
    pollRef.current = setInterval(() => {
      onRefresh() // GET /email/domain/status auto-verifies each pending domain against Resend
    }, 20_000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [wsId, domains.map(d => d.id + d.status).join(','), onRefresh]) // eslint-disable-line react-hooks/exhaustive-deps

  const addDomain = async () => {
    if (!domain.trim()) return
    setLoading(true); setAddError('')
    try {
      const res = await fetch('/api/email/domain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, domain: domain.trim() }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Failed to add domain')
      setDomain(''); setAdding(false); setExpanded(data.id)
      // Show DNS guide immediately for newly added domain
      setShowDnsFor(prev => prev.includes(data.id) ? prev : [...prev, data.id])
      onRefresh()
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const verifyDomain = async (domainId: string) => {
    setVerifying(prev => prev.includes(domainId) ? prev : [...prev, domainId])
    try {
      await fetch('/api/email/domain/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, domain_id: domainId }),
      })
      onRefresh()
    } finally {
      setVerifying(prev => prev.filter(id => id !== domainId))
    }
  }

  const checkDnsRecords = async (domainId: string) => {
    if (dnsChecking.includes(domainId)) return
    setDnsChecking(prev => [...prev, domainId])
    try {
      const res = await fetch('/api/email/domain/check-dns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, domain_id: domainId }),
      })
      const data = await res.json()
      if (data.records) {
        setDnsChecks(prev => ({ ...prev, [domainId]: data.records }))
      }
    } catch { /* ignore */ } finally {
      setDnsChecking(prev => prev.filter(id => id !== domainId))
    }
  }

  const removeDomain = async (domainId: string) => {
    if (!confirm('Remove this domain?')) return
    await fetch('/api/email/domain', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, domain_id: domainId }),
    })
    onRefresh()
  }

  const hasPending = domains.some(d => !d.verified)

  return (
    <div className="space-y-5">
      <CloudflareApiConnect wsId={wsId} connected={cfConnected} onStatusChange={setCfConnected} />

      <div>
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-sm font-semibold text-gray-900">Sending Domains</h3>
          {hasPending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-200 px-2 py-0.5 text-[10px] font-medium text-blue-600">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Auto-checking every 20s
            </span>
          )}
          <button onClick={() => setAdding(true)}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors">
            <Plus className="h-3.5 w-3.5" /> Add Domain
          </button>
        </div>

        {adding && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3 mb-3">
            <p className="text-xs text-gray-500">Enter the domain you want to send from, e.g. <span className="font-mono">yourcompany.com</span> or a subdomain like <span className="font-mono">mail.yourcompany.com</span></p>
            <div className="flex gap-2">
              <input autoFocus type="text" value={domain} onChange={e => setDomain(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addDomain()}
                placeholder="yourcompany.com"
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
              <button onClick={addDomain} disabled={loading}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
                {loading ? 'Adding…' : 'Add'}
              </button>
              <button onClick={() => { setAdding(false); setAddError('') }}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
            </div>
            {addError && <p className="text-xs text-red-600">{addError}</p>}
          </div>
        )}

        {domains.length === 0 && !adding ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-10 text-center">
            <p className="text-sm font-medium text-gray-400">No domains yet</p>
            <p className="text-xs text-gray-400 mt-1">Add a sending domain to start sending email campaigns.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {domains.map(d => {
              const isChecking = verifying.includes(d.id)
              const isExpanded = expanded === d.id
              const showDns = showDnsFor.includes(d.id)

              return (
                <div key={d.id} className="rounded-xl border border-gray-200 overflow-hidden bg-white">
                  {/* Header row */}
                  <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
                    onClick={() => setExpanded(isExpanded ? null : d.id)}>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={d.status} checking={isChecking} />
                      <span className="text-sm font-semibold text-gray-900">{d.domain}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {!d.verified && (
                        <button onClick={e => { e.stopPropagation(); verifyDomain(d.id) }}
                          disabled={isChecking}
                          className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50">
                          <RefreshCw className={`h-3 w-3 ${isChecking ? 'animate-spin' : ''}`} />
                          {isChecking ? 'Checking…' : 'Check Now'}
                        </button>
                      )}
                      <button onClick={e => { e.stopPropagation(); removeDomain(d.id) }}
                        className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                      {isExpanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
                    </div>
                  </div>

                  {/* Expanded: verified */}
                  {isExpanded && d.verified && (
                    <div className="border-t border-green-100 bg-green-50 px-4 py-3 flex items-center gap-2">
                      <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
                      <p className="text-xs text-green-700 font-medium">
                        Domain verified — ready to send from <strong>@{d.domain}</strong>
                      </p>
                    </div>
                  )}

                  {/* Expanded: pending — DNS status */}
                  {isExpanded && !d.verified && d.dns_records.length > 0 && (() => {
                    const checks = dnsChecks[d.id]
                    const isRunningCheck = dnsChecking.includes(d.id)
                    const hasMismatch = checks && checks.some(r => !r.match)
                    const allMatch = checks && checks.every(r => r.match)
                    return (
                    <div className="border-t border-gray-100">
                      {/* Auto-check status bar */}
                      <div className="flex items-center justify-between px-4 py-3 bg-blue-50/60 border-b border-blue-100">
                        <div className="flex items-center gap-2 min-w-0">
                          <Loader2 className={`h-3.5 w-3.5 text-blue-500 shrink-0 ${isChecking ? 'animate-spin' : ''}`} />
                          <div className="min-w-0">
                            <p className="text-xs font-semibold text-blue-800">
                              {isChecking ? 'Checking DNS with Resend right now…' : 'Checking DNS automatically every 20 seconds'}
                            </p>
                            <p className="text-[11px] text-blue-600 mt-0.5">
                              Already added the DNS records? Just wait — this will flip to ✅ Verified automatically once propagation completes.
                            </p>
                          </div>
                        </div>
                        <button
                          onClick={() => checkDnsRecords(d.id)}
                          disabled={isRunningCheck}
                          className="ml-3 shrink-0 flex items-center gap-1 rounded-lg border border-blue-300 bg-white px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                        >
                          <RefreshCw className={`h-3 w-3 ${isRunningCheck ? 'animate-spin' : ''}`} />
                          {isRunningCheck ? 'Checking…' : 'Diagnose'}
                        </button>
                      </div>

                      {/* DNS record check results */}
                      {checks && (
                        <div className="px-4 py-3 border-b border-gray-100">
                          {hasMismatch && (
                            <div className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5">
                              <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                              <div>
                                <p className="text-xs font-semibold text-red-800">DNS mismatch detected</p>
                                <p className="text-[11px] text-red-700 mt-0.5">One or more records don't match what Resend expects. Update them in your DNS manager.</p>
                              </div>
                            </div>
                          )}
                          {allMatch && (
                            <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
                              <Clock className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                              <p className="text-xs text-amber-800 font-medium">All records found ✓ — waiting for Resend to confirm propagation. Usually takes a few minutes.</p>
                            </div>
                          )}
                          <div className="space-y-2">
                            {checks.map((rec, i) => (
                              <div key={i} className={`rounded-lg border p-3 text-xs ${rec.match ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
                                <div className="flex items-center justify-between mb-1">
                                  <span className="font-semibold text-gray-700">{rec.record} ({rec.type})</span>
                                  <span className={`font-bold ${rec.match ? 'text-green-600' : 'text-red-600'}`}>
                                    {rec.match ? '✓ Correct' : '✗ Wrong / Missing'}
                                  </span>
                                </div>
                                <p className="text-gray-500 mb-1">Name: <code className="bg-white/70 px-1 rounded">{rec.fqdn}</code></p>
                                <p className="text-gray-700 mb-0.5">Expected: <code className="bg-white/70 px-1 rounded break-all">{rec.expected}</code></p>
                                {!rec.match && rec.found.length > 0 && (
                                  <p className="text-red-700">Found in DNS: <code className="bg-white/70 px-1 rounded break-all">{rec.found.join(', ')}</code></p>
                                )}
                                {!rec.match && rec.found.length === 0 && (
                                  <p className="text-red-700">Not found in DNS — record is missing or hasn't propagated yet.</p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Toggle DNS records guide */}
                      <button
                        onClick={() => setShowDnsFor(prev =>
                          prev.includes(d.id) ? prev.filter(x => x !== d.id) : [...prev, d.id]
                        )}
                        className="flex items-center gap-2 w-full px-4 py-2.5 text-xs text-gray-500 hover:bg-gray-50 transition-colors border-b border-gray-100"
                      >
                        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${showDns ? 'rotate-90' : ''}`} />
                        {showDns ? 'Hide DNS records' : 'Show DNS records to add'}
                        <span className="ml-auto text-[10px] text-gray-400">{d.dns_records.length} records</span>
                      </button>

                      {showDns && (
                        <DnsGuide domain={d} wsId={wsId} cfConnected={cfConnected} onVerify={() => verifyDomain(d.id)} />
                      )}
                    </div>
                    )
                  })()}

                  {/* Expanded: no records yet */}
                  {isExpanded && !d.verified && d.dns_records.length === 0 && (
                    <div className="border-t border-gray-100 px-4 py-3 text-xs text-gray-400">
                      DNS records are loading… try refreshing.
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
