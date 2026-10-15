"""
================================================================================
Interfaz Gráfica de Monitoreo SDMR (Dashboard Tkinter)
================================================================================
Este módulo implementa una consola gráfica de administración para el Sistema
Distribuido de Monitoreo en Red.

No reemplaza a `client/admin_client.py`: es un cliente adicional que consume el
mismo protocolo de aplicación NETMON/1.0 sobre sockets TCP, tal como exige la
sección 2.2 de la propuesta (la interfaz es un "Desafío Adicional" que no
sustituye a los clientes socket nativos).

Pestañas de la interfaz:
  1. Nodos         -> Tabla con telemetría en vivo (CPU / RAM / Disco por nodo).
  2. Demo          -> Levanta Servidor + N Agentes en un clic, para mostrar el
                      proyecto funcionando de punta a punta.
  3. Tráfico       -> Log con las tramas NETMON/1.0 reales enviadas y recibidas,
                      útil para explicar el protocolo en la defensa.
  4. Instrucciones -> Guía de uso: cómo levantar el sistema, comandos, puertos y
                      problemas frecuentes (pestaña sin conexión, no necesita
                      servidor en marcha).
  5. Conceptos     -> Definiciones de TCP, UDP, sockets y puertos tomadas
                      literalmente de la bibliografía (Kurose, 5.ª ed.).

Decisiones de diseño:
  - Solo biblioteca estándar (tkinter). No depende de frameworks web ni de
    librerías que oculten la capa de sockets.
  - La interfaz se actualiza con `after()` en el hilo principal de Tk, evitando
    actualizar widgets desde hilos secundarios (Tkinter no es thread-safe).
  - El búfer de recepción acumula bytes hasta encontrar el delimitador '\n'
    (encuadrado de trama correcto). No se copia el patrón de un solo `recv()`
    usado en `admin_client.py`, que concatena comandos si llegan juntos.
================================================================================
"""

import os
import re
import sys
import time
import queue
import socket
import subprocess
import threading
import traceback
import tkinter as tk
from tkinter import ttk

# Permitir importar módulos desde la raíz del proyecto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.protocol import (
    DEFAULT_UDP_PORT,
    DEFAULT_TCP_PORT,
    DEFAULT_AGENT_TCP_PORT,
    BUFFER_SIZE,
    ENCODING,
    build_tcp_command,
    parse_tcp_response,
)
from client.contenido_ayuda import INSTRUCCIONES, CONCEPTOS, FUENTE_LIBRO

# Límite de líneas retenidas en el log para no degradar la interfaz
MAX_LOG_LINES = 2000

# Expresión para extraer los valores numéricos del payload de GET_NODES.
# El servidor serializa:  NODO_01:192.168.1.5:OK:CPU=35.4%:RAM=62.1%:DISK=40.0%
METRIC_RE = re.compile(r"(CPU|RAM|DISK)=([0-9]+(?:\.[0-9]+)?)")


def barra(porcentaje, ancho=10):
    """
    Dibuja una barra de progreso_TEXTUAL_ con caracteres de bloque.

    Evita depender de un widget de progreso por celda, que no existe en ttk.

    :param porcentaje: Valor de 0 a 100.
    :param ancho: Cantidad de caracteres de la barra.
    :return: Cadena con la barra y el porcentaje, ej. '████░░░░░░ 35.4%'
    """
    try:
        pct = float(porcentaje)
    except (TypeError, ValueError):
        pct = 0.0
    pct = max(0.0, min(100.0, pct))
    llenos = int(round((ancho * pct) / 100.0))
    return "█" * llenos + "░" * (ancho - llenos) + f" {pct:.1f}%"


class SDMRMonitorGUI:
    """
    Ventana principal del dashboard de monitoreo SDMR.
    """

    def __init__(self, root: tk.Tk, opciones: dict = None):
        self.root = root
        self.root.title("SDMR · Sistema Distribuido de Monitoreo en Red")
        self.root.geometry("1060x720")
        self.root.minsize(940, 600)
        self.opciones = opciones or {}

        # ---------------------------------------------------------
        # Estado de la conexión TCP con el servidor central
        # ---------------------------------------------------------
        self.tcp_socket = None
        self.is_connected = False
        self.is_authenticated = False
        self.rx_buffer = b""          # Búfer de recepción para encuadrado de trama
        self.usuario = None

        # ---------------------------------------------------------
        # Estado de la demo local (procesos hijo)
        # ---------------------------------------------------------
        self.procesos = []
        self.salida_procesos = queue.Queue()

        # ---------------------------------------------------------
        # Estado de la actualización periódica
        # ---------------------------------------------------------
        self._poll_job = None
        self._ultima_actualizacion = 0.0

        # ---------------------------------------------------------
        # Estado de las pestañas de ayuda (instrucciones / conceptos)
        # ---------------------------------------------------------
        self._ayuda_tabs = []

        self._construir_estilos()
        self._construir_interfaz()

        # Planifica el drenaje de la salida de los procesos hijo.
        self.root.after(200, self._drenar_salida_procesos)
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        self._registrar("Sistema", "Dashboard listo. Pestaña 'Demo' para levantar todo con un clic.", "sys")

        # Aplica opciones de arranque (--demo, --agentes, --udp, --tcp, --host)
        self._aplicar_opciones_arranque()

    def _aplicar_opciones_arranque(self):
        """
        Prellena los campos de conexión según los argumentos de línea de
        comandos y, si se pidió `--demo`, levanta el sistema completo solo.
        """
        op = self.opciones
        if not op:
            return

        campos = (
            (self.entrada_host, op.get("host")),
            (self.entrada_puerto, op.get("tcp")),
            (self.entrada_puerto_udp, op.get("udp")),
            (self.entrada_agentes, op.get("agentes")),
        )
        for entrada, valor in campos:
            if valor is None:
                continue
            entrada.delete(0, "end")
            entrada.insert(0, str(valor))

        if op.get("demo"):
            self.notebook.select(1)  # pestaña Demo
            # Pequeña espera para que la ventana se dibuje antes de lanzar todo
            self.root.after(600, self.iniciar_demo)

    # =====================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =====================================================================

    def _construir_estilos(self):
        """
        Aplica un tema consistente y configura los colores de estado.
        """
        estilo = ttk.Style()
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass

        estilo.configure("Treeview", rowheight=26, font=("Consolas", 10))
        estilo.configure("Treeview.Heading", font=("Consolas", 10, "bold"))
        estilo.configure("TButton", padding=6)
        estilo.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        estilo.configure("Hint.TLabel", foreground="#666666", font=("Segoe UI", 9))

    def _construir_interfaz(self):
        """
        Arma el árbol de widgets: barra de conexión, notebook y barra de estado.
        """
        contenedor = ttk.Frame(self.root, padding=10)
        contenedor.pack(fill="both", expand=True)
        contenedor.rowconfigure(1, weight=1)
        contenedor.columnconfigure(0, weight=1)

        # ---------------- Barra superior de conexión ----------------
        marco_conexion = ttk.LabelFrame(contenedor, text=" Conexión con el Servidor Central (TCP) ", padding=10)
        marco_conexion.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # Fila 0: dirección del servidor
        ttk.Label(marco_conexion, text="Servidor:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self.entrada_host = ttk.Entry(marco_conexion, width=16)
        self.entrada_host.insert(0, "127.0.0.1")
        self.entrada_host.grid(row=0, column=1, sticky="ew", padx=(0, 12))

        ttk.Label(marco_conexion, text="Puerto TCP:").grid(row=0, column=2, sticky="e", padx=(0, 4))
        self.entrada_puerto = ttk.Entry(marco_conexion, width=7)
        self.entrada_puerto.insert(0, str(DEFAULT_TCP_PORT))
        self.entrada_puerto.grid(row=0, column=3, sticky="ew", padx=(0, 12))

        ttk.Button(marco_conexion, text="Conectar", command=self.conectar).grid(row=0, column=4, padx=3)
        ttk.Button(marco_conexion, text="Desconectar", command=self.desconectar).grid(row=0, column=5, padx=3)

        ttk.Label(marco_conexion, text="Puerto UDP:").grid(row=0, column=6, sticky="e", padx=(16, 4))
        self.entrada_puerto_udp = ttk.Entry(marco_conexion, width=7)
        self.entrada_puerto_udp.insert(0, str(DEFAULT_UDP_PORT))
        self.entrada_puerto_udp.grid(row=0, column=7, sticky="ew", padx=(0, 4))

        # Fila 1: autenticación
        ttk.Label(marco_conexion, text="Usuario:").grid(row=1, column=0, sticky="e", padx=(0, 4), pady=(8, 0))
        self.entrada_usuario = ttk.Entry(marco_conexion, width=16)
        self.entrada_usuario.insert(0, "admin")
        self.entrada_usuario.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(8, 0))

        ttk.Label(marco_conexion, text="Contraseña:").grid(row=1, column=2, sticky="e", padx=(0, 4), pady=(8, 0))
        self.entrada_clave = ttk.Entry(marco_conexion, width=16, show="*")
        self.entrada_clave.insert(0, "admin123")
        self.entrada_clave.grid(row=1, column=3, sticky="ew", padx=(0, 12), pady=(8, 0))

        ttk.Button(marco_conexion, text="Autenticar", command=self.autenticar).grid(
            row=1, column=4, padx=3, pady=(8, 0), sticky="w"
        )

        self.check_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            marco_conexion, text="Auto-actualizar", variable=self.check_auto,
            command=self._reprogramar_poll
        ).grid(row=1, column=5, padx=3, pady=(8, 0), sticky="w")

        self.entrada_intervalo = ttk.Entry(marco_conexion, width=5)
        self.entrada_intervalo.insert(0, "2")
        self.entrada_intervalo.grid(row=1, column=6, sticky="e", padx=(16, 4), pady=(8, 0))
        ttk.Label(marco_conexion, text="s").grid(row=1, column=7, sticky="w", pady=(8, 0))

        # ---------------- Notebook con las cinco pestañas ----------------
        self.notebook = ttk.Notebook(contenedor)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self._construir_pestana_nodos()
        self._construir_pestana_demo()
        self._construir_pestana_trafico()
        self._construir_pestana_instrucciones()
        self._construir_pestana_conceptos()

        # ---------------- Barra de estado ----------------
        self.barra_estado = tk.StringVar(value="Desconectado")
        marco_estado = ttk.Frame(contenedor)
        marco_estado.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(marco_estado, textvariable=self.barra_estado, font=("Segoe UI", 9, "bold")).pack(side="left")
        # StringVar separado: un Label de ttk no tiene .set() ni .get().
        self.var_conteo = tk.StringVar(value="")
        self.etiqueta_conteo = ttk.Label(marco_estado, textvariable=self.var_conteo, font=("Segoe UI", 9))
        self.etiqueta_conteo.pack(side="right")

    def _construir_pestana_nodos(self):
        """
        Pestaña 1: tabla de nodos con telemetría en vivo y panel de comando remoto.
        """
        marco = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(marco, text="  Nodos  ")

        # --- Barra de herramientas de la tabla ---
        barra = ttk.Frame(marco)
        barra.pack(fill="x", pady=(0, 8))

        ttk.Button(barra, text="⟳ Actualizar ahora", command=self.actualizar_nodos).pack(side="left")
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(barra, text="Nodo:").pack(side="left", padx=(0, 4))
        self.entrada_nodo = ttk.Entry(barra, width=12)
        self.entrada_nodo.insert(0, "NODO_01")
        self.entrada_nodo.pack(side="left", padx=(0, 12))

        ttk.Label(barra, text="Comando remoto:").pack(side="left", padx=(0, 4))
        self.entrada_comando = ttk.Combobox(barra, width=16, values=["RESTART_SERVICE", "DIAGNOSTIC", "CLEAR_LOGS"])
        self.entrada_comando.set("DIAGNOSTIC")
        self.entrada_comando.pack(side="left", padx=(0, 8))
        ttk.Button(barra, text="Enviar (EXEC)", command=self.ejecutar_comando).pack(side="left")

        ttk.Label(barra, text="Doble clic en una fila para seleccionarla como destino.",
                  style="Hint.TLabel").pack(side="right")

        # --- Tabla de nodos ---
        marco_tabla = ttk.Frame(marco)
        marco_tabla.pack(fill="both", expand=True)

        columnas = ("nodo", "ip", "estado", "cpu", "ram", "disco")
        self.tabla_nodos = ttk.Treeview(marco_tabla, columns=columnas, show="headings", selectmode="browse")

        titulos = {
            "nodo": ("NODO", 120, "w"),
            "ip": ("DIRECCIÓN IP", 145, "w"),
            "estado": ("ESTADO", 115, "center"),
            "cpu": ("CPU", 190, "w"),
            "ram": ("MEMORIA RAM", 190, "w"),
            "disco": ("DISCO", 190, "w"),
        }
        for clave, (titulo, ancho, ancla) in titulos.items():
            self.tabla_nodos.heading(clave, text=titulo)
            self.tabla_nodos.column(clave, width=ancho, anchor=ancla, stretch=(clave == "estado"))

        # Colores por estado de salud del nodo
        self.tabla_nodos.tag_configure("ok", background="#e8f8ec", foreground="#14663a")
        self.tabla_nodos.tag_configure("warning", background="#fff6e0", foreground="#8a5a00")
        self.tabla_nodos.tag_configure("offline", background="#fdecec", foreground="#9c1c1c")

        barra_scroll = ttk.Scrollbar(marco_tabla, orient="vertical", command=self.tabla_nodos.yview)
        self.tabla_nodos.configure(yscrollcommand=barra_scroll.set)

        self.tabla_nodos.pack(side="left", fill="both", expand=True)
        barra_scroll.pack(side="right", fill="y")

        self.tabla_nodos.bind("<Double-1>", self._al_seleccionar_nodo)

        # Estado vacío. Se superpone a la tabla y se oculta en cuanto hay filas,
        # así no ocupa espacio permanentte en la pestaña.
        self.mensaje_vacio = ttk.Label(
            marco_tabla,
            text="Sin datos.\n\nVá a la pestaña 'Demo' y pulsa 'Iniciar Demo',\n"
                 "o conéctate a un servidor en ejecución con 'Conectar'.",
            style="Hint.TLabel", justify="center"
        )
        self.mensaje_vacio.place(relx=0.5, rely=0.5, anchor="center")

    def _construir_pestana_demo(self):
        """
        Pestaña 2: lanza Servidor + N Agentes como procesos hijo de esta misma
        interfaz, para demostrar el sistema completo sin abrir varias terminales.
        """
        marco = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(marco, text="  Demo Local  ")

        ttk.Label(
            marco,
            text="Levanta el Servidor Central y varios Agentes en procesos separados,\n"
                 "y conecta este dashboard automáticamente para ver la telemetría en vivo.",
            justify="left", style="Hint.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        controles = ttk.Frame(marco)
        controles.grid(row=1, column=0, sticky="w")

        ttk.Label(controles, text="Número de agentes:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        self.entrada_agentes = ttk.Spinbox(controles, from_=1, to=6, width=5)
        self.entrada_agentes.set(3)
        self.entrada_agentes.grid(row=0, column=1, padx=(0, 16))

        self.boton_iniciar = ttk.Button(controles, text="▶  Iniciar Demo", command=self.iniciar_demo)
        self.boton_iniciar.grid(row=0, column=2, padx=(0, 8))

        self.boton_detener = ttk.Button(controles, text="■  Detener Demo", command=self.detener_demo, state="disabled")
        self.boton_detener.grid(row=0, column=3, padx=(0, 8))

        ttk.Button(controles, text="Ir a Nodos", command=lambda: self.notebook.select(0)).grid(row=0, column=4)

        # Tabla con el estado de cada proceso hijo
        self.etiqueta_procesos = ttk.Label(marco, text="", style="Hint.TLabel")
        self.etiqueta_procesos.grid(row=2, column=0, sticky="w", pady=(16, 6))

        marco_procesos = ttk.Frame(marco)
        marco_procesos.grid(row=3, column=0, sticky="nsew")
        marco.rowconfigure(3, weight=1)
        marco_procesos.rowconfigure(0, weight=1)
        marco_procesos.columnconfigure(0, weight=1)

        self.lista_procesos = tk.Listbox(marco_procesos, font=("Consolas", 9), height=8)
        self.lista_procesos.grid(row=0, column=0, sticky="nsew")
        scroll_proc = ttk.Scrollbar(marco_procesos, orient="vertical", command=self.lista_procesos.yview)
        scroll_proc.grid(row=0, column=1, sticky="ns")
        self.lista_procesos.configure(yscrollcommand=scroll_proc.set)

    def _construir_pestana_trafico(self):
        """
        Pestaña 3: volcado de las tramas del protocolo y envío de datos inválidos.
        """
        marco = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(marco, text="  Tráfico NETMON/1.0  ")

        # --- Log de tramas ---
        marco_log = ttk.LabelFrame(marco, text=" Tramas enviadas / recibidas ", padding=6)
        marco_log.pack(fill="both", expand=True)

        self.log = tk.Text(marco_log, font=("Consolas", 9), wrap="none", height=20)
        scroll_log = ttk.Scrollbar(marco_log, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll_log.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll_log.pack(side="right", fill="y")

        self.log.tag_configure("in", foreground="#0b5394")        # Comandos enviados por el cliente
        self.log.tag_configure("out", foreground="#14663a")       # Respuestas del servidor
        self.log.tag_configure("sys", foreground="#555555")       # Mensajes locales
        self.log.tag_configure("err", foreground="#c62828")       # Errores
        self.log.tag_configure("proc", foreground="#7b5ea7")      # Salida de los procesos hijo

        # --- Envío de tramas craft / inválidas ---
        marco_craft = ttk.Frame(marco)
        marco_craft.pack(fill="x", pady=(10, 0))

        ttk.Label(marco_craft, text="Enviar trama manual:").pack(side="left", padx=(0, 6))
        self.entrada_craft = ttk.Entry(marco_craft, font=("Consolas", 9))
        self.entrada_craft.insert(0, "CMD|ACCION_DESCONOCIDA")
        self.entrada_craft.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(marco_craft, text="Enviar", command=self.enviar_craft).pack(side="left", padx=(0, 6))
        ttk.Button(marco_craft, text="Limpiar log", command=self.limpiar_log).pack(side="left")

        ttk.Label(
            marco,
            text="Prueba el manejo de errores del servidor: 'DATOS_BASURA_SIN_CMD' (ERR_100) · "
                 "'CMD|ACCION_DESCONOCIDA' (ERR_103) · 'CMD|AUTH' (ERR_100)",
            style="Hint.TLabel"
        ).pack(anchor="w", pady=(8, 0))

    # =====================================================================
    # PESTAÑAS DE AYUDA (instrucciones de uso y conceptos de red)
    # =====================================================================

    def _construir_pestana_instrucciones(self):
        """
        Pestaña 4: guía de uso de la aplicación. No necesita servidor en marcha.
        """
        self._pestaña_ayuda(
            titulo="Instrucciones de uso",
            items=INSTRUCCIONES,
            ayuda="Índice de la guía · el contenido es material del proyecto.",
        )

    def _construir_pestana_conceptos(self):
        """
        Pestaña 5: definiciones de la bibliografía (Kurose). Sin conexión.
        """
        self._pestaña_ayuda(
            titulo="Conceptos de red (TCP / UDP)",
            items=CONCEPTOS,
            ayuda="Definiciones tomadas literalmente de la bibliografía. "
                  "Fuente: " + FUENTE_LIBRO,
            con_buscador=True,
        )

    def _pestaña_ayuda(self, titulo, items, ayuda, con_buscador=False):
        """
        Arma una pestaña con un índice a la izquierda y el texto a la derecha.

        Cada pestaña conserva su propio estado (índice, texto y buscador) en un
        diccionario, de modo que dos pestañas de ayuda no pisen sus widgets.

        :param titulo: Encabezado superior de la pestaña.
        :param items: Lista de dicts con claves 'titulo', 'texto' y opcional 'fuente'.
        :param ayuda: Texto de la línea inferior (fuente / nota).
        :param con_buscador: Si es True agrega un campo de filtrado del índice.
        :return: El estado de la pestaña creada.
        """
        estado = {"items": items, "visibles": list(items), "busqueda": None}

        marco = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(marco, text="  %s  " % titulo)
        marco.rowconfigure(1, weight=1)
        marco.columnconfigure(1, weight=1)

        cabecera = ttk.Frame(marco)
        cabecera.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(cabecera, text=titulo, style="Header.TLabel").pack(side="left")
        if con_buscador:
            ttk.Button(cabecera, text="Limpiar",
                       command=lambda: self._filtro_ayuda_limpiar(estado)).pack(side="right")
            ttk.Label(cabecera, text="Buscar:").pack(side="right", padx=(8, 4))
            entrada = ttk.Entry(cabecera, width=24)
            entrada.pack(side="right")
            entrada.bind("<KeyRelease>", lambda e: self._filtrar_ayuda(estado, e))
            estado["busqueda"] = entrada

        # --- Índice (izquierda) ---
        marco_indice = ttk.LabelFrame(marco, text=" Índice ", padding=6)
        marco_indice.grid(row=1, column=0, sticky="ns", padx=(0, 8))

        scroll_indice = ttk.Scrollbar(marco_indice, orient="vertical")
        scroll_indice.pack(side="right", fill="y")
        lista = tk.Listbox(
            marco_indice, width=44, font=("Segoe UI", 10), activestyle="dotbox",
            yscrollcommand=scroll_indice.set, exportselection=False, highlightthickness=0
        )
        lista.pack(fill="both", expand=True)
        scroll_indice.configure(command=lista.yview)
        lista.bind("<<ListboxSelect>>", lambda e: self._al_elegir_ayuda(estado, e))
        for item in estado["visibles"]:
            lista.insert("end", item["titulo"])
        estado["lista"] = lista

        # --- Texto (derecha) ---
        marco_texto = ttk.Frame(marco)
        marco_texto.grid(row=1, column=1, sticky="nsew")
        marco_texto.rowconfigure(1, weight=1)
        marco_texto.columnconfigure(0, weight=1)

        scroll_texto = ttk.Scrollbar(marco_texto, orient="vertical")
        scroll_texto.grid(row=1, column=1, sticky="ns")
        cuadro = tk.Text(
            marco_texto, font=("Segoe UI", 10), wrap="word", bd=1, relief="solid",
            padx=14, pady=12, spacing3=6, yscrollcommand=scroll_texto.set,
            cursor="arrow"
        )
        cuadro.grid(row=1, column=0, sticky="nsew")
        scroll_texto.configure(command=cuadro.yview)
        estado["texto"] = cuadro

        cuadro.tag_configure("titulo", font=("Segoe UI", 13, "bold"),
                             foreground="#0b5394", spacing1=4, spacing3=8)
        cuadro.tag_configure("fuente", font=("Segoe UI", 9, "italic"),
                             foreground="#7a7a7a", spacing3=10)
        cuadro.tag_configure("cuerpo", font=("Segoe UI", 10),
                             lmargin1=6, lmargin2=6, spacing3=8)
        cuadro.tag_configure("viñeta", font=("Segoe UI", 10),
                             lmargin1=22, lmargin2=40, spacing3=4)
        cuadro.tag_configure("cmd", font=("Consolas", 10),
                             lmargin1=22, lmargin2=40, spacing3=4,
                             foreground="#0b5394")
        cuadro.tag_configure("nota", font=("Segoe UI", 9, "italic"),
                             foreground="#7a7a7a", lmargin1=6, spacing3=6)

        # Solo lectura: no se puede editar, pero sí copiar con Ctrl+C.
        cuadro.bind("<Key>", self._texto_ayuda_solo_lectura)

        ttk.Label(marco, text=ayuda, style="Hint.TLabel", wraplength=760,
                  justify="left").grid(row=2, column=0, columnspan=2, sticky="w",
                                       pady=(8, 0))

        # Pinta la primera entrada una vez que el widget de texto existe.
        if estado["visibles"]:
            lista.selection_set(0)
            self._mostrar_entrada_ayuda(estado, 0)
        else:
            cuadro.insert("end", "Sin entradas.", "nota")
            cuadro.configure(state="disabled")

        self._ayuda_tabs.append(estado)
        return estado

    @staticmethod
    def _texto_ayuda_solo_lectura(event):
        """
        Bloquea la escritura en el texto de ayuda. Ctrl+C y Ctrl+A siguen
        funcionando para copiar o seleccionar el contenido.
        """
        if event.state & 0x0004:  # tecla Control
            if event.keysym.lower() in ("c", "a"):
                return None
        return "break"

    @staticmethod
    def _al_elegir_ayuda(estado, _evento):
        """Selecciona el texto de la entrada elegida en el índice."""
        sel = estado["lista"].curselection()
        if sel:
            SDMRMonitorGUI._mostrar_entrada_ayuda(estado, sel[0])

    @staticmethod
    def _mostrar_entrada_ayuda(estado, posicion):
        """Vuelca la entrada elegida en el widget de texto de solo lectura."""
        visibles = estado["visibles"]
        if posicion >= len(visibles):
            return
        item = visibles[posicion]
        cuadro = estado["texto"]
        cuadro.delete("1.0", "end")
        cuadro.insert("end", item["titulo"] + "\n", "titulo")
        if item.get("fuente"):
            cuadro.insert("end", item["fuente"] + "\n\n", "fuente")
        else:
            cuadro.insert("end", "\n", "fuente")
        for linea in item["texto"].split("\n"):
            if not linea.strip():
                cuadro.insert("end", "\n")
            elif linea.lstrip().startswith("•"):
                cuadro.insert("end", linea + "\n", "viñeta")
            elif "python3" in linea or "sdmr " in linea or linea.lstrip().startswith("CMD|"):
                cuadro.insert("end", linea + "\n", "cmd")
            else:
                cuadro.insert("end", linea + "\n", "cuerpo")
        cuadro.see("1.0")

    @staticmethod
    def _filtrar_ayuda(estado, _evento):
        """Filtra el índice del estado recibido según el campo 'Buscar'."""
        busqueda = estado.get("busqueda")
        texto = (busqueda.get().strip().lower() if busqueda else "")
        lista, cuadro = estado["lista"], estado["texto"]
        lista.delete(0, "end")
        estado["visibles"] = []
        for item in estado["items"]:
            if not texto or texto in item["titulo"].lower() or texto in item["texto"].lower():
                estado["visibles"].append(item)
                lista.insert("end", item["titulo"])
        if estado["visibles"]:
            lista.selection_set(0)
            SDMRMonitorGUI._mostrar_entrada_ayuda(estado, 0)
        else:
            cuadro.delete("1.0", "end")
            cuadro.insert("end", "Sin coincidencias.", "nota")

    @staticmethod
    def _filtro_ayuda_limpiar(estado):
        """Vacía el campo de búsqueda y repone el índice completo."""
        busqueda = estado.get("busqueda")
        if busqueda:
            busqueda.delete(0, "end")
        SDMRMonitorGUI._filtrar_ayuda(estado, None)

    # =====================================================================
    # COMUNICACIÓN TCP
    # =====================================================================

    def _leer_linea(self, timeout=5.0) -> str:
        """
        Lee UNA línea del socket acumulando bytes hasta el delimitador '\\n'.

        A diferencia del `recv()` único de `admin_client.py`, este método
        respeta el encuadrado de trama del protocolo y no concatena dos
        respuestas que lleguen en el mismo segmento TCP.

        :raises socket.timeout: Si no llega una línea completa a tiempo.
        :raises ConnectionError: Si el servidor cierra la conexión.
        """
        limite = time.time() + timeout
        while b"\n" not in self.rx_buffer:
            restante = limite - time.time()
            if restante <= 0:
                raise socket.timeout("Tiempo de espera agotado esperando respuesta del servidor.")
            self.tcp_socket.settimeout(restante)
            chunk = self.tcp_socket.recv(BUFFER_SIZE)
            if not chunk:
                raise ConnectionError("El servidor cerró la conexión.")
            self.rx_buffer += chunk

        linea, self.rx_buffer = self.rx_buffer.split(b"\n", 1)
        return linea.decode(ENCODING).strip()

    def _enviar_comando(self, accion: str, *params) -> dict:
        """
        Envía un comando NETMON/1.0 y devuelve la respuesta parseada.
        """
        if not self.is_connected or self.tcp_socket is None:
            return {"status": "ERR", "payload_or_code": "NOT_CONNECTED", "detail": "Sin conexión TCP activa."}

        trama = build_tcp_command(accion, *params)
        self._registrar("TX", trama, "in")

        try:
            self.tcp_socket.sendall((trama + "\n").encode(ENCODING))
            respuesta_cruda = self._leer_linea()
        except (socket.timeout, ConnectionError, OSError) as e:
            self.is_connected = False
            self.barra_estado.set("Desconectado (error de socket)")
            return {"status": "ERR", "payload_or_code": "SOCKET_ERROR", "detail": str(e)}

        self._registrar("RX", respuesta_cruda, "out")

        try:
            return parse_tcp_response(respuesta_cruda)
        except ValueError as e:
            return {"status": "ERR", "payload_or_code": "ERR_100", "detail": str(e)}

    def conectar(self):
        """
        Abre la conexión TCP con el servidor central (handshake de 3 vías).
        """
        if self.is_connected:
            self._registrar("Sistema", "Ya hay una conexión activa.", "sys")
            return

        host = self.entrada_host.get().strip() or "127.0.0.1"
        try:
            puerto = int(self.entrada_puerto.get().strip())
        except ValueError:
            self._registrar("Sistema", "El puerto TCP debe ser un número entero.", "err")
            return

        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.settimeout(5.0)
            self.tcp_socket.connect((host, puerto))
        except socket.timeout:
            self._registrar("Sistema", f"Tiempo agotado al conectar a {host}:{puerto}.", "err")
            self._cerrar_socket()
            return
        except ConnectionRefusedError:
            self._registrar("Sistema", f"Conexión rechazada en {host}:{puerto}. ¿Está el servidor running?", "err")
            self._cerrar_socket()
            return
        except OSError as e:
            self._registrar("Sistema", f"No se pudo conectar: {e}", "err")
            self._cerrar_socket()
            return

        self.rx_buffer = b""
        self.is_connected = True
        self.barra_estado.set(f"Conectado a {host}:{puerto} — no autenticado")
        self._registrar("Sistema", f"Conexión TCP establecida con {host}:{puerto}.", "sys")

        # El protocolo exige un PING para verificar conectividad del canal.
        respuesta = self._enviar_comando("PING")
        if respuesta["status"] == "OK":
            self._registrar("Sistema", f"El servidor respondió: {respuesta['detail']}", "sys")
            self.autenticar()

    def desconectar(self):
        """
        Cierra el socket TCP y detiene la actualización periódica.
        """
        if not self.is_connected:
            return
        self._registrar("Sistema", "Cerrando conexión TCP (FIN).", "sys")
        self._cerrar_socket()
        self.is_connected = False
        self.is_authenticated = False
        self.usuario = None
        self.barra_estado.set("Desconectado")
        self._detener_poll()

    def _cerrar_socket(self):
        """
        Libera el socket TCP tragando la excepción, si la hubiera.
        """
        if self.tcp_socket is not None:
            try:
                self.tcp_socket.close()
            except OSError:
                pass
            self.tcp_socket = None

    def autenticar(self):
        """
        Envía CMD|AUTH con las credenciales ingresadas.
        """
        if not self.is_connected:
            self._registrar("Sistema", "Conéctate primero al servidor.", "err")
            return

        usuario = self.entrada_usuario.get().strip()
        clave = self.entrada_clave.get()

        respuesta = self._enviar_comando("AUTH", usuario, clave)
        if respuesta["status"] == "OK":
            self.is_authenticated = True
            self.usuario = usuario
            self.barra_estado.set(f"Autenticado como '{usuario}' — {self.entrada_host.get()}")
            self._registrar("Sistema", f"Sesión iniciada: {respuesta['detail']}", "sys")
            self.actualizar_nodos()
            self._reprogramar_poll()
        else:
            self.is_authenticated = False
            self.barra_estado.set("Autenticación fallida")
            self._registrar("Sistema", f"Error de autenticación [{respuesta['payload_or_code']}]: {respuesta['detail']}", "err")

    # =====================================================================
    # CONSULTA DE NODOS
    # =====================================================================

    @staticmethod
    def _parsear_nodos(payload: str) -> list:
        """
        Convierte el payload de GET_NODES en una lista de diccionarios.

        Formato recibido:
            NODES_COUNT:2;NODO_01:192.168.1.5:OK:CPU=35.4%:RAM=62.1%:DISK=40.0%

        :param payload: Segundo campo de la respuesta RES|OK|...
        :return: Lista de diccionarios con id, ip, estado, cpu, ram, disk.
        """
        # El servidor emite las claves 'CPU', 'RAM' y 'DISK'; se normalizan a
        # 'cpu', 'ram' y 'disco' para no perder el valor del disco.
        claves = {"CPU": "cpu", "RAM": "ram", "DISK": "disco"}

        nodos = []
        for entrada in payload.split(";"):
            if not entrada or entrada.startswith("NODES_COUNT"):
                continue
            campos = entrada.split(":")
            if len(campos) < 3:
                continue
            nodo = {"id": campos[0], "ip": campos[1], "estado": campos[2], "cpu": 0.0, "ram": 0.0, "disco": 0.0}
            for clave, valor in METRIC_RE.findall(entrada):
                nodo[claves.get(clave, clave.lower())] = float(valor)
            nodos.append(nodo)
        return nodos

    def actualizar_nodos(self):
        """
        Consulta GET_NODES y refresca la tabla con la telemetría vigente.
        """
        if not self.is_connected or not self.is_authenticated:
            return

        respuesta = self._enviar_comando("GET_NODES", "ALL")
        self._ultima_actualizacion = time.time()

        if respuesta["status"] != "OK":
            self.var_conteo.set(f"Error: {respuesta['payload_or_code']}")
            return

        nodos = self._parsear_nodos(respuesta["payload_or_code"])
        self._pintar_nodos(nodos)

        en_linea = sum(1 for n in nodos if n["estado"] != "OFFLINE")
        # time.time() devuelve un float: el formato %H:%M:%S es de strftime,
        # no sirve aquí directamente.
        reloj = time.strftime("%H:%M:%S", time.localtime(self._ultima_actualizacion))
        self.var_conteo.set(f"{len(nodos)} nodo(s) · {en_linea} en línea · actualizado {reloj}")

    def _pintar_nodos(self, nodos: list):
        """
        Vuelve a dibujar la tabla completa conservando la selección.
        """
        seleccion = self.entrada_nodo.get().strip()
        self.tabla_nodos.delete(*self.tabla_nodos.get_children())

        for nodo in nodos:
            estado = nodo["estado"].upper()
            etiqueta = {"OK": "ok", "WARNING": "warning"}.get(estado, "offline")
            icono = {"OK": "🟢", "WARNING": "⚠"}.get(estado, "🔴")

            self.tabla_nodos.insert(
                "", "end", iid=nodo["id"],
                values=(
                    nodo["id"],
                    nodo["ip"],
                    f"{icono} {estado}",
                    barra(nodo["cpu"]),
                    barra(nodo["ram"]),
                    barra(nodo["disco"]),
                ),
                tags=(etiqueta,),
            )

            if nodo["id"] == seleccion:
                self.tabla_nodos.selection_set(nodo["id"])

        # El mensaje de estado vacío solo se ve cuando no hay nada que mostrar.
        if nodos:
            self.mensaje_vacio.place_forget()
        else:
            self.mensaje_vacio.place(relx=0.5, rely=0.5, anchor="center")
            self.var_conteo.set("Sin nodos registrados. ¿Hay algún agente enviando telemetría?")

    def _al_seleccionar_nodo(self, _evento):
        """
        Doble clic sobre una fila: la marca como destino de EXEC.
        """
        seleccion = self.tabla_nodos.selection()
        if seleccion:
            # ttk.Entry no tiene .set(): hay que borrar e insertar.
            self.entrada_nodo.delete(0, "end")
            self.entrada_nodo.insert(0, seleccion[0])
            self._registrar("Sistema", "Destino de EXEC seleccionado: %s" % seleccion[0], "sys")

    def ejecutar_comando(self):
        """
        Envía CMD|EXEC hacia el nodo indicado.
        """
        if not self.is_authenticated:
            self._registrar("Sistema", "Debes autenticarte antes de ejecutar comandos.", "err")
            return

        nodo = self.entrada_nodo.get().strip()
        comando = self.entrada_comando.get().strip()
        if not nodo or not comando:
            self._registrar("Sistema", "Indica el nodo y el comando.", "err")
            return

        respuesta = self._enviar_comando("EXEC", nodo, comando)
        if respuesta["status"] == "OK":
            self._registrar("Sistema", f"EXEC en {nodo}: {respuesta['detail']}", "sys")
        else:
            self._registrar("Sistema", f"EXEC rechazado [{respuesta['payload_or_code']}]: {respuesta['detail']}", "err")

    def enviar_craft(self):
        """
        Envía una trama escrita a mano, útil para demostrar RF07.
        """
        if not self.is_connected:
            self._registrar("Sistema", "Conéctate primero al servidor.", "err")
            return

        trama = self.entrada_craft.get().strip()
        if not trama:
            return

        self._registrar("TX", trama, "in")
        try:
            self.tcp_socket.sendall((trama + "\n").encode(ENCODING))
            respuesta = self._leer_linea()
        except (socket.timeout, ConnectionError, OSError) as e:
            self._registrar("Sistema", f"Error de socket: {e}", "err")
            self.is_connected = False
            return

        self._registrar("RX", respuesta, "out")
        self._registrar(
            "Sistema",
            "El servidor respondió con un error tipificado sin cerrar la conexión. "
            "Eso es exactamente lo que exige RF07.",
            "sys",
        )

    # =====================================================================
    # ACTUALIZACIÓN PERIÓDICA
    # =====================================================================

    def _reprogramar_poll(self):
        """
        (Re)programa la consulta periódica según el estado del checkbox.
        """
        self._detener_poll()
        if self.check_auto.get() and self.is_connected and self.is_authenticated:
            self._poll_job = self.root.after(2000, self._ciclo_poll)

    def _detener_poll(self):
        """
        Cancela el temporizador de actualización si estaba activo.
        """
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None

    def _ciclo_poll(self):
        """
        Tick del temporizador: consulta y vuelve a encolarse a sí mismo.
        """
        if not self.check_auto.get() or not self.is_connected or not self.is_authenticated:
            self._poll_job = None
            return

        self.actualizar_nodos()

        try:
            intervalo = int(self.entrada_intervalo.get().strip())
        except ValueError:
            intervalo = 2
        self._poll_job = self.root.after(max(1, intervalo) * 1000, self._ciclo_poll)

    # =====================================================================
    # DEMO LOCAL: SERVIDOR + AGENTES
    # =====================================================================

    def _puerto_disponible(self, host: str, puerto: int, tipo: str) -> bool:
        """Comprueba si se puede asociar (bind) un puerto local."""
        familia = socket.SOCK_STREAM if tipo == "tcp" else socket.SOCK_DGRAM
        s = socket.socket(socket.AF_INET, familia)
        try:
            s.bind((host, puerto))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def _siguiente_puerto_libre(self, inicio: int, tipo: str, host: str = "127.0.0.1") -> int:
        """Devuelve el primer puerto libre >= inicio (avisa si hubo que moverse)."""
        puerto = inicio
        while puerto < 65535 and not self._puerto_disponible(host, puerto, tipo):
            puerto += 1
        if puerto != inicio:
            self._registrar("Sistema", f"Puerto {tipo.upper()} {inicio} ocupado: se usará {puerto}.", "sys")
        return puerto

    def _puertos_tcp_libres(self, cantidad: int, desde: int) -> list:
        """Reserva `cantidad` puertos TCP libres y distintos a partir de `desde`."""
        puertos = []
        candidato = desde
        while len(puertos) < cantidad and candidato < 65535:
            if self._puerto_disponible("127.0.0.1", candidato, "tcp"):
                puertos.append(candidato)
            candidato += 1
        return puertos

    def iniciar_demo(self):
        """
        Levanta el servidor y N agentes como procesos hijo, y conecta el dashboard.
        """
        if self.procesos:
            self._registrar("Sistema", "La demo ya está en marcha.", "sys")
            return

        raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        ruta_servidor = os.path.join(raiz, "server", "server.py")
        ruta_agente = os.path.join(raiz, "agent", "agent.py")

        for ruta in (ruta_servidor, ruta_agente):
            if not os.path.isfile(ruta):
                self._registrar("Sistema", f"No se encontró {ruta}", "err")
                return

        try:
            puerto_udp = int(self.entrada_puerto_udp.get().strip())
        except ValueError:
            puerto_udp = DEFAULT_UDP_PORT
        try:
            puerto_tcp = int(self.entrada_puerto.get().strip())
        except ValueError:
            puerto_tcp = DEFAULT_TCP_PORT
        try:
            cantidad = max(1, min(6, int(self.entrada_agentes.get().strip())))
        except ValueError:
            cantidad = 3

        # §6 del TP: manejo de "puerto ocupado". Si el puerto pedido está en uso
        # (por ejemplo, ya hay un SDMR corriendo), se avanza al siguiente libre
        # en vez de fallar al lanzar el servidor.
        puerto_udp = self._siguiente_puerto_libre(puerto_udp, "udp", self.entrada_host.get().strip() or "127.0.0.1")
        puerto_tcp = self._siguiente_puerto_libre(puerto_tcp, "tcp", self.entrada_host.get().strip() or "127.0.0.1")

        # ttk.Entry no tiene .set(): hay que borrar e insertar.
        for entrada, valor in (
            (self.entrada_host, "127.0.0.1"),
            (self.entrada_puerto, str(puerto_tcp)),
            (self.entrada_puerto_udp, str(puerto_udp)),
        ):
            entrada.delete(0, "end")
            entrada.insert(0, valor)

        # Puerto TCP de control (EXEC) para cada agente: deben ser distintos
        # porque todos corren en la misma máquina durante la demo.
        puertos_cmd = self._puertos_tcp_libres(cantidad, DEFAULT_AGENT_TCP_PORT)

        # Bandera para no abrir una ventana de consola por cada proceso hijo.
        sin_consola = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        # 1. Servidor central
        self._registrar("Sistema", "Iniciando Servidor Central (TCP+UDP)...", "sys")
        servidor = subprocess.Popen(
            [sys.executable, "-u", ruta_servidor, str(puerto_udp), str(puerto_tcp)],
            cwd=raiz, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding=ENCODING, errors="replace", bufsize=1,
            creationflags=sin_consola,
        )
        self.procesos.append(("Servidor Central", servidor))
        self._escuchar_proceso("Servidor", servidor)

        # Pequeña pausa para que el servidor abra los sockets antes que los agentes.
        time.sleep(1.0)

        # 2. Agentes de monitoreo (cada uno con su canal de comandos EXEC)
        for indice in range(1, cantidad + 1):
            nombre = f"NODO_{indice:02d}"
            cmd_port = puertos_cmd[indice - 1]
            self._registrar("Sistema", f"Iniciando agente {nombre} (EXEC TCP {cmd_port})...", "sys")
            agente = subprocess.Popen(
                [sys.executable, "-u", ruta_agente, nombre, "127.0.0.1", str(puerto_udp), str(cmd_port)],
                cwd=raiz, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding=ENCODING, errors="replace", bufsize=1,
                creationflags=sin_consola,
            )
            self.procesos.append((nombre, agente))
            self._escuchar_proceso(nombre, agente)

        self.boton_iniciar.configure(state="disabled")
        self.boton_detener.configure(state="normal")
        self._refrescar_lista_procesos()
        self._registrar("Sistema", f"Demo en marcha: 1 servidor + {cantidad} agentes.", "sys")

        # 3. Conexión automática del dashboard al servidor recién creado.
        self.root.after(1200, self._conectar_para_demo)

    def _conectar_para_demo(self):
        """
        Conecta y autentica automáticamente tras el arranque de la demo.
        """
        if not self.is_connected:
            self.conectar()
        elif not self.is_authenticated:
            self.autenticar()
        self.notebook.select(0)

    def _escuchar_proceso(self, etiqueta: str, proceso: subprocess.Popen):
        """
        Lanza un hilo demonio que vuelca la salida del proceso a la cola.

        Tkinter no se toca desde este hilo: solo se encola texto, y el hilo
        principal lo drena periódicamente.
        """
        def bombeo():
            try:
                for linea in proceso.stdout:
                    self.salida_procesos.put((etiqueta, linea.rstrip()))
            except (ValueError, OSError):
                pass
            finally:
                self.salida_procesos.put((etiqueta, "<< proceso terminado >>"))

        hilo = threading.Thread(target=bombeo, daemon=True)
        hilo.start()

    def _drenar_salida_procesos(self):
        """
        Vuelca al log lo producido por los procesos hijo. Se ejecuta en el
        hilo principal de Tk, disparado por `after()`.
        """
        try:
            while True:
                etiqueta, linea = self.salida_procesos.get_nowait()
                if linea:
                    self._registrar(etiqueta, linea, "proc")
        except queue.Empty:
            pass

        self._refrescar_lista_procesos()
        self.root.after(400, self._drenar_salida_procesos)

    def _refrescar_lista_procesos(self):
        """
        Actualiza la lista con el estado vivo de cada proceso hijo.
        """
        if not hasattr(self, "lista_procesos"):
            return

        self.lista_procesos.delete(0, "end")
        for nombre, proceso in self.procesos:
            codigo = proceso.poll()
            estado = "activo" if codigo is None else f"terminado (código {codigo})"
            self.lista_procesos.insert("end", f"{nombre:<18} PID {proceso.pid:<7} {estado}")

    def detener_demo(self):
        """
        Termina todos los procesos hijo lanzados por la demo.
        """
        if not self.procesos:
            return

        for nombre, proceso in list(self.procesos):
            if proceso.poll() is None:
                try:
                    proceso.terminate()
                except OSError:
                    pass

        self._registrar("Sistema", "Enviando terminación a los procesos de la demo...", "sys")

        for nombre, proceso in list(self.procesos):
            try:
                proceso.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    proceso.kill()
                except OSError:
                    pass

        self.procesos.clear()

        self.boton_iniciar.configure(state="normal")
        self.boton_detener.configure(state="disabled")
        self._refrescar_lista_procesos()
        self._registrar("Sistema", "Demo detenida.", "sys")
        self.desconectar()

    # =====================================================================
    # LOG Y CIERRE
    # =====================================================================

    def _registrar(self, origen: str, mensaje: str, categoria: str):
        """
        Añade una línea al log de tráfico, recortando si excede el máximo.
        """
        if not hasattr(self, "log"):
            return

        if self.log.index("end-1c").split(".")[0] and int(self.log.index("end-1c").split(".")[0]) > MAX_LOG_LINES:
            self.log.delete("1.0", "100.0")

        marca = time.strftime("%H:%M:%S")
        ancho_origen = 14
        self.log.insert("end", f"{marca}  {origen:<{ancho_origen}} {mensaje}\n", categoria)
        self.log.see("end")

    def limpiar_log(self):
        """
        Vacía el log de tráfico.
        """
        self.log.delete("1.0", "end")

    def cerrar(self):
        """
        Cierre ordenado: detener demo, cerrar socket y salir.
        """
        if self.procesos:
            for _, proceso in self.procesos:
                if proceso.poll() is None:
                    proceso.terminate()
        self._cerrar_socket()
        self.root.destroy()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dashboard SDMR (cliente NETMON/1.0)")
    parser.add_argument("--demo", action="store_true", help="Levanta servidor + agentes automáticamente al abrir")
    parser.add_argument("--agentes", type=int, default=None, help="Cantidad de agentes para la demo (1-6)")
    parser.add_argument("--udp", type=int, default=None, help="Puerto UDP de telemetría")
    parser.add_argument("--tcp", type=int, default=None, help="Puerto TCP de comandos")
    parser.add_argument("--host", default=None, help="IP del servidor central")
    args = parser.parse_args()

    opciones = {
        "demo": args.demo,
        "agentes": args.agentes,
        "udp": args.udp,
        "tcp": args.tcp,
        "host": args.host,
    }

    raiz = tk.Tk()
    dashboard = SDMRMonitorGUI(raiz, opciones)

    def _reportar_error(exc, valor, traza):
        """
        Muestra los errores de los callbacks de Tk.

        Tk se los silencia a si mismo y eso oculta fallos reales de la
        interfaz (una etiqueta mal actualizada, por ejemplo), asi que se
        escriben tambien en el log de trazas.
        """
        texto = "".join(traceback.format_exception(exc, valor, traza))
        print(f"[GUI] Error no controlado:\n{texto}")
        dashboard._registrar("GUI", f"Error: {exc.__name__}: {valor}", "err")

    raiz.report_callback_exception = _reportar_error
    raiz.mainloop()
