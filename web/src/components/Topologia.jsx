import React, { useEffect, useMemo, useState } from 'react'
import { TIPOS, ETIQUETAS, tipoDe, etiquetaTipo } from '../lib/deviceType'

const STORAGE_KEY = 'sdmr.tipos'

const VIEW_W = 760
const VIEW_H = 470
const CX = VIEW_W / 2
const CY = VIEW_H / 2
const R_SERVER = 36
const R_NODO = 25

function estadoColor(estado) {
  const e = String(estado || '').toUpperCase()
  if (e === 'OK') return '#10B981'
  if (e === 'WARNING') return '#F59E0B'
  return '#EF4444'
}

function esOffline(estado) {
  return String(estado || '').toUpperCase() === 'OFFLINE'
}

function cargarTipos() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

function calcularPosiciones(nodos) {
  const n = nodos.length
  const pos = {}
  if (n === 0) return pos

  const dosAnillos = n > 10
  const primeros = dosAnillos ? 8 : n

  nodos.forEach((nodo, i) => {
    let rx = 285
    let ry = 168
    let indice = i
    let total = n
    if (dosAnillos && i >= primeros) {
      rx = 320
      ry = 195
      indice = i - primeros
      total = n - primeros
    } else if (dosAnillos) {
      rx = 180
      ry = 106
    }
    const ang = -Math.PI / 2 + (2 * Math.PI * indice) / Math.max(total, 1)
    pos[nodo.id] = { x: CX + rx * Math.cos(ang), y: CY + ry * Math.sin(ang) }
  })
  return pos
}

function acortarEnlace(x, y, r0, r1) {
  const dx = x - CX
  const dy = y - CY
  const d = Math.hypot(dx, dy) || 1
  const ux = dx / d
  const uy = dy / d
  return {
    x1: CX + ux * r0,
    y1: CY + uy * r0,
    x2: x - ux * r1,
    y2: y - uy * r1
  }
}

function Glyph({ tipo, color }) {
  const common = {
    fill: 'none',
    stroke: color,
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round'
  }
  if (tipo === 'server') {
    return (
      <g {...common}>
        <rect x="-9" y="-11" width="18" height="8" rx="1.5" />
        <rect x="-9" y="-2" width="18" height="8" rx="1.5" />
        <circle cx="-5" cy="-7" r="1" fill={color} stroke="none" />
        <circle cx="-5" cy="2" r="1" fill={color} stroke="none" />
      </g>
    )
  }
  if (tipo === 'printer') {
    return (
      <g {...common}>
        <path d="M-6 -3h12v7H-6z" />
        <path d="M-4 -3v-6h8v6" />
        <rect x="-4" y="2" width="8" height="4" rx="0.5" />
      </g>
    )
  }
  if (tipo === 'network') {
    return (
      <g {...common}>
        <path d="M0 -10 10 0 0 10 -10 0z" />
        <path d="M-4 0h8" />
      </g>
    )
  }
  return (
    <g {...common}>
      <rect x="-9" y="-9" width="18" height="13" rx="2" />
      <path d="M-4 8h8" />
      <path d="M0 4v4" />
    </g>
  )
}

function TipoChip({ tipo, color }) {
  return (
    <span className="topo-tipo-chip" title={etiquetaTipo(tipo)}>
      <svg viewBox="-14 -14 28 28" width="18" height="18">
        <Glyph tipo={tipo} color={color} />
      </svg>
      {etiquetaTipo(tipo)}
    </span>
  )
}

export default function Topologia({ nodos }) {
  const [tipos, setTipos] = useState(cargarTipos)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tipos))
    } catch {}
  }, [tipos])

  const posiciones = useMemo(() => calcularPosiciones(nodos), [nodos])

  const seleccionado = nodos.find(n => n.id === sel) || null

  function cambiarTipo(id, valor) {
    setTipos(prev => {
      const copia = { ...prev }
      if (valor) copia[id] = valor
      else delete copia[id]
      return copia
    })
  }

  return (
    <div className="card">
      <div className="card-h">
        <b>Topología interactiva</b>
        <span className="hint">Hacé clic en un dispositivo para ver sus recursos</span>
      </div>
      <div className="card-b">
        <div className="topo-body">
          <div className="topo-canvas">
            <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="topo-svg" role="img" aria-label="Topología de la red">
              {nodos.map(n => {
                const p = posiciones[n.id]
                if (!p) return null
                const color = estadoColor(n.estado)
                const e = acortarEnlace(p.x, p.y, R_SERVER, R_NODO)
                return (
                  <line
                    key={'l-' + n.id}
                    x1={e.x1}
                    y1={e.y1}
                    x2={e.x2}
                    y2={e.y2}
                    stroke={color}
                    strokeWidth={sel === n.id ? 2.5 : 1.5}
                    strokeOpacity={esOffline(n.estado) ? 0.35 : 0.65}
                    strokeDasharray={esOffline(n.estado) ? '5 5' : undefined}
                  />
                )
              })}

              <g className="topo-node topo-server" transform={`translate(${CX},${CY})`}>
                <circle r={R_SERVER} fill="#0F172A" stroke="#00E5FF" strokeWidth="2.5" />
                <Glyph tipo="server" color="#00E5FF" />
                <text y={R_SERVER + 16} textAnchor="middle" className="topo-label-strong">SERVIDOR</text>
                <text y={R_SERVER + 29} textAnchor="middle" className="topo-label">UDP 5000 · TCP 5001 · WS 5003</text>
              </g>

              {nodos.map(n => {
                const p = posiciones[n.id]
                if (!p) return null
                const color = estadoColor(n.estado)
                const tipo = tipoDe(n.id, tipos)
                const activo = sel === n.id
                return (
                  <g
                    key={n.id}
                    className={'topo-node' + (activo ? ' selected' : '')}
                    transform={`translate(${p.x},${p.y})`}
                    onClick={() => setSel(n.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={ev => { if (ev.key === 'Enter' || ev.key === ' ') setSel(n.id) }}
                  >
                    <circle
                      r={activo ? R_NODO + 4 : R_NODO}
                      fill="#0F172A"
                      stroke={color}
                      strokeWidth={activo ? 3 : 2}
                      strokeDasharray={esOffline(n.estado) ? '4 3' : undefined}
                      opacity={esOffline(n.estado) ? 0.7 : 1}
                    />
                    <Glyph tipo={tipo} color={color} />
                    <text y={R_NODO + 16} textAnchor="middle" className="topo-label-strong">{n.id}</text>
                    <text y={R_NODO + 28} textAnchor="middle" className="topo-label">{n.ip}</text>
                  </g>
                )
              })}
            </svg>

            {nodos.length === 0 && (
              <div className="topo-empty hint">Sin nodos. Levantá agentes UDP en las laptops para verlos aparecer.</div>
            )}
          </div>

          <aside className="topo-panel">
            {seleccionado ? (
              <>
                <div className="topo-panel-head">
                  <div className="avatar" style={{ width: 42, height: 42 }}>
                    <div>{seleccionado.id.slice(0, 2)}</div>
                  </div>
                  <div>
                    <div className="topo-panel-title">{seleccionado.id}</div>
                    <div className="hint">{seleccionado.ip}</div>
                  </div>
                  <span className={'badge ' + (String(seleccionado.estado).toUpperCase() === 'OK' ? 'ok' : String(seleccionado.estado).toUpperCase() === 'WARNING' ? 'warn' : 'off')}>
                    {seleccionado.estado}
                  </span>
                </div>

                <div className="topo-metric">
                  <span className="hint">CPU</span>
                  <div className="bar"><i style={{ width: `${seleccionado.cpu || 0}%`, background: estadoColor(seleccionado.estado) }} /></div>
                  <b>{seleccionado.cpu}%</b>
                </div>
                <div className="topo-metric">
                  <span className="hint">RAM</span>
                  <div className="bar"><i style={{ width: `${seleccionado.ram || 0}%`, background: estadoColor(seleccionado.estado) }} /></div>
                  <b>{seleccionado.ram}%</b>
                </div>
                <div className="topo-metric">
                  <span className="hint">DISCO</span>
                  <div className="bar"><i style={{ width: `${seleccionado.disco || 0}%`, background: estadoColor(seleccionado.estado) }} /></div>
                  <b>{seleccionado.disco}%</b>
                </div>

                <div className="topo-dato">
                  <span className="hint">Última actualización</span>
                  <b>{seleccionado.last == null ? '—' : seleccionado.last + ' s'}</b>
                </div>

                <label className="topo-field">
                  <span className="hint">Tipo de dispositivo</span>
                  <select value={tipos[seleccionado.id] || ''} onChange={e => cambiarTipo(seleccionado.id, e.target.value)}>
                    <option value="">{ETIQUETAS.auto}</option>
                    {TIPOS.map(t => <option key={t} value={t}>{ETIQUETAS[t]}</option>)}
                  </select>
                </label>
                <div className="topo-dato">
                  <span className="hint">Tipo efectivo</span>
                  <TipoChip tipo={tipoDe(seleccionado.id, tipos)} color={estadoColor(seleccionado.estado)} />
                </div>
              </>
            ) : (
              <div className="hint">Seleccioná un dispositivo del diagrama para ver IP, estado y métricas. Podés cambiar su tipo (PC, servidor, impresora o red).</div>
            )}

            <div className="topo-legend">
              <div><span className="dot" style={{ background: '#10B981' }} /> Online</div>
              <div><span className="dot" style={{ background: '#F59E0B' }} /> Warning</div>
              <div><span className="dot" style={{ background: '#EF4444' }} /> Offline</div>
              <div className="hint">Tipo inferido por el ID; cambiable por nodo.</div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
