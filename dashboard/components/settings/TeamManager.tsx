'use client'

import { useState, useEffect, useCallback } from 'react'
import { useUser } from '@clerk/nextjs'
import { toast } from 'sonner'
import { Loader2, UserPlus, Trash2, Mail, Crown, Shield, Eye, User } from 'lucide-react'

interface Member {
  id: string
  clerk_user_id: string
  email: string
  name: string
  role: 'admin' | 'member' | 'viewer'
  joined_at: string | null
}

interface Invite {
  id: string
  email: string
  role: string
  status: string
  expires_at: string | null
  created_at: string | null
}

interface TeamData {
  members: Member[]
  invites: Invite[]
  owner_clerk_id: string
  plan: string
  member_limit: number
  total_used: number
  can_invite: boolean
}

const ROLE_ICONS: Record<string, React.ReactNode> = {
  owner:  <Crown  className="h-3.5 w-3.5 text-amber-500" />,
  admin:  <Shield className="h-3.5 w-3.5 text-blue-500" />,
  member: <User   className="h-3.5 w-3.5 text-gray-400" />,
  viewer: <Eye    className="h-3.5 w-3.5 text-gray-400" />,
}

const ROLE_LABELS: Record<string, string> = {
  owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer',
}

interface Props {
  workspaceId: string
  workspaceName: string
  currentRole: 'owner' | 'admin' | 'member' | 'viewer'
}

export default function TeamManager({ workspaceId, workspaceName, currentRole }: Props) {
  const { user } = useUser()
  const [data, setData] = useState<TeamData | null>(null)
  const [loading, setLoading] = useState(true)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member' | 'viewer'>('member')
  const [sending, setSending] = useState(false)

  const canManage = currentRole === 'owner' || currentRole === 'admin'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/team/members?workspace_id=${workspaceId}`)
      const d = await r.json()
      if (r.ok) setData(d)
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  useEffect(() => { load() }, [load])

  const sendInvite = async () => {
    if (!inviteEmail.trim()) return
    setSending(true)
    try {
      const r = await fetch('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: workspaceId,
          workspace_name: workspaceName,
          email: inviteEmail.trim().toLowerCase(),
          role: inviteRole,
          inviter_name: user?.fullName ?? user?.firstName ?? 'Your teammate',
        }),
      })
      const d = await r.json()
      if (r.ok) {
        toast.success(`Invite sent to ${inviteEmail}`)
        setInviteEmail('')
        load()
      } else {
        toast.error(d.detail ?? 'Failed to send invite')
      }
    } finally {
      setSending(false)
    }
  }

  const removeMember = async (memberId: string, email: string) => {
    if (!confirm(`Remove ${email} from this workspace?`)) return
    const r = await fetch(`/api/team/member/${memberId}?workspace_id=${workspaceId}`, { method: 'DELETE' })
    if (r.ok) { toast.success('Member removed'); load() }
    else { const d = await r.json(); toast.error(d.detail ?? 'Failed to remove') }
  }

  const revokeInvite = async (inviteId: string, email: string) => {
    if (!confirm(`Revoke invite for ${email}?`)) return
    const r = await fetch(`/api/team/invite/${inviteId}?workspace_id=${workspaceId}`, { method: 'DELETE' })
    if (r.ok) { toast.success('Invite revoked'); load() }
  }

  const changeRole = async (memberId: string, newRole: string) => {
    const r = await fetch(`/api/team/member/${memberId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId, role: newRole }),
    })
    if (r.ok) { toast.success('Role updated'); load() }
    else { const d = await r.json(); toast.error(d.detail ?? 'Failed to update role') }
  }

  if (loading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
  }

  const atLimit = data ? !data.can_invite : false
  const planLabel = data?.plan === 'growth' ? 'Growth' : data?.plan === 'starter' ? 'Starter' : 'Free'

  return (
    <div className="space-y-6">
      {/* Header + invite form */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-gray-900">Team members</h3>
          {data && (
            <span className="text-xs text-gray-400">
              {data.total_used} / {data.member_limit >= 999 ? '∞' : data.member_limit} on {planLabel} plan
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Invite teammates to collaborate on this workspace.
        </p>

        {canManage && (
          atLimit ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              You&apos;ve reached the member limit for your <strong>{planLabel}</strong> plan.{' '}
              <a href="/billing" className="underline">Upgrade</a> to add more.
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                type="email"
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendInvite()}
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
              />
              <select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value as 'admin' | 'member' | 'viewer')}
                className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
              >
                <option value="admin">Admin</option>
                <option value="member">Member</option>
                <option value="viewer">Viewer</option>
              </select>
              <button
                onClick={sendInvite}
                disabled={sending || !inviteEmail.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 hover:bg-gray-700"
              >
                {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
                Invite
              </button>
            </div>
          )
        )}
      </div>

      {/* Current members */}
      <div className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white overflow-hidden">
        {/* Owner row */}
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-full bg-gray-900 flex items-center justify-center text-white text-sm font-semibold">
              {(user?.fullName ?? user?.firstName ?? 'O').charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">{user?.fullName ?? user?.primaryEmailAddress?.emailAddress ?? 'Owner'}</p>
              <p className="text-xs text-gray-400">{user?.primaryEmailAddress?.emailAddress}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">
            {ROLE_ICONS.owner}
            Owner
          </div>
        </div>

        {/* Members */}
        {data?.members.map(m => (
          <div key={m.id} className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-600 text-sm font-semibold">
                {(m.name || m.email).charAt(0).toUpperCase()}
              </div>
              <div>
                <p className="text-sm font-medium text-gray-900">{m.name || m.email}</p>
                <p className="text-xs text-gray-400">{m.email}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {canManage ? (
                <select
                  value={m.role}
                  onChange={e => changeRole(m.id, e.target.value)}
                  className="rounded-lg border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-gray-900"
                >
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                  <option value="viewer">Viewer</option>
                </select>
              ) : (
                <div className="flex items-center gap-1 rounded-full bg-gray-50 px-2.5 py-1 text-xs text-gray-600">
                  {ROLE_ICONS[m.role]}
                  {ROLE_LABELS[m.role]}
                </div>
              )}
              {currentRole === 'owner' && (
                <button
                  onClick={() => removeMember(m.id, m.email)}
                  className="p-1.5 text-gray-400 hover:text-red-500 rounded"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        ))}

        {data?.members.length === 0 && (
          <div className="px-4 py-6 text-center text-sm text-gray-400">
            No team members yet. Invite someone above.
          </div>
        )}
      </div>

      {/* Pending invites */}
      {data && data.invites.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Pending invites</h4>
          <div className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white overflow-hidden">
            {data.invites.map(inv => (
              <div key={inv.id} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-3">
                  <Mail className="h-4 w-4 text-gray-300 shrink-0" />
                  <div>
                    <p className="text-sm text-gray-700">{inv.email}</p>
                    <p className="text-xs text-gray-400">
                      {inv.role} · expires {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : '—'}
                    </p>
                  </div>
                </div>
                {canManage && (
                  <button
                    onClick={() => revokeInvite(inv.id, inv.email)}
                    className="text-xs text-gray-400 hover:text-red-500"
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Role legend */}
      <div className="rounded-lg bg-gray-50 px-4 py-3 text-xs text-gray-500 space-y-1">
        <p><strong>Admin</strong> — can invite members, connect platforms, approve actions</p>
        <p><strong>Member</strong> — can view all data and use AI features</p>
        <p><strong>Viewer</strong> — read-only access, cannot approve actions</p>
      </div>
    </div>
  )
}
