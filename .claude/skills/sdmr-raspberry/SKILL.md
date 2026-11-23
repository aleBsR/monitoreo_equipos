---
name: sdmr-raspberry
description: Conexión por SSH a la Raspberry Pi del proyecto SDMR y arranque/parada del stack completo (servidor en la Pi + agentes, gateway y web en la notebook) para pruebas en red real y para grabar el video del TPI. Úsala siempre que se mencione la Raspberry/Pi, "levantar/prender/apagar todo", "conectarme a la raspberry", "levantar el servidor en la Pi", preparar la demo entre dos equipos, o cuando haya que reproducir el escenario de red con IPs distintas (servidor 192.168.0.13 ↔ notebook 192.168.0.8). Trae los datos de conexión, los comandos copiá-y-pegá y dos gotchas que rompen el SSH si no se respetan. Complementa a [[sdmr-contexto]] (qué es el proyecto) y a [[sdmr-demo-video]] (guion manual de la demo).
---

# SDMR en la Raspberry Pi — conexión y arranque del stack

Esta skill sirve para dejar corriendo el **SDMR entre dos equipos reales** de la LAN:
la **Raspberry Pi hace de servidor central** y la **notebook corre los agentes, el
gateway y la web**. Es el escenario que pide la cátedra (dos IP distintas, telemetría
y comandos cruzando la red) y el que se usa para grabar el video.

Para qué es cada rol y cómo funciona el protocolo, ver [[sdmr-contexto]].
Para el paso a paso manual de la demo/video, ver [[sdmr-demo-video]].

---

## 🔌 Datos de conexión (verificados)

| Dato | Valor |
| --- | --- |
| **Host / IP de la Pi** | `192.168.0.13` (puede cambiar si el router da otra IP) |
| **Usuario SSH** | `raspberry` |
| **SO / arquitectura** | Ubuntu 24.04.4 LTS, ARM64 (aarch64) |
| **Python** | 3.12 (solo stdlib para el core; **sin psutil** → el agente simula métricas) |
| **Clave SSH** | Ya instalada (`~/.ssh/id_ed25519`) → entra sin contraseña |
| **Repo en la Pi** | `~/monitoreo_equipos` (clon de `github.com/aleBsR/monitoreo_equipos`) |
| **IP de la notebook** | `192.168.0.8` (es la IP con que aparecen sus agentes/clientes) |
| **Subred** | `192.168.0.0/24` |

Conexión base (se repite en todos los comandos):

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 raspberry@192.168.0.13
```

### Si la Pi tiene otra IP (recién encendida, DHCP)

Las Raspberry Pi tienen MAC de fábrica que empieza con `d8:3a:dd` (entre otras:
`b8:27:eb`, `dc:a6:32`, `e4:5f:01`, `28:cd:c1`, `2c:cf:67`). Para encontrarla:

```bash
for i in $(seq 1 254); do (ping -c1 -W1 192.168.0.$i >/dev/null 2>&1 &) ; done; sleep 3; ip neigh | grep -iE 'd8:3a:dd|b8:27:eb|dc:a6:32|e4:5f:01'
```

Confirmá SSH abierto con `nmap -Pn -p22 <IP>` y actualizá el `192.168.0.13` de los
comandos. Si nunca se instaló la clave, instalala una vez (pide la contraseña **una**
vez, en una terminal visible): `ssh-copy-id -i ~/.ssh/id_ed25519.pub -o StrictHostKeyChecking=accept-new raspberry@<IP>`.

---

## ⚠️ Dos gotchas que ROMPEN el SSH (no repetir)

Estos dos errores cuestan mucho tiempo. Entender el porqué evita reintroducirlos.

1. **`pkill -f server/server.py` se suicida la propia sesión.** `pkill -f` compara
   contra la línea de comando completa de cada proceso, y la línea del shell SSH que
   está corriendo el comando **también contiene** `server/server.py` (porque está por
   lanzarlo o matarlo). Resultado: `pkill` mata su propia sesión → la conexión cae con
   RST (exit 255) y nada se ejecuta. **Solución:** usar siempre el patrón con corchete,
   que coincide con el proceso real pero no con la línea del `pkill`:
   `pkill -f "[s]erver/server.py"`, `pkill -f "[a]gent/agent.py"`, `pkill -f "[g]ateway.py"`.
   Lo mismo para `pgrep`.

2. **Dejar un proceso en segundo plano cuelga el SSH.** Un `python ... &` sobre SSH no
   cierra el canal (el hijo mantiene abiertos los descriptores), así que el `ssh` queda
   colgado. **Solución:** desacoplar con `setsid`, redirigir las tres FD y envolver la
   llamada en `timeout`; el proceso **sobrevive** aunque el `ssh` corte por timeout:
   ```bash
   timeout 10 ssh ... 'cd ~/monitoreo_equipos && setsid python3 -u server/server.py 5000 5001 120 </dev/null >/tmp/srv.log 2>&1 & echo lanzado'
   ```
   Después **verificá en una conexión NUEVA** (puertos + log), nunca en la misma.

---

## ▶️ Levantar TODO el stack

Orden de oro: **servidor primero** (Pi), después los clientes (notebook).

### 1. Servidor central — en la Pi

```bash
timeout 10 ssh -o BatchMode=yes raspberry@192.168.0.13 'cd ~/monitoreo_equipos && setsid python3 -u server/server.py 5000 5001 120 </dev/null >/tmp/srv.log 2>&1 & echo lanzado'
```

Verificar (conexión nueva): puertos `0.0.0.0:5000` (UDP) y `0.0.0.0:5001` (TCP) y log:

```bash
ssh -o BatchMode=yes raspberry@192.168.0.13 'ss -tuln | grep -E ":5000|:5001"; head -8 /tmp/srv.log'
```

### 2. Agente en la Pi (NODO_02 → aparece con IP 192.168.0.13)

```bash
timeout 10 ssh -o BatchMode=yes raspberry@192.168.0.13 'cd ~/monitoreo_equipos && setsid python3 -u agent/agent.py NODO_02 192.168.0.13 5000 5002 </dev/null >/tmp/agent2.log 2>&1 & echo lanzado'
```

### 3. Agente en la notebook (NODO_01 → aparece con IP 192.168.0.8)

Desde la raíz del repo local (`/home/alejandro/Documentos/workspace/redes`):

```bash
nohup setsid python3 -u agent/agent.py NODO_01 192.168.0.13 5000 5002 >/tmp/sdmr_agent1.log 2>&1 &
```

### 4. Gateway WS + web — en la notebook (para el cliente web)

```bash
nohup setsid python3 -u server/gateway.py 5003 192.168.0.13 5001 --serve-web >/tmp/sdmr_gw.log 2>&1 &
```

Esto sirve la web en `http://localhost:5173` y puentea WS `:5003` → TCP de la Pi `:5001`.
La web (login) autocompleta el gateway según el host de la página: abriéndola en
`localhost:5173` queda `ws://127.0.0.1:5003`, que pega al gateway local. Usuario
`admin` / `admin123`.

### Verificación de red (desde la notebook)

```bash
python3 tools/verificar_red.py 192.168.0.13 5000 5001
```

Esperar **TCP OK + UDP OK**. El WS `:5003` solo da OK si el gateway está levantado
(opcional, solo para web/móvil). Chequeo rápido de nodos registrados:

```bash
python3 - <<'PY'
import socket
s=socket.create_connection(('192.168.0.13',5001),timeout=4)
for c in (b'CMD|AUTH|admin|admin123\n', b'CMD|GET_NODES|ALL\n'):
    s.sendall(c); b=b''; s.settimeout(4)
    while b'\n' not in b: b+=s.recv(4096)
    print(b.decode().strip())
s.close()
PY
```

Debe listar `NODES_COUNT:2;NODO_01:192.168.0.8:...;NODO_02:192.168.0.13:...`.

---

## ⏹️ Apagar TODO

```bash
# Notebook
pkill -f "[a]gent/agent.py"; pkill -f "[g]ateway.py"
# Pi (servidor + agente)
ssh -o BatchMode=yes raspberry@192.168.0.13 'pkill -f "[s]erver/server.py"; pkill -f "[a]gent/agent.py"'
```

Verificar que no quedan puertos ni procesos:

```bash
ss -tuln | grep -E ":5002|:5003|:5173" || echo "notebook limpia"
ssh -o BatchMode=yes raspberry@192.168.0.13 'ss -tuln | grep -E ":5000|:5001" || echo "Pi limpia"'
```

---

## 🧭 Notas operativas

- El servidor desacoplado con `setsid` **sobrevive a cerrar el SSH, pero NO a un reboot
  de la Pi**. Tras reiniciar, relanzá el paso 1.
- Para **ver la consola del servidor** (útil en el video): `ssh raspberry@192.168.0.13 'tail -f /tmp/srv.log'`.
- **EXEC** (server→agente) abre un TCP del servidor (Pi) hacia el `cmd_port` del agente
  (`5002`). Si un agente corre en la notebook, la notebook debe aceptar entrantes en
  `5002`; si hay `ufw` activo, abrir ese puerto.
- La IP que viaja en la trama se descarta: el servidor usa la IP de origen real, por eso
  los nodos aparecen con la IP del equipo donde corre cada agente.
- Puertos del stack: UDP 5000 (telemetría), TCP 5001 (comandos), TCP 5002 (EXEC por
  agente), TCP 5003 (gateway WS), HTTP 5173 (web).
