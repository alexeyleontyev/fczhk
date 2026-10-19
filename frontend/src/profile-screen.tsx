import { useState } from 'react'
import { SectionTabs } from './section-tabs'
import { api } from './api'
import type { SeasonFilter } from './seasons'
import { RatingAverages } from './ratings'
import { PlayerStats } from './results'
import { initial } from './format'
import { Button } from './ui'
import { ProfileLink } from './profile-link'
import type { Player, Run } from './types'

export function ProfileScreen({
  me,
  busy,
  run,
  openGame,
  openStats,
  logout,
  players,
  ...seasonFilter
}: SeasonFilter & {
  me: Player
  busy: boolean
  run: Run
  openGame: (id: number) => void
  openStats: (id: number) => void
  logout: () => Promise<void>
  players: Player[]
}) {
  const [section, setSection] = useState('stats')
  const isAdmin = Boolean(me.is_admin)
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</div>
        <h1>Мой профиль</h1>
      </div>
      <section className="panel profile-panel">
        <span className="avatar large">{initial(me.alias)}</span>
        <h2>{me.alias}</h2>
        <span className="tag">
          {me.is_owner ? 'Владелец' : isAdmin ? 'Администратор' : 'Игрок клуба'}
        </span>
        <SectionTabs
          label="Разделы профиля"
          value={section}
          onChange={setSection}
          options={[
            { value: 'stats', label: 'Статистика' },
            { value: 'ratings', label: 'Оценки' },
            { value: 'settings', label: 'Настройки' },
          ]}
        >
          {section === 'ratings' && <RatingAverages player={me} />}
          <div hidden={section !== 'stats'}>
            <PlayerStats
              playerId={me.id}
              onMatch={openGame}
              onPlayer={openStats}
              {...seasonFilter}
            />
          </div>
          <div hidden={section !== 'settings'}>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                const alias = new FormData(e.currentTarget).get('alias')
                void run(() => api('/me', 'PATCH', { alias }), 'Имя обновлено')
              }}
            >
              <label>
                Игровой alias
                <input
                  key={me.alias}
                  name="alias"
                  defaultValue={me.alias}
                  required
                  minLength={2}
                  maxLength={60}
                />
              </label>
              <Button type="submit" disabled={busy}>
                Сохранить имя
              </Button>
            </form>
            <p className="muted caption">
              Ваше имя в заявках и составах. Профиль привязан к аккаунту Telegram.
            </p>
            <ProfileLink players={players} />
          </div>
        </SectionTabs>
        <Button className="secondary" onClick={() => void run(logout)} disabled={busy}>
          Выйти из аккаунта
        </Button>
      </section>
    </>
  )
}
