import { redirect } from 'next/navigation'
import { currentUser } from '@clerk/nextjs/server'

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser()
  const adminEmails = (process.env.ADMIN_EMAILS ?? '')
    .split(',')
    .map(e => e.trim().toLowerCase())
    .filter(Boolean)

  const userEmail = user?.emailAddresses?.[0]?.emailAddress?.toLowerCase() ?? ''

  if (!user || !adminEmails.includes(userEmail)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="rounded-xl border border-red-200 bg-white p-8 max-w-md text-center shadow-sm">
          <p className="text-sm font-bold text-red-600 mb-2">Access Denied</p>
          <p className="text-sm text-gray-600 mb-4">
            Your account <strong>{userEmail || '(not signed in)'}</strong> is not in the admin allowlist.
          </p>
          <p className="text-xs text-gray-400">
            Set <code className="bg-gray-100 px-1 rounded">ADMIN_EMAILS={userEmail}</code> on the dashboard Cloud Run service to grant access.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="border-b border-gray-200 bg-white px-6 py-4 flex items-center gap-3">
        <span className="text-sm font-bold text-gray-900">Runway Studios</span>
        <span className="text-gray-300">·</span>
        <span className="text-sm font-semibold text-purple-600">Super Admin</span>
        <span className="ml-auto text-xs text-gray-400">{userEmail}</span>
      </div>
      <div className="mx-auto max-w-6xl px-6 py-8">
        {children}
      </div>
    </div>
  )
}
