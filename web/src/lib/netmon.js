// Cliente NETMON/1.0 sobre WebSocket (gateway transparente WS->TCP).
// NO inventa REST: envia y recibe las mismas tramas que admin_client.py:
//   CMD|PING  CMD|AUTH|u|p  CMD|GET_NODES|ALL  CMD|EXEC|NODO|CMD
//   RES|OK|...  RES|ERR|ERR_10x|...

export function buildCmd(action, ...params) {
  return ['CMD', String(action).toUpperCase(), ...params.map(String)].join('|')
}

export function parseRes(raw) {
  const p = String(raw || '').split('|')
  if (p.length < 3 || p[0] !== 'RES') throw new Error('Respuesta sin cabecera RES: ' + raw)
  return { status: p[1], code: p[2], detail: p.slice(3).join('|') }
}

export function parseNodes(payload) {
  // NODES_COUNT:2;NODO_01:192.168.43.10:OK:CPU=35.4%:RAM=62.1%:DISK=40.0%:LAST=1.2
  const out = []
  for (const entry of String(payload || '').split(';')) {
    if (!entry || entry.startsWith('NODES_COUNT')) continue
    const f = entry.split(':')
    if (f.length < 3) continue
    const n = { id: f[0], ip: f[1], estado: f[2], cpu: 0, ram: 0, disco: 0, last: null }
    const m = entry.match(/(CPU|RAM|DISK|LAST)=([0-9]+(?:\.[0-9]+)?)/g) || []
    for (const kv of m) {
      const [k, v] = kv.split('=')
      const num = parseFloat(v)
      if (k === 'CPU') n.cpu = num
      if (k === 'RAM') n.ram = num
      if (k === 'DISK') n.disco = num
      if (k === 'LAST') n.last = num
    }
    out.push(n)
  }
  return out
}

export class NetmonWS {
  constructor(url) {
    this.url = url
    this.ws = null
    this.cola = [] // resolvers en orden FIFO (una respuesta por comando)
    this.buffer = ''
    this.onLog = null
    this.onClose = null
  }
  connect() {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url)
      } catch (e) { reject(e); return }
      const to = setTimeout(() => reject(new Error('Timeout WS')), 6000)
      this.ws.onopen = () => { clearTimeout(to); this._log('SYS', 'WS conectado a ' + this.url); resolve() }
      this.ws.onerror = () => { clearTimeout(to); reject(new Error('No se pudo conectar al gateway ' + this.url)) }
      this.ws.onclose = () => { this._log('SYS', 'WS cerrado'); this.onClose && this.onClose() }
      this.ws.onmessage = (ev) => this._llegada(String(ev.data || ''))
    })
  }
  _log(dir, texto) { this.onLog && this.onLog(dir, texto) }
  _llegada(chunk) {
    // El gateway manda una trama por mensaje, pero igual acumulamos por \n
    this.buffer += chunk
    let i
    while ((i = this.buffer.indexOf('\n')) >= 0) {
      const linea = this.buffer.slice(0, i).trim()
      this.buffer = this.buffer.slice(i + 1)
      if (!linea) continue
      this._log('RX', linea)
      const next = this.cola.shift()
      if (next) next(linea)
    }
    // Mensajes sin \n (gateway ya los manda pelados): entregarlos directo
    if (this.buffer && !this.buffer.includes('\n')) {
      const linea = this.buffer.trim()
      this.buffer = ''
      if (linea) {
        this._log('RX', linea)
        const next = this.cola.shift()
        if (next) next(linea)
      }
    }
  }
  sendRaw(trama) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== 1) { reject(new Error('WS no conectado')); return }
      this._log('TX', trama)
      this.cola.push(resolve)
      this.ws.send(trama)
      setTimeout(() => {
        const ix = this.cola.indexOf(resolve)
        if (ix >= 0) { this.cola.splice(ix, 1); reject(new Error('Timeout esperando RES')) }
      }, 6000)
    })
  }
  cmd(action, ...params) { return this.sendRaw(buildCmd(action, ...params)) }
  close() { try { this.ws && this.ws.close() } catch {} }
}
