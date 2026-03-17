'use client'

import { createContext, useContext, useState } from 'react'

interface ChatContextValue {
  chatOpen: boolean
  setChatOpen: (v: boolean) => void
}

const ChatContext = createContext<ChatContextValue>({ chatOpen: false, setChatOpen: () => {} })

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [chatOpen, setChatOpen] = useState(false)
  return <ChatContext.Provider value={{ chatOpen, setChatOpen }}>{children}</ChatContext.Provider>
}

export function useChat() {
  return useContext(ChatContext)
}
