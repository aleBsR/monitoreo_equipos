"""
================================================================================
Contenido de ayuda de SDMR (instrucciones de uso y conceptos de red)
================================================================================
Dos colecciones de texto plano que alimenta las pestañas de ayuda del dashboard:

  * `INSTRUCCIONES` -> pestaña "Instrucciones de uso". Cómo levantar el sistema,
    comandos, puertos y problemas frecuentes (redacción propia del proyecto).

  * `CONCEPTOS`     -> pestaña "Conceptos TCP/UDP". Definiciones de la bibliografía
    obligatoria, copiadas **literalmente** de `Redes de Computadoras 5ed`, sin
    modificar ninguna definición. Cada entrada indica capítulo y página.

No se importa el PDF en tiempo de ejecución: el texto queda fijo acá para que la
GUI no dependa de que el archivo esté presente.
================================================================================
"""

FUENTE_LIBRO = 'KUROSE, A. F.; ROSS, K. W. Redes de Computadoras: Un Enfoque hacia Internet (5.ª edición). Pearson Prentice Hall, 2010. (Copia en PDF incluida en la carpeta del trabajo práctico.)'

INSTRUCCIONES = [{'titulo': '1. Inicio rápido (todo con un comando)',
  'texto': 'La forma más simple de ver el sistema completo (servidor + agentes + este '
           'dashboard).\n'
           '\n'
           'Linux (Debian/Ubuntu):\n'
           '  • ./instalar.sh   -> una sola vez: instala psutil/tkinter y crea el comando '
           "'sdmr'.\n"
           '  • sdmr            -> abre este dashboard ya en modo demo.\n'
           '  • sdmr --agentes 5 --udp 6000 --tcp 6001\n'
           '\n'
           'Windows:\n'
           '  • Doble clic en iniciar_sdmr.bat.\n'
           '  • Ejecutar una vez crear_acceso_directo.bat crea el icono en el Escritorio.\n'
           '\n'
           'Sin instalar nada: python3 client/gui_monitor.py --demo\n'
           '\n'
           "El lanzador deja preseleccionada la pestaña 'Demo Local'; ahí se levantan los\n"
           'procesos con un solo clic.'},
 {'titulo': '2. Modo manual (tres terminales)',
  'texto': '1) Servidor:\n'
           '       python3 server/server.py [udp] [tcp] [segundos_purga]\n'
           '   Por defecto UDP 5000 y TCP 5001.\n'
           '\n'
           '2) Agentes (uno por equipo a monitorear):\n'
           '       python3 agent/agent.py NODO_01 127.0.0.1 5000 5002\n'
           '       python3 agent/agent.py NODO_02 127.0.0.1 5000 5003\n'
           '   Sintaxis: <ID> <IP_DEL_SERVIDOR> <UDP> [PUERTO_CMD].\n'
           '   Cada agente necesita un puerto de comandos distinto (5002, 5003, ...).\n'
           '\n'
           '3) Cliente:\n'
           '       python3 client/admin_client.py 127.0.0.1 5001'},
 {'titulo': '3. Conectar desde esta ventana',
  'texto': 'Barra superior:\n'
           '  • Servidor / Puerto TCP / Puerto UDP: datos del servidor central.\n'
           '  • Usuario y Contraseña: credenciales de administrador.\n'
           "  • 'Conectar' abre la sesión TCP, 'Autenticar' envía CMD|AUTH.\n"
           "  • 'Auto-actualizar' reenvía CMD|GET_NODES cada 2 s para refrescar la tabla.\n"
           '\n'
           'Credenciales por defecto:  admin / admin123  (también operador / operador123).\n'
           '\n'
           "Pestaña 'Nodos':\n"
           "  • '⟳ Actualizar ahora' fuerza un CMD|GET_NODES.\n"
           '  • Doble clic en una fila la selecciona como destino del EXEC.\n'
           "  • Botón 'Enviar (EXEC)' envía CMD|EXEC|<NODO>|<COMANDO>."},
 {'titulo': '4. Qué hace cada pestaña',
  'texto': '• Nodos        -> tabla con telemetría en vivo (estado, CPU, RAM, Disco).\n'
           '• Demo Local   -> levanta Servidor + Agentes como procesos y se conecta solo.\n'
           '                 Si un puerto está ocupado, avanza solo al siguiente libre.\n'
           '• Tráfico      -> cada trama NETMON/1.0 enviada (TX) y recibida (RX), en crudo.\n'
           '                 Permite mandar tramas inválidas para ver los ERR_100 / ERR_103.\n'
           '• Instrucciones-> esta ayuda.\n'
           '• Conceptos    -> definiciones de TCP, UDP, sockets y puertos (Kurose).'},
 {'titulo': '5. Comandos del protocolo NETMON/1.0',
  'texto': 'Sobre TCP (cabecera obligatoria CMD|):\n'
           '  • CMD|PING                              -> PONG (no pide autenticarse)\n'
           '  • CMD|AUTH|<usuario>|<password>         -> AUTH_SUCCESS\n'
           '  • CMD|GET_NODES|ALL                     -> lista de nodos\n'
           '  • CMD|EXEC|<NODO>|<COMANDO>             -> ejecución remota real\n'
           '\n'
           'Comandos EXEC que el agente acepta:\n'
           '  • RESTART_SERVICE   -> simula el reinicio del servicio de monitoreo.\n'
           '  • DIAGNOSTIC        -> diagnóstico del equipo.\n'
           '  • CLEAR_LOGS        -> limpieza de registros.\n'
           '  Cualquier otro se rechaza con ERR_104.\n'
           '\n'
           'Errores tipificados:\n'
           '  ERR_100 mensaje malformado | ERR_101 sin sesión / credenciales\n'
           '  ERR_102 nodo inexistente u OFFLINE | ERR_103 comando desconocido\n'
           '  ERR_104 nodo inalcanzable o comando no soportado por el agente'},
 {'titulo': '6. Puertos del sistema',
  'texto': '  5000/UDP   telemetría de los agentes (MON|ID|IP|CPU|RAM|DISK|ESTADO|PUERTO_CMD)\n'
           '  5001/TCP   comandos de los administradores\n'
           '  5002+/TCP  canal de comandos EXEC de cada agente (uno por nodo)\n'
           '\n'
           'Si el servidor no puede abrir su puerto (ocupado) lo indica y termina con\n'
           'código 1. En Wireshark: udp.port == 5000, tcp.port == 5001, tcp.port == 5002.'},
 {'titulo': '7. Pruebas automáticas',
  'texto': '  python3 test_system.py\n'
           '\n'
           'Levanta servidor y 3 agentes en puertos libres y corre sin pedir teclado:\n'
           'cliente único, clientes simultáneos, desconexión abrupta, datos inválidos,\n'
           'servidor caído, encuadrado de tramas, concurrencia, watchdog y EXEC.\n'
           '\n'
           "Al final imprime 'N/N verificaciones exitosas' y sale con código 0 si todo pasó."},
 {'titulo': '8. Problemas frecuentes',
  'texto': "• 'falta el módulo tkinter' -> sudo apt install python3-tk (o ./instalar.sh).\n"
           "• 'Puerto en uso' / EADDRINUSE -> cerrar el proceso anterior o indicar otro "
           'puerto:\n'
           '      python3 server/server.py 5100 5101\n'
           '• Nodo sin datos -> verificar que el agente corre y que la IP del servidor es\n'
           '  la correcta; el nodo pasa a OFFLINE a los ~15-20 s sin telemetría y se\n'
           '  purga del registro a los 120 s.\n'
           '• ERR_104 en EXEC -> el agente no tiene abierto su puerto de comandos o el\n'
           '  comando no está en la lista permitida.\n'
           "• La GUI no refresca -> tildar 'Auto-actualizar' o pulsar 'Actualizar ahora'."}]

CONCEPTOS = [{'titulo': 'Protocolo',
  'fuente': 'Capítulo 1 · página 9',
  'texto': 'Un protocolo define el formato y el orden de los mensajes intercambiados entre dos '
           'o más entidades que se comunican, así como las acciones tomadas en la transmisión '
           'y/o la recepción de un mensaje u otro suceso.'},
 {'titulo': 'Arquitectura cliente-servidor',
  'fuente': 'Capítulo 2 · página 83',
  'texto': 'En una arquitectura cliente-servidor siempre existe un host activo, denominado '
           'servidor, que da servicio a las solicitudes de muchos otros hosts, que son los '
           'clientes. Los hosts clientes pueden estar activos siempre o de forma '
           'intermitente.'},
 {'titulo': 'Procesos cliente y servidor',
  'fuente': 'Capítulo 2 · página 85',
  'texto': 'En el contexto de una sesión de comunicación entre una pareja de procesos, el '
           'proceso que inicia la comunicación (es decir, que inicialmente se pone en contacto '
           'con el otro proceso al principio de la sesión) se etiqueta como el cliente.'},
 {'titulo': 'Socket: interfaz entre aplicación y transporte',
  'fuente': 'Capítulo 2 · página 87',
  'texto': 'Como se muestra en la figura, un socket es la interfaz entre la capa de aplicación '
           'y la capa de transporte de un host. También se conoce como Interfaz de '
           'programación de aplicaciones (API, Application Programming Interface) que opera '
           'entre la aplicación y la red, ya que el socket es la interfaz de programación con '
           'la que se construyen las aplicaciones de red.'},
 {'titulo': 'Socket: interfaz entre proceso y protocolo de transporte',
  'fuente': 'Capítulo 2 · página 87',
  'texto': 'Recordemos que un socket es la interfaz entre el proceso de la aplicación y el '
           'protocolo de la capa de transporte.'},
 {'titulo': 'Servicios TCP',
  'fuente': 'Capítulo 2 · página 89',
  'texto': 'El modelo de servicio TCP incluye un servicio orientado a la conexión y un '
           'servicio de transferencia de datos fiable.'},
 {'titulo': 'Servicio orientado a la conexión (TCP)',
  'fuente': 'Capítulo 2 · página 91',
  'texto': 'Este procedimiento denominado de negociación, de reconocimiento o de '
           'establecimiento de la conexión alerta al cliente y al servidor, permitiéndoles '
           'prepararse para el intercambio de paquetes. Después de esta fase de negociación, '
           'se dice que existe una conexión TCP entre los sockets de los dos procesos. La '
           'conexión es una conexión full-duplex ya que los dos procesos pueden enviarse '
           'mensajes entre sí a través de la conexión al mismo tiempo.'},
 {'titulo': 'Servicio de transferencia de datos fiable (TCP)',
  'fuente': 'Capítulo 2 · página 91',
  'texto': 'Los procesos de comunicación pueden confiar en TCP para entregar todos los datos '
           'enviados sin errores y en el orden correcto.'},
 {'titulo': 'Control de congestión de TCP',
  'fuente': 'Capítulo 2 · página 91',
  'texto': 'TCP también incluye un mecanismo de control de congestión, que es un servicio para '
           'mejorar el funcionamiento general de Internet, más que para el beneficio directo '
           'de los procesos que se comunican. Este mecanismo de control de congestión de TCP '
           'regula el proceso emisor (cliente o servidor) cuando la red está congestionada '
           'entre el emisor y el receptor.'},
 {'titulo': 'Servicios UDP',
  'fuente': 'Capítulo 2 · página 91',
  'texto': 'UDP es un protocolo de transporte ligero simple que proporciona unos servicios '
           'mínimos y no está orientado a la conexión, por lo que no tiene lugar un '
           'procedimiento de negociación antes de que los dos procesos comiencen a '
           'comunicarse. UDP proporciona un servicio de transferencia de datos no fiable; es '
           'decir, cuando un proceso envía un mensaje a un socket UDP, el protocolo UDP no '
           'ofrece ninguna garantía de que el mensaje vaya a llegar al proceso receptor. '
           'Además, los mensajes que sí llegan al proceso receptor pueden hacerlo de manera '
           'desordenada.'},
 {'titulo': 'Segmento (paquete de la capa de transporte)',
  'fuente': 'Capítulo 1 · página 49',
  'texto': 'En este libro, denominaremos a los paquetes de la capa de transporte segmentos.'},
 {'titulo': 'Datagrama (paquete de la capa de red)',
  'fuente': 'Capítulo 1 · página 49',
  'texto': 'Capa de red La capa de red de Internet es responsable de trasladar los paquetes de '
           'la capa de red, conocidos como datagramas, de un host a otro.'},
 {'titulo': 'Multiplexación y demultiplexación',
  'fuente': 'Capítulo 3 · página 189',
  'texto': 'Extender la entrega host a host a una entrega proceso a proceso es lo que se '
           'denomina multiplexación y demultiplexación de la capa de transporte, tema que '
           'desarrollaremos en la siguiente sección.'},
 {'titulo': 'Números de puerto',
  'fuente': 'Capítulo 3 · página 191',
  'texto': 'Cada número de puerto es un número de 16 bits comprendido en el rango de 0 a '
           '65535. Los números de puerto pertenecientes al rango de 0 a 1023 se conocen como '
           'números de puertos bien conocidos y son restringidos, lo que significa que están '
           'reservados para ser empleados por los protocolos de aplicación bien conocidos, '
           'como por ejemplo HTTP (que utiliza el número de puerto 80) y FTP (que utiliza el '
           'número de puerto 21).'},
 {'titulo': 'UDP: servicio sin conexión',
  'fuente': 'Capítulo 2 · página 161',
  'texto': 'UDP es un servicio sin conexión (no existe una fase inicial de negociación durante '
           'la que se establezca un conducto para la comunicación entre los dos procesos). '
           'Dado que UDP no dispone de un conducto, cuando un proceso desea enviar un lote de '
           'bytes a otro proceso, el proceso emisor tiene que asociar la dirección del proceso '
           'de destino al lote de bytes.'},
 {'titulo': 'UDP: entrega de mejor esfuerzo',
  'fuente': 'Capítulo 2 · página 161',
  'texto': 'UDP es un servicio de entrega de mejor esfuerzo (best effort) en el que no se '
           'garantiza que el lote de bytes sea entregado.'},
 {'titulo': 'Transferencia fiable de datos (TCP)',
  'fuente': 'Capítulo 3 · página 189',
  'texto': 'El primero y más importante es que proporciona una transferencia de datos fiable. '
           'Utilizando técnicas de control de flujo, números de secuencia, mensajes de '
           'reconocimiento y temporizadores (técnicas que estudiaremos en detalle en este '
           'capítulo), TCP garantiza que los datos transmitidos por el proceso emisor sean '
           'entregados al proceso receptor, correctamente y en orden. De este modo, TCP '
           'convierte el servicio no fiable de IP entre sistemas terminales en un servicio de '
           'transporte de datos fiable entre procesos.'},
 {'titulo': 'Control de flujo',
  'fuente': 'Capítulo 3 · página 247',
  'texto': 'TCP proporciona un servicio de control de flujo a sus aplicaciones para eliminar '
           'la posibilidad de que el emisor desborde el buffer del receptor. El control de '
           'flujo es por tanto un servicio de adaptación de velocidades (adapta la velocidad a '
           'la que el emisor está transmitiendo frente a la velocidad a la que la aplicación '
           'receptora está leyendo).'},
 {'titulo': 'Acuerdo en tres fases (establecimiento de conexión TCP)',
  'fuente': 'Capítulo 3 · página 249',
  'texto': 'Observe que con el fin de establecer la conexión se envían tres paquetes entre los '
           'dos hosts, como se ilustra en la Figura 3.39. Por ello, este procedimiento de '
           'establecimiento de la conexión suele denominarse proceso de acuerdo en tres '
           'fases.'}]
