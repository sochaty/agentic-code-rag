import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'

import { Layout } from '@/components/Layout'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AskPage } from '@/pages/AskPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { HowItWorksPage } from '@/pages/HowItWorksPage'
import { RunPage } from '@/pages/RunPage'

import './index.css'

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <AskPage /> },
      { path: '/runs/:id', element: <RunPage /> },
      { path: '/history', element: <HistoryPage /> },
      { path: '/how-it-works', element: <HowItWorksPage /> },
    ],
  },
])

const queries = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queries}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
