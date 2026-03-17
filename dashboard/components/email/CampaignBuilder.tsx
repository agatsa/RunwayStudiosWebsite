'use client'

import { useState, useRef } from 'react'
import {
  Sparkles, Send, Eye, EyeOff, Loader2, AlertCircle,
  ImagePlus, X, Link2, Smartphone, Tablet, Monitor, RefreshCw, Check,
} from 'lucide-react'
import type { EmailDomain, EmailList, EmailComposeResult } from '@/lib/types'

interface Props {
  wsId: string
  domains: EmailDomain[]
  lists: EmailList[]
  onCreated: () => void
}

const GOALS = [
  { value: 'drive_purchase',  label: 'Drive Purchase' },
  { value: 'product_launch',  label: 'Product Launch' },
  { value: 're_engage',       label: 'Re-engage Subscribers' },
  { value: 'cart_recovery',   label: 'Cart Recovery' },
  { value: 'announce_offer',  label: 'Announce Offer / Sale' },
  { value: 'newsletter',      label: 'Newsletter / Update' },
]

const TONES = [
  { value: 'friendly',     label: 'Friendly' },
  { value: 'professional', label: 'Professional' },
  { value: 'urgent',       label: 'Urgent' },
  { value: 'playful',      label: 'Playful' },
  { value: 'luxurious',    label: 'Luxurious' },
]

type PreviewDevice = 'mobile' | 'tablet' | 'desktop'

export default function CampaignBuilder({ wsId, domains, lists, onCreated }: Props) {
  const verifiedDomains = domains.filter(d => d.verified)

  // Campaign meta
  const [name, setName] = useState('')
  const [listId, setListId] = useState(lists[0]?.id ?? '')
  const [domainId, setDomainId] = useState(verifiedDomains[0]?.id ?? '')
  const [fromName, setFromName] = useState('')
  const [fromEmail, setFromEmail] = useState('')
  const [replyTo, setReplyTo] = useState('')

  // Product scraper
  const [productUrl, setProductUrl] = useState('')
  const [scraping, setScraping] = useState(false)
  const [scrapeError, setScrapeError] = useState('')
  const [scraped, setScraped] = useState(false)

  // Product info (editable, auto-filled from scrape or typed)
  const [productName, setProductName] = useState('')
  const [productDesc, setProductDesc] = useState('')
  const [productPrice, setProductPrice] = useState('')

  // Product images (from scrape or uploaded)
  const [productImages, setProductImages] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)
  const imgInputRef = useRef<HTMLInputElement>(null)
  const replaceIndexRef = useRef<number | null>(null)

  // Campaign context
  const [campaignContext, setCampaignContext] = useState('')

  // Email style
  const [goal, setGoal] = useState('drive_purchase')
  const [tone, setTone] = useState('friendly')
  const [ctaText, setCtaText] = useState('Shop Now')

  // AI Compose
  const [composing, setComposing] = useState(false)
  const [composeError, setComposeError] = useState('')

  // Generated content (editable)
  const [subject, setSubject] = useState('')
  const [htmlBody, setHtmlBody] = useState('')
  const htmlTextareaRef = useRef<HTMLTextAreaElement>(null)

  // Preview
  const [previewDevice, setPreviewDevice] = useState<PreviewDevice>('mobile')
  const [showPreview, setShowPreview] = useState(false)

  // Send flow
  const [sendError, setSendError] = useState('')
  const [sending, setSending] = useState(false)
  const [step, setStep] = useState<'compose' | 'review' | 'sent'>('compose')
  const [sentResult, setSentResult] = useState<{ campaign_id: string; recipients: number } | null>(null)

  const selectedDomain = verifiedDomains.find(d => d.id === domainId)
  const selectedList = lists.find(l => l.id === listId)

  // ── Product URL scrape ────────────────────────────────────────────────────
  const scrapeProduct = async () => {
    if (!productUrl.trim()) return
    setScraping(true)
    setScrapeError('')
    setScraped(false)
    try {
      const res = await fetch('/api/email/scrape-product', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: productUrl.trim(), workspace_id: wsId }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Could not fetch product info')
      if (data.name) setProductName(data.name)
      if (data.description) setProductDesc(data.description)
      if (data.price) setProductPrice(data.price)
      if (data.images?.length) setProductImages(data.images.slice(0, 4))
      setScraped(true)
    } catch (e: unknown) {
      setScrapeError(e instanceof Error ? e.message : 'Failed to fetch product info')
    } finally {
      setScraping(false)
    }
  }

  // ── Image upload (add new or replace existing) ────────────────────────────
  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0]) return
    const file = e.target.files[0]
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/email/upload-image', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Upload failed')
      const idx = replaceIndexRef.current
      if (idx !== null) {
        setProductImages(prev => prev.map((img, i) => i === idx ? data.url : img))
        replaceIndexRef.current = null
      } else {
        setProductImages(prev => [...prev, data.url].slice(0, 4))
      }
    } catch (err: unknown) {
      setComposeError(err instanceof Error ? err.message : 'Image upload failed')
    } finally {
      setUploading(false)
      if (imgInputRef.current) imgInputRef.current.value = ''
    }
  }

  const triggerUpload = (replaceIndex?: number) => {
    replaceIndexRef.current = replaceIndex ?? null
    imgInputRef.current?.click()
  }

  // ── AI compose ────────────────────────────────────────────────────────────
  const composeWithAI = async () => {
    if (!productName.trim()) { setComposeError('Product name is required'); return }
    setComposing(true)
    setComposeError('')
    try {
      const res = await fetch('/api/email/campaign/compose-ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: wsId,
          product_name: productName,
          product_description: productDesc,
          product_price: productPrice,
          product_url: productUrl,
          campaign_context: campaignContext,
          goal, tone,
          from_name: fromName || 'Your Brand',
          cta_text: ctaText,
          product_images: productImages,
        }),
      })
      if (res.status === 402) {
        setComposeError('Insufficient credits. You need 3 credits to compose an email.')
        return
      }
      const data: EmailComposeResult = await res.json()
      if (!res.ok) throw new Error((data as unknown as { detail: string }).detail ?? 'Compose failed')
      setSubject(data.subject)
      setHtmlBody(data.html_body)
      setShowPreview(true)
    } catch (e: unknown) {
      setComposeError(e instanceof Error ? e.message : String(e))
    } finally {
      setComposing(false)
    }
  }

  // ── Send flow ─────────────────────────────────────────────────────────────
  const saveAndReview = () => {
    if (!name.trim()) { setSendError('Campaign name is required'); return }
    if (!listId) { setSendError('Select a contact list'); return }
    if (!domainId) { setSendError('Select a verified domain'); return }
    if (!fromName.trim()) { setSendError('From name is required'); return }
    if (!fromEmail.trim()) { setSendError('From email is required'); return }
    if (!subject.trim()) { setSendError('Subject is required'); return }
    if (!htmlBody.trim()) { setSendError('Email body is required'); return }
    setSendError('')
    setStep('review')
  }

  const sendCampaign = async () => {
    setSending(true)
    setSendError('')
    try {
      const createRes = await fetch('/api/email/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: wsId, list_id: listId, domain_id: domainId,
          name, subject, from_name: fromName, from_email: fromEmail,
          reply_to: replyTo || undefined, html_body: htmlBody,
        }),
      })
      const createData = await createRes.json()
      if (!createRes.ok) throw new Error(createData.detail ?? 'Failed to create campaign')

      const sendRes = await fetch('/api/email/campaign/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, campaign_id: createData.id }),
      })
      const sendData = await sendRes.json()
      if (!sendRes.ok) throw new Error(sendData.detail ?? 'Failed to send')
      setSentResult({ campaign_id: createData.id, recipients: sendData.recipients })
      setStep('sent')
      onCreated()
    } catch (e: unknown) {
      setSendError(e instanceof Error ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  // ── Sent state ────────────────────────────────────────────────────────────
  if (step === 'sent' && sentResult) {
    return (
      <div className="rounded-2xl border border-green-200 bg-green-50 p-10 text-center space-y-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-100 mx-auto">
          <Send className="h-7 w-7 text-green-600" />
        </div>
        <h3 className="text-base font-semibold text-gray-900">Campaign Sent!</h3>
        <p className="text-sm text-gray-600">
          Delivering to <strong>{sentResult.recipients.toLocaleString()}</strong> contacts. May take a few minutes.
        </p>
        <button onClick={() => {
          setStep('compose'); setName(''); setSubject(''); setHtmlBody('')
          setProductName(''); setProductDesc(''); setProductPrice(''); setProductUrl('')
          setProductImages([]); setCampaignContext(''); setScraped(false); setSentResult(null)
          onCreated()
        }} className="mt-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700">
          Create Another Campaign
        </button>
      </div>
    )
  }

  // ── Review step ───────────────────────────────────────────────────────────
  if (step === 'review') {
    return (
      <div className="space-y-5">
        <button onClick={() => setStep('compose')} className="text-xs text-gray-400 hover:text-gray-700">← Back</button>
        <div className="rounded-xl border border-gray-200 divide-y divide-gray-100">
          {[
            ['Campaign', name],
            ['From', `${fromName} <${fromEmail}>`],
          ].map(([label, val]) => (
            <div key={label} className="px-5 py-3 flex justify-between text-sm">
              <span className="text-gray-500">{label}</span>
              <span className="font-medium text-gray-900">{val}</span>
            </div>
          ))}
          <div className="px-5 py-3 flex justify-between text-sm">
            <span className="text-gray-500">List</span>
            <span className={`font-medium ${(selectedList?.contact_count ?? 0) === 0 ? 'text-red-600' : 'text-gray-900'}`}>
              {selectedList?.name} ({selectedList?.contact_count?.toLocaleString() ?? 0} contacts)
            </span>
          </div>
          <div className="px-5 py-3 flex justify-between text-sm">
            <span className="text-gray-500">Subject</span>
            <span className="font-medium text-gray-900">{subject}</span>
          </div>
        </div>

        <EmailPreviewPanel htmlBody={htmlBody} />

        {(selectedList?.contact_count ?? 0) === 0 && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0" />
            This list has <strong>&nbsp;0 contacts</strong>. Add contacts in the Contacts tab before sending.
          </div>
        )}
        {sendError && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0" />{sendError}
          </div>
        )}
        <div className="flex justify-end gap-3">
          <button onClick={() => setStep('compose')} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Edit</button>
          <button onClick={sendCampaign} disabled={sending || (selectedList?.contact_count ?? 0) === 0}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {sending ? 'Sending…' : 'Send Now'}
          </button>
        </div>
      </div>
    )
  }

  // ── Compose step ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <input ref={imgInputRef} type="file" accept="image/*" onChange={handleImageUpload} className="hidden" />

      {/* ── Section 1: Campaign basics ── */}
      <Section label="1. Campaign Details">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Campaign Name</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              placeholder="e.g. EasyTouch March Launch" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Contact List</label>
            <select value={listId} onChange={e => setListId(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none">
              {lists.map(l => <option key={l.id} value={l.id}>{l.name} ({l.contact_count})</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">From Name</label>
            <input type="text" value={fromName} onChange={e => setFromName(e.target.value)}
              placeholder="Your Brand" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">From Email</label>
            <div className="flex">
              <input type="text" value={fromEmail.split('@')[0]}
                onChange={e => {
                  const local = e.target.value.replace(/[^a-zA-Z0-9._+-]/g, '')
                  setFromEmail(selectedDomain?.domain ? `${local}@${selectedDomain.domain}` : local)
                }}
                placeholder="hello" className="flex-1 rounded-l-lg border border-r-0 border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
              <select value={domainId} onChange={e => {
                setDomainId(e.target.value)
                const d = verifiedDomains.find(x => x.id === e.target.value)
                if (d) setFromEmail(`${fromEmail.split('@')[0]}@${d.domain}`)
              }} className="rounded-r-lg border border-gray-300 px-2 py-2 text-sm focus:border-indigo-500 focus:outline-none bg-gray-50">
                {verifiedDomains.length === 0 && <option value="">— No verified domain —</option>}
                {verifiedDomains.map(d => <option key={d.id} value={d.id}>@{d.domain}</option>)}
              </select>
            </div>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Reply-To (optional)</label>
            <input type="text" value={replyTo} onChange={e => setReplyTo(e.target.value)}
              placeholder="support@yourcompany.com" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
        </div>
      </Section>

      {/* ── Section 2: Product ── */}
      <Section label="2. Product">
        {/* URL fetch */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Product URL — paste any product page to auto-fill details & images</label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Link2 className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
              <input type="url" value={productUrl} onChange={e => setProductUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && scrapeProduct()}
                placeholder="https://agatsaone.com/products/easytouch-plus"
                className="w-full rounded-lg border border-gray-300 pl-9 pr-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
            </div>
            <button onClick={scrapeProduct} disabled={scraping || !productUrl.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60 shrink-0">
              {scraping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              {scraping ? 'Fetching…' : 'Fetch Info'}
            </button>
          </div>
          {scrapeError && <p className="mt-1.5 text-xs text-red-600">{scrapeError}</p>}
          {scraped && !scrapeError && (
            <p className="mt-1.5 flex items-center gap-1 text-xs text-green-600">
              <Check className="h-3 w-3" /> Product info loaded — review and edit below
            </p>
          )}
        </div>

        {/* Editable product fields */}
        <div className="grid grid-cols-2 gap-4 mt-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Product Name *</label>
            <input type="text" value={productName} onChange={e => setProductName(e.target.value)}
              placeholder="EasyTouch Plus" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Price (optional)</label>
            <input type="text" value={productPrice} onChange={e => setProductPrice(e.target.value)}
              placeholder="₹5,999" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Product Description</label>
            <textarea value={productDesc} onChange={e => setProductDesc(e.target.value)} rows={3}
              placeholder="Key features, benefits, what problem it solves…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none resize-none" />
          </div>
        </div>

        {/* Product images */}
        <div className="mt-4">
          <label className="block text-xs font-medium text-gray-700 mb-1">Product Images (up to 4) — AI will place these in the email</label>
          <div className="flex flex-wrap gap-3 mt-2">
            {productImages.map((img, i) => (
              <div key={i} className="relative group rounded-lg overflow-hidden border border-gray-200 w-20 h-20">
                <img src={img} alt="" className="w-full h-full object-cover" />
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1">
                  <button onClick={() => triggerUpload(i)}
                    className="rounded p-1 bg-white/90 text-gray-700 hover:bg-white" title="Replace">
                    <RefreshCw className="h-3 w-3" />
                  </button>
                  <button onClick={() => setProductImages(prev => prev.filter((_, j) => j !== i))}
                    className="rounded p-1 bg-white/90 text-red-600 hover:bg-white" title="Remove">
                    <X className="h-3 w-3" />
                  </button>
                </div>
                {i === 0 && (
                  <span className="absolute top-1 left-1 rounded bg-indigo-600 px-1 py-0.5 text-[8px] font-bold text-white">HERO</span>
                )}
              </div>
            ))}
            {productImages.length < 4 && (
              <button onClick={() => triggerUpload()} disabled={uploading}
                className="flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-gray-300 w-20 h-20 text-gray-400 hover:border-indigo-400 hover:text-indigo-500 transition-colors disabled:opacity-60">
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
                <span className="text-[9px] font-medium">{uploading ? 'Uploading' : 'Add'}</span>
              </button>
            )}
          </div>
          <p className="mt-1.5 text-xs text-gray-400">
            {productImages.length === 0
              ? 'No images — AI will design a branded color block instead. You can upload images to replace it.'
              : 'First image = hero. Hover images to replace or remove.'}
          </p>
        </div>
      </Section>

      {/* ── Section 3: Campaign context ── */}
      <Section label="3. Campaign Purpose">
        <label className="block text-xs font-medium text-gray-700 mb-1">What is this email about? Give AI full context.</label>
        <textarea value={campaignContext} onChange={e => setCampaignContext(e.target.value)} rows={4}
          placeholder={`Examples:\n• "Holi festival sale — 20% off all products, valid March 20-25. Target audience: customers who haven't purchased in 3 months."\n• "Product launch of EasyTouch Plus. Key message: first prick-free glucose monitor in India under ₹6,000."\n• "Re-engage subscribers who opened emails but didn't buy in last 60 days. Offer: free shipping on next order."`}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none resize-none" />
        <p className="mt-1.5 text-xs text-gray-400">The more context you give, the better the AI copy. Include offers, deadlines, audience, and any special messaging.</p>
      </Section>

      {/* ── Section 4: Email style ── */}
      <Section label="4. Email Style">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Goal</label>
            <select value={goal} onChange={e => setGoal(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none">
              {GOALS.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Tone</label>
            <select value={tone} onChange={e => setTone(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none">
              {TONES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">CTA Button Text</label>
            <input type="text" value={ctaText} onChange={e => setCtaText(e.target.value)}
              placeholder="Shop Now" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          </div>
        </div>
      </Section>

      {/* ── Generate button ── */}
      {composeError && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />{composeError}
        </div>
      )}

      <button onClick={composeWithAI} disabled={composing || !productName.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-all"
        style={{ background: composing ? '#6b7280' : 'linear-gradient(135deg, #4F46E5, #7C3AED)' }}>
        {composing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
        {composing ? 'AI is writing your email…' : 'Generate Email with AI  (3 credits)'}
      </button>

      {/* ── Section 5: Edit generated email ── */}
      {(subject || htmlBody) && (
        <Section label="5. Review & Edit">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Subject Line</label>
              <input type="text" value={subject} onChange={e => setSubject(e.target.value)}
                placeholder="Edit subject line…" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
              <p className="mt-1 text-xs text-gray-400">{subject.length}/52 chars — {subject.length > 52 ? <span className="text-amber-600">may get cut off on mobile</span> : 'good length'}</p>
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-700">HTML Body</label>
                <button onClick={() => triggerUpload()}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50">
                  <ImagePlus className="h-3.5 w-3.5" />
                  Insert Image
                </button>
              </div>
              <textarea ref={htmlTextareaRef} value={htmlBody} onChange={e => setHtmlBody(e.target.value)}
                rows={14} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-mono focus:border-indigo-500 focus:outline-none resize-y" />
            </div>
          </div>
        </Section>
      )}

      {/* ── Section 6: Preview ── */}
      {htmlBody && (
        <Section label="6. Preview">
          <EmailPreviewPanel htmlBody={htmlBody} />
        </Section>
      )}

      {/* ── Footer ── */}
      {verifiedDomains.length === 0 && (
        <div className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-4 py-2.5 text-sm text-amber-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          You need a verified sending domain. Set one up in the Domains tab.
        </div>
      )}
      {sendError && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />{sendError}
        </div>
      )}
      <div className="flex justify-end">
        <button onClick={saveAndReview} disabled={verifiedDomains.length === 0 || !htmlBody || !subject}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
          Review & Send →
        </button>
      </div>
    </div>
  )
}

// ── Helper: collapsible section wrapper ──────────────────────────────────────
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-4 py-2.5 border-b border-gray-200">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

// ── Helper: multi-device preview ─────────────────────────────────────────────
function EmailPreviewPanel({ htmlBody }: { htmlBody: string }) {
  const [device, setDevice] = useState<PreviewDevice>('mobile')

  const devices = [
    { id: 'mobile' as PreviewDevice,  label: 'Mobile',  icon: Smartphone, width: 375,  note: 'iPhone 14' },
    { id: 'tablet' as PreviewDevice,  label: 'Tablet',  icon: Tablet,     width: 768,  note: 'iPad' },
    { id: 'desktop' as PreviewDevice, label: 'Desktop', icon: Monitor,    width: null, note: 'Full width' },
  ]

  const deviceWidths: Record<PreviewDevice, number | null> = { mobile: 375, tablet: 768, desktop: null }
  const iframeWidth = deviceWidths[device]

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      {/* Device switcher */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
        <span className="text-xs font-medium text-gray-600">Email Preview</span>
        <div className="flex gap-1">
          {devices.map(d => (
            <button key={d.id} onClick={() => setDevice(d.id)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${device === d.id ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-200'}`}
              title={d.note}>
              <d.icon className="h-3.5 w-3.5" />
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {/* Preview frame */}
      <div className="bg-gray-100 py-6 flex justify-center overflow-auto" style={{ minHeight: 300 }}>
        {/* Device chrome */}
        <div
          className={`relative bg-white shadow-xl transition-all duration-300 ${device === 'mobile' ? 'rounded-[2rem] ring-4 ring-gray-800 ring-offset-2' : device === 'tablet' ? 'rounded-[1.5rem] ring-4 ring-gray-700 ring-offset-2' : 'rounded-lg shadow-2xl'}`}
          style={{
            width: iframeWidth ?? '100%',
            maxWidth: iframeWidth ?? '100%',
            overflow: 'hidden',
          }}
        >
          {/* Browser/phone top bar */}
          {device === 'desktop' && (
            <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-200 border-b border-gray-300">
              <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-green-400" />
              <div className="ml-2 flex-1 rounded bg-white/80 px-2 py-0.5 text-[10px] text-gray-400 font-mono">preview</div>
            </div>
          )}
          {device === 'mobile' && (
            <div className="flex justify-center py-1.5">
              <div className="h-1 w-16 rounded-full bg-gray-300" />
            </div>
          )}
          <iframe
            srcDoc={htmlBody}
            className="block w-full border-0"
            style={{ height: device === 'mobile' ? 600 : 500 }}
            sandbox="allow-same-origin"
            title={`Email preview — ${device}`}
          />
        </div>
      </div>
    </div>
  )
}

// Tailwind shorthand helpers (used via className strings above)
// label = "block text-xs font-medium text-gray-700 mb-1"
// input = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
// These are inlined directly — no dynamic class generation needed.
