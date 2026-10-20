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

Dependencias externas permitidas y ya declaradas: `psutil` (métricas reales,
opcional — el agente tiene fallback a simulación). `rich` se quitó por no usarse.

## Arquitectura

```
Servidor central (server/server.py)
  ├─ UDP :5000  <- telemetría/heartbeat de agentes   (sin conexión, 3 s)
  ├─ TCP :5001  <- comandos de admins               (conexión, confiable)
  └─ hilo watchdog  -> marca OFFLINE a los 15 s y PURGA a los 120 s

agent/agent.py      -> mide CPU/RAM/Disco, envía MON|... por UDP cada 3 s
                       + canal TCP de comandos EXEC (puerto 5002+, argv[4])
client/admin_client.py -> CLI admin: PING, AUTH, GET_NODES, EXEC
client/gui_monitor.py  -> dashboard Tkinter (5 pestañas: Nodos, Demo, Tráfico,
                          Instrucciones de uso, Conceptos TCP/UDP)
client/contenido_ayuda.py -> texto plano de las 2 pestañas de ayuda
                             (INSTRUCCIONES y CONCEPTOS; los conceptos son
                             citas literales de Kurose 5.ª ed. con cap./pág.)
common/protocol.py  -> encode/decode/parse + TcpFrameReader compartido
sdmr / instalar.sh / *.bat -> lanzadores (un comando abre todo)
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
- `_leer_linea()` en la GUI acumula hasta `\n`. El servidor y `admin_client.py`
  usan `TcpFrameReader` (en `protocol.py`) para lo mismo. No reintroducir un
  `recv()` único sin acumulador.
- Los hijos de `popen` no se cierran solos: sin `try/finally` en los scripts de
  prueba quedan servidores huérfanos ocupando el puerto.

Cada agente es un proceso aparte. El servidor usa un hilo dedicado por cliente
TCP y un `threading.Lock` sobre `nodes_registry` para thread-safety.

## Protocolo NETMON/1.0

Texto plano, delimitador `|`, framing por `\n`, encoding UTF-8.

| Dirección | Formato |
| --- | --- |
| UDP telemetría | `MON\|<ID_NODO>\|<IP>\|<CPU>\|<RAM>\|<DISK>\|<STATUS>[\|<PUERTO_CMD>]` |
| TCP solicitud | `CMD\|<ACCION>\|<PARAM>\|...` |
| TCP respuesta | `RES\|<OK\|ERR>\|<PAYLOAD_O_CODIGO>\|<DETALLE>` |
| TCP servidor->agente (EXEC) | `EXECCMD\|<COMANDO>` |
Acciones TCP: `PING` (sin auth), `AUTH`, `GET_NODES`, `EXEC`.
Descubrimiento UDP: `SRVREQ|<NODE_ID>` -> `SRVINFO|<NODE_ID>|<IP>|<UDP>|<TCP>`.


puerto TCP donde el agente escucha `EXECCMD`. `parse_udp_telemetry` valida ambos.

Códigos de error: `ERR_100` malformado · `ERR_101` no autenticado ·
`ERR_102` nodo inexistente/OFFLINE · `ERR_103` comando desconocido ·
`ERR_104` nodo inalcanzable / comando no soportado por el agente ·
`ERR_500` error interno (definido en `protocol.py`, nunca emitido).

El payload de `GET_NODES` usa `;` entre nodos y `:` entre campos
(`NODES_COUNT:2;NODO_01:IP:STATUS:CPU=x:RAM=y:DISK=z`), **no** `|`.

Credenciales: `admin`/`admin123`, `operador`/`operador123` (server.py).

### EXEC real (extremo a extremo)
El servidor conecta por TCP al `PUERTO_CMD` del nodo (timeout 3 s), envía
`EXECCMD|<COMANDO>` y devuelve la respuesta real del agente. Comandos permitidos
en el agente (`agent/agent.py`): `RESTART_SERVICE`, `DIAGNOSTIC`, `CLEAR_LOGS`;
cualquier otro -> `ERR_104` y queda rechazado. Cada orden se registra en
`agent/historial_comandos.log` (ignorado por `.gitignore`).

## Dónde tocar las cosas

- Cualquier cambio al protocolo debe hacerse en `common/protocol.py` y
  reflejarse en los tres consumidores a la vez.
- La ayuda de la GUI (pestañas "Instrucciones de uso" y "Conceptos TCP/UDP")
  se edita en `client/contenido_ayuda.py`, nunca dentro de `gui_monitor.py`.
  Los textos de `CONCEPTOS` son citas literales del PDF de Kurose: no
  parafrasearlos ni "mejorarlos". Las pestañas de ayuda no abren sockets.
- `sys.path.append(os.path.join(os.path.dirname(__file__), ".."))` al inicio de
  cada entrypoint — es lo que permite `from common.protocol import ...` cuando
  se ejecuta `python server/server.py` desde la raíz.
- Los entrypoints leen puertos de `sys.argv` con fallback a las constantes.
- Los tres entrypoints imprimen en español con `print()`; los comentarios y
  docstrings del código también están en español. Mantener ese idioma.

## Comandos

```bash
python server/server.py [udp_port] [tcp_port] [segundos_purga_offline]
python agent/agent.py [ID_NODO] [IP_SERVIDOR] [PUERTO_UDP] [PUERTO_CMD_TCP]  # flags: --silent --config --id --ip --udp --cmd --intervalo
python client/admin_client.py <IP_SERVIDOR> [PUERTO_TCP]
python client/gui_monitor.py [--demo] [--agentes N] [--udp P] [--tcp P] [--host IP]

# Lanzadores: un comando abre dashboard + servidor + agentes
./instalar.sh        # Linux: crea el comando global 'sdmr' (+ tkinter/psutil)
sdmr                 # Linux: abre todo en modo demo
iniciar_sdmr.bat     # Windows: doble clic (crear_acceso_directo.bat crea el .lnk)

python test_system.py   # 8 pruebas del TP + EXEC, todo no interactivo
```

Filtros de Wireshark para la defensa: `tcp.port == 5001`, `udp.port == 5000`,
y `tcp.port == 5002` para ver el `EXECCMD` hacia el agente.

## Bugs ya corregidos (no reintroducir)

1. **Encuadrado TCP.** Servidor y `admin_client.py` usan `TcpFrameReader`:
   acumula hasta `\n`, soporta tramas partidas y varias en un segmento.
   `test_system.py` prueba ambos casos.
2. **`send_malformed_test` ya no cuelga el test.** Acepta `sub_opt` para modo
   no interactivo; `test_system.py` corre de punta a punta sin teclado.
3. **`EXEC` es real.** Servidor -> agente por TCP (`EXECCMD`), el agente valida
   contra lista permitida y responde. `ERR_104` si no hay canal o no soporta.
4. **Watchdog purga:** borra los nodos OFFLINE tras `offline_purge_seconds`
   (120 s por defecto, 3er argumento del servidor). `nodes_registry` no crece.
5. **Puerto ocupado:** el servidor detecta `EADDRINUSE` y sale con mensaje
   claro; la demo de la GUI avanza al siguiente puerto libre.

## Auto-union de nodos (implementado)

- **Descubrimiento por broadcast (SRVREQ/SRVINFO):** common/protocol.py
  define SRVREQ_HEADER/SRVINFO_HEADER y los helpers uild_srv_request,
  parse_srv_request, uild_srv_info, parse_srv_info, es_trama_descubrimiento.
  El servidor responde por unicast desde _responder_descubrimiento invocado
  dentro de _udp_listener_loop (antes de parsear telemetria). _ip_hacia()
  obtiene la IP local hacia el destino con socket UDP efimero + connect().
- **Agente sin IP fija:** gent/agent.py acepta --silent (pythonw.exe no
  tiene stdout/stderr: se redirigen con _SalidaNula), leer_config lee
  gent/config.ini, y descubrir_servidor() emite SRVREQ cada 2 s hasta
  recibir SRVINFO; si hay IP configurada la usa directo. Redescubre cada 30 s.
- **Arranque oculto:** scripts/instalar_agente.bat/.sh + desinstaladores
  crean el acceso directo de arranque (carpeta de Inicio / autostart XDG),
  abren la regla de firewall del canal EXEC (TCP 5002) si hay admin/root,
  y arrancan el agente ahora (pythonw.exe / nohup). demo_automatico.bat
  levanta servidor + agentes ocultos.
- **GUI mejorada:** columna "ACTUALIZADO" (parsea LAST=), badge amarillo y
  notificacion sonora/log al detectar un nodo nuevo, boton "Copiar comando para
  clientes" que copia al portapapeles el comando de instalacion con la IP del
  servidor conectado.
- **GET_NODES** ahora agrega :LAST=<segundos> por nodo; clientes web/movil
  tolerantes (parsean LAST opcional).
- **Config local:** gent/config.ini (ignorado por .gitignore) con
  gent/config.example.ini como plantilla.
- **Bugs corregidos relacionados:** pythonw.exe stdout=None; broadcast
  255.255.255.255 no vuelve a procesos locales (se agrega 127.0.0.1 a los
  destinos de descubrimiento).


## Pendiente / no implementado

- **Alertas al admin** (propuesta §1): cuando un nodo pasa a OFFLINE el
  servidor solo lo loguea; no notifica por TCP a los admins conectados.
- `TODO` accesorio: `propuesta.md` describe respuestas con `|` y un `<TOKEN>`
  de auth que el código no emite. El README refleja el código real.

## Higiene del repo

- `.gitignore` ya existe (`__pycache__/`, `*.pyc`, `*.log`). Los `.pyc` viejos
  siguen versionados; limpiar con `git rm -r --cached` si se pide.
- Hay binarios pesados versionados: el PDF de Kurose (12.6 MB) y
  `Capitulo2.v2.ppt` (2.6 MB). No versionar PDFs nuevos.
- `LICENSE` (MIT) ya existe y coincide con el badge del README.
- `requirements.txt` ya está sin mojibake ni `rich` (solo `psutil`).
- No hay linter ni formateador configurado. No agregar dependencias de build.

## Detalles de implementación que conviene respetar

- `parse_udp_telemetry` valida rango `[0, 100]` en CPU/RAM/Disco, acepta 7 u 8
  campos y lanza `ValueError`; el servidor lo captura y **no** cierra la
  conexión. Ese comportamiento de tolerancia es requisito explícito (RF07).
- Si el agente no puede abrir su puerto de comandos (ocupado), sigue enviando
  telemetría con `cmd_port=None`; el servidor responde `ERR_104` en `EXEC`.
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
