/**
 * hooks/usePopover.ts — 轻量 popover 状态管理。
 *
 * 提供 open 状态 + toggle/close 方法 + 自动 outside-click/Escape 关闭。
 * ref 由调用方挂到 popover 根元素上。
 *
 * 项目没有 Radix / Headless UI，先用这个最小实现；后续可平替为
 * @radix-ui/react-popover（API 类似）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export interface PopoverState {
  open: boolean
  ref: React.RefObject<HTMLDivElement>
  toggle: () => void
  close: () => void
}

export function usePopover(): PopoverState {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const toggle = useCallback(() => setOpen((v) => !v), [])
  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return { open, ref, toggle, close }
}
