# Propuesta de Arquitectura y Diseño Técnico
## Trabajo Práctico Integrador – Programación de Redes con Sockets
**Asignatura:** Programación de Redes con Sockets (Optativa III - LAS)  
**Tema Propuesto:** Sistema Distribuido de Monitoreo de Equipos en Red (SDMR)  
**Lenguaje:** Python 3  

---

## 1. Resumen de la Propuesta

Se propone desarrollar un **Sistema Distribuido de Monitoreo de Equipos en Red (SDMR)** basado en la arquitectura **Cliente/Servidor**, el cual permite supervisar la disponibilidad y el rendimiento de múltiples computadoras (nodos) en tiempo real, así como ejecutar acciones de administración remota de forma segura y confiable.

El sistema aprovecha de forma natural las ventajas de **UDP** y **TCP**:
* **UDP**: Para la transmisión continua y de baja latencia de métricas de salud (*heartbeat* y telemetría de uso de CPU/RAM/Disco).
* **TCP**: Para la autenticación de administradores, envío de comandos de control (ej: reiniciar servicio, solicitar logs) y recepción de alertas críticas.

---

## 2. Análisis del Stack Tecnológico

### 2.1 Núcleo de Red (Recomendado)
* **Lenguaje:** **Python 3**
* **Librerías principales:** `socket` (nativo), `threading` / `concurrent.futures` / `select` (concurrencia), `psutil` (captura de métricas del sistema), `json` o `struct` (serialización de mensajes).

> [!IMPORTANT]
> **Advertencia sobre Django / Frameworks de Alto Nivel:**  
> La materia evalúa el uso explícito de la API nativa de sockets (`socket.socket(AF_INET, SOCK_STREAM/SOCK_DGRAM)`), el manejo de concurrencia a nivel de sistema y el parseo manual del protocolo de aplicación.  
> El uso de Django o REST API oculta la capa de sockets y transporte bajo servidores WSGI/ASGI, lo que podría incidir negativamente en la evaluación de los requerimientos **RF03**, **RF04** y **RF06**.

### 2.2 Interfaz de Usuario (UI)
* **Opción A (Recomendada - Terminal Rich / TUI):**  
  Dashboard en consola interactiva con colores y tablas en tiempo real usando librerías como `rich` o `curses`. Es directa, no requiere servidores adicionales y permite visualizar el tráfico de forma limpia durante la defensa.
* **Opción B (Opcional - Dashboard Web):**  
  Si el equipo desea añadir una interfaz React, esta debe funcionar como un *Desafío Adicional (Opcional)* que consuma datos del Servidor Python, **sin reemplazar** los clientes/agentes socket nativos TCP/UDP.

---

## 3. Arquitectura del Sistema

```
                  ┌───────────────────────────────────────────┐
                  │       SERVIDOR CENTRAL DE MONITOREO       │
                  │                                           │
                  │  ┌─────────────────┐ ┌─────────────────┐  │
                  │  │ Socket UDP      │ │ Socket TCP      │  │
                  │  │ Puerto 5000     │ │ Puerto 5001     │  │
                  │  └────────┬────────┘ └────────┬────────┘  │
                  └───────────┼───────────────────┼───────────┘
                              │                   │
            UDP (Métricas/Heartbeats)        TCP (Control/Alertas/Logs)
             Baja latencia, periódico           Entrega garantizada
                              │                   │
             ┌────────────────┴───────┐ ┌─────────┴────────────────┐
             │                        │ │                          │
     ┌───────▼────────┐      ┌────────▼─▼──────┐          ┌────────▼────────┐
     │ Agente Nodo 1  │      │ Agente Nodo 2   │          │ Cliente Admin   │
     │ (Equipo Red)   │      │ (Equipo Red)    │          │ (Consola/Dash)  │
     └────────────────┘      └─────────────────┘          └─────────────────┘
```

### Componentes Principales:
1. **Servidor Central (Multi-thread)**:
   * Mantiene un socket UDP a la escucha de datagramas de telemetría de los agentes.
   * Mantiene un socket TCP aceptando conexiones entrantes de clientes administradores y agentes para comandos.
   * Administra una tabla en memoria con el estado de los nodos monitoreados (Online/Offline, CPU, RAM, Uptime).
2. **Agente de Monitoreo (Cliente Agente)**:
   * Proceso ligero que se ejecuta en cada equipo a monitorear.
   * Envía periódicamente (cada 3-5 s) métricas por UDP.
   * Escucha por TCP solicitudes de ejecución de comandos o descarga de logs enviadas por el servidor.
3. **Cliente Administrador (Cliente Admin)**:
   * Permite al usuario autenticarse, consultar el estado de la red, ver nodos activos y enviar comandos de control.

---

## 4. Justificación Técnica TCP vs. UDP

| Característica | Canal UDP (Telemetría / Heartbeat) | Canal TCP (Control / Alertas) |
| :--- | :--- | :--- |
| **Orientación a conexión** | Sin conexión (Datagramas) | Orientado a conexión (Handshake `SYN/ACK`) |
| **Garantía de entrega** | No garantizada (posible pérdida) | Garantizada (Retransmisión y ACK) |
| **Orden de datos** | No garantizado | Secuencial y ordenado |
| **Uso en el Proyecto** | Envío periódico de pings, % CPU, % RAM | Autenticación, envío de comandos, descarga de logs |
| **Justificación Teórica** | Si un paquete de telemetría se pierde, la siguiente muestra llegará en 3 segundos. No vale la pena retransmitir datos viejos. | Un comando administrativo (ej: `RESTART`) o un log de auditoría NO puede perderse ni llegar incompleto. |

---

## 5. Diseño del Protocolo de Aplicación (`NETMON/1.0`)

El protocolo utilizará un formato de texto plano con delimitadores (`|`), fácil de parsear, depurar y capturar con Wireshark.

### 5.1 Mensajes UDP (Agente -> Servidor)
* **Formato:** `MON|<ID_NODO>|<IP_ORIGEN>|<CPU_%>|<RAM_%>|<DISK_%>|<STATUS>`
* **Ejemplo:** `MON|NODO_01|192.168.1.50|35.4|62.1|40.0|OK`

### 5.2 Mensajes TCP (Cliente Admin <-> Servidor)
* **Solicitud de Autenticación:**  
  `CMD|AUTH|<USUARIO>|<PASSWORD>`  
  *Respuesta:* `RES|OK|AUTH_SUCCESS|<TOKEN>` o `RES|ERR|AUTH_FAILED|Credenciales incorrectas`
* **Consulta de Estado de Nodos:**  
  `CMD|GET_NODES|ALL`  
  *Respuesta:* `RES|OK|NODES_COUNT:2|NODO_01:ONLINE|NODO_02:OFFLINE`
* **Ejecución de Comando Remoto:**  
  `CMD|EXEC|<ID_NODO>|<COMANDO>`  
  *Respuesta:* `RES|OK|EXEC_SUCCESS|Servicio reiniciado correctamente`

### 5.3 Códigos de Error Definidos
* `ERR_100`: Solicitud malformada / Parámetros insuficientes.
* `ERR_101`: Autenticación requerida / Sin permisos.
* `ERR_102`: Nodo destino no disponible o desconectado.
* `ERR_103`: Comando desconocido.

---

## 6. Manejo de Errores y Validaciones

1. **Servidor No Disponible:** El cliente/agente detectará timeouts (`socket.settimeout()`) y reintentará conexión con backoff exponencial.
2. **Desconexión Inesperada:** El servidor eliminará hilos asociados a clientes TCP desconectados y marcará el nodo como `OFFLINE` si no recibe UDP heartbeats durante más de 15 segundos.
3. **Validación de Datos Entrantes:** Se validará rango de valores (ej: CPU entre 0 y 100%), formato del mensaje, longitud máxima y sanitización de comandos para evitar inyecciones.

---

## 7. Plan de Pruebas y Análisis con Wireshark

| Prueba | Descripción | Herramienta de Verificación |
| :--- | :--- | :--- |
| **Prueba 1: Cliente Único** | Conexión normal de 1 agente enviando UDP y 1 admin vía TCP | Script Python + Console Logs |
| **Prueba 2: Múltiples Clientes** | Conexión simultánea de al menos 3 agentes y 2 admins concurrenciales | Scripts de prueba paralelos |
| **Prueba 3: Captura TCP** | Observación del saludo de 3 vías (`SYN`, `SYN-ACK`, `ACK`), intercambio de datos y cierre (`FIN`) | **Wireshark** (Filtro: `tcp.port == 5001`) |
| **Prueba 4: Captura UDP** | Inspección de datagramas UDP sin conexión previa | **Wireshark** (Filtro: `udp.port == 5000`) |
| **Prueba 5: Resiliencia** | Desconexión abrupta del cliente y envío de paquetes malformados | Pruebas de estrés y logs de servidor |

---

## 8. Entregables y Roadmap de Trabajo

- [ ] **Fase 1:** Aprobación de la propuesta con el equipo/docente.
- [ ] **Fase 2:** Especificación técnica detallada del protocolo `NETMON/1.0`.
- [ ] **Fase 3:** Código fuente del Servidor Central (`server.py`) con soporte TCP/UDP multi-hilo.
- [ ] **Fase 4:** Código fuente del Agente (`agent.py`) y Cliente Admin (`client.py`).
- [ ] **Fase 5:** Pruebas de concurrencia y capturas de tráfico con Wireshark (`.pcapng`).
- [ ] **Fase 6:** Redacción del Informe Técnico PDF (23 secciones) y grabación del video demostrativo.
