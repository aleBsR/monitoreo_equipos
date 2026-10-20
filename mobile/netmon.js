// Mismo protocolo que web y que admin_client.py. En RN existe WebSocket global.
export function buildCmd(action, ...params) {
  return ['CMD', String(action).toUpperCase(), ...params.map(String)].join('|')
}
export function parseRes(raw) {
  const p = String(raw || '').split('|')
  if (p.length < 3 || p[0] !== 'RES') throw new Error('Sin cabecera RES: ' + raw)
  return { status: p[1], code: p[2], detail: p.slice(3).join('|') }
}
export function parseNodes(payload) {
  const out = []
  for (const entry of String(payload || '').split(';')) {
    if (!entry || entry.startsWith('NODES_COUNT')) continue
    const f = entry.split(':')
    if (f.length < 3) continue
    const n = { id: f[0], ip: f[1], estado: f[2], cpu: 0, ram: 0, disco: 0, last: null }
    for (const kv of (entry.match(/(CPU|RAM|DISK|LAST)=([0-9]+(?:\.[0-9]+)?)/g) || [])) {
      const [k, v] = kv.split('=')
      if (k === 'CPU') n.cpu = parseFloat(v)
      if (k === 'RAM') n.ram = parseFloat(v)
      if (k === 'DISK') n.disco = parseFloat(v)
      if (k === 'LAST') n.last = parseFloat(v)
    }
    out.push(n)
  }
  return out
}
export class NetmonWS {
  constructor(url) { this.url = url; this.ws = null; this.cola = []; this.buf = ''; this.onLog = null }
  connect() {
    return new Promise((resolve, reject) => {
      try { this.ws = new WebSocket(this.url) } catch (e) { reject(e); return }
      const to = setTimeout(() => reject(new Error('Timeout WS')), 6000)
      this.ws.onopen = () => { clearTimeout(to); resolve() }
      this.ws.onerror = () => { clearTimeout(to); reject(new Error('Sin conexión a ' + this.url)) }
      this.ws.onmessage = (ev) => {
        const linea = String(ev.data || '').trim()
        if (!linea) return
        this.onLog && this.onLog('RX', linea)
        const next = this.cola.shift()
        if (next) next(linea)
      }
    })
  }
  sendRaw(trama) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== 1) { reject(new Error('WS no conectado')); return }
      this.onLog && this.onLog('TX', trama)
      this.cola.push(resolve)
      this.ws.send(trama)
      setTimeout(() => {
        const i = this.cola.indexOf(resolve)
        if (i >= 0) { this.cola.splice(i, 1); reject(new Error('Timeout RES')) }
      }, 6000)
    })
  }
  cmd(a, ...p) { return this.sendRaw(buildCmd(a, ...p)) }
  close() { try { this.ws && this.ws.close() } catch (e) {} }
}
