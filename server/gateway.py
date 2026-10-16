"""
===============================================================================
Gateway WebSocket -> TCP para SDMR (clientes web y moviles)
===============================================================================
Puente TRANSPARENTE para que React (web) y React Native (Expo Go) hablen el
mismo protocolo NETMON/1.0 sin traducirlo a REST.

  Navegador/Celu --WS puerto 5003--> gateway --TCP puerto 5001--> server.py

El gateway NO autentica, NO parsea, NO inventa JSON: reenvia tramas de texto
terminadas en '\\n' tal cual en ambas direcciones. La autenticacion y los
comandos (CMD|AUTH, CMD|GET_NODES, CMD|EXEC, CMD|PING) los resuelve el servidor
central de verdad. Por eso en Wireshark se sigue viendo tcp.port==5001 y el
mismo protocolo que con admin_client.py / Tkinter.

Uso:
    python server/gateway.py [ws_port] [tcp_host] [tcp_port] [--serve-web]

    --serve-web : ademas sirve web/dist/ por http://0.0.0.0:5173 para la demo
                  offline (build de Vite pre-compilado).

Ejemplo hotspot celular (todas las laptops y celus a la misma red):
    python server/server.py
    python server/gateway.py 5003 127.0.0.1 5001
    # web:    ws://192.168.43.X:5003  (IP LAN de esta laptop, ver ipconfig)
    # movil:  ws://192.168.43.X:5003  (misma IP, campo editable en Login)
===============================================================================
"""

import argparse
import asyncio
import functools
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import websockets
except ImportError:
    print("ERROR: falta 'websockets'. Instala con: pip install websockets")
    sys.exit(1)

from common.protocol import ENCODING, BUFFER_SIZE


async def puente_ws_tcp(websocket, tcp_host: str, tcp_port: int):
    """Un WS <-> una conexion TCP al servidor central. Todo por lineas \\n."""
    peer = getattr(websocket, "remote_address", "?")
    print(f"[GW] WS conectado desde {peer}")
    try:
        reader, writer = await asyncio.open_connection(tcp_host, tcp_port)
    except OSError as e:
        await websocket.send(f"RES|ERR|ERR_104|No se pudo conectar al servidor TCP {tcp_host}:{tcp_port}: {e}\n".strip())
        await websocket.close()
        print(f"[GW] TCP {tcp_host}:{tcp_port} inalcanzable: {e}")
        return

    print(f"[GW] Puente WS {peer} <-> TCP {tcp_host}:{tcp_port}")
    buf_tcp = b""

    async def ws_hacia_tcp():
        try:
            async for msg in websocket:
                if isinstance(msg, bytes):
                    msg = msg.decode(ENCODING, errors="replace")
                linea = msg if msg.endswith("\n") else msg + "\n"
                print(f"[GW] WS->TCP: {linea.strip()[:120]}")
                writer.write(linea.encode(ENCODING))
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def tcp_hacia_ws():
        nonlocal buf_tcp
        try:
            while True:
                datos = await reader.read(BUFFER_SIZE)
                if not datos:
                    break
                buf_tcp += datos
                while b"\n" in buf_tcp:
                    linea, buf_tcp = buf_tcp.split(b"\n", 1)
                    texto = linea.decode(ENCODING, errors="replace").strip()
                    if texto:
                        print(f"[GW] TCP->WS: {texto[:120]}")
                        await websocket.send(texto)
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    await asyncio.gather(ws_hacia_tcp(), tcp_hacia_ws())
    print(f"[GW] Puente cerrado para {peer}")


def servir_web_carpeta(carpeta: str, puerto: int = 5173):
    """Sirve web/dist/ por HTTP para la demo offline (sin npm)."""
    if not os.path.isdir(carpeta):
        print(f"[GW-WEB] No existe {carpeta}. Corre antes: cd web; npm run build")
        return
    handler = functools.partial(SimpleHTTPRequestHandler, directory=carpeta)
    httpd = ThreadingHTTPServer(("0.0.0.0", puerto), handler)
    print(f"[GW-WEB] Sirviendo {carpeta} en http://0.0.0.0:{puerto}")
    httpd.serve_forever()


async def main_async(ws_port: int, tcp_host: str, tcp_port: int):
    handler = functools.partial(puente_ws_tcp, tcp_host=tcp_host, tcp_port=tcp_port)
    async with websockets.serve(handler, "0.0.0.0", ws_port, max_size=1_048_576):
        print("=================================================================")
        print(f" GATEWAY SDMR WS->TCP en 0.0.0.0:{ws_port} -> {tcp_host}:{tcp_port}")
        print(" Reenvio transparente de tramas NETMON/1.0 (sin REST, sin auth propia)")
        print("=================================================================")
        await asyncio.Future()  # corre para siempre


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Gateway WS->TCP SDMR")
    ap.add_argument("ws_port", nargs="?", type=int, default=5003)
    ap.add_argument("tcp_host", nargs="?", default="127.0.0.1")
    ap.add_argument("tcp_port", nargs="?", type=int, default=5001)
    ap.add_argument("--serve-web", action="store_true", help="Servir web/dist por HTTP 5173")
    ap.add_argument("--web-port", type=int, default=5173)
    args = ap.parse_args()

    if args.serve_web:
        raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dist = os.path.join(raiz, "web", "dist")
        t = threading.Thread(target=servir_web_carpeta, args=(dist, args.web_port), daemon=True)
        t.start()

    try:
        asyncio.run(main_async(args.ws_port, args.tcp_host, args.tcp_port))
    except KeyboardInterrupt:
        print("\n[GW] Detenido por el usuario.")
