import { SignIn } from '@clerk/nextjs'

const clerkDark = {
  elements: {
    rootBox: 'w-full',
    card: 'rounded-2xl bg-gray-900 border border-gray-700 shadow-xl',
    headerTitle: 'text-white text-lg font-bold',
    headerSubtitle: 'text-gray-400',
    socialButtonsBlockButton: 'bg-gray-800 border border-gray-600 text-white hover:bg-gray-700',
    socialButtonsBlockButtonText: 'text-white font-medium',
    dividerLine: 'bg-gray-700',
    dividerText: 'text-gray-500',
    formFieldLabel: 'text-gray-300 font-medium',
    formFieldInput: 'bg-gray-800 border-gray-600 text-white placeholder-gray-500',
    formButtonPrimary: 'bg-violet-600 hover:bg-violet-700 font-semibold',
    footerActionLink: 'text-violet-400 hover:text-violet-300',
    footerActionText: 'text-gray-400',
    identityPreviewText: 'text-white',
    identityPreviewEditButton: 'text-violet-400',
    otpCodeFieldInput: 'bg-gray-800 border-gray-600 text-white',
    formResendCodeLink: 'text-violet-400',
    alertText: 'text-red-400',
    formFieldErrorText: 'text-red-400',
  }
}

export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-950 px-4">
      <div className="mb-6 text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-white font-bold text-lg">R</div>
        <h1 className="text-xl font-bold text-white">Sign in to Runway Studios</h1>
        <p className="mt-1 text-sm text-gray-400">Your AI growth platform</p>
      </div>
      <SignIn fallbackRedirectUrl="/dashboard" signUpUrl="/sign-up" appearance={clerkDark} />
    </div>
  )
}
