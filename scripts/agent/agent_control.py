"""
===============================================================================
SDMR - Control del Agente (mini interfaz, multiplataforma)
===============================================================================
Ventana unica para iniciar / detener / consultar el estado del agente de
monitoreo en ESTE equipo, sin abrir una terminal. Funciona en Linux y Windows
(Tkinter viene con Python en ambos).

Uso:
    python scripts/agent/agent_control.py
===============================================================================
"""

import os
import sys
import signal
import platform
import subprocess
import threading

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENTE = os.path.join(RAIZ, "agent", "agent.py")
LOG = os.path.join(RAIZ, "agent", "agente.log")
IS_WIN = platform.system() == "Windows"


def _python() -> str:
    return sys.executable


def _pythonw() -> str:
    if not IS_WIN:
        return _python()
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
# UI
# ---------------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk, messagebox


class App:
    def __init__(self, root):
        self.root = root
        root.title("SDMR - Control del Agente")
        root.geometry("360x220")
        root.resizable(False, False)

        ttk.Label(root, text="Control del agente de monitoreo", font=("TkDefaultFont", 11, "bold")).pack(pady=(12, 4))

        self.estado_var = tk.StringVar(value="Consultando...")
        ttk.Label(root, textvariable=self.estado_var).pack(pady=4)

        marco = ttk.Frame(root)
        marco.pack(pady=8)
        ttk.Button(marco, text="Iniciar agente", command=self.iniciar, width=16).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(marco, text="Detener agente", command=self.detener, width=16).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(marco, text="Actualizar estado", command=self.actualizar, width=16).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(marco, text="Abrir log", command=open_log, width=16).grid(row=1, column=1, padx=4, pady=4)

        self.log_var = tk.StringVar(value=LOG)
        ttk.Label(root, textvariable=self.log_var, font=("TkDefaultFont", 8), foreground="gray").pack(side="bottom", pady=6)

        self.actualizar()
        self._programar_refresh()

    def actualizar(self):
        pids = agent_pids()
        if pids:
            self.estado_var.set(f"Estado: EN EJECUCION (PID {pids[0]})")
        else:
            self.estado_var.set("Estado: DETENIDO")

    def _programar_refresh(self):
        self.actualizar()
        self.root.after(3000, self._programar_refresh)

    def iniciar(self):
        ok, msg = start_agent()
        self.actualizar()
        if ok:
            messagebox.showinfo("SDMR", msg)
        else:
            messagebox.showwarning("SDMR", msg)

    def detener(self):
        n, msg = stop_agent()
        self.actualizar()
        messagebox.showinfo("SDMR", msg)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()