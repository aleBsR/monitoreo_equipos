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
| `server/server.py` | — | — | 1 | Watchdog: marcar `OFFLINE` y purgar |
| `agent/agent.py` | UDP | — | 1 (proceso) | Medir y emitir cada 3 s |
| `agent/agent.py` | TCP | 5002+ | 1 | Escuchar `EXECCMD` y ejecutar la orden |
| `client/admin_client.py` | TCP | — | 1 (proceso) | CLI, un comando por vez |
| `client/gui_monitor.py` | TCP | — | 1 + N hilos de E/S | Dashboard y demo auto-contenida |

El servidor queda **con cuatro hilos vivos**: UDP, watchdog, accept, y uno por
cliente TCP conectado. Cada agente suma un hilo más para su canal TCP de
comandos.

---

## 2. Arranque, en orden exacto

`MonitoringServer.start()` (`server.py`) hace esto y en este orden:

1. `is_running = True`.
2. Imprime el banner.
3. **Crea y abre el socket UDP**, con `SO_REUSEADDR`, y hace `bind` (vía
   `_asociar_socket`). Si el puerto está ocupado (`EADDRINUSE`), imprime un
   mensaje claro y sale con código 1. Ya puede recibir telemetría aunque el TCP
   todavía no exista.
4. Lanza el **hilo UDP** (`daemon=True`).
5. Lanza el **hilo watchdog** (`daemon=True`).
6. Solo ahora crea el socket TCP, `bind`, y `listen(5)` — el 5 es el backlog,
   también con la comprobación de puerto ocupado.
7. Entra al **bucle de `accept()`** en el hilo principal, que se queda ahí
   bloqueado para siempre.

Ese orden importa: el puerto UDP queda disponible antes que el TCP. Durante los
tests se lanzan los agentes justo después del servidor, así que este detalle
evita que la primera telemetría se pierda. Los `bind` se hacen **antes** de
lanzar los hilos para que un puerto ocupado falle limpio y no con un hilo a
medio arrancar.

Argumentos del servidor: `[udp_port] [tcp_port] [segundos_purga_offline]`.

`stop()` invierte todo: `is_running = False` y cierra ambos sockets. Como los
hilos son *daemon*, el proceso muere solo aunque alguno esté bloqueado en
`recvfrom()` o `accept()`.

---

## 3. El recorrido de un dato, paso a paso

### 3.1 El agente mide y lanza

Cada `interval` segundos (`agent.py`):

1. `get_system_metrics()`. Con `psutil`: `cpu_percent(interval=None)`,
   `virtual_memory().percent`, `disk_usage('/').percent`. Sin `psutil`: valores
   aleatorios en rangos fijos.
2. Decide el estado: `WARNING` si `cpu > 80` **o** `ram > 85`; si no, `OK`.
   **El disco no participa del umbral.**
3. Arma la trama y hace `sendto()`.

Sobre el cable, literalmente:

```
MON|NODO_01|192.168.1.5|35.4|62.1|40.0|OK|5002\n
```

El último campo (`5002`) es el `PUERTO_CMD`: el puerto TCP donde ese agente
escucha órdenes `EXEC`. Es **opcional** en el protocolo (el parseo acepta 7 u 8
campos) pero el agente actual siempre lo envía si logró abrir su canal.

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

En el hilo UDP (`server.py`):

1. `recvfrom(BUFFER_SIZE)` — bloqueante. Devuelve bytes y `(ip, puerto)`.
2. `parse_udp_telemetry()` (`protocol.py`) valida:
   - que la cabecera sea `MON` y haya al menos 7 campos (7 **u** 8);
   - que CPU, RAM y disco parseen como `float`;
   - que los tres estén en `[0, 100]`;
   - si viene el 8º campo, que sea un puerto válido (`1..65535`).
   Si algo falla lanza `ValueError`, que se captura y se loguea. **El hilo
   sigue vivo.** Ese es el requisito RF07.
3. Con `registry_lock` tomado, escribe la entrada completa del nodo, incluido
   `cmd_port`.
4. Imprime una línea por paquete recibido.

### 3.3 El watchdog vigila y purga

Hilo independiente, `time.sleep(5)` por vuelta (`server.py`):

```python
elapsed = now - data["last_seen"]
if elapsed > 15 and data["status"] != "OFFLINE":
    data["status"] = "OFFLINE"
if elapsed > offline_purge_seconds:   # 120 s por defecto
    del nodes_registry[node_id]        # purga
```

**Matemática de la detección:** el chequeo corre cada 5 s y el umbral es 15 s,
así que un nodo muerto aparece `OFFLINE` entre **15 y 20 segundos** después de
su último paquete. Con el agente cada 3 s, hay margen de sobra para 4-5
paquetes perdidos seguidos sin falsos positivos.

El `!= "OFFLINE"` evita reimprimir la alerta cada 5 segundos. Y como el paso 3.2
reescribe la entrada entera cuando vuelve la telemetría, **la recuperación es
automática y sin handshake**: el nodo pasa de `OFFLINE` a `OK` solo porque llegó
un paquete. Si el nodo estuvo caído más de `offline_purge_seconds`, se borra del
registro y al volver reaparece como entrada nueva.

### 3.4 El cliente pregunta por TCP

Conexión dedicada, con hilo propio. El ciclo por comando es siempre el mismo:
`build_tcp_command()` → `encode_message()` (agrega `\n`) → `sendall()` →
lectura con `TcpFrameReader` → `parse_tcp_response()`.

`TcpFrameReader` acumula bytes hasta encontrar `\n`, así que una trama partida en
varios segmentos o dos tramas pegadas en uno solo se separan bien. Tiene tope de
8 KB: si el buffer crece más sin ver un `\n`, descarta y responde `ERR_100`.
El mismo acumulador lo usan servidor, cliente y agente.

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

### 3.5 El recorrido de un EXEC (extremo a extremo)

Es el único comando que sale del servidor hacia otro proceso. Cadena completa
cuando el admin manda `CMD|EXEC|NODO_01|DIAGNOSTIC`:

1. El servidor busca `NODO_01` en `nodes_registry`. Si no existe o está
   `OFFLINE` → `ERR_102`.
2. Toma el `cmd_port` guardado de ese nodo. Si el nodo nunca reportó un puerto
   de comandos → `ERR_104`.
3. Abre una conexión TCP **nueva** al `(ip, cmd_port)` del agente, con timeout de
   3 s (`_ejecutar_en_nodo`). Si no conecta → `ERR_104`.
4. Envía `EXECCMD|<COMANDO>` y espera la respuesta con `TcpFrameReader`.
5. El agente (`agent.py`, canal TCP) valida el comando contra
   `COMANDOS_PERMITIDOS = {RESTART_SERVICE, DIAGNOSTIC, CLEAR_LOGS}`, lo ejecuta
   (simulado, con resultado textual), lo registra en
   `agent/historial_comandos.log` y responde `RES|OK|<COMANDO>|<resultado>`.
   Un comando fuera de la lista se rechaza.
6. El servidor reenvía al admin `RES|OK|EXEC_SUCCESS|<resultado del agente>`.

Ojo con el diseño: **cada EXEC abre y cierra su propio socket TCP** hacia el
agente. No hay canal persistente servidor→agente; el agente atiende una orden
por conexión.

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
                  │
                  └── si pasa > offline_purge_seconds
                       del último last_seen, se BORRA
```

- `OK` y `WARNING` los decide **el agente**, no el servidor. El servidor solo
  añade `OFFLINE` y, tras `offline_purge_seconds` (120 s por defecto), lo **purga**.
- Un nodo purgado deja de aparecer en `GET_NODES`. Si vuelve a enviar un paquete,
  reaparece con los campos completos (incluido `cmd_port`) como una nueva
  entrada.

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
| `CMD\|EXEC\|NODO_01\|DIAGNOSTIC` | `OK` `EXEC_SUCCESS\|[NODO_01] Resultado: ...` | sí |
| `CMD\|EXEC\|NODO_01\|COMANDO_INEXISTENTE` | `ERR_104` Comando no permitido / no soportado | sí |
| `CMD\|EXEC\|NODO_01\|X` (sin canal) | `ERR_104` No se pudo ejecutar en el nodo | sí |
| `CMD\|CUALQUIER_COSA` | `ERR_103` no reconocido por NETMON/1.0 | sí |
| `DATOS_BASURA_SIN_CMD` | `ERR_100` debe iniciar con la cabecera `CMD` | sí |
| `RES\|OK\|...` por TCP | `ERR_100` misma causa, cabecera incorrecta | sí |
| `MON\|...` enviado por TCP | `ERR_100` no empieza con `CMD` | sí |

Lado UDP — todo se descarta en silencio, solo un print:

| Datagrama | Resultado |
| :--- | :--- |
| `MON\|NODO_01\|1.2.3.4\|35.4\|62.1\|40.0\|OK` (7 campos) | aceptado, `cmd_port` queda `None` |
| `MON\|NODO_01\|1.2.3.4\|35.4\|62.1\|40.0\|OK\|5002` (8 campos) | aceptado con el puerto de comandos |
| `MON\|NODO_01\|1.2.3.4\|35.4\|62.1\|40.0\|OK\|99999` | descartado: puerto fuera de rango |
| `MON\|NODO_01\|1.2.3.4\|150\|62\|40\|OK` | descartado: fuera de `[0,100]` |
| `MON\|NODO_01\|1.2.3.4\|abc\|62\|40\|OK` | descartado: no es float |
| `MON\|NODO_01` | descartado: menos de 7 campos |
| `HOLA\|...` | descartado: cabecera incorrecta |
| `MON\|\|1.2.3.4\|1\|1\|1\|OK` | **aceptado con id vacío** — hueco de validación |

Framing TCP — el acumulador (`TcpFrameReader`) hace la separación:

| Situación | Resultado |
| :--- | :--- |
| `CMD\|PING` y `CMD\|GET_NODES\|ALL` en un solo `send()` | dos respuestas correctas, separadas |
| `CMD\|GET_` en un paquete y `NODES\|ALL` en el siguiente | una sola respuesta al juntarse los dos |
| trama sin `\n` que supera 8 KB | buffer descartado, `ERR_100` |

`ERR_500` está definido en `protocol.py` pero **ningún camino lo emite**.

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

Detalle de la demo: si el puerto pedido está ocupado, la GUI avanza al siguiente
libre y le asigna a cada agente un puerto TCP de comandos distinto (5002, 5003,
…) para que los `EXEC` no se pisen.

---

## 9. Dónde el comportamiento real se aparta de la documentación

Dos cosas que conviene decir antes de que las pregunten:

1. **No hay alertas push al administrador.** `propuesta.md` promete
   "recepción de alertas críticas" por TCP. El watchdog solo imprime en la
   consola del servidor; no notifica a nadie. Un cliente conectado nunca se
   entera de que un nodo cayó, salvo que lo consulte con `GET_NODES`.
2. **`propuesta.md` documenta respuestas con `|` y un `<TOKEN>` de auth.** El
   código real usa `;`/`:` en `GET_NODES` y no emite ningún token. El README
   refleja el código.

Lo que sí funciona y es defendible: concurrencia multi-hilo, exclusión mutua del
registro, detección de inactividad con purga, encuadrado de tramas TCP,
ejecución remota real sobre un canal TCP dedicado, validación estricta de
entrada, y la tolerancia a errores sin colapso (RF07).

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
- **"¿Qué pasa si mandan dos comandos juntos?"** → El `TcpFrameReader` del
  servidor los separa por `\n` y responde uno por uno; el cliente hace lo mismo
  con las respuestas. También cubre la trama partida a mitad de segmento.
- **"¿Y el EXEC, hace algo de verdad?"** → Sí: el servidor abre un TCP al
  `PUERTO_CMD` que el agente anunció en su telemetría, manda `EXECCMD|<CMD>`, el
  agente valida contra una lista blanca, lo ejecuta, lo loguea en
  `agent/historial_comandos.log` y devuelve el resultado. Si el nodo no tiene
  canal o el comando no está permitido, responde `ERR_104`.
- **"¿Qué pasa si el puerto ya está ocupado?"** → El servidor detecta
  `EADDRINUSE`, imprime un mensaje claro y sale con código 1 (requisito del
  TP §6). La demo de la GUI en cambio avanza sola al siguiente puerto libre.
- **"¿Y si el nodo se cae para siempre?"** → El watchdog lo marca `OFFLINE`
  a los 15-20 s y lo **purga** del registro a los 120 s (configurable), para que
  `nodes_registry` no crezca sin límite.
