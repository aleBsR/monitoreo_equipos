---
name: sdmr-demo-video
description: Guion/runbook MANUAL para correr y demostrar el SDMR desde la Raspberry Pi al grabar el video del TPI (parte 2 de Alejandro). Paso a paso en terminales visibles, en qué orden mostrar cada cosa (inicio del servidor en la Pi, agentes reportando, cliente, varios clientes, un error, equipo caído/watchdog, EXEC y Wireshark), qué decir y qué filtros usar, y qué capturas completan las secciones pendientes del informe. Úsala cuando se hable de grabar/ensayar el video, la demo, la defensa, "cómo lo corro a mano", "qué muestro y en qué orden", o las capturas de Wireshark pendientes. Para levantar el stack rápido (comandos de arranque/parada y conexión a la Pi) ver [[sdmr-raspberry]]; para el detalle del protocolo ver [[sdmr-contexto]].
---

# Demo del SDMR desde la Raspberry — runbook manual para el video

Este es el **paso a paso que hace Alejandro a mano** para la parte 2 del video, con el
**servidor en la Raspberry Pi** (`192.168.0.13`) y los **agentes + cliente en la
notebook** (`192.168.0.8`). Da el escenario de red real (dos IP) que la cátedra pide.

- Arranque rápido/automatizable, conexión y gotchas: ver [[sdmr-raspberry]].
- El guion narrado (qué decir, tiempos, pase entre partes) está en el documento
  **«Guion del video – TPI SDMR»**; esta skill es la **choreografía de comandos** que lo
  acompaña.

> Importante: en el video la cátedra quiere ver **interacción en vivo**, no el script de
> pruebas. `tools/test_system.py` es evidencia para el informe (22/22), no para grabar.

---

## 0. Antes de grabar (checklist)

- [ ] Pi encendida y en la LAN. Confirmar IP y SSH (ver [[sdmr-raspberry]] → "Si la Pi
      tiene otra IP").
- [ ] En la notebook, terminales ordenadas en mosaico (tmux o ventanas), letra 16–18 pt.
- [ ] Wireshark instalado en la notebook, capturando en la **interfaz Wi-Fi/LAN**
      (`wlp2s0`), **no** en loopback.
- [ ] Firewall: en la Pi UDP 5000 y TCP 5001; en la notebook TCP 5002 (para que el
      EXEC del servidor llegue al agente).
- [ ] Ensayar con cronómetro: parte 2 ≈ 5 min 30 s.

---

## 🎥 OBS Studio — escenas para grabar

OBS está instalado como **Flatpak**. Abrir: menú de apps → "OBS Studio", o
`flatpak run com.obsproject.Studio`. Primera vez: Asistente → **"Optimizar solo
para grabar, no voy a transmitir"**; base **1920×1080**, **30 FPS**. En
Ajustes → Salida, formato de grabación **MKV** (y "Remuxar a MP4" al final: si OBS
se cierra mal, el MKV no se corrompe). Sesión **X11** → la captura va directa.

Con solo **2 escenas** cubrís toda la parte 2:

**Escena "Cámara"** (Entrada 4:05 y Cierre 8:50)
- Fuente: *Dispositivo de captura de video (V4L2)* → la webcam, escalada a pantalla
  completa.

**Escena "Pantalla + cara"** (Demo 4:20 y Wireshark 7:35)
- Fuente 1: *Captura de pantalla (XSHM)* → el monitor, pantalla completa.
- Fuente 2: *Dispositivo de captura de video (V4L2)* → la webcam, achicada a una
  esquina (abajo-derecha), así se te ve la cara mientras narrás.
- El micrófono se captura global (mezclador), no hace falta ponerlo por escena.

La **misma** escena "Pantalla + cara" sirve para la demo y para Wireshark: solo
cambiás qué ventana está al frente (terminales, luego Wireshark).

**Audio:** en el mezclador dejá activo **Mic/Aux** y silenciá "Audio del escritorio"
si no querés el sonido del sistema. Hablá y que el medidor quede en verde/amarillo,
nunca rojo. Prueba de 10 s antes.

**Grabar:** botón "Iniciar grabación" (NO "Iniciar transmisión"). Cambiás de escena
con un clic, o asignás atajos en Ajustes → Atajos. Grabá por bloques: si algo sale
mal, repetís solo ese tramo.

**Mapa escena ↔ guion (parte 2):**
| Tiempo | Bloque | Escena |
| --- | --- | --- |
| 4:05 | Entrada | Cámara |
| 4:20 | Demo (terminales T1–T4) | Pantalla + cara |
| 7:35 | Wireshark | Pantalla + cara (Wireshark al frente) |
| 8:50 | Cierre | Cámara |

> Preparar antes de grabar: terminales ya ubicadas y con los comandos tipeados
> (ver §1), Wireshark capturando con el filtro puesto, y los `.pcapng` del informe
> abiertos si preferís mostrarlos ya cargados.

---

## 1. Choreografía de terminales (en vivo)

Cada paso en su terminal, con el comando ya tipeado para apretar Enter en cámara.

**T1 — Servidor (en la Pi, por SSH, consola visible):**
```bash
ssh raspberry@192.168.0.13
cd ~/monitoreo_equipos
python3 server/server.py 5000 5001 120
```
Decí: «Abre el socket UDP 5000 y el TCP 5001, escuchando en todas las interfaces.»
Dejá esta consola a la vista: van a llegar los reportes UDP de los dos nodos.

**T2 — Agente en la Pi (NODO_02, otra pestaña SSH):**
```bash
cd ~/monitoreo_equipos
python3 agent/agent.py NODO_02 192.168.0.13 5000 5002
```

**T3 — Agente en la notebook (NODO_01):**
```bash
python3 agent/agent.py NODO_01 192.168.0.13 5000 5002
```
Decí: «En la consola del servidor llegan los reportes UDP de los dos nodos cada 3
segundos, cada uno con su IP: 192.168.0.13 y 192.168.0.8.»

**T4 — Cliente admin (notebook):**
```bash
python3 client/admin_client.py 192.168.0.13 5001
```

---

## 2. Qué mostrar y en qué orden (mapea al guion, parte 2)

1. **PING** (opción 1): el servidor responde `PONG`. «Me conecto por TCP.»
2. **Sin sesión** (opción 3 GET_NODES): `ERR_101`. Luego **AUTH con clave mala** →
   `ERR_101`, y **AUTH `admin`/`admin123`** → `AUTH_SUCCESS`.
3. **GET_NODES** (opción 3): se ven los **dos nodos con IP, estado y métricas**.
4. **EXEC real** (opción 4): `DIAGNOSTIC` sobre `NODO_01` → `EXEC_SUCCESS`. Mostrá la
   consola del agente o `agent/historial_comandos.log`. Repetí con un comando fuera de
   la lista blanca (p. ej. `FORMATEAR_DISCO`) → `ERR_104`.
5. **Varios clientes**: abrí 2 clientes más, login y GET_NODES en cada uno. «Tres
   conexiones, cada una desde un puerto distinto y su propio hilo: se atienden a la vez.»
6. **Datos inválidos** (opción 5): el servidor responde `ERR_100`/`ERR_103` **sin cortar
   la conexión** (RF07).
7. **Desconexión**: cerrás de golpe un cliente; el servidor libera ese hilo y sigue.
   Hacé un PING en otro cliente para mostrar que sigue vivo.
8. **Equipo caído / watchdog**: cortá `NODO_02` con Ctrl+C. Mientras pasan 15–20 s
   explicá el watchdog; después GET_NODES muestra `NODO_02 OFFLINE`.

### Alternativa: mostrarlo por la web (opcional, lindo pero no reemplaza lo de arriba)
Levantá el gateway + web (ver [[sdmr-raspberry]] paso 4), abrí `http://localhost:5173`,
login `admin`/`admin123`, y recorré Feed → Nodos (EXEC) → Tráfico (tramas en vivo y una
acción desconocida para `ERR_103`). La web habla por **WebSocket (:5003)**, así que
**no sirve para las capturas de Wireshark** del protocolo crudo (eso va por T1–T4).

---

## 3. Wireshark (parte 2, 7:35–8:50) — y capturas para el informe

Capturar en `wlp2s0` con el filtro:
```
udp.port == 5000 || tcp.port == 5001 || tcp.port == 5002
```

| Qué mostrar | Cómo | Completa en el informe |
| --- | --- | --- |
| **UDP telemetría** | `udp.port == 5000`. Abrí un `MON`: sin handshake, 1 cada 3 s, payload en texto plano, cabecera UDP 8 bytes. | §15.1 y **Tabla 9** (carga útil observada) |
| **TCP un cliente** | `tcp.port == 5001`, clic derecho → Follow → TCP Stream. SYN/SYN-ACK/ACK, PSH de `CMD`/`RES`, FIN. | §15.2 y **Tabla 10** (seq/ack de los segmentos) |
| **Seguridad** | Señalá `CMD|AUTH|admin|admin123` en claro. | §13 (riesgo credenciales) |
| **Varios clientes** | Statistics → Conversations → TCP: 3 conexiones al 5001, distinto puerto origen. | §15.3 |
| **EXEC** | `tcp.port == 5002`: el servidor abre TCP nuevo, `EXECCMD|DIAGNOSTIC`, respuesta, cierre. | §15.4 |
| **Mediciones TCP/UDP** | Contar paquetes/bytes de 10 `MON` vs 10 PING; tiempo hasta primer dato; con 30 % de pérdida (`sudo tc qdisc add dev wlp2s0 root netem loss 30%`). | **Tabla 12** |

Guardá cada captura como **`.pcapng`** para el Anexo C. Las **Tabla 8** (equipos/IPs) y
las celdas deterministas de la **Tabla 9** ya quedaron cargadas en el informe; faltan
las de captura (9 carga útil, 10, 12) y las pantallas de Wireshark (Tabla 7 filas 6–7).

> Tip: si querés, pasá el `.pcapng` y se leen los números exactos (bytes, seq/ack,
> conteos) para completar esas tablas sin tipear a mano.

---

## 4. Cierre
«UDP para la telemetría liviana y frecuente; TCP para lo que no se puede perder. Lo que
más aprendimos: TCP es un flujo de bytes y separar los mensajes es tarea nuestra. Como
mejoras quedan TLS y autenticar la telemetría.»

Al terminar, **apagá todo** (ver [[sdmr-raspberry]] → "Apagar TODO") para liberar puertos.
