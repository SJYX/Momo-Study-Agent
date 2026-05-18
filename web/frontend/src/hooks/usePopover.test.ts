/**
 * usePopover.test.ts — 自管 outside-click + Escape 的轻量 popover 状态钩子。
 */
import { describe, expect, it } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePopover } from './usePopover'

describe('usePopover', () => {
  it('toggle 切换 open 状态', () => {
    const { result } = renderHook(() => usePopover())
    expect(result.current.open).toBe(false)
    act(() => result.current.toggle())
    expect(result.current.open).toBe(true)
    act(() => result.current.toggle())
    expect(result.current.open).toBe(false)
  })

  it('close 强制关闭', () => {
    const { result } = renderHook(() => usePopover())
    act(() => result.current.toggle())
    expect(result.current.open).toBe(true)
    act(() => result.current.close())
    expect(result.current.open).toBe(false)
  })

  it('Escape 键关闭 open popover', () => {
    const { result } = renderHook(() => usePopover())
    act(() => result.current.toggle())
    expect(result.current.open).toBe(true)
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    })
    expect(result.current.open).toBe(false)
  })

  it('关闭状态下 Escape 不影响', () => {
    const { result } = renderHook(() => usePopover())
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    })
    expect(result.current.open).toBe(false)
  })
})
