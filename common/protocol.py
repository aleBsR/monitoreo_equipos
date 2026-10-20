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

  - UDP (Descubrimiento del servidor, ambos sentidos):
      Agente -> red (broadcast):  SRVREQ|<ID_NODO>
      Servidor -> agente (unicast): SRVINFO|<IP_SERVIDOR>|<PUERTO_UDP>|<PUERTO_TCP>
      El agente arranca sin conocer la IP del servidor: emite SRVREQ hasta que
      un servidor le responda SRVINFO con su dirección. Si `agent/config.ini`
      trae la IP escrita, el descubrimiento se salta.

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
from collections import deque

# Versión del protocolo
PROTOCOL_VERSION = "NETMON/1.0"

# Puertos por defecto asignados para la aplicación
DEFAULT_UDP_PORT = 5000  # Canal de baja latencia para Telemetría / Heartbeats
DEFAULT_TCP_PORT = 5001  # Canal confiable para Comandos y Autenticación
DEFAULT_AGENT_TCP_PORT = 5002  # Canal de control del AGENTE (recibe comandos EXEC)

# Delimitador utilizado para separar campos dentro de los mensajes de texto plano
DELIMITER = "|"
ENCODING = "utf-8"
BUFFER_SIZE = 4096  # Tamaño de búfer para lectura de sockets (bytes)

# Tope de longitud de una única trama TCP. Protege al servidor contra
# basura que nunca llega con '\n' y haría crecer el búfer sin límite.
MAX_FRAME_SIZE = 8192

# Codigos de Error Oficiales del Protocolo
ERR_MALFORMED_REQUEST = "ERR_100"  # Mensaje con formato incorrecto o faltan parámetros
ERR_UNAUTHORIZED      = "ERR_101"  # Error de autenticación o falta de permisos
ERR_NODE_NOT_FOUND    = "ERR_102"  # El nodo especificado no existe o está OFFLINE
ERR_UNKNOWN_COMMAND   = "ERR_103"  # El comando TCP solicitado no es válido
ERR_NODE_UNREACHABLE  = "ERR_104"  # El nodo no respondió o no soporta el comando EXEC
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

def build_udp_telemetry(node_id: str, ip: str, cpu: float, ram: float, disk: float, status: str = "OK", cmd_port: int = None) -> str:
    """
    Construye la trama de texto para un reporte de telemetría por UDP.

    Formato: MON|<node_id>|<ip>|<cpu>|<ram>|<disk>|<status>[|<cmd_port>]

    El último campo `cmd_port` es OPCIONAL: indica el puerto TCP donde el
    agente escucha comandos EXEC. Se incluye solo si el agente tiene ese
    canal habilitado (permite que el servidor reenvíe comandos remotos).
    """
    trama = f"MON{DELIMITER}{node_id}{DELIMITER}{ip}{DELIMITER}{cpu:.1f}{DELIMITER}{ram:.1f}{DELIMITER}{disk:.1f}{DELIMITER}{status}"
    if cmd_port is not None:
        trama += f"{DELIMITER}{int(cmd_port)}"
    return trama


def parse_udp_telemetry(message: str) -> dict:
    """
    Parsea y valida un mensaje de telemetría UDP.

    Acepta 7 campos (formato original) u 8 campos (con puerto de comandos).
    Valida tipo, rango de métricas y coherencia del puerto.

    :param message: Cadena de mensaje recibida por UDP.
    :return: Diccionario con los datos del nodo parseados.
    :raises ValueError: Si el formato o los datos son inválidos.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 7 or parts[0] != "MON":
        raise ValueError(f"Formato de paquete UDP invalido: '{message}'")

    node_id = parts[1].strip()
    ip = parts[2].strip()

    if not node_id:
        raise ValueError("El ID de nodo no puede estar vacío.")

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

    # Campo OPCIONAL: puerto TCP de comandos del agente (para EXEC remoto)
    cmd_port = None
    if len(parts) >= 8 and parts[7].strip():
        try:
            cmd_port = int(parts[7])
        except ValueError:
            raise ValueError("El puerto de comandos del nodo debe ser un entero.")
        if not (1 <= cmd_port <= 65535):
            raise ValueError("El puerto de comandos del nodo debe estar dentro de [1, 65535].")

    return {
        "type": "TELEMETRY",
        "node_id": node_id,
        "ip": ip,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "status": status,
        "cmd_port": cmd_port,
        "timestamp": time.time()
    }


# =============================================================================
# FUNCIONES PARA EL DESCUBRIMIENTO AUTOMÁTICO DEL SERVIDOR (UDP)
# =============================================================================

SRVREQ_HEADER = "SRVREQ"    # Agente -> red (broadcast): "¿dónde está el servidor?"
SRVINFO_HEADER = "SRVINFO"  # Servidor -> agente (unicast): "acá estoy"


def build_srv_request(node_id: str) -> str:
    """
    Agente -> red (broadcast). Pide la dirección del Servidor Central.

    Formato: SRVREQ|<node_id>
    """
    return f"{SRVREQ_HEADER}{DELIMITER}{node_id}"


def parse_srv_request(message: str) -> dict:
    """
    Servidor: parsea una solicitud de descubrimiento.

    :return: {'node_id': str}
    :raises ValueError: Si no es un SRVREQ válido.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 2 or parts[0] != SRVREQ_HEADER:
        raise ValueError(f"No es una solicitud de descubrimiento: '{message}'")

    node_id = parts[1].strip()
    if not node_id:
        raise ValueError("La solicitud de descubrimiento no incluye un ID de nodo.")

    return {"node_id": node_id}


def build_srv_info(node_id: str, server_ip: str, udp_port: int, tcp_port: int) -> str:
    """
    Servidor -> agente (unicast): dirección y puertos del Servidor Central.

    Formato: SRVINFO|<node_id>|<IP_SERVIDOR>|<PUERTO_UDP>|<PUERTO_TCP>

    Se devuelve el `node_id` pedido para que el agente sepa que la respuesta
    es para él y no para otro nodo que también estaba descubriendo.
    """
    return f"{SRVINFO_HEADER}{DELIMITER}{node_id}{DELIMITER}{server_ip}{DELIMITER}{int(udp_port)}{DELIMITER}{int(tcp_port)}"


def parse_srv_info(message: str) -> dict:
    """
    Agente: parsea la respuesta de descubrimiento.

    :return: {'node_id': str, 'server_ip': str, 'udp_port': int, 'tcp_port': int}
    :raises ValueError: Si no es un SRVINFO válido o los puertos no son válidos.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 5 or parts[0] != SRVINFO_HEADER:
        raise ValueError(f"No es una respuesta de descubrimiento: '{message}'")

    node_id = parts[1].strip()
    server_ip = parts[2].strip()

    if not node_id:
        raise ValueError("SRVINFO sin ID de nodo.")
    if not server_ip:
        raise ValueError("SRVINFO sin dirección IP del servidor.")

    try:
        udp_port = int(parts[3])
        tcp_port = int(parts[4])
    except ValueError:
        raise ValueError("Los puertos de SRVINFO deben ser enteros.")

    if not (1 <= udp_port <= 65535) or not (1 <= tcp_port <= 65535):
        raise ValueError("Los puertos de SRVINFO deben estar dentro de [1, 65535].")

    return {
        "node_id": node_id,
        "server_ip": server_ip,
        "udp_port": udp_port,
        "tcp_port": tcp_port,
    }


def es_trama_descubrimiento(message: str) -> bool:
    """Indica si una trama UDP es de descubrimiento (SRVREQ o SRVINFO)."""
    return message.startswith(f"{SRVREQ_HEADER}{DELIMITER}") or message.startswith(
        f"{SRVINFO_HEADER}{DELIMITER}"
    )


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


# =============================================================================
# MENSAJES DE CONTROL SERVIDOR <-> AGENTE (EXEC REMOTO)
# =============================================================================

def build_exec_command(comando: str) -> str:
    """
    Servidor -> Agente: orden de ejecución remota.
    Formato: EXECCMD|<COMANDO>
    """
    return f"EXECCMD{DELIMITER}{comando}"


def parse_exec_command(message: str) -> dict:
    """
    Agente: parsea la orden de ejecución recibida del servidor.

    :raises ValueError: Si la cadena no inicia con 'EXECCMD' o no trae comando.
    """
    parts = message.split(DELIMITER)
    if len(parts) < 2 or parts[0] != "EXECCMD":
        raise ValueError("La orden de ejecución debe iniciar con la cabecera 'EXECCMD'")

    comando = parts[1].strip()
    if not comando:
        raise ValueError("La orden de ejecución no incluye un comando.")

    return {"action": "EXEC", "command": comando}


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


# =============================================================================
# ENCUADRADO (FRAMING) DE TRAMAS SOBRE TCP
# =============================================================================

class FrameTooLongError(ValueError):
    """
    Señala que una trama TCP superó el tamaño máximo permitido
    (el emisor nunca envió '\\n' y el búfer crecería sin límite).
    """


class TcpFrameReader:
    """
    Acumulador de tramas por conexión TCP.

    TCP es un flujo de bytes, no un transporte de mensajes: `recv()` puede
    devolver **una trama partida en dos** o **dos tramas juntas en un mismo
    segmento**. Este separador acumula bytes hasta encontrar '\\n' y entrega
    tramas completas, evitando que se concatenen comandos o se parseen
    respuestas truncadas.

    Uso típico (un lector por conexión):

        reader = TcpFrameReader()
        while True:
            datos = socket.recv(BUFFER_SIZE)
            if not datos:
                break
            try:
                reader.feed(datos)
            except FrameTooLongError:
                # trama inválida: descartar y responder ERR_100
                continue
            while reader.hay_tramas():
                trama = reader.siguiente_trama()
                ...
    """

    def __init__(self, max_frame_size: int = MAX_FRAME_SIZE):
        # Búfer de bytes crudos: solo se decodifican tramas COMPLETAS, así
        # nunca se corta una secuencia UTF-8 multibyte por la mitad.
        self._buffer = b""
        self._max_frame_size = max_frame_size
        self._frames = deque()

    def feed(self, data: bytes) -> list:
        """
        Añade bytes recibidos desde el socket y separa las tramas completas.

        :param data: Fragmento de bytes recibido con `recv()`.
        :return: Lista con las tramas completas encontradas en esta tanda.
        :raises FrameTooLongError: Si el búfer supera el máximo sin '\\n'.
        """
        self._buffer += data
        nuevas = []

        while b"\n" in self._buffer:
            crudo, self._buffer = self._buffer.split(b"\n", 1)
            texto = crudo.decode(ENCODING, errors="replace").strip()
            if texto:  # se ignoran tramas vacías (p. ej. el '\n' final suelto)
                self._frames.append(texto)
                nuevas.append(texto)

        if len(self._buffer) > self._max_frame_size:
            self.reset()
            raise FrameTooLongError(
                f"La trama supera el tamaño máximo de {self._max_frame_size} bytes sin incluir '\\n'."
            )

        return nuevas

    def hay_tramas(self) -> bool:
        """Indica si hay tramas completas listas para consumir."""
        return bool(self._frames)

    def siguiente_trama(self) -> str:
        """
        Devuelve la siguiente trama completa en orden de llegada.

        :raises IndexError: Si no hay tramas pendientes.
        """
        return self._frames.popleft()

    def reset(self):
        """Descarta el búfer y las tramas pendientes (conexión contaminada)."""
        self._buffer = b""
        self._frames.clear()
