import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Eraser, GripVertical, Share2 } from 'lucide-react'
import { api } from './api'
import { Button } from './ui'
import { TeamDots } from './team-board'
import { PlayerName } from './player-name'
import { RatingMark, RatingPair, ratingNumber as fmt } from './rating-mark'
import { tacticalLayout, type Point } from './tactical-layout'
import type { Match, Player, Position, Team, Run, BalanceRun } from './types'

type Person = {
  registration_id: number
  player_id: number
  alias: string
  position: Position
  attack: number | null
  defense: number | null
  game_mu: number | null
}
type Source = 'manual' | 'community' | 'game' | 'auction'
type Lineup = {
  version: number
  roster_version: number
  fingerprint: string
  players: Person[]
  official_players: Person[] | null
  assignments: Record<string, Team | null>
  placements: Record<string, Point>
  editable: boolean
  share_available?: boolean
  min_field_players: number
  require_two_keepers: boolean
  auction: {
    id: number
    status: string
    assignments: Record<string, Team>
    prices: Record<string, number>
  } | null
}
type Preview = Lineup & { method: 'community' | 'game'; result: BalanceRun['result'] }
type Draft = Pick<
  Lineup,
  'version' | 'roster_version' | 'fingerprint' | 'assignments' | 'placements'
> & { source: Source; variant: number }

function saved(key: string): Draft | null {
  try {
    const d = JSON.parse(localStorage.getItem(key) || 'null')
    if (
      !d ||
      !Number.isInteger(d.version) ||
      !Number.isInteger(d.roster_version) ||
      typeof d.fingerprint !== 'string' ||
      !['manual', 'community', 'game', 'auction'].includes(d.source) ||
      !Number.isInteger(d.variant) ||
      d.variant < 0 ||
      d.variant > 2 ||
      !d.assignments ||
      !d.placements
    )
      return null
    if (
      Object.entries(d.assignments).some(
        ([id, t]) =>
          !Number.isInteger(Number(id)) || ![null, 'white', 'black'].includes(t as Team | null),
      )
    )
      return null
    if (
      Object.values(d.placements).some(
        (p) =>
          !p ||
          !['x', 'y'].every(
            (k) =>
              typeof (p as Point)[k as keyof Point] === 'number' &&
              Number.isFinite((p as Point)[k as keyof Point]) &&
              (p as Point)[k as keyof Point] >= 0 &&
              (p as Point)[k as keyof Point] <= 1,
          ),
      )
    )
      return null
    return d
  } catch {
    return null
  }
}

export function TacticsScreen({
  match: m,
  me,
  busy,
  run,
  onChanged,
  onAuction,
}: {
  match: Match
  me: Player
  busy: boolean
  run: Run
  onChanged: () => Promise<void>
  onAuction: () => void
}) {
  const key = `fczhk-lineup-v1:${me.id}:${m.id}`
  const [data, setData] = useState<Lineup | null>(null)
  const [draft, setDraft] = useState<Draft | null>(() => saved(key))
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [rosterOpen, setRosterOpen] = useState(true)
  const [selected, setSelected] = useState<number | null>(null)
  const [ghost, setGhost] = useState<{ id: number; x: number; y: number } | null>(null)
  const board = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const changed = useRef(onChanged)
  changed.current = onChanged
  useEffect(() => {
    let active = true,
      pending = false
    async function load() {
      if (pending) return
      pending = true
      try {
        const next = await api<Lineup>(`/matches/${m.id}/lineup`)
        if (active) {
          setData((old) => (!old || next.version >= old.version ? next : old))
          if (next.version !== m.version) void changed.current()
        }
      } catch (e) {
        if (active) setError((e as Error).message)
      } finally {
        pending = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), 15000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [m.id, m.version])
  useEffect(() => {
    try {
      if (draft) localStorage.setItem(key, JSON.stringify(draft))
      else localStorage.removeItem(key)
    } catch {
      /* Storage can be disabled in an embedded browser. */
    }
  }, [draft, key])
  useEffect(() => {
    if (data && !data.editable) {
      setDraft(null)
      setPreview(null)
      setSelected(null)
    }
  }, [data?.editable])
  if (!data) return <p role={error ? 'alert' : 'status'}>{error || 'Загружаем составы…'}</p>
  const people = !draft && data.official_players ? data.official_players : data.players
  const assignments = draft?.assignments ?? data.assignments
  const placements = draft?.placements ?? data.placements
  const positions = tacticalLayout(people, assignments)
  for (const p of people) {
    const point = placements[p.registration_id]
    if (point && point.y >= 0.5 === (assignments[p.registration_id] === 'white'))
      positions[p.registration_id] = point
  }
  const stale = Boolean(
    draft &&
    (draft.version !== data.version ||
      draft.roster_version !== data.roster_version ||
      draft.fingerprint !== data.fingerprint),
  )
  const disabled = busy || working || !data.editable
  const base = (): Draft =>
    draft ?? {
      version: data.version,
      roster_version: data.roster_version,
      fingerprint: data.fingerprint,
      assignments: { ...data.assignments },
      placements: { ...data.placements },
      source: 'manual',
      variant: 0,
    }
  function setTeam(id: number, team: Team | null) {
    const d = base(),
      next = { ...d.placements }
    delete next[id]
    setDraft({ ...d, assignments: { ...d.assignments, [id]: team }, placements: next })
  }
  function place(id: number, point: Point) {
    const d = base()
    const x = Math.max(0.13, Math.min(0.87, point.x)),
      y = Math.max(0.06, Math.min(0.94, point.y))
    setDraft({
      ...d,
      assignments: { ...d.assignments, [id]: y >= 0.5 ? 'white' : 'black' },
      placements: { ...d.placements, [id]: { x, y } },
    })
    setSelected(null)
  }
  function pointAt(x: number, y: number): Point | null {
    const r = board.current?.getBoundingClientRect()
    return r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
      ? { x: (x - r.left) / r.width, y: (y - r.top) / r.height }
      : null
  }
  function pointerDown(e: ReactPointerEvent<HTMLElement>, id: number) {
    if (disabled || e.button !== 0) return
    drag.current = { id, x: e.clientX, y: e.clientY, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  function pointerMove(e: ReactPointerEvent<HTMLElement>) {
    const d = drag.current
    if (!d) return
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6) d.moved = true
    if (d.moved) setGhost({ id: d.id, x: e.clientX, y: e.clientY })
  }
  function pointerUp(e: ReactPointerEvent<HTMLElement>) {
    const d = drag.current
    drag.current = null
    setGhost(null)
    if (d?.moved) {
      suppressClick.current = true
      setTimeout(() => {
        suppressClick.current = false
      }, 0)
      const p = pointAt(e.clientX, e.clientY)
      if (p) place(d.id, p)
    }
  }
  const pointerHandlers = (id: number) => ({
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => pointerDown(e, id),
    onPointerMove: pointerMove,
    onPointerUp: pointerUp,
    onPointerCancel: () => {
      drag.current = null
      setGhost(null)
    },
  })
  function select(id: number) {
    if (suppressClick.current || disabled) return
    setSelected(selected === id ? null : id)
    board.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  function loadVariant(p: Preview, i: number) {
    setDraft({
      version: p.version,
      roster_version: p.roster_version,
      fingerprint: p.fingerprint,
      source: p.method,
      variant: i,
      assignments: p.result.variants[i].assignments,
      placements: {},
    })
    setSelected(null)
  }
  async function loadSource(source: Source) {
    setWorking(true)
    setError('')
    try {
      if (source === 'community' || source === 'game') {
        const p = await api<Preview>(`/matches/${m.id}/lineup/preview`, 'POST', {
          version: data!.version,
          method: source,
        })
        setData(p)
        setPreview(p)
        loadVariant(p, 0)
      } else {
        const p = await api<Lineup>(`/matches/${m.id}/lineup`)
        if (!p.auction || p.auction.status !== 'completed')
          throw new Error('Сначала завершите аукцион')
        const next: Lineup['assignments'] = Object.fromEntries(
          p.players.map((r) => [
            r.registration_id,
            p.auction!.assignments[r.registration_id] ?? null,
          ]),
        )
        const keepers = p.players.filter((r) => r.position === 'keeper')
        keepers.forEach((r, i) => {
          next[r.registration_id] = i === 0 ? 'white' : i === 1 ? 'black' : null
        })
        setData(p)
        setPreview(null)
        setDraft({
          version: p.version,
          roster_version: p.roster_version,
          fingerprint: p.fingerprint,
          source,
          variant: 0,
          assignments: next,
          placements: {},
        })
      }
      setRosterOpen(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setWorking(false)
    }
  }
  const counts = (team: Team, position: Position) =>
    people.filter((p) => assignments[p.registration_id] === team && p.position === position).length
  const fieldWhite = counts('white', 'field'),
    fieldBlack = counts('black', 'field'),
    keeperWhite = counts('white', 'keeper'),
    keeperBlack = counts('black', 'keeper')
  const complete =
    people.length > 0 &&
    people.every((p) => assignments[p.registration_id]) &&
    fieldWhite + fieldBlack >= data.min_field_players &&
    Math.abs(fieldWhite - fieldBlack) <= 1 &&
    Math.abs(fieldWhite + keeperWhite - fieldBlack - keeperBlack) <= 1 &&
    keeperWhite <= 1 &&
    keeperBlack <= 1 &&
    (!data.require_two_keepers || keeperWhite + keeperBlack === 2)
  const auctionRunning = ['active', 'paused'].includes(data.auction?.status || '')
  const ordered = [...people].sort(
    (a, b) =>
      Number(Boolean(assignments[a.registration_id])) -
        Number(Boolean(assignments[b.registration_id])) || a.alias.localeCompare(b.alias, 'ru'),
  )
  async function confirm() {
    const d = base()
    await api(`/matches/${m.id}/lineup/confirm`, 'POST', d)
    setData(await api<Lineup>(`/matches/${m.id}/lineup`))
    setDraft(null)
    setPreview(null)
  }
  function clearBoard() {
    setDraft({
      version: data!.version,
      roster_version: data!.roster_version,
      fingerprint: data!.fingerprint,
      assignments: Object.fromEntries(data!.players.map((p) => [p.registration_id, null])),
      placements: {},
      source: 'manual',
      variant: 0,
    })
    setPreview(null)
    setSelected(null)
    setGhost(null)
    drag.current = null
    setError('')
    setRosterOpen(true)
  }
  const canShare =
    people.length > 0 &&
    people.every((p) => assignments[p.registration_id]) &&
    people.some((p) => assignments[p.registration_id] === 'white') &&
    people.some((p) => assignments[p.registration_id] === 'black')
  async function share() {
    const d = base()
    await api(`/matches/${m.id}/lineup/share`, 'POST', {
      version: d.version,
      roster_version: d.roster_version,
      fingerprint: d.fingerprint,
      assignments,
      official: !draft && Boolean(data!.official_players),
    })
  }
  return (
    <div className="tactics-screen">
      <div className="section-title">
        <h1>Составы</h1>
        <span className="tag">
          {draft ? 'Личный черновик' : data.official_players ? 'Утверждены' : 'Распределение'}
        </span>
      </div>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {stale && (
        <div role="alert" className="alert">
          Список или оценки изменились.{' '}
          <button
            onClick={() => {
              setDraft({
                ...base(),
                version: data.version,
                roster_version: data.roster_version,
                fingerprint: data.fingerprint,
                assignments: Object.fromEntries(
                  data.players.map((p) => [
                    p.registration_id,
                    assignments[p.registration_id] ?? null,
                  ]),
                ),
                placements: {},
                source: 'manual',
              })
              setPreview(null)
            }}
          >
            Обновить черновик
          </button>
        </div>
      )}
      <div className="inline wrap">
        {data.editable && (
          <Button
            className="ghost compact"
            disabled={disabled || !people.some((p) => assignments[p.registration_id])}
            onClick={clearBoard}
          >
            <Eraser size={16} /> Очистить доску
          </Button>
        )}
        <Button
          className="ghost compact"
          disabled={busy || working || stale || !canShare || !data.share_available}
          title={
            !data.share_available
              ? 'Администратор ещё не настроил чат для составов'
              : !canShare
                ? 'Распределите всех игроков по двум командам'
                : 'Отправить вариант состава в чат ФК Желтый Колобок'
          }
          onClick={() => void run(share, 'Состав поставлен в очередь отправки в чат')}
        >
          <Share2 size={16} /> Поделиться в чат
        </Button>
      </div>
      <div
        className="tactics-pitch"
        ref={board}
        role="group"
        aria-label="Тактическая доска"
        onClick={(e) => {
          if (selected !== null && !disabled && !suppressClick.current) {
            const p = pointAt(e.clientX, e.clientY)
            if (p) place(selected, p)
          }
        }}
      >
        <div className="tactics-center" aria-hidden="true" />
        <div className="tactics-goal top" aria-hidden="true" />
        <div className="tactics-goal bottom" aria-hidden="true" />
        {people
          .filter((p) => assignments[p.registration_id])
          .map((p) => {
            const point = positions[p.registration_id]
            return (
              <div
                key={p.registration_id}
                className={`tactics-token ${assignments[p.registration_id]} ${selected === p.registration_id ? 'selected' : ''}`}
                style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
              >
                <button
                  type="button"
                  className="tactics-position"
                  aria-label={`На поле: ${p.alias}`}
                  aria-pressed={selected === p.registration_id}
                  {...pointerHandlers(p.registration_id)}
                  onClick={(e) => {
                    e.stopPropagation()
                    select(p.registration_id)
                  }}
                  onKeyDown={(e) => {
                    const directions: Record<string, Point> = {
                      ArrowLeft: { x: -0.03, y: 0 },
                      ArrowRight: { x: 0.03, y: 0 },
                      ArrowUp: { x: 0, y: -0.03 },
                      ArrowDown: { x: 0, y: 0.03 },
                    }
                    const delta = directions[e.key]
                    if (delta && !disabled) {
                      e.preventDefault()
                      place(p.registration_id, { x: point.x + delta.x, y: point.y + delta.y })
                    }
                    if (e.key === 'Escape') setSelected(null)
                  }}
                >
                  <span className="tactics-shirt">{p.position === 'keeper' ? 'ВР' : ''}</span>
                </button>
                <PlayerName playerId={p.player_id} alias={p.alias} className="tactics-alias" />
              </div>
            )
          })}
        {!people.some((p) => assignments[p.registration_id]) && (
          <p className="tactics-empty">Выберите вариант или добавьте игроков из списка</p>
        )}
      </div>
      <p className="muted caption tactics-hint" role="status">
        {selected !== null
          ? `Куда поставить ${people.find((p) => p.registration_id === selected)?.alias}? Нажмите на поле.`
          : data.editable
            ? 'Перетащите значок игрока или выберите его и нажмите на поле. Имя открывает профиль.'
            : 'Состав завершённой игры'}
      </p>
      <div className="tactics-scores" aria-label="Баллы команд">
        {(['white', 'black'] as Team[]).map((team) => {
          const teamPeople = people.filter((p) => assignments[p.registration_id] === team)
          const sum = (kind: 'attack' | 'defense') => {
            const relevant = teamPeople.filter((p) => kind === 'defense' || p.position === 'field')
            const rated = relevant.filter((p) => p[kind] !== null)
            const known = relevant.reduce((n, p) => n + (p[kind] ?? 0), 0)
            return rated.length ? `${rated.length < relevant.length ? '≥ ' : ''}${fmt(known)}` : '—'
          }
          const total = teamPeople.reduce(
            (n, p) => n + (p.defense ?? 0) + (p.position === 'field' ? (p.attack ?? 0) : 0),
            0,
          )
          const partial = teamPeople.some(
            (p) => p.defense === null || (p.position === 'field' && p.attack === null),
          )
          const rated = teamPeople.some(
            (p) => p.defense !== null || (p.position === 'field' && p.attack !== null),
          )
          return (
            <div key={team}>
              <strong>
                {team === 'white' ? '⚪ Белые' : '⚫ Чёрные'} <small>{teamPeople.length}</small>
              </strong>
              <span>
                <RatingMark kind="attack" /> {sum('attack')}
              </span>
              <span>
                <RatingMark kind="defense" /> {sum('defense')}
              </span>
              <span>Σ {rated ? `${partial ? '≥ ' : ''}${fmt(total)}` : '—'}</span>
              {draft?.source === 'game' && (
                <small className="tactics-mu">
                  OpenSkill μ:{' '}
                  {fmt(
                    teamPeople
                      .filter((p) => p.position === 'field')
                      .reduce((n, p) => n + (p.game_mu ?? 0), 0),
                  )}
                </small>
              )}
            </div>
          )
        })}
      </div>
      {data.editable && (
        <>
          <div className="tactics-sources">
            {(
              [
                ['community', 'По оценкам'],
                ['game', 'OpenSkill'],
                ['auction', 'Аукцион'],
              ] as const
            ).map(([source, label]) => (
              <Button
                key={source}
                className={`secondary compact ${draft?.source === source ? 'active' : ''}`}
                disabled={
                  disabled || (source === 'auction' && data.auction?.status !== 'completed')
                }
                onClick={() => void loadSource(source)}
              >
                {working ? '…' : label}
              </Button>
            ))}
          </div>
          {preview && (
            <div className="tactics-variants" role="group" aria-label="Варианты составов">
              <span className="muted caption">Вариант</span>
              {preview.result.variants.map((_, i) => (
                <button
                  key={i}
                  aria-label={`Показать вариант ${i + 1}`}
                  aria-pressed={draft?.variant === i}
                  disabled={disabled || stale}
                  onClick={() => loadVariant(preview, i)}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          )}
        </>
      )}
      {data.editable && (
        <details
          className="panel tactics-roster"
          open={rosterOpen}
          onToggle={(e) => setRosterOpen(e.currentTarget.open)}
        >
          <summary>
            Игроки{' '}
            <span className="muted">
              {people.length} · без команды{' '}
              {people.filter((p) => !assignments[p.registration_id]).length}
            </span>
          </summary>
          {(expanded ? ordered : ordered.slice(0, 6)).map((p) => (
            <div className="tactics-roster-row" key={p.registration_id}>
              <div className="tactics-person">
                <div className="tactics-name">
                  {p.position === 'keeper' ? '🧤 ' : ''}
                  <PlayerName playerId={p.player_id} alias={p.alias} />
                </div>
                <small className="muted">
                  <RatingPair
                    attack={p.attack}
                    defense={p.defense}
                    keeper={p.position === 'keeper'}
                  />
                  {draft?.source === 'auction' &&
                    data.auction?.prices[p.registration_id] !== undefined && (
                      <> · {data.auction.prices[p.registration_id]} баллов</>
                    )}
                </small>
              </div>
              <button
                type="button"
                className="tactics-drag"
                aria-label={`Перетащить: ${p.alias}`}
                disabled={disabled}
                {...pointerHandlers(p.registration_id)}
                onClick={() => select(p.registration_id)}
              >
                <GripVertical size={18} />
              </button>
              <TeamDots
                alias={p.alias}
                team={assignments[p.registration_id] ?? null}
                disabled={disabled}
                onChange={(team) => setTeam(p.registration_id, team)}
              />
            </div>
          ))}
          {people.length > 6 && (
            <Button className="ghost compact" onClick={() => setExpanded(!expanded)}>
              {expanded ? 'Свернуть список' : `Все игроки · ${people.length}`}
            </Button>
          )}
        </details>
      )}
      {data.editable && (
        <div className="tactics-footer">
          <p className="muted caption">
            {draft
              ? 'Личный черновик сохранён в этом браузере.'
              : 'Изменения на доске видны только вам.'}
          </p>
          {me.is_admin || me.is_owner ? (
            <>
              <Button
                disabled={
                  disabled ||
                  stale ||
                  !complete ||
                  auctionRunning ||
                  !['finalized', 'approved'].includes(m.status)
                }
                onClick={() => void run(confirm, 'Состав утверждён для всех участников')}
              >
                Утвердить состав
              </Button>
              {m.status === 'open' && (
                <small className="muted">
                  Сначала зафиксируйте составы на игру на вкладке «Игра».
                </small>
              )}
              {auctionRunning && (
                <small className="muted">Подтверждение доступно после завершения аукциона.</small>
              )}
            </>
          ) : (
            <small className="muted">Общий состав подтверждает администратор.</small>
          )}
        </div>
      )}
      <details className="panel tactics-details">
        <summary>Действия и подробности</summary>
        <p className="muted caption">
          Сумма атаки — только полевые, защиты — все игроки. Σ — атака + защита. Знак ≥ означает,
          что есть игроки без оценок. OpenSkill считается отдельно.
        </p>
        {data.editable && (
          <div className="inline">
            <Button
              className="ghost compact"
              disabled={disabled}
              onClick={() => {
                const d = base()
                setDraft({
                  ...d,
                  assignments: Object.fromEntries(
                    Object.entries(d.assignments).map(([id, t]) => [
                      id,
                      t === 'white' ? 'black' : t === 'black' ? 'white' : null,
                    ]),
                  ),
                  placements: Object.fromEntries(
                    Object.entries(d.placements).map(([id, p]) => [id, { x: 1 - p.x, y: 1 - p.y }]),
                  ),
                })
              }}
            >
              Поменять цвета команд
            </Button>
            {draft && (
              <Button
                className="ghost compact"
                onClick={() => {
                  setDraft(null)
                  setPreview(null)
                  setSelected(null)
                }}
              >
                Вернуть общий состав
              </Button>
            )}
          </div>
        )}
        {preview?.result.warnings.map((w) => (
          <p key={w} className="muted caption">
            {w}
          </p>
        ))}
        {data.auction && (
          <Button className="ghost compact" onClick={onAuction}>
            Открыть аукцион
          </Button>
        )}
      </details>
      {ghost && (
        <div className="tactics-drag-ghost" style={{ left: ghost.x, top: ghost.y }}>
          {people.find((p) => p.registration_id === ghost.id)?.alias}
        </div>
      )}
    </div>
  )
}
