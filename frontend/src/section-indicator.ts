import { useLayoutEffect, useRef } from 'react'

/** Underline follows the selected tab. Changing direction keeps its live velocity. */
export function useSectionIndicator(selection: string) {
  const nav = useRef<HTMLElement>(null)
  const line = useRef<HTMLSpanElement>(null)
  const motion = useRef({ x: 0, w: 0, vx: 0, vw: 0, y: 0, initialized: false })

  useLayoutEffect(() => {
    const group = nav.current, mark = line.current
    if (!group || !mark) return
    const selected = group.querySelector<HTMLElement>('[aria-selected="true"]')
    if (!selected) return
    const state = motion.current
    const reduce = matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0
    const place = () => {
      cancelAnimationFrame(frame)
      if (!selected.offsetWidth) return
      const x = selected.offsetLeft, w = selected.offsetWidth
      const y = selected.offsetTop + selected.offsetHeight - 2
      const draw = () => {
        mark.style.transform = `translate(${state.x}px,${y}px) scaleX(${state.w})`
      }
      if (!state.initialized || reduce.matches || state.y !== y) {
        Object.assign(state, { x, w, vx: 0, vw: 0, y, initialized: true })
        draw()
        return
      }
      let last = performance.now()
      const stiffness = 26
      const tick = (time: number) => {
        const dt = Math.max(0, (time - last) / 1000)
        last = time
        const decay = Math.exp(-stiffness * dt)
        for (const [key, velocity, target] of [['x', 'vx', x], ['w', 'vw', w]] as const) {
          const delta = state[key] - target
          const impulse = state[velocity] + stiffness * delta
          state[key] = target + (delta + impulse * dt) * decay
          state[velocity] = (state[velocity] - stiffness * impulse * dt) * decay
        }
        if (Math.abs(x - state.x) + Math.abs(w - state.w) < .05 && Math.abs(state.vx) + Math.abs(state.vw) < 1) {
          Object.assign(state, { x, w, vx: 0, vw: 0 })
        } else frame = requestAnimationFrame(tick)
        draw()
      }
      frame = requestAnimationFrame(tick)
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(group)
    observer.observe(selected)
    reduce.addEventListener('change', place)
    return () => {
      observer.disconnect()
      reduce.removeEventListener('change', place)
      cancelAnimationFrame(frame)
    }
  }, [selection])
  return { nav, line }
}
