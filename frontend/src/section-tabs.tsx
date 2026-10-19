import { useId, type ReactNode } from 'react'

export function SectionTabs<T extends string>({
  label,
  value,
  options,
  onChange,
  children,
}: {
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
  children?: ReactNode
}) {
  const id = useId()
  const selected = options.find((o) => o.value === value) ?? options[0]
  return (
    <div className="section-workspace">
      <nav className="section-tabs" role="tablist" aria-label={label}>
        {options.map((o, i) => (
          <button
            key={o.value}
            type="button"
            role="tab"
            id={`${id}-${o.value}`}
            aria-controls={`${id}-panel`}
            aria-selected={selected.value === o.value}
            tabIndex={selected.value === o.value ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              const direction = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
              const next =
                e.key === 'Home'
                  ? 0
                  : e.key === 'End'
                    ? options.length - 1
                    : direction
                      ? (i + direction + options.length) % options.length
                      : null
              if (next === null) return
              e.preventDefault()
              onChange(options[next].value)
              e.currentTarget.parentElement
                ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
                [next]?.focus()
            }}
          >
            {o.label}
          </button>
        ))}
      </nav>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${selected.value}`}>
        {children}
      </div>
    </div>
  )
}
