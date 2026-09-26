export function percentTone(value: number): string {
  return value > 50 ? 'percent-high' : value < 50 ? 'percent-low' : 'percent-even'
}
