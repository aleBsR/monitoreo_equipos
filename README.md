# 📡 Sistema Distribuido de Monitoreo en Red (SDMR)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/Protocol-NETMON%2F1.0-orange.svg)](#-protocolo-de-aplicación-netmon10)

Aplicación distribuida basada en el modelo **Cliente/Servidor** desarrollada para la asignatura **Programación de Redes con Sockets (Optativa III - LAS)**.

El sistema permite supervisar en tiempo real la disponibilidad, métricas de rendimiento y salud (CPU, Memoria RAM y Uso de Disco) de múltiples computadoras (nodos) distribuidas en una red local, además de permitir la ejecución de acciones administrativas de forma remota.


---

## 🌟 Características Principales

* **Uso Dual de Sockets (TCP & UDP):**
  * **UDP (Puerto 5000):** Canal sin conexión de alta velocidad y baja latencia para el envío periódico de telemetría y *heartbeats* desde los nodos hacia el servidor.
  * **TCP (Puerto 5001):** Canal orientando a conexión y confiable para la autenticación de administradores, consulta de estado de la red, ejecución de comandos remotos y alertas.
* **Servidor Concurrente Multihilo:**
  * Atiende a **múltiples clientes y agentes simultáneamente** utilizando hilos independientes (`threading`).
  * Utiliza mecanismos de exclusión mutua (`threading.Lock`) para garantizar la integridad del registro de nodos en memoria (*thread-safety*).
* **Guardián de Inactividad (Watchdog):**
  * Monitor en segundo plano que detecta si un nodo deja de transmitir telemetría UDP durante más de 15 segundos y lo marca automáticamente como `OFFLINE`.
* **Protocolo de Aplicación Propio (`NETMON/1.0`):**
  * Formato claro basado en cadenas delimitadas por tuberías (`|`), con códigos de respuesta (`OK`, `ERR`) y errores tipificados.
* **Resiliencia y Manejo de Errores (RF07):**
  * Validación estricta de encabezados, parámetros e integridad lógica. El servidor no colapsa ni cierra conexiones abruptamente ante mensajes malformados o datos inválidos.
* **Captura de Métricas Reales:**
  * Uso de `psutil` para monitorear hardware real (con fallback a simulación si la librería no está instalada).

---

## 🏗️ Arquitectura del Sistema

```
                  ┌───────────────────────────────────────────┐
                  │       SERVIDOR CENTRAL DE MONITOREO       │
                  │                                           │
                  │  ┌─────────────────┐ ┌─────────────────┐  │
                  │  │ Socket UDP      │ │ Socket TCP      │  │
                  │  │ Puerto 5000     │ │ Puerto 5001     │  │
                  │  └────────┬────────┘ └────────┬────────┘  │
                  └───────────┼───────────────────┼───────────┘
                              │                   │
            UDP (Métricas/Heartbeats)        TCP (Control/Alertas/Logs)
             Baja latencia, periódico           Entrega garantizada
                              │                   │
             ┌────────────────┴───────┐ ┌─────────┴────────────────┐
             │                        │ │                          │
     ┌───────▼────────┐      ┌────────▼─▼──────┐          ┌────────▼────────┐
     │ Agente Nodo 1  │      │ Agente Nodo 2   │          │ Cliente Admin   │
     │ (Equipo Red)   │      │ (Equipo Red)    │          │ (Consola/Dash)  │
     └────────────────┘      └─────────────────┘          └─────────────────┘
```

---

## 📜 Protocolo de Aplicación `NETMON/1.0`

### 📤 Canal UDP (Telemetría / Heartbeat)
* **Formato:** `MON|<ID_NODO>|<IP>|<CPU_%>|<RAM_%>|<DISK_%>|<STATUS>[|<PUERTO_CMD>]`
* **Ejemplo:** `MON|NODO_01|192.168.1.50|35.4|62.1|40.0|OK|5002`
* El último campo `PUERTO_CMD` es **opcional**: indica el puerto TCP donde el
  agente escucha órdenes `EXEC`. El parseo acepta el formato con y sin ese campo.

### 📥 Canal TCP (Comandos y Respuestas)
* **Autenticación:**
  * *Solicitud:* `CMD|AUTH|<USUARIO>|<PASSWORD>`
  * *Respuesta:* `RES|OK|AUTH_SUCCESS|Bienvenido admin`
* **Consulta de Nodos:**
  * *Solicitud:* `CMD|GET_NODES|ALL`
  * *Respuesta:* `RES|OK|NODES_COUNT:2;NODO_01:...;NODO_02:...`
* **Ejecución Remota (real, extremo a extremo):**
  * *Solicitud (admin → servidor):* `CMD|EXEC|<ID_NODO>|<COMANDO>`
  * *Servidor → Agente:* `EXECCMD|<COMANDO>` (conexión TCP al puerto de control del nodo)
  * *Agente → Servidor:* `RES|OK|<COMANDO>|<resultado>`
  * *Respuesta final:* `RES|OK|EXEC_SUCCESS|[NODO_01] Servicio reiniciado correctamente`
  * Comandos permitidos del agente: `RESTART_SERVICE`, `DIAGNOSTIC`, `CLEAR_LOGS`.
    Cualquier otro se rechaza con `ERR_104`. El agente registra cada orden en
    `agent/historial_comandos.log`.

### ⚠️ Catálogo de Errores Tipificados
* `ERR_100`: Mensaje malformado o falta de parámetros obligatorios.
* `ERR_101`: Autenticación requerida o credenciales inválidas.
* `ERR_102`: El nodo especificado no existe o se encuentra `OFFLINE`.
* `ERR_103`: El comando solicitado no existe en el protocolo.
* `ERR_104`: El nodo no respondió, no tiene canal de comandos o no soporta el `EXEC`.

### 🧩 Encuadrado de tramas (Framing)
TCP es un flujo de bytes: un mensaje puede llegar partido o varios mensajes
juntos. Servidor, cliente y agente separan las tramas con un acumulador común
(`TcpFrameReader` en `common/protocol.py`) que corta por `\n`, con un tope de
8 KB por trama para descartar basura que nunca cierra.

---

## 📁 Estructura del Repositorio

```
.
├── common/
│   ├── __init__.py
│   └── protocol.py          # Definición, codificación, parseo y encuadrado del protocolo NETMON/1.0
├── server/
│   ├── __init__.py
│   ├── server.py            # Servidor concurrente TCP (5001) y UDP (5000) + watchdog
│   └── gateway.py           # Puente WS (5003) → TCP (5001) para web y móvil (reenvío transparente NETMON/1.0)
├── agent/
│   ├── __init__.py
│   └── agent.py             # Agente: telemetría UDP + canal TCP de comandos EXEC
├── client/
│   ├── __init__.py
│   ├── admin_client.py      # Cliente de administración interactivo (CLI)
│   ├── gui_monitor.py       # Dashboard gráfico (Tkinter) — cliente adicional
│   └── contenido_ayuda.py   # Texto de las pestañas de ayuda (instrucciones y conceptos)
├── web/                     # Cliente web React (tema NOC oscuro) — habla NETMON/1.0 vía gateway WS
│   ├── package.json         #   src/: App.jsx, components/Topologia.jsx, lib/{netmon,deviceType}.js, styles.css
├── mobile/                  # Cliente móvil React Native (Expo Go) — mismo protocolo vía gateway WS
│   ├── package.json         #   App.js, Topologia.js, theme.js, deviceType.js, netmon.js, app.json
├── scripts/                 # Lanzadores (doble clic / un comando)
│   ├── scripts/iniciar_todo.bat     #   Windows TODO-EN-UNO: servidor + gateway + web + 2 agentes + verificación
│   ├── iniciar_todo.sh      #   Linux TODO-EN-UNO (equivalente al .bat)
│   ├── scripts/iniciar_sdmr.bat     #   Windows solo Tkinter en modo Demo
│   ├── scripts/crear_acceso_directo.bat # Acceso directo del Escritorio (Windows)
│   ├── scripts/agente_remoto.bat / .sh # Agente apuntando a otro equipo (red local)
│   ├── sdmr                 #   Lanzador Linux: dashboard + demo
│   └── instalar.sh          #   Instalador Linux (comando global 'sdmr' + menú)
├── tools/
│   ├── verificar_red.py     # Diagnóstico TCP + UDP + WS (gateway) hacia el servidor
│   └── test_system.py       # Pruebas de integración automatizadas
├── docs/                    # Propuesta, bibliografía (Kurose PDF) y consigna del TP
│   └── propuesta_tpi.md     #   (propuesta.md, .ppt y .pdf en la misma carpeta)
├── requirements.txt         # psutil (métricas reales) + websockets (gateway)
└── LEEME_OTRA_PC.md         # Guía corta para replicar el entorno en otra PC
```

---

## 🚀 Guía de Instalación y Ejecución

### Prerrequisitos
* **Python 3.8+** instalado.
* **Tkinter** (interfaz gráfica, parte de la biblioteca estándar). En Linux suele
  requerir el paquete del sistema `python3-tk`.
* Instalar dependencias Python (métricas reales + gateway WS):
  ```bash
  pip install -r requirements.txt
  ```
* Solo para web/móvil: **Node.js 18+** (`node --version`). La app móvil además
  necesita **Expo Go** (Play Store) en el celu/tablet.

---

### ⚡ Inicio rápido (todo con un comando)

La forma más simple de ver el sistema completo (dashboard + servidor + agentes)
sin abrir varias terminales.

**Linux (Debian/Ubuntu):**
```bash
./scripts/instalar.sh     # una sola vez: instala tkinter/psutil y crea el comando 'sdmr'
sdmr              # abre el dashboard con servidor + 3 agentes en marcha
```
Opciones: `sdmr --agentes 5`, `sdmr --udp 6000 --tcp 6001`,
`sdmr --host 192.168.0.10 --tcp 5001` (para conectarse a otro equipo).
Si preferís no instalar nada global, `./scripts/sdmr` funciona igual desde la carpeta.

**Windows:**
* Doble clic en `scripts/iniciar_todo.bat` → **recomendado**: levanta servidor +
  gateway + web + 2 agentes y verifica la red solo (ver § Orden de encendido).
* Doble clic en `scripts/iniciar_sdmr.bat` → solo dashboard Tkinter en modo Demo.
* Para tener un ícono en el Escritorio, ejecutá una vez
  `scripts/crear_acceso_directo.bat` (crea el acceso directo que apunta al `.bat`).

> El lanzador abre la pestaña **Demo**, que levanta el servidor y los agentes
> como procesos hijo y conecta el dashboard automáticamente.

---

### 📋 Orden de encendido (resumen)

> **Regla de oro:** el **servidor siempre primero**, los clientes después.
> La app del celu, la web y los dashboards son **clientes**: sin servidor
> corriendo en la PC muestran "sin conexión".

| # | Qué | Archivo / comando | Dónde |
| :-: | :--- | :--- | :--- |
| 0 | Preparar red + IP + firewall | `ipconfig` + reglas `netsh`/`ufw` (ver abajo) | PC servidor, una sola vez por red |
| 1 | Servidor central | `python server/server.py` | PC servidor, terminal 1 |
| 2 | Gateway WS + web | `python server/gateway.py 5003 127.0.0.1 5001 --serve-web` | PC servidor, terminal 2 |
| 3 | Agentes (uno por equipo a monitorear) | `python agent/agent.py <ID> <IP_SERVIDOR> 5000 <PUERTO_CMD>` | Cada equipo, una terminal por agente |
| 4 | Verificación | `python tools/verificar_red.py <IP_SERVIDOR> 5000 5001 5003` | Cualquier equipo (esperar 3/3 OK) |
| 5 | Clientes a elección | CLI / Tkinter / web / móvil (ver sección Clientes) | Donde corresponda |

**Credenciales de Administrador por defecto:**
* **Usuario:** `admin` | **Contraseña:** `admin123`
* **Usuario:** `operador` | **Contraseña:** `operador123`

---

> **Manual de uso:** [MANUAL.md](MANUAL.md) — uso detallado, clientes, pruebas y análisis de red.
