"""
================================================================================
 CAPA DE SEGURIDAD OPCIONAL DEL SDMR (NETMON/1.0)
================================================================================

Este módulo agrega DOS protecciones al sistema, SIN cambiar el protocolo de
aplicación ni ocultar la capa de transporte (requisito de la cátedra: se siguen
usando sockets nativos y el parseo del protocolo sigue siendo manual):

  1. TLS para el canal TCP de comandos (puerto 5001).
     - Confidencialidad: las credenciales (`CMD|AUTH|admin|...`) y los comandos
       dejan de viajar en texto plano.
     - Autenticidad: el cliente verifica que habla con el servidor legítimo
       (certificado firmado por nuestra CA) y, en modo mutuo, el servidor exige
       además el certificado del cliente.
     Se implementa envolviendo el socket nativo con `ssl.SSLSocket`; el socket
     TCP y el handshake de 3 vías siguen ahí debajo, solo que cifrados.

  2. HMAC-SHA256 + timestamp + nonce para la telemetría UDP (puerto 5000).
     - Integridad y autenticidad: el servidor descarta telemetría alterada o
       enviada por un impostor que no conoce la clave compartida.
     - Anti-replay: un atacante no puede reenviar un datagrama capturado, porque
       el timestamp caduca y el nonce ya fue visto.
     UDP no tiene conexión, así que no hay TLS: se firma el contenido con una
     clave simétrica precompartida (la misma para todos los agentes).

DISEÑO CLAVE
------------
- Usa SOLO librería estándar (`ssl`, `hmac`, `hashlib`, `secrets`). La librería
  externa `cryptography` se usa únicamente en `scripts/gen_certs.py` para GENERAR
  los certificados una vez; el sistema en ejecución no la necesita.
- Todo es OPCIONAL: si la seguridad está desactivada (modo `--inseguro`), nada de
  esto se usa y el sistema se comporta exactamente como antes. Así no se rompe la
  demo ni la compatibilidad con agentes/clientes viejos.
- El sobre seguro UDP usa el separador de unidad ASCII `0x1f` (US), que NO aparece
  en el protocolo NETMON/1.0 (que usa `|` y `\\n`), para no colisionar con el
  parseo existente.
================================================================================
"""

import hashlib
import hmac
import os
import secrets
import ssl
import threading
import time

# =============================================================================
# CONSTANTES DEL SOBRE SEGURO UDP
# =============================================================================
# Cabecera que identifica un datagrama UDP firmado. Si un datagrama empieza con
# esto, el servidor sabe que debe verificar el HMAC antes de parsear telemetría.
SEC_HEADER = "SEC/1"

# Separador de campos del sobre: US (Unit Separator, 0x1f). Elegido a propósito
# para NO chocar con '|' (campos NETMON) ni con '\n' (framing).
SEC_SEP = "\x1f"

# Ventana temporal aceptada para el timestamp (segundos). Un datagrama con
# timestamp fuera de +/- esta ventana se descarta: frena reenvíos viejos y
# tolera un pequeño desfasaje de reloj entre agente y servidor.
VENTANA_ANTIREPLAY_SEG = 30.0

# Codificación del contenido a firmar (coherente con el resto del protocolo).
ENCODING = "utf-8"


# =============================================================================
# CONTEXTOS TLS (canal TCP 5001)
# =============================================================================
def contexto_tls_servidor(
    certfile: str,
    keyfile: str,
    cafile: str,
    exigir_cliente: bool = True,
) -> ssl.SSLContext:
    """
    Construye el contexto TLS que usa el SERVIDOR para envolver cada conexión
    entrante en el canal de comandos.

    :param certfile: Certificado del servidor (PEM), firmado por nuestra CA.
    :param keyfile:  Clave privada del servidor (PEM).
    :param cafile:   CA que firma los certificados de cliente (para modo mutuo).
    :param exigir_cliente: Si True (mTLS), el servidor EXIGE y verifica el
        certificado del cliente; solo clientes con certificado válido (admin,
        gui, gateway) pueden conectarse. Si False, TLS de una vía: el cliente
        verifica al servidor pero el servidor no pide certificado.
    :return: `ssl.SSLContext` listo para `wrap_socket(..., server_side=True)`.
    """
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Prohibir versiones viejas e inseguras (SSLv3/TLS1.0/1.1).
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.load_cert_chain(certfile=certfile, keyfile=keyfile)

    if exigir_cliente:
        contexto.load_verify_locations(cafile=cafile)
        contexto.verify_mode = ssl.CERT_REQUIRED

    return contexto


def contexto_tls_cliente(
    cafile: str,
    certfile: str = None,
    keyfile: str = None,
    verificar_hostname: bool = True,
) -> ssl.SSLContext:
    """
    Construye el contexto TLS que usa un CLIENTE (admin, gui o gateway) para
    conectarse al servidor y verificar su identidad.

    :param cafile:  CA con la que se valida el certificado del servidor.
    :param certfile: Certificado del cliente (PEM) para TLS mutuo. Opcional.
    :param keyfile:  Clave privada del cliente (PEM). Opcional.
    :param verificar_hostname: Si True, además de la cadena de confianza se
        valida que el nombre/IP del servidor coincida con el SAN del certificado.
        En una LAN con IP fija conviene True; con IP dinámica puede ponerse False
        (la cadena de confianza se sigue verificando).
    :return: `ssl.SSLContext` listo para `wrap_socket(..., server_hostname=...)`.
    """
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.load_verify_locations(cafile=cafile)
    contexto.verify_mode = ssl.CERT_REQUIRED
    contexto.check_hostname = verificar_hostname

    if certfile and keyfile:
        contexto.load_cert_chain(certfile=certfile, keyfile=keyfile)

    return contexto


# =============================================================================
# SOBRE SEGURO UDP: HMAC-SHA256 + TIMESTAMP + NONCE (anti-replay)
# =============================================================================
class CacheNonces:
    """
    Memoria de corta duración de los nonces ya vistos, para rechazar reenvíos.

    Un nonce es un valor aleatorio único por datagrama. Si llega un datagrama
    con un nonce que ya procesamos dentro de la ventana temporal, es un REPLAY:
    se descarta. Los nonces más viejos que la ventana se purgan (ya no pueden
    reenviarse porque su timestamp también caducó), así la memoria no crece.

    Es seguro para hilos: el `_udp_listener_loop` corre en su propio hilo.
    """

    def __init__(self, ventana_seg: float = VENTANA_ANTIREPLAY_SEG):
        self._vistos = {}            # nonce (str) -> timestamp de recepción
        self._lock = threading.Lock()
        self.ventana_seg = ventana_seg

    def visto_o_registrar(self, nonce: str, ahora: float) -> bool:
        """
        Registra el nonce y dice si ya había sido visto.

        :return: True si es un REPLAY (nonce repetido dentro de la ventana);
                 False si es nuevo (y queda registrado).
        """
        with self._lock:
            # Purga de nonces vencidos (más viejos que la ventana).
            vencidos = [n for n, t in self._vistos.items() if ahora - t > self.ventana_seg]
            for n in vencidos:
                del self._vistos[n]

            if nonce in self._vistos:
                return True
            self._vistos[nonce] = ahora
            return False


def envolver_udp(payload: str, clave: bytes) -> str:
    """
    Envuelve un payload NETMON (p. ej. `MON|NODO_01|...`) en un sobre firmado.

    Formato del sobre (campos separados por 0x1f):
        SEC/1 <US> <timestamp> <US> <nonce> <US> <payload> <US> <hmac_hex>

    El HMAC se calcula sobre `timestamp<US>nonce<US>payload`, de modo que
    cualquier alteración de esos tres campos invalida la firma.

    :param payload: Trama NETMON original (texto).
    :param clave:   Clave simétrica compartida (bytes).
    :return: Texto del sobre listo para `encode_message()` y `sendto()`.
    """
    ts = f"{time.time():.3f}"
    nonce = secrets.token_hex(8)
    mensaje = f"{ts}{SEC_SEP}{nonce}{SEC_SEP}{payload}"
    firma = hmac.new(clave, mensaje.encode(ENCODING), hashlib.sha256).hexdigest()
    return f"{SEC_HEADER}{SEC_SEP}{mensaje}{SEC_SEP}{firma}"


def es_sobre_seguro(trama: str) -> bool:
    """Indica si una trama UDP recibida viene firmada (empieza con la cabecera SEC)."""
    return trama.startswith(SEC_HEADER + SEC_SEP)


def desenvolver_udp(
    trama: str,
    clave: bytes,
    cache: CacheNonces,
    ventana_seg: float = VENTANA_ANTIREPLAY_SEG,
) -> str:
    """
    Verifica un sobre seguro UDP y devuelve el payload NETMON original.

    Valida, en orden:
      1. Estructura del sobre (cabecera y cantidad de campos).
      2. Firma HMAC (comparación en tiempo constante con `hmac.compare_digest`).
      3. Ventana temporal del timestamp (anti-replay por antigüedad).
      4. Nonce no repetido (anti-replay por duplicado).

    :raises ValueError: Si el sobre es inválido, la firma no coincide, el
        timestamp está fuera de ventana o el nonce es un reenvío. El servidor
        captura esta excepción, la loguea y NO cierra la conexión (RF07).
    :return: El payload NETMON original (texto) listo para `parse_udp_telemetry`.
    """
    partes = trama.split(SEC_SEP)
    if len(partes) != 5 or partes[0] != SEC_HEADER:
        raise ValueError("Sobre seguro UDP malformado.")

    _, ts_str, nonce, payload, firma_recibida = partes

    # 2. Verificación del HMAC en tiempo constante (evita ataques de temporización).
    mensaje = f"{ts_str}{SEC_SEP}{nonce}{SEC_SEP}{payload}"
    firma_esperada = hmac.new(clave, mensaje.encode(ENCODING), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(firma_esperada, firma_recibida):
        raise ValueError("Firma HMAC inválida: telemetría no autenticada o alterada.")

    # 3. Ventana temporal.
    try:
        ts = float(ts_str)
    except ValueError:
        raise ValueError("Timestamp inválido en el sobre seguro.")

    ahora = time.time()
    if abs(ahora - ts) > ventana_seg:
        raise ValueError(
            f"Timestamp fuera de ventana (+/-{ventana_seg:.0f}s): posible reenvío."
        )

    # 4. Nonce no repetido.
    if cache.visto_o_registrar(nonce, ahora):
        raise ValueError("Nonce repetido: datagrama reenviado (replay) descartado.")

    return payload


# =============================================================================
# HASHEO DE CONTRASEÑAS (PBKDF2-SHA256)  —  usado por AUTH y set_password.py
# =============================================================================
# Número de iteraciones de PBKDF2: cuanto más alto, más caro es un ataque de
# fuerza bruta. 200k es un valor razonable para 2024+ en hardware modesto.
PBKDF2_ITERACIONES = 200_000
PBKDF2_HASH = "sha256"


def hashear_password(password: str, salt: bytes = None) -> dict:
    """
    Deriva un hash PBKDF2-SHA256 salado de una contraseña.

    :param password: Contraseña en texto plano (solo en memoria, nunca se guarda).
    :param salt: Sal de 16 bytes; si no se pasa, se genera una aleatoria.
    :return: Dict con los campos a guardar en `usuarios.json`:
             {"algoritmo", "iteraciones", "salt" (hex), "hash" (hex)}.
    """
    if salt is None:
        salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac(
        PBKDF2_HASH, password.encode(ENCODING), salt, PBKDF2_ITERACIONES
    )
    return {
        "algoritmo": f"pbkdf2_{PBKDF2_HASH}",
        "iteraciones": PBKDF2_ITERACIONES,
        "salt": salt.hex(),
        "hash": derivado.hex(),
    }


def verificar_password(password: str, registro: dict) -> bool:
    """
    Verifica una contraseña contra un registro guardado (el dict de
    `hashear_password`). Comparación en tiempo constante.

    :param password: Contraseña en texto plano a verificar.
    :param registro: Dict con "salt", "hash" e "iteraciones".
    :return: True si coincide, False si no.
    """
    try:
        salt = bytes.fromhex(registro["salt"])
        iteraciones = int(registro.get("iteraciones", PBKDF2_ITERACIONES))
        esperado = bytes.fromhex(registro["hash"])
    except (KeyError, ValueError):
        return False

    derivado = hashlib.pbkdf2_hmac(PBKDF2_HASH, password.encode(ENCODING), salt, iteraciones)
    return hmac.compare_digest(derivado, esperado)


# =============================================================================
# CARGA DE LA CLAVE HMAC COMPARTIDA
# =============================================================================
def cargar_clave_hmac(valor: str) -> bytes:
    """
    Normaliza la clave HMAC compartida a bytes.

    La clave puede venir de una variable de entorno o de la config. NUNCA debe
    estar hardcodeada en el código ni versionada en el repositorio.

    :param valor: Clave como texto (hex o passphrase). Si parece hex de 64
        caracteres se interpreta como 32 bytes; si no, se usa su UTF-8 directo.
    :return: La clave en bytes.
    :raises ValueError: Si el valor está vacío.
    """
    if not valor:
        raise ValueError(
            "Clave HMAC vacía. Definí SDMR_HMAC_KEY (entorno) o la clave en config."
        )
    valor = valor.strip()
    try:
        if len(valor) == 64:
            return bytes.fromhex(valor)
    except ValueError:
        pass
    return valor.encode(ENCODING)


def generar_clave_hmac_hex() -> str:
    """Genera una clave HMAC aleatoria de 32 bytes en hex (para copiar a la config)."""
    return secrets.token_hex(32)


# Variable de entorno donde vive la clave HMAC compartida (la MISMA en el
# servidor y en todos los agentes). NUNCA se versiona ni se hardcodea.
NOMBRE_VAR_HMAC = "SDMR_HMAC_KEY"


def clave_hmac_desde_entorno() -> bytes:
    """
    Lee la clave HMAC compartida de la variable de entorno SDMR_HMAC_KEY.

    :raises ValueError: si no está definida, con instrucciones para generarla.
    """
    valor = os.environ.get(NOMBRE_VAR_HMAC)
    if not valor:
        raise ValueError(
            f"Falta la clave HMAC compartida. Definí la variable de entorno "
            f"{NOMBRE_VAR_HMAC} con el MISMO valor en el servidor y en los agentes. "
            f"Generá una con: python -c \"from common import security; "
            f"print(security.generar_clave_hmac_hex())\""
        )
    return cargar_clave_hmac(valor)


# =============================================================================
# AYUDANTES DE ALTO NIVEL  (para que los entrypoints sean de 1-2 líneas)
# =============================================================================
NOMBRE_CA = "ca.pem"


def ruta_certs_por_defecto() -> str:
    """Carpeta `certs/` en la raíz del proyecto (donde gen_certs.py deja los PEM)."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, "certs")


def opciones_seguridad(argv, seguro_por_defecto: bool = False) -> dict:
    """
    Interpreta las banderas de seguridad comunes SIN romper los argumentos
    posicionales que ya usan los entrypoints (puertos, IDs, etc.).

    Banderas reconocidas:
      --seguro / --inseguro     activa o desactiva TLS+HMAC (gana la última).
      --certs <dir>             carpeta de certificados (def: ./certs).
      --no-verificar-host       no exige que el host coincida con el SAN
                                (útil con IP dinámica; la CA se sigue validando).

    :return: dict con {"seguro", "dir_certs", "verificar_host"}.
    """
    argv = list(argv)
    seguro = seguro_por_defecto
    if "--seguro" in argv:
        seguro = True
    if "--inseguro" in argv:
        seguro = False

    dir_certs = ruta_certs_por_defecto()
    if "--certs" in argv:
        i = argv.index("--certs")
        if i + 1 < len(argv):
            dir_certs = argv[i + 1]

    verificar_host = "--no-verificar-host" not in argv
    return {"seguro": seguro, "dir_certs": dir_certs, "verificar_host": verificar_host}


def args_posicionales(argv) -> list:
    """
    Devuelve solo los argumentos POSICIONALES de `argv[1:]`, descartando las
    banderas de seguridad (`--seguro`, `--inseguro`, `--no-verificar-host`) y el
    par `--certs <dir>`. Permite agregar flags sin romper el parseo posicional
    (puertos, IDs, host) que ya hacen los entrypoints.
    """
    posicionales = []
    saltar = False
    for arg in list(argv)[1:]:
        if saltar:
            saltar = False
            continue
        if arg == "--certs":
            saltar = True  # el siguiente token es la carpeta, no un posicional
            continue
        if arg.startswith("--"):
            continue
        posicionales.append(arg)
    return posicionales


def contexto_servidor_desde_dir(dir_certs: str, exigir_cliente: bool = True) -> ssl.SSLContext:
    """Arma el contexto TLS del servidor leyendo server.pem/.key y ca.pem de `dir_certs`."""
    return contexto_tls_servidor(
        certfile=os.path.join(dir_certs, "server.pem"),
        keyfile=os.path.join(dir_certs, "server.key"),
        cafile=os.path.join(dir_certs, NOMBRE_CA),
        exigir_cliente=exigir_cliente,
    )


def contexto_cliente_desde_dir(dir_certs: str, rol: str, verificar_host: bool = True) -> ssl.SSLContext:
    """
    Arma el contexto TLS de un cliente (rol = 'admin' | 'gui' | 'gateway') leyendo
    ca.pem y <rol>.pem/.key de `dir_certs`. Si no existe el par del cliente, hace
    TLS de una vía (solo verifica al servidor).
    """
    cert = os.path.join(dir_certs, f"{rol}.pem")
    key = os.path.join(dir_certs, f"{rol}.key")
    tiene_par = os.path.exists(cert) and os.path.exists(key)
    return contexto_tls_cliente(
        cafile=os.path.join(dir_certs, NOMBRE_CA),
        certfile=cert if tiene_par else None,
        keyfile=key if tiene_par else None,
        verificar_hostname=verificar_host,
    )
