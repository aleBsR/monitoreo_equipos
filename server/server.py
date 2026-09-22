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
import sys
import threading
import time
import os

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
    encode_message,
    decode_message,
    parse_udp_telemetry,
    parse_tcp_command,
    build_tcp_response
)


class MonitoringServer:
    """
    Clase principal que encapsula la lógica del Servidor Central de Monitoreo.
    """

    def __init__(self, host: str = "0.0.0.0", udp_port: int = DEFAULT_UDP_PORT, tcp_port: int = DEFAULT_TCP_PORT):
        self.host = host
        self.udp_port = udp_port
        self.tcp_port = tcp_port

        # Registro thread-safe de nodos monitoreados
        # Estructura: { node_id: { "ip": str, "cpu": float, "ram": float, "disk": float, "status": str, "last_seen": float } }
        self.nodes_registry = {}
        self.registry_lock = threading.Lock()

        # Bandera de control para apagado controlado
        self.is_running = False

        # Credenciales sencillas para la prueba de autenticación de administradores
        self.admin_credentials = {
            "admin": "admin123",
            "operador": "operador123"
        }

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
        # 1. INICIALIZACIÓN DEL SOCKET UDP (Canal de Telemetría)
        # ---------------------------------------------------------------------
        # AF_INET = Familia IPv4
        # SOCK_DGRAM = Socket de Datagramas (Protocolo UDP)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permite reutilizar la dirección local en caso de reinicio rápido del servidor
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Asocia el socket a la IP y Puerto UDP especificado
        self.udp_socket.bind((self.host, self.udp_port))
        print(f"[UDP] Socket en escucha en {self.host}:{self.udp_port} (Telemetría / Heartbeats)")

        # Lanzar hilo en segundo plano (daemon thread) para escuchar paquetes UDP
        udp_thread = threading.Thread(target=self._udp_listener_loop, daemon=True)
        udp_thread.start()

        # ---------------------------------------------------------------------
        # 2. INICIALIZACIÓN DEL SOCKET GUARDIA (Watchdog de Nodos)
        # ---------------------------------------------------------------------
        watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        watchdog_thread.start()

        # ---------------------------------------------------------------------
        # 3. INICIALIZACIÓN DEL SOCKET TCP (Canal Confiable de Comandos)
        # ---------------------------------------------------------------------
        # AF_INET = Familia IPv4
        # SOCK_STREAM = Socket de Flujo de Bytes Confiable (Protocolo TCP)
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind((self.host, self.tcp_port))
        # listen(5): Habilita el socket para recibir conexiones. El parámetro 5 indica
        # la longitud máxima de la cola de conexiones pendientes de aceptación (backlog).
        self.tcp_socket.listen(5)
        print(f"[TCP] Socket en escucha en {self.host}:{self.tcp_port} (Comandos / Administración)")
        print("-----------------------------------------------------------------")
        print("Servidor iniciado exitosamente. Presione Ctrl+C para detener.")
        print("-----------------------------------------------------------------")

        # Bucle principal: Aceptar clientes TCP entrantes (Bloqueante)
        self._tcp_accept_loop()

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
        """
        TIMEOUT_SECONDS = 15.0

        while self.is_running:
            time.sleep(5)  # Verificación cada 5 segundos
            now = time.time()
            
            with self.registry_lock:
                for node_id, data in self.nodes_registry.items():
                    elapsed = now - data["last_seen"]
                    if elapsed > TIMEOUT_SECONDS and data["status"] != "OFFLINE":
                        data["status"] = "OFFLINE"
                        print(f"[WATCHDOG] ⚠️ ALERTA: El nodo '{node_id}' ({data['ip']}) ha sido marcado como OFFLINE (Inactivo por {int(elapsed)}s)")

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
        
        :param client_socket: Socket TCP individual conectado con el cliente.
        :param client_address: Tupla (IP, Puerto) del cliente.
        """
        is_authenticated = False
        authenticated_user = None

        try:
            while self.is_running:
                # recv(BUFFER_SIZE) lee datos stream del socket TCP
                raw_data = client_socket.recv(BUFFER_SIZE)
                
                # Si recv() retorna bytes vacíos (b''), significa que el cliente cerró la conexión
                if not raw_data:
                    print(f"[TCP - Desconexión] El cliente {client_address} cerró la conexión TCP de forma ordenada.")
                    break

                raw_message = decode_message(raw_data)
                if not raw_message:
                    continue

                print(f"[TCP - Comando Recibido] De {client_address}: '{raw_message}'")

                # Parsear comando según el protocolo NETMON/1.0
                try:
                    command_data = parse_tcp_command(raw_message)
                    action = command_data["action"]
                    params = command_data["params"]

                    # Procesar la acción solicitada
                    response_str = self._process_command(action, params, is_authenticated, client_address)
                    
                    # Actualizar estado de autenticación si fue exitosa
                    if action == "AUTH" and response_str.startswith("RES|OK|AUTH_SUCCESS"):
                        is_authenticated = True
                        authenticated_user = params[0] if len(params) > 0 else "Unknown"

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

    def _process_command(self, action: str, params: list, is_authenticated: bool, client_address: tuple) -> str:
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
            if username in self.admin_credentials and self.admin_credentials[username] == password:
                return build_tcp_response("OK", "AUTH_SUCCESS", f"Bienvenido {username}")
            else:
                return build_tcp_response("ERR", ERR_UNAUTHORIZED, "Usuario o contraseña incorrectos")

        # Los siguientes comandos requieren autenticación previa
        if not is_authenticated:
            return build_tcp_response("ERR", ERR_UNAUTHORIZED, "Debe autenticarse primero mediante CMD|AUTH|usuario|password")

        # 3. Consulta de lista de Nodos (GET_NODES)
        if action == "GET_NODES":
            with self.registry_lock:
                if not self.nodes_registry:
                    return build_tcp_response("OK", "NODES_COUNT:0", "No hay nodos registrados en el sistema")
                
                nodes_list = []
                for n_id, info in self.nodes_registry.items():
                    node_str = f"{n_id}:{info['ip']}:{info['status']}:CPU={info['cpu']}%:RAM={info['ram']}%:DISK={info['disk']}%"
                    nodes_list.append(node_str)
                
                payload = f"NODES_COUNT:{len(nodes_list)};" + ";".join(nodes_list)
                return build_tcp_response("OK", payload, "Lista de nodos obtenida exitosamente")

        # 4. Ejecución de comandos remotos en un nodo (EXEC)
        elif action == "EXEC":
            if len(params) < 2:
                return build_tcp_response("ERR", ERR_MALFORMED_REQUEST, "Uso correcto: CMD|EXEC|<ID_NODO>|<COMANDO>")
            
            target_node, remote_cmd = params[0], params[1]
            
            with self.registry_lock:
                if target_node not in self.nodes_registry:
                    return build_tcp_response("ERR", ERR_NODE_NOT_FOUND, f"El nodo '{target_node}' no esta registrado")
                
                node_info = self.nodes_registry[target_node]
                if node_info["status"] == "OFFLINE":
                    return build_tcp_response("ERR", ERR_NODE_NOT_FOUND, f"El nodo '{target_node}' se encuentra OFFLINE")

            # Simulación de orden enviada con éxito al nodo
            return build_tcp_response("OK", "EXEC_SUCCESS", f"Comando '{remote_cmd}' ejecutado en nodo '{target_node}'")

        # Comando no reconocido
        else:
            return build_tcp_response("ERR", ERR_UNKNOWN_COMMAND, f"Comando '{action}' no reconocido por el protocolo NETMON/1.0")

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
    # Permite especificar puertos desde la línea de comandos o usar los de defecto
    udp_p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_UDP_PORT
    tcp_p = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TCP_PORT
    
    server = MonitoringServer(udp_port=udp_p, tcp_port=tcp_p)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
