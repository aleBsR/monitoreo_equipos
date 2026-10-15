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
│   └── server.py            # Servidor concurrente TCP (5001) y UDP (5000) + watchdog
├── agent/
│   ├── __init__.py
│   └── agent.py             # Agente: telemetría UDP + canal TCP de comandos EXEC
├── client/
│   ├── __init__.py
│   ├── admin_client.py      # Cliente de administración interactivo (CLI)
│   ├── gui_monitor.py       # Dashboard gráfico (Tkinter) — cliente adicional
│   └── contenido_ayuda.py   # Texto de las pestañas de ayuda (instrucciones y conceptos)
├── sdmr                     # Lanzador Linux: abre todo con un comando
├── instalar.sh              # Instalador Linux (crea el comando 'sdmr' y el acceso de menú)
├── iniciar_sdmr.bat         # Lanzador Windows (doble clic)
├── crear_acceso_directo.bat # Crea el acceso directo del Escritorio en Windows
├── requirements.txt         # Dependencia opcional (psutil)
├── test_system.py           # Pruebas de integración automatizadas
└── propuesta_tpi.md         # Documentación de diseño y arquitectura
```

---

## 🚀 Guía de Instalación y Ejecución

### Prerrequisitos
* **Python 3.8+** instalado.
* **Tkinter** (interfaz gráfica, parte de la biblioteca estándar). En Linux suele
  requerir el paquete del sistema `python3-tk`.
* (Opcional) Instalar dependencias para medir recursos reales:
  ```bash
  pip install -r requirements.txt
  ```

---

### ⚡ Inicio rápido (todo con un comando)

La forma más simple de ver el sistema completo (dashboard + servidor + agentes)
sin abrir varias terminales.

**Linux (Debian/Ubuntu):**
```bash
./instalar.sh     # una sola vez: instala tkinter/psutil y crea el comando 'sdmr'
sdmr              # abre el dashboard con servidor + 3 agentes en marcha
```
Opciones: `sdmr --agentes 5`, `sdmr --udp 6000 --tcp 6001`,
`sdmr --host 192.168.0.10 --tcp 5001` (para conectarse a otro equipo).
Si preferís no instalar nada global, `./sdmr` funciona igual desde la carpeta.

**Windows:**
* Doble clic en `iniciar_sdmr.bat`.
* Para tener un ícono en el Escritorio, ejecutá una vez
  `crear_acceso_directo.bat` (crea el acceso directo que apunta al `.bat`).

> El lanzador abre la pestaña **Demo**, que levanta el servidor y los agentes
> como procesos hijo y conecta el dashboard automáticamente.

---

### Modo de Uso (Paso a Paso)

#### 1️⃣ Iniciar el Servidor Central
Abre una terminal y ejecuta:
```bash
python3 server/server.py
```
*El servidor comenzará a escuchar en `UDP:5000` y `TCP:5001`.*

#### 2️⃣ Iniciar uno o varios Agentes de Monitoreo
Abre otra terminal para cada agente a monitorear:
```bash
# Sintaxis: python3 agent/agent.py <ID_NODO> <IP_SERVIDOR> <PUERTO_UDP> [PUERTO_CMD_TCP]
python3 agent/agent.py NODO_01 127.0.0.1 5000 5002
python3 agent/agent.py NODO_02 127.0.0.1 5000 5003
```
*El último parámetro es el puerto TCP donde el agente atiende comandos `EXEC`.
Si se omiten varios agentes en la misma máquina, cada uno necesita un puerto
distinto (por defecto 5002).*

#### 3️⃣ Iniciar la Consola de Administración (Cliente TCP)
Abre una nueva terminal:
```bash
# Sintaxis: python3 client/admin_client.py <IP_SERVIDOR> <PUERTO_TCP>
python3 client/admin_client.py 127.0.0.1 5001
```

**Credenciales de Administrador por defecto:**
* **Usuario:** `admin` | **Contraseña:** `admin123`
* **Usuario:** `operador` | **Contraseña:** `operador123`

---

## 🖥️ Interfaz Gráfica (Dashboard Tkinter)

Para mostrar el proyecto de forma visual, existe un dashboard construido con
`tkinter` (biblioteca estándar, sin dependencias extra):

```bash
python3 client/gui_monitor.py            # abre el dashboard
python3 client/gui_monitor.py --demo     # abre y levanta servidor + agentes solo
```

Opciones: `--agentes N`, `--udp <puerto>`, `--tcp <puerto>`, `--host <ip>`.

Es un **cliente adicional** que habla el mismo protocolo `NETMON/1.0` por TCP;
no reemplaza a la consola `admin_client.py` ni a los agentes socket nativos.

Incluye cinco pestañas:

| Pestaña | Para qué sirve |
| :--- | :--- |
| **Nodos** | Tabla con la telemetría en vivo: ID, IP, estado y barras de CPU / RAM / Disco. Doble clic en una fila para usarla como destino de `EXEC`. |
| **Demo Local** | Levanta el Servidor + N Agentes en procesos separados con un clic, conecta el dashboard automáticamente y permite detener todo. Ideal para una demostración de punta a punta sin abrir varias terminales. |
| **Tráfico NETMON/1.0** | Volcado de cada trama `TX`/`RX` tal cual viaja por el socket, más un campo para enviar tramas inválidas a propósito y ver cómo el servidor responde con `ERR_100` / `ERR_103` sin cortar la conexión (RF07). |
| **Instrucciones de uso** | Guía integrada: inicio rápido, modo manual en tres terminales, pestañas, comandos `NETMON/1.0`, puertos, pruebas y problemas frecuentes. |
| **Conceptos TCP/UDP** | Definiciones de la bibliografía (Kurose, 5.ª ed.) con buscador: protocolo, socket, cliente/servidor, TCP, UDP, segmento/datagrama, multiplexación, puertos, control de flujo y handshake. Cada una indica capítulo y página. |

El texto de las dos últimas pestañas vive en `client/contenido_ayuda.py`
(`INSTRUCCIONES` y `CONCEPTOS`): las definiciones están copiadas literalmente
del PDF de Kurose que acompaña el trabajo, sin modificar, y no requieren tener
el archivo presente en tiempo de ejecución.

Notas:
* Requiere un servidor con Tk instalado. En Linux suele necesitar `sudo apt install python3-tk`
  (o simplemente ejecutá `./instalar.sh`, que lo deja listo).
* La actualización del dashboard usa `after()` en el hilo principal de Tk, porque Tkinter no es thread-safe.
* Si los puertos 5000/5001 están ocupados, la demo **avanza automáticamente al
  siguiente par de puertos libres** y lo informa en el log.

---

## 🧪 Pruebas Automatizadas de Integración

Ejecuta una batería **no interactiva** que levanta el servidor y 3 agentes en
puertos libres, y verifica las pruebas de la consigna del TPI:

```bash
python3 test_system.py
```

| Prueba | Qué verifica |
| :--- | :--- |
| 1 | Cliente único: `PING`, `AUTH`, `GET_NODES` |
| 2 | Múltiples clientes simultáneos |
| 3 | Desconexión abrupta y a mitad de operación |
| 4 | Datos inválidos / malformados (RF07) |
| 5 | Servidor no disponible |
| 6 | Encuadrado de tramas TCP (trama partida y dos juntas) |
| 7 | Watchdog: nodo `OFFLINE` por inactividad |
| 8 | Concurrencia entre clientes |
| EXEC | Ejecución remota real: permitida, rechazada y nodo inexistente |

Al final imprime `N/N verificaciones exitosas` y devuelve código de salida 0
si todo pasó.

---

## 📊 Análisis de Tráfico de Red (Wireshark)

Para inspeccionar el tráfico generado durante la evaluación:
* **Filtro TCP:** `tcp.port == 5001` (Muestra el Handshake `SYN`, `SYN-ACK`, `ACK`, envío de comandos y cierre `FIN`).
* **Filtro UDP:** `udp.port == 5000` (Muestra la ráfaga continua de datagramas de telemetría).

---

## 📄 Licencia

Este proyecto fue desarrollado con fines educativos para la asignatura **Programación de Redes con Sockets**.
