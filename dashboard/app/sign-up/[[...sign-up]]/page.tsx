import { SignUp } from '@clerk/nextjs'

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="mb-8 text-2xl font-bold text-gray-900">Runway Studios</h1>
        <SignUp fallbackRedirectUrl="/dashboard" signInUrl="/sign-in" />
      </div>
    </div>
  )
}
