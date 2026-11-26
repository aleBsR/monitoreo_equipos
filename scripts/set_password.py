"""
================================================================================
 ALTA / CAMBIO DE CONTRASEÑAS DE USUARIOS DEL SDMR  (hash PBKDF2 salado)
================================================================================

Crea o actualiza `server/usuarios.json`, donde el servidor guarda los usuarios
con su contraseña HASHEADA (PBKDF2-SHA256 + sal), NUNCA en texto plano, y su ROL.

Con esto se eliminan las credenciales hardcodeadas del código (`admin/admin123`)
y se habilita el control por roles:
  - rol "admin"    -> puede ver y ejecutar comandos (EXEC).
  - rol "operador" -> solo lectura (GET_NODES / PING), sin EXEC.

El archivo `server/usuarios.json` está en `.gitignore`: no se versiona.

USO
---
    python scripts/set_password.py admin --rol admin
    python scripts/set_password.py operador --rol operador
    # pedirá la contraseña de forma oculta (no queda en el historial de la shell)

    # alternativa no interactiva (menos segura, queda en el historial):
    python scripts/set_password.py admin --rol admin --password "mi-clave"
================================================================================
"""

import argparse
import getpass
import json
import os
import sys

# Permite importar common.security al correr desde la raíz del proyecto.
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.security import hashear_password  # noqa: E402

ROLES_VALIDOS = ("admin", "operador")


def ruta_usuarios() -> str:
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, "server", "usuarios.json")


def cargar(ruta: str) -> dict:
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar(ruta: str, data: dict):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description="Alta/cambio de contraseña de un usuario SDMR.")
    ap.add_argument("usuario", help="Nombre de usuario (p. ej. admin).")
    ap.add_argument("--rol", choices=ROLES_VALIDOS, default="admin",
                    help="Rol del usuario (admin = EXEC, operador = solo lectura).")
    ap.add_argument("--password", default=None,
                    help="Contraseña (si se omite, se pide de forma oculta).")
    args = ap.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass(f"Contraseña para '{args.usuario}' ({args.rol}): ")
        repetir = getpass.getpass("Repetir contraseña: ")
        if password != repetir:
            print("ERROR: las contraseñas no coinciden.")
            sys.exit(1)
    if not password:
        print("ERROR: la contraseña no puede estar vacía.")
        sys.exit(1)

    ruta = ruta_usuarios()
    usuarios = cargar(ruta)

    registro = hashear_password(password)
    registro["rol"] = args.rol
    usuarios[args.usuario] = registro

    guardar(ruta, usuarios)
    print(f"[OK] Usuario '{args.usuario}' (rol: {args.rol}) guardado en server/usuarios.json")
    print("     La contraseña quedó hasheada con PBKDF2-SHA256 salado (no en texto plano).")


if __name__ == "__main__":
    main()
