"""
===============================================================================
Servicio HTTP auxiliar para descubrimiento de hosts en la LAN (EXTRA)
===============================================================================
Independiente del protocolo NETMON/1.0: NO usa UDP 5000 / TCP 5001 / WS 5003
ni el gateway. Es un servicio HTTP aparte (puerto 8090 por defecto) que expone
el escaneo de la LAN en JSON para que la vista web pueda mostrarlo.

Uso:
    python extras/lan_scan_service.py [puerto]

Endpoints:
    GET /                 -> info del servicio + subred sugerida
    GET /scan?subnet=CIDR -> { subnet, method, scapy_installed,
                               hosts:[{ip,mac,vendor,hostname,alive,latency_ms}] }

CORS habilitado para que la web (otro origen/puerto) pueda consumirlo.

Si se retira esta funcionalidad extra, basta con borrar extras/ y la sección
web correspondiente: el SDMR (NETMON/1.0) queda intacto.
===============================================================================
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from extras.network_discovery import escanear_lan, detectar_subred, scapy_instalado


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _enviar_json(self, codigo, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._enviar_json(200, {
                "service": "lan-scan-extra",
                "note": "Servicio HTTP auxiliar. NO usa NETMON/1.0.",
                "suggested_subnet": detectar_subred(),
                "scapy_installed": scapy_instalado(),
                "endpoints": ["/", "/scan?subnet=CIDR"],
            })
            return

        if parsed.path == "/scan":
            qs = parse_qs(parsed.query)
            subnet = (qs.get("subnet") or [detectar_subred()])[0].strip()
            usar_scapy = (qs.get("scapy") or ["1"])[0] != "0"
            try:
                hosts, metodo = escanear_lan(subnet, usar_scapy=usar_scapy)
                self._enviar_json(200, {
                    "subnet": subnet,
                    "method": metodo,
                    "scapy_installed": scapy_instalado(),
                    "hosts": hosts,
                })
            except Exception as e:  # noqa: BLE001
                self._enviar_json(500, {"error": str(e), "subnet": subnet})
            return

        self._enviar_json(404, {"error": "not found"})

    def log_message(self, *args):
        # Silencioso por defecto; descomentar para depurar:
        # super().log_message(*args)
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("=================================================================")
    print(f" LAN SCAN SERVICE (EXTRA) en http://0.0.0.0:{port}")
    print(" NO usa NETMON/1.0. Endpoints: /  /scan?subnet=CIDR")
    print("=================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Servicio detenido]")


if __name__ == "__main__":
    main()