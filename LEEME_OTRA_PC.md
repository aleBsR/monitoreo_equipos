# LEEME — Poner en marcha en otra PC (5 minutos)

Guía corta para replicar el entorno SDMR en la segunda notebook.
El detalle completo (orden de encendido, firewall, clientes) está en `README.md`.

## 0. Requisitos (una vez por PC)

- **Python 3.8+** (Windows: tildar *Add Python to PATH* en el instalador)
- **Node.js 18+** (`node --version`) — solo si vas a usar la web o la app móvil
- **Expo Go** (Play Store) — solo en el celu/tablet para la app móvil

## 1. Clonar e instalar dependencias

```bash
git clone https://github.com/aleBsR/monitoreo_equipos.git
cd monitoreo_equipos
pip install -r requirements.txt
```

## 2. Compilar la web (una vez por PC, solo si usarás web o `--serve-web`)

```bash
cd web && npm install && npm run build && cd ..
```

## 3. App móvil (solo donde corra el Metro de Expo)

```bash
cd mobile && npm install && cd ..
```

Después: `cd mobile` → `npm run start:tunel` (o `npm start` en la misma red) →
QR con Expo Go → Login con `ws://IP_DEL_SERVIDOR:5003`, `admin` / `admin123`.

## 4. Probar que todo anda

```bash
# Terminal 1: servidor
python server/server.py
# Terminal 2: gateway + web
python server/gateway.py 5003 127.0.0.1 5001 --serve-web
# Terminal 3: un agente
python agent/agent.py NODO_01 127.0.0.1 5000 5002
# Terminal 4: verificación (tiene que dar 3/3 OK)
python tools/verificar_red.py 127.0.0.1 5000 5001 5003
```

O en Windows, doble clic en `scripts\iniciar_todo.bat` (hace los 4 pasos solo).

## 5. Batería completa (opcional)

```bash
python tools/test_system.py
```

> **Carpetas:** `server/` `agent/` `client/` `common/` = código Python ·
> `web/` = React · `mobile/` = Expo · `scripts/` = lanzadores ·
> `tools/` = verificación y tests · `docs/` = propuesta y bibliografía.

## 6. Auto-instalacion del agente (sin terminal)

En cada PC cliente, una sola vez:
`ash
# Windows
scripts\instalar_agente.bat                # IP por broadcast (automatico)
scripts\instalar_agente.bat 192.168.1.50    # IP fija en agent\config.ini

# Linux / macOS
./scripts/instalar_agente.sh
./scripts/instalar_agente.sh 192.168.1.50 NODO_02
`
A partir de ahi el agente arranca solo, oculto, al iniciar sesion (carpeta de
Inicio en Windows / ~/.config/autostart en Linux). Para quitarlo:
scripts\desinstalar_agente.bat / ./scripts/desinstalar_agente.sh.

Si no se pasa la IP del servidor, el agente la descubre solo por broadcast
(SRVREQ -> SRVINFO). En el dashboard del administrador, pestana Nodos ->
boton "Copiar comando para clientes" copia el comando de instalacion con la IP
del servidor al que esta conectado.
