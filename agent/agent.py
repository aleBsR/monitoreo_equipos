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

¿Cómo se une a la red sin configurar nada (y sin terminal)?
  1. Si `agent/config.ini` trae `ip_servidor`, se usa esa IP y no se descubre nada.
  2. Si no, el agente emite SRVREQ por broadcast hasta recibir SRVINFO del
     Servidor Central (ver common/protocol.py). Reintenta cada 30 s, por si el
     servidor cambia de IP.
  3. Con `--silent` no abre consola: todo se registra en `agent/agente.log`.
     Los instaladores (scripts/instalar_agente.*) lo dejan corriendo oculto al
     iniciar sesión, de modo que el cliente nunca toca la terminal.
"""

import argparse
import configparser
import io
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
    DEFAULT_TCP_PORT,
    DEFAULT_AGENT_TCP_PORT,
    BUFFER_SIZE,
    ENCODING,
    ERR_MALFORMED_REQUEST,
    ERR_NODE_UNREACHABLE,
    build_udp_telemetry,
    build_tcp_response,
    parse_exec_command,
    encode_message,
    decode_message,
    build_srv_request,
    parse_srv_info,
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
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_HISTORIAL = os.path.join(RUTA_BASE, "historial_comandos.log")
RUTA_LOG = os.path.join(RUTA_BASE, "agente.log")
RUTA_CONFIG = os.path.join(RUTA_BASE, "config.ini")

# Tope del archivo de log en modo silencioso (se rotaja a .old al superarlo)
MAX_LOG_BYTES = 512 * 1024

# Segundos entre reintentos de descubrimiento (SRVREQ) durante la operación normal
REDISCOVER_INTERVALO = 30.0

# False = imprime en consola; True = solo escribe en agent/agente.log
MODO_SILENCIO = False


class _SalidaNula:
    """
    Reemplazo de sys.stdout/sys.stderr cuando no consola (pythonw.exe).

    Sin este envoltorio, cada `print()` lanzaría `AttributeError: 'NoneType'
    object has no attribute 'write'` y el agente moriría al arrancar oculto.
    """

    es_nula = True

    def write(self, texto):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


def _asegurar_salida():
    """Garantiza que stdout y stderr existan (indispensable bajo pythonw)."""
    if sys.stdout is None:
        sys.stdout = _SalidaNula()
    if sys.stderr is None:
        sys.stderr = _SalidaNula()


def _rotar_log():
    """Conserva como `agente.log.old` el log actual antes de desbordarse."""
    try:
        if os.path.exists(RUTA_LOG) and os.path.getsize(RUTA_LOG) >= MAX_LOG_BYTES:
            os.replace(RUTA_LOG, RUTA_LOG + ".old")
    except OSError:
        pass


def _escribir_log(mensaje: str):
    """Append de una línea fechada a agent/agente.log (modo silencioso)."""
    marca = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _rotar_log()
        with open(RUTA_LOG, "a", encoding=ENCODING, errors="replace") as archivo:
            archivo.write(f"{marca} {mensaje}\n")
    except OSError:
        pass


def log(mensaje: str, forzar_archivo: bool = False):
    """
    Salida unificada del agente.

    - Consola normal: imprime en pantalla.
    - `--silent` o sin consola (pythonw): escribe solo en agent/agente.log.
    """
    salida_nula = isinstance(sys.stdout, _SalidaNula)
    if MODO_SILENCIO or salida_nula or forzar_archivo:
        _escribir_log(mensaje)
    else:
        print(mensaje, flush=True)



class SystemNodeAgent:
    """
    Agente cliente encargado de recopilar métricas del sistema local y
    transmitirlas por UDP al servidor central. Además escucha por TCP
    órdenes EXEC enviadas por el servidor.
    """

    def __init__(self, node_id: str = None, server_host: str = None, server_udp_port: int = DEFAULT_UDP_PORT,
                 interval: float = 3.0, cmd_port: int = DEFAULT_AGENT_TCP_PORT, bind_host: str = "0.0.0.0"):
        # Sin ID explícito se usa el nombre de la máquina: dos agentes nunca
        # chocan y el administrador reconoce el equipo de un vistazo.
        self.node_id = node_id or socket.gethostname() or "NODO_01"
        # None = el servidor debe descubrirse por broadcast (SRVREQ -> SRVINFO)
        self.server_host = server_host or None
        # True si la IP vino de config.ini o de la línea de comandos: en ese
        # caso no se redescubre periódicamente (el usuario indicó dónde está).
        self.ip_configurada = server_host is not None
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
        """Registra en consola/log y en archivo cada comando administrativo recibido."""
        marca = time.strftime("%Y-%m-%d %H:%M:%S")
        linea = f"{marca} | {self.node_id} | {comando} | {resultado}"
        log(f"[EXEC] {linea}", forzar_archivo=True)
        try:
            with open(RUTA_HISTORIAL, "a", encoding=ENCODING) as f:
                f.write(linea + "\n")
        except OSError as e:
            log(f"[AGENTE - Advertencia] No se pudo escribir el historial: {e}")

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
            log(f"[AGENTE - Advertencia] No se pudo abrir el canal de comandos TCP en el puerto {puerto_fallido}: {e}")
            log("[AGENTE - Advertencia] El nodo enviará telemetría pero NO aceptará comandos EXEC.")
            return

        log(f"[TCP Control] Canal de comandos EXEC en escucha en {self.bind_host}:{self.cmd_port}")
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
    # DESCUBRIMIENTO AUTOMÁTICO DEL SERVIDOR (SRVREQ -> SRVINFO)
    # -------------------------------------------------------------------------

    @staticmethod
    def _en_consola() -> bool:
        """True si la salida normal (consola) está disponible y el modo no es silencioso."""
        return not MODO_SILENCIO and not isinstance(sys.stdout, _SalidaNula)

    @staticmethod
    def _broadcast_de(ip_local: str, mascara: str):
        """
        Dirección de broadcast de una interfaz a partir de su IP y máscara.

        :return: Cadena con la broadcast, o None si no se pudo calcular.
        """
        if not ip_local or not mascara:
            return None
        try:
            import ipaddress
            red = ipaddress.IPv4Network(f"{ip_local}/{mascara}", strict=False)
            destino = str(red.broadcast_address)
        except (ValueError, TypeError, ImportError):
            return None
        if destino == ip_local or destino.startswith("127."):
            return None
        return destino

    def _destinos_descubrimiento(self) -> list:
        """
        Direcciones a las que se emite el SRVREQ.

        - 255.255.255.255: broadcast limitado de la red local (el caso típico).
        - Broadcast calculada por interfaz (con psutil): cubre redes donde el
          broadcast limitado está filtrado por el punto de acceso.
        - 127.0.0.1: demo del servidor en la MISMA máquina (el broadcast no
          vuelve a los procesos locales, por eso hace falta este destino).
        """
        destinos = []

        if self.server_host:
            destinos.append(self.server_host)
        destinos.append("255.255.255.255")

        if HAS_PSUTIL:
            try:
                for interfaces in psutil.net_if_addrs().values():
                    for iface in interfaces:
                        if iface.family != socket.AF_INET:
                            continue
                        if not iface.address or iface.address.startswith("127."):
                            continue
                        broadcast = self._broadcast_de(iface.address, iface.netmask)
                        if broadcast and broadcast not in destinos:
                            destinos.append(broadcast)
            except Exception:
                pass

        if "127.0.0.1" not in destinos:
            destinos.append("127.0.0.1")
        return destinos

    def _enviar_srvreq(self):
        """Emite una solicitud de descubrimiento a todos los destinos posibles."""
        trama = encode_message(build_srv_request(self.node_id))
        for destino in self._destinos_descubrimiento():
            try:
                self.udp_socket.sendto(trama, (destino, self.server_udp_port))
            except OSError:
                # Una interfaz caída o una broadcast filtrada no debe frenar al resto
                continue

    def _escuchar_srvinfo(self, timeout: float = 2.0):
        """
        Espera pasiva de una respuesta SRVINFO dirigida a ESTE nodo.

        :param timeout: Segundos máximo de espera.
        :return: dict con la info del servidor, o None si no llegó.
        """
        limite = time.time() + timeout
        while time.time() < limite:
            restante = limite - time.time()
            if restante <= 0:
                break
            self.udp_socket.settimeout(min(0.5, restante))
            try:
                datos, _ = self.udp_socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            mensaje = decode_message(datos)
            if not mensaje.startswith("SRVINFO|"):
                continue
            try:
                info = parse_srv_info(mensaje)
            except ValueError:
                continue
            if info["node_id"] != self.node_id:
                continue  # la respuesta es para otro nodo que también descubría
            return info
        return None

    def _aplicar_srvinfo(self, info: dict) -> bool:
        """
        Adopta la dirección del servidor informada por SRVINFO.

        :return: True si cambió algo (el log debe avisarlo).
        """
        cambiado = (
            info["server_ip"] != self.server_host
            or info["udp_port"] != self.server_udp_port
        )
        self.server_host = info["server_ip"]
        self.server_udp_port = info["udp_port"]
        return cambiado

    def descubrir_servidor(self, max_intentos=None, espera: float = 2.0) -> bool:
        """
        Busca el Servidor Central por broadcast hasta que responda SRVINFO.

        :param max_intentos: Tope de intentos (None = reintenta indefinidamente
                             mientras el agente esté corriendo, así el nodo se
                             suma solo cuando el servidor se levante).
        :param espera: Segundos de escucha pasiva por intento.
        :return: True si se descubrió el servidor.
        """
        intento = 0
        while self.is_running:
            self._enviar_srvreq()
            info = self._escuchar_srvinfo(espera)
            if info:
                self._aplicar_srvinfo(info)
                log(
                    f"[DESCUBRIMIENTO] Servidor encontrado: {self.server_host} "
                    f"(UDP {self.server_udp_port})"
                )
                return True

            intento += 1
            if max_intentos is not None and intento >= max_intentos:
                return False

            # Backoff suave: al principio proba seguido, después cada 10 s
            espera_reintento = 5.0 if intento < 10 else 10.0
            if intento == 1 or intento % 10 == 0:
                log(
                    f"[DESCUBRIMIENTO] Sin respuesta del servidor "
                    f"(intento {intento}). Buscando por broadcast..."
                )
            time.sleep(espera_reintento)
        return False

    def _redescubrir_si_hace_falta(self):
        """
        Sondeo periódico del servidor (cada REDISCOVER_INTERVALO segundos).

        Cubre el caso de un servidor que se reinicia con otra IP (DHCP) sin
        reiniciar los agentes: el nodo cambia de destino solo.
        """
        if self.ip_configurada:
            return  # la IP vino de config.ini: el usuario sabe dónde está
        self._enviar_srvreq()
        info = self._escuchar_srvinfo(1.0)
        if info and self._aplicar_srvinfo(info):
            log(
                f"[DESCUBRIMIENTO] El servidor cambió de dirección: "
                f"{self.server_host}:{self.server_udp_port}"
            )

    # -------------------------------------------------------------------------
    # BUCLE PRINCIPAL
    # -------------------------------------------------------------------------

    def start(self):
        """Inicia el canal de comandos TCP y el bucle de telemetría UDP periódica."""
        self.is_running = True

        # Socket UDP primero: hace falta tanto para descubrir como para reportar.
        # SO_BROADCAST es obligatorio: sin él Windows rechaza el 255.255.255.255.
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # 1. Ubicar al Servidor Central (salta si config.ini trae la IP)
        if self.server_host:
            log(f"[DESCUBRIMIENTO] IP del servidor tomada de configuración: {self.server_host}")
        else:
            log("[DESCUBRIMIENTO] Sin IP configurada: buscando el Servidor Central por broadcast...")
            if not self.descubrir_servidor():
                log("[DESCUBRIMIENTO] Se interrumpió la búsqueda del servidor.", forzar_archivo=True)
                self.stop()
                return

        # IP de la interfaz que realmente llega al servidor (o 127.0.0.1)
        local_ip = self._detectar_ip_local()

        log("=================================================================")
        log(f" INICIANDO AGENTE DE MONITOREO - ID: '{self.node_id}'")
        log("=================================================================")
        log(f"Destino del Servidor UDP: {self.server_host}:{self.server_udp_port}")
        log(f"IP local de este equipo: {local_ip}")
        log(f"Frecuencia de envío: Cada {self.interval} segundos")
        log(f"Uso de métricas reales (psutil): {'SÍ' if HAS_PSUTIL else 'NO (Simuladas)'}")
        log("-----------------------------------------------------------------")

        # Abrir el canal TCP que recibe las órdenes EXEC del servidor
        self._iniciar_canal_comandos()

        proxima_redescubricion = time.time() + REDISCOVER_INTERVALO

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

                # En modo silencioso no se registra cada ciclo (serían ~28.000
                # líneas por día en agente.log): solo estados y comandos.
                if self._en_consola():
                    print(f"[UDP Sent] Telemetría enviada -> CPU: {cpu}% | RAM: {ram}% | Disco: {disk}% | Estado: {status}", flush=True)

                # 4. Sondeo de cambios de dirección del servidor
                if time.time() >= proxima_redescubricion:
                    self._redescubrir_si_hace_falta()
                    local_ip = self._detectar_ip_local()
                    proxima_redescubricion = time.time() + REDISCOVER_INTERVALO

                # Esperar el intervalo configurado
                time.sleep(self.interval)

        except KeyboardInterrupt:
            log(f"\n[AGENTE '{self.node_id}'] Deteniendo la transmisión de telemetría...")
        except Exception as e:
            log(f"[AGENTE - Error] Ocurrió una falla en la transmisión UDP: {e}", forzar_archivo=True)
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
        log(f"[AGENTE '{self.node_id}'] Sockets liberados y agente detenido.", forzar_archivo=True)


def leer_config(ruta: str = RUTA_CONFIG) -> dict:
    """
    Lee `agent/config.ini` (opcional): permite instalar el agente sin argumentos.

    Ejemplo de archivo:

        [nodo]
        id_nodo = LAPTOP-JUAN
        [red]
        ip_servidor =
        puerto_udp = 5000
        puerto_cmd = 5002
        intervalo = 3

    `ip_servidor` vacía = descubrir el servidor por broadcast.

    :return: Dict con las claves id_nodo, ip_servidor, puerto_udp, puerto_cmd, intervalo.
    """
    valores = {
        "id_nodo": None,
        "ip_servidor": None,
        "puerto_udp": DEFAULT_UDP_PORT,
        "puerto_cmd": DEFAULT_AGENT_TCP_PORT,
        "intervalo": 3.0,
    }
    if not os.path.isfile(ruta):
        return valores

    parser = configparser.ConfigParser()
    try:
        parser.read(ruta, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as e:
        log(f"[CONFIG] No se pudo leer '{ruta}': {e} (se usan valores por defecto)", forzar_archivo=True)
        return valores

    if parser.has_section("nodo"):
        id_nodo = parser.get("nodo", "id_nodo", fallback="").strip()
        if id_nodo:
            valores["id_nodo"] = id_nodo

    if parser.has_section("red"):
        ip = parser.get("red", "ip_servidor", fallback="").strip()
        if ip and ip not in ("0.0.0.0", "-"):
            valores["ip_servidor"] = ip
        try:
            valores["puerto_udp"] = parser.getint("red", "puerto_udp", fallback=DEFAULT_UDP_PORT)
        except ValueError:
            pass
        try:
            valores["puerto_cmd"] = parser.getint("red", "puerto_cmd", fallback=DEFAULT_AGENT_TCP_PORT)
        except ValueError:
            pass
        try:
            valores["intervalo"] = parser.getfloat("red", "intervalo", fallback=3.0)
        except ValueError:
            pass
    return valores


def main():
    """
    Punto de entrada del agente.

    Soporta DOS formas de uso (la vieja sigue funcionando igual):

      1. Con argumentos posicionales (scripts/antiguos):
             python agent/agent.py NODO_01 192.168.1.50 5000 5002
      2. Sin argumentos (instalación automática):
             python agent/agent.py --silent
         Lee agent/config.ini y, si no hay IP, descubre el servidor por broadcast.
    """
    global MODO_SILENCIO

    # pythonw.exe no tiene consola: redirigir antes de cualquier print()
    _asegurar_salida()

    parser = argparse.ArgumentParser(
        description="Agente de monitoreo SDMR (telemetría UDP + canal de comandos EXEC)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python agent/agent.py NODO_01 192.168.1.50        (forma clásica)\n"
            "  python agent/agent.py                             (lee config.ini y descubre)\n"
            "  python agent/agent.py --silent                    (sin consola: log en agente.log)\n"
        ),
    )
    parser.add_argument("posicionales", nargs="*", metavar="ARG",
                        help="[id_nodo] [ip_servidor] [puerto_udp] [puerto_cmd] (forma clásica)")
    parser.add_argument("--silent", action="store_true",
                        help="No abre consola: todo va a agent/agente.log (para arranque oculto)")
    parser.add_argument("--config", default=RUTA_CONFIG, metavar="ARCHIVO",
                        help=f"Archivo de configuración (por defecto: {RUTA_CONFIG})")
    parser.add_argument("--id", dest="id_nodo", default=None, help="ID del nodo (por defecto: hostname)")
    parser.add_argument("--ip", dest="ip_servidor", default=None,
                        help="IP del servidor; si se omite se descubre por broadcast")
    parser.add_argument("--udp", type=int, default=None, help="Puerto UDP del servidor (5000)")
    parser.add_argument("--cmd", type=int, default=None, help="Puerto TCP local de comandos EXEC (5002)")
    parser.add_argument("--intervalo", type=float, default=None, help="Segundos entre telemetrías (3)")
    args = parser.parse_args()

    MODO_SILENCIO = args.silent

    config = leer_config(args.config)

    # Precedencia: argumentos de línea de comandos > config.ini > posición clásica > defecto
    posicionales = args.posicionales
    id_nodo = args.id_nodo or config["id_nodo"] or (posicionales[0] if len(posicionales) > 0 else None)
    ip_servidor = args.ip_servidor or config["ip_servidor"] or (posicionales[1] if len(posicionales) > 1 else None)

    try:
        puerto_udp = args.udp or (int(posicionales[2]) if len(posicionales) > 2 else config["puerto_udp"])
    except ValueError:
        puerto_udp = config["puerto_udp"]
    try:
        puerto_cmd = args.cmd or (int(posicionales[3]) if len(posicionales) > 3 else config["puerto_cmd"])
    except ValueError:
        puerto_cmd = config["puerto_cmd"]

    intervalo = args.intervalo if args.intervalo is not None else config["intervalo"]

    agente = SystemNodeAgent(
        node_id=id_nodo,
        server_host=ip_servidor,
        server_udp_port=puerto_udp,
        interval=intervalo,
        cmd_port=puerto_cmd,
    )
    agente.start()


if __name__ == "__main__":
    main()
