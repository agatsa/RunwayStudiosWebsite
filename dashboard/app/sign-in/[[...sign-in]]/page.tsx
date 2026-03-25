import { SignIn } from '@clerk/nextjs'

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="mb-8 text-2xl font-bold text-gray-900">Runway Studios</h1>
        <SignIn fallbackRedirectUrl="/dashboard" signUpUrl="/sign-up" />
      </div>
    </div>
  )
}
