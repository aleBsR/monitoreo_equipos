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
===============================================================================
"""

import socket
import sys
import time
import random
import os

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
    ENCODING,
    build_udp_telemetry,
    encode_message
)


class SystemNodeAgent:
    """
    Agente cliente encargado de recopilar métricas del sistema local y
    transmitirlas por UDP al servidor central.
    """

    def __init__(self, node_id: str, server_host: str = "127.0.0.1", server_udp_port: int = DEFAULT_UDP_PORT, interval: float = 3.0):
        self.node_id = node_id
        self.server_host = server_host
        self.server_udp_port = server_udp_port
        self.interval = interval
        self.is_running = False

        # Socket UDP (AF_INET, SOCK_DGRAM)
        # No requiere conectar (connect), ya que envía paquetes directos mediante sendto()
        self.udp_socket = None

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

    def start(self):
        """
        Inicia el bucle de transmisión periódica de métricas por UDP.
        """
        self.is_running = True
        print("=================================================================")
        print(f" INICIANDO AGENTE DE MONITOREO - ID: '{self.node_id}'")
        print("=================================================================")
        print(f"Destino del Servidor UDP: {self.server_host}:{self.server_udp_port}")
        print(f"Frecuencia de envío: Cada {self.interval} segundos")
        print(f"Uso de métricas reales (psutil): {'SÍ' if HAS_PSUTIL else 'NO (Simuladas)'}")
        print("-----------------------------------------------------------------")

        # Crear el socket UDP para el envío de datagramas
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Obtener la IP local del equipo (o usar 127.0.0.1)
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

        try:
            while self.is_running:
                # 1. Medir recursos
                cpu, ram, disk = self.get_system_metrics()

                # Determinar estado de salud según umbrales de recursos
                status = "WARNING" if (cpu > 80.0 or ram > 85.0) else "OK"

                # 2. Construir la trama del protocolo NETMON/1.0
                telemetry_str = build_udp_telemetry(self.node_id, local_ip, cpu, ram, disk, status)
                raw_bytes = encode_message(telemetry_str)

                # 3. Transmitir el datagrama UDP utilizando sendto()
                # sendto(datos, (ip_destino, puerto_destino)) envía el paquete sin requerir handshake previo
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
        """
        Cierra de forma segura el socket UDP.
        """
        self.is_running = False
        if self.udp_socket:
            self.udp_socket.close()
        print(f"[AGENTE '{self.node_id}'] Socket liberado y agente detenido.")


if __name__ == "__main__":
    # Parámetros desde línea de comandos: <node_id> <server_ip> <server_port>
    node_name = sys.argv[1] if len(sys.argv) > 1 else "NODO_01"
    srv_ip = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    srv_port = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_UDP_PORT

    agent = SystemNodeAgent(node_id=node_name, server_host=srv_ip, server_udp_port=srv_port)
    agent.start()
