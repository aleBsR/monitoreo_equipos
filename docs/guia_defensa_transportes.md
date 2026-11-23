# Guía de defensa — Cómo funciona cada parte del SDMR (transportes TCP/UDP)

Guía de estudio para la defensa oral: qué transporte usa cada sección de la web,
por qué, dónde está la librería `socket` y qué librería usa la sección "Extra".
Las referencias `archivo:línea` son del repositorio al momento de escribir esta guía.

---

## 🧠 La idea central (decir esto primero)

El sistema usa **un solo protocolo propio, NETMON/1.0**, sobre **dos transportes**:

- **UDP (puerto 5000):** telemetría/heartbeat de los agentes → servidor. Rápido, sin
  conexión, "fuego y olvido".
- **TCP (puerto 5001):** comandos de administración (login, consultas, EXEC). Confiable,
  ordenado, con confirmación.

**El detalle clave de la web:** el navegador **no habla UDP ni TCP directo** (no puede).
Habla **WebSocket** con el **gateway** (`server/gateway.py`, puerto 5003), y el gateway
**abre una conexión TCP real al servidor** (`asyncio.open_connection` → puerto 5001) y
reenvía las tramas NETMON **tal cual**, sin cambiarlas.

```
Navegador ──WebSocket:5003──> gateway ──TCP:5001──> servidor
Agentes   ─────────────────UDP:5000──────────────> servidor
```

Entonces: **todo lo que hace la web es TCP** (a través del WebSocket→gateway). El **UDP
solo existe entre los agentes y el servidor**. Los datos que se ven en la web **nacieron
por UDP** (telemetría) pero **llegan a la web por TCP** (consulta `GET_NODES`).

> Frase para la defensa: *"El UDP mete los datos al servidor; el TCP los saca hacia los clientes."*

---

## 🎬 Flujo de la demo en vivo (cómo lo corro)

En esta demo la **notebook es el servidor** (`192.168.0.8`) y la **Raspberry es un
agente remoto**. Así se ve lo distribuido: nodos locales + un equipo físico distinto
con su IP real.

**1) Arranque con el Centro de Control (en la notebook):**

```bash
cd ~/Documentos/workspace/redes/scripts && ./centro_control.sh
```

Abre el panel **SDMR · Centro de Control** en `http://127.0.0.1:7070`. Con un clic en
**"⚡ Encender TODO"** levanta todo el stack sin tocar más la terminal:

- **Servidor central** → UDP 5000 (telemetría) + TCP 5001 (comandos)
- **Gateway WS** → 5003 (puente WebSocket → TCP para la web)
- **Web (dashboard)** → 5173
- **Escaneo de red** → 8090 (el servicio Scapy de la sección "Red extra")
- **2 agentes demo** → `NODO_01` y `NODO_02` (en `127.0.0.1`, misma máquina)

> El Centro de Control es una **comodidad local**: solo biblioteca estándar, escucha en
> `127.0.0.1`, **aislado del core** (si se borra, el SDMR queda intacto). No es parte del
> protocolo NETMON/1.0 — es para no tener que abrir cinco terminales en la demo.

**2) Login en el dashboard** (`http://localhost:5173`, `admin` / `admin123`): es **TCP**
(WebSocket → gateway → TCP 5001). Desde acá se sigue la explicación sección por sección
(abajo).

**3) Sumar el nodo REAL de la Raspberry** (para mostrar un equipo físico distinto):

```bash
ssh raspberry@192.168.0.13
cd ~/monitoreo_equipos/agent && python3 agent.py NODO_raspberry 192.168.0.8 5000 5002
```

Argumentos: `NODO_raspberry` (ID) · `192.168.0.8` (IP del **servidor** = la notebook) ·
`5000` (UDP telemetría) · `5002` (puerto TCP para EXEC). La Pi manda su telemetría por
**UDP** a la notebook; aparece en el dashboard como **`NODO_raspberry` con IP
`192.168.0.13`** (su IP real en la LAN), junto a `NODO_01`/`NODO_02` que están en
`127.0.0.1`.

> **Punto fuerte para la defensa:** acá se ve lo **distribuido de verdad** — un equipo
> físico aparte, con otra IP, cruzando la red real por UDP. El servidor **descarta la IP
> que viaja dentro de la trama** y usa la **IP de origen real** del datagrama, por eso
> `NODO_raspberry` sale con `192.168.0.13` y no con lo que diga el mensaje.

**4) Seguir con la guía:** en **Feed** se ven los 3 nodos en vivo; en **Nodos** se prueba
**EXEC** (ej. `DIAGNOSTIC` sobre `NODO_raspberry`); en **Topología** aparecen dibujados;
en **Tráfico** se muestran las tramas y un error (`ERR_103`). Cada sección, con su
transporte, está explicada abajo.

---

## Sección por sección

### 🔐 Login
- **Transporte: TCP.** Al apretar "Entrar", la web hace `cli.cmd('PING')` y
  `cli.cmd('AUTH', usuario, clave)` (`web/src/App.jsx:56,59`), que viajan como
  `CMD|PING` y `CMD|AUTH|admin|admin123` por el WebSocket → gateway → **TCP** al servidor.
- **Por qué TCP:** un login **no se puede perder ni desordenar**, y necesita una
  **respuesta segura** (`AUTH_SUCCESS` o `ERR_101`). TCP garantiza entrega, orden y ACK.
  Con UDP el OK podría perderse.

### 📰 Feed
- **Transporte: TCP** (los datos **originalmente** vienen por UDP).
- La web hace **polling**: cada 2 s pide `cli.cmd('GET_NODES', 'ALL')`
  (`web/src/App.jsx:141,155` → "poll GET_NODES cada 2s"). Eso es TCP.
- **Cómo se arma el dato:** los agentes mandan su CPU/RAM/disco por **UDP** al servidor
  cada 3 s; el servidor los guarda en `nodes_registry`; cuando la web pide `GET_NODES`,
  el servidor responde por **TCP** con la foto actual.

### 🖧 Nodos
- **Transporte: TCP** (tabla + EXEC).
- La **tabla** sale del mismo `GET_NODES` (TCP).
- **EXEC remoto:** `cli.cmd('EXEC', nodo, comando)` (`web/src/App.jsx:194`). El TCP se
  usa **dos veces**:
  1. Web → servidor (`CMD|EXEC|NODO_01|DIAGNOSTIC`) por TCP :5001.
  2. El **servidor abre una conexión TCP NUEVA** hacia el **canal de control del agente**
     (puerto 5002) y le manda `EXECCMD|DIAGNOSTIC`. El agente valida contra su lista
     blanca (`RESTART_SERVICE, DIAGNOSTIC, CLEAR_LOGS`), ejecuta y responde.
- **Por qué TCP y no UDP:** una orden de ejecución tiene que llegar **sí o sí** y traer
  un resultado; es el caso de libro para TCP.

### 🕸️ Topología
- **Transporte: TCP** (no tiene red propia).
- `Topologia({ nodos })` (`web/src/components/Topologia.jsx:129`) **solo dibuja** el mismo
  array `nodos` que ya trajo `GET_NODES` (TCP). Las posiciones se calculan en el navegador
  (`calcularPosiciones`). No hace ninguna llamada de red adicional.
- Su mensaje de "sin nodos" dice *"Levantá agentes UDP…"*: recuerda que el origen último
  del dato es la telemetría UDP.

### ⇄ Tráfico
- **Transporte: TCP.** Es un **log en vivo** de las tramas NETMON que entran y salen
  (TX `CMD|...` / RX `RES|...`) por el canal WebSocket→TCP. También permite mandar tramas
  crudas con `sendRaw` (`web/src/App.jsx:202`) para mostrar el manejo de errores
  (`ERR_100`, `ERR_103`) **sin cortar la conexión** (RF07).

### 🌐 Red (extra) — ⚠️ la excepción
- **NO usa NETMON/1.0, NO usa UDP 5000 / TCP 5001 / WS 5003.** Es un módulo **aislado**.
- **Transporte: HTTP.** La web hace `fetch('http://host:8090/scan?subnet=...')`
  (`web/src/App.jsx:163-164`) a un **servicio HTTP auxiliar independiente**:
  `extras/lan_scan_service.py` (puerto 8090).
- **Librería: `Scapy`.** Ese servicio llama a `extras/network_discovery.py`, que hace un
  **ARP scan real con Scapy** (`from scapy.all import ...`, función `arp_scan_scapy`). Si
  Scapy **no** está instalado, cae a un **fallback con `arp -a`** del sistema (vía
  `subprocess`), sin dependencias.
- **Por qué está separado:** la cátedra evalúa el uso **explícito** de sockets y el
  parseo **manual** del protocolo. Scapy y HTTP ocultarían eso, así que se mantiene
  **fuera del core**. El propio código lo aclara: *"Si se solicita retirar esta
  funcionalidad extra, basta con eliminar la carpeta `extras/`: el SDMR queda intacto."*

---

## 🔌 Dónde está la librería `socket` (el corazón de la cátedra)

`import socket` está en el **backend de Python**, con el tipo según el transporte:

| Archivo | UDP (`SOCK_DGRAM`) | TCP (`SOCK_STREAM`) |
| --- | --- | --- |
| `server/server.py` | ✅ `:5000` telemetría (línea 113) | ✅ `:5001` comandos (línea 125) |
| `agent/agent.py` | ✅ envía `MON` con `sendto()` (226, 506) | ✅ canal EXEC `:5002` (256) |
| `client/admin_client.py` | — | ✅ `:5001` (59) |
| `common/protocol.py` | **nada de socket**: solo arma/parsea tramas y el `TcpFrameReader` (independiente del transporte) | |
| `server/gateway.py` | usa la librería **`websockets`** (+ `asyncio.open_connection` para el TCP), no socket crudo | |

- **`AF_INET`** = IPv4. **`SOCK_DGRAM`** = UDP (datagramas, sin conexión).
  **`SOCK_STREAM`** = TCP (flujo de bytes confiable).
- La **web/móvil (JS)** usan la **API WebSocket del navegador**, no `socket` de Python.
  El `socket` de Python está en el servidor, los agentes y el cliente de consola.

---

## 📋 Tabla resumen

| Sección web | Transporte | Comando/llamada | Origen real del dato |
| --- | --- | --- | --- |
| **Login** | TCP (WS→gateway) | `CMD\|PING`, `CMD\|AUTH` | — |
| **Feed** | TCP (poll 2 s) | `CMD\|GET_NODES` | telemetría **UDP** de agentes |
| **Nodos** | TCP (+ EXEC) | `CMD\|GET_NODES`, `CMD\|EXEC` | UDP + ejecución TCP server→agente |
| **Topología** | TCP | reusa `GET_NODES` | UDP (dibujado local) |
| **Tráfico** | TCP | tramas crudas | el propio canal NETMON |
| **Red (extra)** | **HTTP :8090** | `fetch /scan` | **Scapy** (ARP) / `arp -a` |

---

## Preguntas típicas y respuesta corta

- **¿Por qué UDP para la telemetría?** Es periódica (cada 3 s) y se renueva sola: si se
  pierde un reporte, el siguiente lo reemplaza. Importa la rapidez y el bajo costo, no la
  entrega garantizada. El control de pérdidas lo hace la app (watchdog → OFFLINE a los 15 s).
- **¿Por qué TCP para los comandos?** AUTH, GET_NODES y EXEC no pueden perderse ni
  desordenarse y necesitan respuesta confiable.
- **¿La web usa UDP?** No directamente: usa WebSocket → el gateway lo convierte en TCP.
  El UDP solo corre entre agentes y servidor.
- **¿Qué librería usa la sección Extra?** Scapy (ARP scan), con fallback a `arp -a`. Está
  aislada en `extras/` y no toca el protocolo NETMON/1.0.
- **¿Dónde está la API de sockets?** En `server/`, `agent/` y `client/` (Python `socket`,
  `AF_INET` + `SOCK_DGRAM`/`SOCK_STREAM`). `common/protocol.py` arma/parsea las tramas a mano.
