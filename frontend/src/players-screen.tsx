import { useState } from 'react'
import { Plus, ArrowUpRight } from 'lucide-react'
import { Leaderboards } from './leaderboards'
import { GameRatingLeaderboard, RatingAverages } from './ratings'
import { Button } from './ui'
import { SectionTabs } from './section-tabs'
import { filterPlayerNames } from './player-list-filters'
import { RatingMark, ratingNumber } from './rating-mark'
import { SeasonSelect, type SeasonFilter } from './seasons'
import type { Player } from './types'

export function PlayersScreen({
  players,
  me,
  dataRevision,
  openStats,
  openRatings,
  setModal,
  ...seasonFilter
}: SeasonFilter & {
  players: Player[]
  me: Player
  dataRevision: number
  openStats: (id: number) => void
  openRatings: (id: number | null) => void
  setModal: (value: string | null) => void
}) {
  const isAdmin = Boolean(me.is_admin)
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('catalog')
  const [source, setSource] = useState('community')
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">СВОИ НА ПОЛЕ</div>
          <h1>
            Игроки <span className="muted">{players.length}</span>
          </h1>
        </div>
        <div className="inline wrap">
          <Button onClick={() => openRatings(null)}>Оценить игроков</Button>
          {isAdmin && (
            <Button onClick={() => setModal('guest')}>
              <Plus size={17} /> Гость
            </Button>
          )}
        </div>
      </div>
      <SectionTabs
        label="Разделы игроков"
        value={section}
        onChange={setSection}
        options={[
          { value: 'catalog', label: 'Каталог' },
          { value: 'results', label: 'Зачёты' },
          { value: 'ratings', label: 'Рейтинги' },
        ]}
      >
        {section !== 'ratings' && <SeasonSelect {...seasonFilter} />}
        <input
          className="search"
          type="search"
          placeholder="Найти игрока"
          aria-label="Поиск игроков"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {section === 'results' && (
          <Leaderboards
            mode="results"
            name={search}
            onPlayer={openStats}
            revision={dataRevision}
            season={seasonFilter.season}
          />
        )}
        {section === 'ratings' && (
          <SectionTabs
            label="Источник рейтинга"
            value={source}
            onChange={setSource}
            options={[
              { value: 'community', label: 'Сообщество' },
              { value: 'openskill', label: 'OpenSkill' },
            ]}
          >
            {source === 'community' ? (
              <Leaderboards
                mode="community"
                name={search}
                onPlayer={openStats}
                revision={dataRevision}
                season={seasonFilter.season}
              />
            ) : (
              <GameRatingLeaderboard name={search} onPlayer={openStats} revision={dataRevision} />
            )}
          </SectionTabs>
        )}
        {section === 'catalog' && (
          <div className="panel compact-catalog">
            <div className="catalog-head">
              <span>Игрок</span>
              <span>
                <RatingMark kind="attack" />
              </span>
              <span>
                <RatingMark kind="defense" />
              </span>
              <span>Σ</span>
            </div>
            {filterPlayerNames(players, search).map((p) => (
              <details className="player-card catalog-person" key={p.id} name="catalog-player">
                <summary>
                  <h3>
                    <span className="catalog-chevron" aria-hidden="true">
                      ›
                    </span>
                    {p.alias}
                  </h3>
                  <span>{ratingNumber(p.ratings?.field.attack ?? null)}</span>
                  <span>{ratingNumber(p.ratings?.field.defense ?? null)}</span>
                  <strong>
                    {p.ratings?.field.attack == null || p.ratings?.field.defense == null
                      ? '—'
                      : ratingNumber(p.ratings.field.attack + p.ratings.field.defense)}
                  </strong>
                </summary>
                <div className="catalog-details">
                  {p.shared_keeper ? (
                    <span className="muted caption">
                      Для игр с неизвестным или сменным вратарём.
                    </span>
                  ) : (
                    <>
                      <span className="muted caption">{p.guest ? 'Гость' : 'Игрок клуба'}</span>
                      <RatingAverages player={p} />
                      <div className="inline wrap">
                        <button
                          className="button secondary compact"
                          onClick={() => openStats(p.id)}
                        >
                          Статистика
                        </button>
                        {(p.id !== me.id || isAdmin) && (
                          <button
                            className="button ghost compact"
                            aria-label={`Оценки: ${p.alias}`}
                            onClick={() => openRatings(p.id)}
                          >
                            {p.id === me.id ? 'Посмотреть оценки' : 'Оценить'}
                          </button>
                        )}
                        {isAdmin && p.guest && (
                          <button
                            className="button ghost compact"
                            aria-label={`Связать гостя ${p.alias}`}
                            onClick={() => setModal(`link:${p.id}`)}
                          >
                            <ArrowUpRight size={16} /> Связать с аккаунтом
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </details>
            ))}
            {!filterPlayerNames(players, search).length && (
              <p className="empty-small muted">Игроки не найдены.</p>
            )}
          </div>
        )}
      </SectionTabs>
    </>
  )
}
