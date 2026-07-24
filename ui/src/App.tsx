import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { useChatRuntime } from '@assistant-ui/react-ai-sdk'
import { DefaultChatTransport } from 'ai'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AssistantModal } from '@/components/assistant-ui/assistant-modal'

function App() {
  const runtime = useChatRuntime({
    transport: new DefaultChatTransport({ api: '/api/chat' }),
  })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <AssistantModal />
      </TooltipProvider>
    </AssistantRuntimeProvider>
  )
}

export default App
