import { Suspense } from 'react'
import InviteClient from './InviteClient'

export default function InvitePage() {
  return (
    <Suspense>
      <InviteClient />
    </Suspense>
  )
}
