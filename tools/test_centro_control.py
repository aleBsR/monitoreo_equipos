"""
Pruebas del núcleo de gestión del Centro de Control (scripts/centro_control.py).

Se puede correr con pytest o directamente:
    python3 tools/test_centro_control.py
"""

import os
import socket
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import centro_control as cc


def test_puerto_escuchando_detecta_abierto_y_cerrado():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    puerto = s.getsockname()[1]
    assert cc.puerto_escuchando(puerto) is True
    s.close()
    # Un puerto que (casi con certeza) nadie abrió
    assert cc.puerto_escuchando(1) is False


def test_tail_log_devuelve_ultimas_lineas():
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("\n".join(f"linea{i}" for i in range(500)))
        ruta = f.name
    out = cc.tail_log(ruta, 10)
    assert "linea499" in out
    assert "linea490" in out
    assert "linea489" not in out


def test_tail_log_archivo_inexistente_no_falla():
    out = cc.tail_log("/no/existe/nada.log", 10)
    assert isinstance(out, str)


def test_comando_agente_usa_id_y_puerto_cmd_distintos():
    cmd0 = cc.comando_servicio("agentes", "/proj", 0)
    cmd1 = cc.comando_servicio("agentes", "/proj", 1)
    assert "NODO_01" in cmd0 and "5002" in cmd0
    assert "NODO_02" in cmd1 and "5004" in cmd1
    assert "5003" not in cmd1  # no pisa el gateway


def test_estado_tiene_todas_las_claves_y_forma():
    g = cc.GestorProcesos("/proj")
    est = g.estado()
    assert set(est.keys()) == {"servidor", "gateway", "web", "escaneo", "agentes"}
    for v in est.values():
        assert set(v.keys()) >= {"corriendo", "pids", "puerto_ok"}


def test_detener_servicio_no_iniciado_es_idempotente():
    g = cc.GestorProcesos("/proj")
    g.detener("servidor")  # no debe lanzar excepción
    # 'corriendo' puede ser True si hay un server externo en el puerto; lo que
    # prueba la idempotencia es que el gestor no trackea procesos propios.
    assert g.estado()["servidor"]["pids"] == []


class _FakePopen:
    """Popen de mentira para probar la lógica sin lanzar procesos reales."""
    _n = 0

    def __init__(self, *a, **k):
        _FakePopen._n += 1
        self.pid = 9000 + _FakePopen._n
        self._vivo = True

    def poll(self):
        return None if self._vivo else 0

    def terminate(self):
        self._vivo = False

    def kill(self):
        self._vivo = False

    def wait(self, timeout=None):
        self._vivo = False
        return 0


def test_web_falta_build_se_refleja_en_estado():
    raiz = tempfile.mkdtemp()  # sin web/dist
    g = cc.GestorProcesos(raiz)
    assert g.estado()["web"]["falta_build"] is True


def test_iniciar_web_sin_dist_no_lanza_proceso():
    raiz = tempfile.mkdtemp()
    g = cc.GestorProcesos(raiz)
    g.iniciar("web")
    assert g.estado()["web"]["pids"] == []


def test_agentes_escala_a_n_al_reiniciar():
    raiz = tempfile.mkdtemp()
    orig = cc.subprocess.Popen
    cc.subprocess.Popen = _FakePopen
    try:
        g = cc.GestorProcesos(raiz)
        g.iniciar("agentes", n=1)
        assert len(g.estado()["agentes"]["pids"]) == 1
        g.iniciar("agentes", n=3)
        assert len(g.estado()["agentes"]["pids"]) == 3
    finally:
        cc.subprocess.Popen = orig


def test_post_sin_header_es_rechazado():
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer(("127.0.0.1", 0), cc.Handler)
    puerto = srv.server_address[1]
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        # Sin el header custom -> 403 (bloquea CSRF de otra pestaña)
        req = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/detener?svc=agentes", method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
            codigo = 200
        except urllib.error.HTTPError as e:
            codigo = e.code
        assert codigo == 403
        # Con el header -> 200
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/detener?svc=agentes", method="POST",
            headers={"X-SDMR-Control": "1"})
        with urllib.request.urlopen(req2, timeout=3) as r:
            assert r.status == 200
    finally:
        srv.shutdown()


def test_concurrencia_no_rompe_ni_deja_estado_inconsistente():
    import threading
    raiz = tempfile.mkdtemp()
    orig = cc.subprocess.Popen
    cc.subprocess.Popen = _FakePopen
    try:
        g = cc.GestorProcesos(raiz)
        errores = []

        def trabajar():
            try:
                for _ in range(20):
                    g.iniciar("agentes", n=2)
                    g.estado()
                    g.detener("agentes")
            except Exception as e:  # noqa: BLE001
                errores.append(e)

        hilos = [threading.Thread(target=trabajar) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        assert not errores, errores
        g.iniciar("agentes", n=2)
        assert len(g.estado()["agentes"]["pids"]) == 2
    finally:
        cc.subprocess.Popen = orig


# --------------------------------------------------------------------------
# Runner sin pytest
# --------------------------------------------------------------------------
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
