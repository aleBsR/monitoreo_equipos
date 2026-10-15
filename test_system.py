"""
===============================================================================
Pruebas de Integración Automatizadas para SDMR (NETMON/1.0)
===============================================================================
Script NO interactivo que levanta el Servidor Central y varios Agentes como
procesos hijo, y verifica las pruebas pedidas en la consigna del TPI:

  Prueba 1  - Cliente único (PING / AUTH / GET_NODES)
  Prueba 2  - Múltiples clientes simultáneos (3 clientes TCP)
  Prueba 3  - Desconexión (abrupta y a mitad de operación)
  Prueba 4  - Datos inválidos y tramas malformadas (RF07)
  Prueba 5  - Servidor no disponible
  Prueba 6  - Encuadrado de tramas TCP (trama partida y dos tramas juntas)
  Prueba 7  - Watchdog: nodo OFFLINE al dejar de enviar telemetría UDP
  Prueba 8  - Concurrencia: un cliente opera mientras otros son atendidos

Los puertos se eligen libres automáticamente para no chocar con un servidor
que ya esté corriendo en la máquina.
===============================================================================
"""

import os
import socket
import struct
import subprocess
import sys
import threading
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from client.admin_client import AdminClient

RAIZ = os.path.dirname(os.path.abspath(__file__))
RUTA_SERVIDOR = os.path.join(RAIZ, "server", "server.py")
RUTA_AGENTE = os.path.join(RAIZ, "agent", "agent.py")

# Acumulador de resultados de las pruebas
RESULTADOS = []


# =============================================================================
# UTILIDADES
# =============================================================================

def _puertos_libres() -> tuple:
    """Pide al SO un puerto UDP y uno TCP libres para no pisar procesos ajenos."""
    s_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_tcp.bind(("127.0.0.1", 0))
    tcp = s_tcp.getsockname()[1]
    s_tcp.close()

    s_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_udp.bind(("127.0.0.1", 0))
    udp = s_udp.getsockname()[1]
    s_udp.close()

    return udp, tcp


def _n_puertos_tcp_libres(n: int) -> list:
    """Reserva n puertos TCP distintos (para el canal de comandos de cada agente)."""
    sockets = []
    puertos = []
    for _ in range(n):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        puertos.append(s.getsockname()[1])
        sockets.append(s)
    for s in sockets:
        s.close()
    return puertos


def _esperar_servidor(tcp_port: int, timeout: float = 10.0) -> bool:
    """Espera a que el servidor acepte conexiones TCP."""
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            s = socket.create_connection(("127.0.0.1", tcp_port), timeout=0.5)
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def _esperar_nodos(tcp_port: int, cantidad: int, timeout: float = 15.0) -> int:
    """Espera hasta que el servidor registre al menos `cantidad` nodos."""
    limite = time.time() + timeout
    cantidad_actual = 0
    while time.time() < limite:
        cli = AdminClient("127.0.0.1", tcp_port)
        if cli.connect():
            cli.send_command("AUTH", "admin", "admin123")
            cli.is_authenticated = True
            resp = cli.send_command("GET_NODES", "ALL")
            payload = resp["payload_or_code"]
            if payload.startswith("NODES_COUNT:"):
                cantidad_actual = int(payload.split(";")[0].split(":")[1])
            cli.close()
            if cantidad_actual >= cantidad:
                return cantidad_actual
        time.sleep(0.5)
    return cantidad_actual


def check(nombre: str, condicion: bool, detalle: str = ""):
    """Registra y muestra el resultado de una verificación."""
    estado = "OK  " if condicion else "FALLA"
    RESULTADOS.append((nombre, condicion))
    sufijo = f" | {detalle}" if detalle else ""
    print(f"  [{estado}] {nombre}{sufijo}")


def _cliente_autenticado(tcp_port: int) -> AdminClient:
    cli = AdminClient("127.0.0.1", tcp_port)
    assert cli.connect(), "No se pudo conectar un cliente de prueba"
    resp = cli.send_command("AUTH", "admin", "admin123")
    assert resp["status"] == "OK", "AUTH falló"
    cli.is_authenticated = True
    return cli


# =============================================================================
# PRUEBAS
# =============================================================================

def prueba_1_cliente_unico(tcp_port: int):
    print("\n[Prueba 1] Cliente único (PING / AUTH / GET_NODES)")
    cli = AdminClient("127.0.0.1", tcp_port)
    check("Conexión TCP del cliente", cli.connect())

    resp = cli.send_command("PING")
    check("PING -> PONG", resp["status"] == "OK" and resp["payload_or_code"] == "PONG")

    resp = cli.send_command("AUTH", "admin", "admin123")
    check("AUTH correcto", resp["status"] == "OK")
    cli.is_authenticated = True

    resp = cli.send_command("GET_NODES", "ALL")
    check("GET_NODES devuelve nodos", resp["status"] == "OK" and resp["payload_or_code"].startswith("NODES_COUNT:"))
    cli.close()


def prueba_2_multiples_clientes(tcp_port: int, cantidad: int = 3):
    print(f"\n[Prueba 2] Múltiples clientes simultáneos ({cantidad} clientes TCP)")
    resultados = []
    hilos = []

    def sesion(indice):
        try:
            cli = _cliente_autenticado(tcp_port)
            resp = cli.send_command("GET_NODES", "ALL")
            resultados.append((indice, resp["status"] == "OK"))
            cli.close()
        except Exception as e:  # noqa: BLE001
            resultados.append((indice, False))
            print(f"    Cliente {indice} error: {e}")

    for i in range(1, cantidad + 1):
        h = threading.Thread(target=sesion, args=(i,))
        h.start()
        hilos.append(h)

    for h in hilos:
        h.join(timeout=10)

    check(
        f"{cantidad} clientes atendidos en simultáneo",
        len(resultados) == cantidad and all(ok for _, ok in resultados),
        f"{sum(1 for _, ok in resultados if ok)}/{cantidad} OK",
    )


def prueba_3_desconexion(tcp_port: int):
    print("\n[Prueba 3] Desconexión abrupta y a mitad de operación")

    # Desconexión con RST (SO_LINGER 0) mientras el servidor espera datos
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", tcp_port))
    s.sendall(b"CMD|PI")  # operación incompleta
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()
    time.sleep(0.5)

    # El servidor debe seguir atendiendo
    cli = _cliente_autenticado(tcp_port)
    resp = cli.send_command("PING")
    check("Servidor sobrevive a desconexión abrupta", resp["status"] == "OK" and resp["payload_or_code"] == "PONG")
    cli.close()


def prueba_4_datos_invalidos(tcp_port: int):
    print("\n[Prueba 4] Datos inválidos y malformados (RF07)")
    cli = _cliente_autenticado(tcp_port)

    # Pruebas no interactivas del cliente admin
    r1 = cli.send_malformed_test(sub_opt="1")
    check("Sin cabecera CMD -> ERR_100", "ERR_100" in r1, r1.strip())

    r2 = cli.send_malformed_test(sub_opt="2")
    check("Acción desconocida -> ERR_103", "ERR_103" in r2, r2.strip())

    r3 = cli.send_malformed_test(sub_opt="3")
    check("AUTH sin parámetros -> ERR_100", "ERR_100" in r3, r3.strip())

    # Acceso no autorizado: GET_NODES sin autenticarse
    cli2 = AdminClient("127.0.0.1", tcp_port)
    cli2.connect()
    r4 = cli2.send_command("GET_NODES", "ALL")
    check("GET_NODES sin autenticar -> ERR_101", r4["payload_or_code"] == "ERR_101")
    cli2.close()

    # El servidor sigue vivo luego de todos los malformados
    resp = cli.send_command("PING")
    check("Servidor sigue operativo tras errores", resp["payload_or_code"] == "PONG")
    cli.close()


def prueba_5_servidor_no_disponible():
    print("\n[Prueba 5] Servidor no disponible")
    tcp_libre, _ = _puertos_libres()
    cli = AdminClient("127.0.0.1", tcp_libre)
    conectado = cli.connect()
    check("Conexión rechazada con servidor caído", conectado is False)
    cli.close()


def prueba_6_encuadrado_tcp(tcp_port: int):
    print("\n[Prueba 6] Encuadrado de tramas TCP (framing)")
    cli = _cliente_autenticado(tcp_port)

    # 6.a Dos comandos en un MISMO segmento TCP -> dos respuestas
    cli.tcp_socket.sendall(b"CMD|PING\nCMD|PING\n")
    r1 = cli._esperar_trama()
    r2 = cli._esperar_trama()
    check(
        "Dos tramas en un solo segmento -> 2 respuestas",
        r1 == "RES|OK|PONG|Servidor activo y escuchando" and r2 == r1,
        f"'{r1}' + '{r2}'",
    )

    # 6.b Una trama PARTIDA en dos segmentos -> una respuesta correcta
    cli.tcp_socket.sendall(b"CMD|PI")
    time.sleep(0.3)
    cli.tcp_socket.sendall(b"NG\n")
    r3 = cli._esperar_trama()
    check("Trama partida en dos segmentos -> 1 respuesta", r3 == "RES|OK|PONG|Servidor activo y escuchando", r3)

    cli.close()


def prueba_exec(tcp_port: int):
    print("\n[Prueba EXEC] Ejecución remota real en el agente (TCP)")
    cli = _cliente_autenticado(tcp_port)

    # Comando permitido -> el agente lo ejecuta y confirma
    resp = cli.send_command("EXEC", "NODO_01", "RESTART_SERVICE")
    check(
        "EXEC comando permitido -> EXEC_SUCCESS",
        resp["status"] == "OK" and resp["payload_or_code"] == "EXEC_SUCCESS",
        resp["detail"],
    )

    # Comando no permitido -> el agente lo rechaza con ERR_104
    resp = cli.send_command("EXEC", "NODO_01", "FORMATEAR_DISCO")
    check(
        "EXEC comando no permitido -> ERR_104",
        resp["status"] == "ERR" and resp["payload_or_code"] == "ERR_104",
        resp["detail"],
    )

    # Nodo inexistente -> ERR_102
    resp = cli.send_command("EXEC", "NODO_99", "RESTART_SERVICE")
    check("EXEC nodo inexistente -> ERR_102", resp["payload_or_code"] == "ERR_102", resp["detail"])

    cli.close()


def prueba_7_watchdog(udp_port: int, tcp_port: int, agentes: list):
    print("\n[Prueba 7] Watchdog: nodo OFFLINE al dejar de enviar telemetría")
    if not agentes:
        check("Watchdog OFFLINE", False, "no hay agentes para detener")
        return

    victima = agentes.pop()  # se toma el último agente
    victima.terminate()
    victima.wait(timeout=5)

    # El watchdog corre cada 5 s con timeout de 15 s: esperar con margen
    limite = time.time() + 25
    estado = ""
    while time.time() < limite:
        cli = _cliente_autenticado(tcp_port)
        payload = cli.send_command("GET_NODES", "ALL")["payload_or_code"]
        cli.close()
        if "OFFLINE" in payload:
            estado = payload
            break
        time.sleep(2)

    check("Nodo marcado OFFLINE por inactividad", "OFFLINE" in estado, estado[:80])


def prueba_8_concurrencia(tcp_port: int):
    print("\n[Prueba 8] Concurrencia: un cliente opera mientras otros son atendidos")
    errores = []

    def carga(indice):
        try:
            cli = _cliente_autenticado(tcp_port)
            for _ in range(10):
                resp = cli.send_command("PING")
                if resp["payload_or_code"] != "PONG":
                    errores.append(f"cliente {indice} recibió {resp}")
            cli.close()
        except Exception as e:  # noqa: BLE001
            errores.append(f"cliente {indice}: {e}")

    hilos = [threading.Thread(target=carga, args=(i,)) for i in range(1, 4)]
    inicio = time.time()
    for h in hilos:
        h.start()
    # Mientras los 3 clientes hacen PING en paralelo, un cliente más consulta nodos
    cli = _cliente_autenticado(tcp_port)
    resp = cli.send_command("GET_NODES", "ALL")
    cli.close()
    for h in hilos:
        h.join(timeout=15)
    duracion = time.time() - inicio

    check("Operación concurrente sin interferencias", not errores and resp["status"] == "OK", f"{duracion:.2f}s, errores={errores or 'ninguno'}")


# =============================================================================
# ORQUESTACIÓN
# =============================================================================

def run_integration_test() -> int:
    print("=================================================================")
    print(" PRUEBAS DE INTEGRACIÓN AUTOMATIZADAS (SDMR / NETMON 1.0)")
    print("=================================================================")

    udp_port, tcp_port = _puertos_libres()
    print(f"Puertos de prueba: UDP {udp_port} | TCP {tcp_port}")

    print("[SETUP] Iniciando Servidor Central...")
    servidor = subprocess.Popen(
        [sys.executable, "-u", RUTA_SERVIDOR, str(udp_port), str(tcp_port), "60"],
        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )

    agentes = []
    try:
        if not _esperar_servidor(tcp_port):
            check("Arranque del servidor", False, "el servidor no aceptó conexiones")
            return 1
        check("Arranque del servidor", True, f"{udp_port}/{tcp_port}")

        print("[SETUP] Lanzando 3 Agentes (NODO_01..NODO_03) con su canal de comandos...")
        cmd_ports = _n_puertos_tcp_libres(3)
        for i in range(1, 4):
            p = subprocess.Popen(
                [sys.executable, "-u", RUTA_AGENTE, f"NODO_0{i}", "127.0.0.1", str(udp_port), str(cmd_ports[i - 1])],
                cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
            agentes.append(p)

        registrados = _esperar_nodos(tcp_port, 3)
        check("3 agentes registrados por UDP", registrados >= 3, f"{registrados} nodos")

        prueba_1_cliente_unico(tcp_port)
        prueba_2_multiples_clientes(tcp_port)
        prueba_3_desconexion(tcp_port)
        prueba_4_datos_invalidos(tcp_port)
        prueba_5_servidor_no_disponible()
        prueba_6_encuadrado_tcp(tcp_port)
        prueba_8_concurrencia(tcp_port)
        prueba_exec(tcp_port)
        prueba_7_watchdog(udp_port, tcp_port, agentes)

    finally:
        print("\n[TEARDOWN] Cerrando agentes y servidor...")
        for a in list(agentes):
            if a.poll() is None:
                a.terminate()
        if servidor.poll() is None:
            servidor.terminate()
        for p in list(agentes) + [servidor]:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Procesos finalizados.")

    total = len(RESULTADOS)
    exitos = sum(1 for _, ok in RESULTADOS if ok)
    print("\n=================================================================")
    print(f" RESULTADO: {exitos}/{total} verificaciones exitosas")
    print("=================================================================")
    if exitos == total:
        print("✅ TODAS LAS PRUEBAS DE INTEGRACIÓN PASARON EXITOSAMENTE")
        return 0
    print("❌ HAY PRUEBAS FALLIDAS (ver detalle arriba)")
    return 1


if __name__ == "__main__":
    sys.exit(run_integration_test())
