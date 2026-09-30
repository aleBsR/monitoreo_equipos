---
name: sdmr-monitoreo
description: Contexto del proyecto SDMR (Sistema Distribuido de Monitoreo en Red) - TPI de Programación de Redes con Sockets en Python. Úsala al trabajar en server/server.py, agent/agent.py, client/admin_client.py, common/protocol.py, el protocolo NETMON/1.0, el test_system.py, o cuando se mencione SDMR, NETMON, monitoreo de equipos, nodos, telemetría UDP, heartbeat, watchdog o EXEC remoto.
---

# SDMR — Sistema Distribuido de Monitoreo en Red

Trabajo práctico integrador para la asignatura **Programación de Redes con Sockets
(Optativa III - LAS)**. Python 3 con sockets nativos (`socket`, `threading`).
Educational use, network lab. Repo: `github.com/aleBsR/monitoreo_equipos`.

Skill de **contexto**: qué es el proyecto, dónde tocar cada cosa, y qué bugs
no reintroducir. Para entender **cómo se ejecuta en tiempo real** (hilos,
recorrido de un dato, máquina de estados, tabla de errores) ver la skill hermana
`sdmr-funcionamiento`.

## Restricción dura del proyecto

La cátedra evalúa el uso **explícito** de la API de sockets y el parseo manual
del protocolo de aplicación. **No** introducir Django, FastAPI, REST, asyncio,
selectors, ni ningún framework que oculte la capa de transporte. Se menciona
en `propuesta.md` §2.1 que usar un framework "podría incidir negativamente en la
evaluación de RF03, RF04 y RF06".

Dependencias externas permitidas y ya declaradas: `psutil` (métricas reales) y
`rich` (consola). Son opcionales — el agente tiene fallback a simulación.

## Arquitectura

```
Servidor central (server/server.py)
  ├─ UDP :5000  <- telemetría/heartbeat de agentes   (sin conexión, 3 s)
  ├─ TCP :5001  <- comandos de admins               (conexión, confiable)
  └─ hilo watchdog  -> marca OFFLINE a los 15 s de inactividad

agent/agent.py      -> mide CPU/RAM/Disco, envía MON|... por UDP cada 3 s
client/admin_client.py -> CLI admin: PING, AUTH, GET_NODES, EXEC
client/gui_monitor.py  -> dashboard Tkinter (3 pestañas: Nodos, Demo, Tráfico)
common/protocol.py  -> encode/decode/parse compartido por los tres
```

`gui_monitor.py` es un cliente **adicional**, no un reemplazo: habla el mismo
NETMON/1.0 por TCP. Levanta servidor + N agentes como procesos hijo desde la
pestaña "Demo". Restricciones propias de Tkinter:

- Los widgets se actualizan **solo** desde el hilo principal vía `after()`.
  Tkinter no es thread-safe. Los hilos solo encolan texto en una `queue.Queue`.
- `ttk.Entry` **no tiene `.set()`** — hay que `delete(0, "end")` + `insert(0, v)`.
- `ttk.Label` tampoco: usar un `tk.StringVar` con `textvariable=`.
- `time.time()` devuelve float: para `%H:%M:%S` usar
  `time.strftime("%H:%M:%S", time.localtime(ts))`.
- Los procesos hijo se lanzan con `CREATE_NO_WINDOW` y `-u` (sin buffer) para
  que no abran consolas ni retrasen la salida.
- `_leer_linea()` en la GUI **sí** acumula hasta `\n` (corrige el bug del punto 1
  de abajo). No reintroducir un `recv()` único aquí.
- Los hijos de `popen` no se cierran solos: sin `try/finally` en los scripts de
  prueba quedan servidores huérfanos ocupando el puerto.

Cada agente es un proceso aparte. El servidor usa un hilo dedicado por cliente
TCP y un `threading.Lock` sobre `nodes_registry` para thread-safety.

## Protocolo NETMON/1.0

Texto plano, delimitador `|`, framing por `\n`, encoding UTF-8.

| Dirección | Formato |
| --- | --- |
| UDP telemetría | `MON\|<ID_NODO>\|<IP>\|<CPU>\|<RAM>\|<DISK>\|<STATUS>` |
| TCP solicitud | `CMD\|<ACCION>\|<PARAM>\|...` |
| TCP respuesta | `RES\|<OK\|ERR>\|<PAYLOAD_O_CODIGO>\|<DETALLE>` |

Acciones TCP: `PING` (sin auth), `AUTH`, `GET_NODES`, `EXEC`.

Códigos de error: `ERR_100` malformado · `ERR_101` no autenticado ·
`ERR_102` nodo inexistente/OFFLINE · `ERR_103` comando desconocido ·
`ERR_500` error interno (definido en `protocol.py:50`, nunca emitido).

El payload de `GET_NODES` usa `;` entre nodos y `:` entre campos
(`NODES_COUNT:2;NODO_01:IP:STATUS:CPU=x:RAM=y:DISK=z`), **no** `|`.

Credenciales: `admin`/`admin123`, `operador`/`operador123` (server.py:73).

## Dónde tocar las cosas

- Cualquier cambio al protocolo debe hacerse en `common/protocol.py` y
  reflejarse en los tres consumidores a la vez.
- `sys.path.append(os.path.join(os.path.dirname(__file__), ".."))` al inicio de
  cada entrypoint — es lo que permite `from common.protocol import ...` cuando
  se ejecuta `python server/server.py` desde la raíz.
- Los entrypoints leen puertos de `sys.argv` con fallback a las constantes.
- Los tres entrypoints imprimen en español con `print()`; los comentarios y
  docstrings del código también están en español. Mantener ese idioma.

## Comandos

```bash
python server/server.py [udp_port] [tcp_port]
python agent/agent.py <ID_NODO> <IP_SERVIDOR> [PUERTO_UDP]
python client/admin_client.py <IP_SERVIDOR> [PUERTO_TCP]
python client/gui_monitor.py    # dashboard; usar puertos libres si hay otros
python test_system.py            # integración: 3 agentes + 1 admin
```

Filtros de Wireshark para la defensa: `tcp.port == 5001`, `udp.port == 5000`.

## Bugs conocidos — no reintroducirlos

1. **Encuadrado TCP roto.** `server.py:227` y `admin_client.py:96` hacen un
   único `recv(BUFFER_SIZE)` sin acumular hasta `\n`. Dos comandos en el mismo
   segmento se concatenan; uno fragmentado se parsea truncado. Si se toca el
   transporte, arreglar con un buffer acumulador por conexión.
2. **`test_system.py:72` cuelga.** Llama a `client.send_malformed_test()`, que
   es interactiva (`input()` en `admin_client.py:184`). El test "automatizado"
   del README se bloquea esperando teclado.
3. **`EXEC` es un stub.** `server.py:323` devuelve `EXEC_SUCCESS` sin ejecutar
   nada. El agente no escucha por TCP, aunque `propuesta.md:69` lo exige.
4. **Faltan las alertas al admin** (propuesta §1) — no implementado.
5. **Watchdog no purga nodos** — `nodes_registry` crece sin límite.
6. **`propuesta.md` y `propuesta_tpi.md` son idénticos** (mismo hash). El
   README referencia el segundo; no crear un tercero.
7. **Doc desalineada con el código:** `propuesta.md:98-104` describe respuestas
   con `|` y un `<TOKEN>` de auth que el código no emite. El README sí
   refleja el código real.

## Higiene del repo

- **No existe `.gitignore` y los `__pycache__/*.pyc` están versionados.**
  Crear `.gitignore` con `__pycache__/`, `*.pyc` antes de añadir archivos.
- Hay binarios pesados versionados: el PDF de Kurose (12.6 MB) y
  `Capitulo2.v2.ppt` (2.6 MB). No versionar PDFs nuevos.
- El badge del README enlaza a `LICENSE` (MIT) pero **el archivo no existe**.
- `README.md:9` tiene texto de una prueba de commit: "Estoy probando como
  funciona el commit". Limpiar.
- `requirements.txt` tiene mojibake: dice "mǸtricas" en vez de "métricas".
- No hay linter ni formateador configurado. No agregar dependencias de build.

## Detalles de implementación que conviene respetar

- `parse_udp_telemetry` valida rango `[0, 100]` en CPU/RAM/Disco y lanza
  `ValueError`; el servidor lo captura y **no** cierra la conexión. Ese
  comportamiento de tolerancia es requisito explícito (RF07).
- El agente marca `WARNING` si `cpu > 80` o `ram > 85`; el disco no participa
  del umbral.
- El watchdog corre cada 5 s con timeout de 15 s. Al volver la telemetría, el
  listener UDP sobreescribe la entrada y el nodo se recupera solo.
- Los hilos son todos `daemon=True`; `is_running` es la bandera de apagado y
  `stop()` cierra ambos sockets.

## Al tocar el código

El servidor y el cliente comparten `BUFFER_SIZE` y `ENCODING` desde
`common/protocol.py`. No hardcodear números de búfer ni encodings.
Preferir editar archivos existentes; el estilo es docstrings largos en español
con bloques `====` y comentarios que explican el porqué, no el qué.
