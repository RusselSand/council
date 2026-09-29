import { describe, expect, it } from 'vitest'
import { merge } from './useAutosave'

describe('merge', () => {
  it('сливает словари по ключам, остальное заменяет', () => {
    expect(merge({ labels: { 1: 'risk' }, name: 'а', participants: ['sol', 'fable'] },
                 { labels: { 2: 'idea' }, name: 'б', participants: ['sol', 'astra'] }))
      .toEqual({ labels: { 1: 'risk', 2: 'idea' }, name: 'б', participants: ['sol', 'astra'] })
  })

  it('новое значение ключа словаря важнее старого', () => {
    expect(merge({ labels: { 1: 'risk' } }, { labels: { 1: 'idea' } })).toEqual({ labels: { 1: 'idea' } })
  })
})
