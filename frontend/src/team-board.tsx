import { api } from './api'
import { Button } from './ui'
import { TeamMeans, score } from './ratings'
import type { Match, Team, Entry, Run } from './types'

export function TeamBoard({
  match: m,
  admin,
  busy,
  run,
}: {
  match: Match
  admin: boolean
  busy: boolean
  run: Run
}) {
  const regs = m.registrations.filter((r) => r.selected)
  const move = (r: Entry, team: Team | null) =>
    run(() =>
      api(`/matches/${m.id}/teams`, 'PUT', {
        version: m.version,
        assignments: Object.fromEntries(regs.map((x) => [x.id, x.id === r.id ? team : x.team])),
      }),
    )
  return (
    <section className="panel">
      <div className="section-title">
        <h2>Составы команд</h2>
        <span className="tag">
          {m.status === 'approved'
            ? 'Утверждены'
            : m.team_ratings.method.startsWith('auto-game')
              ? 'OpenSkill · черновик'
              : m.team_ratings.method.startsWith('auto')
                ? 'Автоподбор · черновик'
                : m.team_ratings.method.startsWith('auction')
                  ? 'Аукцион'
                  : 'Ручное распределение'}
        </span>
      </div>
      {m.team_ratings.game_summary ? (
        <p className="muted caption">
          OpenSkill · сумма μ полевых: белые {score(m.team_ratings.game_summary.white_total)} ·
          чёрные {score(m.team_ratings.game_summary.black_total)} · нормированная Δ силы{' '}
          {score(m.team_ratings.game_summary.mu_gap)}.
          {m.team_ratings.frozen ? ' Зафиксировано при утверждении.' : ' Экспериментальный расчёт.'}
        </p>
      ) : (
        <>
          <TeamMeans summary={m.team_ratings.summary} />
          <p className="muted caption">
            Расчетные средние только полевых, после уменьшения меньшего рейтинга.{' '}
            {m.team_ratings.frozen
              ? 'Зафиксированы при утверждении.'
              : 'Исходные оценки игроков не изменяются.'}
          </p>
        </>
      )}
      {m.team_ratings.stale && (
        <p className="alert error" role="alert">
          Рейтинги изменились. Для утверждения пересчитайте варианты или начните вручную с нуля.
        </p>
      )}
      {admin && (
        <p className="muted caption">
          Выберите команду каждому игроку. Изменения сохраняются сразу. Для утверждения численность
          полевых должна отличаться не более чем на одного.
        </p>
      )}
      {admin &&
        Date.now() < new Date(m.starts_at).getTime() &&
        regs.some((r) => r.team === 'white') &&
        regs.some((r) => r.team === 'black') && (
          <Button
            className="secondary compact"
            disabled={busy}
            onClick={() =>
              void run(
                () => api(`/matches/${m.id}/teams/swap-colors`, 'POST', { version: m.version }),
                'Цвета команд поменяны. Если составы уже публиковались, опубликуйте их снова.',
              )
            }
          >
            Поменять цвета команд
          </Button>
        )}
      <div className="team-grid">
        {(['white', 'black', null] as (Team | null)[]).map((team) => {
          const list = regs.filter((r) => r.team === team)
          if (!list.length && team === null) return null
          return (
            <div className={`team ${team || 'unassigned'}`} key={team || 'none'}>
              <h3>
                <span className="team-dot" />
                {team === 'white' ? 'Белые' : team === 'black' ? 'Черные' : 'Не распределены'}
                <span>{list.length}</span>
              </h3>
              {list.map((r) => (
                <div className="team-player" key={r.id}>
                  <span>
                    {r.position === 'keeper' ? '🧤 ' : ''}
                    {r.alias}
                  </span>
                  {admin && (
                    <select
                      aria-label={`Команда: ${r.alias}`}
                      value={r.team || ''}
                      disabled={busy}
                      onChange={(e) => void move(r, (e.target.value || null) as Team | null)}
                    >
                      <option value="">—</option>
                      <option value="white">Белые</option>
                      <option value="black">Черные</option>
                    </select>
                  )}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}
