import { useEffect, useRef, useState } from 'react'
import type { PointerEvent, CSSProperties } from 'react'
import { ArrowLeft, ArrowRight, GripVertical } from 'lucide-react'
import { PlayerName } from './player-name'
import { TeamDots } from './team-board'
import { ratingNumber } from './rating-mark'
import { communityStrength, fieldTotals, totalLabel } from './lineup-strength'
import type { Person, Assignments } from './lineup-types'
import type { Team } from './types'

export function LineupTotals({
  people,
  assignments,
}: {
  people: Person[]
  assignments: Assignments
}) {
  return (
    <div className="lineup-team-totals" aria-label="Суммарные баллы команд">
      {(['white', 'black'] as Team[]).map((team) => {
        const members = people.filter((p) => assignments[p.registration_id] === team)
        const totals = fieldTotals(members)
        return (
          <section key={team} className="lineup-total-team">
            <strong>
              <i className={`lineup-team-dot ${team}`} />
              {team === 'white' ? 'Белые' : 'Чёрные'}{' '}
              <small>
                {members.filter((p) => p.position === 'field').length} +{' '}
                {members.filter((p) => p.position === 'keeper').length}
              </small>
            </strong>
            <div>
              {(['attack', 'defense', 'total'] as const).map((kind, i) => (
                <span key={kind}>
                  <small>{['Атака', 'Защита', 'Σ Сумма'][i]}</small>
                  <b>{totalLabel(totals[kind])}</b>
                </span>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

export function LineupTeams({
  people,
  assignments,
  disabled,
  onChange,
  color,
  onExchange,
}: {
  people: Person[]
  assignments: Assignments
  disabled: boolean
  onChange: (id: number, team: Team | null) => void
  onExchange: (first: number, second: number) => void
  color: (p: Person) => CSSProperties
}) {
  const [exchanging, setExchanging] = useState(false)
  const [first, setFirst] = useState<number | null>(null)
  useEffect(() => {
    setFirst(null)
    setExchanging(false)
  }, [disabled, assignments])
  const [ghost, setGhost] = useState<{ id: number; x: number; y: number } | null>(null)
  const [target, setTarget] = useState<Team | null>(null)
  const drag = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null)
  const sorted = [...people].sort(
    (a, b) =>
      Number(a.position === 'keeper') - Number(b.position === 'keeper') ||
      (communityStrength(b) ?? -1) - (communityStrength(a) ?? -1) ||
      a.alias.localeCompare(b.alias, 'ru'),
  )
  const teamAt = (x: number, y: number) =>
    document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-lineup-team]')?.dataset
      .lineupTeam as Team | undefined
  function down(e: PointerEvent<HTMLButtonElement>, id: number) {
    if (disabled || e.button !== 0) return
    e.preventDefault()
    drag.current = { id, x: e.clientX, y: e.clientY, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  function move(e: PointerEvent<HTMLButtonElement>) {
    const d = drag.current
    if (!d) return
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5) d.moved = true
    if (d.moved) {
      setGhost({ id: d.id, x: e.clientX, y: e.clientY })
      setTarget(teamAt(e.clientX, e.clientY) ?? null)
    }
  }
  function up(e: PointerEvent<HTMLButtonElement>) {
    const d = drag.current,
      team = teamAt(e.clientX, e.clientY)
    drag.current = null
    setGhost(null)
    setTarget(null)
    if (d?.moved && team && !disabled) onChange(d.id, team)
  }
  const unassigned = sorted.filter((p) => !assignments[p.registration_id])
  return (
    <>
      <div className="lineup-table-intro">
        <button
          className="button secondary compact"
          disabled={disabled}
          aria-pressed={exchanging}
          onClick={() => {
            setExchanging(!exchanging)
            setFirst(null)
          }}
        >
          {exchanging ? 'Отменить обмен' : 'Обменять игроков'}
        </button>
        <span className="lineup-strength-key">
          Ниже <i /> Выше
        </span>
      </div>
      {exchanging && (
        <p className="lineup-exchange-hint" role="status">
          {first === null
            ? 'Выберите первого игрока.'
            : `${people.find((p) => p.registration_id === first)?.alias}: выберите игрока другой команды.`}
        </p>
      )}
      <div className="lineup-sticky-totals">
        <LineupTotals people={people} assignments={assignments} />
      </div>
      <div className="lineup-team-tables">
        {(['white', 'black'] as Team[]).map((team) => {
          const members = sorted.filter((p) => assignments[p.registration_id] === team)
          const total = fieldTotals(members)
          const other = team === 'white' ? 'black' : 'white'
          return (
            <section
              key={team}
              data-lineup-team={team}
              className={`lineup-team-table ${target === team ? 'drop-target' : ''}`}
              aria-label={team === 'white' ? 'Белая команда' : 'Чёрная команда'}
            >
              <div className="lineup-table-columns">
                <span>Игрок ↓ по силе</span>
                <span>А</span>
                <span>З</span>
                <span>Σ</span>
                <span />
              </div>
              <div className="lineup-team-rows">
                {members.length === 0 && (
                  <p className="lineup-no-players">
                    {disabled ? 'Нет игроков' : 'Перенесите игроков сюда'}
                  </p>
                )}
                {members.map((p, i) => (
                  <div key={p.registration_id}>
                    {p.position === 'keeper' && members[i - 1]?.position !== 'keeper' && (
                      <div className="lineup-keeper-divider">Вратари</div>
                    )}
                    <div
                      className={`lineup-player-row ${p.position === 'keeper' ? 'keeper' : ''} ${ghost?.id === p.registration_id ? 'drag-origin' : ''} ${first === p.registration_id ? 'exchange-selected' : ''}`}
                      style={color(p)}
                    >
                      {exchanging && (
                        <button
                          className="lineup-exchange-player"
                          aria-label={`Выбрать для обмена: ${p.alias}`}
                          aria-pressed={first === p.registration_id}
                          disabled={
                            first !== null &&
                            first !== p.registration_id &&
                            assignments[first] === team
                          }
                          onClick={() => {
                            if (first === p.registration_id) setFirst(null)
                            else if (first === null) setFirst(p.registration_id)
                            else {
                              onExchange(first, p.registration_id)
                              setFirst(null)
                              setExchanging(false)
                            }
                          }}
                        />
                      )}
                      <div className="lineup-player-cell" data-name={p.alias} inert={exchanging}>
                        <button
                          className="lineup-drag-handle"
                          disabled={disabled}
                          aria-label={`Перетащить: ${p.alias}`}
                          onPointerDown={(e) => down(e, p.registration_id)}
                          onPointerMove={move}
                          onPointerUp={up}
                          onPointerCancel={() => {
                            drag.current = null
                            setGhost(null)
                            setTarget(null)
                          }}
                          onKeyDown={(e) => {
                            if (
                              (e.key === 'ArrowRight' && team === 'white') ||
                              (e.key === 'ArrowLeft' && team === 'black')
                            ) {
                              e.preventDefault()
                              onChange(p.registration_id, other)
                            }
                          }}
                        >
                          <GripVertical size={14} />
                        </button>
                        <PlayerName playerId={p.player_id} alias={p.alias} />
                      </div>
                      <span className="lineup-score-cell">
                        <small>А</small>
                        {ratingNumber(p.attack)}
                      </span>
                      <span className="lineup-score-cell">
                        <small>З</small>
                        {ratingNumber(p.defense)}
                      </span>
                      <span className="lineup-score-cell total">
                        <small>Σ</small>
                        {p.position === 'keeper' || p.attack === null || p.defense === null
                          ? '—'
                          : ratingNumber(p.attack + p.defense)}
                      </span>
                      <button
                        className="lineup-move-player"
                        disabled={disabled || exchanging}
                        aria-label={`${p.alias}: перевести ${other === 'white' ? 'в белые' : 'в чёрные'}`}
                        onClick={() => onChange(p.registration_id, other)}
                      >
                        {other === 'black' ? <ArrowRight size={15} /> : <ArrowLeft size={15} />}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <footer>
                <span>Суммы полевых</span>
                <span>А {totalLabel(total.attack)}</span>
                <span>З {totalLabel(total.defense)}</span>
                <b>Σ {totalLabel(total.total)}</b>
              </footer>
            </section>
          )
        })}
      </div>
      {unassigned.length > 0 && (
        <section className="panel lineup-unassigned" aria-label="Игроки без команды">
          <h3>Без команды · {unassigned.length}</h3>
          {unassigned.map((p) => (
            <div key={p.registration_id} className="lineup-unassigned-row" style={color(p)}>
              <PlayerName playerId={p.player_id} alias={p.alias} />
              <small>
                {p.position === 'keeper'
                  ? `ВР · З ${ratingNumber(p.defense)}`
                  : `А ${ratingNumber(p.attack)} · З ${ratingNumber(p.defense)}`}
              </small>
              <TeamDots
                alias={p.alias}
                team={null}
                disabled={disabled}
                onChange={(team) => onChange(p.registration_id, team)}
              />
            </div>
          ))}
        </section>
      )}
      <details className="lineup-color-note compact-explanation">
        <summary>Перенос игроков и цвета</summary>
        <p className="muted caption">
          Перетаскивайте за значок или нажимайте стрелку. Полевые отсортированы по силе, вратари —
          внизу. Заливка — по общим оценкам сообщества внутри этого сбора: полевые — атака + защита,
          вратари — защита по шкале 0–5. Нет оценки — серый цвет. Баллы выбранного варианта
          сохраняют его источник оценок.
        </p>
      </details>
      {ghost && (
        <div className="tactics-drag-ghost" style={{ left: ghost.x, top: ghost.y }}>
          {people.find((p) => p.registration_id === ghost.id)?.alias}
        </div>
      )}
    </>
  )
}
