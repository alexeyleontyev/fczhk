export async function lineupShareImage(teams: HTMLElement | null): Promise<string> {
  const { default: html2canvas } = await import('html2canvas-pro')
  await document.fonts.ready
  if (!teams?.isConnected || !teams.clientWidth) {
    throw new Error('Откройте команды, чтобы сделать снимок состава.')
  }
  const canvas = await html2canvas(teams, {
    backgroundColor: getComputedStyle(teams).getPropertyValue('--paper').trim() || '#fff',
    scale: Math.min(2, 1400 / teams.clientWidth),
    scrollY: 0,
    logging: false,
    onclone(_document, copy) {
      for (const child of Array.from(copy.children)) {
        if (!child.matches('.lineup-sticky-totals, .lineup-team-tables')) child.remove()
      }
      const totals = copy.querySelector<HTMLElement>('.lineup-sticky-totals')
      if (totals) totals.style.position = 'static'
      for (const control of copy.querySelectorAll<HTMLElement>(
        '.lineup-drag-handle, .lineup-move-player, .lineup-exchange-player',
      )) {
        control.style.visibility = 'hidden'
      }
    },
  })
  const image = canvas.toDataURL('image/jpeg', 0.9).split(',')[1]
  if (!image) throw new Error('Не удалось сделать снимок состава. Попробуйте ещё раз.')
  return image
}
