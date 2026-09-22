"""
Script de prueba de integración automatizado para SDMR.
Prueba:
 1. Inicio de Servidor Central (TCP + UDP)
 2. Ejecución simultánea de 3 Agentes de Monitoreo (NODO_01, NODO_02, NODO_03)
 3. Conexión de Cliente Administrador TCP
 4. Pruebas de PING, AUTH, GET_NODES y EXEC
 5. Verificación de respuestas y cierre limpio
"""

import subprocess
import time
import sys
import os

sys.path.append(os.path.dirname(__file__))
from client.admin_client import AdminClient


def run_integration_test():
    print("=================================================================")
    print(" INICIANDO PRUEBA DE INTEGRACIÓN AUTOMATIZADA (SDMR)")
    print("=================================================================")

    # 1. Iniciar Servidor en proceso en segundo plano
    print("[1/5] Lanzando Servidor Central (server.py)...")
    server_proc = subprocess.Popen([sys.executable, "server/server.py", "5000", "5001"])
    time.sleep(1.5)  # Dar tiempo a que abra los sockets

    agents = []
    try:
        # 2. Lanzar 3 Agentes en paralelo para probar concurrencia
        print("[2/5] Lanzando 3 Agentes de Monitoreo concurrentes (NODO_01, NODO_02, NODO_03)...")
        for i in range(1, 4):
            node_name = f"NODO_0{i}"
            p = subprocess.Popen([sys.executable, "agent/agent.py", node_name, "127.0.0.1", "5000"])
            agents.append(p)
        
        time.sleep(4.0)  # Permitir que los agentes transmitan métricas UDP al servidor

        # 3. Conectar Cliente Administrador vía TCP
        print("[3/5] Conectando Cliente Administrador vía TCP...")
        client = AdminClient("127.0.0.1", 5001)
        assert client.connect(), "Falló la conexión TCP al servidor"

        # 4. Probar comandos TCP
        print("[4/5] Ejecutando comandos TCP según protocolo NETMON/1.0...")

        # PING
        res_ping = client.send_command("PING")
        print(f"  -> PING Test: {res_ping}")
        assert res_ping["status"] == "OK", "PING falló"

        # AUTH
        res_auth = client.send_command("AUTH", "admin", "admin123")
        print(f"  -> AUTH Test: {res_auth}")
        assert res_auth["status"] == "OK", "AUTH falló"
        client.is_authenticated = True

        # GET_NODES
        res_nodes = client.send_command("GET_NODES", "ALL")
        print(f"  -> GET_NODES Test: {res_nodes['payload_or_code']}")
        assert "NODES_COUNT:3" in res_nodes["payload_or_code"], "No se registraron los 3 nodos en el servidor"

        # EXEC
        res_exec = client.send_command("EXEC", "NODO_01", "RESTART_SERVICE")
        print(f"  -> EXEC Test: {res_exec}")
        assert res_exec["status"] == "OK", "EXEC falló"

        # 5. Probar envío de datos inválidos
        print("[5/5] Probando envío de datos inválidos...")
        client.send_malformed_test()

        client.close()
        print("\n✅ ¡TODAS LAS PRUEBAS DE INTEGRACIÓN PASARON EXITOSAMENTE!")

    finally:
        print("\nCerrando agentes y servidor de prueba...")
        for a in agents:
            a.terminate()
        server_proc.terminate()
        print("Procesos finalizados.")


if __name__ == "__main__":
    run_integration_test()
