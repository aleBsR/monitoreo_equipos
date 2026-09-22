# 📡 Sistema Distribuido de Monitoreo en Red (SDMR)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/Protocol-NETMON%2F1.0-orange.svg)](#-protocolo-de-aplicación-netmon10)

Aplicación distribuida basada en el modelo **Cliente/Servidor** desarrollada para la asignatura **Programación de Redes con Sockets (Optativa III - LAS)**.

El sistema permite supervisar en tiempo real la disponibilidad, métricas de rendimiento y salud (CPU, Memoria RAM y Uso de Disco) de múltiples computadoras (nodos) distribuidas en una red local, además de permitir la ejecución de acciones administrativas de forma remota.Estoy probando como funciona el commit


---

## 🌟 Características Principales

* **Uso Dual de Sockets (TCP & UDP):**
  * **UDP (Puerto 5000):** Canal sin conexión de alta velocidad y baja latencia para el envío periódico de telemetría y *heartbeats* desde los nodos hacia el servidor.
  * **TCP (Puerto 5001):** Canal orientando a conexión y confiable para la autenticación de administradores, consulta de estado de la red, ejecución de comandos remotos y alertas.
* **Servidor Concurrente Multihilo:**
  * Atiende a **múltiples clientes y agentes simultáneamente** utilizando hilos independientes (`threading`).
  * Utiliza mecanismos de exclusión mutua (`threading.Lock`) para garantizar la integridad del registro de nodos en memoria (*thread-safety*).
* **Guardián de Inactividad (Watchdog):**
  * Monitor en segundo plano que detecta si un nodo deja de transmitir telemetría UDP durante más de 15 segundos y lo marca automáticamente como `OFFLINE`.
* **Protocolo de Aplicación Propio (`NETMON/1.0`):**
  * Formato claro basado en cadenas delimitadas por tuberías (`|`), con códigos de respuesta (`OK`, `ERR`) y errores tipificados.
* **Resiliencia y Manejo de Errores (RF07):**
  * Validación estricta de encabezados, parámetros e integridad lógica. El servidor no colapsa ni cierra conexiones abruptamente ante mensajes malformados o datos inválidos.
* **Captura de Métricas Reales:**
  * Uso de `psutil` para monitorear hardware real (con fallback a simulación si la librería no está instalada).

---

## 🏗️ Arquitectura del Sistema

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

---

## 📜 Protocolo de Aplicación `NETMON/1.0`

### 📤 Canal UDP (Telemetría / Heartbeat)
* **Formato:** `MON|<ID_NODO>|<IP>|<CPU_%>|<RAM_%>|<DISK_%>|<STATUS>`
* **Ejemplo:** `MON|NODO_01|192.168.1.50|35.4|62.1|40.0|OK`

### 📥 Canal TCP (Comandos y Respuestas)
* **Autenticación:**
  * *Solicitud:* `CMD|AUTH|<USUARIO>|<PASSWORD>`
  * *Respuesta:* `RES|OK|AUTH_SUCCESS|Bienvenido admin`
* **Consulta de Nodos:**
  * *Solicitud:* `CMD|GET_NODES|ALL`
  * *Respuesta:* `RES|OK|NODES_COUNT:2;NODO_01:...;NODO_02:...`
* **Ejecución Remota:**
  * *Solicitud:* `CMD|EXEC|<ID_NODO>|<COMANDO>`
  * *Respuesta:* `RES|OK|EXEC_SUCCESS|Comando ejecutado`

### ⚠️ Catálogo de Errores Tipificados
* `ERR_100`: Mensaje malformado o falta de parámetros obligatorios.
* `ERR_101`: Autenticación requerida o credenciales inválidas.
* `ERR_102`: El nodo especificado no existe o se encuentra `OFFLINE`.
* `ERR_103`: El comando solicitado no existe en el protocolo.

---

## 📁 Estructura del Repositorio

```
.
├── common/
│   ├── __init__.py
│   └── protocol.py          # Definición, encodificación y parseo del protocolo NETMON/1.0
├── server/
│   ├── __init__.py
│   └── server.py            # Servidor concurrente TCP (5001) y UDP (5000)
├── agent/
│   ├── __init__.py
│   └── agent.py             # Agente de monitoreo de equipo local
├── client/
│   ├── __init__.py
│   └── admin_client.py      # Cliente de administración interactivo (CLI)
├── requirements.txt         # Dependencias opcionales (psutil, rich)
├── test_system.py           # Script de pruebas automatizadas de integración
└── propuesta_tpi.md         # Documentación de diseño y arquitectura
```

---

## 🚀 Guía de Instalación y Ejecución

### Prerrequisitos
* **Python 3.8+** instalado.
* (Opcional) Instalar dependencias para medir recursos reales:
  ```bash
  pip install -r requirements.txt
  ```

---

### Modo de Uso (Paso a Paso)

#### 1️⃣ Iniciar el Servidor Central
Abre una terminal y ejecuta:
```bash
python3 server/server.py
```
*El servidor comenzará a escuchar en `UDP:5000` y `TCP:5001`.*

#### 2️⃣ Iniciar uno o varios Agentes de Monitoreo
Abre otra terminal para cada agente a monitorear:
```bash
# Sintaxis: python3 agent/agent.py <ID_NODO> <IP_SERVIDOR> <PUERTO_UDP>
python3 agent/agent.py NODO_01 127.0.0.1 5000
python3 agent/agent.py NODO_02 127.0.0.1 5000
```

#### 3️⃣ Iniciar la Consola de Administración (Cliente TCP)
Abre una nueva terminal:
```bash
# Sintaxis: python3 client/admin_client.py <IP_SERVIDOR> <PUERTO_TCP>
python3 client/admin_client.py 127.0.0.1 5001
```

**Credenciales de Administrador por defecto:**
* **Usuario:** `admin` | **Contraseña:** `admin123`
* **Usuario:** `operador` | **Contraseña:** `operador123`

---

## 🧪 Pruebas Automatizadas de Integración

Para ejecutar un test de integración completo que levanta el servidor, 3 agentes concurrentes y efectúa pruebas de comandos y manejo de errores vía TCP:

```bash
python3 test_system.py
```

---

## 📊 Análisis de Tráfico de Red (Wireshark)

Para inspeccionar el tráfico generado durante la evaluación:
* **Filtro TCP:** `tcp.port == 5001` (Muestra el Handshake `SYN`, `SYN-ACK`, `ACK`, envío de comandos y cierre `FIN`).
* **Filtro UDP:** `udp.port == 5000` (Muestra la ráfaga continua de datagramas de telemetría).

---

## 📄 Licencia

Este proyecto fue desarrollado con fines educativos para la asignatura **Programación de Redes con Sockets**.
