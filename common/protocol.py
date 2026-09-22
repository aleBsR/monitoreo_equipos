"""
===============================================================================
Módulo de Protocolo de Aplicación: NETMON/1.0
===============================================================================
Este archivo define la especificación, constantes, funciones de formateo y
mecanismos de validación para el protocolo de capa de aplicación propio 'NETMON/1.0'.

Tanto el Servidor, como el Agente y el Cliente Administrador utilizan este
módulo para codificar (encode) y decodificar (decode) mensajes de red sobre
sockets TCP y UDP.

Estructura de Mensajes:
  - UDP (Telemetría):
      MON|<ID_NODO>|<IP>|<CPU_%>|<RAM_%>|<DISK_%>|<STATUS>
      Ejemplo: MON|NODO_01|127.0.0.1|34.5|62.0|45.2|OK

  - TCP (Comandos Solicitud):
      CMD|<ACCION>|<PARAM1>|<PARAM2>|...
      Ejemplo: CMD|AUTH|admin|admin123
      Ejemplo: CMD|GET_NODES|ALL
      Ejemplo: CMD|EXEC|NODO_01|RESTART

  - TCP (Respuestas):
      RES|<ESTADO>|<DATOS_O_CODIGO_ERROR>|<DETALLE>
      Ejemplo: RES|OK|AUTH_SUCCESS|Sesion iniciada correctamente
      Ejemplo: RES|ERR|ERR_101|Credenciales de administrador invalidas
===============================================================================
"""

import json
import time

# Versión del protocolo
PROTOCOL_VERSION = "NETMON/1.0"

# Puertos por defecto asignados para la aplicación
DEFAULT_UDP_PORT = 5000  # Canal de baja latencia para Telemetría / Heartbeats
DEFAULT_TCP_PORT = 5001  # Canal confiable para Comandos y Autenticación

# Delimitador utilizado para separar campos dentro de los mensajes de texto plano
DELIMITER = "|"
ENCODING = "utf-8"
BUFFER_SIZE = 4096  # Tamaño de búfer para lectura de sockets (bytes)

# Codigos de Error Oficiales del Protocolo
ERR_MALFORMED_REQUEST = "ERR_100"  # Mensaje con formato incorrecto o faltan parámetros
ERR_UNAUTHORIZED      = "ERR_101"  # Error de autenticación o falta de permisos
ERR_NODE_NOT_FOUND    = "ERR_102"  # El nodo especificado no existe o está OFFLINE
ERR_UNKNOWN_COMMAND   = "ERR_103"  # El comando TCP solicitado no es válido
ERR_INTERNAL_SERVER   = "ERR_500"  # Error interno del servidor


def encode_message(data: str) -> bytes:
    """
    Convierte una cadena de texto en bytes listos para ser enviados por el socket.
    Agrega un carácter de fin de línea '\\n' como delimitador de trama TCP.
    
    :param data: Cadena de texto a codificar.
    :return: Objeto de bytes codificado en UTF-8.
    """
    if not data.endswith("\n"):
        data += "\n"
    return data.encode(ENCODING)


def decode_message(raw_bytes: bytes) -> str:
    """
    Convierte los bytes recibidos desde un socket en una cadena de texto UTF-8 limpia.
    
    :param raw_bytes: Bytes recibidos por el socket.
    :return: Cadena de texto sin espacios en blanco ni saltos de línea finales.
    """
    return raw_bytes.decode(ENCODING).strip()


# =============================================================================
# FUNCIONES PARA MENSAJES UDP (TELEMETRÍA DE NODOS)
# =============================================================================

def build_udp_telemetry(node_id: str, ip: str, cpu: float, ram: float, disk: float, status: str = "OK") -> str:
    """
    Construye la trama de texto para un reporte de telemetría por UDP.
    
    Formato: MON|<node_id>|<ip>|<cpu>|<ram>|<disk>|<status>
    """
    return f"MON{DELIMITER}{node_id}{DELIMITER}{ip}{DELIMITER}{cpu:.1f}{DELIMITER}{ram:.1f}{DELIMITER}{disk:.1f}{DELIMITER}{status}"


def parse_udp_telemetry(message: str) -> dict:
    """
    Parsea y valida un mensaje de telemetría UDP.
    
    :param message: Cadena de mensaje recibida por UDP.
    :return: Diccionario con los datos del nodo parseados.
    :raises ValueError: Si el formato o los datos son inválidos.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 7 or parts[0] != "MON":
        raise ValueError(f"Formato de paquete UDP invalido: '{message}'")

    node_id = parts[1].strip()
    ip = parts[2].strip()
    
    try:
        cpu = float(parts[3])
        ram = float(parts[4])
        disk = float(parts[5])
    except ValueError:
        raise ValueError("Los valores de CPU, RAM y Disco deben ser números flotantes.")

    # Validaciones de integridad lógica
    if not (0.0 <= cpu <= 100.0) or not (0.0 <= ram <= 100.0) or not (0.0 <= disk <= 100.0):
        raise ValueError("Los porcentajes de recursos deben estar dentro del rango [0, 100].")

    status = parts[6].strip()

    return {
        "type": "TELEMETRY",
        "node_id": node_id,
        "ip": ip,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "status": status,
        "timestamp": time.time()
    }


# =============================================================================
# FUNCIONES PARA MENSAJES TCP (COMANDOS Y RESPUESTAS)
# =============================================================================

def build_tcp_command(action: str, *params) -> str:
    """
    Construye una solicitud de comando TCP.
    
    Ejemplo: build_tcp_command("AUTH", "admin", "1234") -> "CMD|AUTH|admin|1234"
    """
    parts = ["CMD", action.upper()] + [str(p) for p in params]
    return DELIMITER.join(parts)


def parse_tcp_command(message: str) -> dict:
    """
    Parsea una cadena recibida por TCP y la convierte en una estructura de comando.
    
    :param message: Cadena recibida por el socket TCP.
    :return: Diccionario con la acción y lista de parámetros.
    :raises ValueError: Si la cadena no inicia con 'CMD' o está malformada.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 2 or parts[0] != "CMD":
        raise ValueError("El comando TCP debe iniciar con la cabecera 'CMD'")

    action = parts[1].upper()
    params = parts[2:]

    return {
        "action": action,
        "params": params
    }


def build_tcp_response(status: str, payload_or_code: str, detail: str = "") -> str:
    """
    Construye una respuesta TCP estructurada.
    
    :param status: 'OK' o 'ERR'
    :param payload_or_code: Datos de éxito o Código de error (ej: ERR_101)
    :param detail: Mensaje explicativo adicional
    :return: Cadena formateada para el protocolo
    """
    return f"RES{DELIMITER}{status}{DELIMITER}{payload_or_code}{DELIMITER}{detail}"


def parse_tcp_response(message: str) -> dict:
    """
    Parsea la respuesta enviada por el servidor TCP.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 3 or parts[0] != "RES":
        raise ValueError("La respuesta TCP debe iniciar con la cabecera 'RES'")

    status = parts[1]
    payload_or_code = parts[2]
    detail = parts[3] if len(parts) > 3 else ""

    return {
        "status": status,
        "payload_or_code": payload_or_code,
        "detail": detail
    }
