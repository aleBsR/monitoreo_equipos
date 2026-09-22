"""
===============================================================================
Cliente Administrador Interactivo (SDMR Admin CLI)
===============================================================================
Este programa implementa la consola de administración del sistema.
Utiliza un Socket TCP (orientado a conexión y confiable) para interactuar
con el Servidor Central de Monitoreo.

Operaciones TCP soportadas:
  1. Verificación de conectividad (PING -> PONG).
  2. Autenticación de administrador (CMD|AUTH|usuario|clave).
  3. Consulta de lista de nodos monitoreados (CMD|GET_NODES|ALL).
  4. Envío de comandos de administración remota (CMD|EXEC|NODO|COMANDO).
  5. Simulación de errores para pruebas de validación.
===============================================================================
"""

import socket
import sys
import os

# Permitir importar el protocolo común
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.protocol import (
    DEFAULT_TCP_PORT,
    BUFFER_SIZE,
    build_tcp_command,
    parse_tcp_response,
    encode_message,
    decode_message
)


class AdminClient:
    """
    Cliente de consola para administrar el servidor de monitoreo a través de Sockets TCP.
    """

    def __init__(self, server_host: str = "127.0.0.1", server_tcp_port: int = DEFAULT_TCP_PORT):
        self.server_host = server_host
        self.server_tcp_port = server_tcp_port
        self.tcp_socket = None
        self.is_connected = False
        self.is_authenticated = False
        self.username = None

    def connect(self) -> bool:
        """
        Establece la conexión TCP inicial con el Servidor Central (Handshake de 3 vías).
        """
        print(f"[TCP] Intentando conectar con el Servidor Central en {self.server_host}:{self.server_tcp_port}...")
        
        try:
            # 1. Crear socket TCP (SOCK_STREAM)
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Establecer un tiempo de espera máximo para la conexión
            self.tcp_socket.settimeout(5.0)

            # 2. Conectar al servidor remoto (Inicia el Handshake TCP: SYN -> SYN-ACK -> ACK)
            self.tcp_socket.connect((self.server_host, self.server_tcp_port))
            
            # Remover timeout para operaciones subsecuentes de recepción si se desea
            self.tcp_socket.settimeout(None)
            self.is_connected = True
            print("[TCP] ¡Conexión TCP establecida con éxito con el servidor!")
            return True

        except socket.timeout:
            print("[ERROR TCP] Tiempo de espera agotado. El servidor no respondió a tiempo.")
            return False
        except ConnectionRefusedError:
            print(f"[ERROR TCP] Conexión rechazada. Verifique si el servidor está en ejecución en el puerto {self.server_tcp_port}.")
            return False
        except Exception as e:
            print(f"[ERROR TCP] No se pudo establecer la conexión: {e}")
            return False

    def send_command(self, action: str, *params) -> dict:
        """
        Envía un comando al servidor por el socket TCP y retorna la respuesta parseada.
        """
        if not self.is_connected:
            print("[ERROR] No hay una conexión TCP activa con el servidor.")
            return {"status": "ERR", "payload_or_code": "NOT_CONNECTED", "detail": "Desconectado"}

        try:
            # 1. Construir la trama según el protocolo NETMON/1.0
            cmd_str = build_tcp_command(action, *params)
            raw_bytes = encode_message(cmd_str)

            # 2. Transmitir por el socket TCP usando sendall()
            self.tcp_socket.sendall(raw_bytes)

            # 3. Recibir la respuesta del servidor usando recv()
            response_bytes = self.tcp_socket.recv(BUFFER_SIZE)
            
            if not response_bytes:
                print("[TCP] El servidor cerró la conexión.")
                self.is_connected = False
                return {"status": "ERR", "payload_or_code": "SERVER_DISCONNECTED", "detail": "Conexión cerrada"}

            response_str = decode_message(response_bytes)
            
            # 4. Parsear la respuesta
            return parse_tcp_response(response_str)

        except Exception as e:
            print(f"[ERROR TCP en transmisión/recepción]: {e}")
            self.is_connected = False
            return {"status": "ERR", "payload_or_code": "SOCKET_ERROR", "detail": str(e)}

    def authenticate_interactive(self):
        """
        Flujo de autenticación interactivo por consola.
        """
        print("\n--- AUTENTICACIÓN DE ADMINISTRADOR ---")
        user = input("Usuario (ej. admin): ").strip()
        password = input("Contraseña (ej. admin123): ").strip()

        resp = self.send_command("AUTH", user, password)
        if resp["status"] == "OK":
            self.is_authenticated = True
            self.username = user
            print(f"✅ ¡Autenticación Exitosa! {resp['detail']}")
        else:
            print(f"❌ Error de Autenticación [{resp['payload_or_code']}]: {resp['detail']}")

    def show_nodes_interactive(self):
        """
        Consulta y muestra la lista de nodos registrados en el servidor.
        """
        resp = self.send_command("GET_NODES", "ALL")
        print("\n=================================================================")
        print(" ESTADO DE NODOS EN LA RED (TELEMETRÍA RECIBIDA VÍA UDP)")
        print("=================================================================")

        if resp["status"] != "OK":
            print(f"❌ Error al consultar nodos [{resp['payload_or_code']}]: {resp['detail']}")
            return

        payload = resp["payload_or_code"]
        parts = payload.split(";")
        count_header = parts[0]  # NODES_COUNT:N
        
        print(f"Información: {count_header} | Detalle: {resp['detail']}")
        print("-----------------------------------------------------------------")
        
        if len(parts) > 1 and parts[1]:
            for node_raw in parts[1:]:
                # Formato: ID:IP:STATUS:CPU:RAM:DISK
                node_fields = node_raw.split(":")
                if len(node_fields) >= 6:
                    n_id, ip, status, cpu, ram, disk = node_fields[0], node_fields[1], node_fields[2], node_fields[3], node_fields[4], node_fields[5]
                    status_icon = "🟢 ONLINE" if status == "OK" else ("⚠️ WARNING" if status == "WARNING" else "🔴 OFFLINE")
                    print(f" NODO: {n_id:<12} | IP: {ip:<15} | Estado: {status_icon:<12} | {cpu} | {ram} | {disk}")
        else:
            print(" No hay nodos registrados en este momento. Inicie un Agente UDP.")
        print("-----------------------------------------------------------------")

    def execute_remote_command_interactive(self):
        """
        Envía una orden remota a un nodo a través del servidor central.
        """
        node_id = input("Ingrese el ID del nodo destino (ej. NODO_01): ").strip()
        cmd_name = input("Ingrese la acción/comando (ej. RESTART, DIAGNOSTIC, CLEAR_LOGS): ").strip()

        resp = self.send_command("EXEC", node_id, cmd_name)
        if resp["status"] == "OK":
            print(f"✅ Éxito [{resp['payload_or_code']}]: {resp['detail']}")
        else:
            print(f"❌ Error [{resp['payload_or_code']}]: {resp['detail']}")

    def send_malformed_test(self):
        """
        Permite enviar paquetes malformados o inválidos a propósito para verificar
        el manejo de errores y validaciones en el servidor (RF07 / Seccion 6 del TP).
        """
        print("\n--- PRUEBA DE VALIDACIÓN Y MANEJO DE ERRORES (DATOS INVÁLIDOS) ---")
        print(" 1. Enviar cadena sin cabecera CMD ('DATOS_BASURA_SIN_CMD')")
        print(" 2. Enviar comando inexistente ('CMD|ACCION_DESCONOCIDA')")
        print(" 3. Enviar comando AUTH con parámetros faltantes ('CMD|AUTH')")
        print(" 4. Escribir una cadena personalizada personalizada para enviar por el socket")
        sub_opt = input("Seleccione tipo de prueba (1-4): ").strip()

        payload = ""
        if sub_opt == "1":
            payload = "DATOS_BASURA_SIN_CMD"
        elif sub_opt == "2":
            payload = "CMD|ACCION_DESCONOCIDA"
        elif sub_opt == "3":
            payload = "CMD|AUTH"
        elif sub_opt == "4":
            payload = input("Ingrese el texto exacto a enviar por el socket TCP: ").strip()
        else:
            print("Opción inválida. Cancelando prueba.")
            return

        print(f"\n[CLIENTE TCP] Enviando trama por socket: '{payload}'")
        try:
            # Transmitir la cadena cruda codificada
            self.tcp_socket.sendall(encode_message(payload))
            
            # Recibir respuesta del servidor
            response_bytes = self.tcp_socket.recv(BUFFER_SIZE)
            respuesta = decode_message(response_bytes)
            
            print("-----------------------------------------------------------------")
            print(f"📩 [RESPUESTA DEL SERVIDOR (TCP)]: {respuesta}")
            print("-----------------------------------------------------------------")
            print("💡 Explicación: El servidor procesó el error sin colapsar ni cerrar la conexión.")
        except Exception as e:
            print(f"[Error en prueba de transmisión]: {e}")

    def run_menu(self):
        """
        Menú de opciones interactivo.
        """
        if not self.connect():
            return

        while self.is_connected:
            auth_str = f"(Autenticado como: {self.username})" if self.is_authenticated else "(No autenticado)"
            print(f"\n===== MENÚ DE ADMINISTRACIÓN SDMR {auth_str} =====")
            print(" 1. Probar Conectividad PING (TCP)")
            print(" 2. Iniciar Sesión / Autenticar (AUTH)")
            print(" 3. Listar Nodos Monitoreados (GET_NODES)")
            print(" 4. Ejecutar Comando Remoto en Nodo (EXEC)")
            print(" 5. Probar Envío de Datos Inválidos / Malformados (Prueba de Errores)")
            print(" 6. Desconectar y Salir")
            print("==================================================")
            
            option = input("Seleccione una opción (1-6): ").strip()

            if option == "1":
                resp = self.send_command("PING")
                print(f"\n[Respuesta PING]: Status={resp['status']} | Response={resp['payload_or_code']} | Detail={resp['detail']}")
            elif option == "2":
                self.authenticate_interactive()
            elif option == "3":
                self.show_nodes_interactive()
            elif option == "4":
                self.execute_remote_command_interactive()
            elif option == "5":
                self.send_malformed_test()
            elif option == "6":
                print("\n[TCP] Cerrando conexión TCP y saliendo...")
                self.close()
                break
            else:
                print("\n❌ Opción no válida. Intente nuevamente.")

    def close(self):
        """
        Cierra limpiamente el socket TCP.
        """
        self.is_connected = False
        if self.tcp_socket:
            try:
                self.tcp_socket.close()
            except Exception:
                pass
        print("[TCP] Socket cerrado.")


if __name__ == "__main__":
    host_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port_tcp = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TCP_PORT

    client = AdminClient(server_host=host_ip, server_tcp_port=port_tcp)
    client.run_menu()
