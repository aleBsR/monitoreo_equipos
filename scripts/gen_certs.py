"""
================================================================================
 GENERADOR DE CERTIFICADOS TLS PARA EL SDMR  (se corre UNA sola vez)
================================================================================

Crea, dentro de la carpeta `certs/` (ignorada por git), todo lo necesario para
el canal TLS del puerto 5001:

  - ca.pem / ca.key       -> Autoridad Certificadora propia (raíz de confianza).
  - server.pem / server.key  -> Certificado del SERVIDOR, con SAN (localhost,
                                127.0.0.1, el hostname y las IPs de LAN que le
                                pases con --ip / --host).
  - admin.pem / admin.key
    gui.pem / gui.key
    gateway.pem / gateway.key -> Certificados de los CLIENTES (TLS mutuo).

IMPORTANTE
----------
- Este script es la ÚNICA pieza que necesita la librería externa `cryptography`.
  El sistema en ejecución (server/clientes/agente) usa solo `ssl` de la stdlib.
- Para que un cliente en OTRA máquina confíe en el servidor, hay que copiarle el
  `ca.pem` (la raíz de confianza) y SU par de certificado+clave. Esa copia es la
  "distribución de la CA": con la Raspberry + la notebook son solo 2 equipos.
- Las claves privadas (.key) NUNCA se versionan. `certs/` está en `.gitignore`.

USO
---
    pip install cryptography
    python scripts/gen_certs.py                      # localhost para probar en 1 PC
    python scripts/gen_certs.py --ip 192.168.0.13    # agrega la IP de la Pi al SAN
    python scripts/gen_certs.py --ip 192.168.0.13 --ip 192.168.0.8 --host mi-pc
================================================================================
"""

import argparse
import datetime
import ipaddress
import os
import socket
import sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("ERROR: falta la librería 'cryptography' (solo se usa para generar los certs).")
    print("Instalala con:  pip install cryptography")
    sys.exit(1)


VALIDEZ_DIAS = 825  # ~2 años y algo, suficiente para el proyecto.


def _nueva_clave():
    """Genera una clave privada RSA de 2048 bits."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _guardar_clave(clave, ruta: str):
    """Escribe una clave privada en formato PEM (sin passphrase, uso de laboratorio)."""
    with open(ruta, "wb") as f:
        f.write(
            clave.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )


def _guardar_cert(cert, ruta: str):
    """Escribe un certificado en formato PEM."""
    with open(ruta, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def crear_ca(dir_certs: str):
    """Crea la Autoridad Certificadora raíz (CA) autofirmada."""
    clave = _nueva_clave()
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SDMR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SDMR Root CA"),
    ])
    ahora = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora)
        .not_valid_after(ahora + datetime.timedelta(days=VALIDEZ_DIAS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(clave, hashes.SHA256())
    )
    _guardar_clave(clave, os.path.join(dir_certs, "ca.key"))
    _guardar_cert(cert, os.path.join(dir_certs, "ca.pem"))
    print("[OK] CA raíz creada:        certs/ca.pem  (+ ca.key)")
    return clave, cert


def crear_cert_firmado(dir_certs, nombre_archivo, common_name, ca_clave, ca_cert, sans=None):
    """
    Crea un certificado (servidor o cliente) firmado por la CA.

    :param sans: lista de Subject Alternative Names (DNS o IP). Solo el servidor
        los necesita (para que el cliente valide el host). Los clientes no.
    """
    clave = _nueva_clave()
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SDMR"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    ahora = datetime.datetime.utcnow()
    builder = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(ca_cert.subject)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora)
        .not_valid_after(ahora + datetime.timedelta(days=VALIDEZ_DIAS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )

    if sans:
        entradas = []
        for s in sans:
            try:
                entradas.append(x509.IPAddress(ipaddress.ip_address(s)))
            except ValueError:
                entradas.append(x509.DNSName(s))
        builder = builder.add_extension(x509.SubjectAlternativeName(entradas), critical=False)

    cert = builder.sign(ca_clave, hashes.SHA256())
    _guardar_clave(clave, os.path.join(dir_certs, f"{nombre_archivo}.key"))
    _guardar_cert(cert, os.path.join(dir_certs, f"{nombre_archivo}.pem"))
    etiqueta = "Servidor" if sans else "Cliente "
    print(f"[OK] {etiqueta} '{common_name}':".ljust(28) + f"certs/{nombre_archivo}.pem  (+ .key)")
    return cert


def main():
    ap = argparse.ArgumentParser(description="Genera los certificados TLS del SDMR.")
    ap.add_argument("--ip", action="append", default=[],
                    help="IP de LAN a incluir en el SAN del servidor (repetible).")
    ap.add_argument("--host", action="append", default=[],
                    help="Hostname a incluir en el SAN del servidor (repetible).")
    ap.add_argument("--dir", default=None, help="Carpeta de salida (def: ./certs).")
    args = ap.parse_args()

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dir_certs = args.dir or os.path.join(raiz, "certs")
    os.makedirs(dir_certs, exist_ok=True)

    # SAN del servidor: siempre localhost + loopback + hostname local, más lo que pidan.
    sans = ["localhost", "127.0.0.1"]
    try:
        sans.append(socket.gethostname())
    except OSError:
        pass
    sans.extend(args.host)
    sans.extend(args.ip)
    # Dedup conservando orden.
    sans = list(dict.fromkeys(sans))

    print("=================================================================")
    print(" GENERANDO CERTIFICADOS TLS DEL SDMR")
    print("=================================================================")
    print(f"Carpeta de salida : {dir_certs}")
    print(f"SAN del servidor  : {', '.join(sans)}")
    print("-----------------------------------------------------------------")

    ca_clave, ca_cert = crear_ca(dir_certs)
    crear_cert_firmado(dir_certs, "server", "SDMR Server", ca_clave, ca_cert, sans=sans)
    for cliente in ("admin", "gui", "gateway"):
        crear_cert_firmado(dir_certs, cliente, f"SDMR {cliente}", ca_clave, ca_cert)

    print("-----------------------------------------------------------------")
    print("Listo. Para una máquina cliente en otra IP, copiale: ca.pem y su par")
    print("<cliente>.pem/.key. Para el servidor en la Pi: ca.pem, server.pem/.key.")
    print("=================================================================")


if __name__ == "__main__":
    main()
