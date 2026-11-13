---
name: sdmr-contexto
description: Contexto del proyecto SDMR (Sistema Distribuido de Monitoreo en Red), el TPI de Programación de Redes con Sockets en Python. Qué es, su arquitectura cliente/servidor sobre TCP+UDP, el protocolo propio NETMON/1.0, dónde tocar cada cosa, las restricciones de la cátedra, los bugs ya corregidos a no reintroducir, y cómo ejecutar y probar todo. Úsala al trabajar en server/, agent/, client/, common/protocol.py, server/gateway.py, web/, mobile/, extras/, los scripts/ lanzadores, o cuando se mencione SDMR, NETMON, monitoreo de nodos, telemetría UDP, heartbeat, watchdog, EXEC remoto, gateway WS, o la defensa oral del TP.
---

# SDMR — Sistema Distribuido de Monitoreo en Red

Trabajo Práctico Integrador para **Programación de Redes con Sockets (Optativa III - LAS)**.
Python 3 con sockets nativos (`socket`, `threading`). Uso educativo, laboratorio de red.
Repo: `github.com/aleBsR/monitoreo_equipos`.

Aplicación distribuida **cliente/servidor** que supervisa en tiempo real la
disponibilidad y las métricas (CPU, RAM, Disco) de múltiples nodos en una LAN, y
permite ejecutar acciones administrativas remotas (`EXEC`). Todo el código,
comentarios, docstrings y salidas por consola están **en español**: mantener ese idioma.

---

## ⛔ Restricción dura de la cátedra

La cátedra evalúa el uso **explícito** de la API de sockets y el parseo **manual**
del protocolo de aplicación. **NO** introducir Django, FastAPI, REST, `asyncio`,
`selectors`, ni ningún framework que oculte la capa de transporte en el core
(server/agent/client/common). `propuesta.md` §2.1 avisa que usar un framework
"podría incidir negativamente en la evaluación de RF03, RF04 y RF06".

Dependencias externas permitidas y declaradas en `requirements.txt`:
- `psutil` — métricas reales (opcional; el agente tiene fallback a simulación).
- `websockets` — solo para el gateway WS→TCP de los clientes web/móvil (reenvía
  tramas NETMON/1.0 tal cual, no cambia el protocolo).
- `scapy` — opcional, solo para el extra de descubrimiento LAN (fallback `arp -a`).

`rich` se quitó por no usarse. No agregar linters, formateadores ni dependencias de build.

---

## 🏗️ Arquitectura

Un solo protocolo de aplicación (`NETMON/1.0`) sobre **dos transportes**. Esa es
la decisión de diseño central y todo lo demás se deriva de ahí.

```
Servidor central (server/server.py)   -> escucha en 0.0.0.0 (todas las interfaces)
  ├─ UDP :5000   <- telemetría/heartbeat de agentes   (sin conexión, cada 3 s)
  ├─ TCP :5001   <- comandos de admins                (conexión, confiable)
  └─ hilo watchdog -> marca OFFLINE a los 15 s y PURGA del registro a los 120 s

agent/agent.py          -> mide CPU/RAM/Disco, envía MON|... por UDP cada 3 s
                           + canal TCP de comandos EXEC (puerto 5002+, argv[4])
client/admin_client.py  -> CLI admin interactivo: PING, AUTH, GET_NODES, EXEC
client/gui_monitor.py   -> dashboard Tkinter (6 pestañas, cliente ADICIONAL)
client/contenido_ayuda.py -> texto de las pestañas de ayuda (INSTRUCCIONES y
                           CONCEPTOS; los conceptos son citas LITERALES de Kurose 5ª ed.)
common/protocol.py      -> encode/decode/parse + TcpFrameReader compartido
server/gateway.py       -> puente WS :5003 -> TCP :5001 (para web y móvil); --serve-web publica web/ en :5173
web/                    -> cliente React estilo Instagram (habla NETMON/1.0 vía gateway WS)
mobile/                 -> cliente React Native (Expo Go), mismo protocolo vía gateway WS
extras/                 -> módulos AISLADOS de descubrimiento LAN (no tocan el core)
scripts/                -> lanzadores (un comando / doble clic) e instaladores de agente
tools/                  -> verificar_red.py (diagnóstico) y test_system.py (integración)
```

El servidor queda con **cuatro hilos vivos**: UDP, watchdog, accept, y uno por
cada cliente TCP conectado. Cada agente suma un hilo más para su canal TCP de comandos.
`threading.Lock` (`registry_lock`) protege `nodes_registry` — toda escritura pasa
por la sección crítica; no es decorativo. Los hilos son `daemon=True`; `is_running`
es la bandera de apagado y `stop()` cierra ambos sockets.

`gui_monitor.py` es un cliente **adicional**, no reemplaza a `admin_client.py` ni a
los agentes. Habla el mismo NETMON/1.0 por TCP y desde su pestaña "Demo" levanta
servidor + N agentes como procesos hijo. El gateway, la web y la móvil son **clientes**:
sin servidor corriendo muestran "sin conexión".

---

## 📜 Protocolo NETMON/1.0

Texto plano, delimitador `|`, framing por `\n`, encoding UTF-8. Constantes en
`common/protocol.py` (`BUFFER_SIZE=4096`, `MAX_FRAME_SIZE=8192`, puertos por defecto).
**No hardcodear** buffers ni encodings: importarlos de ahí.

| Dirección | Formato |
| --- | --- |
| UDP telemetría | `MON\|<ID_NODO>\|<IP>\|<CPU>\|<RAM>\|<DISK>\|<STATUS>[\|<PUERTO_CMD>]` |
| UDP descubrimiento | `SRVREQ\|<NODE_ID>` → `SRVINFO\|<IP_SRV>\|<UDP>\|<TCP>` |
| TCP solicitud | `CMD\|<ACCION>\|<PARAM>\|...` |
| TCP respuesta | `RES\|<OK\|ERR>\|<PAYLOAD_O_CODIGO>\|<DETALLE>` |
| TCP servidor→agente (EXEC) | `EXECCMD\|<COMANDO>` |

Acciones TCP: `PING` (sin auth), `AUTH`, `GET_NODES`, `EXEC`.
Credenciales (en `server.py`): `admin`/`admin123`, `operador`/`operador123`.

**El 8º campo `PUERTO_CMD` de `MON` es opcional**: el puerto TCP donde el agente
escucha `EXECCMD`. `parse_udp_telemetry` acepta 7 u 8 campos y valida: cabecera
`MON`, CPU/RAM/Disco parseables como float y en rango `[0,100]`, y si viene el 8º,
que sea puerto `1..65535`. Si algo falla lanza `ValueError`; el servidor lo captura,
loguea y **no cierra la conexión** (requisito RF07).

**El campo `<IP>` que viaja en la trama se descarta**: el servidor lo pisa con la
IP fuente real del `recvfrom()`. El agente **no envía timestamp**; el servidor usa
el suyo al recibir, así un reloj desfasado no rompe el watchdog.

El payload de `GET_NODES` usa `;` entre nodos y `:` entre campos
(`NODES_COUNT:2;NODO_01:IP:STATUS:CPU=x:RAM=y:DISK=z:LAST=<seg>`), **no** `|`
(porque `|` ya separa los campos de la respuesta). Mezclarlos rompe el parseo.
`GET_NODES` **ignora su parámetro** (el `ALL` es decorativo).

Códigos de error: `ERR_100` malformado · `ERR_101` no autenticado ·
`ERR_102` nodo inexistente/OFFLINE · `ERR_103` comando desconocido ·
`ERR_104` nodo inalcanzable / comando no soportado por el agente ·
`ERR_500` interno (definido en `protocol.py`, **nunca emitido**).
Ningún error cierra la conexión TCP.

### EXEC real (extremo a extremo)
Único comando que sale del servidor hacia otro proceso. Cadena cuando el admin
manda `CMD|EXEC|NODO_01|DIAGNOSTIC`:
1. Busca `NODO_01`; si no existe o está OFFLINE → `ERR_102`.
2. Toma su `cmd_port`; si nunca reportó puerto de comandos → `ERR_104`.
3. Abre un TCP **nuevo** a `(ip, cmd_port)` del agente (timeout 3 s). Si no conecta → `ERR_104`.
4. Envía `EXECCMD|<COMANDO>` y espera con `TcpFrameReader`.
5. El agente valida contra `COMANDOS_PERMITIDOS = {RESTART_SERVICE, DIAGNOSTIC, CLEAR_LOGS}`,
   lo ejecuta (simulado, resultado textual), lo registra en `agent/historial_comandos.log`
   y responde `RES|OK|<COMANDO>|<resultado>`. Cualquier otro comando → `ERR_104`.
6. El servidor reenvía `RES|OK|EXEC_SUCCESS|<resultado>`.

Cada EXEC abre y cierra su propio socket; no hay canal persistente servidor→agente.

### Framing TCP
TCP es un flujo de bytes. `TcpFrameReader` (en `common/protocol.py`) acumula hasta
`\n`: separa tramas partidas y varias pegadas en un segmento. Tope `MAX_FRAME_SIZE`
(8 KB): si crece sin `\n`, descarta y responde `ERR_100`. Lo usan servidor, cliente
y agente. La GUI tiene su propio `_leer_linea()` equivalente. **No reintroducir un
`recv()` único sin acumulador.**

---

## 🧭 Comportamiento en tiempo de ejecución (claves)

- **Arranque del servidor:** UDP primero (bind antes de lanzar hilos, con `SO_REUSEADDR`),
  luego watchdog, luego TCP `listen(5)`, y el hilo principal entra en `accept()`.
  Puerto ocupado → detecta `EADDRINUSE`, imprime mensaje claro y sale con código 1.
- **Estado del nodo:** `OK`/`WARNING` los decide el **agente** (`WARNING` si `cpu>80`
  **o** `ram>85`; el disco NO participa del umbral). El **servidor** solo añade `OFFLINE`.
- **Watchdog:** corre cada 5 s, umbral 15 s → un nodo muerto aparece OFFLINE entre
  **15 y 20 s** después de su último paquete. Recuperación automática sin handshake:
  al llegar un paquete, el listener UDP reescribe la entrada. Tras `offline_purge_seconds`
  (120 s, 3er argv) lo **purga** para que `nodes_registry` no crezca.
- **Sesión TCP:** el flag `is_authenticated` vive en el hilo del cliente, no es
  compartido; dos admins no se pisan. `PING` y `AUTH` se evalúan antes del filtro de auth.
- **EXEC_500 nunca ocurre;** las alertas push al admin **no están implementadas**
  (el watchdog solo loguea en la consola del servidor — ver "Pendiente").

---

## 🔌 Auto-unión de nodos (implementado)

- **Descubrimiento por broadcast (SRVREQ/SRVINFO):** `common/protocol.py` define los
  headers y helpers (`build_srv_request`, `parse_srv_request`, `build_srv_info`,
  `parse_srv_info`, `es_trama_descubrimiento`). El servidor responde por unicast en
  `_responder_descubrimiento`, invocado dentro de `_udp_listener_loop` **antes** de
  parsear telemetría. `_ip_hacia()` obtiene la IP local hacia el destino.
- **Agente sin IP fija:** `--silent` (pythonw.exe no tiene stdout/stderr → se redirigen
  con `_SalidaNula`), `leer_config` lee `agent/config.ini`, y `descubrir_servidor()`
  emite SRVREQ cada 2 s hasta recibir SRVINFO; redescubre cada 30 s. Si hay IP
  configurada la usa directo.
- **Arranque oculto:** `scripts/instalar_agente.sh`/`.bat` (+ desinstaladores) crean
  el acceso directo de arranque (Inicio de Windows / `~/.config/autostart` XDG), abren
  la regla de firewall del canal EXEC (TCP 5002) si hay admin/root, y arrancan el agente
  oculto (pythonw.exe / nohup). `agent/agente.log` con rotación a 512 KB.
- **Control manual sin terminal:** `scripts/agent/agent_control.py` es una mini-GUI con
  Iniciar/Detener/Estado/Abrir log; `scripts/agent/crear_accesos.sh`/`.bat` dejan el
  acceso directo "SDMR Control Agente" en el Escritorio.

---

## 📂 Dónde tocar las cosas

- **Cualquier cambio al protocolo** se hace en `common/protocol.py` y se refleja en
  los tres consumidores (server, agent, client) a la vez. Si afecta a web/móvil,
  también en `web/src/lib/netmon.js` y `mobile/netmon.js`.
- **Ayuda de la GUI** (pestañas "Instrucciones de uso" y "Conceptos TCP/UDP") se edita
  en `client/contenido_ayuda.py`, **nunca** dentro de `gui_monitor.py`. Los textos de
  `CONCEPTOS` son citas literales de Kurose: **no** parafrasearlos ni "mejorarlos".
- Cada entrypoint empieza con
  `sys.path.append(os.path.join(os.path.dirname(__file__), ".."))` — es lo que permite
  `from common.protocol import ...` al correr `python server/server.py` desde la raíz.
- Los entrypoints leen puertos de `sys.argv` con fallback a las constantes de `protocol.py`.
- **Extras aislados:** `extras/network_discovery.py` (descubrimiento LAN) y
  `extras/lan_scan_service.py` (servicio HTTP :8090 con CORS). **No** usarlos desde
  server/agent/common; si se retiran, el SDMR queda intacto.
- Estilo: docstrings largos en español con bloques `====` que explican el **porqué**,
  no el qué. Preferir editar archivos existentes.

---

## ▶️ Comandos

```bash
# Core (orden de oro: SERVIDOR primero, clientes después)
python server/server.py [udp_port] [tcp_port] [segundos_purga_offline]      # def. 5000 5001 120
python agent/agent.py [ID_NODO] [IP_SERVIDOR] [PUERTO_UDP] [PUERTO_CMD_TCP]  # flags: --silent --config --id --ip --udp --cmd --intervalo
python client/admin_client.py <IP_SERVIDOR> [PUERTO_TCP]
python client/gui_monitor.py [--demo] [--agentes N] [--udp P] [--tcp P] [--host IP]

# Gateway WS + web (solo si se usa navegador o móvil)
python server/gateway.py 5003 127.0.0.1 5001 --serve-web   # WS :5003 -> TCP :5001, publica web en :5173

# Diagnóstico y pruebas
python tools/verificar_red.py <IP_SERVIDOR> 5000 5001 5003  # esperar 3/3 OK antes de abrir clientes
python tools/test_system.py                                 # 8 pruebas del TP + EXEC, no interactivo, exit 0 si pasa

# Lanzadores de un comando
./scripts/instalar.sh   # Linux: crea comando global 'sdmr' (+ tkinter/psutil) una vez
sdmr                    # Linux: abre dashboard + servidor + agentes en modo demo
./scripts/iniciar_todo.sh   # Linux TODO-EN-UNO: server + gateway + web + 2 agentes + verificación
```

Firewall (una vez por red): UDP 5000, TCP 5001 (comandos), 5002/5004 (EXEC por agente,
evitar 5003), 5003 (gateway WS), 5173 (web), 8081 (Expo móvil).
Wireshark para la defensa: `tcp.port == 5001`, `udp.port == 5000`, `tcp.port == 5002` (EXECCMD).

---

## 🐛 Bugs ya corregidos (NO reintroducir)

1. **Encuadrado TCP:** server y `admin_client.py` usan `TcpFrameReader`; soporta trama
   partida y varias en un segmento. `test_system.py` prueba ambos casos.
2. **`send_malformed_test` no cuelga:** acepta `sub_opt` para modo no interactivo.
3. **`EXEC` es real** server→agente por TCP; lista blanca y `ERR_104` si no hay canal.
4. **Watchdog purga** los OFFLINE tras `offline_purge_seconds`; el registro no crece.
5. **Puerto ocupado:** server sale con `EADDRINUSE` claro; la demo de la GUI avanza al
   siguiente puerto libre y da a cada agente un puerto EXEC distinto.
6. **Broadcast:** `255.255.255.255` no vuelve a procesos locales → se agrega `127.0.0.1`
   a los destinos de descubrimiento. pythonw.exe stdout=None manejado con `_SalidaNula`.

---

## 📌 Pendiente / discrepancias conocidas (decirlas antes de que las pregunten)

- **Alertas push al admin NO implementadas** (`propuesta.md` §1): al pasar a OFFLINE el
  servidor solo loguea en su consola; un cliente conectado no se entera salvo que haga `GET_NODES`.
- **`propuesta.md` documenta `GET_NODES` con `|` y un `<TOKEN>` de auth** que el código
  nunca emite. El código usa `;`/`:` y no hay token. El README refleja el código real.

Lo que sí es defendible: concurrencia multihilo con exclusión mutua, detección de
inactividad con purga, framing TCP, EXEC remoto real, validación estricta y tolerancia
a errores sin colapso (RF07).

---

## 🧹 Higiene del repo

- `.gitignore` cubre `__pycache__/`, `*.pyc`, `*.log`, `agent/config.ini`,
  `agent/historial_comandos.log`. Hay `.pyc` viejos aún versionados: limpiar con
  `git rm -r --cached` si se pide.
- Binarios pesados versionados: PDF de Kurose (~12.6 MB) y `Capitulo2.v2.ppt` (~2.6 MB).
  **No versionar PDFs nuevos.**
- `LICENSE` (MIT) coincide con el badge del README. No hay linter/formateador configurado.

> Nota: en `.opencode/skills/` existen dos skills hermanas más extensas
> (`sdmr-monitoreo` de contexto y `sdmr-funcionamiento` de runtime) usadas por OpenCode;
> esta skill de Claude Code las consolida. Mantenerlas en sync si se cambia el protocolo.
