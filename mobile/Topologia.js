import React, { useMemo, useState } from 'react'
import { View, Text, Pressable, StyleSheet } from 'react-native'
import Svg, { G, Circle, Line, Path, Rect, Text as SvgText } from 'react-native-svg'
import { C, estadoColor, estadoBadge } from './theme'
import { TIPOS, tipoDe, etiquetaTipo } from './deviceType'

const VW = 360
const VH = 300
const CX = VW / 2
const CY = 140
const R_SERVER = 30
const R_NODO = 21

function esOffline(estado) {
  return String(estado || '').toUpperCase() === 'OFFLINE'
}

function calcularPosiciones(nodos) {
  const n = nodos.length
  const pos = {}
  if (n === 0) return pos
  const dosAnillos = n > 10
  const primeros = dosAnillos ? 8 : n
  nodos.forEach((nodo, i) => {
    let rx = 132
    let ry = 88
    let indice = i
    let total = n
    if (dosAnillos && i >= primeros) {
      rx = 158
      ry = 112
      indice = i - primeros
      total = n - primeros
    } else if (dosAnillos) {
      rx = 82
      ry = 56
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
  return { x1: CX + ux * r0, y1: CY + uy * r0, x2: x - ux * r1, y2: y - uy * r1 }
}

function Glyph({ tipo, color }) {
  const common = { fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }
  if (tipo === 'server') {
    return (
      <G {...common}>
        <Rect x={-8} y={-10} width={16} height={7} rx={1.5} />
        <Rect x={-8} y={-2} width={16} height={7} rx={1.5} />
        <Circle cx={-4} cy={-6.5} r={1} fill={color} stroke="none" />
        <Circle cx={-4} cy={1.5} r={1} fill={color} stroke="none" />
      </G>
    )
  }
  if (tipo === 'printer') {
    return (
      <G {...common}>
        <Path d="M-6 -3h12v6H-6z" />
        <Path d="M-4 -3v-5h8v5" />
        <Rect x={-4} y={2} width={8} height={4} rx={0.5} />
      </G>
    )
  }
  if (tipo === 'network') {
    return (
      <G {...common}>
        <Path d="M0 -9 9 0 0 9 -9 0z" />
        <Path d="M-4 0h8" />
      </G>
    )
  }
  return (
    <G {...common}>
      <Rect x={-8} y={-8} width={16} height={12} rx={2} />
      <Path d="M-3 7h6" />
      <Path d="M0 4v3" />
    </G>
  )
}

function Barra({ valor, color }) {
  return (
    <View style={s.bar}>
      <View style={[s.fill, { width: `${Math.max(0, Math.min(100, valor || 0))}%`, backgroundColor: color }]} />
    </View>
  )
}

export default function Topologia({ nodos }) {
  const [tipos, setTipos] = useState({})
  const [sel, setSel] = useState(null)
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
    <View>
      <View style={s.canvas}>
        <Svg width="100%" height={300} viewBox={`0 0 ${VW} ${VH}`}>
          {nodos.map(n => {
            const p = posiciones[n.id]
            if (!p) return null
            const color = estadoColor(n.estado)
            const e = acortarEnlace(p.x, p.y, R_SERVER, R_NODO)
            return (
              <Line
                key={'l-' + n.id}
                x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
                stroke={color}
                strokeWidth={sel === n.id ? 2.5 : 1.4}
                strokeOpacity={esOffline(n.estado) ? 0.35 : 0.65}
                strokeDasharray={esOffline(n.estado) ? [5, 5] : undefined}
              />
            )
          })}

          <G transform={`translate(${CX},${CY})`}>
            <Circle r={R_SERVER} fill={C.bgSoft} stroke={C.accent} strokeWidth={2.5} />
            <Glyph tipo="server" color={C.accent} />
            <SvgText x={0} y={R_SERVER + 14} fontSize={9} fontWeight="800" fill={C.inkStrong} textAnchor="middle">SERVIDOR</SvgText>
            <SvgText x={0} y={R_SERVER + 25} fontSize={7} fill={C.muted} textAnchor="middle">UDP 5000 · TCP 5001</SvgText>
          </G>

          {nodos.map(n => {
            const p = posiciones[n.id]
            if (!p) return null
            const color = estadoColor(n.estado)
            const tipo = tipoDe(n.id, tipos)
            const activo = sel === n.id
            return (
              <G key={n.id} transform={`translate(${p.x},${p.y})`} onPress={() => setSel(n.id)}>
                <Circle
                  r={activo ? R_NODO + 4 : R_NODO}
                  fill={C.bgSoft}
                  stroke={color}
                  strokeWidth={activo ? 3 : 2}
                  strokeDasharray={esOffline(n.estado) ? [4, 3] : undefined}
                  opacity={esOffline(n.estado) ? 0.7 : 1}
                />
                <Glyph tipo={tipo} color={color} />
                <SvgText x={0} y={R_NODO + 13} fontSize={8} fontWeight="700" fill={C.inkStrong} textAnchor="middle">{n.id}</SvgText>
                <SvgText x={0} y={R_NODO + 23} fontSize={7} fill={C.muted} textAnchor="middle">{n.ip}</SvgText>
              </G>
            )
          })}
        </Svg>
        {nodos.length === 0 && <Text style={s.empty}>Sin nodos. Levantá agentes UDP en las laptops.</Text>}
      </View>

      <View style={s.panel}>
        {seleccionado ? (
          <>
            <View style={s.panelHead}>
              <View style={s.avatar}><Text style={s.avatarT}>{seleccionado.id.slice(0, 2)}</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={s.panelTitle}>{seleccionado.id}</Text>
                <Text style={s.hint}>{seleccionado.ip}</Text>
              </View>
              <Text style={[s.badge, s['badge_' + estadoBadge(seleccionado.estado)]]}>{seleccionado.estado}</Text>
            </View>

            <View style={s.metricRow}>
              <Text style={s.metricLbl}>CPU</Text>
              <View style={{ flex: 1 }}><Barra valor={seleccionado.cpu} color={estadoColor(seleccionado.estado)} /></View>
              <Text style={s.metricVal}>{seleccionado.cpu}%</Text>
            </View>
            <View style={s.metricRow}>
              <Text style={s.metricLbl}>RAM</Text>
              <View style={{ flex: 1 }}><Barra valor={seleccionado.ram} color={estadoColor(seleccionado.estado)} /></View>
              <Text style={s.metricVal}>{seleccionado.ram}%</Text>
            </View>
            <View style={s.metricRow}>
              <Text style={s.metricLbl}>DISCO</Text>
              <View style={{ flex: 1 }}><Barra valor={seleccionado.disco} color={estadoColor(seleccionado.estado)} /></View>
              <Text style={s.metricVal}>{seleccionado.disco}%</Text>
            </View>

            <Text style={s.hint}>Última actualización: {seleccionado.last == null ? '—' : seleccionado.last + ' s'}</Text>
            <Text style={[s.hint, { marginTop: 8 }]}>Tipo de dispositivo</Text>
            <View style={s.chips}>
              <Pressable
                onPress={() => cambiarTipo(seleccionado.id, '')}
                style={[s.chip, !tipos[seleccionado.id] && s.chipOn]}
              >
                <Text style={[s.chipT, !tipos[seleccionado.id] && s.chipTOn]}>Auto</Text>
              </Pressable>
              {TIPOS.map(t => {
                const activo = tipos[seleccionado.id] === t
                return (
                  <Pressable key={t} onPress={() => cambiarTipo(seleccionado.id, t)} style={[s.chip, activo && s.chipOn]}>
                    <Text style={[s.chipT, activo && s.chipTOn]}>{etiquetaTipo(t)}</Text>
                  </Pressable>
                )
              })}
            </View>
            <Text style={s.hint}>Tipo efectivo: {etiquetaTipo(tipoDe(seleccionado.id, tipos))}</Text>
          </>
        ) : (
          <Text style={s.hint}>Tocá un dispositivo del diagrama para ver IP, estado y métricas. Podés cambiar su tipo (PC, servidor, impresora o red).</Text>
        )}

        <View style={s.legend}>
          <View style={s.legendItem}><View style={[s.legendDot, { backgroundColor: C.ok }]} /><Text style={s.hint}>Online</Text></View>
          <View style={s.legendItem}><View style={[s.legendDot, { backgroundColor: C.warn }]} /><Text style={s.hint}>Warning</Text></View>
          <View style={s.legendItem}><View style={[s.legendDot, { backgroundColor: C.off }]} /><Text style={s.hint}>Offline</Text></View>
        </View>
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  canvas: { backgroundColor: C.bgSoft, borderWidth: 1, borderColor: C.line, borderRadius: 14, overflow: 'hidden', position: 'relative' },
  empty: { position: 'absolute', top: 130, left: 16, right: 16, textAlign: 'center', color: C.muted, fontSize: 12 },
  panel: { backgroundColor: C.bgSoft, borderWidth: 1, borderColor: C.line, borderRadius: 14, padding: 14, marginTop: 10 },
  panelHead: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: C.card2, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: C.accent },
  avatarT: { color: C.accent, fontWeight: '900' },
  panelTitle: { color: C.inkStrong, fontWeight: '800', fontSize: 15 },
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, fontSize: 11, fontWeight: '800', color: '#04121c', overflow: 'hidden' },
  badge_ok: { backgroundColor: C.ok },
  badge_warn: { backgroundColor: C.warn },
  badge_off: { backgroundColor: C.off },
  metricRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6 },
  metricLbl: { width: 42, color: C.muted, fontSize: 11 },
  metricVal: { width: 42, textAlign: 'right', color: C.inkStrong, fontSize: 12, fontWeight: '700' },
  bar: { height: 8, backgroundColor: '#0a1422', borderRadius: 99, overflow: 'hidden', borderWidth: 1, borderColor: C.lineSoft },
  fill: { height: '100%', borderRadius: 99 },
  hint: { color: C.muted, fontSize: 12, marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: C.line, backgroundColor: C.card },
  chipOn: { backgroundColor: C.accent, borderColor: C.accent },
  chipT: { color: C.ink, fontSize: 11, fontWeight: '700' },
  chipTOn: { color: '#04121c' },
  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 10, marginTop: 12 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 9, height: 9, borderRadius: 5 }
})
