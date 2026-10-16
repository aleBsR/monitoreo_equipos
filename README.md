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
├── web/                     # Cliente web React (estilo Instagram) — habla NETMON/1.0 vía gateway WS
│   ├── package.json         #   src/: App.jsx, lib/netmon.js, styles.css · dist/: build para demo offline
├── mobile/                  # Cliente móvil React Native (Expo Go) — mismo protocolo vía gateway WS
│   ├── package.json         #   App.js, netmon.js, index.js, app.json, babel.config.js
├── sdmr                     # Lanzador Linux: abre todo con un comando
├── instalar.sh              # Instalador Linux (crea el comando 'sdmr' y el acceso de menú)
├── iniciar_sdmr.bat         # Lanzador Windows (doble clic, solo Tkinter)
├── iniciar_todo.bat         # Lanzador Windows TODO-EN-UNO: servidor + gateway + web + 2 agentes + verificación
├── iniciar_todo.sh          # Lanzador Linux TODO-EN-UNO (equivalente al .bat)
├── crear_acceso_directo.bat # Crea el acceso directo del Escritorio en Windows
├── agente_remoto.sh         # Lanzador Linux: agente apuntando a otro equipo (red local)
├── agente_remoto.bat        # Lanzador Windows: agente apuntando a otro equipo (red local)
├── verificar_red.py         # Diagnóstico de conectividad TCP + UDP + WS (gateway) hacia el servidor
├── requirements.txt         # psutil (métricas reales) + websockets (gateway)
├── test_system.py           # Pruebas de integración automatizadas
└── propuesta_tpi.md         # Documentación de diseño y arquitectura
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
./instalar.sh     # una sola vez: instala tkinter/psutil y crea el comando 'sdmr'
sdmr              # abre el dashboard con servidor + 3 agentes en marcha
```
Opciones: `sdmr --agentes 5`, `sdmr --udp 6000 --tcp 6001`,
`sdmr --host 192.168.0.10 --tcp 5001` (para conectarse a otro equipo).
Si preferís no instalar nada global, `./sdmr` funciona igual desde la carpeta.

**Windows:**
* Doble clic en `iniciar_todo.bat` → **recomendado**: levanta servidor +
  gateway + web + 2 agentes y verifica la red solo (ver § Orden de encendido).
* Doble clic en `iniciar_sdmr.bat` → solo dashboard Tkinter en modo Demo.
* Para tener un ícono en el Escritorio, ejecutá una vez
  `crear_acceso_directo.bat` (crea el acceso directo que apunta al `.bat`).

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
| 4 | Verificación | `python verificar_red.py <IP_SERVIDOR> 5000 5001 5003` | Cualquier equipo (esperar 3/3 OK) |
| 5 | Clientes a elección | CLI / Tkinter / web / móvil (ver sección Clientes) | Donde corresponda |

**Credenciales de Administrador por defecto:**
* **Usuario:** `admin` | **Contraseña:** `admin123`
* **Usuario:** `operador` | **Contraseña:** `operador123`

---

### Modo de Uso detallado (paso a paso)

#### 0️⃣ Preparar la red (una vez por cada red/hotspot)

Todos los equipos (PCs, celus, tablet) deben estar en la **misma red**
(mismo WiFi o hotspot del celular).

Averiguar la IP del equipo servidor:

**Windows:**
```bat
ipconfig               # buscar "Dirección IPv4" de la interfaz activa (ej. 192.168.43.10)
```
**Linux:**
```bash
hostname -I            # muestra la IP de la LAN (ej. 192.168.1.50)
```

Abrir los puertos en el equipo SERVIDOR (una sola vez):

```bat
REM Windows (PowerShell/CMD como Administrador)
netsh advfirewall firewall add rule name="SDMR UDP" dir=in action=allow protocol=UDP localport=5000
netsh advfirewall firewall add rule name="SDMR TCP" dir=in action=allow protocol=TCP localport=5001
netsh advfirewall firewall add rule name="SDMR WS" dir=in action=allow protocol=TCP localport=5003
netsh advfirewall firewall add rule name="SDMR EXEC" dir=in action=allow protocol=TCP localport=5002,5004
netsh advfirewall firewall add rule name="Expo Metro" dir=in action=allow protocol=TCP localport=8081
```
```bash
# Linux (ufw)
sudo ufw allow 5000/udp
sudo ufw allow 5001/tcp
sudo ufw allow 5002,5003,5004/tcp
sudo ufw allow 8081/tcp    # solo si se usa la app móvil con Expo
```

> En los ejemplos de abajo, `TU_IP` es la IPv4 del servidor
> (ej. `192.168.43.10`). En la misma PC se usa `127.0.0.1`.

#### 1️⃣ Iniciar el Servidor Central (PRIMERO, siempre)
Terminal 1 en el equipo servidor:
```bash
# Sintaxis: python server/server.py [udp] [tcp]  (por defecto 5000 5001)
python server/server.py
```
*Escucha en `UDP:5000` (telemetría) y `TCP:5001` (comandos). Dejar esta
terminal abierta: si se cierra, todo lo demás se desconecta.*

#### 2️⃣ Iniciar el Gateway WS + web (SEGUNDO, solo si usarás celu o navegador)
Terminal 2 en el equipo servidor:
```bash
# Sintaxis: python server/gateway.py [ws] [tcp_host] [tcp_port] [--serve-web]
python server/gateway.py 5003 127.0.0.1 5001 --serve-web
```
* Puente **transparente** `WS 5003 → TCP 5001`: reenvía las tramas
  `NETMON/1.0` tal cual, sin traducir a REST (por eso en Wireshark se sigue
  viendo el mismo protocolo).
* Con `--serve-web` además publica la web compilada en
  `http://TU_IP:5173` (ideal para la defensa sin internet).

#### 3️⃣ Iniciar uno o varios Agentes de Monitoreo (TERCERO)
Una terminal por cada equipo a monitorear:
```bash
# Sintaxis: python agent/agent.py <ID_NODO> <IP_SERVIDOR> <PUERTO_UDP> [PUERTO_CMD_TCP]
python agent/agent.py NODO_01 127.0.0.1 5000 5002
python agent/agent.py NODO_02 TU_IP 5000 5004
```
*El último parámetro es el puerto TCP donde el agente atiende `EXEC`.
**Cada agente en la misma máquina necesita un puerto distinto**
(5002, 5004, …). Si cada agente vive en una máquina distinta, todos pueden
usar el `5002`. En el otro equipo también sirven los lanzadores
`agente_remoto.bat TU_IP NODO_02` / `./agente_remoto.sh TU_IP NODO_02`.*

#### 4️⃣ Verificar que todo llega (CUARTO, recomendado)
Desde cualquier equipo:
```bash
# Sintaxis: python verificar_red.py <IP_SERVIDOR> [UDP] [TCP] [WS]
python verificar_red.py TU_IP 5000 5001 5003
```
*Comprueba `[1/3]` PING TCP, `[2/3]` telemetría UDP registrada y
`[3/3]` gateway WS. Tiene que dar **3/3 OK** antes de abrir los clientes.*

---

### 📱💻 Clientes: cómo correr cada uno (QUINTO, a elección, varios a la vez)

Todos los clientes hablan el mismo protocolo `NETMON/1.0` contra el servidor.
Se pueden usar **en simultáneo** (CLI + Tkinter + web + 2 celus).

#### A. Consola de administración CLI (sin interfaz, menú de texto)
```bash
# Sintaxis: python client/admin_client.py <IP_SERVIDOR> <PUERTO_TCP>
python client/admin_client.py 127.0.0.1 5001
```
*Autenticarse (opción 2), listar nodos (3), EXEC (4), probar tramas
inválidas RF07 (5). Es el cliente "de referencia" de la materia.*

#### B. Dashboard Tkinter (PC, interfaz original)
```bash
python client/gui_monitor.py            # conectar a mano
python client/gui_monitor.py --demo     # levanta servidor + agentes solo y conecta
```
*En red local, escribir `TU_IP` en el campo "Servidor".*

#### C. Web React estilo Instagram (navegador, PC o celu)
Requiere el gateway del paso 2 en marcha. Si `web/dist/` no existe,
compilar una vez: `cd web && npm install && npm run build`.
```bash
# Abrir en el navegador:
http://127.0.0.1:5173        # en la misma PC
http://TU_IP:5173            # desde otro equipo o el celu
```
*En el Login, campo **Gateway**: `ws://127.0.0.1:5003` (misma PC) o
`ws://TU_IP:5003` (red). Usuario `admin` / `admin123`.*

#### D. App móvil con Expo Go (celu/tablet Android)
Requiere el gateway del paso 2 en marcha y el **puerto 8081 abierto**.
```bash
cd mobile
npm install                  # una sola vez (ya incluye @expo/ngrok local)
npm run start:tunel          # genera un QR (requiere internet la 1ª vez)
# o: npm start               # modo LAN, sin túnel, misma red obligatoria
```
*Escanear el QR con **Expo Go** (Play Store). En el Login poner
`ws://TU_IP:5003` (**la IP de la PC, nunca `127.0.0.1`**), `admin` /
`admin123`. Si Expo pide instalar `@expo/ngrok`, aceptar: ya está fijado
como dependencia local del proyecto.*
*Nota: el túnel solo trae la app al celu; el login sigue conectando por
WiFi local al gateway, así que PC y celu deben estar en la misma red.*

---

## 🌐 Prueba en 2+ equipos (red local)

El TP pide que la aplicación **se ejecute en al menos dos equipos o máquinas
virtuales conectadas en red** (§11). La arquitectura ya lo soporta: el servidor
escucha en `0.0.0.0` (todas las interfaces) y tanto los agentes como los
clientes reciben la IP del servidor como parámetro. Los pasos son los mismos
que en modo manual, cambiando `127.0.0.1` por la **IP de la red local del
equipo servidor**.

### 1. Averiguar la IP del equipo servidor

**Linux:**
```bash
hostname -I            # muestra la IP de la LAN (ej. 192.168.1.50)
```
**Windows:**
```bat
ipconfig               # buscar "Dirección IPv4" de la interfaz activa
```

> Ejemplo para el resto de la guía: el servidor tiene la IP **192.168.1.50**.

### 2. En el equipo SERVIDOR: abrir los puertos en el firewall

| Puerto | Protocolo | Para qué |
| :--- | :--- | :--- |
| `5000` | UDP | Telemetría / heartbeat de los agentes |
| `5001` | TCP | Comandos y autenticación de administradores |
| `5002`, `5004`, … | TCP | Canal `EXEC` de cada agente (en el equipo del agente; evitar el `5003`) |
| `5003` | TCP | Gateway WS para web y móvil (en el equipo servidor) |
| `8081` | TCP | Metro de Expo, solo si se usa la app móvil |
| `5173` | TCP | Web compilada (`--serve-web`), opcional |

```bash
# Linux (ufw)
sudo ufw allow 5000/udp
sudo ufw allow 5001/tcp
sudo ufw allow 5002,5003,5004/tcp
sudo ufw allow 5173,8081/tcp   # web + Expo móvil
```
```bat
REM Windows (PowerShell/CMD como Administrador)
netsh advfirewall firewall add rule name="SDMR UDP" dir=in action=allow protocol=UDP localport=5000
netsh advfirewall firewall add rule name="SDMR TCP" dir=in action=allow protocol=TCP localport=5001
netsh advfirewall firewall add rule name="SDMR WS" dir=in action=allow protocol=TCP localport=5003
netsh advfirewall firewall add rule name="SDMR EXEC" dir=in action=allow protocol=TCP localport=5002,5004
```

### 3. En el equipo SERVIDOR: iniciar el servidor

```bash
python3 server/server.py
```
(o el lanzador gráfico `sdmr`, cuya pestaña Demo también escucha en todas las
interfaces y por lo tanto ve a los agentes remotos).

### 4. En cada OTRO equipo: iniciar un agente apuntando al servidor

La forma más simple, con los lanzadores incluidos:

**Linux:**
```bash
./agente_remoto.sh 192.168.1.50 NODO_02
```
**Windows:**
```bat
agente_remoto.bat 192.168.1.50 NODO_02
```
El ID de nodo es opcional (por defecto usa el hostname del equipo); el puerto
UDP por defecto es `5000` y el del canal `EXEC` es `5002`. Sintaxis completa:
`<IP_SERVIDOR> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]`.

Si preferís el comando manual, es el mismo de siempre pero con la IP del
servidor:
```bash
python3 agent/agent.py NODO_02 192.168.1.50 5000 5002
```
> **Nota:** un puerto de comandos distinto por agente (5002, 5004, …) solo es
> necesario cuando **varios agentes corren en el mismo equipo**. Si cada agente
> vive en una máquina distinta, todos pueden usar el `5002`.
> **No usar el `5003`** para agentes: es el puerto del gateway WS.

### 5. Verificar la conectividad (opcional pero recomendado)

Desde cualquier equipo, antes o durante la demo:
```bash
python3 verificar_red.py 192.168.1.50 5000 5001 5003
```
Comprueba `[1/3]` PING TCP, `[2/3]` telemetría UDP registrada y `[3/3]`
gateway WS para web/móvil. Si algo falla, indica si el problema es la IP o el
firewall, y sugiere las reglas a abrir.

### 6. En otro equipo: administrar con el cliente o el dashboard

```bash
# Consola CLI
python3 client/admin_client.py 192.168.1.50 5001

# Dashboard gráfico (escribir 192.168.1.50 en el campo "Servidor")
python3 client/gui_monitor.py
```

> En una captura con Wireshark vas a ver que las IP de origen de cada agente
> son las **de su propia máquina** (no `127.0.0.1`), y el `EXEC` sale del
> servidor hacia esa IP en el puerto de comandos del agente.

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
* **Filtro EXEC:** `tcp.port == 5002` (la orden `EXECCMD|...` que el servidor envía al agente).

En una prueba entre 2+ equipos conviene documentar la IP de origen y destino de
cada paquete (sección §9 del TP): la telemetría UDP lleva como origen la IP de
la LAN del agente y como destino la IP del servidor, y el `EXEC` hace el camino
inverso.

---

## 📄 Licencia

Este proyecto fue desarrollado con fines educativos para la asignatura **Programación de Redes con Sockets**.
