"""
===============================================================================
Servidor Central Concurrente de Monitoreo (SDMR)
===============================================================================
Este programa implementa el Servidor Central de Monitoreo utilizando programación
nativas de Sockets en Python (librería `socket`) y concurrencia basada en Hilos (`threading`).

Características de Red e Hilos:
  1. Hilo Escuchador UDP (Puerto 5000):
     - Recibe datagramas sin conexión (`socket.recvfrom()`) provenientes de los Agentes.
     - Parsea las métricas de telemetría (CPU, RAM, Disco) y actualiza el registro global de nodos.
     - Responde SRVREQ (descubrimiento automático): el agente broadcast su solicitud
       y este servidor le contesta SRVINFO con su IP y puertos, de modo que los
       clientes se unen a la red sin configurar la IP a mano.
  
  2. Hilo Principal Escuchador TCP (Puerto 5001):
     - Abre un socket de escucha TCP (`socket.listen()`).
     - Acepta conexiones entrantes (`socket.accept()`) y crea UN HILO DEDICADO por cada cliente conectado.
     - Permite múltiples clientes administradores y agentes simultáneamente.

  3. Hilo Guardián / Watchdog de Nodos:
     - Revisa periódicamente la marca de tiempo (timestamp) de los nodos registrados.
     - Si un nodo no envía telemetría UDP durante más de 15 segundos, se marca como 'OFFLINE'.

  4. Protección de Concurrencia (Mutex):
     - Acceso al diccionario compartido `nodes_registry` protegido mediante `threading.Lock()`
       para evitar condiciones de carrera (Race Conditions).
===============================================================================
"""

import socket
import ssl
import sys
import threading
import time
import os
import json
import hmac
import errno

# Permitir importar módulos desde el directorio raíz del proyecto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.protocol import (
    DEFAULT_UDP_PORT,
    DEFAULT_TCP_PORT,
    BUFFER_SIZE,
    ENCODING,
    ERR_MALFORMED_REQUEST,
    ERR_UNAUTHORIZED,
    ERR_NODE_NOT_FOUND,
    ERR_UNKNOWN_COMMAND,
    ERR_NODE_UNREACHABLE,
    encode_message,
    decode_message,
    parse_udp_telemetry,
    parse_tcp_command,
    parse_tcp_response,
    build_tcp_response,
    build_exec_command,
    parse_srv_request,
    build_srv_info,
    es_trama_descubrimiento,
    TcpFrameReader,
    FrameTooLongError,
    configurar_salida,
)
from common import security


class MonitoringServer:
    """
    Clase principal que encapsula la lógica del Servidor Central de Monitoreo.
    """

    def __init__(self, host: str = "0.0.0.0", udp_port: int = DEFAULT_UDP_PORT, tcp_port: int = DEFAULT_TCP_PORT, offline_purge_seconds: float = 120.0, seguro: bool = False, dir_certs: str = None):
        self.host = host
        self.udp_port = udp_port
        self.tcp_port = tcp_port

        # --- Seguridad (OPCIONAL) ---------------------------------------------
        # Si `seguro` es True, el canal TCP 5001 se envuelve en TLS (mutuo) y la
        # telemetría UDP se verifica por HMAC. Por defecto está DESACTIVADO: el
        # sistema se comporta igual que siempre y no rompe la demo ni los clientes
        # viejos. El contexto TLS se construye en start() para fallar con un
        # mensaje claro si faltan los certificados.
        self.seguro = seguro
        self.dir_certs = dir_certs or security.ruta_certs_por_defecto()
        self.tls_context = None
        # Clave HMAC compartida y caché anti-replay para la telemetría UDP firmada.
        self.hmac_key = None
        self.nonce_cache = None

        # Segundos de inactividad tolerados antes de PURGAR un nodo OFFLINE
        # del registro (evita que nodes_registry crezca sin límite)
        self.offline_purge_seconds = offline_purge_seconds

        # Registro thread-safe de nodos monitoreados
        # Estructura: { node_id: { "ip": str, "cpu": float, "ram": float, "disk": float, "status": str, "last_seen": float } }
        self.nodes_registry = {}
        self.registry_lock = threading.Lock()

        # Bandera de control para apagado controlado
        self.is_running = False

        # Usuarios y roles. Se cargan en start() desde server/usuarios.json
        # (contraseñas hasheadas con PBKDF2). Si el archivo no existe, se usa un
        # juego de credenciales por defecto (modo demo / compatibilidad).
        self.usuarios = {}

        # Sockets
        self.udp_socket = None
        self.tcp_socket = None

    def start(self):
        """
        Inicializa los sockets UDP y TCP, e inicia los hilos de ejecución.
        """
        self.is_running = True
        print("=================================================================")
        print(" INICIALIZANDO SERVIDOR CENTRAL DE MONITOREO EN RED (SDMR)")
        print("=================================================================")

        # ---------------------------------------------------------------------
        # 0. SEGURIDAD (OPCIONAL): construir el contexto TLS antes de abrir
        #    sockets. Si faltan los certificados, salir con un mensaje claro.
        # ---------------------------------------------------------------------
        if self.seguro:
            try:
                self.tls_context = security.contexto_servidor_desde_dir(self.dir_certs)
            except (FileNotFoundError, ssl.SSLError, OSError) as e:
                print("=================================================================")
                print(f" [ERROR] Modo seguro activado pero no se pudo cargar TLS: {e}")
                print(" ¿Generaste los certificados?  ->  python scripts/gen_certs.py")
                print(f" Carpeta esperada: {self.dir_certs}")
                print("=================================================================")
                sys.exit(1)
            # Clave HMAC para verificar la telemetría UDP firmada por los agentes.
            try:
                self.hmac_key = security.clave_hmac_desde_entorno()
            except ValueError as e:
                print("=================================================================")
                print(f" [ERROR] Modo seguro activado pero no hay clave HMAC: {e}")
                print("=================================================================")
                sys.exit(1)
            self.nonce_cache = security.CacheNonces()
            print("[SEGURIDAD] TLS mutuo ACTIVADO en el canal TCP (los clientes deben presentar certificado).")
            print("[SEGURIDAD] Telemetría UDP verificada con HMAC-SHA256 + anti-replay.")
        else:
            print("[SEGURIDAD] Modo INSEGURO (sin TLS/HMAC). Para activarlo, agregá: --seguro")

        # Cargar usuarios y roles (PBKDF2 desde usuarios.json o fallback en código).
        self.usuarios = self._cargar_usuarios()

        # ---------------------------------------------------------------------
        # 1. INICIALIZACIÓN DEL SOCKET UDP (Canal de Telemetría)
        # ---------------------------------------------------------------------
        # AF_INET = Familia IPv4
        # SOCK_DGRAM = Socket de Datagramas (Protocolo UDP)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permite reutilizar la dirección local en caso de reinicio rápido del servidor
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Asocia el socket a la IP y Puerto UDP especificado
        self._asociar_socket(self.udp_socket, "UDP", self.udp_port)
        print(f"[UDP] Socket en escucha en {self.host}:{self.udp_port} (Telemetría / Heartbeats)")

        # ---------------------------------------------------------------------
        # 2. INICIALIZACIÓN DEL SOCKET TCP (Canal Confiable de Comandos)
        # ---------------------------------------------------------------------
        # AF_INET = Familia IPv4
        # SOCK_STREAM = Socket de Flujo de Bytes Confiable (Protocolo TCP)
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Se asocia ANTES de lanzar los hilos: si el puerto está ocupado, el
        # servidor sale prolijamente sin dejar un arranque a medias.
        self._asociar_socket(self.tcp_socket, "TCP", self.tcp_port)
        # listen(5): Habilita el socket para recibir conexiones. El parámetro 5 indica
        # la longitud máxima de la cola de conexiones pendientes de aceptación (backlog).
        self.tcp_socket.listen(5)
        print(f"[TCP] Socket en escucha en {self.host}:{self.tcp_port} (Comandos / Administración)")

        # ---------------------------------------------------------------------
        # 3. HILOS DE EJECUCIÓN (Telemetría UDP + Guardián de Nodos)
        # ---------------------------------------------------------------------
        # Lanzar hilo en segundo plano (daemon thread) para escuchar paquetes UDP
        udp_thread = threading.Thread(target=self._udp_listener_loop, daemon=True)
        udp_thread.start()

        # Hilo guardián: marca OFFLINE y purga nodos inactivos
        watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        watchdog_thread.start()

        print("-----------------------------------------------------------------")
        print("Servidor iniciado exitosamente. Presione Ctrl+C para detener.")
        print("-----------------------------------------------------------------")

        # Bucle principal: Aceptar clientes TCP entrantes (Bloqueante)
        self._tcp_accept_loop()

    def _asociar_socket(self, sock: socket.socket, tipo: str, puerto: int):
        """
        Asocia (bind) un socket al puerto indicado manejando los errores
        esperados del §6 del TP: puerto ocupado e imposibilidad de enlace.

        :raises SystemExit: Con código 1 si el puerto ya está en uso.
        """
        try:
            sock.bind((self.host, puerto))
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                print(f"=================================================================")
                print(f" [ERROR] El puerto {tipo} {puerto} ya está en uso.")
                print(f" ¿Ya hay un servidor SDMR corriendo? Cierre ese proceso")
                print(f" o ejecute el servidor con otros puertos:")
                print(f"     python3 server/server.py <udp> <tcp>")
                print(f"=================================================================")
                sys.exit(1)
            print(f"[ERROR] No se pudo asociar el socket {tipo} en {puerto}: {e}")
            sys.exit(1)

    def _ip_hacia(self, destino: str) -> str:
        """
        Dirección IP local con la que ESTE servidor alcanza a `destino`.

        Se abre un socket UDP efímero y se hace connect() (sin enviar un solo
        byte): el sistema elige la interfaz de salida y getsockname() devuelve
        la IP real. Evita responder 0.0.0.0 a un SRVREQ.

        :param destino: IP del agente que pidió el descubrimiento.
        :return: Cadena con la IP local, o "127.0.0.1" como último recurso.
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect((destino, 1))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _responder_descubrimiento(self, raw_message: str, addr: tuple):
        """
        Atiende un SRVREQ (broadcast de un agente que no sabe dónde está el
        servidor) y le contesta SRVINFO con la IP y puertos de este servidor.

        La respuesta va por UNICAST al origen: sale por la misma interfaz que
        recibió el datagrama, así el agente aprende una IP alcanzable.

        :param raw_message: Trama UDP cruda recibida.
        :param addr: Tupla (ip_origen, puerto_origen) del agente.
        :return: True si la trama era de descubrimiento (ya atendida).
        """
        if not es_trama_descubrimiento(raw_message):
            return False
        if not raw_message.startswith("SRVREQ|"):
            # Un SRVINFO llegado acá no es para nosotros (somos el servidor).
            return True

        try:
            solicitud = parse_srv_request(raw_message)
        except ValueError as ve:
            print(f"[UDP - Descubrimiento] Solicitud inválida desde {addr}: {ve}")
            return True

        ip_servidor = self._ip_hacia(addr[0])
        respuesta = build_srv_info(solicitud["node_id"], ip_servidor, self.udp_port, self.tcp_port)
        # En modo seguro, el SRVINFO también se firma para que el agente verifique
        # que la respuesta viene del servidor legítimo (y no de un impostor).
        if self.seguro:
            respuesta = security.envolver_udp(respuesta, self.hmac_key)
        try:
            self.udp_socket.sendto(encode_message(respuesta), addr)
            print(
                f"[UDP - Descubrimiento] Nodo '{solicitud['node_id']}' desde {addr[0]} "
                f"-> SRVINFO {ip_servidor} (UDP {self.udp_port} / TCP {self.tcp_port})"
            )
        except OSError as e:
            print(f"[UDP - Descubrimiento] No se pudo responder a {addr}: {e}")
        return True

    def _udp_listener_loop(self):
        """
        Bucle de ejecución para escuchar datagramas UDP entrantes de los agentes.
        """
        while self.is_running:
            try:
                # recvfrom(BUFFER_SIZE) es bloqueante.
                # Retorna una tupla: (datos_recibidos: bytes, direccion_cliente: (IP, Puerto))
                data, addr = self.udp_socket.recvfrom(BUFFER_SIZE)
                raw_message = decode_message(data)

                # 0.a SEGURIDAD: en modo seguro, TODO el tráfico UDP (telemetría y
                #     descubrimiento) debe venir firmado. Se verifica el HMAC y el
                #     anti-replay ANTES de interpretar nada; un datagrama inválido
                #     se descarta y se loguea, sin cerrar nada (RF07).
                if self.seguro:
                    if not security.es_sobre_seguro(raw_message):
                        print(f"[UDP - Seguridad] Datagrama sin firmar descartado de {addr[0]}.")
                        continue
                    try:
                        raw_message = security.desenvolver_udp(raw_message, self.hmac_key, self.nonce_cache)
                    except ValueError as e:
                        print(f"[UDP - Seguridad] Datagrama rechazado de {addr[0]}: {e}")
                        continue

                # 0. Descubrimiento automático: SRVREQ -> SRVINFO
                if self._responder_descubrimiento(raw_message, addr):
                    continue

                # Intentar parsear el paquete de telemetría usando nuestro protocolo
                try:
                    telemetry = parse_udp_telemetry(raw_message)
                    node_id = telemetry["node_id"]

                    # Sección Crítica: Actualizar diccionario compartido usando Mutex
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

                    print(f"[UDP - Telemetría Recibida] Nodo: {node_id} ({addr[0]}) | CPU: {telemetry['cpu']}% | RAM: {telemetry['ram']}% | Estado: {telemetry['status']}")

                except ValueError as ve:
                    print(f"[UDP - Error de Validación] Datos malformados desde {addr}: {ve}")

            except Exception as e:
                if self.is_running:
                    print(f"[UDP - Error Inesperado]: {e}")

    def _watchdog_loop(self):
        """
        Hilo de monitoreo de inactividad de nodos. Si un nodo no envía UDP en > 15s,
        se marca su estado como 'OFFLINE'.

        Además PURGA el registro: los nodos que siguen inactivos más de
        `offline_purge_seconds` se eliminan del diccionario para que
        `nodes_registry` no crezca sin límite.
        """
        TIMEOUT_SECONDS = 15.0

        while self.is_running:
            time.sleep(5)  # Verificación cada 5 segundos
            now = time.time()

            with self.registry_lock:
                nodos_a_borrar = []
                for node_id, data in self.nodes_registry.items():
                    elapsed = now - data["last_seen"]
                    if data["status"] != "OFFLINE" and elapsed > TIMEOUT_SECONDS:
                        data["status"] = "OFFLINE"
                        print(f"[WATCHDOG] ⚠️ ALERTA: El nodo '{node_id}' ({data['ip']}) ha sido marcado como OFFLINE (Inactivo por {int(elapsed)}s)")
                    elif data["status"] == "OFFLINE" and elapsed > self.offline_purge_seconds:
                        nodos_a_borrar.append(node_id)

                # Borrado fuera del iterador: no se puede modificar el diccionario mientras se recorre
                for node_id in nodos_a_borrar:
                    ip = self.nodes_registry[node_id]["ip"]
                    del self.nodes_registry[node_id]
                    print(f"[WATCHDOG] 🧹 Nodo '{node_id}' ({ip}) eliminado del registro (inactivo por más de {int(self.offline_purge_seconds)}s)")

    def _tcp_accept_loop(self):
        """
        Bucle principal que acepta conexiones TCP y lanza un nuevo hilo por cada cliente.
        """
        while self.is_running:
            try:
                # accept() bloquea la ejecución hasta que llega un nuevo cliente TCP.
                # Retorna: (socket_cliente, (ip_cliente, puerto_cliente))
                client_socket, client_address = self.tcp_socket.accept()
                print(f"[TCP - Nueva Conexión] Cliente conectado desde {client_address[0]}:{client_address[1]}")

                # Lanzar un hilo independiente para atender a este cliente sin bloquear a los demás
                client_thread = threading.Thread(
                    target=self._handle_tcp_client,
                    args=(client_socket, client_address),
                    daemon=True
                )
                client_thread.start()

            except KeyboardInterrupt:
                print("\n[SERVIDOR] Apagando el servidor por solicitud del usuario (Ctrl+C)...")
                self.stop()
                break
            except Exception as e:
                if self.is_running:
                    print(f"[TCP - Error en Accept]: {e}")

    def _handle_tcp_client(self, client_socket: socket.socket, client_address: tuple):
        """
        Atiende la interacción continua con un cliente TCP específico en su propio hilo.

        Encuadrado de tramas: TCP es un flujo de bytes, por lo que `recv()`
        puede devolver una trama partida en dos segmentos o dos tramas juntas
        en un mismo segmento. Se usa un `TcpFrameReader` por conexión para
        separar correctamente por '\\n' y no concatenar comandos.

        :param client_socket: Socket TCP individual conectado con el cliente.
        :param client_address: Tupla (IP, Puerto) del cliente.
        """
        is_authenticated = False
        authenticated_user = None
        authenticated_role = None
        reader = TcpFrameReader()

        # Envoltura TLS por conexión. Se hace DENTRO del hilo del cliente para que
        # el handshake (que puede demorar) no bloquee el accept() de otros clientes.
        # Si el cliente no presenta un certificado válido, el handshake falla y se
        # cierra solo esta conexión, sin afectar al servidor (RF07).
        if self.tls_context is not None:
            try:
                client_socket = self.tls_context.wrap_socket(client_socket, server_side=True)
            except (ssl.SSLError, OSError) as e:
                print(f"[TCP - TLS] Handshake rechazado con {client_address}: {e}")
                try:
                    client_socket.close()
                except OSError:
                    pass
                return

        try:
            while self.is_running:
                # recv(BUFFER_SIZE) lee bytes del flujo TCP (no necessarily una trama completa)
                raw_data = client_socket.recv(BUFFER_SIZE)

                # Si recv() retorna bytes vacíos (b''), significa que el cliente cerró la conexión
                if not raw_data:
                    print(f"[TCP - Desconexión] El cliente {client_address} cerró la conexión TCP de forma ordenada.")
                    break

                # Acumular y separar tramas completas a partir de los bytes recibidos
                try:
                    tramas = reader.feed(raw_data)
                except FrameTooLongError as fle:
                    # RF07: trama inválida, se responde el error sin cortar la conexión
                    print(f"[TCP - Trama Inválida] De {client_address}: {fle}")
                    client_socket.sendall(
                        encode_message(build_tcp_response("ERR", ERR_MALFORMED_REQUEST, str(fle)))
                    )
                    continue

                # Puede haber llegado más de una trama en el mismo segmento TCP
                for raw_message in tramas:
                    print(f"[TCP - Comando Recibido] De {client_address}: '{raw_message}'")

                    try:
                        command_data = parse_tcp_command(raw_message)
                        action = command_data["action"]
                        params = command_data["params"]

                        response_str = self._process_command(action, params, is_authenticated, client_address, role=authenticated_role)

                        # Actualizar estado de autenticación si fue exitosa
                        if action == "AUTH" and response_str.startswith("RES|OK|AUTH_SUCCESS"):
                            is_authenticated = True
                            authenticated_user = params[0] if len(params) > 0 else "Unknown"
                            authenticated_role = self.usuarios.get(authenticated_user, {}).get("rol", "operador")
                            print(f"[TCP - Sesión] Cliente {client_address} autenticado como '{authenticated_user}' (rol: {authenticated_role})")

                    except ValueError as ve:
                        response_str = build_tcp_response("ERR", ERR_MALFORMED_REQUEST, str(ve))

                    # Enviar respuesta por el socket TCP utilizando sendall()
                    # sendall() garantiza que todos los bytes de la respuesta sean transmitidos
                    client_socket.sendall(encode_message(response_str))

        except ConnectionResetError:
            print(f"[TCP - Error] Conexión interrumpida abruptamente por el cliente {client_address}.")
        except Exception as e:
            print(f"[TCP - Error atendiendo cliente {client_address}]: {e}")
        finally:
            # Cierre seguro del socket del cliente al finalizar el hilo
            client_socket.close()
            print(f"[TCP - Socket Cerrado] Recursos liberados para cliente {client_address}")

    def _cargar_usuarios(self) -> dict:
        """
        Carga los usuarios y sus roles desde `server/usuarios.json` (creado con
        `scripts/set_password.py`), donde las contraseñas están HASHEADAS con
        PBKDF2 salado, nunca en texto plano.

        Si el archivo no existe, usa un juego de credenciales por defecto en
        código (modo demo / compatibilidad con la versión previa y la suite de
        pruebas). Para producción se recomienda generar el archivo.
        """
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usuarios.json")
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[AUTH] {len(data)} usuario(s) cargado(s) desde usuarios.json (contraseñas PBKDF2 hasheadas).")
                return data
            except (OSError, ValueError) as e:
                print(f"[AUTH] No se pudo leer usuarios.json ({e}); se usan credenciales por defecto.")

        print("[AUTH] usuarios.json ausente: credenciales por defecto (admin / operador). "
              "Generá hashes con: python scripts/set_password.py admin --rol admin")
        return {
            "admin": {"rol": "admin", "password_plano": "admin123"},
            "operador": {"rol": "operador", "password_plano": "operador123"},
        }

    def _verificar_credenciales(self, username: str, password: str) -> tuple:
        """
        Verifica usuario y contraseña contra el registro cargado.

        Soporta dos formatos de registro:
          - Hasheado (desde usuarios.json): se valida con PBKDF2 en tiempo constante.
          - En claro (fallback por defecto): comparación directa.

        :return: Tupla (ok: bool, rol: str|None).
        """
        registro = self.usuarios.get(username)
        if not registro:
            return False, None

        rol = registro.get("rol", "operador")

        if "hash" in registro:
            # Registro con contraseña hasheada (PBKDF2 salado).
            if security.verificar_password(password, registro):
                return True, rol
            return False, None

        # Fallback: contraseña en texto plano (solo credenciales por defecto).
        esperado = registro.get("password_plano", "")
        if hmac.compare_digest(password.encode(ENCODING), esperado.encode(ENCODING)):
            return True, rol
        return False, None

    def _process_command(self, action: str, params: list, is_authenticated: bool, client_address: tuple, role: str = None) -> str:
        """
        Evalúa el comando recibido y genera la respuesta correspondiente respetando el protocolo.
        """
        # 1. Comando PING (No requiere autenticación)
        if action == "PING":
            return build_tcp_response("OK", "PONG", "Servidor activo y escuchando")

        # 2. Autenticación (AUTH)
        elif action == "AUTH":
            if len(params) < 2:
                return build_tcp_response("ERR", ERR_MALFORMED_REQUEST, "Uso correcto: CMD|AUTH|<usuario>|<password>")
            
            username, password = params[0], params[1]
            ok, rol = self._verificar_credenciales(username, password)
            if ok:
                return build_tcp_response("OK", "AUTH_SUCCESS", f"Bienvenido {username} (rol: {rol})")
            else:
                return build_tcp_response("ERR", ERR_UNAUTHORIZED, "Usuario o contraseña incorrectos")

        # Los siguientes comandos requieren autenticación previa
        if not is_authenticated:
            return build_tcp_response("ERR", ERR_UNAUTHORIZED, "Debe autenticarse primero mediante CMD|AUTH|usuario|password")

        # 3. Consulta de lista de Nodos (GET_NODES)
        if action == "GET_NODES":
            ahora = time.time()
            with self.registry_lock:
                if not self.nodes_registry:
                    return build_tcp_response("OK", "NODES_COUNT:0", "No hay nodos registrados en el sistema")
                
                nodes_list = []
                for n_id, info in self.nodes_registry.items():
                    # LAST: segundos transcurridos desde el último heartbeat UDP.
                    # Campo OPCIONAL: los clientes viejos lo ignoran sin romperse.
                    ultima = max(0, int(ahora - info.get("last_seen", ahora)))
                    node_str = (
                        f"{n_id}:{info['ip']}:{info['status']}"
                        f":CPU={info['cpu']}%:RAM={info['ram']}%:DISK={info['disk']}%"
                        f":LAST={ultima}"
                    )
                    nodes_list.append(node_str)
                
                payload = f"NODES_COUNT:{len(nodes_list)};" + ";".join(nodes_list)
                return build_tcp_response("OK", payload, "Lista de nodos obtenida exitosamente")

        # 4. Ejecución de comandos remotos en un nodo (EXEC)
        elif action == "EXEC":
            # RBAC: solo el rol 'admin' puede ejecutar comandos remotos.
            # El 'operador' tiene acceso de solo lectura (PING / GET_NODES).
            if role != "admin":
                return build_tcp_response(
                    "ERR", ERR_UNAUTHORIZED,
                    f"Permiso denegado: EXEC requiere rol 'admin' (rol actual: {role or 'desconocido'})."
                )
            if len(params) < 2:
                return build_tcp_response("ERR", ERR_MALFORMED_REQUEST, "Uso correcto: CMD|EXEC|<ID_NODO>|<COMANDO>")

            target_node, remote_cmd = params[0], params[1]

            with self.registry_lock:
                if target_node not in self.nodes_registry:
                    return build_tcp_response("ERR", ERR_NODE_NOT_FOUND, f"El nodo '{target_node}' no esta registrado")

                node_info = self.nodes_registry[target_node]
                if node_info["status"] == "OFFLINE":
                    return build_tcp_response("ERR", ERR_NODE_NOT_FOUND, f"El nodo '{target_node}' se encuentra OFFLINE")

                node_ip = node_info["ip"]
                cmd_port = node_info.get("cmd_port")

            if not cmd_port:
                return build_tcp_response(
                    "ERR", ERR_NODE_UNREACHABLE,
                    f"El nodo '{target_node}' no expone un canal de comandos (EXEC no disponible)."
                )

            # Reenviar la orden al agente por TCP y devolver su respuesta real
            ok, payload_o_codigo, detalle = self._ejecutar_en_nodo(node_ip, cmd_port, remote_cmd)
            if ok:
                return build_tcp_response("OK", "EXEC_SUCCESS", f"[{target_node}] {detalle}")
            return build_tcp_response("ERR", payload_o_codigo, f"[{target_node}] {detalle}")

        # Comando no reconocido
        else:
            return build_tcp_response("ERR", ERR_UNKNOWN_COMMAND, f"Comando '{action}' no reconocido por el protocolo NETMON/1.0")

    def _ejecutar_en_nodo(self, node_ip: str, cmd_port: int, remote_cmd: str, timeout: float = 3.0) -> tuple:
        """
        Abre una conexión TCP al canal de comandos del agente y le reenvía la
        orden EXEC, esperando su confirmación (entrega confiable).

        :return: Tupla (ok: bool, payload_o_codigo, detalle).
        """
        try:
            # create_connection maneja el handshake TCP y aplica timeout
            with socket.create_connection((node_ip, cmd_port), timeout=timeout) as sock:
                reader = TcpFrameReader()
                sock.sendall(encode_message(build_exec_command(remote_cmd)))

                while not reader.hay_tramas():
                    datos = sock.recv(BUFFER_SIZE)
                    if not datos:
                        raise ConnectionError("El agente cerró la conexión sin responder.")
                    reader.feed(datos)

                respuesta = parse_tcp_response(reader.siguiente_trama())
                return respuesta["status"] == "OK", respuesta["payload_or_code"], respuesta["detail"]

        except socket.timeout:
            return False, ERR_NODE_UNREACHABLE, f"El nodo no respondió en {timeout:.0f}s (timeout)."
        except ConnectionRefusedError:
            return False, ERR_NODE_UNREACHABLE, "El nodo no tiene abierto el canal de comandos."
        except (OSError, ValueError) as e:
            return False, ERR_NODE_UNREACHABLE, f"No se pudo ejecutar el comando en el nodo: {e}"

    def stop(self):
        """
        Cierra de forma limpia y segura los sockets.
        """
        self.is_running = False
        if self.udp_socket:
            self.udp_socket.close()
        if self.tcp_socket:
            self.tcp_socket.close()
        print("[SERVIDOR] Sockets cerrados y servidor detenido correctamente.")


if __name__ == "__main__":
    configurar_salida()
    # Permite especificar puertos desde la línea de comandos o usar los de defecto
    # Uso: python3 server/server.py [udp_port] [tcp_port] [segundos_purga_offline] [--seguro]
    #
    # Se separan las banderas de seguridad (--seguro / --inseguro / --certs <dir>)
    # de los argumentos POSICIONALES (puertos y purga), para no romper el uso de
    # siempre ni confundir un flag con un número de puerto.
    opc = security.opciones_seguridad(sys.argv)
    posicionales = security.args_posicionales(sys.argv)

    udp_p = int(posicionales[0]) if len(posicionales) > 0 else DEFAULT_UDP_PORT
    tcp_p = int(posicionales[1]) if len(posicionales) > 1 else DEFAULT_TCP_PORT
    purga_s = float(posicionales[2]) if len(posicionales) > 2 else 120.0

    server = MonitoringServer(
        udp_port=udp_p, tcp_port=tcp_p, offline_purge_seconds=purga_s,
        seguro=opc["seguro"], dir_certs=opc["dir_certs"],
    )
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
