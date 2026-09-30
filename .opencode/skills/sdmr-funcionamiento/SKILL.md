---
name: sdmr-funcionamiento
description: Explica cómo se ejecuta el programa SDMR en tiempo de ejecución - arranque, hilos, recorrido de un dato UDP y TCP, máquina de estados de nodos y sesiones, tabla de errores y qué falla de verdad. Úsala para entender qué hace el código paso a paso, para depurar por qué un nodo aparece OFFLINE o una trama se pierde, para preparar la defensa oral, o cuando se pregunte cómo funciona, qué pasa al ejecutar, cuándo se marca OFFLINE, por qué hay dos puertos, qué significa cada ERR_.
---

# SDMR — Cómo funciona en tiempo de ejecución

Skill de **comprensión**: qué ocurre, en qué orden y por qué. Para las
convenciones de código, los bugs a no reintroducir y la higiene del repo ver la
skill hermana `sdmr-monitoreo`.

---

## 1. El reparto del trabajo

Un solo protocolo de aplicación, `NETMON/1.0`, sobre **dos transportes**. Eso
es la decisión de diseño central y todo lo demás se deriva de ahí.

| Componente | Transporte | Puerto | Hilo | Responsabilidad |
| :--- | :--- | :--- | :--- | :--- |
| `server/server.py` | UDP | 5000 | 1 | Recibir telemetría y llenar el registro |
| `server/server.py` | TCP | 5001 | 1 (principal) | Aceptar clientes y lanzar un hilo por cada uno |
| `server/server.py` | — | — | 1 | Watchdog: marcar `OFFLINE` |
| `agent/agent.py` | UDP | — | 1 (proceso) | Medir y emitir cada 3 s |
| `client/admin_client.py` | TCP | — | 1 (proceso) | CLI, un comando por vez |
| `client/gui_monitor.py` | TCP | — | 1 + N hilos de E/S | Dashboard y demo auto-contenida |

El servidor queda **con cuatro hilos vivos**: UDP, watchdog, accept, y uno por
cliente TCP conectado.

---

## 2. Arranque, en orden exacto

`MonitoringServer.start()` (`server.py:82`) hace esto y en este orden:

1. `is_running = True`.
2. Imprime el banner.
3. **Crea y abre el socket UDP**, con `SO_REUSEADDR`, y hace `bind`. Ya puede
   recibir telemetría aunque el TCP todavía no exista.
4. Lanza el **hilo UDP** (`daemon=True`).
5. Lanza el **hilo watchdog** (`daemon=True`).
6. Solo ahora crea el socket TCP, `bind`, y `listen(5)` — el 5 es el backlog.
7. Entra al **bucle de `accept()`** en el hilo principal, que se queda ahí
   bloqueado para siempre.

Ese orden importa: el puerto UDP queda disponible antes que el TCP. Durante los
tests se lanzan los agentes justo después del servidor, así que este detalle
evita que la primera telemetría se pierda.

`stop()` invierte todo: `is_running = False` y cierra ambos sockets. Como los
hilos son *daemon*, el proceso muere solo aunque alguno esté bloqueado en
`recvfrom()` o `accept()`.

---

## 3. El recorrido de un dato, paso a paso

### 3.1 El agente mide y lanza

Cada `interval` segundos (`agent.py:100`):

1. `get_system_metrics()`. Con `psutil`: `cpu_percent(interval=None)`,
   `virtual_memory().percent`, `disk_usage('/').percent`. Sin `psutil`: valores
   aleatorios en rangos fijos.
2. Decide el estado: `WARNING` si `cpu > 80` **o** `ram > 85`; si no, `OK`.
   **El disco no participa del umbral.**
3. Arma la trama y hace `sendto()`.

Sobre el cable, literalmente:

```
MON|NODO_01|192.168.1.5|35.4|62.1|40.0|OK\n
```

Puntos que conviene tener claros:

- El socket del agente **nunca se conecta** con `connect()`. Usa `sendto()` con
  la dirección destino en cada llamada. Por eso UDP no reintenta ni se entera.
- El agente **no envía timestamp**. El que se guarda es el del servidor, tomado
  al recibir. Así un agente con reloj desfasado no rompe el watchdog.
- El campo `<IP>` que viaja en la trama **se descarta**: el servidor lo pisa con
  la dirección fuente real del datagrama (`server.py:151`). El `ip` que se ve en
  la tabla es el del `recvfrom()`, no el que el agente trenza.
- `cpu_percent(interval=None)` mide el uso **desde la llamada anterior**, así que
  la primera lectura de un agente recién arrancado da `0.0`.

### 3.2 El servidor recibe, valida y guarda

En el hilo UDP (`server.py:132`):

1. `recvfrom(BUFFER_SIZE)` — bloqueante. Devuelve bytes y `(ip, puerto)`.
2. `parse_udp_telemetry()` (`protocol.py:89`) valida:
   - que la cabecera sea `MON` y haya al menos 7 campos;
   - que CPU, RAM y disco parseen como `float`;
   - que los tres estén en `[0, 100]`.
   Si algo falla lanza `ValueError`, que se captura y se loguea. **El hilo
   sigue vivo.** Ese es el requisito RF07.
3. Con `registry_lock` tomado, escribe la entrada completa del nodo.
4. Imprime una línea por paquete recibido.

### 3.3 El watchdog vigila

Hilo independiente, `time.sleep(5)` por vuelta (`server.py:176`):

```python
elapsed = now - data["last_seen"]
if elapsed > 15 and data["status"] != "OFFLINE":
    data["status"] = "OFFLINE"
```

**Matemática de la detección:** el chequeo corre cada 5 s y el umbral es 15 s,
así que un nodo muerto aparece `OFFLINE` entre **15 y 20 segundos** después de
su último paquete. Con el agente cada 3 s, hay margen de sobra para 4-5
paquetes perdidos seguidos sin falsos positivos.

El `!= "OFFLINE"` evita reimprimir la alerta cada 5 segundos. Y como el paso 3.2
reescribe la entrada entera cuando vuelve la telemetría, **la recuperación es
automática y sin handshake**: el nodo pasa de `OFFLINE` a `OK` solo porque llegó
un paquete.

### 3.4 El cliente pregunta por TCP

Conexión dedicada, con hilo propio. El ciclo por comando es siempre el mismo:
`build_tcp_command()` → `encode_message()` (agrega `\n`) → `sendall()` →
lectura → `parse_tcp_response()`.

La respuesta de `GET_NODES` trae **todo el estado en un solo campo**:

```
RES|OK|NODES_COUNT:2;NODO_01:192.168.1.5:OK:CPU=35.4:RAM=62.1:DISK=40.0;NODO_02:...|Lista de nodos obtenida
 └─┬─┘ └┬┘ └──────────────── campo 2: payload ────────────────────────┘ └── campo 3: detalle
```

Ojo: aquí los separadores son `;` entre nodos y `:` entre campos, **no** `|`,
porque `|` ya está separando los campos de la respuesta. Mezclarlos rompe el
parseo. Es la discrepancia número uno con `propuesta.md:101`, que sí documenta
`|` y además promete un `<TOKEN>` que el código nunca emite.

`GET_NODES` **ignora su parámetro**: mandes lo que mandes tras `GET_NODES`, el
parámetro se descarta. El `ALL` del README es decorativo.

---

## 4. Máquina de estados de un nodo

```
                    primer datagrama
                          │
                          ▼
                    ┌──────────┐
        +──────────►│ REGISTERD│  (implicitado: nace en el registro)
        │           └────┬─────┘
        │                │ el agente fija el estado
        │     ┌──────────┴──────────┐
        │     ▼                     ▼
   vuelve a     │                ┌──────────┐
   enviar   ┌───┴────┐           │ WARNING  │  cpu>80 o ram>85
   telemetría│   OK   │◄──────────┤          │
        │   └────────┘  baja de    └────┬─────┘
        │        │        umbrales      │
        │        │ 15 s sin paquetes     │
        │        ▼                      │
        │   ┌───────────┐               │
        └────┤  OFFLINE  │───────────────┘
            └───────────┘   llega un paquete nuevo
```

- `OK` y `WARNING` los decide **el agente**, no el servidor. El servidor solo
  añade `OFFLINE`.
- El watchdog **no borra** nodos. El registro crece sin límite durante la
  ejecución; en un TP de minutos no se nota.

---

## 5. Máquina de estados de una sesión TCP

```
  accept()
     │
     ▼
  CONECTADO ──(CMD|AUTH incorrecto)──► CONECTADO   (ERR_101, se puede reintentar)
     │
     ├─(CMD|AUTH correcto)──► AUTENTICADO
     │                            │
     │        ┌───────────────────┼───────────────────┐
     │        ▼                   ▼                   ▼
     │   GET_NODES            EXEC válido        EXEC inválido
     │        │                   │                   │
     ▼        ▼                   ▼                   ▼
   (PING es válido en cualquier estado: responde PONG sin pedir sesión)
```

- `PING` y `AUTH` se evalúan **antes** de la comprobación de autenticación;
  todo lo demás pasa por el filtro de `server.py:290`.
- El flag de sesión vive **en el hilo del cliente**, no en el servidor. Cada
  conexión tiene su propia `is_authenticated`. No hay estado compartido, así
  que dos administradores no se pisan.
- Cerrar el socket (recv devuelve `b""`) termina el hilo y libera los recursos
  en el `finally`.

---

## 6. Matriz completa de errores

Comportamiento real, verificado. **Ningún error cierra la conexión TCP.**

| Trama enviada | Respuesta | Sobrevive |
| :--- | :--- | :--- |
| `CMD\|PING` | `RES\|OK\|PONG\|Servidor activo y escuchando` | sí |
| `CMD\|AUTH` (sin parámetros) | `ERR_100` Uso correcto: `CMD\|AUTH\|<usuario>\|<password>` | sí |
| `CMD\|AUTH\|admin\|mal` | `ERR_101` Usuario o contraseña incorrectos | sí |
| `CMD\|GET_NODES\|ALL` sin sesión | `ERR_101` Debe autenticarse primero | sí |
| `CMD\|GET_NODES\|ALL` sin nodos | `OK` `NODES_COUNT:0` | sí |
| `CMD\|EXEC` (sin parámetros) | `ERR_100` Uso correcto: `CMD\|EXEC\|<ID>\|<CMD>` | sí |
| `CMD\|EXEC\|NODO_99\|X` | `ERR_102` no está registrado | sí |
| `CMD\|EXEC\|<offline>\|X` | `ERR_102` se encuentra OFFLINE | sí |
| `CMD\|EXEC\|NODO_01\|X` | `OK` `EXEC_SUCCESS` ← **miente, no ejecuta nada** | sí |
| `CMD\|CUALQUIER_COSA` | `ERR_103` no reconocido por NETMON/1.0 | sí |
| `DATOS_BASURA_SIN_CMD` | `ERR_100` debe iniciar con la cabecera `CMD` | sí |
| `RES\|OK\|...` por TCP | `ERR_100` misma causa, cabecera incorrecta | sí |
| `MON\|...` enviado por TCP | `ERR_100` no empieza con `CMD` | sí |

Lado UDP — todo se descarta en silencio, solo un print:

| Datagrama | Resultado |
| :--- | :--- |
| `MON\|NODO_01\|1.2.3.4\|35.4\|62.1\|40.0\|OK` | aceptado |
| `MON\|NODO_01\|1.2.3.4\|150\|62\|40\|OK` | descartado: fuera de `[0,100]` |
| `MON\|NODO_01\|1.2.3.4\|abc\|62\|40\|OK` | descartado: no es float |
| `MON\|NODO_01` | descartado: menos de 7 campos |
| `HOLA\|...` | descartado: cabecera incorrecta |
| `MON\|\|1.2.3.4\|1\|1\|1\|OK` | **aceptado con id vacío** — hueco de validación |

`ERR_500` está definido en `protocol.py:50` pero **ningún camino lo emite**.

---

## 7. Por qué dos transportes

La justificación es sobre **qué se pierde por el camino**:

- *Telemetría UDP:* si un paquete se pierde, el siguiente llega 3 s después con
  un dato más fresco. Retransmitir el viejo es trabajo desperdiciado, y la
  cabecera de TCP (20 bytes) es del orden de la trama completa.
- *Control TCP:* un `RESTART` o un log de auditoría no puede perderse ni llegar
  a medias. Necesita handshake, retransmisión y orden.

Se sostiene en la discusión. Decir "porque UDP es más rápido" es incorrecto: la
ventaja no es de velocidad, es que **el dato caduca**.

---

## 8. La línea de tiempo de la demo

Lo que alguien ve si pulsa *Iniciar Demo* en la GUI:

| t | Suceso |
| --- | :--- |
| 0.0 s | Se lanza `server.py` con `-u`. Abre UDP 5000 y luego TCP 5001. |
| 0.0 s | Thread UDP, thread watchdog, y el hilo principal entra en `accept()`. |
| 1.0 s | El servidor ya está listo. Se lanzan los 3 agentes. |
| 1.0 s | Cada agente mide y hace su primer `sendto()`. El hilo UDP lo recibe y lo guarda. |
| 1.0 s | El watchdog ya corre; `last_seen` acaba de crearse, no hay alerta. |
| ~2.2 s | La GUI se autoconecta: TCP handshake, `PING` → `PONG`, `AUTH` → sesión. |
| ~2.2 s | Primer `GET_NODES`: la tabla se llena con 3 filas. |
| 3.0 s | Segundo paquete de cada agente. Las barras se mueven. |
| cada 3 s | Se repite indefinidamente mientras la demo siga viva. |
| cada 5 s | El watchdog revisa; nadie pasa de 15 s, nadie se marca `OFFLINE`. |
| cada 2 s | La GUI repinta la tabla con `after()`. |

Si se detiene un agente, la realidad es esta: el watchdog lo ve entre 15 y 20 s
después del último paquete. La fila se pone roja sola, sin que nadie la toque.

---

## 9. Dónde el comportamiento real se aparta de la documentación

Tres cosas que conviene decir antes de que las pregunten:

1. **`EXEC` es un stub.** `server.py:323` devuelve `EXEC_SUCCESS` sin ejecutar
   nada. El agente **no tiene socket TCP**: no hay forma de que el comando
   llegue. `propuesta.md:69` sí lo exige.
2. **No hay alertas push al administrador.** `propuesta.md:15` promete
   "recepción de alertas críticas" por TCP. El watchdog solo imprime en la
   consola del servidor; no notifica a nadie. Un cliente conectado nunca se
   entera de que un nodo cayó.
3. **El servidor no encuadra tramas.** `server.py:227` hace un solo `recv()` y
   asume que llegó exactamente un mensaje. Consecuencia medida: enviar
   `CMD|PING\nCMD|GET_NODES|ALL` en un mismo `send()` produce
   `ERR_103|Comando 'PING\nCMD' no reconocido`. Peor: como la respuesta de error
   *hereda* ese salto de línea, el cliente puede leer una respuesta partida como
   si fueran dos.

Lo que sí funciona y es defendible: concurrencia multi-hilo, exclusión mutua del
registro, detección de inactividad, validación estricta de entrada, y la
tolerancia a errores sin colapso (RF07).

---

## 10. Para la defensa oral

Preguntas que casi seguro llegan, con la respuesta corta:

- **"¿Por qué UDP para la telemetría?"** → Porque el dato caduca; la siguiente
  muestra llega en 3 s y retransmitir la anterior es inútil. TCP se reserva
  para lo que no puede perderse.
- **"¿Cómo evitan condiciones de carrera?"** → `threading.Lock` en
  `nodes_registry`. Toda escritura pasa por la sección crítica. No es decorativo.
- **"¿Qué pasa si un agente se apaga?"** → El watchdog lo marca `OFFLINE` entre
  15 y 20 s. Se recupera solo al volver a recibir un paquete, sin handshake.
- **"¿Y si mandan basura?"** → El protocolo la rechaza con un error tipificado y
  la conexión sigue abierta. Eso es RF07, y está en la matriz de la §6.
- **"¿Qué pasa si mandan dos comandos juntos?"** → Ahí hay que ser honesto: el
  servidor no lo tolera, es el bug de §9.3. La GUI sí lo hace bien con un búfer
  acumulador.
