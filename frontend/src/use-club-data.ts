import { useEffect, useRef, useState } from 'react'
import { api, ApiError, DATA_CHANGED, hasToken, SESSION_EXPIRED, setToken } from './api'
import type { Match, Player } from './types'

export function useClubData() {
  const [me, setMe] = useState<Player | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [seasons, setSeasons] = useState<string[]>([])
  const [match, setMatch] = useState<Match | null>(null)
  const [selectedId, select] = useState<number | null>(null)
  const [dataRevision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [demo, setDemo] = useState(false)
  const [loadError, setLoadError] = useState('')
  const selected = useRef<number | null>(null)
  const dirty = useRef(new Set<string>())
  const generation = useRef(0)
  const loadedSelection = useRef<number | null | undefined>(undefined)
  const identityGeneration = useRef(0)
  const initial = useRef<Promise<void> | null>(null)

  function setSelectedId(id: number | null) {
    if (selected.current !== id) setMatch(null)
    selected.current = id
    select(id)
  }

  async function loadMatch(id: number | null) {
    const request = ++generation.current
    const next = await api<Match | null>(id ? `/matches/${id}` : '/matches/current')
    if (request === generation.current) {
      loadedSelection.current = id
      setMatch(next)
    }
  }

  async function refresh(force = false) {
    if (!hasToken()) return
    const identity = identityGeneration.current
    const paths = [...dirty.current]
    dirty.current.clear()
    const peopleChanged =
      force ||
      paths.some(
        (p) =>
          p.startsWith('/players') ||
          p.startsWith('/administrators') ||
          p === '/me' ||
          p.includes('profile-claim'),
      )
    const matchChanged =
      force ||
      peopleChanged ||
      paths.some((p) => p.startsWith('/matches') || p.startsWith('/publications'))
    try {
      await Promise.all([
        ...(peopleChanged
          ? [
              api<Player>('/me').then((value) => {
                if (identity === identityGeneration.current && hasToken()) setMe(value)
              }),
              api<Player[]>('/players').then((value) => {
                if (identity === identityGeneration.current && hasToken()) setPlayers(value)
              }),
            ]
          : []),
        ...(matchChanged
          ? [
              loadMatch(selected.current),
              api<string[]>('/seasons').then((value) => {
                if (identity === identityGeneration.current && hasToken()) setSeasons(value)
              }),
            ]
          : []),
      ])
      if (force || paths.length) setRevision((value) => value + 1)
    } catch (error) {
      paths.forEach((path) => dirty.current.add(path))
      throw error
    }
  }

  async function logout() {
    await api('/auth/logout', 'POST')
    setToken('')
    window.dispatchEvent(new Event(SESSION_EXPIRED))
  }

  useEffect(() => {
    const expired = () => {
      ++generation.current
      ++identityGeneration.current
      loadedSelection.current = undefined
      dirty.current.clear()
      setMe(null)
      setMatch(null)
      setPlayers([])
      setSeasons([])
    }
    const changed = (event: Event) => {
      const { path } = (event as CustomEvent<{ path: string }>).detail
      dirty.current.add(path)
    }
    window.addEventListener(SESSION_EXPIRED, expired)
    window.addEventListener(DATA_CHANGED, changed)
    return () => {
      window.removeEventListener(SESSION_EXPIRED, expired)
      window.removeEventListener(DATA_CHANGED, changed)
    }
  }, [])

  useEffect(() => {
    initial.current ??= (async () => {
      try {
        const health = await api<{ demo: boolean }>('/health')
        setDemo(health.demo)
        const tg = window.Telegram?.WebApp
        tg?.ready()
        tg?.expand()
        const param = tg?.initDataUnsafe?.start_param
        const id = param?.startsWith('game_')
          ? Number(param.slice(5))
          : Number(new URLSearchParams(location.search).get('game'))
        if (Number.isInteger(id) && id > 0) setSelectedId(id)
        if (hasToken()) {
          try {
            await api('/me')
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 401)) throw error
          }
        }
        if (!hasToken() && tg?.initData) {
          const result = await api<{ token: string }>('/auth/telegram', 'POST', {
            init_data: tg.initData,
          })
          setToken(result.token)
        }
        await refresh(true)
      } catch (error) {
        setLoadError((error as Error).message)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  useEffect(() => {
    if (!me || loading || loadedSelection.current === selectedId) return
    void loadMatch(selectedId).catch((error) => setLoadError(error.message))
  }, [selectedId, me?.id, loading])

  return {
    me,
    players,
    seasons,
    match,
    selectedId,
    setSelectedId,
    dataRevision,
    demo,
    loading,
    loadError,
    refresh,
    logout,
  }
}
