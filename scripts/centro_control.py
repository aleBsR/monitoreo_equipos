"""
===============================================================================
SDMR - Centro de Control (herramienta EXTRA, local)
===============================================================================
Panel web local para iniciar / detener / monitorear TODO el stack SDMR sin
abrir varias terminales: servidor, gateway WS, web, servicio de escaneo y los
agentes de demo. Pensado para la defensa del TP (levantar el sistema en
segundos) y el uso diario.

- Solo biblioteca estándar (http.server, subprocess, socket). SIN frameworks.
- Escucha EXCLUSIVAMENTE en 127.0.0.1 (nunca 0.0.0.0): puede lanzar y matar
  procesos, así que exponerlo a la red sería un agujero de seguridad.
- Herramienta aislada: NO importa ni modifica server/ agent/ client/ common/.
  Si se borra scripts/centro_control.*, el SDMR queda intacto.

Uso:
    python scripts/centro_control.py [puerto]     # por defecto 7070
    # luego abrir http://127.0.0.1:7070

La página (scripts/centro_control.html) usa el mismo tema que la web.
===============================================================================
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUTA_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "centro_control.html")

# Catálogo de servicios gestionables. 'puerto' es el TCP que se sondea para
# saber si está vivo (None = no se sondea; los agentes no tienen uno fijo).
SERVICIOS = {
    "servidor": {"nombre": "Servidor central", "icono": "🖥", "puerto": 5001},
    "gateway":  {"nombre": "Gateway WS",       "icono": "🔀", "puerto": 5003},
    "web":      {"nombre": "Web (dashboard)",  "icono": "🌐", "puerto": 5173},
    "escaneo":  {"nombre": "Escaneo de red",   "icono": "📡", "puerto": 8090},
    "agentes":  {"nombre": "Agentes (demo)",   "icono": "🟢", "puerto": None},
}


def puerto_escuchando(puerto: int, host: str = "127.0.0.1") -> bool:
    """True si hay algo aceptando conexiones TCP en (host, puerto)."""
    if not puerto:
        return False
    try:
        with socket.create_connection((host, puerto), timeout=0.3):
            return True
    except OSError:
        return False


def tail_log(ruta: str, n: int = 200) -> str:
    """Últimas `n` líneas de un archivo de log (cadena vacía si no existe)."""
    try:
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()
    except OSError:
        return ""
    return "".join(lineas[-n:])


def comando_servicio(clave: str, raiz: str, indice: int = 0) -> list:
    """
    Arma el argv para lanzar un servicio.

    Para 'agentes', `indice` define el ID (NODO_0i) y el puerto de comandos
    EXEC (5002, 5004, 5006 ... salteando el 5003 del gateway).
    """
    py = sys.executable or "python3"
    if clave == "servidor":
        return [py, "-u", os.path.join(raiz, "server", "server.py"), "5000", "5001", "120"]
    if clave == "gateway":
        return [py, "-u", os.path.join(raiz, "server", "gateway.py"), "5003", "127.0.0.1", "5001"]
    if clave == "web":
        return [py, "-u", "-m", "http.server", "5173", "--directory", os.path.join(raiz, "web", "dist")]
    if clave == "escaneo":
        return [py, "-u", os.path.join(raiz, "extras", "lan_scan_service.py"), "8090"]
    if clave == "agentes":
        node_id = f"NODO_{indice + 1:02d}"
        puerto_cmd = 5002 + indice * 2
        return [py, "-u", os.path.join(raiz, "agent", "agent.py"), node_id, "127.0.0.1", "5000", str(puerto_cmd)]
    raise ValueError(f"Servicio desconocido: {clave}")


class GestorProcesos:
    """
    Lanza y detiene los procesos de los servicios, y deriva su estado.

    Un servicio figura 'corriendo' si tiene un proceso propio vivo O si su
    puerto está escuchando (así detecta también servicios que ya estaban
    levantados por fuera del panel).
    """

    def __init__(self, raiz: str):
        self.raiz = raiz
        self._procs = {clave: [] for clave in SERVICIOS}
        self.dir_logs = os.path.join(raiz, "scripts", ".control_logs")
        # ThreadingHTTPServer atiende cada request en su propio hilo (el poll de
        # /estado se solapa con los clics de iniciar/detener): este lock serializa
        # toda mutación de _procs para no dejar procesos huérfanos. Es RLock
        # porque encender_todo/apagar_todo llaman a iniciar/detener.
        self._lock = threading.RLock()

    def ruta_log(self, clave: str) -> str:
        return os.path.join(self.dir_logs, f"{clave}.log")

    def _web_falta_build(self) -> bool:
        """True si el servicio 'web' no tiene build que servir (web/dist)."""
        return not os.path.isdir(os.path.join(self.raiz, "web", "dist"))

    def _vivos(self, clave: str) -> list:
        """Procesos propios de `clave` que siguen vivos (poda los muertos)."""
        self._procs[clave] = [p for p in self._procs.get(clave, []) if p.poll() is None]
        return self._procs[clave]

    def iniciar(self, clave: str, n: int = 2):
        if clave not in SERVICIOS:
            raise ValueError(f"Servicio desconocido: {clave}")
        with self._lock:
            self._iniciar_bloqueado(clave, n)

    def _iniciar_bloqueado(self, clave: str, n: int):
        cantidad = max(1, n) if clave == "agentes" else 1

        if clave == "agentes":
            # Reconciliar a exactamente `n` agentes: si ya hay esa cantidad,
            # nada; si difiere, se reinician para escalar (el stepper de la UI
            # tiene efecto real).
            if len(self._vivos("agentes")) == cantidad:
                return
            self._detener_bloqueado("agentes")
        elif self._vivos(clave):
            return  # ya corriendo: idempotente, no duplica

        # 'web' sin build: no lanzar un http.server que serviría 404 (quedaría
        # "corriendo" engañando al usuario). Se refleja como falta_build.
        if clave == "web" and self._web_falta_build():
            return

        os.makedirs(self.dir_logs, exist_ok=True)

        logf = open(self.ruta_log(clave), "a", encoding="utf-8", errors="replace")
        logf.write(f"\n===== iniciado {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        logf.flush()

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        procs = []
        for i in range(cantidad):
            cmd = comando_servicio(clave, self.raiz, i)
            try:
                p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                     cwd=self.raiz, **kwargs)
                procs.append(p)
            except OSError as e:
                logf.write(f"[ERROR] no se pudo lanzar {clave}: {e}\n")
                logf.flush()
        logf.close()  # los hijos heredan su propio descriptor; el padre no lo necesita
        self._procs[clave] = procs

    def detener(self, clave: str):
        if clave not in SERVICIOS:
            raise ValueError(f"Servicio desconocido: {clave}")
        with self._lock:
            self._detener_bloqueado(clave)

    def _detener_bloqueado(self, clave: str):
        procs = self._procs.get(clave, [])
        for p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except OSError:
                    pass
        fin = time.time() + 2.0
        for p in procs:
            try:
                p.wait(timeout=max(0.0, fin - time.time()))
            except Exception:  # noqa: BLE001  (TimeoutExpired u otros)
                try:
                    p.kill()
                    p.wait(timeout=1.0)  # cosechar para no dejar zombi
                except Exception:  # noqa: BLE001
                    pass
        self._procs[clave] = []

    def encender_todo(self, n_agentes: int = 2):
        with self._lock:
            # Orden: servidor primero, luego el resto que depende de él
            for clave in ("servidor", "gateway", "web", "escaneo"):
                self._iniciar_bloqueado(clave, 1)
            self._iniciar_bloqueado("agentes", n_agentes)

    def apagar_todo(self):
        with self._lock:
            for clave in SERVICIOS:
                self._detener_bloqueado(clave)

    def estado(self) -> dict:
        with self._lock:
            salida = {}
            for clave, info in SERVICIOS.items():
                vivos = self._vivos(clave)
                puerto = info.get("puerto")
                puerto_ok = puerto_escuchando(puerto) if puerto else False
                entrada = {
                    "nombre": info["nombre"],
                    "icono": info["icono"],
                    "puerto": puerto,
                    "corriendo": bool(vivos) or puerto_ok,
                    "pids": [p.pid for p in vivos],
                    "puerto_ok": puerto_ok,
                }
                if clave == "web":
                    entrada["falta_build"] = self._web_falta_build()
                salida[clave] = entrada
            return salida


# =============================================================================
# SERVIDOR HTTP LOCAL
# =============================================================================
# Un único gestor compartido por todas las peticiones. ThreadingHTTPServer
# atiende en varios hilos, por eso el gestor serializa internamente con un lock.
GESTOR = GestorProcesos(RAIZ)


class Handler(BaseHTTPRequestHandler):
    def _json(self, codigo: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _svc(self, qs: dict) -> str:
        return (qs.get("svc") or [""])[0]

    def _n(self, qs: dict, por_defecto: int = 2) -> int:
        try:
            return max(1, int((qs.get("n") or [por_defecto])[0]))
        except (ValueError, TypeError):
            return por_defecto

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            try:
                with open(RUTA_HTML, "rb") as f:
                    cuerpo = f.read()
            except OSError:
                self.send_error(500, f"No se encontro {RUTA_HTML}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return

        if parsed.path == "/estado":
            self._json(200, {"servicios": GESTOR.estado()})
            return

        if parsed.path == "/log":
            svc = self._svc(qs)
            if svc not in SERVICIOS:
                self._json(404, {"error": "servicio desconocido"})
                return
            self._json(200, {"svc": svc, "log": tail_log(GESTOR.ruta_log(svc), 200)})
            return

        self._json(404, {"error": "no encontrado"})

    def _origen_confiable(self) -> bool:
        """
        Defensa CSRF / DNS-rebinding para las acciones que lanzan/matan procesos.

        - Exige el header custom 'X-SDMR-Control': un sitio de otro origen no puede
          agregarlo sin disparar un preflight CORS que este servidor no aprueba,
          así que una pestaña maliciosa no puede invocar las acciones.
        - Valida que el Host sea loopback (bloquea DNS-rebinding).
        """
        if self.headers.get("X-SDMR-Control") != "1":
            return False
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "")

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if not self._origen_confiable():
            self._json(403, {"error": "origen no confiable (falta X-SDMR-Control o Host inválido)"})
            return

        try:
            if parsed.path == "/iniciar":
                svc = self._svc(qs)
                if svc not in SERVICIOS:
                    self._json(404, {"error": "servicio desconocido"})
                    return
                GESTOR.iniciar(svc, n=self._n(qs))
            elif parsed.path == "/detener":
                svc = self._svc(qs)
                if svc not in SERVICIOS:
                    self._json(404, {"error": "servicio desconocido"})
                    return
                GESTOR.detener(svc)
            elif parsed.path == "/encender-todo":
                GESTOR.encender_todo(n_agentes=self._n(qs))
            elif parsed.path == "/apagar-todo":
                GESTOR.apagar_todo()
            else:
                self._json(404, {"error": "no encontrado"})
                return
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})
            return

        self._json(200, {"servicios": GESTOR.estado()})

    def log_message(self, *args):
        pass  # silencioso


def main(puerto: int = 7070):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    except OSError as e:
        print(f"[CONTROL] No se pudo abrir el puerto {puerto} en 127.0.0.1: {e}")
        print("[CONTROL] ¿Ya hay un Centro de Control abierto? Cerralo o usá otro puerto.")
        sys.exit(1)

    print("=================================================================")
    print(f" SDMR CENTRO DE CONTROL en http://127.0.0.1:{puerto}")
    print(" Panel local para iniciar/detener todo el stack. Solo 127.0.0.1.")
    print("=================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[CONTROL] Cerrando y deteniendo procesos lanzados...")
        GESTOR.apagar_todo()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7070
    main(port)
