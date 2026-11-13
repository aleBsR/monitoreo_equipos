"""
===============================================================================
SDMR - Control del Agente (mini interfaz, multiplataforma)
===============================================================================
Ventana unica para iniciar / detener / consultar el estado del agente de
monitoreo en ESTE equipo, SIN abrir una terminal. Funciona en Linux y Windows
(Tkinter viene con Python en ambos).

Permite apuntar el agente a un Servidor Central que corre en OTRA PC de la red:
se escribe su IP en el campo "Servidor (IP)" y queda guardada en agent/config.ini
(si se deja vacio, el agente descubre el servidor solo por broadcast).

Uso:
    python scripts/agent/agent_control.py
===============================================================================
"""

import configparser
import os
import platform
import signal
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTE = os.path.join(RAIZ, "agent", "agent.py")
LOG = os.path.join(RAIZ, "agent", "agente.log")
RUTA_CONFIG = os.path.join(RAIZ, "agent", "config.ini")
IS_WIN = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# CONFIGURACION (agent/config.ini) — el agente la lee al arrancar con --silent
# ---------------------------------------------------------------------------
def leer_config_ui(ruta: str = RUTA_CONFIG) -> tuple:
    """Devuelve (id_nodo, ip_servidor) guardados; cadenas vacias si no hay."""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(ruta, encoding="utf-8")
    except (configparser.Error, OSError):
        return "", ""
    idn = cfg.get("nodo", "id_nodo", fallback="").strip() if cfg.has_section("nodo") else ""
    ip = cfg.get("red", "ip_servidor", fallback="").strip() if cfg.has_section("red") else ""
    return idn, ip


def guardar_config_ui(id_nodo: str, ip_servidor: str, ruta: str = RUTA_CONFIG):
    """
    Escribe id_nodo e ip_servidor en config.ini preservando el resto de valores
    (puertos, intervalo). ip vacia = el agente descubre el servidor por broadcast.
    """
    cfg = configparser.ConfigParser()
    try:
        cfg.read(ruta, encoding="utf-8")
    except (configparser.Error, OSError):
        pass
    if not cfg.has_section("nodo"):
        cfg.add_section("nodo")
    if not cfg.has_section("red"):
        cfg.add_section("red")
    cfg.set("nodo", "id_nodo", (id_nodo or "").strip())
    cfg.set("red", "ip_servidor", (ip_servidor or "").strip())
    # Defaults solo si faltan (no pisa lo que el usuario ya tenga)
    for clave, valor in (("puerto_udp", "5000"), ("puerto_cmd", "5002"), ("intervalo", "3")):
        if not cfg.has_option("red", clave):
            cfg.set("red", clave, valor)
    with open(ruta, "w", encoding="utf-8") as f:
        cfg.write(f)


# ---------------------------------------------------------------------------
# GESTION DEL PROCESO DEL AGENTE
# ---------------------------------------------------------------------------
def _pythonw() -> str:
    if not IS_WIN:
        return sys.executable
    base = os.path.dirname(sys.executable)
    cand = os.path.join(base, "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def agent_pids():
    """PIDs de los procesos que estan ejecutando agent/agent.py."""
    pids = []
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if "agent.py" in cmd and "agent_control" not in cmd:
                pids.append(proc.info["pid"])
        return pids
    except ImportError:
        pass

    if IS_WIN:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" "
                 "| Where-Object { $_.CommandLine -like '*agent.py*' } "
                 "| Select-Object -ExpandProperty ProcessId"],
                capture_output=True, text=True, timeout=10)
            for line in out.stdout.split():
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
    else:
        try:
            out = subprocess.run(["pgrep", "-f", "agent/agent.py"],
                                 capture_output=True, text=True, timeout=5)
            for line in out.stdout.split():
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
    return pids


def start_agent():
    """Lanza el agente oculto (lee agent/config.ini para IP/ID)."""
    if agent_pids():
        return False, "El agente ya esta corriendo."
    try:
        if IS_WIN:
            pyw = _pythonw()
            flags = 0x08000000  # CREATE_NO_WINDOW
            if pyw.endswith("pythonw.exe"):
                subprocess.Popen([pyw, AGENTE, "--silent"], cwd=RAIZ, creationflags=flags)
            else:
                subprocess.Popen([sys.executable, "-u", AGENTE, "--silent"],
                                 cwd=RAIZ, creationflags=flags,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([sys.executable, AGENTE, "--silent"], cwd=RAIZ,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception as e:
        return False, f"No se pudo iniciar: {e}"
    return True, "Agente iniciado. Log: " + LOG


def stop_agent():
    pids = agent_pids()
    if not pids:
        return 0, "No hay agente corriendo."
    for pid in pids:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=5)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    return len(pids), f"Agente detenido ({len(pids)} proceso(s))."


def open_log():
    if not os.path.exists(LOG):
        return
    try:
        if IS_WIN:
            os.startfile(LOG)
        elif platform.system() == "Darwin":
            subprocess.run(["open", LOG])
        else:
            subprocess.run(["xdg-open", LOG])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# UI (Tkinter, tema oscuro NOC — mismo espíritu que la web)
# ---------------------------------------------------------------------------
import tkinter as tk
from tkinter import messagebox

# Paleta (coincide con web/src/styles.css)
BG = "#0B1220"
CARD = "#111C2E"
CARD2 = "#16233A"
LINE = "#243449"
INK = "#E2E8F0"
INK_STRONG = "#F8FAFC"
MUTED = "#94A3B8"
ACCENT = "#00E5FF"
OK = "#10B981"
OFF = "#EF4444"
GREY = "#475569"
FUENTE = "Segoe UI" if IS_WIN else "DejaVu Sans"


def _boton(parent, texto, comando, base, hover, fg="#04121c", ancho=12):
    b = tk.Button(parent, text=texto, command=comando, bg=base, fg=fg,
                  activebackground=hover, activeforeground=fg, relief="flat",
                  bd=0, highlightthickness=0, cursor="hand2",
                  font=(FUENTE, 10, "bold"), width=ancho, pady=7)
    b.bind("<Enter>", lambda e: b.configure(bg=hover))
    b.bind("<Leave>", lambda e: b.configure(bg=base))
    return b


def _entry(parent):
    e = tk.Entry(parent, bg=CARD2, fg=INK_STRONG, insertbackground=ACCENT,
                 relief="flat", font=(FUENTE, 11), highlightthickness=1,
                 highlightbackground=LINE, highlightcolor=ACCENT)
    return e


class App:
    def __init__(self, root):
        self.root = root
        root.title("SDMR · Control del Agente")
        root.configure(bg=BG)
        root.geometry("420x460")
        root.resizable(False, False)

        cont = tk.Frame(root, bg=BG)
        cont.pack(fill="both", expand=True, padx=20, pady=16)

        # --- Encabezado ---
        cab = tk.Frame(cont, bg=BG)
        cab.pack(fill="x")
        tk.Label(cab, text="SDMR", bg=BG, fg=ACCENT,
                 font=(FUENTE, 20, "bold")).pack(side="left")
        tk.Label(cab, text="  Control del Agente", bg=BG, fg=MUTED,
                 font=(FUENTE, 11)).pack(side="left", anchor="s", pady=(0, 3))

        # --- Pill de estado ---
        pill = tk.Frame(cont, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        pill.pack(fill="x", pady=(12, 0))
        self.punto = tk.Label(pill, text="●", bg=CARD, fg=GREY, font=(FUENTE, 13))
        self.punto.pack(side="left", padx=(12, 6), pady=8)
        self.estado_var = tk.StringVar(value="Consultando…")
        tk.Label(pill, textvariable=self.estado_var, bg=CARD, fg=INK,
                 font=(FUENTE, 10, "bold")).pack(side="left")

        # --- Campos ---
        tarjeta = tk.Frame(cont, bg=BG)
        tarjeta.pack(fill="x", pady=(14, 0))

        idn, ip = leer_config_ui()

        tk.Label(tarjeta, text="SERVIDOR (IP)", bg=BG, fg=MUTED,
                 font=(FUENTE, 9, "bold")).pack(anchor="w")
        self.entrada_ip = _entry(tarjeta)
        self.entrada_ip.pack(fill="x", ipady=5, pady=(3, 0))
        self.entrada_ip.insert(0, ip)
        tk.Label(tarjeta, text="vacío = descubrir el servidor en la red (broadcast)",
                 bg=BG, fg=MUTED, font=(FUENTE, 8)).pack(anchor="w", pady=(3, 0))

        tk.Label(tarjeta, text="ID DEL NODO (opcional)", bg=BG, fg=MUTED,
                 font=(FUENTE, 9, "bold")).pack(anchor="w", pady=(12, 0))
        self.entrada_id = _entry(tarjeta)
        self.entrada_id.pack(fill="x", ipady=5, pady=(3, 0))
        self.entrada_id.insert(0, idn)
        tk.Label(tarjeta, text="vacío = nombre de este equipo",
                 bg=BG, fg=MUTED, font=(FUENTE, 8)).pack(anchor="w", pady=(3, 0))

        # --- Botones ---
        botones = tk.Frame(cont, bg=BG)
        botones.pack(fill="x", pady=(18, 0))
        botones.columnconfigure(0, weight=1)
        botones.columnconfigure(1, weight=1)

        _boton(botones, "▶  Iniciar", self.iniciar, ACCENT, "#5CF2FF").grid(
            row=0, column=0, sticky="ew", padx=(0, 5), pady=4)
        _boton(botones, "■  Detener", self.detener, "#3a1620", "#4d1d2a",
               fg="#fca5a5").grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=4)
        _boton(botones, "Estado", self.actualizar, CARD2, LINE,
               fg=INK).grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=4)
        _boton(botones, "Abrir log", open_log, CARD2, LINE,
               fg=INK).grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=4)

        tk.Label(cont, text=LOG, bg=BG, fg=MUTED, font=(FUENTE, 8)).pack(
            side="bottom", pady=(14, 0))

        self.actualizar()
        self._programar_refresh()

    def _datos(self):
        return self.entrada_id.get().strip(), self.entrada_ip.get().strip()

    def actualizar(self):
        pids = agent_pids()
        if pids:
            self.estado_var.set(f"EN EJECUCIÓN · PID {pids[0]}")
            self.punto.configure(fg=OK)
        else:
            self.estado_var.set("DETENIDO")
            self.punto.configure(fg=GREY)

    def _programar_refresh(self):
        self.actualizar()
        self.root.after(3000, self._programar_refresh)

    def iniciar(self):
        idn, ip = self._datos()
        # Guarda IP/ID para que el agente (--silent) los tome y queden recordados.
        try:
            guardar_config_ui(idn, ip)
        except OSError as e:
            messagebox.showwarning("SDMR", f"No se pudo guardar la configuración: {e}")
            return
        ok, msg = start_agent()
        self.actualizar()
        if ok:
            destino = ip if ip else "la red (broadcast)"
            messagebox.showinfo("SDMR", f"Agente iniciado.\nServidor: {destino}\n\nLog: {LOG}")
        else:
            messagebox.showwarning("SDMR", msg)

    def detener(self):
        _n, msg = stop_agent()
        self.actualizar()
        messagebox.showinfo("SDMR", msg)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
