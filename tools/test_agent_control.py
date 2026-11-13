"""
Pruebas de la lógica de configuración del control del agente.

Correr con pytest o directo:
    python3 tools/test_agent_control.py
"""

import configparser
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.agent import agent_control as ac


def test_guardar_y_leer_config_roundtrip():
    tmp = os.path.join(tempfile.mkdtemp(), "config.ini")
    ac.guardar_config_ui("NODO_X", "10.0.0.5", ruta=tmp)
    idn, ip = ac.leer_config_ui(ruta=tmp)
    assert idn == "NODO_X"
    assert ip == "10.0.0.5"


def test_guardar_preserva_otros_valores_existentes():
    tmp = os.path.join(tempfile.mkdtemp(), "config.ini")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("[red]\npuerto_cmd=5099\nintervalo=7\n")
    ac.guardar_config_ui("", "10.0.0.5", ruta=tmp)
    cfg = configparser.ConfigParser()
    cfg.read(tmp, encoding="utf-8")
    assert cfg.get("red", "puerto_cmd") == "5099"   # preservado
    assert cfg.get("red", "intervalo") == "7"        # preservado
    assert cfg.get("red", "ip_servidor") == "10.0.0.5"


def test_leer_config_inexistente_devuelve_vacio():
    idn, ip = ac.leer_config_ui(ruta="/no/existe/nada.ini")
    assert idn == ""
    assert ip == ""


def test_ip_vacia_queda_vacia_para_broadcast():
    tmp = os.path.join(tempfile.mkdtemp(), "config.ini")
    ac.guardar_config_ui("NODO_Y", "", ruta=tmp)
    idn, ip = ac.leer_config_ui(ruta=tmp)
    assert idn == "NODO_Y"
    assert ip == ""  # vacío = descubrir por broadcast


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"PASS {prueba.__name__}")
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"FAIL {prueba.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} OK")
    sys.exit(1 if fallos else 0)
