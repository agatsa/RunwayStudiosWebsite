'use client'

import { useState } from 'react'
import { useWorkspace } from '@/components/layout/WorkspaceProvider'
import { LifeBuoy, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'

const CATEGORIES = [
  'General Question',
  'Bug / Something not working',
  'Billing / Credits',
  'Integration (Meta / Google / Shopify)',
  'Feature Request',
  'Account / Login',
  'Other',
]

const PRIORITIES = [
  { label: 'Low',      value: 'Low',      color: 'text-blue-600 bg-blue-50 border-blue-200' },
  { label: 'Normal',   value: 'Normal',   color: 'text-amber-600 bg-amber-50 border-amber-200' },
  { label: 'High',     value: 'High',     color: 'text-orange-600 bg-orange-50 border-orange-200' },
  { label: 'Critical', value: 'Critical', color: 'text-red-600 bg-red-50 border-red-200' },
]

const BACKEND = 'https://agent-swarm-771420308292.asia-south1.run.app'

export default function SupportPage() {
  const { current } = useWorkspace()

  const [name, setName]         = useState('')
  const [email, setEmail]       = useState('')
  const [category, setCategory] = useState(CATEGORIES[0])
  const [priority, setPriority] = useState('Normal')
  const [message, setMessage]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [success, setSuccess]   = useState(false)
  const [error, setError]       = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const res = await fetch(`${BACKEND}/public/submit-ticket`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          email,
          company: current?.name ?? '',
          category,
          priority,
          message,
          workspace_id: current?.id,
        }),
      })
      if (!res.ok) throw new Error('Server error')
      setSuccess(true)
      setName(''); setEmail(''); setMessage(''); setCategory(CATEGORIES[0]); setPriority('Normal')
    } catch {
      setError('Failed to submit. Please email us at info@runwaystudios.co')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50">
          <LifeBuoy className="h-5 w-5 text-brand-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Submit a Support Ticket</h1>
          <p className="text-sm text-gray-500">We typically reply within 24 hours.</p>
        </div>
      </div>

      {/* Success state */}
      {success && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 px-4 py-4">
          <CheckCircle className="h-5 w-5 text-green-600 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold text-green-800">Ticket submitted!</p>
            <p className="text-sm text-green-700 mt-0.5">We've received your message and will reply to <strong>{email || 'you'}</strong> within 24 hours.</p>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-4">
          <AlertCircle className="h-5 w-5 text-red-600 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-gray-200 p-6 space-y-5 shadow-sm">

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Your Name *</label>
            <input
              type="text" required value={name} onChange={e => setName(e.target.value)}
              placeholder="Rahul Sharma"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Email Address *</label>
            <input
              type="email" required value={email} onChange={e => setEmail(e.target.value)}
              placeholder="you@yourbrand.com"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5">Category *</label>
          <select
            value={category} onChange={e => setCategory(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 bg-white"
          >
            {CATEGORIES.map(c => <option key={c}>{c}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-2">Priority</label>
          <div className="flex flex-wrap gap-2">
            {PRIORITIES.map(p => (
              <button
                key={p.value} type="button"
                onClick={() => setPriority(p.value)}
                className={`rounded-full border px-3.5 py-1 text-xs font-semibold transition-all ${
                  priority === p.value ? p.color : 'border-gray-200 text-gray-500 bg-white hover:border-gray-300'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5">Describe the issue *</label>
          <textarea
            required value={message} onChange={e => setMessage(e.target.value)}
            rows={5}
            placeholder="What happened? What did you expect? Include any error messages or steps to reproduce."
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 resize-y"
          />
        </div>

        <button
          type="submit" disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          {loading ? 'Submitting…' : 'Submit Ticket'}
        </button>

        <p className="text-center text-xs text-gray-400">
          Or email us directly at{' '}
          <a href="mailto:info@runwaystudios.co" className="text-brand-600 hover:underline">info@runwaystudios.co</a>
          {' '}· WhatsApp: <a href="tel:+918826283840" className="text-brand-600 hover:underline">+91 88262 83840</a>
        </p>
      </form>
    </div>
  )
}
