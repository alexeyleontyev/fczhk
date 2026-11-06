import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Copy, Eraser, Share2 } from 'lucide-react'
import { api } from './api'
import { Button } from './ui'
import { PlayerName } from './player-name'
import { ratingNumber } from './rating-mark'
import { LineupRatings } from './lineup-ratings'
import { LineupTeams, LineupTotals } from './lineup-teams'
import { strengthScale } from './lineup-strength'
import { tacticalLayout, type Point } from './tactical-layout'
import { gameSummary, teamSummary } from './confirmation-summary'
import type { Match, Player, Team, Run } from './types'
import type { Draft, Lineup, Preview, Proposals } from './lineup-types'

function saved(key: string): Draft | null {
  try {
    const d = JSON.parse(localStorage.getItem(key) || 'null')
    if (
      !d ||
      !Number.isInteger(d.version) ||
      !Number.isInteger(d.roster_version) ||
      !/^[a-f0-9]{64}$/.test(d.fingerprint) ||
      !['manual', 'community', 'game', 'auction', 'proposal'].includes(d.source) ||
      !Number.isInteger(d.variant) ||
      d.variant < 0 ||
      d.variant > 2 ||
      !d.assignments ||
      !d.placements
    )
      return null
    if (
      Object.entries(d.assignments).some(
        ([id, team]) =>
          !Number.isInteger(Number(id)) || ![null, 'white', 'black'].includes(team as Team | null),
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
    if (
      (d.proposal_id === undefined) !== (d.proposal_revision === undefined) ||
      (d.proposal_id !== undefined &&
        (!Number.isInteger(d.proposal_id) ||
          d.proposal_id < 1 ||
          !Number.isInteger(d.proposal_revision) ||
          d.proposal_revision < 1))
    )
      return null
    return d
  } catch {
    return null
  }
}

const proposalChoice = (id: number) => `proposal:${id}`
const proposalDate = (value: string) =>
  new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  })

export function TacticsScreen({
  match: m,
  me,
  view,
  busy,
  run,
  onChanged,
  onAuction,
}: {
  match: Match
  me: Player
  view: 'teams' | 'field'
  busy: boolean
  run: Run
  onChanged: () => Promise<void>
  onAuction: () => void
}) {
  const key = `fczhk-lineup-v1:${me.id}:${m.id}`
  const [data, setData] = useState<Lineup | null>(null)
  const [proposals, setProposals] = useState<Proposals>({
    proposals: [],
    mine_revision: 0,
    editable: false,
  })
  const [draft, setDraft] = useState<Draft | null>(() => saved(key))
  const [choice, setChoice] = useState('official')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [candidate, setCandidate] = useState<Draft | null>(null)
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [ghost, setGhost] = useState<{ id: number; x: number; y: number } | null>(null)
  const initialized = useRef(false)
  const board = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const changed = useRef(onChanged)
  changed.current = onChanged

  async function reload() {
    const [next, nextProposals] = await Promise.all([
      api<Lineup>(`/matches/${m.id}/lineup`),
      api<Proposals>(`/matches/${m.id}/lineup/proposals`),
    ])
    setData(next)
    setProposals(nextProposals)
    return next
  }

  useEffect(() => {
    let active = true,
      pending = false
    async function load() {
      if (pending) return
      pending = true
      try {
        const [next, list] = await Promise.all([
          api<Lineup>(`/matches/${m.id}/lineup`),
          api<Proposals>(`/matches/${m.id}/lineup/proposals`),
        ])
        if (active) {
          setData((old) => (!old || next.version >= old.version ? next : old))
          setProposals(list)
          if (!initialized.current) {
            initialized.current = true
            setChoice(next.official_players ? 'official' : 'draft')
          }
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
      /* Embedded browsers may disable storage. */
    }
  }, [draft, key])
  useEffect(() => {
    if (data && !data.editable && !choice.startsWith('proposal:')) {
      setChoice('official')
      setCandidate(null)
      setSelected(null)
    }
  }, [data?.editable])

  if (!data) return <p role={error ? 'alert' : 'status'}>{error || 'Загружаем составы…'}</p>
  const proposal = proposals.proposals.find((p) => proposalChoice(p.id) === choice)
  const official = choice === 'official'
  const ownDraft = choice === 'draft'
  const people =
    proposal?.players ?? (official && data.official_players ? data.official_players : data.players)
  const selectedDraft: Draft = proposal
    ? {
        version: data.version,
        roster_version: proposal.roster_version,
        fingerprint: proposal.fingerprint,
        assignments: proposal.assignments,
        placements: proposal.placements,
        source: 'proposal',
        variant: 0,
        proposal_id: proposal.id,
        proposal_revision: proposal.revision,
      }
    : ownDraft && draft
      ? draft
      : !official && !ownDraft && candidate
        ? candidate
        : {
            version: data.version,
            roster_version: data.roster_version,
            fingerprint: data.fingerprint,
            assignments: official
              ? (data.official_assignments ?? (data.official_players ? data.assignments : {}))
              : data.assignments,
            placements: data.placements,
            source: 'manual',
            variant: 0,
          }
  const { assignments, placements } = selectedDraft
  const missingProposal = choice.startsWith('proposal:') && !proposal
  const stale =
    missingProposal ||
    (!official &&
      (selectedDraft.version !== data.version ||
        selectedDraft.roster_version !== data.roster_version ||
        selectedDraft.fingerprint !== data.fingerprint ||
        Boolean(proposal?.roster_stale)))
  const disabled = busy || working || !data.editable || stale
  const colorByPlayer = new Map(data.players.map((p) => [p.player_id, p]))
  const scale = strengthScale(data.players)
  const color = (p: (typeof people)[number]) => scale(colorByPlayer.get(p.player_id) ?? p)
  const positions = tacticalLayout(people, assignments)
  for (const p of people) {
    const point = placements[p.registration_id]
    if (point && point.y >= 0.5 === (assignments[p.registration_id] === 'white'))
      positions[p.registration_id] = point
  }
  const base = (): Draft => ({
    ...selectedDraft,
    assignments: { ...assignments },
    placements: { ...placements },
  })
  function edit(next: Draft) {
    setDraft({ ...next, source: next.source === 'proposal' ? 'manual' : next.source })
    setChoice('draft')
    setSelected(null)
  }
  function setTeam(id: number, team: Team | null) {
    if (disabled || assignments[id] === team) return
    const d = base(),
      next = { ...d.placements }
    delete next[id]
    edit({ ...d, assignments: { ...d.assignments, [id]: team }, placements: next })
  }
  function place(id: number, point: Point) {
    if (disabled) return
    const d = base(),
      x = Math.max(0.13, Math.min(0.87, point.x)),
      y = Math.max(0.06, Math.min(0.94, point.y))
    edit({
      ...d,
      assignments: { ...d.assignments, [id]: y >= 0.5 ? 'white' : 'black' },
      placements: { ...d.placements, [id]: { x, y } },
    })
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
  const handlers = (id: number) => ({
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => pointerDown(e, id),
    onPointerMove: pointerMove,
    onPointerUp: pointerUp,
    onPointerCancel: () => {
      drag.current = null
      setGhost(null)
    },
  })

  function loadVariant(p: Preview, i: number) {
    setCandidate({
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
  async function choose(next: string) {
    setError('')
    setSelected(null)
    if (['official', 'draft'].includes(next) || next.startsWith('proposal:')) {
      if (next === 'draft' && !draft) setDraft(base())
      setChoice(next)
      return
    }
    setWorking(true)
    try {
      if (next === 'community' || next === 'game') {
        const p = await api<Preview>(`/matches/${m.id}/lineup/preview`, 'POST', {
          version: data!.version,
          method: next,
        })
        setData(p)
        setPreview(p)
        loadVariant(p, 0)
      } else {
        const p = await api<Lineup>(`/matches/${m.id}/lineup`)
        if (!p.auction || p.auction.status !== 'completed')
          throw new Error('Сначала завершите аукцион')
        const nextAssignments: Lineup['assignments'] = Object.fromEntries(
          p.players.map((r) => [
            r.registration_id,
            p.auction!.assignments[r.registration_id] ?? null,
          ]),
        )
        p.players
          .filter((r) => r.position === 'keeper')
          .forEach((r, i) => {
            nextAssignments[r.registration_id] = i === 0 ? 'white' : i === 1 ? 'black' : null
          })
        setData(p)
        setPreview(null)
        setCandidate({
          version: p.version,
          roster_version: p.roster_version,
          fingerprint: p.fingerprint,
          source: 'auction',
          variant: 0,
          assignments: nextAssignments,
          placements: {},
        })
      }
      setChoice(next)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setWorking(false)
    }
  }
  function refreshDraft() {
    const oldPlayers = new Map(people.map((p) => [p.player_id, p]))
    const next = Object.fromEntries(
      data!.players.map((p) => {
        const old = oldPlayers.get(p.player_id)
        return [
          p.registration_id,
          old && old.position === p.position ? (assignments[old.registration_id] ?? null) : null,
        ]
      }),
    )
    edit({
      version: data!.version,
      roster_version: data!.roster_version,
      fingerprint: data!.fingerprint,
      assignments: next,
      placements: {},
      source: 'manual',
      variant: 0,
    })
    setPreview(null)
  }
  const counts = (team: Team, position: 'field' | 'keeper') =>
    people.filter((p) => assignments[p.registration_id] === team && p.position === position).length
  const fw = counts('white', 'field'),
    fb = counts('black', 'field'),
    kw = counts('white', 'keeper'),
    kb = counts('black', 'keeper')
  const complete =
    people.length > 0 &&
    people.every((p) => assignments[p.registration_id]) &&
    fw + fb >= data.min_field_players &&
    Math.abs(fw - fb) <= 1 &&
    Math.abs(fw + kw - fb - kb) <= 1 &&
    kw <= 1 &&
    kb <= 1 &&
    (!data.require_two_keepers || kw + kb === 2)
  const auctionRunning = ['active', 'paused'].includes(data.auction?.status || '')
  const mine = proposals.proposals.find((p) => p.author_id === me.id)
  const title = proposal
    ? `Предложение: ${proposal.author}`
    : official
      ? data.official_players
        ? 'Утверждённый состав'
        : 'Состав ещё не утверждён'
      : ownDraft
        ? 'Моя прикидка'
        : choice === 'community'
          ? 'По оценкам сообщества'
          : choice === 'game'
            ? 'По OpenSkill'
            : 'По результатам аукциона'

  async function propose() {
    const d = base()
    await run(
      async () => {
        const result = await api<{ id: number }>(`/matches/${m.id}/lineup/proposals/mine`, 'PUT', {
          roster_version: d.roster_version,
          fingerprint: d.fingerprint,
          assignments: d.assignments,
          placements: d.placements,
          revision: proposals.mine_revision,
        })
        await reload()
        setChoice(proposalChoice(result.id))
      },
      mine ? 'Предложение обновлено для сообщества' : 'Ваш вариант доступен участникам сообщества',
    )
  }
  async function withdraw() {
    if (!mine) return
    await run(async () => {
      await api(`/matches/${m.id}/lineup/proposals/mine/withdraw`, 'POST', {
        revision: mine.revision,
      })
      await reload()
      if (choice === proposalChoice(mine.id))
        setChoice(data!.official_players ? 'official' : 'draft')
    }, 'Предложение отозвано')
  }
  async function confirm() {
    if (
      (m.status === 'approved' || data!.official_players) &&
      !window.confirm(
        `Заменить утверждённые составы?\n${gameSummary(m)}\n\n${teamSummary(people.map((p) => ({ alias: p.alias, team: assignments[p.registration_id] ?? null })))}\n\nЭтот вариант станет общим для всех участников. Прежние публикации составов будут помечены неактуальными.`,
      )
    )
      return
    await run(async () => {
      await api(`/matches/${m.id}/lineup/confirm`, 'POST', base())
      await reload()
      setChoice('official')
      setCandidate(null)
      setPreview(null)
    }, 'Состав утверждён для всех участников')
  }
  async function share() {
    if (
      !window.confirm(
        `Отправить ${official ? 'утверждённый состав' : 'вариант состава'} в чат для составов?\n${gameSummary(m)}\n\n${teamSummary(people.map((p) => ({ alias: p.alias, team: assignments[p.registration_id] ?? null })))}`,
      )
    )
      return
    const d = base()
    await run(
      () =>
        api(`/matches/${m.id}/lineup/share`, 'POST', {
          version: data!.version,
          roster_version: d.roster_version,
          fingerprint: d.fingerprint,
          assignments,
          official: official && Boolean(data!.official_players),
        }),
      'Состав поставлен в очередь отправки в чат',
    )
  }
  return (
    <div className="tactics-screen lineup-workspace">
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      <section className="panel lineup-variant-picker">
        <div className="lineup-variant-controls">
          <div>
            <label htmlFor="lineup-variant">Вариант состава</label>
            <select
              id="lineup-variant"
              value={choice}
              disabled={busy || working}
              onChange={(e) => void choose(e.target.value)}
            >
              <optgroup label="Основные">
                <option value="official" disabled={!data.official_players}>
                  ✓ Утверждённый состав
                </option>
                <option value="draft" disabled={!data.editable}>
                  Моя прикидка
                </option>
              </optgroup>
              <optgroup label="Автоподбор">
                <option value="community" disabled={!data.editable}>
                  По оценкам сообщества
                </option>
                <option value="game" disabled={!data.editable}>
                  По OpenSkill
                </option>
                <option
                  value="auction"
                  disabled={!data.editable || data.auction?.status !== 'completed'}
                >
                  По результатам аукциона
                </option>
              </optgroup>
              {proposals.proposals.length > 0 && (
                <optgroup label="Предложения игроков">
                  {proposals.proposals.map((p) => (
                    <option key={p.id} value={proposalChoice(p.id)}>
                      {p.author_id === me.id ? 'Моё предложение' : p.author} ·{' '}
                      {proposalDate(p.updated_at)}
                      {p.roster_stale ? ' · участники изменились' : ''}
                    </option>
                  ))}
                </optgroup>
              )}
              {missingProposal && <option value={choice}>Предложение отозвано</option>}
            </select>
            <p className="muted caption lineup-variant-status">
              {title}
              {proposal && ` · обновлено ${proposalDate(proposal.updated_at)} МСК`}
              {ownDraft && ' · видно только вам'}
            </p>
          </div>
          {data.editable && (
            <div className="lineup-proposal-buttons">
              <Button
                className="secondary compact"
                disabled={busy || working || missingProposal}
                onClick={() => (stale ? refreshDraft() : edit(base()))}
              >
                <Copy size={15} />
                Взять за основу
              </Button>
              <Button
                className="compact"
                disabled={disabled || !ownDraft || !complete || !proposals.editable}
                onClick={() => void propose()}
              >
                {mine ? 'Обновить предложение' : 'Предложить состав'}
              </Button>
            </div>
          )}
        </div>
        {preview && ['community', 'game'].includes(choice) && (
          <div className="tactics-variants" role="group" aria-label="Варианты составов">
            <span className="muted caption">Вариант</span>
            {preview.result.variants.map((_, i) => (
              <button
                key={i}
                aria-label={`Показать вариант ${i + 1}`}
                aria-pressed={candidate?.variant === i}
                disabled={disabled}
                onClick={() => loadVariant(preview, i)}
              >
                {i + 1}
              </button>
            ))}
          </div>
        )}
        {data.editable && (
          <p className="muted caption lineup-proposal-note">
            {proposals.editable
              ? 'Перенос игрока создаёт личную прикидку. Нажмите «Предложить состав», чтобы её увидело сообщество.'
              : 'Приём и изменение предложений закрыты: игра уже началась.'}
          </p>
        )}
      </section>
      {stale && (
        <div role="alert" className="alert">
          {missingProposal
            ? 'Автор отозвал предложение. Выберите другой вариант.'
            : proposal?.roster_stale
              ? 'Участники изменились. Этот вариант можно посмотреть и обновить в своей прикидке.'
              : 'Список, оценки или утверждённый состав изменились.'}{' '}
          {!missingProposal && data.editable && (
            <button disabled={busy || working} onClick={refreshDraft}>
              Обновить прикидку
            </button>
          )}
        </div>
      )}
      <section hidden={view !== 'teams'} aria-label="Подбор команд">
        <LineupTeams
          people={people}
          assignments={assignments}
          disabled={disabled}
          onChange={setTeam}
          color={color}
        />
        {data.editable && !complete && (
          <p className="alert muted caption" role="status">
            Распределите всех участников. Численность команд должна отличаться не более чем на
            одного, в каждой — не более одного вратаря.
          </p>
        )}
        <LineupRatings
          key={m.id}
          matchId={m.id}
          version={data.version}
          people={people}
          assignments={assignments}
          showGameRating={choice === 'game'}
        />
        {data.editable && (
          <div className="tactics-footer">
            <p className="muted caption">
              {ownDraft
                ? 'Личная прикидка сохранена в этом браузере.'
                : proposal
                  ? 'Предложение не утверждает команды на игру.'
                  : 'Утверждённый состав меняет администратор.'}
            </p>
            {(me.is_admin || me.is_owner) && (
              <>
                <Button
                  disabled={
                    disabled ||
                    !complete ||
                    auctionRunning ||
                    !['finalized', 'approved'].includes(m.status) ||
                    official
                  }
                  onClick={() => void confirm()}
                >
                  Утвердить состав
                </Button>
                {m.status === 'open' && (
                  <small className="muted">
                    Сначала зафиксируйте участников на вкладке «Игра».
                  </small>
                )}
                {auctionRunning && (
                  <small className="muted">Подтверждение доступно после завершения аукциона.</small>
                )}
              </>
            )}
          </div>
        )}
        <details className="panel tactics-details">
          <summary>Действия и подробности</summary>
          <p className="muted caption">
            Суммы атаки и защиты — только полевые, без вратарей. Σ — атака + защита. Знак ≥ означает
            неполные оценки. Индивидуальные оценки текущие; баллы утверждённого состава сохранены на
            игру. Публикация предложения и отправка в чат — отдельные действия.
          </p>
          <div className="inline wrap">
            <Button
              className="ghost compact"
              disabled={
                busy ||
                working ||
                stale ||
                !people.length ||
                !people.every((p) => assignments[p.registration_id]) ||
                !people.some((p) => assignments[p.registration_id] === 'white') ||
                !people.some((p) => assignments[p.registration_id] === 'black') ||
                !data.share_available
              }
              onClick={() => void share()}
            >
              <Share2 size={15} />
              Поделиться в чат
            </Button>
            {data.editable && (
              <>
                <Button
                  className="ghost compact"
                  disabled={busy || working}
                  onClick={() => {
                    edit({
                      version: data.version,
                      roster_version: data.roster_version,
                      fingerprint: data.fingerprint,
                      assignments: Object.fromEntries(
                        data.players.map((p) => [p.registration_id, null]),
                      ),
                      placements: {},
                      source: 'manual',
                      variant: 0,
                    })
                    setPreview(null)
                  }}
                >
                  <Eraser size={15} />
                  Очистить команды
                </Button>
                <Button
                  className="ghost compact"
                  disabled={disabled}
                  onClick={() => {
                    const d = base()
                    edit({
                      ...d,
                      assignments: Object.fromEntries(
                        Object.entries(assignments).map(([id, team]) => [
                          id,
                          team === 'white' ? 'black' : team === 'black' ? 'white' : null,
                        ]),
                      ),
                      placements: Object.fromEntries(
                        Object.entries(placements).map(([id, p]) => [
                          id,
                          { x: 1 - p.x, y: 1 - p.y },
                        ]),
                      ),
                    })
                  }}
                >
                  Поменять цвета команд
                </Button>
                {mine && proposals.editable && (
                  <Button
                    className="ghost compact"
                    disabled={busy || working}
                    onClick={() => void withdraw()}
                  >
                    Отозвать предложение
                  </Button>
                )}
              </>
            )}
            {data.auction && (
              <Button className="ghost compact" onClick={onAuction}>
                Открыть аукцион
              </Button>
            )}
          </div>
          {preview &&
            ['community', 'game'].includes(choice) &&
            preview.result.warnings.map((w) => (
              <p className="muted caption" key={w}>
                {w}
              </p>
            ))}
        </details>
      </section>
      <section hidden={view !== 'field'} aria-label="Расстановка на поле">
        <div
          className="tactics-pitch"
          ref={board}
          role="group"
          aria-label="Тактическая доска"
          onClick={(e) => {
            if (selected !== null && !disabled && !suppressClick.current) {
              const point = pointAt(e.clientX, e.clientY)
              if (point) place(selected, point)
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
                  className={`tactics-token lineup-colored-token ${assignments[p.registration_id]} ${selected === p.registration_id ? 'selected' : ''}`}
                  style={{ ...color(p), left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
                >
                  <button
                    type="button"
                    className="tactics-position"
                    aria-label={`На поле: ${p.alias}`}
                    aria-pressed={selected === p.registration_id}
                    {...handlers(p.registration_id)}
                    onClick={(e) => {
                      e.stopPropagation()
                      if (!disabled && !suppressClick.current)
                        setSelected(selected === p.registration_id ? null : p.registration_id)
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
                    <span className="lineup-token-score">
                      {p.position === 'keeper'
                        ? `З ${ratingNumber(p.defense)}`
                        : `Σ ${p.attack === null || p.defense === null ? '—' : ratingNumber(p.attack + p.defense)}`}
                    </span>
                  </button>
                  <PlayerName playerId={p.player_id} alias={p.alias} className="tactics-alias" />
                </div>
              )
            })}
          {!people.some((p) => assignments[p.registration_id]) && (
            <p className="tactics-empty">Сформируйте команды на вкладке «Команды»</p>
          )}
        </div>
        <p className="muted caption tactics-hint" role="status">
          {selected !== null
            ? `Куда поставить ${people.find((p) => p.registration_id === selected)?.alias}? Нажмите на поле.`
            : data.editable
              ? 'Перетащите значок или выберите игрока и нажмите на поле. Имя открывает профиль.'
              : 'Состав завершённой игры'}
        </p>
        <LineupTotals people={people} assignments={assignments} />
      </section>
      {ghost && (
        <div className="tactics-drag-ghost" style={{ left: ghost.x, top: ghost.y }}>
          {people.find((p) => p.registration_id === ghost.id)?.alias}
        </div>
      )}
    </div>
  )
}
