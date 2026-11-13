# SDMR Centro de Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un panel web local (stdlib) que inicia/detiene/monitorea todos los servicios del stack SDMR, con el tema visual de la web, abierto por un acceso directo en Linux y Windows.

**Architecture:** Mini-servicio `http.server` que escucha SOLO en `127.0.0.1:7070`. Un `GestorProcesos` guarda los `subprocess.Popen` que lanza y redirige su salida a logs; el estado se deriva de si el proceso vive o si su puerto escucha. El handler HTTP expone estado/iniciar/detener/log en JSON y sirve una página HTML (archivo aparte) con el tema NOC de la web, que hace polling cada ~2 s.

**Tech Stack:** Python 3 stdlib (`http.server`, `subprocess`, `socket`, `json`), HTML/CSS/JS vanilla (tokens de `web/src/styles.css`), lanzadores bash + batch.

**Spec:** `docs/superpowers/specs/2026-11-13-centro-control-design.md`

## Global Constraints

- Solo stdlib de Python en el servicio de control; **sin frameworks** (ni Flask/FastAPI).
- El servidor HTTP escucha **exclusivamente en `127.0.0.1`**, nunca `0.0.0.0`.
- Herramienta aislada en `scripts/`; no importa ni modifica `server/`, `agent/`, `client/`, `common/`.
- Arranque de procesos con `sys.executable`; en Windows, grupo de proceso nuevo (`CREATE_NEW_PROCESS_GROUP`) para poder detener.
- Textos y comentarios en español (convención del repo).
- Puerto EXEC de agentes: 5002, 5004, 5006… (saltear 5003, que es del gateway).

## Review Focus

- **Puerto 7070 ocupado al arrancar:** el panel debe avisar con un mensaje claro y salir, no reventar con traceback. → Task 2.
- **`web/dist` no existe:** el servicio "web" no debe tirar excepción; su estado debe quedar "parado" y la UI mostrar la pista de `npm run build`. → Task 1 (estado) y Task 3 (UI).
- **Detener un servicio ya detenido / iniciar uno ya corriendo:** idempotente, sin excepción. → Task 1.
- **Proceso que muere solo (p. ej. servidor con puerto ocupado):** el estado debe reflejar "parado" en el siguiente poll (no quedar "corriendo" por un Popen zombi). → Task 1.
- **`Apagar TODO` al cerrar:** detiene todos los procesos hijos lanzados, incluidos los N agentes. → Task 1.

---

### Task 1: Núcleo de gestión de servicios

**Files:**
- Create: `scripts/centro_control.py` (solo la parte lógica en esta task: registro + helpers + `GestorProcesos`)
- Test: `tools/test_centro_control.py`

**Interfaces:**
- Consumes: nada (stdlib).
- Produces:
  - `SERVICIOS: dict[str, dict]` — claves `servidor`, `gateway`, `web`, `escaneo`, `agentes`; cada valor con `nombre`, `icono`, `puerto` (int o None).
  - `puerto_escuchando(puerto: int, host: str = "127.0.0.1") -> bool`
  - `tail_log(ruta: str, n: int = 200) -> str`
  - `comando_servicio(clave: str, raiz: str, indice: int = 0) -> list[str]` — arma el argv (para `agentes`, `indice` define ID `NODO_0i` y puerto cmd `5002 + indice*2`).
  - `class GestorProcesos`: `iniciar(clave, n=2)`, `detener(clave)`, `estado() -> dict[str, dict]` (cada uno `{corriendo: bool, pids: list[int], puerto_ok: bool}`), `apagar_todo()`, `encender_todo(n_agentes=2)`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/test_centro_control.py
import os, socket, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import centro_control as cc

def test_puerto_escuchando_detecta_abierto_y_cerrado():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    puerto = s.getsockname()[1]
    assert cc.puerto_escuchando(puerto) is True
    s.close()
    # un puerto que nadie abrió
    assert cc.puerto_escuchando(1) is False

def test_tail_log_devuelve_ultimas_lineas():
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("\n".join(f"linea{i}" for i in range(500)))
        ruta = f.name
    out = cc.tail_log(ruta, 10)
    assert "linea499" in out and "linea490" in out and "linea489" not in out

def test_comando_agente_usa_id_y_puerto_cmd_distintos():
    cmd0 = cc.comando_servicio("agentes", "/proj", 0)
    cmd1 = cc.comando_servicio("agentes", "/proj", 1)
    assert "NODO_01" in cmd0 and "5002" in cmd0
    assert "NODO_02" in cmd1 and "5004" in cmd1
    assert "5003" not in cmd1  # no pisa el gateway

def test_estado_tiene_todas_las_claves_y_forma():
    g = cc.GestorProcesos("/proj")
    est = g.estado()
    assert set(est.keys()) == {"servidor", "gateway", "web", "escaneo", "agentes"}
    for v in est.values():
        assert set(v.keys()) >= {"corriendo", "pids", "puerto_ok"}

def test_detener_servicio_no_iniciado_es_idempotente():
    g = cc.GestorProcesos("/proj")
    g.detener("servidor")  # no debe lanzar excepción
    assert g.estado()["servidor"]["corriendo"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/test_centro_control.py -v` (o `python3 tools/test_centro_control.py` si no hay pytest)
Expected: FAIL — `scripts.centro_control` no existe / atributos no definidos.

- [ ] **Step 3: Implement the logic in `scripts/centro_control.py`**

Definir `SERVICIOS`, los helpers y `GestorProcesos` con las firmas del bloque Interfaces. Notas que el test no fija:
- `puerto_escuchando`: `socket.create_connection((host, puerto), timeout=0.3)` → True; `OSError` → False.
- `GestorProcesos` guarda `self._procs: dict[str, list[subprocess.Popen]]` y la raíz del proyecto. `corriendo` = hay Popen vivo (`poll() is None`) **o** `puerto_ok`. `puerto_ok` se evalúa con `puerto_escuchando` (None → False). Al detener: `terminate()`, esperar ~2 s, `kill()` si sigue vivo; limpiar la lista. Logs a `scripts/.control_logs/<clave>.log` (crear dir). `encender_todo` llama a `iniciar` de cada servicio (agentes con `n`); `apagar_todo` detiene todos.
- Añadir `if __name__ == "__main__":` mínimo que importe la parte HTTP (se completa en Task 2) — por ahora puede quedar un `pass` o un comentario; no romper el import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/test_centro_control.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/centro_control.py tools/test_centro_control.py
git commit -m "feat(control): nucleo de gestion de servicios del Centro de Control"
```

---

### Task 2: Servidor HTTP + endpoints

**Files:**
- Modify: `scripts/centro_control.py` (añadir handler y `main`)

**Interfaces:**
- Consumes: `GestorProcesos`, `SERVICIOS`, `tail_log` de Task 1.
- Produces: `main(puerto: int = 7070)` que levanta `ThreadingHTTPServer` en `127.0.0.1`. Endpoints: `GET /estado`, `POST /iniciar?svc=&n=`, `POST /detener?svc=`, `POST /encender-todo?n=`, `POST /apagar-todo`, `GET /log?svc=`, `GET /` (sirve `scripts/centro_control.html`).

- [ ] **Step 1: Implement handler + main**

Un `BaseHTTPRequestHandler` con un `GestorProcesos` compartido a nivel módulo. `do_GET`/`do_POST` enrutan por `urlparse(path)`. Respuestas JSON con helper `_json(codigo, payload)`. `/` lee y sirve el HTML (si falta el archivo → 500 con texto claro). `main` imprime banner y hace `serve_forever`; si el bind falla por puerto ocupado (`OSError`/`EADDRINUSE`) → mensaje claro y `sys.exit(1)`. Bindear SIEMPRE a `127.0.0.1`.

- [ ] **Step 2: Verify — arranca y responde estado**

Run:
```bash
python3 scripts/centro_control.py & sleep 2
curl -s http://127.0.0.1:7070/estado | python3 -m json.tool | head -20
curl -s -X POST "http://127.0.0.1:7070/iniciar?svc=escaneo" ; echo
sleep 2; curl -s http://127.0.0.1:7070/estado | python3 -m json.tool | grep -A3 escaneo
curl -s -X POST http://127.0.0.1:7070/apagar-todo ; echo
kill %1 2>/dev/null
```
Expected: `/estado` devuelve JSON con las 5 claves; tras iniciar `escaneo`, su `corriendo` pasa a `true`; `apagar-todo` lo detiene.

- [ ] **Step 3: Verify — puerto ocupado da mensaje claro**

Run: levantar dos instancias; la segunda debe imprimir el aviso de puerto ocupado y salir con código 1 (no traceback).

- [ ] **Step 4: Commit**

```bash
git add scripts/centro_control.py
git commit -m "feat(control): servidor HTTP local y endpoints de control"
```

---

### Task 3: Página HTML con el tema de la web

**Files:**
- Create: `scripts/centro_control.html`

**Interfaces:**
- Consumes: endpoints de Task 2 (`fetch`).
- Produces: la UI (no la consume nadie más).

- [ ] **Step 1: Build the page**

HTML+CSS+JS vanilla en un solo archivo. Copiar los tokens `:root` y el estilo de `.card/.badge/.btn/.topbar/.dot` de `web/src/styles.css` (mismo tema NOC). Estructura: topbar "SDMR · Centro de Control" con luz global; una tarjeta por servicio (ícono, nombre, luz de estado, botones Iniciar/Detener/Log); control de agentes `[– N +]`; barra inferior con **⚡ Encender TODO** / **⛔ Apagar TODO**; un panel/modal para mostrar el log. JS: `fetch('/estado')` cada 2 s y pinta luces (verde=corriendo, gris=parado); botones hacen POST y refrescan; "web" parado muestra pista `npm run build`. Sin librerías externas (ni CDNs).

- [ ] **Step 2: Verify — se ve y controla**

Run: con el panel levantado, `xdg-open http://127.0.0.1:7070` (o abrir a mano). Comprobar: cargan las tarjetas con el tema oscuro/gradiente; iniciar/detener un servicio cambia la luz en ≤2 s; el botón Log muestra contenido. (Si hay herramienta de navegador, capturar screenshot; si no, verificación visual manual.)

- [ ] **Step 3: Commit**

```bash
git add scripts/centro_control.html
git commit -m "feat(control): pagina del Centro de Control con el tema de la web"
```

---

### Task 4: Lanzadores y accesos directos (Linux + Windows)

**Files:**
- Create: `scripts/centro_control.sh`, `scripts/centro_control.bat`
- Create: `scripts/crear_acceso_control.sh`, `scripts/crear_acceso_control.bat`

**Interfaces:**
- Consumes: `scripts/centro_control.py`.
- Produces: punto de entrada de un click + creadores de icono.

- [ ] **Step 1: Write the launchers**

- `centro_control.sh`: resuelve la raíz (patrón de `scripts/sdmr`, incl. symlink), `PY="${PYTHON:-python3}"`, arranca el panel en segundo plano y abre el navegador con `xdg-open http://127.0.0.1:7070`.
- `centro_control.bat`: arranca con `pythonw` (o `python`) y abre con `start http://127.0.0.1:7070`.
- `crear_acceso_control.sh`: genera `~/.local/share/applications/sdmr-control.desktop` (y copia al Escritorio si existe) apuntando a `centro_control.sh`, con nombre "SDMR Centro de Control".
- `crear_acceso_control.bat`: genera `SDMR Centro de Control.lnk` en el Escritorio (mismo patrón PowerShell que `crear_acceso_directo.bat`) apuntando a `centro_control.bat`.
- `chmod +x` a los `.sh`.

- [ ] **Step 2: Verify — sintaxis y arranque**

Run:
```bash
bash -n scripts/centro_control.sh && bash -n scripts/crear_acceso_control.sh && echo "sintaxis OK"
chmod +x scripts/centro_control.sh scripts/crear_acceso_control.sh
```
Expected: "sintaxis OK". (Los `.bat` se revisan por contenido; no corren en Linux.)

- [ ] **Step 3: Commit**

```bash
git add scripts/centro_control.sh scripts/centro_control.bat scripts/crear_acceso_control.sh scripts/crear_acceso_control.bat
git commit -m "feat(control): lanzadores y accesos directos del Centro de Control (Linux y Windows)"
```

---

### Task 5: Documentación breve

**Files:**
- Modify: `README.md` (sección de lanzadores / comandos)

- [ ] **Step 1:** Añadir una línea que mencione el Centro de Control: cómo abrirlo (acceso directo o `./scripts/centro_control.sh`), qué hace (prende/apaga todo el stack, local, 127.0.0.1:7070), y que es una herramienta aislada.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: documentar el Centro de Control SDMR"
```
