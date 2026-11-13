// Paleta NOC oscura compartida por App.js y la topología.
export const C = {
  bg: '#0B1220',
  bgSoft: '#0F172A',
  card: '#111C2E',
  card2: '#16233A',
  line: '#1E293B',
  lineSoft: '#243449',
  ink: '#E2E8F0',
  inkStrong: '#F8FAFC',
  muted: '#94A3B8',
  accent: '#00E5FF',
  accent2: '#3B82F6',
  ok: '#10B981',
  warn: '#F59E0B',
  off: '#EF4444'
}

export function estadoColor(estado) {
  const e = String(estado || '').toUpperCase()
  if (e === 'OK') return C.ok
  if (e === 'WARNING') return C.warn
  return C.off
}

export function estadoBadge(estado) {
  const e = String(estado || '').toUpperCase()
  if (e === 'OK') return 'ok'
  if (e === 'WARNING') return 'warn'
  return 'off'
}
