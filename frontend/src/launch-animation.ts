import gsap from 'gsap'
import { Physics2DPlugin } from 'gsap/Physics2DPlugin'

gsap.registerPlugin(Physics2DPlugin)

type Point = { x: number; y: number }
type Shot = {
  name: string
  timeline: gsap.core.Timeline
  contact: number
  net: number
}

const SHOT_DURATION = 3.6
const BALL_HOME: Point = { x: 206, y: 232 }

function startLaunchAnimation(splash: HTMLElement) {
  const find = (name: string) => splash.querySelector<SVGGraphicsElement>(`.club-launch-${name}`)
  const drone = find('drone')
  const ball = find('ball')
  const net = find('net')
  const goal = find('goal')
  if (!drone || !ball || !net || !goal) return

  const spin = find('ball-spin') ?? ball
  const shadow = find('shadow')
  const ballShadow = find('ball-shadow')
  const beer = splash.querySelector<HTMLElement>('.club-launch-beer-entrance')
  const bottle = find('bottle')
  const cap = find('bottle-cap')
  const capTurnMark = find('cap-turn-mark')
  const foam = find('bottle-foam')
  const halo = find('bottle-halo')
  const confettiScene = splash.querySelector<SVGSVGElement>('.club-launch-confetti-scene')
  const media = gsap.matchMedia()

  media.add('(prefers-reduced-motion: no-preference)', () => {
    const confettiColors = ['#ffd900', '#1d211c', '#d9b800', '#b4b6a8', '#fffdf6']
    const confetti = confettiScene
      ? Array.from({ length: 84 }, (_, index) => {
          const piece = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
          piece.setAttribute('class', 'club-launch-confetti')
          piece.setAttribute('x', '-3')
          piece.setAttribute('y', '-4')
          piece.setAttribute('width', String(5 + (index % 3)))
          piece.setAttribute('height', String(index % 3 === 0 ? 5 : 10))
          piece.setAttribute('rx', '1')
          piece.setAttribute('fill', confettiColors[index % confettiColors.length])
          confettiScene.append(piece)
          return piece
        })
      : []
    gsap.set(drone, { x: 0, y: 0, rotation: 0, scale: 1, svgOrigin: '140 180' })
    gsap.set(ball, { ...BALL_HOME, scale: 1, opacity: 1, svgOrigin: '0 0' })
    gsap.set(spin, { rotation: 0, scale: 1, svgOrigin: '0 0' })
    gsap.set(net, { scale: 1, skewY: 0, svgOrigin: '250 244' })
    gsap.set(goal, { opacity: 0, y: 5, scale: 0.94, svgOrigin: '355 64' })

    // The shadows follow the scene's actual positions, including when paused or sought.
    const updateShadows = () => {
      if (shadow) {
        const x = Number(gsap.getProperty(drone, 'x'))
        const y = Number(gsap.getProperty(drone, 'y'))
        const scale = gsap.utils.clamp(0.62, 1.06, 1 + y / 150)
        shadow.setAttribute(
          'transform',
          `translate(${x * 0.45} 0) translate(128 242) scale(${scale} 1) translate(-128 -242)`,
        )
        shadow.setAttribute('opacity', String(gsap.utils.clamp(0.06, 0.15, 0.14 + y / 600)))
      }
      if (ballShadow) {
        const x = Number(gsap.getProperty(ball, 'x'))
        const y = Number(gsap.getProperty(ball, 'y'))
        const radius = 18 * Number(gsap.getProperty(ball, 'scaleX'))
        // The rebound rolls toward the foreground, so its ground contact moves
        // below the deeper net floor instead of leaving a shadow through the ball.
        const ground = Math.max(248 - gsap.utils.clamp(0, 1, (x - 206) / 203) * 20, y + radius)
        const height = Math.max(0, ground - y - radius)
        const scale = gsap.utils.clamp(0.38, 1, 1 - height / 260)
        ballShadow.setAttribute('transform', `translate(${x} ${ground}) scale(${scale} 1)`)
        ballShadow.setAttribute(
          'opacity',
          String(Number(gsap.getProperty(ball, 'opacity')) * (0.06 + 0.1 * scale)),
        )
      }
    }

    // One continuous ballistic tween per flight: constant horizontal velocity and
    // gravitational acceleration, rather than an ease restarting at every waypoint.
    const flight = (
      timeline: gsap.core.Timeline,
      at: number,
      from: Point,
      to: Point,
      duration: number,
      gravity: number,
    ) => {
      const vx = (to.x - from.x) / duration
      const vy = (to.y - from.y - 0.5 * gravity * duration * duration) / duration
      timeline.fromTo(
        ball,
        from,
        {
          duration,
          physics2D: {
            velocity: Math.hypot(vx, vy),
            angle: (Math.atan2(vy, vx) * 180) / Math.PI,
            gravity,
          },
          ease: 'none',
          immediateRender: false,
        },
        at,
      )
    }

    const beginShot = (position = BALL_HOME) => {
      const timeline = gsap.timeline({ defaults: { duration: 0.25, ease: 'power2.out' } })
      timeline.set(drone, { x: 0, y: 0, rotation: 0, scale: 1, immediateRender: false }, 0)
      timeline.set(ball, { ...position, scale: 1, opacity: 0, immediateRender: false }, 0)
      timeline.set(spin, { rotation: 0, scale: 1, immediateRender: false }, 0)
      timeline.to(ball, { opacity: 1, duration: 0.14 }, 0)
      // A fixed beat leaves a short, quiet reset between attempts.
      timeline.to({}, { duration: 0.01 }, SHOT_DURATION - 0.01)
      return timeline
    }

    const score = (timeline: gsap.core.Timeline, at: number) => {
      timeline.addLabel('net', at)
      timeline.to(net, { scaleX: 1.025, scaleY: 0.985, skewY: -0.5, duration: 0.09 }, at)
      timeline.to(
        net,
        { scaleX: 1, scaleY: 1, skewY: 0, duration: 0.52, ease: 'elastic.out(1, 0.25)' },
        at + 0.09,
      )
      timeline.fromTo(
        goal,
        { opacity: 0, y: 5, scale: 0.94 },
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.16,
          ease: 'back.out(1.3)',
          immediateRender: false,
        },
        at + 0.04,
      )
      timeline.to(goal, { opacity: 0, y: -3, duration: 0.22, ease: 'power1.in' }, at + 0.72)
    }

    const strike = (
      timeline: gsap.core.Timeline,
      at: number,
      rotation: number,
      duration: number,
    ) => {
      timeline.addLabel('contact', at)
      timeline.to(spin, { scaleX: 1.08, scaleY: 0.94, duration: 0.045 }, at)
      timeline.to(spin, { scaleX: 1, scaleY: 1, duration: 0.11 }, at + 0.045)
      timeline.to(spin, { rotation, duration, ease: 'none' }, at)
      timeline.to(ball, { scale: 0.9, duration, ease: 'none' }, at)
    }

    const groundShot = (): Shot => {
      const timeline = beginShot()
      const contact = 0.8
      const impact = 1.43
      timeline.to(drone, { x: -13, y: -3, rotation: 8, duration: 0.38, ease: 'power2.inOut' }, 0.2)
      timeline.to(drone, { x: 26, y: 4, rotation: -7, duration: 0.22, ease: 'power2.in' }, 0.58)
      timeline.to(drone, { x: 31, y: -5, rotation: -12, duration: 0.18 }, contact)
      timeline.to(drone, { x: 8, y: -15, rotation: -4, duration: 0.48, ease: 'sine.inOut' }, 0.98)
      strike(timeline, contact, 650, impact - contact)
      flight(timeline, contact, BALL_HOME, { x: 409, y: 210 }, impact - contact, 0)
      score(timeline, impact)
      flight(timeline, impact, { x: 409, y: 210 }, { x: 395, y: 220 }, 0.23, 210)
      timeline.to(ball, { x: 400, y: 225, scale: 1, duration: 0.3 }, impact + 0.23)
      timeline.to(spin, { rotation: 615, duration: 0.23 }, impact)
      timeline.to(drone, { x: 3, y: -22, rotation: -5, duration: 0.24, ease: 'sine.out' }, 1.7)
      timeline.to(drone, { x: 0, y: 0, rotation: 0, duration: 0.58, ease: 'sine.inOut' }, 1.94)
      timeline.to(ball, { opacity: 0, duration: 0.2 }, 3.05)
      return { name: 'ground', timeline, contact, net: impact }
    }

    const headerShot = (): Shot => {
      const incoming = { x: 240, y: 26 }
      const hit = { x: 204, y: 78 }
      const timeline = beginShot(incoming)
      const contact = 0.92
      const impact = 1.76
      flight(timeline, 0.12, incoming, hit, 0.8, 162.5)
      timeline.to(spin, { rotation: -75, duration: 0.8, ease: 'none' }, 0.12)
      timeline.to(drone, { x: -7, y: 7, rotation: -7, duration: 0.3, ease: 'power1.inOut' }, 0.28)
      timeline.to(drone, { x: 24, y: -28, rotation: 12, duration: 0.34, ease: 'power2.in' }, 0.58)
      timeline.to(drone, { x: 31, y: -19, rotation: 20, duration: 0.18 }, contact)
      timeline.to(drone, { x: 12, y: -10, rotation: 3, duration: 0.43, ease: 'sine.inOut' }, 1.1)
      strike(timeline, contact, 290, impact - contact)
      flight(timeline, contact, hit, { x: 409, y: 175 }, impact - contact, 190)
      score(timeline, impact)
      flight(timeline, impact, { x: 409, y: 175 }, { x: 392, y: 172 }, 0.27, 240)
      flight(timeline, impact + 0.27, { x: 392, y: 172 }, { x: 397, y: 225 }, 0.58, 240)
      flight(timeline, impact + 0.85, { x: 397, y: 225 }, { x: 402, y: 225 }, 0.23, 340)
      timeline.to(ball, { scale: 1, duration: 0.85, ease: 'none' }, impact)
      timeline.to(spin, { rotation: 240, duration: 0.27 }, impact)
      timeline.to(spin, { rotation: 280, duration: 0.81, ease: 'none' }, impact + 0.27)
      timeline.to(drone, { x: 4, y: -20, rotation: -5, duration: 0.25, ease: 'sine.out' }, 1.98)
      timeline.to(drone, { x: 0, y: 0, rotation: 0, duration: 0.55, ease: 'sine.inOut' }, 2.23)
      timeline.to(ball, { opacity: 0, duration: 0.22 }, 3.15)
      return { name: 'header', timeline, contact, net: impact }
    }

    const bicycleShot = (): Shot => {
      const timeline = beginShot()
      const contact = 1.04
      const impact = 1.82
      const hit = { x: 206, y: 99 }
      timeline.to(drone, { x: -7, y: 7, rotation: 10, duration: 0.24, ease: 'power1.inOut' }, 0)
      timeline.to(drone, { x: 17, y: -3, rotation: -12, duration: 0.18, ease: 'power2.in' }, 0.24)
      // A toe flick lifts the ball before the body turns under it.
      flight(timeline, 0.42, BALL_HOME, hit, 0.62, 580)
      timeline.to(spin, { rotation: -180, duration: 0.62, ease: 'none' }, 0.42)
      timeline.to(drone, { rotation: -110, duration: 0.62, ease: 'power1.in' }, 0.42)
      timeline.to(drone, { x: 25, y: -46, duration: 0.42, ease: 'power2.out' }, 0.42)
      timeline.to(drone, { x: 29, y: -34, duration: 0.2, ease: 'power1.in' }, 0.84)
      timeline.to(drone, { rotation: -360, duration: 0.68, ease: 'power1.out' }, contact)
      timeline.to(drone, { x: 34, y: -26, duration: 0.3, ease: 'power1.in' }, contact)
      timeline.to(drone, { x: 10, y: 0, duration: 0.34, ease: 'power1.in' }, 1.34)
      timeline.to(drone, { x: 0, y: 6, scaleX: 1.02, scaleY: 0.97, duration: 0.12 }, 1.68)
      timeline.to(drone, { y: -14, scale: 1, duration: 0.28, ease: 'sine.out' }, 1.8)
      timeline.to(drone, { y: 0, duration: 0.52, ease: 'sine.inOut' }, 2.08)
      strike(timeline, contact, 340, impact - contact)
      flight(timeline, contact, hit, { x: 409, y: 210 }, impact - contact, 400)
      score(timeline, impact)
      flight(timeline, impact, { x: 409, y: 210 }, { x: 395, y: 210 }, 0.2, 250)
      flight(timeline, impact + 0.2, { x: 395, y: 210 }, { x: 400, y: 225 }, 0.24, 250)
      flight(timeline, impact + 0.44, { x: 400, y: 225 }, { x: 403, y: 225 }, 0.2, 250)
      timeline.to(ball, { scale: 1, duration: 0.44 }, impact)
      timeline.to(spin, { rotation: 300, duration: 0.2 }, impact)
      timeline.to(spin, { rotation: 340, duration: 0.44, ease: 'none' }, impact + 0.2)
      timeline.to(ball, { opacity: 0, duration: 0.2 }, 3.05)
      // -360 and 0 are the same pose: normalize only after the turn has settled.
      timeline.set(drone, { rotation: 0 }, 3.3)
      return { name: 'bicycle', timeline, contact, net: impact }
    }

    const master = gsap.timeline({ paused: true, repeat: -1, onUpdate: updateShadows })
    for (const [index, shot] of [groundShot(), headerShot(), bicycleShot()].entries()) {
      const at = index * SHOT_DURATION
      master.addLabel(shot.name, at)
      master.addLabel(`${shot.name}:contact`, at + shot.contact)
      master.addLabel(`${shot.name}:net`, at + shot.net)
      master.add(shot.timeline, at)
    }

    if (beer && bottle && cap && foam) {
      const enterAt = master.labels['bicycle:net'] + 0.3
      const celebrateAt = enterAt + 0.8
      const popAt = celebrateAt + 1.1
      master.addLabel('celebration:enter', enterAt)
      master.addLabel('celebration', celebrateAt)
      master.addLabel('celebration:pop', popAt)
      master.addLabel('celebration:reset', 14.55)
      master.addLabel('loop:end', 15)

      gsap.set(beer, { autoAlpha: 0, y: 0 })
      const offscreenY = () =>
        -(
          beer.getBoundingClientRect().top -
          Number(gsap.getProperty(beer, 'y')) +
          beer.offsetHeight +
          24
        )
      gsap.set(bottle, { x: 0, y: 0, rotation: 0, scale: 1, svgOrigin: '260 250' })
      gsap.set(cap, { x: 0, y: 0, rotation: 0, opacity: 1, svgOrigin: '260 43' })
      gsap.set(foam, { opacity: 0, y: 0, scaleX: 0.4, scaleY: 0.05, svgOrigin: '260 50' })
      gsap.set(confetti, { x: 0, y: 0, rotation: 0, scale: 1, opacity: 0, svgOrigin: '0 0' })
      if (capTurnMark) gsap.set(capTurnMark, { x: 0, opacity: 0 })
      if (halo) gsap.set(halo, { opacity: 0, scale: 0.92, svgOrigin: '260 145' })

      // Enter from beyond the viewport only once the third ball reaches the net.
      master.fromTo(
        beer,
        { autoAlpha: 0, y: offscreenY },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.8,
          ease: 'power3.out',
          immediateRender: false,
        },
        enterAt,
      )

      master.to(bottle, { rotation: -3, duration: 0.18, ease: 'power1.inOut' }, celebrateAt)
      master.to(bottle, { rotation: 2.5, duration: 0.16, ease: 'sine.inOut' }, celebrateAt + 0.18)
      master.to(bottle, { rotation: -1, duration: 0.14, ease: 'sine.inOut' }, celebrateAt + 0.34)
      master.to(
        bottle,
        { rotation: 0, scaleX: 1.006, scaleY: 0.988, duration: 0.16 },
        celebrateAt + 0.48,
      )
      master.to(
        bottle,
        { y: 4, rotation: 1.8, scale: 1, duration: 0.08, ease: 'power2.out' },
        popAt,
      )
      master.to(
        bottle,
        { y: 0, rotation: 0, duration: 0.55, ease: 'elastic.out(1, 0.35)' },
        popAt + 0.08,
      )

      // Successive turns lift the screw cap along the neck. A moving rib wraps
      // across its face to show rotation around the bottle's vertical axis.
      const unscrewAt = celebrateAt + 0.12
      master.to(cap, { y: -7, duration: 0.98, ease: 'sine.inOut' }, unscrewAt)
      for (let turn = 0; turn < 4; turn++) {
        const at = unscrewAt + turn * 0.24
        master.to(cap, { scaleX: 0.92, duration: 0.1, ease: 'sine.inOut' }, at)
        master.to(cap, { scaleX: 1, duration: 0.12, ease: 'sine.inOut' }, at + 0.1)
        if (capTurnMark) {
          master.fromTo(
            capTurnMark,
            { x: -7, opacity: 0 },
            {
              x: 7,
              opacity: 0.45,
              duration: 0.22,
              ease: 'none',
              immediateRender: false,
            },
            at,
          )
          master.to(capTurnMark, { opacity: 0, duration: 0.05 }, at + 0.17)
        }
      }
      master.to(cap, { x: 22, y: -24, rotation: 16, duration: 0.4, ease: 'power2.out' }, popAt)
      master.to(cap, { opacity: 0, duration: 0.25 }, popAt + 0.45)

      master.to(
        foam,
        { opacity: 1, scaleX: 1, scaleY: 1, duration: 0.22, ease: 'power2.out' },
        popAt,
      )
      master.to(
        foam,
        { y: -2, scaleX: 1.08, scaleY: 1.04, duration: 0.3, ease: 'sine.out' },
        popAt + 0.22,
      )
      master.to(
        foam,
        { opacity: 0, y: 10, scaleY: 0.6, duration: 0.6, ease: 'power1.in' },
        popAt + 0.85,
      )
      if (halo) {
        master.to(
          halo,
          { opacity: 0.35, scale: 1.06, duration: 0.45, ease: 'sine.out' },
          popAt - 0.12,
        )
        master.to(halo, { opacity: 0, scale: 1.18, duration: 1.1, ease: 'sine.in' }, popAt + 0.35)
      }

      confetti.forEach((piece, index) => {
        const at = popAt + (index % 9) * 0.02
        const duration = 2.4 + (index % 7) * 0.07
        const startY = -12 - (index % 7) * 18
        const vx = ((index * 19) % 81) - 40
        const vy = 100 + ((index * 17) % 150)
        // The overlay uses viewport pixels, so the rain spans the full screen
        // independently of the small illustration and cannot intercept taps.
        master.set(
          piece,
          {
            x: () => ((((index * 47) % 84) + 0.5) / 84) * window.innerWidth,
            y: startY,
            opacity: 0,
            scale: 1,
            rotation: index * 23,
          },
          at,
        )
        master.to(piece, { opacity: 1, duration: 0.04 }, at)
        master.to(
          piece,
          {
            physics2D: {
              velocity: Math.hypot(vx, vy),
              angle: (Math.atan2(vy, vx) * 180) / Math.PI,
              gravity: () =>
                (2 * (window.innerHeight + 40 - startY - vy * duration)) / (duration * duration),
            },
            rotation: (index % 2 ? 1 : -1) * (180 + index * 31),
            duration,
            ease: 'none',
          },
          at,
        )
        master.to(
          piece,
          { scaleX: 0.25, duration: 0.18, repeat: 11, yoyo: true, ease: 'sine.inOut' },
          at,
        )
        master.to(piece, { opacity: 0, duration: 0.28, ease: 'power1.in' }, at + duration - 0.28)
      })

      // Leave upward and remain hidden for all three goals in the next round.
      master.to(beer, { autoAlpha: 0, y: offscreenY, duration: 0.55, ease: 'power2.in' }, 14)
      master.set(bottle, { x: 0, y: 0, rotation: 0, scale: 1 }, 'celebration:reset')
      master.set(cap, { x: 0, y: 0, rotation: 0, opacity: 1 }, 'celebration:reset')
      master.set(foam, { opacity: 0, y: 0, scaleX: 0.4, scaleY: 0.05 }, 'celebration:reset')
      master.set(confetti, { x: 0, y: 0, rotation: 0, scale: 1, opacity: 0 }, 'celebration:reset')
      if (halo) master.set(halo, { opacity: 0, scale: 0.92 }, 'celebration:reset')
      master.to({}, { duration: 0.01 }, 14.99)
    }

    const syncPlayback = () => master.paused(splash.hidden || document.hidden)
    const observer = new MutationObserver(syncPlayback)
    observer.observe(splash, { attributes: true, attributeFilter: ['hidden'] })
    document.addEventListener('visibilitychange', syncPlayback)
    const onPageHide = () => master.pause()
    window.addEventListener('pagehide', onPageHide)
    window.addEventListener('pageshow', syncPlayback)
    updateShadows()
    syncPlayback()

    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', syncPlayback)
      window.removeEventListener('pagehide', onPageHide)
      window.removeEventListener('pageshow', syncPlayback)
      master.kill()
      confetti.forEach((piece) => piece.remove())
      shadow?.removeAttribute('transform')
      shadow?.setAttribute('opacity', '.14')
      ballShadow?.removeAttribute('transform')
      ballShadow?.setAttribute('opacity', '0')
    }
  })

  // Preserve paused state in the back-forward cache; fully release it when unloading.
  window.addEventListener('pagehide', (event) => {
    if (!event.persisted) media.revert()
  })
}

const splash = document.getElementById('club-launch')
if (splash) startLaunchAnimation(splash)
