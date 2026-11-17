# Manual de Uso – SDMR

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

**Opción A — Por terminal** (una terminal por cada equipo a monitorear):
```bash
# Sintaxis: python agent/agent.py <ID_NODO> <IP_SERVIDOR> <PUERTO_UDP> [PUERTO_CMD_TCP]
python agent/agent.py NODO_01 127.0.0.1 5000 5002
python agent/agent.py NODO_02 TU_IP 5000 5004
```
*El último parámetro es el puerto TCP donde el agente atiende `EXEC`.
**Cada agente en la misma máquina necesita un puerto distinto**
(5002, 5004, …). Si cada agente vive en una máquina distinta, todos pueden
usar el `5002`. En el otro equipo también sirven los lanzadores
`scripts/agente_remoto.bat TU_IP NODO_02` / `./scripts/agente_remoto.sh TU_IP NODO_02`.*

**Opción B — Con un click (mini interfaz, sin terminal):** en el equipo
cliente ejecutá una sola vez `scripts/agent/crear_accesos.sh` (Linux) o
`scripts\agent\crear_accesos.bat` (Windows) para dejar un acceso directo en
el Escritorio. A partir de ahí, doble clic en "SDMR Control Agente" abre una
ventanita (tema oscuro) con un campo **Servidor (IP)** —escribí ahí la IP del
equipo donde corre el servidor para apuntar el agente a **otra PC de la red**;
si lo dejás vacío, lo descubre solo por broadcast—, un campo **ID del nodo**
opcional, y los botones **Iniciar / Detener / Estado / Abrir log**. La IP queda
guardada en `agent/config.ini`, así la próxima vez ya aparece. El agente
arranca oculto. También se puede abrir manualmente:
```bash
python scripts/agent/agent_control.py
```

#### 4️⃣ Verificar que todo llega (CUARTO, recomendado)
Desde cualquier equipo:
```bash
# Sintaxis: python tools/verificar_red.py <IP_SERVIDOR> [UDP] [TCP] [WS]
python tools/verificar_red.py TU_IP 5000 5001 5003
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

#### C. Web React (tema NOC oscuro, navegador, PC o celu)
Requiere el gateway del paso 2 en marcha. Si `web/dist/` no existe,
compilar una vez: `cd web && npm install && npm run build`.

Interfaz con paleta oscura de centro de operaciones (acento cian, estados en
verde/ámbar/rojo) y pestaña **Topología** interactiva: diagrama radial con el
servidor al centro, iconos según el tipo de dispositivo y un panel de detalle
(IP, estado, CPU/RAM/Disco, actualización). El tipo se infiere del ID del nodo
(`IMPRESORA_*`, `SRV_*`, `ROUTER_*`, resto = computadora) y puede cambiarse por
nodo; en la web la elección se guarda en `localStorage`. No modifica el
protocolo `NETMON/1.0`.
```bash
# Abrir en el navegador:
http://127.0.0.1:5173        # en la misma PC
http://TU_IP:5173            # desde otro equipo o el celu
```
*En el Login, campo **Gateway**: `ws://127.0.0.1:5003` (misma PC) o
`ws://TU_IP:5003` (red). Usuario `admin` / `admin123`.*

#### D. Servicio HTTP extra "Red (extra)" (opcional, NO usa NETMON/1.0)

Servicio auxiliar para diagnóstico de red (descubrimiento de hosts en la LAN).
Es INDEPENDIENTE del protocolo NETMON/1.0: no usa UDP 5000 / TCP 5001 / WS 5003
y no toca el servidor central. Si se retira, el SDMR queda intacto.

```bash
# Terminal aparte, en el equipo servidor:
python extras/lan_scan_service.py 8090
```

Luego abrí la web (http://TU_IP:5173) y andá a la pestaña **"Red (extra)"**:
pone la subred (ej. 192.168.1.0/24) y pulsá "Escanear LAN". La sección muestra
un texto explicativo para la defensa que aclara que NO usa NETMON/1.0.

Requiere Scapy + Npcap solo si querés ARP scan real; si no, usa fallback `arp -a`.

#### E. App móvil con Expo Go (celu/tablet Android)
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
*La app usa el mismo tema NOC oscuro e incluye la pestaña **Topología**
interactiva (dibujada con `react-native-svg`): tocá un nodo para ver sus
recursos y cambiar su tipo durante la sesión.*
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
./scripts/agente_remoto.sh 192.168.1.50 NODO_02
```
**Windows:**
```bat
scripts/agente_remoto.bat 192.168.1.50 NODO_02
```
El ID de nodo es opcional (por defecto usa el hostname del equipo); el puerto
UDP por defecto es `5000` y el del canal `EXEC` es `5002`. Sintaxis completa:
`<IP_SERVIDOR> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]`.

> **Sin terminal (con un botón):** en el otro equipo corré una vez
> `scripts/agent/crear_accesos.sh` (o `scripts\agent\crear_accesos.bat`), abrí
> el icono **"SDMR Control Agente"**, escribí la IP del servidor (ej.
> `192.168.1.50`) en el campo **Servidor (IP)** y tocá **Iniciar**. La IP queda
> recordada para la próxima vez.

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
python3 tools/verificar_red.py 192.168.1.50 5000 5001 5003
```
Comprueba `[1/3]` PING TCP, `[2/3]` telemetría UDP registrada y `[3/3]`
gateway WS para web/móvil. Si algo falla, indica si el problema es la IP o el
firewall, y sugiere las reglas a abrir.

### 6. Auto-instalacion del agente (sin terminal, al iniciar sesion)

Para dejar un equipo cliente monitoreandose solo, sin abrir terminales:

**Windows (en el equipo cliente, dentro de la carpeta del proyecto):**
```bat
scripts\instalar_agente.bat                # IP por broadcast (automatico)
scripts\instalar_agente.bat 192.168.1.50    # IP fija en agent\config.ini
scripts\instalar_agente.bat 192.168.1.50 LAPTOP-JUAN
```
**Linux / macOS:**
```bash
./scripts/instalar_agente.sh
./scripts/instalar_agente.sh 192.168.1.50 NODO_02
```
Que hace: escribe agent/config.ini, crea el acceso directo de arranque
(carpeta de Inicio en Windows / ~/.config/autostart en Linux), abre la regla
de firewall del canal EXEC (TCP 5002) si hay administrador, y arranca el agente
oculto (pythonw.exe / nohup). Para quitarlo: scripts\desinstalar_agente.bat /
./scripts/desinstalar_agente.sh.

**Control manual con un click (sin terminal):** además de la instalación
automática, en `scripts/agent/` hay una mini interfaz (`agent_control.py`) y
los creadores de accesos directos `crear_accesos.sh` / `crear_accesos.bat`.
Ejecutalos una vez para dejar en el Escritorio "SDMR Control Agente", que abre
una ventanita con botones **Iniciar / Detener / Estado / Abrir log** para
controlar el agente de esa máquina sin tocar la terminal.

**Descubrimiento automatico (broadcast):** si no se pasa la IP del servidor (o
config.ini tiene ip_servidor vacio), el agente emite SRVREQ por broadcast
y el Servidor Central responde SRVINFO con su IP y puertos. No hace falta
saber la IP del servidor de antemano. El dashboard incluye el boton
"Copiar comando para clientes" que copia el comando de instalacion con la IP
del servidor al que esta conectado.

El agente corre sin ventana y escribe su log en agent/agente.log (rotacion
automatica a 512 KB).

### 7. En otro equipo: administrar con el cliente o el dashboard

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
| **Red (extra)** | Descubrimiento de hosts en la LAN (Scapy opcional con fallback a `arp -a`): IP, MAC y hostname. Módulo aislado en `extras/`, no toca el core SDMR. |

El texto de las dos últimas pestañas vive en `client/contenido_ayuda.py`
(`INSTRUCCIONES` y `CONCEPTOS`): las definiciones están copiadas literalmente
del PDF de Kurose que acompaña el trabajo, sin modificar, y no requieren tener
el archivo presente en tiempo de ejecución.

Notas:
* Requiere un servidor con Tk instalado. En Linux suele necesitar `sudo apt install python3-tk`
  (o simplemente ejecutá `./scripts/instalar.sh`, que lo deja listo).
* La actualización del dashboard usa `after()` en el hilo principal de Tk, porque Tkinter no es thread-safe.
* Si los puertos 5000/5001 están ocupados, la demo **avanza automáticamente al
  siguiente par de puertos libres** y lo informa en el log.

---

## 🧪 Pruebas Automatizadas de Integración

Ejecuta una batería **no interactiva** que levanta el servidor y 3 agentes en
puertos libres, y verifica las pruebas de la consigna del TPI:

```bash
python3 tools/test_system.py
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
