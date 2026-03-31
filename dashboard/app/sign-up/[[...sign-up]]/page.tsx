import { SignUp } from '@clerk/nextjs'

const clerkLight = {
  elements: {
    rootBox: 'w-full',
    card: 'rounded-2xl bg-white border border-gray-200 shadow-lg',
    headerTitle: 'text-gray-900 text-lg font-bold',
    headerSubtitle: 'text-gray-500',
    socialButtonsBlockButton: 'bg-white border border-gray-300 text-gray-800 hover:bg-gray-50',
    socialButtonsBlockButtonText: 'text-gray-800 font-medium',
    dividerLine: 'bg-gray-200',
    dividerText: 'text-gray-400',
    formFieldLabel: 'text-gray-700 font-medium',
    formFieldInput: 'bg-white border-gray-300 text-gray-900 placeholder-gray-400',
    formButtonPrimary: 'bg-violet-600 hover:bg-violet-700 text-white font-semibold',
    footerActionLink: 'text-violet-600 hover:text-violet-700',
    footerActionText: 'text-gray-500',
    identityPreviewText: 'text-gray-900',
    identityPreviewEditButton: 'text-violet-600',
    otpCodeFieldInput: 'bg-white border-gray-300 text-gray-900',
    formResendCodeLink: 'text-violet-600',
    alertText: 'text-red-600',
    formFieldErrorText: 'text-red-500',
  }
}

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-100 px-4">
      <div className="mb-6 text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-white font-bold text-lg">R</div>
        <h1 className="text-xl font-bold text-gray-900">Create your account</h1>
        <p className="mt-1 text-sm text-gray-500">Start your free analysis on Runway Studios</p>
      </div>
      <SignUp fallbackRedirectUrl="/dashboard" signInUrl="/sign-in" appearance={clerkLight} />
    </div>
  )
}
