import { useEffect, useRef, type ReactNode } from 'react'
import { X, CalendarDays } from 'lucide-react'

export function Button({
  children,
  onClick,
  className = '',
  disabled,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  className?: string
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  return (
    <button type={type} className={`button ${className}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

export function Modal({
  title,
  children,
  close,
}: {
  title: string
  children: ReactNode
  close: () => void
}) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLElement>('input, select, button')?.focus()
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key !== 'Tab') return
      const elements = Array.from(
        ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
        ) || [],
      )
      const first = elements[0],
        last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener('keydown', keys)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', keys)
      previous?.focus()
    }
  }, [title])
  return (
    <div className="scrim" onClick={close}>
      <section
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-title">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="Закрыть" onClick={close}>
            <X />
          </button>
        </div>
        {children}
      </section>
    </div>
  )
}

export function Empty({ title, text }: { title: string; text: string }) {
  return (
    <section className="panel empty">
      <CalendarDays size={36} />
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  )
}
