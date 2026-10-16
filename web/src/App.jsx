import React, { useEffect, useRef, useState } from 'react'
import { NetmonWS, parseNodes, parseRes } from './lib/netmon.js'

const EXECS = ['RESTART_SERVICE', 'DIAGNOSTIC', 'CLEAR_LOGS']

function estadoClase(e) {
  e = String(e || '').toUpperCase()
  if (e === 'OK') return 'ok'
  if (e === 'WARNING') return 'warn'
  return 'off'
}

function Login({ onOk }) {
  const [gw, setGw] = useState('ws://127.0.0.1:5003')
  const [user, setUser] = useState('admin')
  const [pass, setPass] = useState('admin123')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  // Autocompleta ws:// con la IP LAN actual si viene de hotspot
  useEffect(() => {
    const host = window.location.hostname
    if (host && host !== 'localhost' && host !== '127.0.0.1') setGw(`ws://${host}:5003`)
  }, [])

  async function entrar(e) {
    e && e.preventDefault()
    setErr(''); setBusy(true)
    const cli = new NetmonWS(gw.trim())
    cli.onLog = () => {}
    try {
      await cli.connect()
      const ping = await cli.cmd('PING')
      const rp = parseRes(ping)
      if (rp.status !== 'OK') throw new Error('Gateway no responde PING')
      const auth = await cli.cmd('AUTH', user.trim(), pass)
      const ra = parseRes(auth)
      if (ra.status !== 'OK') { cli.close(); throw new Error(`[${ra.code}] ${ra.detail}`) }
      onOk(cli, { gw: gw.trim(), user: user.trim() })
    } catch (ex) {
      try { cli.close() } catch {}
      setErr(String(ex.message || ex))
    } finally { setBusy(false) }
  }

  return (
    <div className="login-wrap">
      <div className="phone">
        <div className="phone-art">
          <div style={{ fontSize: 28, fontWeight: 900 }}>SDMR 📡</div>
          <div style={{ opacity: .95 }}>Sistema Distribuido de Monitoreo en Red</div>
          <div className="hint" style={{ color: '#fff', opacity: .85 }}>
            Mismo protocolo <b>NETMON/1.0</b> que la consola Python, pero con onda Instagram.
            Login separado, feed de nodos, historias y tráfico en vivo.
          </div>
          <div className="hint" style={{ color: '#fff', opacity: .8 }}>
            Hotspot del celu: poné la IP LAN del servidor, ej. ws://192.168.43.10:5003
          </div>
        </div>
        <form className="phone-form" onSubmit={entrar}>
          <h2 style={{ margin: '0 0 4px' }}>Iniciar sesión</h2>
          <div className="hint">Gateway WS → TCP 5001 · UDP 5000 sigue en el servidor Python</div>
          <div className="field"><label>Gateway (editable para hotspot)</label>
            <input value={gw} onChange={e => setGw(e.target.value)} placeholder="ws://192.168.43.10:5003" />
          </div>
          <div className="field"><label>Usuario</label>
            <input value={user} onChange={e => setUser(e.target.value)} />
          </div>
          <div className="field"><label>Contraseña</label>
            <input type="password" value={pass} onChange={e => setPass(e.target.value)} />
          </div>
          <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>
            {busy ? 'Conectando…' : 'Entrar'}
          </button>
          {err && <div className="err">{err}</div>}
          <div className="hint" style={{ marginTop: 10 }}>admin / admin123 · operador / operador123</div>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [sesion, setSesion] = useState(null) // {cli, gw, user}
  const [tab, setTab] = useState('feed')
  const [nodos, setNodos] = useState([])
  const [conteo, setConteo] = useState('')
  const [logs, setLogs] = useState([])
  const [craft, setCraft] = useState('CMD|ACCION_DESCONOCIDA')
  const [execNodo, setExecNodo] = useState('NODO_01')
  const [execCmd, setExecCmd] = useState('DIAGNOSTIC')
  const [execOut, setExecOut] = useState('')
  const timer = useRef(null)

  function pushLog(dir, texto) {
    setLogs(prev => [...prev.slice(-199), { h: new Date().toLocaleTimeString(), dir, texto }])
  }

  function conectar(cli, meta) {
    cli.onLog = (dir, texto) => pushLog(dir, texto)
    setSesion({ cli, ...meta })
  }

  async function refrescar() {
    if (!sesion) return
    try {
      const raw = await sesion.cli.cmd('GET_NODES', 'ALL')
      const r = parseRes(raw)
      if (r.status === 'OK') {
        const lista = parseNodes(r.code)
        setNodos(lista)
        const on = lista.filter(n => n.estado !== 'OFFLINE').length
        setConteo(`${lista.length} nodo(s) · ${on} en línea · ${new Date().toLocaleTimeString()}`)
      } else setConteo(`Error: ${r.code}`)
    } catch (e) { setConteo('Sin conexión: ' + e.message) }
  }

  useEffect(() => {
    if (!sesion) return
    refrescar()
    timer.current = setInterval(refrescar, 2000)
    return () => clearInterval(timer.current)
  }, [sesion])

  async function ejecutar() {
    setExecOut('Enviando CMD|EXEC…')
    try {
      const raw = await sesion.cli.cmd('EXEC', execNodo, execCmd)
      const r = parseRes(raw)
      setExecOut(`[${r.status} ${r.code}] ${r.detail}`)
    } catch (e) { setExecOut('Error: ' + e.message) }
  }

  async function enviarCraft() {
    try {
      const raw = await sesion.cli.sendRaw(craft.trim())
      pushLog('SYS', 'Servidor respondió sin cerrar (RF07 OK): ' + raw)
    } catch (e) { pushLog('SYS', 'Error craft: ' + e.message) }
  }

  function salir() {
    try { sesion.cli.close() } catch {}
    clearInterval(timer.current)
    setSesion(null); setNodos([]); setLogs([]); setTab('feed')
  }

  if (!sesion) return <Login onOk={conectar} />

  const total = nodos.length
  const on = nodos.filter(n => n.estado === 'OK').length
  const warn = nodos.filter(n => String(n.estado).toUpperCase() === 'WARNING').length
  const off = nodos.filter(n => String(n.estado).toUpperCase() === 'OFFLINE').length
  const cpuProm = total ? (nodos.reduce((a, n) => a + (n.cpu || 0), 0) / total).toFixed(1) : '0.0'

  return (
    <div>
      <div className="topbar"><div className="topbar-inner">
        <div className="logo logo-grad">SDMR</div>
        <span className="pill"><span className="dot ok" />{sesion.user} · {sesion.gw}</span>
        <span className="pill">{conteo || 'conectando…'}</span>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={refrescar}>⟳</button>
        <button className="btn btn-dark" onClick={salir}>Salir</button>
      </div></div>

      <div className="layout">
        <div className="sidebar">
          {[['feed', '◉ Feed'], ['nodos', '▦ Nodos'], ['topo', '✦ Topología'], ['trafico', '⇄ Tráfico'], ['ayuda', '? Ayuda']].map(([k, l]) => (
            <button key={k} className={'navbtn' + (tab === k ? ' active' : '')} onClick={() => setTab(k)}>{l}</button>
          ))}
          <div className="hint" style={{ padding: '8px 12px' }}>NETMON/1.0<br />UDP 5000 · TCP 5001<br />WS 5003 (gateway)</div>
        </div>

        <div className="feed">
          {tab === 'feed' && (<>
            <div className="card"><div className="card-h">
              <div className="avatar"><div>SD</div></div>
              <div><b>servidor_central</b><div className="hint">Dashboard en vivo · poll GET_NODES cada 2s</div></div>
            </div>
            <div className="card-b">
              <div className="kpis">
                <div className="kpi"><b>{total}</b><span>nodos</span></div>
                <div className="kpi"><b style={{ color: 'var(--ok)' }}>{on}</b><span>online</span></div>
                <div className="kpi"><b style={{ color: 'var(--warn)' }}>{warn}</b><span>warning</span></div>
                <div className="kpi"><b style={{ color: 'var(--off)' }}>{off}</b><span>offline</span></div>
              </div>
              <div className="hint" style={{ marginTop: 8 }}>CPU promedio red: <b>{cpuProm}%</b> · Wireshark: <b>udp.port==5000</b> telemetría, <b>tcp.port==5001</b> comandos</div>
            </div></div>

            <div className="card"><div className="card-h"><b>Historias de nodos</b></div>
              <div className="stories">
                {nodos.length === 0 && <span className="hint">Sin nodos. Levantá agentes UDP en las laptops.</span>}
                {nodos.map(n => (
                  <div key={n.id} className="story" onClick={() => { setExecNodo(n.id); setTab('nodos') }} style={{ cursor: 'pointer' }}>
                    <div className={`ring ${estadoClase(n.estado) === 'ok' ? '' : estadoClase(n.estado)}`}><div>{n.id.slice(-2)}</div></div>
                    <span>{n.id}</span>
                    <span className={`badge ${estadoClase(n.estado)}`}>{n.estado}</span>
                  </div>
                ))}
              </div></div>

            {nodos.map(n => (
              <div className="card" key={n.id}><div className="card-h">
                <div className="avatar"><div>{n.id.slice(0, 2)}</div></div>
                <div><b>{n.id}</b> · {n.ip}<div className="hint">❤ {n.cpu}% · 💬 {n.ram}% · 💾 {n.disco}%</div></div>
                <span style={{ flex: 1 }} /><span className={`badge ${estadoClase(n.estado)}`}>{n.estado}</span>
              </div>
              <div className="card-b">
                <div className="row">
                  <span className="hint">CPU</span><div className="bar" style={{ flex: 1 }}><i style={{ width: `${n.cpu}%` }} /></div><b>{n.cpu}%</b>
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="hint">RAM</span><div className="bar" style={{ flex: 1 }}><i style={{ width: `${n.ram}%` }} /></div><b>{n.ram}%</b>
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="hint">DISK</span><div className="bar" style={{ flex: 1 }}><i style={{ width: `${n.disco}%` }} /></div><b>{n.disco}%</b>
                </div>
              </div></div>
            ))}
          </>)}

          {tab === 'nodos' && (
            <div className="card"><div className="card-h"><b>Nodos + EXEC remoto</b></div>
              <div className="card-b">
                <div className="row">
                  <input value={execNodo} onChange={e => setExecNodo(e.target.value)} style={{ width: 110 }} placeholder="NODO_01" />
                  <select value={execCmd} onChange={e => setExecCmd(e.target.value)}>
                    {EXECS.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <button className="btn btn-primary" onClick={ejecutar}>Enviar EXEC</button>
                </div>
                {execOut && <div className="hint" style={{ marginTop: 8 }}>{execOut}</div>}
                <div style={{ marginTop: 10, overflow: 'auto' }}>
                  <table><thead><tr><th>Nodo</th><th>IP</th><th>Estado</th><th>CPU</th><th>RAM</th><th>Disco</th></tr></thead>
                    <tbody>{nodos.map(n => (
                      <tr key={n.id} onClick={() => setExecNodo(n.id)} style={{ cursor: 'pointer' }}>
                        <td><b>{n.id}</b></td><td>{n.ip}</td>
                        <td><span className={`badge ${estadoClase(n.estado)}`}>{n.estado}</span></td>
                        <td>{n.cpu}%</td><td>{n.ram}%</td><td>{n.disco}%</td>
                      </tr>))}</tbody></table>
                </div>
              </div></div>
          )}

          {tab === 'topo' && (
            <div className="card"><div className="card-h"><b>Topología (quién habla con quién)</b></div>
              <div className="card-b">
                <div className="topo">
                  <div className="node-chip" style={{ borderColor: 'var(--ig-pink)' }}><b>🖥 servidor</b><div className="hint">UDP 5000 · TCP 5001 · WS 5003</div></div>
                  {nodos.map(n => (
                    <div key={n.id} className="node-chip"><b>{n.estado === 'OFFLINE' ? '🔴' : '🟢'} {n.id}</b><div className="hint">{n.ip} · CPU {n.cpu}%</div></div>
                  ))}
                </div>
                <div className="hint" style={{ marginTop: 8 }}>UDP: telemetría periódica (se pierde, no pasa nada). TCP/WS: comandos confiables + EXEC.</div>
              </div></div>
          )}

          {tab === 'trafico' && (
            <div className="card"><div className="card-h"><b>Tráfico NETMON/1.0 (prueba RF07)</b></div>
              <div className="card-b">
                <div className="row">
                  <input value={craft} onChange={e => setCraft(e.target.value)} style={{ flex: 1 }} />
                  <button className="btn btn-dark" onClick={enviarCraft}>Enviar trama</button>
                </div>
                <div className="hint" style={{ margin: '6px 0' }}>Probá: DATOS_BASURA_SIN_CMD (ERR_100) · CMD|ACCION_DESCONOCIDA (ERR_103) · CMD|AUTH (ERR_100)</div>
                <div className="log">{logs.map((l, i) => (
                  <div key={i} className={l.dir.toLowerCase()}>{l.h} {l.dir} {l.texto}</div>
                ))}</div>
              </div></div>
          )}

          {tab === 'ayuda' && (
            <div className="card"><div className="card-h"><b>Ayuda hotspot 📱</b></div>
              <div className="card-b hint">
                1) Celular con hotspot → conectar laptop1, laptop2 y tablet a ese WiFi.<br />
                2) Laptop1: <b>python server/server.py</b> + <b>python server/gateway.py 5003 127.0.0.1 5001 --serve-web</b>.<br />
                3) Ver IP con <b>ipconfig</b> (ej. 192.168.43.10) y usarla en agentes y en este Login (ws://...:5003).<br />
                4) Laptop2: <b>python agent/agent.py NODO_02 192.168.43.10 5000 5002</b>.<br />
                5) Web: <b>http://192.168.43.10:5173</b> · Móvil Expo Go: QR de <b>npx expo start --lan</b>.<br />
                6) Firewall: abrir UDP 5000, TCP 5001/5002/5003.
              </div></div>
          )}
        </div>
      </div>
    </div>
  )
}
