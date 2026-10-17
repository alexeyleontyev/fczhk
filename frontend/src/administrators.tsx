import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'

type Member = {
  id: number
  alias: string
  telegram_id: number
  role: 'owner' | 'admin' | 'player'
  revision: number
}

export function AdministratorsPanel({ onChanged }: { onChanged: () => Promise<void> }) {
  const [members, setMembers] = useState<Member[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    void api<Member[]>('/administrators')
      .then((value) => {
        if (active) {
          setMembers(value)
        }
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [revision])

  async function change(member: Member, isAdmin: boolean) {
    if (
      !isAdmin &&
      !window.confirm(`Снять права администратора у «${member.alias}»? Он останется игроком.`)
    )
      return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const updated = await api<Member>(`/administrators/${member.id}`, 'PUT', {
        is_admin: isAdmin,
        revision: member.revision,
      })
      setMembers((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setSelected('')
      setNotice(
        isAdmin ? `«${member.alias}» назначен администратором.` : `Права «${member.alias}» сняты.`,
      )
      await onChanged()
    } catch (e) {
      setError((e as Error).message)
      setRevision((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  const candidate = members.find(
    (member) => String(member.id) === selected && member.role === 'player',
  )
  const candidates = members.filter((member) => member.role === 'player')

  return (
    <section className="panel form-panel" aria-label="Администраторы">
      <h2>Администраторы</h2>
      <p>
        Только владелец назначает и снимает администраторов. Администраторы управляют играми,
        составами, результатами и оплатами. Права владельца сохраняются всегда.
      </p>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="alert success" role="status">
          {notice}
        </p>
      )}
      {loading ? (
        <p>Загружаем список…</p>
      ) : (
        <>
          {members
            .filter((member) => member.role !== 'player')
            .map((member) => (
              <div className="publication" key={member.id}>
                <strong>{member.alias}</strong>
                <span>
                  {member.role === 'owner' ? 'Владелец' : 'Администратор'} · Telegram ID{' '}
                  {member.telegram_id}
                </span>
                {member.role === 'admin' && (
                  <Button
                    disabled={busy}
                    className="ghost"
                    onClick={() => void change(member, false)}
                  >
                    Снять права
                  </Button>
                )}
              </div>
            ))}
          <label>
            Новый администратор
            <select value={selected} disabled={busy} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Выберите игрока</option>
              {candidates.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.alias}
                </option>
              ))}
            </select>
          </label>
          <small>В списке появляются игроки, которые уже вошли в приложение через Telegram.</small>
          <Button
            disabled={busy || !candidate}
            onClick={() => candidate && void change(candidate, true)}
          >
            Назначить администратором
          </Button>
        </>
      )}
      <Button
        className="secondary"
        disabled={busy || loading}
        onClick={() => {
          setError('')
          setRevision((value) => value + 1)
        }}
      >
        Обновить список
      </Button>
    </section>
  )
}
