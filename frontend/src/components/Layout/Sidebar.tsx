import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, ListTodo, GitBranch, CheckSquare,
  BookOpen, Route, BarChart3, FileBarChart,
  Database, Webhook, Cog, Settings, Globe, Cpu, Brain, Code, PowerOff,
} from 'lucide-react'
import { useHealth } from '../../hooks/useHealth'

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/tasks', label: 'Tasks', icon: ListTodo },
  { to: '/plans', label: 'Plans', icon: GitBranch },
  { to: '/planner', label: 'Planner', icon: Brain },
  { to: '/coder',   label: 'Coder',   icon: Code  },
  { to: '/validation', label: 'Validation', icon: CheckSquare },
  { type: 'divider' as const },
  { to: '/codex', label: 'Codex', icon: BookOpen },
  { to: '/router', label: 'Router', icon: Route },
  { to: '/telemetry', label: 'Telemetry', icon: BarChart3 },
  { to: '/reports', label: 'Reports', icon: FileBarChart },
  { type: 'divider' as const },
  { to: '/sql', label: 'SQL Console', icon: Database },
  { to: '/workers', label: 'Workers', icon: Cpu },
  { to: '/artifacts', label: 'Artifacts', icon: Cog },
  { to: '/integrations', label: 'Integrations', icon: Webhook },
  { to: '/settings', label: 'Settings', icon: Settings },
  { type: 'divider' as const },
  { href: 'http://localhost:8888', label: 'Atlas Hub', icon: Globe },
] as const

interface SidebarProps {
  onNavigate?: () => void
}

export default function Sidebar({ onNavigate }: SidebarProps) {
  const { data: health } = useHealth()
  const healthStatus = health?.status ?? 'unknown'
  const isOk = healthStatus === 'ok'
  const [shuttingDown, setShuttingDown] = useState(false)

  const handleShutdown = async () => {
    if (!confirm('Shut down Mission Control server?')) return
    setShuttingDown(true)
    try {
      await fetch('/system/shutdown', { method: 'POST' })
    } catch {
      // expected — server closes the connection
    }
  }

  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col h-full shrink-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800 hidden md:block">
        <div className="flex items-center gap-2">
          <Cpu className="w-6 h-6 text-blue-400" />
          <span className="text-lg font-semibold tracking-tight">Mission Control</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {navItems.map((item, i) => {
          if ('type' in item && item.type === 'divider') {
            return <div key={i} className="my-2 border-t border-gray-800" />
          }

          if ('href' in item) {
            const Icon = item.icon
            return (
              <a
                key={item.href}
                href={item.href}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="flex-1">{item.label}</span>
              </a>
            )
          }

          if (!('to' in item)) return null
          const Icon = item.icon

          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-gray-800 text-white'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="flex-1">{item.label}</span>
            </NavLink>
          )
        })}
      </nav>

      {/* Footer: health + shutdown */}
      <div className="px-3 py-3 border-t border-gray-800 flex items-center gap-2 text-xs text-gray-500">
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${isOk ? 'bg-green-400' : 'bg-red-400'}`}
        />
        <span className="flex-1">{isOk ? 'ok' : healthStatus}</span>
        <button
          onClick={handleShutdown}
          disabled={shuttingDown}
          title="Shut down Mission Control"
          className="flex items-center gap-1 px-2 py-1 rounded hover:bg-red-950/60 hover:text-red-400 transition-colors disabled:opacity-50"
        >
          <PowerOff className="w-3.5 h-3.5" />
          {shuttingDown ? 'stopping…' : 'shutdown'}
        </button>
      </div>
    </aside>
  )
}
