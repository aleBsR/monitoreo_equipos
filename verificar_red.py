"""
===============================================================================
Verificador de conectividad SDMR para la prueba en red local (2+ equipos)
===============================================================================
Diagnostica, desde ESTE equipo, si el Servidor Central SDMR es alcanzable sobre
la red. Sirve para descartar los dos culpables habituales de la demo fallida:
la IP equivocada y el firewall cerrado.

Qué comprueba:
  1. IP local de salida: la que deben usar los demás equipos para llegar acá.
  2. Camino TCP (puerto 5001): hace el saludo de 3 vías y envía 'CMD|PING',
     esperando 'RES|OK|PONG|...'. Verifica que el servidor está vivo y que el
     puerto no está bloqueado.
  3. Camino UDP (puerto 5000): envía un datagrama de telemetría de prueba
     ('MON|PRUEBA_xxx|...') y luego consulta GET_NODES por TCP para confirmar
     que el servidor lo registró. El servidor NO responde por UDP (por
     diseño), así que esta es la forma de validar el camino completo.

Nota: el nodo de prueba queda registrado en el servidor. El watchdog lo marca
OFFLINE a los ~15 s y lo purga del registro a los ~120 s.

Uso:
    python3 verificar_red.py <IP_SERVIDOR> [PUERTO_UDP] [PUERTO_TCP]

Ejemplo:
    python3 verificar_red.py 192.168.1.50
    python3 verificar_red.py 192.168.1.50 5000 5001
===============================================================================
"""

import os
import socket
import sys
import time
import uuid

# Permitir importar el protocolo común cuando se ejecuta desde la raíz
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from common.protocol import (
    DEFAULT_UDP_PORT,
    DEFAULT_TCP_PORT,
    BUFFER_SIZE,
    encode_message,
    build_tcp_command,
    build_udp_telemetry,
    parse_tcp_response,
    TcpFrameReader,
)


def detectar_ip_local(destino: str, puerto: int) -> str:
    """
    Devuelve la IP de la interfaz de este equipo que se usa para llegar al
    destino, sin enviar un solo byte (connect() sobre un socket UDP solo fija
    la interfaz de salida). Es la IP que hay que compartir con los demás.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((destino, puerto))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _leer_trama(sock: socket.socket, reader: TcpFrameReader) -> str:
    """Acumula bytes TCP hasta completar UNA trama del protocolo ('\\n')."""
    while not reader.hay_tramas():
        datos = sock.recv(BUFFER_SIZE)
        if not datos:
            raise ConnectionError("El servidor cerró la conexión sin responder.")
        reader.feed(datos)
    return reader.siguiente_trama()


def probar_tcp(host: str, puerto: int, timeout: float = 5.0) -> tuple:
    """
    Realiza el handshake TCP y un PING lógico.

    :return: Tupla (ok: bool, detalle: str).
    """
    try:
        sock = socket.create_connection((host, puerto), timeout=timeout)
    except socket.timeout:
        return False, f"Timeout al conectar a {host}:{puerto}. El firewall puede estar bloqueando el puerto o la IP es incorrecta."
    except ConnectionRefusedError:
        return False, f"Conexión rechazada en {host}:{puerto}. El servidor no está corriendo (o el puerto no es el correcto)."
    except OSError as e:
        return False, f"No se pudo conectar a {host}:{puerto}: {e}"

    try:
        reader = TcpFrameReader()
        sock.sendall(encode_message(build_tcp_command("PING")))
        respuesta = parse_tcp_response(_leer_trama(sock, reader))
        if respuesta["status"] == "OK" and respuesta["payload_or_code"] == "PONG":
            return True, f"Servidor vivo (RES|OK|PONG en {host}:{puerto})."
        return False, f"El servidor respondió algo inesperado: {respuesta}"
    except (OSError, ValueError, ConnectionError) as e:
        return False, f"Error durante el PING TCP: {e}"
    finally:
        sock.close()


def autenticar(sock: socket.socket, reader: TcpFrameReader, usuario: str, password: str) -> bool:
    """Envía CMD|AUTH y devuelve True si el servidor concede la sesión."""
    sock.sendall(encode_message(build_tcp_command("AUTH", usuario, password)))
    respuesta = parse_tcp_response(_leer_trama(sock, reader))
    return respuesta["status"] == "OK"


def probar_udp(host: str, puerto: int, puerto_tcp: int, ip_local: str, timeout: float = 5.0) -> tuple:
    """
    Envía un datagrama de telemetría de prueba y verifica por TCP (GET_NODES)
    que el servidor lo haya registrado.

    :return: Tupla (ok: bool, detalle: str).
    """
    node_id = f"PRUEBA_{uuid.uuid4().hex[:6]}"

    # 1. Enviar el datagrama UDP de prueba (sin canal EXEC: cmd_port=None)
    try:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        trama = build_udp_telemetry(node_id, ip_local, 0.0, 0.0, 0.0, "OK")
        udp.sendto(encode_message(trama), (host, puerto))
        udp.close()
    except OSError as e:
        return False, f"No se pudo enviar el datagrama UDP a {host}:{puerto}: {e}"

    # 2. Esperar a que el hilo UDP del servidor procese el paquete
    time.sleep(1.0)

    # 3. Confirmar por TCP que el nodo quedó registrado
    try:
        sock = socket.create_connection((host, puerto_tcp), timeout=timeout)
    except OSError as e:
        return False, f"El datagrama UDP se envió pero no se pudo confirmar por TCP: {e}"

    try:
        reader = TcpFrameReader()
        if not autenticar(sock, reader, "admin", "admin123"):
            return False, "El servidor no aceptó la autenticación de verificación."

        sock.sendall(encode_message(build_tcp_command("GET_NODES", "ALL")))
        respuesta = parse_tcp_response(_leer_trama(sock, reader))

        if respuesta["status"] != "OK":
            return False, f"GET_NODES falló: {respuesta['payload_or_code']}"

        if node_id in respuesta["payload_or_code"]:
            return True, f"El nodo de prueba '{node_id}' llegó por UDP y quedó registrado."
        return False, (
            f"El datagrama UDP no apareció en el registro del servidor. "
            f"Posible bloqueo del puerto UDP {puerto} por firewall o ruta incorrecta."
        )
    except (OSError, ValueError, ConnectionError) as e:
        return False, f"Error al confirmar la telemetría por TCP: {e}"
    finally:
        sock.close()


def sugerencias_firewall(host: str, puerto_udp: int, puerto_tcp: int):
    """Imprime recordatorios de apertura de puertos para el servidor."""
    print("\n  Recordá abrir en el EQUIPO SERVIDOR:")
    print(f"    Linux:   sudo ufw allow {puerto_udp}/udp && sudo ufw allow {puerto_tcp}/tcp")
    print("             sudo ufw allow 5002/tcp   (canal EXEC del agente)")
    print(f"    Windows: netsh advfirewall firewall add rule name=\"SDMR UDP\" dir=in action=allow protocol=UDP localport={puerto_udp}")
    print(f"             netsh advfirewall firewall add rule name=\"SDMR TCP\" dir=in action=allow protocol=TCP localport={puerto_tcp}")


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 verificar_red.py <IP_SERVIDOR> [PUERTO_UDP] [PUERTO_TCP]")
        print("Ejemplo: python3 verificar_red.py 192.168.1.50")
        sys.exit(2)

    host = sys.argv[1]
    puerto_udp = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_UDP_PORT
    puerto_tcp = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_TCP_PORT

    print("=================================================================")
    print(" VERIFICACIÓN DE RED SDMR")
    print("=================================================================")
    print(f" Servidor objetivo : {host}")
    print(f" Puerto UDP        : {puerto_udp}")
    print(f" Puerto TCP        : {puerto_tcp}")

    ip_local = detectar_ip_local(host, puerto_udp)
    print(f" IP local de salida: {ip_local}")
    print(" (esa es la IP que ven los demás equipos de este equipo)")
    print("-----------------------------------------------------------------")

    # 1. Camino TCP
    print("[1/2] Probando TCP (comandos) ...")
    ok_tcp, detalle_tcp = probar_tcp(host, puerto_tcp)
    print(f"      {'OK  ' if ok_tcp else 'FALLA'}: {detalle_tcp}")

    # 2. Camino UDP (solo tiene sentido si el TCP llegó, para poder confirmar)
    ok_udp = False
    detalle_udp = "Omitido: primero hay que resolver el camino TCP."
    if ok_tcp:
        print("[2/2] Probando UDP (telemetría) ...")
        ok_udp, detalle_udp = probar_udp(host, puerto_udp, puerto_tcp, ip_local)
        print(f"      {'OK  ' if ok_udp else 'FALLA'}: {detalle_udp}")

    print("-----------------------------------------------------------------")
    if ok_tcp and ok_udp:
        print(" RESULTADO: Todo listo. Este equipo puede monitorear al servidor")
        print(f"            {host} y enviarle telemetría.")
        print("=================================================================")
        sys.exit(0)

    print(" RESULTADO: Hay conexiones que fallan. Revisá:")
    print("   - Que server/server.py esté corriendo en el equipo destino.")
    print(f"   - Que la IP '{host}' sea la del servidor en la red local.")
    print("   - Que ambos equipos estén en la misma red y se hagan ping.")
    sugerencias_firewall(host, puerto_udp, puerto_tcp)
    print("=================================================================")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Verificación cancelada por el usuario]")
        sys.exit(130)
