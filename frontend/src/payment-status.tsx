export function PaymentStatus({
  reported,
  confirmed,
  alias,
  disabled,
  onReported,
  onConfirmed,
}: {
  reported: boolean
  confirmed: boolean
  alias: string
  disabled?: boolean
  onReported?: () => void
  onConfirmed?: () => void
}) {
  const statuses = [
    {
      value: reported,
      label: reported ? 'Оплачен' : 'Не оплачен',
      title: 'Отметка игрока',
      action: onReported,
      accessible: `${reported ? 'Отменить отметку оплаты' : 'Отметить оплату'}: ${alias}`,
    },
    {
      value: confirmed,
      label: confirmed ? 'Подтверждено' : 'Не подтверждено',
      title: 'Подтверждение администратора',
      action: onConfirmed,
      accessible: `${confirmed ? 'Снять подтверждение' : 'Подтвердить оплату'}: ${alias}`,
    },
  ]
  return (
    <div className="payment-statuses" role="group" aria-label={`Оплата и подтверждение: ${alias}`}>
      {statuses.map((status) =>
        status.action ? (
          <button
            type="button"
            key={status.title}
            className={`payment-status ${status.value ? 'positive' : 'negative'}`}
            disabled={disabled}
            onClick={status.action}
            aria-label={status.accessible}
            aria-pressed={status.value}
            title={status.title}
          >
            <span className="payment-status-label">{status.label}</span>
          </button>
        ) : (
          <span
            key={status.title}
            className={`payment-status ${status.value ? 'positive' : 'negative'}`}
            title={status.title}
          >
            <span className="payment-status-label">{status.label}</span>
          </span>
        ),
      )}
    </div>
  )
}
