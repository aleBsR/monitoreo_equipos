"""
===============================================================================
Agente de Monitoreo de Equipo en Red (Node Agent)
===============================================================================
Este programa representa un Agente instalado en un equipo de la red.
Su función principal es medir periódicamente los recursos locales del sistema
(Uso de CPU, Memoria RAM y Espacio en Disco) y transmitirlos al Servidor Central
mediante datagramas UDP (socket no orientado a conexión).

¿Por qué UDP para la telemetría?
  - Alta frecuencia de envío (cada 3 segundos).
  - Mínima sobrecarga de encabezados en la red.
  - Sin necesidad de mantener una sesión activa constante (handshake TCP).

¿Por qué TCP para los comandos remotos (EXEC)?
  - Cada orden administrativa debe llegar sí o sí y ser confirmada.
  - El servidor abre una conexión al canal de control del agente, envía
    'EXECCMD|<COMANDO>' y el agente responde con el resultado (entrega confiable).
===============================================================================
"""

import os
import socket
import sys
import threading
import time
import random

# Intentar importar psutil para métricas reales del sistema
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Permitir importar el protocolo común
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.protocol import (
    DEFAULT_UDP_PORT,
    DEFAULT_AGENT_TCP_PORT,
    BUFFER_SIZE,
    ENCODING,
    ERR_MALFORMED_REQUEST,
    ERR_NODE_UNREACHABLE,
    build_udp_telemetry,
    build_tcp_response,
    parse_exec_command,
    encode_message,
    TcpFrameReader,
    FrameTooLongError
)

# Comandos administrativos que el agente acepta ejecutar (lista permitida).
# Es una simulación controlada: no se ejecuta nada arbitrario del sistema.
COMANDOS_PERMITIDOS = {
    "RESTART_SERVICE": "Servicio de monitoreo reiniciado correctamente",
    "DIAGNOSTIC": "Diagnóstico ejecutado: sin errores detectados",
    "CLEAR_LOGS": "Registros temporales eliminados correctamente",
}

# Bitácora local de comandos recibidos (evidencia para el informe/video)
RUTA_HISTORIAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historial_comandos.log")


class SystemNodeAgent:
    """
    Agente cliente encargado de recopilar métricas del sistema local y
    transmitirlas por UDP al servidor central. Además escucha por TCP
    órdenes EXEC enviadas por el servidor.
    """

    def __init__(self, node_id: str, server_host: str = "127.0.0.1", server_udp_port: int = DEFAULT_UDP_PORT,
                 interval: float = 3.0, cmd_port: int = DEFAULT_AGENT_TCP_PORT, bind_host: str = "0.0.0.0"):
        self.node_id = node_id
        self.server_host = server_host
        self.server_udp_port = server_udp_port
        self.interval = interval
        self.cmd_port = cmd_port
        self.bind_host = bind_host
        self.is_running = False

        # Socket UDP (AF_INET, SOCK_DGRAM): no requiere connect(), envía con sendto()
        self.udp_socket = None
        # Socket TCP de control (AF_INET, SOCK_STREAM): recibe órdenes EXEC del servidor
        self.tcp_socket = None

    # -------------------------------------------------------------------------
    # MÉTRICAS DEL SISTEMA
    # -------------------------------------------------------------------------

    def get_system_metrics(self) -> tuple:
        """
        Obtiene las métricas actuales del sistema.
        Utiliza `psutil` si está disponible; de lo contrario, simula valores para pruebas.

        :return: Tupla (cpu_percent, ram_percent, disk_percent)
        """
        if HAS_PSUTIL:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            return cpu, ram, disk
        else:
            # Métricas simuladas dinámicas para entorno de desarrollo o pruebas sin psutil
            cpu = round(random.uniform(10.0, 85.0), 1)
            ram = round(random.uniform(30.0, 75.0), 1)
            disk = round(random.uniform(40.0, 50.0), 1)
            return cpu, ram, disk

    # -------------------------------------------------------------------------
    # CANAL DE COMANDOS (TCP / EXEC)
    # -------------------------------------------------------------------------

    def _detectar_ip_local(self) -> str:
        """
        Devuelve la IP de la interfaz local que realmente se usa para llegar
        al servidor (no necesariamente la del hostname).

        Se abre un socket UDP y se hace connect() hacia el servidor: no se
        envía un solo byte, solo se deja que el sistema elija la interfaz de
        salida y luego se lee la IP asignada con getsockname(). Con esto el
        campo IP de la telemetría coincide con la IP vista por el servidor,
        que es la que se usa para reenviar los EXEC.

        :return: Cadena con la IP local, o "127.0.0.1" si no se puede resolver.
        """
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.server_host, self.server_udp_port))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def _log_comando(self, comando: str, resultado: str):
        """Registra en consola y en archivo cada comando administrativo recibido."""
        marca = time.strftime("%Y-%m-%d %H:%M:%S")
        linea = f"{marca} | {self.node_id} | {comando} | {resultado}"
        print(f"[EXEC] {linea}")
        try:
            with open(RUTA_HISTORIAL, "a", encoding=ENCODING) as f:
                f.write(linea + "\n")
        except OSError as e:
            print(f"[AGENTE - Advertencia] No se pudo escribir el historial: {e}")

    def _iniciar_canal_comandos(self):
        """
        Abre el socket TCP de control donde el servidor enviará órdenes EXEC.
        Si el puerto está ocupado, el agente sigue reportando telemetría pero
        sin aceptar comandos (el servidor devolverá ERR_104 al intentar EXEC).
        """
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_socket.bind((self.bind_host, self.cmd_port))
            self.tcp_socket.listen(5)
        except OSError as e:
            puerto_fallido = self.cmd_port
            self.tcp_socket = None
            self.cmd_port = None
            print(f"[AGENTE - Advertencia] No se pudo abrir el canal de comandos TCP en el puerto {puerto_fallido}: {e}")
            print("[AGENTE - Advertencia] El nodo enviará telemetría pero NO aceptará comandos EXEC.")
            return

        print(f"[TCP Control] Canal de comandos EXEC en escucha en {self.bind_host}:{self.cmd_port}")
        hilo = threading.Thread(target=self._loop_comandos, daemon=True)
        hilo.start()

    def _loop_comandos(self):
        """Acepta conexiones del servidor y atiende cada una en un hilo aparte."""
        while self.is_running:
            try:
                conexion, direccion = self.tcp_socket.accept()
            except OSError:
                break
            threading.Thread(target=self._atender_comando, args=(conexion, direccion), daemon=True).start()

    def _atender_comando(self, conexion: socket.socket, direccion: tuple):
        """Lee órdenes encuadradas por '\\n' y responde el resultado de cada una."""
        reader = TcpFrameReader()
        try:
            while self.is_running:
                datos = conexion.recv(BUFFER_SIZE)
                if not datos:
                    break
                try:
                    tramas = reader.feed(datos)
                except FrameTooLongError as fle:
                    conexion.sendall(encode_message(build_tcp_response("ERR", ERR_MALFORMED_REQUEST, str(fle))))
                    continue
                for trama in tramas:
                    conexion.sendall(encode_message(self._procesar_orden(trama)))
        except (ConnectionResetError, OSError):
            pass
        finally:
            conexion.close()

    def _procesar_orden(self, trama: str) -> str:
        """
        Valida la orden recibida contra la lista permitida y arma la respuesta.

        :return: Trama 'RES|OK|...' o 'RES|ERR|...' según el resultado.
        """
        try:
            orden = parse_exec_command(trama)
        except ValueError as ve:
            return build_tcp_response("ERR", ERR_MALFORMED_REQUEST, str(ve))

        comando = orden["command"].upper()

        if comando not in COMANDOS_PERMITIDOS:
            self._log_comando(comando, "RECHAZADO (comando no soportado)")
            return build_tcp_response(
                "ERR", ERR_NODE_UNREACHABLE,
                f"Comando '{comando}' no soportado por el nodo '{self.node_id}'"
            )

        resultado = COMANDOS_PERMITIDOS[comando]
        self._log_comando(comando, resultado)
        return build_tcp_response("OK", comando, resultado)

    # -------------------------------------------------------------------------
    # BUCLE PRINCIPAL
    # -------------------------------------------------------------------------

    def start(self):
        """Inicia el canal de comandos TCP y el bucle de telemetría UDP periódica."""
        self.is_running = True

        # IP de la interfaz que realmente llega al servidor (o 127.0.0.1)
        local_ip = self._detectar_ip_local()

        print("=================================================================")
        print(f" INICIANDO AGENTE DE MONITOREO - ID: '{self.node_id}'")
        print("=================================================================")
        print(f"Destino del Servidor UDP: {self.server_host}:{self.server_udp_port}")
        print(f"IP local de este equipo: {local_ip}")
        print(f"Frecuencia de envío: Cada {self.interval} segundos")
        print(f"Uso de métricas reales (psutil): {'SÍ' if HAS_PSUTIL else 'NO (Simuladas)'}")
        print("-----------------------------------------------------------------")

        # Crear el socket UDP para el envío de datagramas
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Abrir el canal TCP que recibe las órdenes EXEC del servidor
        self._iniciar_canal_comandos()

        try:
            while self.is_running:
                # 1. Medir recursos
                cpu, ram, disk = self.get_system_metrics()

                # Determinar estado de salud según umbrales de recursos
                status = "WARNING" if (cpu > 80.0 or ram > 85.0) else "OK"

                # 2. Construir la trama del protocolo NETMON/1.0 (incluye el
                #    puerto de comandos para que el servidor pueda hacer EXEC)
                telemetry_str = build_udp_telemetry(self.node_id, local_ip, cpu, ram, disk, status, self.cmd_port)
                raw_bytes = encode_message(telemetry_str)

                # 3. Transmitir el datagrama UDP utilizando sendto()
                self.udp_socket.sendto(raw_bytes, (self.server_host, self.server_udp_port))

                print(f"[UDP Sent] Telemetría enviada -> CPU: {cpu}% | RAM: {ram}% | Disco: {disk}% | Estado: {status}")

                # Esperar el intervalo configurado
                time.sleep(self.interval)

        except KeyboardInterrupt:
            print(f"\n[AGENTE '{self.node_id}'] Deteniendo la transmisión de telemetría...")
        except Exception as e:
            print(f"[AGENTE - Error] Ocurrió una falla en la transmisión UDP: {e}")
        finally:
            self.stop()

    def stop(self):
        """Cierra de forma segura los sockets UDP y TCP."""
        self.is_running = False
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except OSError:
                pass
        if self.tcp_socket:
            try:
                self.tcp_socket.close()
            except OSError:
                pass
        print(f"[AGENTE '{self.node_id}'] Sockets liberados y agente detenido.")


if __name__ == "__main__":
    # Parámetros desde línea de comandos: <node_id> <server_ip> <server_port> [cmd_tcp_port]
    node_name = sys.argv[1] if len(sys.argv) > 1 else "NODO_01"
    srv_ip = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    srv_port = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_UDP_PORT
    cmd_tcp_port = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_AGENT_TCP_PORT

    agent = SystemNodeAgent(node_id=node_name, server_host=srv_ip, server_udp_port=srv_port, cmd_port=cmd_tcp_port)
    agent.start()
