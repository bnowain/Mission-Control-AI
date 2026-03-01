/**
 * ModelStatusBar — global top bar showing Ollama loaded models + VRAM.
 * Polls GET /system/ollama/ps every 3 seconds.
 * Shown on every page, sits between the mobile header and main content.
 */
import { useState, useEffect, useRef } from 'react'
import { Cpu, Circle } from 'lucide-react'

interface OllamaModel {
  name: string
  size: number       // total size in bytes
  size_vram: number  // VRAM used in bytes (0 if CPU)
  expires_at?: string
}

interface OllamaPsResponse {
  models: OllamaModel[]
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const gb = bytes / (1024 ** 3)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / (1024 ** 2)
  return `${mb.toFixed(0)} MB`
}

function shortName(name: string): string {
  // "deepseek-coder-v2:16b" → "deepseek-coder-v2:16b" (keep as-is, it's already short)
  // "ollama/qwen2.5:32b" → "qwen2.5:32b"
  return name.replace(/^ollama\//, '')
}

export default function ModelStatusBar() {
  const [models, setModels]       = useState<OllamaModel[]>([])
  const [ollamaUp, setOllamaUp]   = useState<boolean | null>(null)  // null = unknown
  const intervalRef               = useRef<ReturnType<typeof setInterval> | null>(null)

  const poll = async () => {
    try {
      const res = await fetch('/system/ollama/ps')
      if (!res.ok) { setOllamaUp(false); return }
      const data: OllamaPsResponse = await res.json()
      setModels(data.models ?? [])
      setOllamaUp(true)
    } catch {
      setOllamaUp(false)
      setModels([])
    }
  }

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, 3000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  // Don't render anything if we don't know yet
  if (ollamaUp === null) return null

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 bg-gray-900 border-b border-gray-800 text-xs overflow-x-auto shrink-0">

      {/* Ollama status dot */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Circle
          className={`w-2 h-2 fill-current ${ollamaUp ? 'text-green-400' : 'text-red-500'}`}
        />
        <span className={`font-medium ${ollamaUp ? 'text-gray-400' : 'text-red-400'}`}>
          Ollama
        </span>
      </div>

      <span className="text-gray-700 shrink-0">|</span>

      {/* Loaded models */}
      {!ollamaUp && (
        <span className="text-gray-600">unreachable</span>
      )}

      {ollamaUp && models.length === 0 && (
        <span className="text-gray-600">no models loaded</span>
      )}

      {ollamaUp && models.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          {models.map(m => {
            const vram  = m.size_vram ?? 0
            const isGpu = vram > 0
            return (
              <div
                key={m.name}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-gray-700 bg-gray-800"
              >
                <Cpu className={`w-3 h-3 ${isGpu ? 'text-blue-400' : 'text-gray-500'}`} />
                <span className="text-gray-200 font-mono">{shortName(m.name)}</span>
                <span className="text-gray-500">
                  {isGpu
                    ? `${formatBytes(vram)} VRAM`
                    : `${formatBytes(m.size)} RAM`
                  }
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
