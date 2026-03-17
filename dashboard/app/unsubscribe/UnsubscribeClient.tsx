'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { CheckCircle, XCircle, Loader2, Mail } from 'lucide-react'

export default function UnsubscribeClient() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token) {
      setStatus('error')
      setMessage('Invalid unsubscribe link.')
      return
    }

    const doUnsub = async () => {
      try {
        const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'https://agent-swarm-771420308292.asia-south1.run.app'
        const res = await fetch(`${apiBase}/unsubscribe?token=${encodeURIComponent(token)}`, {
          method: 'POST',
        })
        if (res.ok) {
          setStatus('success')
          setMessage('You have been successfully unsubscribed. You will no longer receive marketing emails from us.')
        } else {
          const data = await res.json().catch(() => ({}))
          setStatus('error')
          setMessage(data.detail ?? 'This unsubscribe link is invalid or has already been used.')
        }
      } catch {
        setStatus('error')
        setMessage('Something went wrong. Please try again.')
      }
    }

    doUnsub()
  }, [token])

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 max-w-md w-full text-center">
      <div className="flex justify-center mb-5">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-indigo-50">
          <Mail className="h-7 w-7 text-indigo-500" />
        </div>
      </div>

      {status === 'loading' && (
        <>
          <Loader2 className="h-6 w-6 animate-spin text-gray-400 mx-auto mb-3" />
          <p className="text-sm text-gray-500">Processing your request…</p>
        </>
      )}

      {status === 'success' && (
        <>
          <CheckCircle className="h-8 w-8 text-green-500 mx-auto mb-3" />
          <h1 className="text-lg font-semibold text-gray-900 mb-2">Unsubscribed</h1>
          <p className="text-sm text-gray-500">{message}</p>
          <p className="mt-4 text-xs text-gray-400">
            You can re-subscribe by contacting the sender directly.
          </p>
        </>
      )}

      {status === 'error' && (
        <>
          <XCircle className="h-8 w-8 text-red-400 mx-auto mb-3" />
          <h1 className="text-lg font-semibold text-gray-900 mb-2">Something went wrong</h1>
          <p className="text-sm text-gray-500">{message}</p>
        </>
      )}

      <p className="mt-8 text-xs text-gray-400">Powered by Runway Studios</p>
    </div>
  )
}
