import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Leaderboards } from './leaderboards'
import { GameRatingLeaderboard } from './ratings'
import { Button } from './ui'
import { SectionTabs } from './section-tabs'
import { filterPlayerNames } from './player-list-filters'
import { SeasonSelect, type SeasonFilter } from './seasons'
import type { Player, Position } from './types'
import { CatalogTable } from './catalog-table'
import { useLastCompleted } from './use-last-completed'

export function PlayersScreen({
  players,
  me,
  dataRevision,
  refresh,
  openStats,
  setModal,
  ...seasonFilter
}: SeasonFilter & {
  players: Player[]
  me: Player
  dataRevision: number
  refresh: () => Promise<void>
  openStats: (id: number) => void
  setModal: (value: string | null) => void
}) {
  const isAdmin = Boolean(me.is_admin)
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('catalog')
  const [source, setSource] = useState('community')
  const [ratedOnly, setRatedOnly] = useState(false)
  const [previousOnly, setPreviousOnly] = useState(false)
  const [position, setPosition] = useState<Position>('field')
  const previous = useLastCompleted(dataRevision)
  const visiblePlayers = filterPlayerNames(players, search).filter(
    (p) =>
      (!ratedOnly || p.ratings?.field.defense != null || p.ratings?.keeper.defense != null) &&
      (!previousOnly || Boolean(previous.match?.participant_ids.includes(p.id))),
  )
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
          <>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={ratedOnly}
                onChange={(event) => setRatedOnly(event.target.checked)}
              />
              Только игроки с оценками
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={previousOnly}
                onChange={(event) => setPreviousOnly(event.target.checked)}
              />
              Только участники предыдущей игры
            </label>
            {previousOnly && (previous.error || !previous.match) && (
              <p className="muted caption" role="status">
                {previous.loading
                  ? 'Загрузка последней игры…'
                  : previous.error || (!previous.match ? 'Завершённых игр пока нет.' : '')}
              </p>
            )}
            <SectionTabs
              label="Амплуа для оценки"
              value={position}
              onChange={(value) => setPosition(value as Position)}
              options={[
                { value: 'field', label: 'Полевые' },
                { value: 'keeper', label: 'Вратари' },
              ]}
            >
              <CatalogTable
                players={visiblePlayers}
                me={me}
                position={position}
                refresh={refresh}
                setModal={setModal}
              />
            </SectionTabs>
          </>
        )}
      </SectionTabs>
    </>
  )
}
