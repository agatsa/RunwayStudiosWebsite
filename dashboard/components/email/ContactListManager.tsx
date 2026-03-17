'use client'

import { useState, useRef } from 'react'
import { Plus, Trash2, Upload, Users, ChevronRight, X } from 'lucide-react'
import type { EmailList, EmailContact } from '@/lib/types'

interface Props {
  wsId: string
  lists: EmailList[]
  onRefresh: () => void
}

function parseCSV(text: string): { headers: string[]; rows: Record<string, string>[] } {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  if (lines.length < 2) return { headers: [], rows: [] }
  const headers = lines[0].split(',').map(h => h.replace(/['"]/g, '').trim().toLowerCase())
  const rows = lines.slice(1).map(line => {
    const vals = line.match(/(".*?"|[^,]+)(?=,|$)/g) ?? []
    const obj: Record<string, string> = {}
    headers.forEach((h, i) => {
      obj[h] = (vals[i] ?? '').replace(/^"|"$/g, '').trim()
    })
    return obj
  })
  return { headers, rows }
}

function mapRow(row: Record<string, string>) {
  const emailKey = Object.keys(row).find(k => k.includes('email')) ?? 'email'
  const firstKey = Object.keys(row).find(k => k.includes('first') || k === 'firstname' || k === 'name') ?? ''
  const lastKey = Object.keys(row).find(k => k.includes('last') || k === 'lastname' || k === 'surname') ?? ''
  return {
    email: row[emailKey] ?? '',
    first_name: firstKey ? row[firstKey] : '',
    last_name: lastKey ? row[lastKey] : '',
    custom_fields: {},
  }
}

export default function ContactListManager({ wsId, lists, onRefresh }: Props) {
  const [creatingList, setCreatingList] = useState(false)
  const [newListName, setNewListName] = useState('')
  const [selectedList, setSelectedList] = useState<EmailList | null>(null)
  const [contacts, setContacts] = useState<EmailContact[]>([])
  const [contactsTotal, setContactsTotal] = useState(0)
  const [loadingContacts, setLoadingContacts] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ imported: number; duplicates: number } | null>(null)
  const [quickAddEmail, setQuickAddEmail] = useState('')
  const [quickAddName, setQuickAddName] = useState('')
  const [quickAdding, setQuickAdding] = useState(false)
  const [showQuickAdd, setShowQuickAdd] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const createList = async () => {
    if (!newListName.trim()) return
    await fetch('/api/email/lists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, name: newListName.trim() }),
    })
    setNewListName('')
    setCreatingList(false)
    onRefresh()
  }

  const deleteList = async (listId: string) => {
    if (!confirm('Delete this list and all its contacts?')) return
    await fetch(`/api/email/lists/${listId}?workspace_id=${wsId}`, { method: 'DELETE' })
    if (selectedList?.id === listId) setSelectedList(null)
    onRefresh()
  }

  const openList = async (list: EmailList) => {
    setSelectedList(list)
    setLoadingContacts(true)
    setImportResult(null)
    try {
      const res = await fetch(`/api/email/contacts?workspace_id=${wsId}&list_id=${list.id}&limit=100`)
      const data = await res.json()
      setContacts(data.contacts ?? [])
      setContactsTotal(data.total ?? 0)
    } finally {
      setLoadingContacts(false)
    }
  }

  const quickAddContact = async () => {
    if (!selectedList || !quickAddEmail.includes('@')) return
    setQuickAdding(true)
    try {
      const nameParts = quickAddName.trim().split(' ')
      const res = await fetch('/api/email/lists/import-csv', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: wsId,
          list_id: selectedList.id,
          rows: [{ email: quickAddEmail.trim(), first_name: nameParts[0] ?? '', last_name: nameParts.slice(1).join(' ') }],
        }),
      })
      const data = await res.json()
      if (data.imported > 0) {
        setImportResult({ imported: 1, duplicates: 0 })
        setQuickAddEmail('')
        setQuickAddName('')
        setShowQuickAdd(false)
        openList(selectedList)
        onRefresh()
      } else {
        setImportResult({ imported: 0, duplicates: 1 })
      }
    } finally {
      setQuickAdding(false)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedList || !e.target.files?.[0]) return
    const file = e.target.files[0]
    const text = await file.text()
    const { rows } = parseCSV(text)
    const mapped = rows.map(mapRow).filter(r => r.email.includes('@'))
    if (!mapped.length) { alert('No valid email rows found in CSV.'); return }
    setImporting(true)
    try {
      const res = await fetch('/api/email/lists/import-csv', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, list_id: selectedList.id, rows: mapped }),
      })
      const data = await res.json()
      setImportResult({ imported: data.imported, duplicates: data.duplicates })
      openList(selectedList)
      onRefresh()
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (selectedList) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSelectedList(null)}
            className="text-xs text-gray-400 hover:text-gray-700 flex items-center gap-1"
          >
            ← All Lists
          </button>
          <span className="text-gray-300">/</span>
          <span className="text-sm font-medium text-gray-900">{selectedList.name}</span>
          <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            {contactsTotal} contacts
          </span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleFileUpload}
            className="hidden"
          />
          <button
            onClick={() => { setShowQuickAdd(true); setImportResult(null) }}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Contact
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            <Upload className="h-3.5 w-3.5" />
            {importing ? 'Importing…' : 'Import CSV'}
          </button>
          <span className="text-xs text-gray-400">CSV must have an "email" column.</span>
        </div>

        {showQuickAdd && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3">
            <p className="text-xs font-medium text-gray-700">Add a single contact</p>
            <div className="flex gap-2">
              <input
                autoFocus
                type="email"
                value={quickAddEmail}
                onChange={e => setQuickAddEmail(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && quickAddContact()}
                placeholder="email@example.com *"
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              />
              <input
                type="text"
                value={quickAddName}
                onChange={e => setQuickAddName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && quickAddContact()}
                placeholder="Full name (optional)"
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={quickAddContact}
                disabled={quickAdding || !quickAddEmail.includes('@')}
                className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
              >
                {quickAdding ? 'Adding…' : 'Add'}
              </button>
              <button
                onClick={() => { setShowQuickAdd(false); setQuickAddEmail(''); setQuickAddName('') }}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {importResult && (
          <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-2.5 flex items-center justify-between">
            <span className="text-xs text-green-700">
              ✓ Imported {importResult.imported} contacts
              {importResult.duplicates > 0 && ` (${importResult.duplicates} duplicates skipped)`}
            </span>
            <button onClick={() => setImportResult(null)}>
              <X className="h-3.5 w-3.5 text-green-400" />
            </button>
          </div>
        )}

        {loadingContacts ? (
          <div className="flex items-center justify-center py-8 text-sm text-gray-400">Loading contacts…</div>
        ) : contacts.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center">
            <Users className="h-8 w-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">No contacts yet. Click <strong>Add Contact</strong> to add one, or import a CSV.</p>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left font-medium">Email</th>
                  <th className="px-4 py-2.5 text-left font-medium">Name</th>
                  <th className="px-4 py-2.5 text-left font-medium">Status</th>
                  <th className="px-4 py-2.5 text-left font-medium">Added</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {contacts.slice(0, 50).map(c => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5 text-gray-800 font-mono text-xs">{c.email}</td>
                    <td className="px-4 py-2.5 text-gray-600">{[c.first_name, c.last_name].filter(Boolean).join(' ') || '—'}</td>
                    <td className="px-4 py-2.5">
                      {c.unsubscribed ? (
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-600">Unsubscribed</span>
                      ) : c.bounced ? (
                        <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-medium text-orange-600">Bounced</span>
                      ) : (
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-600">Active</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-400">{new Date(c.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {contactsTotal > 50 && (
              <div className="px-4 py-2 text-xs text-gray-400 bg-gray-50 border-t border-gray-100">
                Showing 50 of {contactsTotal} contacts
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Contact Lists</h3>
          <p className="text-xs text-gray-500 mt-0.5">Manage your subscriber lists and import contacts via CSV.</p>
        </div>
        <button
          onClick={() => setCreatingList(true)}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
        >
          <Plus className="h-3.5 w-3.5" /> New List
        </button>
      </div>

      {creatingList && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 flex gap-2">
          <input
            autoFocus
            type="text"
            value={newListName}
            onChange={e => setNewListName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && createList()}
            placeholder="List name (e.g. Newsletter Subscribers)"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
          <button onClick={createList} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">Create</button>
          <button onClick={() => setCreatingList(false)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      )}

      {lists.length === 0 && !creatingList ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center">
          <Users className="h-8 w-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No lists yet. Create a list and import your contacts.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {lists.map(l => (
            <div
              key={l.id}
              className="flex items-center justify-between rounded-xl border border-gray-200 p-4 hover:bg-gray-50 cursor-pointer"
              onClick={() => openList(l)}
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50">
                  <Users className="h-4.5 w-4.5 text-indigo-500" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-900">{l.name}</p>
                  {l.description && <p className="text-xs text-gray-400">{l.description}</p>}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                  {l.contact_count.toLocaleString()} contacts
                </span>
                <button
                  onClick={e => { e.stopPropagation(); deleteList(l.id) }}
                  className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                <ChevronRight className="h-4 w-4 text-gray-300" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
