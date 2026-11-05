"""
===============================================================================
Descubrimiento de hosts en la LAN (módulo EXTRA, opcional)
===============================================================================
Este módulo es INDEPENDIENTE del núcleo SDMR (server/agent/common). No se
importa desde el servidor ni el agente, para no violar la restricción académica
de usar sockets nativos en el core. Solo lo consumen herramientas extra y la
pestaña "Red (extra)" del dashboard.

Estrategia:
  1. Si Scapy está instalado y se pide `usar_scapy=True`, hace un ARP scan
     real sobre la subred (requiere Npcap + privilegios de admin en Windows).
  2. Si Scapy no está disponible o falla, cae a un fallback basado en
     `arp -a` del sistema operativo (sin dependencias extra).

No lista archivos compartidos (eso es SMB): ver list_smb_shares.py si se
necesita (no implementado aún).
===============================================================================
"""

import platform
import re
import socket
import subprocess
import threading


def _scapy_disponible() -> bool:
    try:
        import scapy.all  # noqa: F401
        return True
    except ImportError:
        return False


def detectar_subred() -> str:
    """Detecta la IP local y asume una subred /24."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    partes = ip.split(".")
    if len(partes) == 4:
        return f"{partes[0]}.{partes[1]}.{partes[2]}.0/24"
    return "192.168.1.0/24"


def _hostname_de(ip: str) -> str:
    """Resuelve hostname con timeout para no bloquear el escaneo."""
    resultado = {"h": ""}

    def worker():
        try:
            resultado["h"] = socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror, OSError):
            resultado["h"] = ""

    hilo = threading.Thread(target=worker, daemon=True)
    hilo.start()
    hilo.join(timeout=0.5)
    return resultado["h"]


def arp_scan_scapy(subred: str):
    """ARP scan real con Scapy. Lanza excepción si falla."""
    from scapy.all import ARP, Ether, srp

    ans, _ = srp(
        Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subred),
        timeout=2,
        verbose=0,
    )
    resultados = []
    for _, rcv in ans:
        resultados.append({
            "ip": rcv.psrc,
            "mac": rcv.hwsrc,
            "hostname": _hostname_de(rcv.psrc),
        })
    return resultados


def arp_scan_fallback():
    """Parsea `arp -a` del SO (sin dependencias)."""
    sistema = platform.system().lower()
    cmd = ["arp", "-a"]
    try:
        salida = subprocess.check_output(
            cmd, text=True, stderr=subprocess.DEVNULL, timeout=10
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []

    patron = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]{11,17})")
    resultados = []
    vistos = set()
    for m in patron.finditer(salida):
        ip = m.group(1)
        if ip in vistos:
            continue
        if ip.endswith(".255") or ip == "255.255.255.255":
            continue
        vistos.add(ip)
        mac = m.group(2).replace("-", ":").lower()
        resultados.append({
            "ip": ip,
            "mac": mac,
            "hostname": _hostname_de(ip),
        })
    return resultados


def escanear_lan(subred: str = None, usar_scapy: bool = True):
    """
    Descubre hosts en la LAN.

    :return: Tupla (lista_de_hosts, metodo_usado).
    """
    if subred is None:
        subred = detectar_subred()

    if usar_scapy and _scapy_disponible():
        try:
            return arp_scan_scapy(subred), "scapy (ARP scan)"
        except Exception as e:  # noqa: BLE001
            fallback = arp_scan_fallback()
            return fallback, f"fallback (scapy falló: {e})"

    return arp_scan_fallback(), "fallback (arp -a)"


def scapy_instalado() -> bool:
    return _scapy_disponible()