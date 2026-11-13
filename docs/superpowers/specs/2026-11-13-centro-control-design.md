# Diseño — SDMR Centro de Control

**Fecha:** 2026-11-13
**Estado:** propuesto (pendiente de aprobación)

## Intención y por qué

Hoy, para levantar el stack SDMR hay que abrir varias terminales
(`server.py`, `gateway.py`, `lan_scan_service.py`, la web, cada agente). Solo
el dashboard de demo y el agente tienen lanzadores sin terminal; el gateway y el
servicio de escaneo no tienen ninguno. Se quiere **un único punto de entrada,
intuitivo y con el mismo estilo que la web**, para prender/apagar todo el stack
sin tocar la terminal. Sirve para la defensa del TP (mostrar el sistema vivo en
segundos) y para el uso diario.

## Objetivos

- Un **Centro de Control en el navegador** con el tema NOC de la web (tokens de
  `web/src/styles.css`: fondo oscuro, gradiente cian/azul, tarjetas, badges).
- Por cada servicio: botón **Iniciar**, **Detener**, **luz de estado en vivo**
  (corriendo/parado) y ver su **log**.
- Botones globales **Encender TODO** y **Apagar TODO**.
- Agentes de demo con cantidad ajustable (`– N +`).
- Un acceso directo (icono) que lo abre, en **Linux y Windows**.

## No-objetivos

- No reemplaza al dashboard de monitoreo ni al protocolo NETMON/1.0.
- No controla equipos por la red: solo procesos **locales** de esta máquina.
- No gestiona finamente procesos lanzados por fuera (solo los detecta por puerto,
  best-effort).

## Anti-objetivos (qué sería un fracaso aunque "funcione")

- **Que el panel sea accesible desde la LAN.** Ejecuta comandos de arranque de
  procesos; si se expusiera a la red, cualquiera podría lanzar/matar procesos en
  la máquina. **Debe escuchar solo en `127.0.0.1`.**
- Introducir un framework web (Flask/FastAPI). Rompe el espíritu de la cátedra.

## Restricciones

- **Solo stdlib** para el servicio de control: `http.server`, `subprocess`,
  `socket` (igual que `extras/lan_scan_service.py`). Sin frameworks.
- Es una **herramienta de `scripts/`**, aislada del core (`server/`, `agent/`,
  `client/`, `common/`). Si se borra, el SDMR queda intacto.
- Multiplataforma: el arranque de procesos usa `sys.executable`; en Windows,
  grupo de proceso nuevo para poder detener limpio.

## Enfoques considerados

- **A — Centro de Control en el navegador (ELEGIDO).** Mini-servicio local con
  `http.server` que sirve una página con el tema de la web y expone endpoints
  para iniciar/detener/estado/log de cada servicio. Un acceso directo lo abre.
  *Por qué:* es lo único que cumple "intuitivo + mismo estilo que la web", y
  reutiliza el patrón ya probado de `lan_scan_service.py`.
- **B — Panel Tkinter.** Ventana de escritorio con botones (como
  `agent_control.py`, extendido a todo). *Descartado:* Tkinter no puede verse
  como la web (sin gradientes, tarjetas redondeadas ni tipografía); incumple el
  requisito explícito de estilo.
- **C — Menú en terminal / mejorar `iniciar_todo`.** *Descartado:* no es un
  botón ni tiene estilo; es justo lo que se quiere evitar.

## Cómo se construye (decisiones tomadas)

### Servicios gestionados
| Clave | Comando lanzado | Puerto |
|---|---|---|
| `servidor` | `python server/server.py 5000 5001 120` | UDP 5000 / TCP 5001 |
| `gateway` | `python server/gateway.py 5003 127.0.0.1 5001` | TCP 5003 |
| `web` | `python -m http.server 5173 --directory web/dist` | 5173 |
| `escaneo` | `python extras/lan_scan_service.py 8090` | 8090 |
| `agentes` | N × `python agent/agent.py NODO_0i 127.0.0.1 5000 <cmd>` | cmd 5002,5004,5006… (evita 5003) |

- **web**: sirve el build (`web/dist`). Si no existe, el estado muestra "falta
  build" con la pista `cd web && npm run build` (no lo compila solo; mantiene el
  arranque rápido y predecible). *Decisión del constructor.*
- **gateway** se lanza **sin** `--serve-web` para que "web" sea un servicio
  independiente y toggleable por separado.

### Servicio de control — `scripts/centro_control.py`
- `ThreadingHTTPServer` en **`127.0.0.1:7070`** (nunca `0.0.0.0`).
- Endpoints:
  - `GET /` → página HTML (tema embebido, standalone, no depende del build).
  - `GET /estado` → JSON con, por servicio: `corriendo` (bool), `pid`, `puerto_ok`.
  - `POST /iniciar?svc=<clave>[&n=<N>]` · `POST /detener?svc=<clave>`.
  - `POST /encender-todo` · `POST /apagar-todo`.
  - `GET /log?svc=<clave>` → últimas ~200 líneas del log del servicio.
- **Gestión de procesos:** dict `clave → Popen` (lista para agentes). La salida
  de cada servicio se redirige a `scripts/.control_logs/<clave>.log`. Detener =
  `terminate()` y, si no muere, `kill()`. Los agentes se guardan como lista.
- **Estado robusto:** un servicio figura "corriendo" si su `Popen` vive **o** su
  puerto está escuchando (detecta también los que se iniciaron por fuera).
- El front hace *polling* de `/estado` cada ~2 s y pinta las luces.

### Puntos de entrada (el "un solo click")
- Linux: `scripts/centro_control.sh` (arranca el servicio y abre el navegador con
  `xdg-open`). `scripts/crear_acceso_control.sh` deja el icono **"SDMR Centro de
  Control"** en el menú/escritorio (`.desktop`).
- Windows: `scripts/centro_control.bat` (arranca con `pythonw` y abre el
  navegador con `start`). `scripts/crear_acceso_control.bat` deja el `.lnk` en el
  Escritorio (mismo patrón que `crear_acceso_directo.bat`).

## Lo que queda a criterio del constructor

- Puerto del panel (7070 propuesto; cambiar si está ocupado).
- Estética fina (orden de tarjetas, textos de ayuda), respetando los tokens.
- Detalle del tail de logs y refresco.
