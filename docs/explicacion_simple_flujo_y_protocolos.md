# 💡 Guía Simple: Qué es NETMON/1.0 y Cómo Funciona el Flujo del Sistema

Explicación en lenguaje natural y paso a paso de cómo funciona el proyecto **SDMR (Sistema Distribuido de Monitoreo en Red)**, qué es `NETMON/1.0` y dónde se usa cada protocolo (**UDP**, **TCP** y **WebSocket**).

---

## 1. ¿El protocolo `NETMON/1.0` ya viene en Python/Windows o lo creamos nosotros?

**Lo creamos 100% nosotros.** No existe en Internet, ni viene instalado en Python, ni en Windows.

Para entenderlo fácil, piensa en una **llamada telefónica** o en **el correo**:
* **TCP y UDP** sí vienen en el sistema operativo (Windows/Linux). Son como **la línea telefónica** o **el camión de correo**: saben llevar mensajes de una computadora a otra usando su dirección IP y su puerto, pero **no entienden qué significan las palabras que van adentro**. Para TCP y UDP, todo lo que envías son simplemente letras o bytes sueltos.
* **`NETMON/1.0` (Network Monitoring 1.0)** es **el idioma y las reglas que nosotros inventamos** en el archivo `common/protocol.py` para que nuestros programas se entiendan entre sí cuando hablan por esa línea.

### ¿Por qué tuvimos que inventar `NETMON/1.0`?
Imagina que el Agente quiere decirle al Servidor: *"Soy la PC 1, mi IP es 192.168.1.20, tengo el CPU al 35%, la RAM al 60% y el disco al 40%"*.
Si cada programador escribiera eso como quisiera, el Servidor no sabría cómo leerlo. Entonces nosotros pusimos una regla fija en `common/protocol.py`:
> *"Siempre vamos a separar los datos con una barrita `|` y vamos a poner una palabra clave al principio para saber de qué estamos hablando"*:
* Si empieza con `MON|...` → es un reporte de estado (monitoreo).
* Si empieza con `CMD|...` → es una orden o pedido de un administrador.
* Si empieza con `RES|...` → es una respuesta del servidor.

A ese conjunto de reglas de texto que inventamos nosotros le pusimos el nombre **`NETMON/1.0`** (así como los navegadores web usan un protocolo llamado `HTTP/1.1`).

---

## 2. ¿Cómo funciona todo el sistema en palabras naturales? (El Flujo Paso a Paso)

Imagina que el proyecto es como **la central de seguridad de un edificio**:

1. **El Servidor Central** (`server/server.py`) es la **recepción central**. Tiene un cuaderno en la mesa (un diccionario en memoria llamado `nodes_registry`) donde anota qué computadoras están prendidas y cómo están funcionando.
2. **Los Agentes** (`agent/agent.py`) son **pequeños informantes** instalados en cada computadora del laboratorio que queremos vigilar.
3. **El Cliente Administrador** (`client/admin_client.py`, la ventana gráfica `client/gui_monitor.py` o la Web) es **la pantalla del jefe de sistemas**, que quiere ver el cuaderno del servidor o mandar órdenes.

Veamos la película completa de qué pasa desde que prendes todo:

---

### Paso 1: Se prende el Servidor Central (`server/server.py`)
Cuando ejecutas `python server/server.py`, el servidor abre **dos puertas distintas** (dos puertos) y pone a trabajar a **tres ayudantes** al mismo tiempo (tres hilos o *threads*):

* **Puerta 1 — Buzón rápido sin confirmación (UDP en el puerto `5000`):**
  Aquí se para el **Ayudante 1** (`_udp_listener_loop`). Su único trabajo es recibir cartelitos rápidos que tiran los agentes cada 3 segundos y anotarlos en el cuaderno (`nodes_registry`).
  * **¿Por qué usa UDP aquí?** Porque es como tirar una postal en un buzón: es rapidísimo, no hace falta saludar ni despedirse, y si una postal se pierde no pasa nada porque a los 3 segundos llega la siguiente actualizada.

* **Puerta 2 — Línea telefónica directa y segura (TCP en el puerto `5001`):**
  Aquí se para el **Ayudante 2** (`_tcp_accept_loop`). Espera a que se conecte algún Jefe/Administrador.
  * **¿Por qué usa TCP aquí?** Porque el administrador va a mandar su usuario y contraseña, va a pedir la lista completa de máquinas o va a ordenar reiniciar un servicio. Eso es como una llamada telefónica: necesitas levantar el tubo, confirmar que el otro te escucha y asegurarte de que no se pierda ni una sola letra.

* **El Relojero / Vigilante (Watchdog — `_watchdog_loop`):**
  Es el **Ayudante 3**. Cada 5 segundos mira el cuaderno del servidor. Como los agentes mandan señales por UDP (que no avisa si alguien se desconecta), este ayudante se fija en la hora del último reporte de cada PC:
  * *"¿Pasaron más de 15 segundos sin que la PC 1 mande su reporte? Entonces se apagó o se cortó su red: le pongo el sello de `OFFLINE`"*.

---

### Paso 2: Se prende un Agente en una PC (`agent/agent.py`)
Cuando prendes `agent.py` en una computadora a monitorear, hace tres cosas:

1. **Busca al Servidor (si no le dijiste la IP) — usa UDP:**
   Si el agente no sabe en qué IP está el servidor, grita a toda la red local por **UDP Broadcast** (`descubrir_servidor`):
   * Agente grita: `SRVREQ|NODO_01` (*"¡Hola! Soy NODO_01, ¿alguien es el servidor?"*)
   * El Servidor lo escucha por su puerta UDP 5000 y le responde directo a él: `SRVINFO|NODO_01|192.168.1.50|5000|5001` (*"¡Acá estoy! Mi IP es 192.168.1.50"*).

2. **Abre su propio teléfono para recibir órdenes (TCP en el puerto `5002`):**
   El agente deja abierto un pequeño canal **TCP** (`_iniciar_canal_comandos`) por si más adelante el servidor necesita darle una orden importante (como reiniciar el servicio o borrar logs).

3. **Entra en un ciclo infinito cada 3 segundos — usa UDP:**
   En `start()`, cada 3 segundos el agente:
   * Mira cuánto CPU, RAM y Disco está usando su propia PC (`get_system_metrics`).
   * Arma la frase en nuestro idioma `NETMON/1.0`:
     `MON|NODO_01|192.168.1.20|25.4|60.1|45.0|OK|5002`
   * La tira por **UDP** hacia el puerto `5000` del servidor y duerme 3 segundos.
   * El servidor la recibe al instante y actualiza su cuaderno.

---

### Paso 3: Entra el Administrador a mirar y controlar (`client/admin_client.py` o GUI/Web)
Ahora tú abres el cliente administrador para ver qué pasa en la red. Todo lo que hace el administrador ocurre por **TCP (puerto `5001`)**:

1. **Conecta el teléfono (`connect`):**
   El cliente llama al puerto TCP `5001` del servidor. El servidor atiende y le asigna un hilo exclusivo (`_handle_tcp_client`) solo para conversar con ese administrador.
2. **Inicia sesión (`AUTH`):**
   * El cliente envía por TCP: `CMD|AUTH|admin|admin123`
   * El servidor revisa si la clave está bien y responde por TCP: `RES|OK|AUTH_SUCCESS|Bienvenido admin`. A partir de ese momento, el servidor recuerda que en esa llamada telefónica ya estás autorizado.
3. **Pide la lista de equipos (`GET_NODES`):**
   * El cliente envía por TCP: `CMD|GET_NODES|ALL`
   * El servidor lee su cuaderno (el mismo cuaderno que el ayudante UDP viene llenando cada 3 segundos) y le contesta por TCP con toda la lista de máquinas:
     `RES|OK|NODES_COUNT:1;NODO_01:192.168.1.20:OK:CPU=25.4%:RAM=60.1%:DISK=45.0%:LAST=1|Lista de nodos obtenida exitosamente`
   * Tu pantalla (consola, Tkinter o Web) recibe ese texto, lo separa por `;` y `:`, y te dibuja la tabla con los porcentajes.

---

### Paso 4: El Administrador manda una orden remota (`EXEC`)
Imagina que ves que `NODO_01` está en `WARNING` y decides mandarle la orden `RESTART_SERVICE`. Aquí ocurre una **cadena de dos llamadas TCP**:

1. **Del Admin al Servidor (TCP puerto `5001`):**
   Tu cliente le dice al servidor: `CMD|EXEC|NODO_01|RESTART_SERVICE`.
2. **Del Servidor al Agente (TCP puerto `5002`):**
   El servidor busca a `NODO_01` en su cuaderno, ve que su IP es `192.168.1.20` y su puerto de órdenes es `5002`. Entonces el servidor llama por **TCP** al agente (`_ejecutar_en_nodo`) y le dice:
   `EXECCMD|RESTART_SERVICE`
3. **Respuesta de vuelta:**
   * El Agente recibe la orden en `_procesar_orden`, verifica que `RESTART_SERVICE` sea una orden permitida, la anota en su historial y le responde al Servidor por TCP: `RES|OK|RESTART_SERVICE|Servicio de monitoreo reiniciado correctamente`.
   * El Servidor recibe esa confirmación y te la reenvía a ti (al Admin) por TCP: `RES|OK|EXEC_SUCCESS|[NODO_01] Servicio de monitoreo reiniciado correctamente`.

---

## 3. Resumen Visual: Dónde se usa cada protocolo y por qué

| Quién habla con quién | Qué se envían | Qué protocolo de transporte usan | Qué formato `NETMON/1.0` viaja adentro | ¿Por qué ese protocolo? |
| :--- | :--- | :--- | :--- | :--- |
| **Agente → Servidor** (al arrancar sin IP) | *"¿Dónde está el servidor?"* | **UDP** (Broadcast puerto `5000`) | `SRVREQ\|NODO_01` y vuelve `SRVINFO\|...` | Porque UDP permite gritar a toda la red a la vez (*broadcast*) sin saber la IP del servidor. |
| **Agente → Servidor** (cada 3 segundos) | Porcentajes de CPU, RAM y Disco | **UDP** (puerto `5000`) | `MON\|NODO_01\|IP\|CPU\|RAM\|DISK\|OK\|5002` | Porque se manda todo el tiempo; queremos velocidad y no gastar recursos manteniendo conexiones abiertas. |
| **Admin → Servidor** (cuando usas el sistema) | Login, pedir lista de nodos, pedir `EXEC` | **TCP** (puerto `5001`) | `CMD\|AUTH\|...`, `CMD\|GET_NODES\|ALL` y vuelve `RES\|OK\|...` | Porque necesitamos una sesión segura donde no se pierda ningún comando ni respuesta. |
| **Servidor → Agente** (cuando pides un `EXEC`) | Orden administrativa a un equipo | **TCP** (puerto `5002` del agente) | `EXECCMD\|RESTART_SERVICE` y vuelve `RES\|OK\|...` | Porque una orden de control debe llegar sí o sí y necesitamos confirmación de que el agente la ejecutó. |
| **Web/Celu → Gateway** (solo si usas navegador o app móvil) | Lo mismo que el Admin | **WebSocket** (puerto `5003`) → que pasa a **TCP** (`5001`) | Las mismas frases `CMD\|...` y `RES\|...` | Porque los navegadores web no tienen permiso para hablar TCP directo, así que usan el Gateway (`server/gateway.py`) como adaptador. |
