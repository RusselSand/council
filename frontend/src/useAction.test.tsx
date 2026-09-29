import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Council } from './api'
import './i18n'
import { useAction } from './useAction'

const COUNCIL = { id: 'demo-1' } as Council

describe('useAction', () => {
  it('второе действие, пока идёт первое, не начинается', async () => {
    let release!: (council: Council) => void
    const first = vi.fn(() => new Promise<Council>(r => { release = r }))
    const second = vi.fn(() => Promise.resolve(COUNCIL))
    const done = vi.fn()
    const { result } = renderHook(() => useAction(done))

    let pending!: Promise<boolean>
    let refused!: Promise<boolean>
    act(() => {
      pending = result.current.go(first)
      refused = result.current.go(second)   // тот же щелчок: busy ещё не отрисован
    })
    expect(await refused).toBe(false)
    expect(second).not.toHaveBeenCalled()
    await act(async () => { release(COUNCIL); expect(await pending).toBe(true) })
    expect(done).toHaveBeenCalledTimes(1)

    await act(async () => { expect(await result.current.go(second)).toBe(true) })
    expect(second).toHaveBeenCalledTimes(1)
  })
})
