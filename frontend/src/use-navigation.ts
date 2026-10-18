import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { SESSION_EXPIRED } from './api'

type Screen = {
  tab: string
  modal: string | null
  statsTarget: number | null
  ratingTarget: number | null
}
type Frame = Screen & { matchId: number | null; scroll: number; modalScroll: number }
const root: Screen = { tab: 'game', modal: null, statsTarget: null, ratingTarget: null }

export function useNavigation(
  selectedId: number | null,
  selectMatch: (id: number | null) => void,
  authenticated: boolean,
) {
  const [screen, setScreen] = useState<Screen>(root)
  const current = useRef<Frame>({ ...root, matchId: selectedId, scroll: 0, modalScroll: 0 })
  const history = useRef<Frame[]>([])
  const visited = useRef(new Set(['game']))
  const select = useRef(selectMatch)
  select.current = selectMatch
  current.current.matchId = selectedId

  function commit(frame: Frame) {
    current.current = frame
    visited.current.add(frame.tab)
    select.current(frame.matchId)
    setScreen({ ...frame })
  }

  function navigate(next: Partial<Frame>) {
    const previous = current.current
    const frame = { ...previous, ...next }
    if (
      frame.tab === previous.tab &&
      frame.modal === previous.modal &&
      frame.matchId === previous.matchId &&
      frame.statsTarget === previous.statsTarget &&
      frame.ratingTarget === previous.ratingTarget
    )
      return
    history.current.push({
      ...previous,
      scroll: window.scrollY,
      modalScroll: document.querySelector('.modal')?.scrollTop ?? 0,
    })
    commit({ ...frame, scroll: frame.modal ? window.scrollY : 0, modalScroll: 0 })
  }

  const back = useCallback(() => {
    const previous = history.current.pop()
    if (!previous) return
    current.current = previous
    select.current(previous.matchId)
    setScreen({ ...previous })
  }, [])

  const reset = useCallback(() => {
    history.current = []
    visited.current = new Set(['game'])
    const frame = { ...root, matchId: current.current.matchId, scroll: 0, modalScroll: 0 }
    current.current = frame
    setScreen({ ...frame })
  }, [])

  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED, reset)
    return () => window.removeEventListener(SESSION_EXPIRED, reset)
  }, [reset])

  useLayoutEffect(() => {
    window.scrollTo(0, current.current.scroll)
    const modal = document.querySelector('.modal')
    if (modal) modal.scrollTop = current.current.modalScroll
  }, [screen])

  const tg = window.Telegram?.WebApp
  const nativeBack =
    tg?.initData && (!tg.isVersionAtLeast || tg.isVersionAtLeast('6.1')) ? tg.BackButton : undefined
  const canBack = authenticated && history.current.length > 0
  useEffect(() => {
    if (!nativeBack) return
    nativeBack.onClick(back)
    return () => {
      nativeBack.offClick(back)
      nativeBack.hide()
    }
  }, [nativeBack, back])
  useEffect(() => {
    if (canBack) nativeBack?.show()
    else nativeBack?.hide()
  }, [nativeBack, canBack])

  return {
    ...screen,
    back,
    canBack,
    nativeBack: Boolean(nativeBack),
    reset,
    visited: (tab: string) => visited.current.has(tab),
    setTab: (tab: string) => {
      if (tab === 'game') reset()
      else navigate({ tab, modal: null })
    },
    setModal: (modal: string | null) => {
      if (modal === null) {
        if (current.current.modal) back()
      } else navigate({ modal })
    },
    openStats: (statsTarget: number) => navigate({ modal: 'stats', statsTarget }),
    openRatings: (ratingTarget: number | null) => navigate({ modal: 'ratings', ratingTarget }),
    openGame: (matchId: number) => navigate({ tab: 'game', modal: null, matchId }),
  }
}
