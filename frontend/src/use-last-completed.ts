import { useEffect, useState } from 'react'
import { api } from './api'
import type { LastCompleted } from './types'

export function useLastCompleted(revision: number) {
  const [match, setMatch] = useState<LastCompleted | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void api<LastCompleted | null>('/matches/last-completed')
      .then((value) => {
        if (active) setMatch(value)
      })
      .catch(() => {
        if (active) setError('Не удалось загрузить последнюю игру')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [revision])
  return { match, loading, error }
}
