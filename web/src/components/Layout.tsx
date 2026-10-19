import { useQuery } from '@tanstack/react-query'
import { BookOpen, History, MessageSquareText, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router'

import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { applyTheme, initialTheme, type Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Ask', icon: MessageSquareText },
  { to: '/history', label: 'History', icon: History },
  { to: '/how-it-works', label: 'How it works', icon: BookOpen },
]

export function Layout() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  useEffect(() => applyTheme(theme), [theme])
  const index = useQuery({ queryKey: ['index'], queryFn: api.index, staleTime: Infinity })

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4">
          <NavLink to="/" className="mr-2 font-semibold tracking-tight">
            agentic-code-rag
          </NavLink>
          <nav className="flex items-center gap-1">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground',
                    isActive && 'bg-muted text-foreground',
                  )
                }
              >
                <Icon className="size-4" />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {index.data && (
              <span className="hidden text-xs text-muted-foreground md:inline">
                {index.data.name} {index.data.ref} · {index.data.provider}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle dark mode"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Sun /> : <Moon />}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
