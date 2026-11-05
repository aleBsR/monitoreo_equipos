# 📡 Análisis Integral del Proyecto SDMR y sus Protocolos de Red

Documento técnico de análisis arquitectónico, especificación de protocolos (Transporte y Aplicación `NETMON/1.0`) y desglose detallado de la implementación en código del **Sistema Distribuido de Monitoreo en Red (SDMR)**.

---

## 1. Propósito General y Contexto Académico

El proyecto implementa un **Sistema Distribuido de Monitoreo en Red (SDMR)** bajo el modelo **Cliente/Servidor**, diseñado para la asignatura *Programación de Redes con Sockets (Optativa III - LAS)*.

* **Objetivo funcional:** Supervisar en tiempo real métricas de hardware (CPU, Memoria RAM y Espacio en Disco) y disponibilidad de múltiples equipos (nodos) en una red local (LAN), además de permitir la ejecución remota de comandos administrativos de manera segura.
* **Restricción académica clave:** El núcleo del sistema utiliza **exclusivamente la API nativa de sockets de Python** (`socket` y `threading`) y el parseo manual de tramas de capa de aplicación, evitando frameworks web/REST (como Django o FastAPI) o librerías que oculten la capa de transporte en el servidor principal, con el fin de demostrar el dominio explícito de **TCP** y **UDP**.

---

## 2. Mapa de Componentes del Proyecto

| Directorio / Archivo | Rol dentro de la Arquitectura |
| :--- | :--- |
| `common/protocol.py` | Especificación centralizada del protocolo `NETMON/1.0`, constructores/validadores de tramas, catálogo de errores y encuadrado TCP (`TcpFrameReader`). |
| `server/server.py` | **Servidor Central (`MonitoringServer`)**: escucha telemetría y descubrimiento por UDP (`:5000`), atiende administradores por TCP concurrente (`:5001`), ejecuta el hilo guardián (*Watchdog*) y envía órdenes `EXECCMD` por TCP a los agentes. |
| `server/gateway.py` | **Puente WebSocket → TCP (`puente_ws_tcp`)**: túnel transparente en el puerto `:5003` que reenvía tramas `NETMON/1.0` crudas entre clientes Web/Móvil y el puerto TCP `:5001` del servidor. También puede servir el frontend compilado en `:5173` (`--serve-web`). |
| `agent/agent.py` | **Agente de Monitoreo (`SystemNodeAgent`)**: recolecta métricas reales con `psutil` (o simuladas como fallback), descubre al servidor por broadcast UDP, emite telemetría cada 3 s y expone un servidor TCP en `:5002+` para ejecutar comandos remotos permitidos. |
| `client/admin_client.py` | **Cliente CLI (`AdminClient`)**: consola interactiva por TCP nativo con soporte para `PING`, `AUTH`, `GET_NODES`, `EXEC` y pruebas de inyección de tramas malformadas (RF07). |
| `client/gui_monitor.py` | **Dashboard Escritorio (`SDMRMonitorGUI`)**: interfaz gráfica en Tkinter con 5 pestañas (*Nodos*, *Demo Local*, *Tráfico NETMON/1.0*, *Instrucciones* y *Conceptos TCP/UDP*). |
| `client/contenido_ayuda.py` | Textos de ayuda integrada y citas textuales de la bibliografía (Kurose, 5.ª ed.). |
| `web/` | **Cliente Web React + Vite**: SPA que habla `NETMON/1.0` sobre WebSocket (`web/src/lib/netmon.js`) a través del gateway. |
| `mobile/` | **Cliente Móvil React Native (Expo Go)**: aplicación móvil que reutiliza el protocolo `NETMON/1.0` vía WebSocket. |
| `tools/test_system.py` | Suite de **9 pruebas de integración automatizadas** y no interactivas en puertos efímeros libres. |
| `tools/verificar_red.py` | Diagnóstico de red en 3 pasos (TCP `:5001`, UDP `:5000` confirmado vía `GET_NODES`, y WebSocket `:5003`). |
| `scripts/` | Lanzadores multiplataforma (`.bat` / `.sh`), instaladores de autoarranque y mini interfaz de control del agente (`scripts/agent/agent_control.py`). |

---

## 3. Los Protocolos a Profundidad

El sistema combina protocolos estándar de la **Capa de Transporte (UDP y TCP)** con un protocolo propio de **Capa de Aplicación (`NETMON/1.0`)**.

```
+-------------------------------------------------------------------------+
| CAPA DE APLICACIÓN: Protocolo propio NETMON/1.0 (Texto UTF-8 con '|')   |
|   - Telemetría (MON) y Descubrimiento (SRVREQ / SRVINFO)                |
|   - Comandos Admin (CMD / RES) y Ejecución Remota (EXECCMD)             |
+-----------------------------------+-------------------------------------+
| CAPA DE TRANSPORTE:               | CAPA DE TRANSPORTE:                 |
|   UDP (SOCK_DGRAM - Puerto 5000)  |   TCP (SOCK_STREAM - Puertos 5001,  |
|   Sin conexión, baja latencia     |   5002+) + WebSocket (Puerto 5003)  |
|                                   |   Orientado a conexión, confiable   |
+-----------------------------------+-------------------------------------+
```

### 3.1 Protocolos de Capa de Transporte: ¿Por qué UDP y TCP juntos?

El diseño aplica un criterio fundamental de ingeniería de redes: **seleccionar el protocolo de transporte según la criticidad, frecuencia y topología del mensaje**.

#### A. UDP (*User Datagram Protocol*) — Puerto `5000`
Utilizado para **Telemetría periódica (*Heartbeats*)** y **Autodescubrimiento de red (`SRVREQ` / `SRVINFO`)**.
* **Funcionamiento:** Es un protocolo **sin conexión** (`SOCK_DGRAM`). El agente empaqueta los datos en un datagrama independiente y lo transmite con `sendto()` sin establecer sesión previa (*sin handshake*).
* **Por qué se eligió UDP:**
  1. **Alta frecuencia y caducidad rápida:** Cada agente transmite métricas cada **3 segundos**. Si un datagrama UDP se pierde, 3 segundos después llegará otro con el estado actualizado del hardware. Retransmitir un valor viejo de CPU (como haría TCP) agregaría latencia innecesaria.
  2. **Mínima sobrecarga (*overhead*):** El encabezado UDP tiene solo 8 bytes (frente a los 20+ bytes de TCP) y no requiere mantener estructuras de estado ni descriptores de socket abiertos por cada nodo en el servidor. Un único socket UDP recibe paquetes de todos los agentes.
  3. **Soporte nativo de *Broadcast*:** UDP permite transmitir datagramas a `255.255.255.255` o al broadcast de la subred local para descubrir dónde está el servidor sin conocer su IP previamente. TCP no admite broadcast porque exige un *3-Way Handshake* punto a punto.

#### B. TCP (*Transmission Control Protocol*) — Puertos `5001` y `5002+`
Utilizado para **Administración (`5001`)** y **Ejecución Remota de órdenes `EXEC` en los agentes (`5002+`)**.
* **Funcionamiento:** Es un protocolo **orientado a conexión** (`SOCK_STREAM`) y de **flujo continuo de bytes**. Establece primero el saludo de tres vías (*3-Way Handshake*: `SYN` → `SYN-ACK` → `ACK`) y garantiza entrega ordenada, libre de errores y sin pérdidas mediante confirmaciones (`ACK`) y retransmisiones.
* **Por qué se eligió TCP:**
  1. **Entrega confiable garantizada:** Comandos de autenticación (`AUTH`), consultas de inventario (`GET_NODES`) u órdenes de control (`EXEC|NODO_01|RESTART_SERVICE`) no pueden perderse ni llegar truncados.
  2. **Persistencia de estado de sesión:** En el puerto `5001`, el servidor asocia la variable `is_authenticated = True` al socket dedicado de cada cliente administrador tras un login exitoso.

#### C. WebSocket (sobre TCP) — Puerto `5003`
* **Por qué existe:** Los navegadores modernos y entornos JavaScript móviles no permiten abrir sockets TCP crudos por restricciones de seguridad del sandbox; únicamente permiten HTTP y WebSockets.
* **Solución transparente:** `server/gateway.py` abre un servidor WebSocket en el puerto `5003` y, por cada cliente web/móvil, abre una conexión TCP nativa hacia `127.0.0.1:5001`, copiando las tramas `NETMON/1.0` en ambos sentidos sin traducirlas a REST ni JSON.

---

### 3.2 Protocolo de Capa de Aplicación: `NETMON/1.0`

Definido en `common/protocol.py`, es un protocolo textual pensado para ser **legible en capturas de Wireshark** y **parseable sin dependencias externas**.

* **Codificación:** `UTF-8` (`ENCODING = "utf-8"`).
* **Delimitador de campos:** Tubería `|` (`DELIMITER = "|"`).
* **Delimitador de trama (*Framing*):** Salto de línea `\n` al final de cada mensaje (`encode_message`).

Cuenta con **5 tipos de tramas**:

#### 1. Trama UDP de Telemetría (`MON`)
Enviada periódicamente cada 3 s del Agente al Servidor (`UDP :5000`):
```text
MON|<ID_NODO>|<IP>|<CPU_%>|<RAM_%>|<DISK_%>|<STATUS>[|<PUERTO_CMD>]
```
* **Ejemplo:** `MON|NODO_01|192.168.1.50|35.4|62.1|40.0|OK|5002`
* **`STATUS`:** `WARNING` si `CPU > 80.0%` o `RAM > 85.0%`; de lo contrario `OK`.
* **`PUERTO_CMD` (opcional):** Puerto TCP donde el agente escucha órdenes `EXEC`. Es opcional para mantener retrocompatibilidad y tolerar agentes cuyo puerto de control esté ocupado.

#### 2. Tramas UDP de Autodescubrimiento (`SRVREQ` y `SRVINFO`)
Permiten que el agente descubra automáticamente la IP del Servidor Central en la LAN:
* **Solicitud del Agente (Broadcast UDP `:5000`):**
  ```text
  SRVREQ|<ID_NODO>
  ```
* **Respuesta del Servidor (Unicast UDP al Agente):**
  ```text
  SRVINFO|<ID_NODO>|<IP_SERVIDOR>|<PUERTO_UDP>|<PUERTO_TCP>
  ```
  *Incluye `<ID_NODO>` para que el agente verifique que la respuesta le corresponde a él y no a otro nodo descubriendo en simultáneo.*

#### 3. Tramas TCP de Solicitud Administrativa (`CMD`)
Enviadas por el Cliente Administrador al Servidor (`TCP :5001`):
* `CMD|PING` → Comprobación de conectividad (no requiere sesión iniciada).
* `CMD|AUTH|<USUARIO>|<PASSWORD>` → Autenticación de administrador (`admin`/`admin123` u `operador`/`operador123`).
* `CMD|GET_NODES|ALL` → Solicita el listado y estado de todos los nodos registrados.
* `CMD|EXEC|<ID_NODO>|<COMANDO>` → Solicita ejecutar un comando remoto en `<ID_NODO>`.

#### 4. Tramas TCP Servidor → Agente (`EXECCMD`)
Enviadas cuando el Servidor Central se conecta como cliente TCP al `<PUERTO_CMD>` (`5002+`) del Agente:
```text
EXECCMD|<COMANDO>
```
* **Comandos permitidos (lista blanca en el agente):** `RESTART_SERVICE`, `DIAGNOSTIC`, `CLEAR_LOGS`.

#### 5. Tramas TCP de Respuesta (`RES`)
Enviadas del Servidor al Cliente Administrador, o del Agente al Servidor tras un `EXECCMD`:
```text
RES|<ESTADO>|<DATOS_O_CODIGO_ERROR>|<DETALLE>
```
* **`<ESTADO>`:** `OK` o `ERR`.
* **Ejemplos de éxito (`OK`):**
  * `RES|OK|PONG|Servidor activo y escuchando`
  * `RES|OK|AUTH_SUCCESS|Bienvenido admin`
  * `RES|OK|NODES_COUNT:2;NODO_01:192.168.1.50:OK:CPU=35.4%:RAM=62.1%:DISK=40.0%:LAST=1;NODO_02:...|Lista de nodos obtenida exitosamente`
    *(Nota: dentro del payload de `GET_NODES` se emplean `;` para separar nodos y `:` para separar atributos, evitando colisionar con el delimitador principal `|` de la trama).*
  * `RES|OK|EXEC_SUCCESS|[NODO_01] Servicio de monitoreo reiniciado correctamente`

#### Catálogo de Errores Tipificados (`NETMON/1.0`)
| Código | Constante en `protocol.py` | Significado y Causa |
| :--- | :--- | :--- |
| `ERR_100` | `ERR_MALFORMED_REQUEST` | Trama sin cabecera válida (`CMD`, `MON`, `EXECCMD`), parámetros insuficientes o trama mayor a 8 KB sin `\n`. |
| `ERR_101` | `ERR_UNAUTHORIZED` | Credenciales inválidas o intento de ejecutar `GET_NODES` / `EXEC` sin haber ejecutado `CMD|AUTH` antes. |
| `ERR_102` | `ERR_NODE_NOT_FOUND` | El nodo destino de `EXEC` no existe en el registro o se encuentra en estado `OFFLINE`. |
| `ERR_103` | `ERR_UNKNOWN_COMMAND` | La acción solicitada tras `CMD|` no existe en el protocolo `NETMON/1.0`. |
| `ERR_104` | `ERR_NODE_UNREACHABLE` | El agente no tiene canal de comandos, dio timeout (3 s), rechazó la conexión TCP o el comando no está en `COMANDOS_PERMITIDOS`. |
| `ERR_500` | `ERR_INTERNAL_SERVER` | Código reservado para fallos internos del servidor. |

---

## 4. Explicación Detallada del Código: Cómo y Por Qué Funciona

### 4.1 El Flujo de Bytes en TCP y el Encuadrado (`common/protocol.py`)

#### ¿Por qué existe `TcpFrameReader`?
En **UDP**, cada llamada a `recvfrom()` devuelve exactamente un datagrama completo. En cambio, **TCP es un flujo continuo de bytes (`SOCK_STREAM`)** sin fronteras de mensaje nativas:
* **Concatenación:** Si el cliente envía dos comandos seguidos (`CMD|PING\n` y `CMD|GET_NODES|ALL\n`), el sistema operativo puede agruparlos en un único segmento TCP y el receptor leerá `b"CMD|PING\nCMD|GET_NODES|ALL\n"` en una sola llamada a `recv()`.
* **Fragmentación:** Un mensaje puede llegar partido en dos llamadas sucesivas a `recv()` (por ejemplo, `b"CMD|PI"` y luego `b"NG\n"`).

#### Cómo lo resuelve el código (`TcpFrameReader`, líneas 363–438 de `common/protocol.py`)
```python
class TcpFrameReader:
    def __init__(self, max_frame_size: int = MAX_FRAME_SIZE):
        self._buffer = b""
        self._max_frame_size = max_frame_size
        self._frames = deque()

    def feed(self, data: bytes) -> list:
        self._buffer += data
        nuevas = []

        while b"\n" in self._buffer:
            crudo, self._buffer = self._buffer.split(b"\n", 1)
            texto = crudo.decode(ENCODING, errors="replace").strip()
            if texto:
                self._frames.append(texto)
                nuevas.append(texto)

        if len(self._buffer) > self._max_frame_size:
            self.reset()
            raise FrameTooLongError(...)
        return nuevas
```
1. **Acumulación en `bytes` crudos (`self._buffer = b""`):** En `UTF-8`, los caracteres acentuados o la `ñ` ocupan 2 bytes. Si un paquete TCP se fragmentara justo entre esos 2 bytes y se decodificara antes de reunir toda la línea, fallaría la decodificación UTF-8. Al dividir primero por `b"\n"` sobre bytes crudos y decodificar recién la trama completa, nunca se corrompen caracteres multibyte.
2. **Extracción iterativa (`while b"\n" in self._buffer`):** Si llegaron varias tramas juntas, las extrae todas en orden FIFO (`deque`) y conserva en `self._buffer` cualquier fragmento final incompleto hasta el próximo `recv()`.
3. **Defensa contra agotamiento de memoria (`MAX_FRAME_SIZE = 8192`):** Si un cliente defectuoso o malintencionado envía bytes sin fin sin incluir jamás `\n`, al superar 8 KB se vacía el buffer (`self.reset()`) y se lanza `FrameTooLongError`, permitiendo que el servidor responda `ERR_100` sin colapsar.

---

### 4.2 El Servidor Central Concurrente (`server/server.py`)

#### 1. Creación y enlace de los sockets UDP y TCP (`MonitoringServer.start`, líneas 98–151)
* **Socket UDP (`SOCK_DGRAM`):**
  ```python
  self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  self._asociar_socket(self.udp_socket, "UDP", self.udp_port)
  ```
  Solo requiere `bind()` (encapsulado en `_asociar_socket`, que captura `errno.EADDRINUSE` para informar claramente si el puerto ya está ocupado). No usa `listen()` ni `accept()`.
* **Socket TCP (`SOCK_STREAM`):**
  ```python
  self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  self._asociar_socket(self.tcp_socket, "TCP", self.tcp_port)
  self.tcp_socket.listen(5)
  ```
  * **`SO_REUSEADDR`:** Permite reiniciar el servidor inmediatamente después de cerrarlo sin esperar a que venza el estado `TIME_WAIT` del kernel.
  * **`listen(5)`:** Pone el socket en modo pasivo de escucha con una cola (*backlog*) de hasta 5 conexiones entrantes pendientes de `accept()`.

#### 2. Recepción de Telemetría y Sincronización con Mutex (`_udp_listener_loop`, líneas 234–275)
```python
data, addr = self.udp_socket.recvfrom(BUFFER_SIZE)
raw_message = decode_message(data)

if self._responder_descubrimiento(raw_message, addr):
    continue

telemetry = parse_udp_telemetry(raw_message)
with self.registry_lock:
    self.nodes_registry[node_id] = {
        "ip": addr[0],
        "udp_port": addr[1],
        "cpu": telemetry["cpu"],
        "ram": telemetry["ram"],
        "disk": telemetry["disk"],
        "status": telemetry["status"],
        "cmd_port": telemetry.get("cmd_port"),
        "last_seen": telemetry["timestamp"]
    }
```
* **¿Por qué `recvfrom()`?** Porque al no existir conexión en UDP, un único socket recibe datagramas de todos los agentes y necesita obtener la tupla `addr = (ip_remota, puerto_remoto)` de cada paquete.
* **¿Por qué se guarda `addr[0]` como IP del nodo?** Porque `addr[0]` es la IP real de origen del paquete IP vista por el servidor en la red, evitando que un agente mal configurado reporte `127.0.0.1` cuando en realidad está en otra máquina.
* **¿Por qué `with self.registry_lock:`?** El diccionario `self.nodes_registry` es memoria compartida entre:
  1. El hilo UDP (que escribe cada vez que llega telemetría).
  2. El hilo Watchdog (que modifica estados a `OFFLINE` y borra nodos antiguos).
  3. Los N hilos de clientes TCP (que leen el diccionario al responder `GET_NODES` y `EXEC`).
  El `threading.Lock()` garantiza **exclusión mutua (thread-safety)**, evitando condiciones de carrera (*race conditions*) o excepciones `RuntimeError: dictionary changed size during iteration`.

#### 3. Detección de Caídas sin Conexión: El Hilo Watchdog (`_watchdog_loop`, líneas 276–306)
Dado que UDP no avisa cuando un nodo se apaga, el servidor implementa un **Guardián de Inactividad (*Watchdog*)** que corre en su propio hilo daemon cada 5 segundos:
* Si `now - data["last_seen"] > 15.0` segundos (5 periodos de telemetría sin noticias), marca el nodo como `"OFFLINE"`.
* Si permanece `"OFFLINE"` por más de `self.offline_purge_seconds` (120 segundos por defecto), lo elimina de `self.nodes_registry` para evitar fugas de memoria a largo plazo.

#### 4. Concurrencia Multihilo en TCP (`_tcp_accept_loop` y `_handle_tcp_client`, líneas 307–403)
* En `_tcp_accept_loop`:
  ```python
  client_socket, client_address = self.tcp_socket.accept()
  client_thread = threading.Thread(
      target=self._handle_tcp_client,
      args=(client_socket, client_address),
      daemon=True
  )
  client_thread.start()
  ```
  `accept()` bloquea hasta que un cliente completa el *3-Way Handshake* y retorna un **nuevo socket dedicado** (`client_socket`). Al delegar su atención a un hilo independiente, el servidor puede atender a múltiples administradores en paralelo sin que uno bloquee a los demás.
* En `_handle_tcp_client`:
  * Mantiene el estado `is_authenticated` de forma local al hilo (por ende, privado a esa conexión TCP).
  * Detecta desconexión ordenada cuando `client_socket.recv(BUFFER_SIZE)` devuelve `b""` (recepción del flag TCP `FIN`) y captura `ConnectionResetError` cuando la desconexión es abrupta (flag TCP `RST`).
  * Transmite respuestas con `client_socket.sendall(...)` para asegurar que el buffer completo se envíe por la red.

#### 5. Ejecución Remota Extremo a Extremo (`_ejecutar_en_nodo`, líneas 483–510)
Cuando un administrador autenticado envía `CMD|EXEC|NODO_01|RESTART_SERVICE`:
```python
with socket.create_connection((node_ip, cmd_port), timeout=timeout) as sock:
    reader = TcpFrameReader()
    sock.sendall(encode_message(build_exec_command(remote_cmd)))
    while not reader.hay_tramas():
        datos = sock.recv(BUFFER_SIZE)
        if not datos:
            raise ConnectionError("El agente cerró la conexión sin responder.")
        reader.feed(datos)
    respuesta = parse_tcp_response(reader.siguiente_trama())
```
El Servidor Central abre una conexión TCP saliente hacia `(node_ip, cmd_port)` con un `timeout=3.0` s, envía `EXECCMD|RESTART_SERVICE\n`, lee la respuesta del agente usando `TcpFrameReader` y retransmite el resultado al administrador.

---

### 4.3 El Agente de Monitoreo (`agent/agent.py`)

#### 1. Habilitación de Broadcast UDP (`SystemNodeAgent.start`, líneas 506–507)
```python
self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
```
Por defecto, el sistema operativo bloquea el envío de datagramas a direcciones de broadcast (`255.255.255.255`) para prevenir tormentas de red accidentales. La opción `SO_BROADCAST = 1` autoriza explícitamente al socket UDP a emitir solicitudes `SRVREQ`.

#### 2. Detección de la Interfaz de Red de Salida (`_detectar_ip_local`, líneas 211–237)
```python
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((self.server_host, self.server_udp_port))
return s.getsockname()[0]
```
* **¿Por qué se usa `connect()` en un socket UDP efímero?** En una PC con múltiples adaptadores (WiFi, Ethernet, WSL, Docker, VirtualBox), consultar el hostname suele devolver `127.0.1.1` o una IP virtual. Al ejecutar `connect()` sobre un socket UDP (operación puramente local en el kernel que **no envía ningún paquete a la red**), el sistema operativo consulta su tabla de ruteo hacia `self.server_host` y asigna la IP de la placa de red física correspondiente, la cual se recupera con `s.getsockname()[0]`.
* Exactamente el mismo mecanismo utiliza el servidor en `_ip_hacia()` (`server/server.py`, líneas 173–197) para responder su propia IP LAN dentro de `SRVINFO`.

#### 3. Autodescubrimiento Resiliente (`descubrir_servidor`, líneas 353–495)
1. Si no se configuró IP en `agent/config.ini` ni por argumentos CLI, `_destinos_descubrimiento()` construye la lista de destinos de búsqueda: `255.255.255.255`, los broadcasts dirigidos de cada subred local (calculados con `ipaddress.IPv4Network` + `psutil.net_if_addrs()`) y `127.0.0.1` (necesario en Windows cuando servidor y agente corren en la misma máquina).
2. Envía `SRVREQ|<node_id>` y espera hasta 2 segundos con `settimeout` por una trama `SRVINFO|<node_id>|...`.
3. Además, durante el bucle normal de telemetría, cada `REDISCOVER_INTERVALO = 30.0` segundos vuelve a sondear por si el servidor cambió de IP por DHCP.

#### 4. Servidor TCP de Control en el Agente (`_iniciar_canal_comandos`, líneas 249–324)
* El agente levanta un socket TCP servidor en `self.cmd_port` (`5002` por defecto) en un hilo daemon (`_loop_comandos`).
* Si el puerto está ocupado, captura `OSError`, fija `self.cmd_port = None` y continúa enviando telemetría UDP sin interrumpir su función principal.
* Al recibir `EXECCMD|<COMANDO>`, `_procesar_orden()` verifica que el comando esté en el diccionario `COMANDOS_PERMITIDOS` (`RESTART_SERVICE`, `DIAGNOSTIC`, `CLEAR_LOGS`), escribe una línea de auditoría fechada en `agent/historial_comandos.log` y responde `RES|OK|<COMANDO>|<resultado>`.

---

### 4.4 Clientes de Administración y Gateway WebSocket

1. **Cliente CLI (`client/admin_client.py`):**
   * En `connect()` establece un timeout de 5 s para el *handshake* TCP inicial y luego deja el socket en modo bloqueante (`settimeout(None)`).
   * En `send_command()` utiliza `sendall()` y `_esperar_trama()` (basado en `TcpFrameReader`).
   * En `send_malformed_test()` utiliza `send_raw()` para enviar cadenas arbitrarias sin cabecera `CMD|` y comprobar en vivo que el servidor responde `ERR_100` / `ERR_103` manteniendo viva la sesión TCP (cumplimiento de **RF07**).
2. **Dashboard Tkinter (`client/gui_monitor.py`):**
   * Debido a que Tkinter no es *thread-safe*, toda lectura de subprocesos o actualización periódica (`poll`) se coordina mediante `queue.Queue` y `root.after(...)` en el hilo principal de la interfaz.
3. **Gateway y Clientes Web/Móvil (`server/gateway.py` y `web/src/lib/netmon.js`):**
   * `server/gateway.py` utiliza `asyncio.open_connection(tcp_host, tcp_port)` y `asyncio.gather(ws_hacia_tcp(), tcp_hacia_ws())` para acoplar cada cliente WebSocket a su propia conexión TCP con el servidor central.
   * `NetmonWS` (`web/src/lib/netmon.js`) mantiene una cola FIFO de promesas (`this.cola = []`) que empareja cada comando `CMD|...` enviado con la siguiente trama `RES|...` recibida.

---

## 5. Diagrama de Secuencia Extremo a Extremo

```mermaid
sequenceDiagram
    participant Agente as Agente (agent.py)
    participant Server as Servidor Central (server.py)
    participant Admin as Cliente Admin (CLI / GUI / Web)

    Note over Agente,Server: 1. Autodescubrimiento LAN (Opcional, por UDP :5000)
    Agente->>Server: UDP Broadcast: SRVREQ|NODO_01
    Server->>Agente: UDP Unicast: SRVINFO|NODO_01|192.168.1.50|5000|5001

    Note over Agente,Server: 2. Telemetría Continua (Cada 3s por UDP :5000)
    loop Cada 3 segundos
        Agente->>Server: UDP: MON|NODO_01|192.168.1.20|25.0|48.2|55.0|OK|5002
        Note right of Server: Actualiza nodes_registry<br/>protegido con registry_lock
    end

    Note over Server,Admin: 3. Sesión de Administración (Por TCP :5001)
    Admin->>Server: Handshake TCP (SYN -> SYN-ACK -> ACK)
    Admin->>Server: TCP: CMD|AUTH|admin|admin123\n
    Server->>Admin: TCP: RES|OK|AUTH_SUCCESS|Bienvenido admin\n
    Admin->>Server: TCP: CMD|GET_NODES|ALL\n
    Server->>Admin: TCP: RES|OK|NODES_COUNT:1;NODO_01:...|Lista de nodos...\n

    Note over Agente,Admin: 4. Ejecución Remota Real (Admin -> Server -> Agente)
    Admin->>Server: TCP (:5001): CMD|EXEC|NODO_01|RESTART_SERVICE\n
    Server->>Agente: TCP (:5002): EXECCMD|RESTART_SERVICE\n
    Agente->>Server: TCP (:5002): RES|OK|RESTART_SERVICE|Servicio de monitoreo reiniciado...\n
    Server->>Admin: TCP (:5001): RES|OK|EXEC_SUCCESS|[NODO_01] Servicio de monitoreo...\n
```

---

## 6. Resumen de Pruebas Automatizadas (`tools/test_system.py`)

El script `tools/test_system.py` valida de forma autónoma todos los mecanismos anteriores levantando el servidor y 3 agentes en puertos libres:

1. **Prueba 1 (Cliente único):** Flujo completo `PING` → `AUTH` → `GET_NODES`.
2. **Prueba 2 (Múltiples clientes):** 3 clientes TCP concurrentes autenticándose y consultando en paralelo.
3. **Prueba 3 (Desconexión abrupta):** Envía media trama (`b"CMD|PI"`) y fuerza un cierre TCP `RST` con `SO_LINGER`, verificando que el servidor no caiga.
4. **Prueba 4 (Datos inválidos - RF07):** Prueba tramas sin cabecera (`ERR_100`), comandos desconocidos (`ERR_103`), parámetros faltantes (`ERR_100`) y acceso sin autenticación (`ERR_101`).
5. **Prueba 5 (Servidor no disponible):** Comprueba el manejo de `ConnectionRefusedError` en el cliente.
6. **Prueba 6 (Encuadrado TCP):** Envía dos tramas pegadas en un mismo `sendall()` (`b"CMD|PING\nCMD|PING\n"`) y una trama partida en dos envíos separados (`b"CMD|PI"` + `b"NG\n"`).
7. **Prueba 7 (Watchdog):** Termina un proceso agente y verifica que el servidor lo marque como `OFFLINE` tras superar los 15 segundos de inactividad.
8. **Prueba 8 (Concurrencia bajo carga):** Múltiples hilos enviando ráfagas de `PING` mientras otro cliente consulta `GET_NODES`.
9. **Prueba EXEC:** Verifica ejecución remota exitosa (`RESTART_SERVICE` → `EXEC_SUCCESS`), rechazo de comando fuera de lista blanca (`FORMATEAR_DISCO` → `ERR_104`) y nodo inexistente (`NODO_99` → `ERR_102`).
