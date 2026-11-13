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

Por cada host devuelve:
  - ip        : dirección IPv4 (del ARP / cache).
  - mac       : dirección física.
  - vendor    : fabricante deducido del OUI (primeros 3 bytes de la MAC). Es un
                dato "gratis": NO genera tráfico, es una consulta a la base de
                datos de OUI que ya trae Scapy. Si la MAC es aleatoria (bit de
                administración local encendido, típico de celulares por
                privacidad) se informa como tal en vez de inventar un fabricante.
  - hostname  : nombre resuelto por DNS inverso (no viene del ARP).
  - alive     : True si respondió al ping ICMP.
  - latency_ms: latencia del ping en milisegundos (None si no respondió).

IMPORTANTE (por qué NO hay CPU/RAM/Disco acá): esas son métricas INTERNAS del
sistema operativo de cada equipo; no se pueden observar desde la red sin que un
proceso corra EN el equipo y las publique (ese es el trabajo del agente SDMR por
NETMON/1.0). El descubrimiento de red solo puede ver lo que el equipo expone
hacia afuera: su presencia (ARP), su MAC/fabricante y si responde (ping).

No lista archivos compartidos (eso es SMB): ver list_smb_shares.py si se
necesita (no implementado aún).
===============================================================================
"""

import platform
import re
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

# Cache de fabricantes por MAC: la consulta OUI es determinística, así que
# no tiene sentido repetirla entre escaneos sucesivos.
_VENDOR_CACHE = {}


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


def _mac_es_aleatoria(mac: str) -> bool:
    """
    True si la MAC es "localmente administrada" (bit U/L del primer octeto).

    Los celulares modernos rotan MACs aleatorias por privacidad; en ese caso
    buscar el fabricante en la base de OUI no tiene sentido (no corresponde a
    ningún vendor real), así que conviene avisarlo en vez de mostrar basura.
    """
    try:
        primer_octeto = int(mac.split(":")[0], 16)
    except (ValueError, IndexError, AttributeError):
        return False
    # bit 1 (0b10) del primer octeto = administración local
    return bool(primer_octeto & 0b10)


def _vendor_de(mac: str) -> str:
    """
    Fabricante del equipo a partir del OUI (primeros 3 bytes de la MAC).

    No manda ningún paquete: usa la base de datos de OUI que Scapy ya trae
    cargada (la misma de Wireshark). La API de Scapy cambió entre versiones,
    por eso se prueba de forma defensiva y, si no se puede resolver, se devuelve
    cadena vacía (o el aviso de MAC aleatoria) en vez de arriesgar un dato falso.
    """
    if not mac:
        return ""
    mac = mac.lower()
    if mac in _VENDOR_CACHE:
        return _VENDOR_CACHE[mac]

    vendor = ""
    try:
        from scapy.all import conf
        db = getattr(conf, "manufdb", None)
        if db is not None:
            for metodo in ("_get_manuf", "lookup"):
                fn = getattr(db, metodo, None)
                if fn is None:
                    continue
                try:
                    r = fn(mac)
                except Exception:  # noqa: BLE001
                    continue
                # Algunas versiones devuelven (corto, largo); nos quedamos con
                # la descripción más larga/legible.
                if isinstance(r, (tuple, list)):
                    r = r[-1] if r else ""
                s = str(r).strip() if r else ""
                # Filtramos ecos de la propia MAC: un vendor real tiene letras.
                if s and any(c.isalpha() for c in s) and s.lower() not in mac:
                    vendor = s
                    break
    except Exception:  # noqa: BLE001
        pass

    if not vendor and _mac_es_aleatoria(mac):
        vendor = "MAC aleatoria (privacidad)"

    _VENDOR_CACHE[mac] = vendor
    return vendor


def _ping(ip: str) -> tuple:
    """
    Comprueba si un host responde al ping y mide la latencia.

    Usa el comando `ping` del sistema (no sockets ICMP crudos) para no requerir
    privilegios de administrador. Un único eco con timeout corto.

    :return: Tupla (alcanzable: bool, latencia_ms: float|None).
    """
    es_windows = platform.system().lower().startswith("win")
    if es_windows:
        cmd = ["ping", "-n", "1", "-w", "800", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        salida = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3
        )
    except (subprocess.SubprocessError, OSError):
        return (False, None)

    if salida.returncode != 0:
        return (False, None)

    # "time=12.3 ms", "time<1ms" (Windows EN) o "tiempo=12ms" (Windows ES)
    m = re.search(r"(?:time|tiempo)[=<]\s*([\d.,]+)\s*ms",
                  salida.stdout, re.IGNORECASE)
    latencia = None
    if m:
        try:
            latencia = round(float(m.group(1).replace(",", ".")), 1)
        except ValueError:
            latencia = None
    return (True, latencia)


def _enriquecer(hosts: list) -> list:
    """
    Agrega vendor, hostname, alive y latency_ms a cada host, en paralelo.

    El trabajo pesado (ping + DNS inverso) se hace concurrente con un pool de
    hilos para que el escaneo no se vuelva lineal con la cantidad de equipos.
    """
    if not hosts:
        return hosts

    def tarea(h):
        h["vendor"] = _vendor_de(h.get("mac", ""))
        h["hostname"] = _hostname_de(h["ip"])
        alcanzable, latencia = _ping(h["ip"])
        h["alive"] = alcanzable
        h["latency_ms"] = latencia
        return h

    with ThreadPoolExecutor(max_workers=min(32, len(hosts))) as pool:
        list(pool.map(tarea, hosts))
    # Orden estable por IP (numérico) para que la tabla no "salte" entre escaneos
    try:
        hosts.sort(key=lambda h: tuple(int(p) for p in h["ip"].split(".")))
    except (ValueError, KeyError):
        pass
    return hosts


def arp_scan_scapy(subred: str):
    """ARP scan real con Scapy. Devuelve [{ip, mac}]. Lanza excepción si falla."""
    from scapy.all import ARP, Ether, srp

    ans, _ = srp(
        Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subred),
        timeout=2,
        verbose=0,
    )
    resultados = []
    for _, rcv in ans:
        resultados.append({"ip": rcv.psrc, "mac": rcv.hwsrc})
    return resultados


def _ping_sweep(subred: str):
    """
    "Despierta" a los vecinos de la subred con un ping a cada IP.

    Sin Scapy no se puede hacer un barrido ARP activo, y `arp -a` solo lee la
    CACHÉ del sistema operativo: si nadie contactó a esos equipos, la caché
    está vacía y no aparece nada. Un ping a cada host de la /24 fuerza al kernel
    a resolver la MAC (ARP) y así poblar esa tabla. El ping NO requiere root y
    corre en paralelo, así que un /24 se barre en pocos segundos.
    """
    try:
        import ipaddress
        red = ipaddress.ip_network(subred, strict=False)
    except (ValueError, TypeError):
        return
    objetivos = [str(ip) for ip in red.hosts()]
    # No barrer redes enormes (p. ej. una /16 son 65.534 hosts)
    if not objetivos or len(objetivos) > 1024:
        return
    with ThreadPoolExecutor(max_workers=min(64, len(objetivos))) as pool:
        list(pool.map(_ping, objetivos))


def _leer_tabla_vecinos() -> str:
    """Concatena la tabla de vecinos del SO (`ip neigh` y/o `arp -a`)."""
    salidas = []
    # `ip neigh` (iproute2) es lo estándar en Linux moderno; `arp -a` (net-tools)
    # puede no estar instalado. En Windows/macOS solo responde `arp -a`.
    for cmd in (["ip", "neigh"], ["arp", "-a"]):
        try:
            salidas.append(subprocess.check_output(
                cmd, text=True, stderr=subprocess.DEVNULL, timeout=10
            ))
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
    return "\n".join(salidas)


# IPv4 y MAC en cualquier formato de tabla (arp -a: "host (ip) at mac ...";
# ip neigh: "ip dev eth0 lladdr mac REACHABLE").
_PATRON_IP = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
_PATRON_MAC = re.compile(r"([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})")


def arp_scan_fallback(subred: str = None):
    """
    Descubre hosts sin Scapy: ping-sweep (puebla la caché) + lectura de la
    tabla de vecinos del SO. Devuelve [{ip, mac}].
    """
    if subred:
        _ping_sweep(subred)

    texto = _leer_tabla_vecinos()
    resultados = []
    vistos = set()
    for linea in texto.splitlines():
        # Descartar entradas sin MAC resuelta (incomplete / failed / <incomplete>)
        if re.search(r"incomplete|failed", linea, re.IGNORECASE):
            continue
        mi = _PATRON_IP.search(linea)
        mm = _PATRON_MAC.search(linea)
        if not mi or not mm:
            continue
        ip = mi.group(1)
        if ip in vistos or ip.endswith(".255") or ip == "255.255.255.255":
            continue
        # Normalizar la MAC a aa:bb:cc:dd:ee:ff (octetos de 2 dígitos, en minúscula)
        mac = ":".join(p.zfill(2) for p in mm.group(1).replace("-", ":").split(":")).lower()
        if mac == "00:00:00:00:00:00":
            continue
        vistos.add(ip)
        resultados.append({"ip": ip, "mac": mac})
    return resultados


def escanear_lan(subred: str = None, usar_scapy: bool = True):
    """
    Descubre hosts en la LAN y los enriquece (vendor, hostname, ping).

    :return: Tupla (lista_de_hosts, metodo_usado). Cada host es un dict con
             ip, mac, vendor, hostname, alive, latency_ms.
    """
    if subred is None:
        subred = detectar_subred()

    if usar_scapy and _scapy_disponible():
        try:
            return _enriquecer(arp_scan_scapy(subred)), "scapy (ARP scan)"
        except Exception as e:  # noqa: BLE001
            return _enriquecer(arp_scan_fallback(subred)), f"fallback (scapy falló: {e})"

    return _enriquecer(arp_scan_fallback(subred)), "fallback (ping-sweep + tabla de vecinos)"


def scapy_instalado() -> bool:
    return _scapy_disponible()
