import { useEffect, useState } from 'react'
import { api } from './api'
import { seasonQuery } from './seasons'
import { DEFAULT_MIN_GAMES, filterPlayers, PlayerListFilters } from './player-list-filters'
import type {
  Average,
  BalanceRun,
  BalanceSummary,
  Entry,
  Match,
  Player,
  Position,
  Run,
} from './types'

export const score = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })

type GameRatingBoard = {
  model: string
  margin: number
  matches: number
  provisional: boolean
  players: {
    player_id: number
    alias: string
    mu: number
    sigma: number
    ordinal: number
    rating: number
    games: number
  }[]
}

export function GameRatingLeaderboard({
  onPlayer,
  season,
  revision,
}: {
  onPlayer: (id: number) => void
  season: string
  revision: number
}) {
  const [board, setBoard] = useState<GameRatingBoard | null>(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [playerName, setPlayerName] = useState('')
  const [minimumGames, setMinimumGames] = useState(DEFAULT_MIN_GAMES)
  useEffect(() => {
    let active = true
    setBoard(null)
    setError('')
    void api<GameRatingBoard>(`/game-ratings${seasonQuery(season)}`)
      .then((data) => {
        if (active) setBoard(data)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [season, revision])
  const qualifiedPlayers = filterPlayers(board?.players ?? [], '', minimumGames)
  const players = filterPlayers(qualifiedPlayers, playerName, '0')
  return (
    <section className="panel game-rating-board">
      <div className="section-title">
        <div>
          <div className="eyebrow">ПО ИСТОРИИ МАТЧЕЙ</div>
          <h2>{season ? `OpenSkill · сезон ${season}` : 'Общий рейтинг OpenSkill'}</h2>
        </div>
        <span className="tag">Эксперимент</span>
      </div>
      <p className="muted caption">
        {board ? `${board.matches} игр` : 'Загрузка…'} · Только полевые игроки · Победа, поражение и
        ничья. Разница мячей пока не влияет на рейтинг. Порядок учитывает неопределённость оценки;
        для надёжного подбора пока мало игр, поэтому этот способ помечен как эксперимент.
      </p>
      <p className="muted caption">
        Шкала начинается с 1500: рейтинг = 1500 + 10 × (μ − 3σ). μ — оценка силы, σ —
        неопределённость.
      </p>
      <PlayerListFilters
        name={playerName}
        setName={setPlayerName}
        minimumGames={minimumGames}
        setMinimumGames={setMinimumGames}
        scope="Фильтры OpenSkill"
      />
      {error && <p className="alert error">{error}</p>}
      {board?.players.length === 0 && <p>Истории завершённых матчей пока нет.</p>}
      {board && board.players.length > 0 && !players.length && (
        <p>По выбранным фильтрам игроки не найдены.</p>
      )}
      {players.length > 0 && (
        <>
          <div className="game-rating-list">
            {(expanded ? players : players.slice(0, 10)).map((player) => (
              <div className="game-rating-row" key={player.player_id}>
                <span className="muted">
                  {qualifiedPlayers.findIndex(
                    (candidate) => candidate.player_id === player.player_id,
                  ) + 1}
                </span>
                <button className="button ghost compact" onClick={() => onPlayer(player.player_id)}>
                  {player.alias}
                </button>
                <span>{player.games} игр</span>
                <span title={`μ ${score(player.mu)} · σ ${score(player.sigma)}`}>
                  {player.rating.toLocaleString('ru-RU')} · μ {score(player.mu)} · σ{' '}
                  {score(player.sigma)}
                </span>
              </div>
            ))}
          </div>
          {players.length > 10 && (
            <button className="button ghost compact" onClick={() => setExpanded(!expanded)}>
              {expanded ? 'Свернуть' : `Показать всех (${players.length})`}
            </button>
          )}
        </>
      )}
    </section>
  )
}

export function RatingAverages({ player }: { player: Player }) {
  return (
    <div className="rating-averages" aria-label={`Средние оценки: ${player.alias}`}>
      <span>
        Полевой: <b>А {score(player.ratings?.field.attack)}</b> ·{' '}
        <b>З {score(player.ratings?.field.defense)}</b>
      </span>
      <span>
        Вратарь: <b>З {score(player.ratings?.keeper.defense)}</b>
      </span>
      {player.ratings?.field.count !== undefined && (
        <small>
          Оценивших: полевой {player.ratings.field.count}, вратарь {player.ratings.keeper.count}
        </small>
      )}
    </div>
  )
}

function ScoreInputs({
  position,
  attack,
  defense,
  setAttack,
  setDefense,
  disabled = false,
}: {
  position: Position
  attack: string
  defense: string
  setAttack: (v: string) => void
  setDefense: (v: string) => void
  disabled?: boolean
}) {
  return (
    <div className="rating-inputs">
      {position === 'field' && (
        <label>
          Атака · 0–5
          <input
            aria-label="Оценка атаки"
            inputMode="decimal"
            type="text"
            required
            pattern="[0-5]([.,][0-9])?"
            value={attack}
            onChange={(e) => setAttack(e.target.value)}
            disabled={disabled}
            placeholder="Например, 4,5"
          />
        </label>
      )}
      <label>
        Защита · 0–5
        <input
          aria-label="Оценка защиты"
          inputMode="decimal"
          type="text"
          required
          pattern="[0-5]([.,][0-9])?"
          value={defense}
          onChange={(e) => setDefense(e.target.value)}
          disabled={disabled}
          placeholder="Например, 3,2"
        />
      </label>
    </div>
  )
}

type Review = Average & { revision: number; at: string; source?: 'sheet' }
type ReviewData = {
  own: Review | null
  imported_own?: Average
  averages: Average
  reviews?: (Review & { author: string; author_id: number; history: Review[] })[]
}

export function RatingFlow({
  me,
  players,
  target,
  run,
  busy,
}: {
  me: Player
  players: Player[]
  target: number | null
  run: Run
  busy: boolean
}) {
  const eligible = players.filter((p) => p.id !== me.id)
  const key = `fczhk-rating-progress:${me.id}`
  const [position, setPosition] = useState<Position>(() =>
    localStorage.getItem(`${key}:position`) === 'keeper' ? 'keeper' : 'field',
  )
  const [playerId, setPlayerId] = useState<number | null>(
    () => target ?? (Number(localStorage.getItem(key)) || eligible[0]?.id || null),
  )
  const [done, setDone] = useState(false)
  const [loaded, setData] = useState<ReviewData | null>(null)
  const [loadedKey, setLoadedKey] = useState('')
  const data = loadedKey === `${playerId}:${position}` ? loaded : null
  const [attack, setAttack] = useState('')
  const [defense, setDefense] = useState('')
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const person = players.find((p) => p.id === playerId)
  const index = eligible.findIndex((p) => p.id === playerId)
  useEffect(() => {
    let active = true
    setData(null)
    setAttack('')
    setDefense('')
    setError('')
    if (!person) return
    void api<ReviewData>(`/players/${person.id}/ratings/${position}`)
      .then((value) => {
        if (!active) return
        setData(value)
        setLoadedKey(`${playerId}:${position}`)
        setAttack(value.own?.attack == null ? '' : String(value.own.attack))
        setDefense(value.own?.defense == null ? '' : String(value.own.defense))
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [playerId, position, reload])
  const next = () => {
    const nextPerson = eligible[index + 1]
    if (!nextPerson) {
      setDone(true)
      localStorage.removeItem(key)
    } else {
      setPlayerId(nextPerson.id)
      localStorage.setItem(key, String(nextPerson.id))
    }
  }
  if (!eligible.length && !person) return <p>Пока нет других игроков в каталоге.</p>
  if (done)
    return (
      <div className="rating-finished">
        <h3>Список пройден</h3>
        <p>Пропущенные оценки не изменены. К любому игроку можно вернуться позже.</p>
        <button
          className="button"
          onClick={() => {
            setDone(false)
            setPlayerId(eligible[0]?.id ?? null)
          }}
        >
          Начать заново
        </button>
      </div>
    )
  return (
    <div className="rating-flow">
      <p className="muted caption">
        От 0 до 5 с шагом 0,1. Пустое значение — не ноль. Видны только средние и ваши оценки;
        администратор видит все.
      </p>
      <label>
        Оцениваемый игрок
        <select
          value={person?.id ?? ''}
          disabled={busy}
          onChange={(e) => setPlayerId(Number(e.target.value))}
        >
          {!person && <option value="">Выберите игрока</option>}
          {(me.is_admin ? players : eligible).map((p) => (
            <option key={p.id} value={p.id}>
              {p.alias}
            </option>
          ))}
        </select>
      </label>
      <div className="segments" aria-label="Амплуа для оценки">
        <button
          className={position === 'field' ? 'active' : ''}
          disabled={busy}
          onClick={() => {
            setPosition('field')
            localStorage.setItem(`${key}:position`, 'field')
          }}
        >
          Полевой
        </button>
        <button
          className={position === 'keeper' ? 'active' : ''}
          disabled={busy}
          onClick={() => {
            setPosition('keeper')
            localStorage.setItem(`${key}:position`, 'keeper')
          }}
        >
          Вратарь
        </button>
      </div>
      {person && (
        <>
          <div className="rating-subject">
            <div>
              <span className="eyebrow">
                {target ? 'КАРТОЧКА ИГРОКА' : `${Math.max(0, index) + 1} / ${eligible.length}`}
              </span>
              <h3>{person.alias}</h3>
            </div>
            <span className="tag">
              Средние: {position === 'field' ? `А ${score(data?.averages.attack)} · ` : ''}З{' '}
              {score(data?.averages.defense)}
            </span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button onClick={() => setReload((x) => x + 1)}>Обновить оценки</button>
            </div>
          )}
          {!data && !error && <p role="status">Загружаем оценки…</p>}
          {data && person.id !== me.id && (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void run(async () => {
                  const result = await api<ReviewData>(`/players/${person.id}/ratings`, 'PUT', {
                    position,
                    attack: position === 'field' ? attack : null,
                    defense,
                    revision: data.own?.revision ?? 0,
                  })
                  setData(result)
                  if (!target) next()
                }, 'Ваша оценка сохранена')
              }}
            >
              <ScoreInputs
                position={position}
                attack={attack}
                defense={defense}
                setAttack={setAttack}
                setDefense={setDefense}
                disabled={busy}
              />
              {data.own && (
                <p className="muted caption">
                  Ваша предыдущая оценка будет заменена, а не добавлена второй раз.
                </p>
              )}
              {!data.own && data.imported_own && (
                <p className="muted caption">
                  Ваша оценка из таблицы:{' '}
                  {position === 'field' ? `А ${score(data.imported_own.attack)} · ` : ''}З{' '}
                  {score(data.imported_own.defense)}. Новая оценка заменит её в общем зачёте.
                </p>
              )}
              {position === 'keeper' && (
                <p className="muted caption">
                  Защита вратаря — для информации, в подборе команд не участвует.
                </p>
              )}
              <div className="inline wrap">
                <button className="button" type="submit" disabled={busy}>
                  {target ? 'Сохранить оценку' : 'Сохранить и дальше'}
                </button>
                <button className="button secondary" type="button" disabled={busy} onClick={next}>
                  Пропустить
                </button>
                <button
                  className="button ghost compact"
                  type="button"
                  disabled={busy}
                  onClick={() => setReload((x) => x + 1)}
                >
                  Обновить
                </button>
              </div>
            </form>
          )}
          {person.id === me.id && <p>Вы можете посмотреть оценки, но не оценивать себя.</p>}
          {me.is_admin && data?.reviews && (
            <details className="rating-review-list">
              <summary>Все оценки и история · {data.reviews.length}</summary>
              {data.reviews.length === 0 && <p className="muted">Оценок пока нет.</p>}
              {data.reviews.map((review) => (
                <div className="rating-review" key={review.author_id}>
                  <strong>
                    {review.author}
                    {review.source === 'sheet' ? ' · из таблицы' : ''}
                  </strong>
                  <span>
                    {position === 'field' ? `А ${score(review.attack)} · ` : ''}З{' '}
                    {score(review.defense)}
                  </span>
                  {review.source !== 'sheet' && (
                    <details>
                      <summary>История изменений</summary>
                      {review.history.map((h) => (
                        <p className="muted caption" key={h.revision}>
                          #{h.revision} ·{' '}
                          {new Date(h.at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}{' '}
                          МСК · {position === 'field' ? `А ${score(h.attack)} · ` : ''}З{' '}
                          {score(h.defense)}
                        </p>
                      ))}
                    </details>
                  )}
                </div>
              ))}
            </details>
          )}
        </>
      )}
    </div>
  )
}

export function TemporaryRatings({
  match: m,
  run,
  busy,
}: {
  match: Match
  run: Run
  busy: boolean
}) {
  const [chosen, setChosen] = useState<number | null>(null)
  const r = m.registrations.find((r) => r.id === chosen)
  const eligible = m.registrations.filter((r) => r.rating.source !== 'community')
  return (
    <details className="temporary-ratings">
      <summary>
        Рейтинги на эту игру{eligible.length ? ` · ${eligible.length} без оценок сообщества` : ''}
      </summary>
      <p className="muted caption">
        Только для гостей и игроков без оценок сообщества. Не переходят на следующую игру.
        Появившиеся оценки сообщества имеют приоритет до утверждения.
      </p>
      {m.status === 'approved' && (
        <p className="muted">Рейтинги утвержденных составов зафиксированы.</p>
      )}
      {eligible.map((entry) => (
        <div className="temporary-rating-row" key={entry.id}>
          <span>
            {entry.alias}
            <small>
              {entry.position === 'field' ? `А ${score(entry.rating.attack)} · ` : 'Вратарь · '}З{' '}
              {score(entry.rating.defense)}
            </small>
          </span>
          <button
            className="button secondary compact"
            aria-label={`Рейтинг на игру: ${entry.alias}`}
            disabled={busy || m.status === 'approved'}
            onClick={() => setChosen(entry.id)}
          >
            Оценить
          </button>
        </div>
      ))}
      {r && m.status !== 'approved' && (
        <TemporaryForm
          key={`${m.id}:${r.id}:${r.rating.source}`}
          entry={r}
          busy={busy}
          close={() => setChosen(null)}
          save={(attack, defense) =>
            run(async () => {
              await api(`/matches/${m.id}/registrations/${r.id}/rating`, 'PUT', {
                version: m.version,
                position: r.position,
                attack: r.position === 'field' ? attack : null,
                defense,
              })
              setChosen(null)
            }, 'Рейтинг сохранен только для этой игры')
          }
        />
      )}
    </details>
  )
}

function TemporaryForm({
  entry,
  save,
  busy,
  close,
}: {
  entry: Entry
  save: (a: string, d: string) => Promise<void>
  busy: boolean
  close: () => void
}) {
  const [attack, setAttack] = useState(
    entry.rating.attack == null ? '' : String(entry.rating.attack),
  )
  const [defense, setDefense] = useState(
    entry.rating.defense == null ? '' : String(entry.rating.defense),
  )
  return (
    <form
      className="temporary-form"
      aria-label={`Временный рейтинг: ${entry.alias}`}
      onSubmit={(e) => {
        e.preventDefault()
        void save(attack, defense)
      }}
    >
      <h3>{entry.alias} · только эта игра</h3>
      <ScoreInputs
        position={entry.position}
        attack={attack}
        defense={defense}
        setAttack={setAttack}
        setDefense={setDefense}
        disabled={busy}
      />
      <div className="inline">
        <button className="button" type="submit" disabled={busy}>
          Сохранить на игру
        </button>
        <button className="button ghost" type="button" disabled={busy} onClick={close}>
          Отмена
        </button>
      </div>
    </form>
  )
}

export function TeamMeans({ summary }: { summary: BalanceSummary | null | undefined }) {
  if (!summary)
    return <p className="muted caption">Снимок рейтингов для этого состава отсутствует.</p>
  return (
    <div className="balance-summary">
      <div className="balance-means">
        {(['white', 'black'] as const).map((team) => (
          <div key={team}>
            <strong>
              {team === 'white' ? '⚪ Белые' : '⚫ Черные'} · {summary[team].count} полевых
            </strong>
            <span>
              Атака <b>{score(summary[team].attack)}</b> · Защита{' '}
              <b>{score(summary[team].defense)}</b>
            </span>
          </div>
        ))}
      </div>
      <p className="muted caption">
        Δ атаки {score(summary.attack_gap)} · Δ защиты {score(summary.defense_gap)} · Дисбаланс{' '}
        <b>{score(summary.cost)}</b>
        {summary.unassigned > 0 && ` · Не распределены: ${summary.unassigned}`}
      </p>
      {summary.cost === null && (
        <p className="muted caption">
          Средние появятся, когда обе команды непустые и у всех их полевых есть рейтинги. Пропуски
          не считаются нулями.
        </p>
      )}
    </div>
  )
}

export function AutomaticTeams({ match: m, run, busy }: { match: Match; run: Run; busy: boolean }) {
  const [runs, setRuns] = useState<BalanceRun[]>([])
  const [settings, setSettings] = useState<BalanceRun['settings'] | null>(null)
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  useEffect(() => {
    let active = true
    setError('')
    void Promise.all([
      api<BalanceRun[]>(`/matches/${m.id}/balance`),
      api<BalanceRun['settings']>('/balance/settings'),
    ])
      .then(([result, defaults]) => {
        if (active) {
          setRuns(result)
          setSettings((current) => current ?? defaults)
        }
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [m])
  const latest = runs[0]
  const missing = m.registrations.filter(
    (r) => r.selected && r.position === 'field' && r.rating.source === 'missing',
  )
  return (
    <section className="panel auto-teams">
      <div className="section-title">
        <div>
          <div className="eyebrow">БАЛАНС И РАЗНООБРАЗИЕ</div>
          <h2>Подобрать команды</h2>
        </div>
        <span className="tag">До 3 вариантов</span>
      </div>
      <p className="muted caption">
        {settings?.method === 'game'
          ? 'Экспериментальный OpenSkill сравнивает сумму ожидаемой силы полевых. Разница мячей пока не используется.'
          : 'Меньший рейтинг делим пополам; при равенстве уменьшаем защиту. Сравниваем средние полевых.'}{' '}
        Вратарей назначаете вручную.
      </p>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {settings?.method !== 'game' && missing.length > 0 && (
        <p className="alert" role="status">
          Сначала задайте рейтинги на игру: {missing.map((r) => r.alias).join(', ')}.
        </p>
      )}
      {settings && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              const result = await api<BalanceRun>(`/matches/${m.id}/balance`, 'POST', {
                version: m.version,
                settings,
              })
              setRuns((current) => [result, ...current.filter((r) => r.id !== result.id)])
            }, 'Варианты рассчитаны. Выбор еще не утвержден.')
          }}
        >
          <label>
            Способ подбора
            <select
              value={settings.method ?? 'community'}
              onChange={(e) =>
                setSettings({ ...settings, method: e.target.value as 'community' | 'game' })
              }
            >
              <option value="community">Оценки сообщества</option>
              <option value="game">OpenSkill · эксперимент</option>
            </select>
          </label>
          <details className="balance-settings">
            <summary>Настройки подбора</summary>
            <p className="muted caption">
              Стартовые значения предварительные. Допуск — прибавка к минимальному дисбалансу;
              автоматически расширяется только до указанного предела.
            </p>
            <div className="rating-inputs">
              <label>
                Начальный допуск
                <input
                  type="number"
                  min="0"
                  max="10"
                  step="0.01"
                  required
                  value={settings.epsilon}
                  onChange={(e) => setSettings({ ...settings, epsilon: e.target.value })}
                />
              </label>
              <label>
                Максимальный допуск
                <input
                  type="number"
                  min="0"
                  max="10"
                  step="0.01"
                  required
                  value={settings.max_epsilon}
                  onChange={(e) => setSettings({ ...settings, max_epsilon: e.target.value })}
                />
              </label>
              <label>
                Шаг расширения
                <input
                  type="number"
                  min="0.01"
                  max="10"
                  step="0.01"
                  required
                  value={settings.epsilon_step}
                  onChange={(e) => setSettings({ ...settings, epsilon_step: e.target.value })}
                />
              </label>
              <label>
                Минимум сменивших команду
                <input
                  type="number"
                  min="1"
                  max="8"
                  step="1"
                  placeholder="Авто: 6 для 16 полевых"
                  value={settings.min_distance ?? ''}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      min_distance: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
          </details>
          <button
            className="button"
            type="submit"
            disabled={busy || (settings.method !== 'game' && missing.length > 0)}
          >
            {busy ? 'Подождите…' : 'Рассчитать варианты'}
          </button>
        </form>
      )}
      {latest && (
        <div className="balance-results">
          <p className="muted caption">
            Расчет #{latest.id} · Перебрано {latest.result.partition_count} разбиений · В пределах
            допуска {latest.result.pool_count}
            <br />
            {latest.settings.method === 'game' ? 'Лучшая Δ силы' : 'Лучший дисбаланс'}{' '}
            {score(latest.result.minimum_cost)} · Использован допуск{' '}
            {score(latest.result.epsilon_used)} · Минимальное различие {latest.result.min_distance}
          </p>
          {(latest.stale || m.team_ratings.stale) && (
            <p className="alert error" role="alert">
              Список или рейтинги изменились. Рассчитайте варианты заново.
            </p>
          )}
          {latest.result.warnings.map((w) => (
            <p className="alert" key={w}>
              {w}
            </p>
          ))}
          {latest.result.variants.map((variant, i) => (
            <article
              className="balance-variant"
              aria-label={`Вариант ${i + 1}`}
              key={`${latest.id}:${i}`}
            >
              <div className="section-title">
                <h3>Вариант {i + 1}</h3>
                <span className="tag">
                  {variant.game_rating
                    ? `Δ силы ${score(variant.game_rating.mu_gap)}`
                    : `Дисбаланс ${score(variant.summary.cost)}`}
                </span>
              </div>
              {variant.game_rating ? (
                <p className="muted caption">
                  Сумма μ: белые {score(variant.game_rating.white_total)} · чёрные{' '}
                  {score(variant.game_rating.black_total)}
                </p>
              ) : (
                <TeamMeans summary={variant.summary} />
              )}
              <div className="variant-names">
                {(['white', 'black'] as const).map((team) => (
                  <div key={team}>
                    <h4>{team === 'white' ? 'Белые' : 'Черные'}</h4>
                    {latest.inputs
                      .filter((r) => variant.assignments[r.registration_id] === team)
                      .map((r) => {
                        const community = r.community ?? (r.source === 'community' ? r : null)
                        const temporary = r.temporary ?? (r.source === 'temporary' ? r : null)
                        return (
                          <div className="variant-player" key={r.registration_id}>
                            <span>{r.alias}</span>
                            <small>
                              {community
                                ? `Сообщество: А ${score(community.attack)} · З ${score(community.defense)}`
                                : 'Сообщество: нет оценок'}
                            </small>
                            <small>
                              {temporary
                                ? `На эту игру: А ${score(temporary.attack)} · З ${score(temporary.defense)}`
                                : 'На эту игру: оценка не задана'}
                            </small>
                          </div>
                        )
                      })}
                  </div>
                ))}
              </div>
              <p className="muted caption">
                {latest.result.distances[i]
                  .map((d, j) => (i === j ? null : `С вариантом ${j + 1}: ${d} сменивших команду`))
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              <button
                className="button secondary"
                disabled={busy || latest.stale}
                onClick={() =>
                  void run(
                    () =>
                      api(`/matches/${m.id}/balance/${latest.id}/apply`, 'POST', {
                        version: m.version,
                        variant: i,
                      }),
                    'Вариант перенесен в черновик. Назначьте вратарей и утвердите команды.',
                  )
                }
              >
                Выбрать вариант {i + 1}
              </button>
            </article>
          ))}
          <p className="muted caption">
            Смена цветов не считается отличием. Поиск разных вариантов эвристический, без гарантии
            глобального максимума разнообразия.
          </p>
          <details>
            <summary>Рейтинги, использованные в расчете</summary>
            {latest.inputs.map((r) => (
              <p className="caption" key={r.registration_id}>
                {r.alias}:{' '}
                {latest.settings.method === 'game'
                  ? `μ ${score(r.game_mu)} · σ ${score(r.game_sigma)} · ${r.game_count} игр`
                  : `А ${score(r.attack)} / З ${score(r.defense)} · ${r.source === 'temporary' ? 'на эту игру' : 'среднее сообщества'}`}
              </p>
            ))}
          </details>
          {runs.length > 1 && (
            <details>
              <summary>Предыдущие расчеты · {runs.length - 1}</summary>
              {runs.slice(1).map((r) => (
                <p className="caption" key={r.id}>
                  #{r.id} ·{' '}
                  {new Date(r.created_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}{' '}
                  МСК · {r.stale ? 'Устарел' : 'Сохранен'} · {r.result.variants.length} вариант(а),
                  допуск {score(r.result.epsilon_used)}
                </p>
              ))}
            </details>
          )}
        </div>
      )}
      <div className="manual-reset">
        <button className="button ghost" disabled={busy} onClick={() => setConfirmReset(true)}>
          Распределить вручную с нуля
        </button>
        {confirmReset && (
          <div className="alert">
            <p>Текущие назначения и утверждение будут сброшены. История сохранится.</p>
            <div className="inline wrap">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await api(`/matches/${m.id}/teams`, 'PUT', {
                      version: m.version,
                      reset: true,
                      assignments: Object.fromEntries(
                        m.registrations.filter((r) => r.selected).map((r) => [r.id, null]),
                      ),
                    })
                    setConfirmReset(false)
                  }, 'Ручной черновик очищен')
                }
              >
                Начать вручную
              </button>
              <button
                className="button ghost"
                disabled={busy}
                onClick={() => setConfirmReset(false)}
              >
                Не сбрасывать
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
