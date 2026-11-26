# Guía de las mejoras de seguridad — SDMR

> Cómo probar el proyecto con **todas las mejoras** y ver qué cambió.
> Pensada para correr paso a paso, en una sola máquina o entre dos equipos.

Esta tanda de mejoras agrega una **capa de seguridad opcional** al SDMR **sin cambiar
el protocolo NETMON/1.0** ni las librerías permitidas (solo biblioteca estándar de
Python: `ssl`, `hmac`, `hashlib`, `sqlite3` no hace falta acá). Todo está **apagado por
defecto**: el proyecto se sigue usando igual que siempre, y la seguridad se enciende con
el flag `--seguro`.

---

## 1. Qué cambió (resumen)

| Mejora | Antes | Ahora (con `--seguro`) |
| :--- | :--- | :--- |
| **Canal TCP de comandos (5001)** | Texto plano: la contraseña viajaba legible | **TLS mutuo (TLS 1.3)**: cifrado + cliente y servidor se verifican con certificados |
| **Telemetría UDP (5000)** | Cualquiera podía inyectar o reenviar telemetría | **HMAC-SHA256 + timestamp + nonce**: se descarta lo no firmado, alterado o reenviado |
| **Contraseñas** | Hardcodeadas en `server.py` (`admin/admin123`) | **PBKDF2-SHA256 salado** en `server/usuarios.json`, fuera del código |
| **Permisos** | `admin` y `operador` podían todo | **RBAC**: `operador` es solo lectura; solo `admin` ejecuta `EXEC` |

> **El RBAC está activo SIEMPRE** (no depende de `--seguro`): a partir de ahora el
> `operador` no puede ejecutar comandos, ni por consola ni por la web.

**Archivos nuevos:** `common/security.py`, `scripts/gen_certs.py`, `scripts/set_password.py`.
**Archivos tocados:** `server/server.py`, `agent/agent.py`, `client/admin_client.py`,
`client/gui_monitor.py`, `server/gateway.py`, `.gitignore`, `requirements.txt`.

---

## 2. Poner el repo al día

En la máquina de tu compañero (y en cualquier equipo del test):

```bash
git checkout main
git pull
```

Las mejoras ya están en `main`. No hace falta instalar nada nuevo para el modo normal;
`cryptography` solo se usa **una vez** para generar certificados (paso 4.1).

---

## 3. Modo normal (como siempre)

Nada cambió para el día a día. Desde la raíz del repo:

```bash
python server/server.py
python agent/agent.py
python client/admin_client.py 127.0.0.1
```

El servidor imprime `[SEGURIDAD] Modo INSEGURO (sin TLS/HMAC)...`. El login y el RBAC
igual funcionan (si existe `server/usuarios.json` usa PBKDF2; si no, usa las credenciales
por defecto `admin/admin123` y `operador/operador123`).

> La suite de pruebas sigue pasando igual: `python tools/test_system.py` → **22/22**.

---

## 4. Activar el modo seguro (TLS + HMAC)

Son 4 pasos; los 3 primeros se hacen **una sola vez**.

### 4.1 Generar los certificados (una vez)

```bash
pip install cryptography
python scripts/gen_certs.py                      # para probar todo en una sola PC
python scripts/gen_certs.py --ip 192.168.0.13    # agrega la IP del servidor (red real)
```

Esto crea la carpeta `certs/` (ignorada por git) con:
- `ca.pem` → la autoridad de confianza.
- `server.pem` / `server.key` → certificado del servidor.
- `admin.pem`, `gui.pem`, `gateway.pem` (+ `.key`) → certificados de los clientes.

> **Red real (Pi + notebook):** generá los certs en una PC con `--ip <IP_del_servidor>`
> y copiá a la otra máquina `ca.pem` + el par del rol que corra ahí (p. ej. `admin.*`).
> Los `.key` nunca se suben a git (están en `.gitignore`).

### 4.2 Crear usuarios con contraseña hasheada (una vez)

```bash
python scripts/set_password.py admin --rol admin
python scripts/set_password.py operador --rol operador
```

Pide la contraseña de forma oculta y la guarda **hasheada** en `server/usuarios.json`
(también ignorado por git). El servidor lo carga solo.

### 4.3 Definir la clave HMAC compartida (una vez por sesión)

Generá una clave:

```bash
python -c "from common import security; print(security.generar_clave_hmac_hex())"
```

Y seteála con el **mismo valor** en **cada terminal** que levante el servidor o un agente:

- **PowerShell (Windows):**
  ```powershell
  $env:SDMR_HMAC_KEY = "pega-aca-la-clave"
  ```
- **Bash (Linux/Git Bash):**
  ```bash
  export SDMR_HMAC_KEY="pega-aca-la-clave"
  ```

### 4.4 Levantar todo en modo seguro

Agregá `--seguro` a cada componente (cada uno en su terminal, con `SDMR_HMAC_KEY` seteada):

```bash
python server/server.py --seguro
python agent/agent.py --ip 127.0.0.1 --seguro
python client/admin_client.py 127.0.0.1 --seguro
python client/gui_monitor.py --seguro
python server/gateway.py 5003 127.0.0.1 5001 --seguro --serve-web
```

El servidor debe imprimir:
```
[SEGURIDAD] TLS mutuo ACTIVADO en el canal TCP...
[SEGURIDAD] Telemetría UDP verificada con HMAC-SHA256 + anti-replay.
[AUTH] 2 usuario(s) cargado(s) desde usuarios.json (contraseñas PBKDF2 hasheadas).
```

> Si falta un cert o la clave, el servidor avisa con un mensaje claro y no arranca.
> Opcional: `--no-verificar-host` si la IP del servidor es dinámica.

---

## 5. Probar cada mejora y ver la diferencia

### Mejora 1 — TLS (cifrado del canal de comandos)
1. Levantá server y `admin_client.py` **con** `--seguro` → conecta e imprime
   *"¡Conexión TLS establecida y verificada!"*.
2. Probá el cliente **sin** `--seguro` contra el server seguro → **no conecta** (rechazado).
3. En Wireshark (filtro `tcp.port == 5001`): sin seguridad se lee `CMD|AUTH|admin|admin123`
   en claro; con `--seguro` se ve **cifrado**. Ese es el antes/después.

### Mejora 2 — HMAC en la telemetría UDP
1. Con el server en `--seguro`, levantá un agente **sin** `--seguro` (o con otra clave).
2. Pedí `GET_NODES`: ese agente **no aparece** (su telemetría se descarta).
3. Levantá el agente **con** `--seguro` y la clave correcta → aparece al toque.
4. En Wireshark (`udp.port == 5000`): la trama ya no es `MON|NODO_01|...` legible, sino el
   sobre `SEC/1` con su firma.

### Mejora 3 — Contraseñas PBKDF2 (fuera del código)
1. Abrí `server/usuarios.json`: las contraseñas están **hasheadas**, no en texto plano.
2. En `server/server.py` ya **no hay** credenciales hardcodeadas de verdad (solo un
   fallback de demo).
3. Cambiá una contraseña con `scripts/set_password.py` y verificá que el login la toma.

### Mejora 4 — RBAC (roles)
Esto se ve **sin** `--seguro` también. Con `admin_client.py`:
1. Autenticate como **`operador` / `operador123`** y mandá un `EXEC` → responde
   **`ERR_101` "Permiso denegado: EXEC requiere rol 'admin'"**.
2. Autenticate como **`admin` / `admin123`** y mandá el mismo `EXEC` → se ejecuta.

---

## 6. Probarlo desde la WEB (lo más vistoso)

Levantá el stack (en modo normal alcanza para ver login + RBAC; agregá `--seguro` al
server y al gateway si querés también TLS):

```bash
python server/server.py
python agent/agent.py NODO_01 127.0.0.1 5000 5002
python agent/agent.py NODO_02 127.0.0.1 5000 5004
python server/gateway.py 5003 127.0.0.1 5001 --serve-web
```

Abrí **http://localhost:5173** y:
1. **Login** como `admin` / `admin123` → dashboard en vivo con los nodos.
2. Pestaña **Nodos** → elegí un nodo + `DIAGNOSTIC` → **Enviar EXEC** → responde
   *"[OK EXEC_SUCCESS] Diagnóstico ejecutado..."*.
3. **Salir** y entrá como `operador` / `operador123` → probá **Enviar EXEC** → la web
   muestra *"[ERR ERR_101] Permiso denegado: EXEC requiere rol 'admin'"*.
4. Pestaña **Tráfico** → se ven las tramas NETMON/1.0 en vivo (`TX`/`RX`).
5. Pestaña **Topología** → mapa de red con los nodos.

> Si falla `npm`/web: primero `cd web && npm install && npm run build` (en Windows,
> si PowerShell bloquea `npm`, usá `npm.cmd install` y `npm.cmd run build`).

---

## 7. Qué NO cambió (compatibilidad)

- Por defecto todo sigue **inseguro/en claro**: la demo y los clientes viejos andan igual.
- El protocolo NETMON/1.0 **no cambió**; el modo seguro solo envuelve el transporte.
- La suite de integración sigue en **22/22**.
- El canal de comandos del agente (`EXEC`, puerto 5002) **queda en claro a propósito**
  (evita tener que distribuir un certificado por cada agente).

---

## 8. Lo que quedó afuera (mejoras futuras)

- **mTLS por agente** (certificado por equipo) y **TLS en el canal EXEC 5002**.
- **WSS** (cifrar el tramo navegador/celular ↔ gateway; hoy ese tramo es WS en claro).
- Ver [`docs/MEJORAS_RECOMENDADAS.md`](docs/MEJORAS_RECOMENDADAS.md) para el resto del
  roadmap (histórico/gráficas, alertas, EXEC con resultado real, etc.).

---

## 9. Chuleta de comandos

```bash
# Normal
python server/server.py
python agent/agent.py
python client/admin_client.py 127.0.0.1

# Setup seguro (una vez)
pip install cryptography
python scripts/gen_certs.py                 # o --ip <IP_servidor>
python scripts/set_password.py admin --rol admin
python scripts/set_password.py operador --rol operador
python -c "from common import security; print(security.generar_clave_hmac_hex())"

# Seguro (SDMR_HMAC_KEY seteada en cada terminal)
python server/server.py --seguro
python agent/agent.py --ip 127.0.0.1 --seguro
python client/admin_client.py 127.0.0.1 --seguro

# Web
python server/gateway.py 5003 127.0.0.1 5001 --serve-web   # http://localhost:5173

# Pruebas
python tools/test_system.py                 # 22/22
```

**Filtros de Wireshark:** `tcp.port == 5001` (comandos / TLS) · `udp.port == 5000`
(telemetría / HMAC) · `tcp.port == 5002` (EXEC).

**Usuarios por defecto:** `admin` / `admin123` (rol admin) · `operador` / `operador123`
(rol operador). Cambiá las contraseñas con `scripts/set_password.py`.
