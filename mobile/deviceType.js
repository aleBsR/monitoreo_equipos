// Tipo de dispositivo para la topología. NETMON/1.0 no envía el tipo, así que
// se infiere del ID y el usuario puede sobreescribirlo durante la sesión.
export const TIPOS = ['computer', 'server', 'printer', 'network']

export const ETIQUETAS = {
  auto: 'Automático (inferido)',
  computer: 'Computadora',
  server: 'Servidor',
  printer: 'Impresora',
  network: 'Dispositivo de red',
  unknown: 'Desconocido'
}

const REGLAS = [
  [/IMPR|PRINT|PRN|ESCAN|SCAN/i, 'printer'],
  [/SRV|SERVER|SERVIDOR/i, 'server'],
  [/ROUT|SWITCH|SW-|SW_|AP-|AP_|ACCESS|FIREWALL|GATEWAY|FW/i, 'network'],
  [/PC|LAP|DESK|NOTE|COMP/i, 'computer']
]

export function inferirTipo(id) {
  const s = String(id || '')
  for (const [re, tipo] of REGLAS) if (re.test(s)) return tipo
  return 'computer'
}

export function tipoDe(id, overrides) {
  const o = overrides && overrides[id]
  return o || inferirTipo(id)
}

export function etiquetaTipo(tipo) {
  return ETIQUETAS[tipo] || ETIQUETAS.unknown
}
