---
title: Registro de Cambios de E.D.I.T.H.
aliases: [Changelog EDITH]
tags:
  - edith
  - changelog
created: 2026-10-15
---

# 📜 Registro de Cambios de E.D.I.T.H.

Bitácora técnica de cada versión. Plan general: [[Plan de Cambios y Evolución de EDITH]].

---

## v0.0.8 — 16/10/2026 · Asistente de primer arranque y Ajustes (Fase 15.2)
Commits `8cea1f8` (asistente y Ajustes) y `3466373` (pruebas), en `main` encima de la v0.0.7. Segunda entrega de la Fase 15: EDITH se configura sola la primera vez y todo se cambia desde la app, sin editar `.env`. Diseño: [[Diseño de EDITH Setup (Aplicación de Escritorio)]].

> [!note] Numeración
> Se desarrolló como «0.0.7», pero ese número lo tomó la Fase 14 (seguridad), así que sale como **v0.0.8**.

### 🧙 Asistente de primer arranque (7 pasos)
Aparece solo la primera vez que se abre EDITH (en la app o en el navegador). **«Configurar más tarde»** lo cierra para siempre: todo queda en ⚙️ Ajustes.

| Paso | Qué pide | Detalle |
|---|---|---|
| 1 · Bienvenida | Tu nombre | Va a la memoria a largo plazo: EDITH te llama por tu nombre en todas las conversaciones |
| 2 · Tu equipo y mis modelos | Modelo rápido y profundo | Diagnóstico de procesador, RAM, GPU, disco de los modelos y Ollama → recomendación según la VRAM. Si faltan modelos: **descarga con barra de progreso, pausa y reanudación** |
| 3 · Tu bóveda de Obsidian | Carpeta | Botón **«Elegir…»** (selector de carpetas de Windows, solo en la app), **«Comprobar»** (existe, cuántas notas, se puede escribir) y crear las carpetas `00–04` si está vacía |
| 4 · Elige mi voz | Elvira, Dalia, Ximena, Salomé | **▶ Escuchar** cada una; si no hay internet avisa de que sonará la voz de Windows |
| 5 · WhatsApp y teléfono | Números autorizados, WhatsApp, QR | Opcional. Twilio y la URL pública van en «Avanzado» |
| 6 · Iniciativa propia | Heartbeat, resumen matutino, horas de silencio, avisos | También **«Iniciar EDITH con Windows»** (solo en la app) |
| 7 · ¡Lista! | — | Resumen de lo elegido |

**Recomendación de modelos** (`agent/setup/hardware.py`):

| GPU dedicada | Rápido | Profundo |
|---|---|---|
| 24 GB o más | `qwen3:14b` | `qwen3:32b` |
| 16 GB | `qwen3:8b` | `qwen3:14b` |
| 10–12 GB | `qwen3:8b` | `qwen3:8b` (híbrido: el mismo para los dos modos) |
| 4–8 GB (esta laptop) | `qwen3:4b-instruct` | `qwen3:4b` |
| Sin GPU dedicada | `qwen3:1.7b` | `qwen3:4b` (lento) |

Con menos de 8 GB de RAM baja a los modelos pequeños. Antes de descargar comprueba que haya espacio (descarga + 2 GB de margen).

### ⚙️ Panel de Ajustes
- Botón **⚙️ Ajustes** en la barra lateral y en el menú del icono junto al reloj. Los mismos campos que el asistente, en 7 pestañas: *Tú, Modelos de IA, Obsidian, Voz, WhatsApp y teléfono, Autonomía, Avanzado*.
- **Se aplica al momento, sin reiniciar**: modelos (y los precarga en la GPU), voz, precisión de Whisper, WhatsApp (reinicia el bridge) y Heartbeat (lo enciende o apaga). Solo el puerto y el atajo global piden reiniciar, y lo indican.
- Se guarda en el `.env` activo: el del proyecto mientras EDITH corre desde el código; `%LOCALAPPDATA%\EDITH\.env` cuando no hay proyecto (la app instalada de la 15.3). Se conservan los comentarios y las demás claves.
- El Auth Token de Twilio se muestra como `••••••••`; si no se toca, se conserva.
- **Validación con mensajes claros**: rutas completas, números en formato internacional (8–15 dígitos; se aceptan espacios, guiones y paréntesis y se guardan normalizados), URL pública solo `https://`, horas `HH:MM`, rangos numéricos y puerto `auto` o 1024–65535.
- **Iniciar con Windows**: crea `HKCU\…\Run\EDITH` → `EDITH.exe --tray` (sin permisos de administrador). Con `--tray` EDITH arranca oculta en la bandeja.

### 🔒 Seguridad
- Las rutas que cambian ajustes, descargan modelos o crean carpetas exigen el token de la v0.0.7 y además solo aceptan peticiones de esta computadora (`Host` 127.0.0.1/localhost) y de la propia EDITH (`Origin` igual): otra web abierta en el navegador no puede cambiarlos y, **desde otro dispositivo, aunque tenga el token, Ajustes responde 403** (el chat sí funciona).
- Cada ajuste es una sola línea: los saltos de línea se rechazan, así nadie puede colar otra clave en el `.env` (p. ej. `REMOTE_ALLOW_SYSTEM_TOOLS=true`). Las claves que no son de Ajustes se ignoran.
- «Iniciar con Windows» solo se acepta desde la app de escritorio.

### 🔐 Limpieza del repositorio
- El commit `7446bb0` («Gran actualizacion 0.0.4») subió la bóveda a git, incluido `EDITH_p/.obsidian/plugins/obsidian-local-rest-api/data.json` con la **API key y las claves privadas de los certificados** del plugin Local REST API, y el repositorio de GitHub es público.
- Ahora ese archivo sale de git y `**/.obsidian/plugins/*/data.json` va al `.gitignore` (el archivo sigue en tu bóveda y el plugin funciona igual). Al fusionar la Fase 14 también salen de git las dos sesiones de `data/sessions/` (los archivos se conservan).

> [!danger] Pendiente tuyo
> Lo que ya se publicó sigue en el historial de GitHub: **regenera la API key y los certificados** en Obsidian → Ajustes → Local REST API, y actualiza la clave donde la uses (por ejemplo, la conexión MCP de Obsidian). Para borrarlo también del historial habría que reescribirlo (force push) o hacer privado el repositorio.

### 🐛 Corregido de paso
- **«Oye EDITH» ya no reintenta sin parar** si el micrófono está bloqueado o no hay servicio de voz (en la app de escritorio WebView2 puede no tenerlo): se pausa y el botón dice *«sin micrófono»* o *«sin servicio de voz»*; al pulsarlo vuelve a intentarlo. Los reintentos normales esperan cada vez más. (Era un pendiente de la v0.0.7.)
- El Heartbeat no podía volver a encenderse después de apagarlo.
- La app de escritorio guardaba el puerto que le tocó como si fuera tu ajuste: ahora usa `EDITH_RUNTIME_PORT` y tu `EDITH_PORT` queda intacto.

### 🔧 Piezas técnicas
| Archivo | Qué hace |
|---|---|
| `agent/setup/hardware.py` | GPUs (`nvidia-smi` + registro de Windows, separa la integrada), CPU, RAM, disco, Ollama y recomendación |
| `agent/setup/models.py` | Descargas con `/api/pull` de Ollama en segundo plano: progreso, cancelar y reanudar |
| `agent/setup/settings.py` | Esquema único de ajustes (asistente y panel), validación y guardado en `.env`; `setup.json` en `%LOCALAPPDATA%\EDITH` |
| `ide/setup_api.py` | `/api/setup/*` y `/api/settings`; aplica los cambios en vivo |
| `ide/static/setup.js` | Asistente y panel de Ajustes |
| `desktop/desktop_app.py` | Selector de carpetas nativo, `--tray`, «Ajustes» en el menú de la bandeja |

### 🧪 Pruebas
- **`python tests/test_fase_15_2.py`: 65/65** (Ollama simulado y `.env` temporal: nunca toca tus datos ni descarga nada). Recomendación por VRAM y GPU integrada vs dedicada; diagnóstico; asistente pendiente/completado; 7 secciones; token de Twilio enmascarado; números, URL y horas normalizados; comentarios del `.env` conservados; 8 valores inválidos rechazados con su mensaje (incluido el salto de línea); claves desconocidas ignoradas; nombre a la memoria; modelos y voz aplicados en vivo; descarga completa, una a la vez, pausa y error de Ollama; bóveda (crear 00-04, reconocer `.obsidian`, contar notas); otra web, otro puerto, sin token, `Host` ajeno y otro dispositivo → rechazados.
- **Tras fusionar con la v0.0.7**: `tests/test_seguridad.py` **78/78** y `tests/test_fases_9_11.py` **55/55**.
- **App de escritorio real con el token** (oculta con `--tray`, sin tocar la pantalla): 12/12. La ventana entra con su enlace (WebView2 guarda la cookie `HttpOnly`), sin token → 401, «Iniciar con Windows» crea y borra la entrada, otro origen → 403, salida ordenada y sin errores en el registro.
- **Navegador**: el asistente aparece solo en el primer arranque; diagnóstico real de esta laptop (Ryzen 5 8645HS, RTX 4050 de 6 GB —la Radeon integrada se descarta—, 30.3 GB libres, Ollama 0.34.4) → recomienda `qwen3:4b-instruct` + `qwen3:4b`, que ya están instalados; descarga con progreso, pausa y reanudación (siguió desde el 19 %); errores de validación (ruta relativa, URL `http://`, número inválido); números normalizados; token de Twilio enmascarado; resumen final y Ajustes con sus 7 pestañas.
- **App de escritorio**: modo escritorio detectado; «Iniciar con Windows» crea y borra la entrada de inicio con `--tray`; otro origen recibe 403; `--tray` arranca oculta y «Abrir EDITH» la muestra; **«Elegir…» abre el selector «Seleccionar carpeta» de Windows** en la bóveda actual; salida ordenada.
- **«Oye EDITH»**: micrófono bloqueado → se pausa sin reintentar; 3 fallos de red seguidos → se pausa; «no-speech» sigue escuchando.

### 📌 Pendiente
- Regenerar la API key y los certificados del plugin Local REST API (ver arriba).
- 15.3 · Empaquetado con PyInstaller: es lo que permitirá usar `%LOCALAPPDATA%\EDITH\.env` sin la carpeta del proyecto.
- El registro de modelos de Ollama fue muy lento en la prueba (~150 KB/s): la descarga se puede pausar y seguir otro día.

---

## v0.0.7 — 16/10/2026 · Endurecimiento de seguridad (Fase 14)
Commit `eded747` (rama `claude/inspiring-rhodes-a46533`), **fusionado en `main` el 16/10/2026** con `b3afff3`. Es el requisito para mover EDITH al servidor 24/7 (Fase 8). Riesgos y estado: [[Auditoria de Seguridad y Protecciones de EDITH]].

> [!note] Numeración
> Se pensó como v0.0.6, pero ese número ya lo usa la app de escritorio (Fase 15.1), así que sale como **v0.0.7**.

### 🔑 Token de acceso para la interfaz, la API y el chat
| Pieza | Archivo | Qué hace |
|---|---|---|
| Token | `agent/channels/security.py` | `EDITH_API_TOKEN` o `%LOCALAPPDATA%\EDITH\data\channels\api_token` (se genera solo, fuera de git) |
| Guardián | `ide/auth.py` | Middleware para HTTP y WebSocket: token, `Host` y `Origin` |
| Enlace | `python main.py --access-link` | Muestra `http://…/?token=…` para abrir EDITH desde otro dispositivo |

- **En la laptop no cambia nada**: al abrir `http://localhost:8000` o la app de escritorio, la interfaz recibe sola una cookie `HttpOnly` + `SameSite=Lax` (JavaScript no puede leerla). Si la petición llega por un túnel o proxy (`X-Forwarded-For`…) no entra sola. Se desactiva con `EDITH_LOCAL_AUTOLOGIN=false`.
- **Desde otro dispositivo**: se abre una vez el enlace con token; EDITH guarda la cookie y redirige a `/` **quitando el token de la URL**. Sin token se ve la página «🔒 EDITH está protegida».
- **App de escritorio**: la ventana entra con ese mismo enlace al arrancar, así no depende del auto-login.
- **Scripts**: cabecera `Authorization: Bearer <token>`.
- **Host permitido** en todas las peticiones (`localhost`, `127.0.0.1`, el host de `PUBLIC_BASE_URL` y `EDITH_ALLOWED_HOSTS`): bloquea el *DNS rebinding*. Para Tailscale o la red local hay que añadir el nombre o la IP a `EDITH_ALLOWED_HOSTS`.
- **Origin del mismo sitio** en `/ws/chat` y en todo `POST`/`PATCH`/`DELETE`: otra web (o una app en `localhost:3000`) no puede mandar órdenes con tu cookie.
- `X-Frame-Options: DENY`: nadie puede incrustar EDITH en un iframe para engañarte con el botón «Autorizar».
- **Sin cambios** en las rutas con autenticación propia: bridge de WhatsApp (`X-Edith-Bridge-Secret`), webhooks de Twilio (firma) y `/ws/voice` (token de un solo uso). El QR de WhatsApp sí pide ahora el token (es una pantalla de la interfaz).

### ✋ Confirmación humana antes de actuar
- Antes de `run_system_command` (PowerShell) y `open_application`, la interfaz muestra **«EDITH quiere ejecutar: … ¿Autorizas?»** con el comando exacto. El foco empieza en **Rechazar** (un Enter por accidente no autoriza), `Esc` rechaza y, sin respuesta, se rechaza sola a los **120 s**.
- El agente espera la respuesta por el WebSocket: el chat ahora lee mensajes mientras EDITH trabaja (cola de consultas + confirmaciones por pestaña; otra pestaña no puede autorizar lo que se pidió en esta).
- En la terminal (`python main.py`) se pregunta con `¿Autorizas? [y/n]`.
- Desde WhatsApp o el teléfono no hay a quién preguntar: esas acciones **se rechazan** (falla cerrado), aunque `REMOTE_ALLOW_SYSTEM_TOOLS=true`.
- `open_application` ya **no usa `shell=True`**: abre con `os.startfile` (ShellExecute), así `"notepad & del archivo"` ya no ejecuta el borrado. Los botones del panel *Laptop* solo lanzan las apps conocidas.
- PowerShell y los lanzadores `.cmd` (como el de VS Code) corren **sin ventana de consola** (`CREATE_NO_WINDOW`): la app de escritorio ya no tiene consola y antes parpadeaba una ventanita negra.

### 🧪 Contenido externo = dato no confiable
- La salida de `web_search`, `read_web_page`, archivos del workspace, notas de Obsidian, portapapeles y pantalla llega al modelo envuelta en `[DATO NO CONFIABLE · origen: …]` entre `<<<CONTENIDO_EXTERNO>>>` y `<<<FIN_CONTENIDO_EXTERNO>>>` (el texto no puede cerrar el bloque por su cuenta). El prompt de sistema explica que es solo información.
- En un turno donde entró contenido externo, también piden confirmación: guardar archivos o diagramas, escribir en Obsidian, recordatorios, portapapeles, volumen y pantalla.
- En un turno donde se leyeron datos privados (notas, archivos, portapapeles, pantalla), **consultar internet pide confirmación**: así una instrucción escondida no puede sacar tus notas en una URL. Investigar en la web (buscar + leer páginas) sigue sin preguntar.
- El modo Equipo marca igual la evidencia web que lee Scout.

### 🧼 HTML saneado con DOMPurify
- `ide/static/render.js`: todo el HTML de cada respuesta pasa por **DOMPurify 3.4.16** (cdnjs, versión fija + SRI) antes de insertarse. Fuera: `<script>`, `onerror`/`onclick`, enlaces `javascript:`, `<style>`, formularios y botones falsos, `id`/`name` (nada puede hacerse pasar por el modal), CSS con `url()` o `position: fixed`.
- **Imágenes externas bloqueadas**: `![x](https://…?d=datos)` se convierte en un enlace en vez de cargarse sola (era una vía para filtrar datos).
- Los enlaces se abren en otra pestaña (`noopener noreferrer`).
- Sin las librerías (sin internet) se muestra texto plano, nunca HTML sin sanear.
- También escapados en `app.js`: las fuentes consultadas (títulos y URLs de la web), el código de los diagramas Mermaid (ahora `securityLevel: 'strict'`) y los nombres de archivo.

### 🗂️ Historial fuera de git
- `data/sessions/` en `.gitignore` y fuera del repositorio con `git rm --cached` (los archivos locales se conservan). Las sesiones reales ya viven en `%LOCALAPPDATA%\EDITH\data\sessions` (v0.0.6).

### 🧪 Pruebas
- Las pruebas pasan a vivir en el repositorio (`tests/`, con `EDITH_HOME` en una carpeta temporal: nunca tocan tus datos): `python tests/test_seguridad.py` y `python tests/test_fases_9_11.py`.
- **78/78** de la Fase 14: sin token → 401; token incorrecto → 401; enlace con token → cookie y redirección sin token; en local entra sola, pero no tras un proxy; `Host` ajeno → 400; `Origin` ajeno, otro puerto local o sin `Origin` → 403; bridge y Twilio siguen entrando con su propia clave o firma; `/ws/chat` rechaza sin token u Origin ajeno; PowerShell espera confirmación sin ejecutarse; rechazado o caducado → no se ejecuta; autorizado → una sola vez; contenido marcado; herramientas sensibles tras contenido externo; `open_application` sin shell; PowerShell sin ventana; la app de escritorio entra con su enlace aunque el auto-login esté apagado; `data/sessions` fuera de git.
- **55/55** de las Fases 9-11 siguen pasando (WhatsApp, notas de voz reales, Twilio con firmas, relay, Heartbeat), antes y después de fusionar `main`.
- **Navegador** (EDITH real en el puerto 8010): DOMPurify 3.4.16 cargado con SRI, la cookie no es visible para JavaScript, 17/17 casos de HTML malicioso neutralizados (`onerror`, `javascript:`, `<script>`, `<style>`, overlay con `position:fixed`, `<svg onload>`, imagen externa, CSS `url()`, formulario falso) sin romper KaTeX (en línea, en bloque y `\sqrt` en SVG), los bloques de código ni las tablas. Con el modelo real, «Ejecuta en PowerShell el comando Get-Date» abrió el modal con `Get-Date`; al **Rechazar** no se ejecutó y EDITH lo explicó.

> [!warning] Al fusionar en `main`
> El commit saca `data/sessions/session_20260926_141522.json` de git. En el checkout principal ese archivo tiene cambios sin guardar: hay que copiar `data/sessions/` aparte antes de fusionar y restaurarla después, o git se niega a fusionar (o lo borra).

### 📌 Pendiente (siguiente ronda)
- Content-Security-Policy completa (requiere quitar los `onclick` en línea de `index.html`).
- Fijar la versión de `marked`, `mermaid` y `chart.js` (hoy sin versión fija en el CDN).
- Confirmación por WhatsApp («responde *sí* para ejecutar») para usar PowerShell desde remoto.
- Límite de peticiones por minuto y cifrado de secretos con DPAPI (ver la auditoría).
- `data/memory/long_term_profile.json` y `data/audio/` siguen en git y también son personales.
- ~~«Oye EDITH» reintenta sin parar si el micrófono está bloqueado (llena la consola con `not-allowed`).~~ Resuelto en v0.0.8.

---

## v0.0.6 — 16/10/2026 · EDITH como app de escritorio (Fase 15.1)
Commit `ab67c32` (ya en `main`). Diseño: [[Diseño de EDITH Setup (Aplicación de Escritorio)]].

### 🖥️ Qué cambia al abrir EDITH
| Antes | Ahora |
|---|---|
| Acceso directo a `run_desktop.bat` con consola negra | `EDITH.exe` sin consola (accesos del Escritorio y menú Inicio actualizados) |
| Cerrar la ventana apagaba todo | Cerrar la **oculta**; sigue junto al reloj con Heartbeat, WhatsApp y recordatorios |
| Abrirla dos veces = dos EDITH peleando por el puerto | Una sola instancia: abrirla otra vez muestra la ventana |
| Puerto 8000 fijo (fallaba si estaba ocupado) | 8000 o el siguiente libre (8001-8010); fijo con `EDITH_PORT` |
| Avisos firmados por "Windows PowerShell" | Avisos de **EDITH** con su logo |
| Datos dentro de la carpeta del código | Datos en `%LOCALAPPDATA%\EDITH` |
| Pedía el micrófono en cada arranque | WebView2 con perfil persistente: lo pide una vez |

**Menú de la bandeja:** Abrir EDITH · Nueva conversación · Pausar avisos 1 h · Abrir carpeta de datos · Salir.
**Atajo global:** `Win + Shift + E` muestra u oculta EDITH (`EDITH_HOTKEY` para cambiarlo, `off` para desactivarlo).

### 🗂️ Nueva carpeta de datos: `%LOCALAPPDATA%\EDITH`
| Carpeta | Contenido |
|---|---|
| `data\` | sesiones, memoria, ML, aprendizajes, canales (clave del bridge y sesión de WhatsApp), recordatorios, estado del Heartbeat, audio |
| `workspace\` | archivos compartidos con EDITH |
| `logs\` | `edith-desktop.log` y `whatsapp-bridge.log` |
| `webview\` | perfil de la ventana (permisos y preferencias) |

- La primera vez que EDITH se abre desde la carpeta del proyecto, **copia** (no mueve) `data/` y `workspace/`; los originales quedan como respaldo. No sobrescribe nada ni copia la caché de audio. Lo hace una sola vez.
- Nunca migra desde copias de trabajo temporales (`.claude\worktrees`).
- Ajustes: siguen en el `.env` del proyecto; la app instalada (15.3) usará `%LOCALAPPDATA%\EDITH\.env`.

### 🔧 Piezas técnicas
- `agent/paths.py`: rutas centralizadas (13 módulos actualizados) y migración.
- `desktop/desktop_app.py`: reescrito. Mutex de instancia única, evento "mostrar", evento "cerrar" (para el futuro desinstalador), servidor Uvicorn en hilo con apagado ordenado, pystray, `RegisterHotKey` y aviso de fin de sesión de Windows.
- `desktop/launcher/EDITH.cs` + `build_launcher.bat`: `EDITH.exe` compilado con el compilador C# de Windows (sin instalar nada). `install_edith.bat` lo compila y crea los accesos directos.
- `desktop/assets/edith-app.ico`: icono cuadrado de 16 a 256 px. El `edith.ico` original mide 101×106 y Windows lo mostraba en blanco.
- Avisos: EDITH se registra como remitente en `HKCU\Software\Classes\AppUserModelId\EDITH.Desktop` (sin administrador); si Windows lo rechaza, usa el remitente anterior.

### 🧪 Pruebas con la app real
**15/15 OK:** arranque sin consola (interfaz lista en 4–5 s); con el 8000 ocupado elige el 8001; ventana visible con el icono de EDITH; bandeja; atajo registrado; datos en `EDITH_HOME`; cerrar = ocultar con el servidor activo; segunda instancia sale en 1.7 s y muestra la original; `Win+Shift+E` oculta y muestra; salir ordenado y puerto liberado; sin errores en el registro. Además: las 55 pruebas de las Fases 9-11 siguen pasando, la migración (6 casos) funciona y Windows acepta los avisos con remitente EDITH.

> [!warning] Incidente durante las pruebas (corregido)
> Una instancia de prueba arrancó a las 10:35 dentro de la ventana del resumen matutino y **sobrescribió `01 - Diario/2026-10-16 - Resumen matutino.md`**, que tu EDITH había creado a las 08:15. Ambas versiones usaban los mismos datos (sin recordatorios ni tareas); cambian la redacción y el porcentaje de batería. La versión de las 08:15 puede recuperarse en Obsidian → *Ajustes → Recuperación de archivos*.
> **Corrección:** el Heartbeat ya no sobrescribe un resumen existente del mismo día. Esto también evita duplicados cuando haya una EDITH en la laptop y otra en el servidor (Fase 8). Las pruebas ahora aíslan también la bóveda.

---

## v0.0.5 — 15/10/2026 · WhatsApp, llamadas y autonomía proactiva (Fases 9, 10 y 11)
Commit `e1581e4` (ya en `main`). Configuración paso a paso: [[Guía de Configuración de Canales (WhatsApp, Teléfono y Heartbeat)]].

### 💬 Fase 9 — WhatsApp
| Pieza | Archivo | Qué hace |
|---|---|---|
| Bridge Baileys v7 | `bridges/whatsapp/bridge.mjs` | Enlaza WhatsApp por QR; reenvía chats privados autorizados a EDITH |
| Canal | `agent/channels/whatsapp.py` | Procesa texto/voz, formato WhatsApp, `/nuevo`, "ok" confirma alarmas |
| Notas de voz | `agent/channels/voice_notes.py` | `faster-whisper` local + transcodificación a Ogg/Opus con PyAV |
| Conversaciones | `agent/channels/conversations.py` | Un agente por contacto, con su memoria y herramientas limitadas |

### 📞 Fase 10 — Teléfono (Twilio Voice)
- `agent/channels/telephony.py`: modos `gather` (por turnos) y `relay` (ConversationRelay en tiempo real), llamadas de alarma con "pulsa 1".
- Rutas: `POST /api/voice/incoming`, `/api/voice/gather`, `/api/voice/result`, `/api/voice/alarm-ack` y `WS /ws/voice`.

### ⏰ Fase 11 — Heartbeat
- `agent/heartbeat/daemon.py` + `agent/tools/reminder_tools.py` + `agent/channels/notifier.py`.
- Avisos en la interfaz (con botón **Confirmar** para alarmas), toast de Windows y WhatsApp.
- Panel nuevo *Laptop > Canales y autonomía / Recordatorios*.

### 🛡️ Seguridad incluida desde el diseño
- Lista blanca obligatoria: sin `AUTHORIZED_PHONE_NUMBERS`, ningún canal remoto responde. Unifica `+521…` y `+52…` (México) y `+549…`/`+54…` (Argentina).
- Desde WhatsApp/teléfono EDITH **no** puede usar PowerShell, abrir apps, ver la pantalla ni el portapapeles (`REMOTE_ALLOW_SYSTEM_TOOLS=false`).
- Bridge: API solo en `127.0.0.1` con clave compartida comparada en tiempo constante; ignora grupos, estados y canales.
- Twilio: firma `X-Twilio-Signature` verificada contra la URL pública; desconocidos rechazados con `<Reject>`; token de un solo uso por llamada.
- **Corregido** `workspace_tools`: la comprobación `startswith` dejaba escapar a carpetas hermanas (`../workspace_x/…`). La auditoría lo había marcado como "protegido"; ahora sí lo está.

### 🐛 Problemas encontrados y resueltos durante las pruebas
- **La ventana de contexto se desbordaba**: el prompt de EDITH (~1500 tokens) + 23 herramientas (~2600) ya sumaban 4116 tokens, más que `num_ctx=4096`, así que Ollama rechazaba **cualquier** mensaje. Medido: con `qwen3:4b` a 8192 sigue 100 % en GPU y a la misma velocidad (63 tok/s), así que el valor por defecto pasa a **8192**. Además, si una charla larga desborda, se reintenta solo con el turno actual.
- **Fechas mal calculadas por el modelo pequeño**: "el viernes" acababa en un jueves y "en 30 minutos" en las 9:18 del día siguiente. Ahora el código resuelve "viernes 07:30", "mañana 9", "+30m"… y los recordatorios activos van en el contexto. Prueba con el modelo real: **12/12 en 3 corridas**.
- **faster-whisper 1.2.1 incompatible con PyAV 19** (`metadata_errors`): el audio se decodifica antes con PyAV.
- Faltaba `python-multipart` (sin él, Twilio no podía enviar sus formularios).
- Las 4 notas nuevas de la bóveda tenían acentos y emojis corruptos: reparadas (copia de las originales en el scratchpad de la sesión).

### 🧪 Pruebas
- 55/55 pruebas funcionales (recordatorios, WhatsApp, notas de voz reales, Twilio con firmas, relay, heartbeat, Obsidian, workspace).
- Integración real: EDITH arrancó el bridge, este obtuvo la lista blanca con la clave y mostró el QR en la interfaz; se detiene junto con EDITH.
- No probado aún: vinculación real de WhatsApp (requiere escanear el QR) y llamadas reales (requiere cuenta de Twilio y la URL pública de la Fase 8).

> [!warning] Aviso del Heartbeat al probar
> El disco `C:` tiene **28.8 GB libres de ~476 GB (6 %)**: EDITH avisará una vez al día mientras siga por debajo del 10 %.

---

## v0.0.4 — 15/10/2026 · Cuello de botella resuelto + LaTeX
Commit `0fd0bce` (ya en `main`).

### ⚡ El cuello de botella
`deepseek-r1:8b` no cabía en la RTX 4050 (6 GB): **25–30 % del modelo corría en el CPU** y además razonaba siempre (~1000 caracteres de `<think>` incluso para un "hola").

**Solución: dos variantes de Qwen3 4B, ambas 100 % en GPU**
| Rol | Modelo | Cuándo se usa |
|---|---|---|
| ⚡ Rápido | `qwen3:4b-instruct` | Charla, preguntas, ideas, herramientas |
| 🔬 Profundo | `qwen3:4b` (variante *Thinking*) | Matemáticas, lógica, depuración, "paso a paso" |

> [!warning] Trampa descubierta
> En Ollama, `qwen3:4b` ahora es la variante **Thinking-2507**: siempre razona y, si se le pide `think=false`, mezcla su razonamiento en inglés dentro de la respuesta. Por eso el modo rápido necesita la variante `-instruct`.

**Medición real (mismo prompt y herramientas de EDITH):**
| Mensaje | deepseek-r1:8b | v0.0.4 |
|---|---|---|
| "Hola, ¿cómo estás?" | 22.4 s al primer texto · 27.9 s total | **1.5 s · 3.4 s** |
| "¿Qué es Obsidian?" | 20.5 s · 32.9 s | **0.1 s · 1.4 s** |
| "Resuelve 2x + 3 = 11" | 15.0 s · 23.6 s | 11.5 s · 13.8 s (modo profundo) |
| Llamar herramienta (batería) | — | **0.4 s** |

> [!note] Coste del cambio de modo
> Las dos variantes (2.9 GB cada una) no caben juntas en 6 GB: pasar de rápido a profundo (o al revés) cuesta ~6–8 s. Por eso el modo automático solo piensa a fondo cuando de verdad hace falta.

### 🧠 Razonamiento a demanda
- `OLLAMA_THINK=auto`: EDITH decide en cada mensaje con una heurística instantánea (sin llamar al modelo).
- Botón junto a **Enviar**: 🧠 Auto → ⚡ Rápido → 🔬 Profundo (se recuerda entre sesiones).
- Cada respuesta indica si fue "⚡ rápido" o "🔬 razonado"; el indicador dice "Pensando a fondo" o "Respondiendo".
- El equipo Co-Working siempre razona a fondo.
- Nuevas variables: `OLLAMA_MODEL`, `OLLAMA_DEEP_MODEL`, `OLLAMA_THINK=auto`. Tu `.env` se actualizó (respaldo en `.env.backup-0.0.3`).

### 🧮 Fase 7 implementada: LaTeX y código profesional
- **Fórmulas con KaTeX**: $...$ en línea y $$...$$ en bloque (también `\(...\)` y `\[...\]`), protegidas antes de pasar por Markdown para que `\frac`, `_` y `*` no se rompan. Ejemplo de lo que ahora se ve en el chat:
  $$f'(x) = \frac{d}{dx}\left(x^3\right) + \frac{d}{dx}(2x) = 3x^2 + 2$$
- Los precios tipo "$5 y $10" **no** se confunden con fórmulas.
- **Doble clic** en una fórmula copia su LaTeX (listo para pegar aquí en Obsidian).
- **Bloques de código** con colores (highlight.js), nombre del lenguaje y botones **📋 Copiar** y **💾 Guardar** en el workspace.
- Tablas y citas con estilo; el formato enriquecido se ve **mientras EDITH escribe**.
- El prompt de sistema pide LaTeX para toda la matemática y bloques con lenguaje para el código.
- **La voz lee las fórmulas en español**: `$$\int_0^1 x^2\,dx = \frac{1}{3}$$` → "la integral de 0 a 1 de x al cuadrado dx igual a 1 entre 3".

### 🐛 Otras correcciones
- La interfaz ya no se queda con un `app.js` viejo en caché tras actualizar (cabecera `no-cache` + versión en los recursos).

---

## v0.0.3 — 15/10/2026 · Velocidad, Historial y Obsidian
Rama: `claude/edith-obsidian-updates-8056b1`

### ⚡ Velocidad
| Cambio | Archivo | Por qué acelera |
|---|---|---|
| Respuesta token a token en el chat (`content_chunk`) | `ide/server.py`, `ide/static/app.js` | Ves el texto mientras se genera, no al final |
| Voz sintetizada **después** de enviar la respuesta (`audio_ready`) | `ide/server.py` | El texto ya no espera a edge-tts |
| Precarga del modelo al iniciar (`warmup`) | `agent/providers/ollama_provider.py` | El primer mensaje no paga los ~10–14 s de carga |
| `keep_alive=30m` en cada petición | idem | El modelo no se descarga entre mensajes |
| `num_ctx` fijo (4096) y usado también en la precarga | idem, `agent/config.py` | Cambiar `num_ctx` obliga a Ollama a recargar el modelo |
| Prompt de sistema estable; contexto dinámico en mensaje aparte | `agent/core/reasoning_agent.py` | Ollama reutiliza la caché KV del historial |
| Instrucciones de herramientas compactas | `ollama_provider.py` | Miles de tokens menos que procesar por paso |
| Cliente HTTP persistente + reintento sin `tools`/`think` | `ollama_provider.py` | Menos latencia por conexión; no se repite el error |
| Flash attention + KV cache `q8_0` al arrancar Ollama | `ollama_provider.py` | Menos VRAM para el contexto |

**Medición en la laptop (RTX 4050 6 GB, `deepseek-r1:8b`):**

| `num_ctx` | Velocidad | Reparto CPU/GPU |
|---|---|---|
| 8192 | 14.7 tok/s | 36% / 64% |
| 4096 | 17.7 tok/s | 30% / 70% |
| 2048 | 19.5 tok/s | 25% / 75% |

> [!note] Límite actual
> El modelo no cabe entero en la GPU y siempre genera ~1000 caracteres de razonamiento, así que un "hola" sigue tardando ~20 s. Ver la recomendación de modelo en [[Plan de Cambios y Evolución de EDITH#⚡ Próxima mejora de velocidad recomendada]].

### 🗂️ Historial de conversaciones
- Nuevo panel en la barra lateral (reemplaza el `<select>` que no hacía nada al elegir una sesión).
- Agrupación por fecha, búsqueda (título + contenido), abrir, renombrar, eliminar y exportar a Obsidian.
- Abrir una conversación también **restaura el contexto del agente**: EDITH continúa donde se quedó.
- "Nueva conversación" crea una sesión real en el servidor.
- Las charlas vacías no aparecen; el título se toma del primer mensaje.
- API nueva: `GET /api/sessions?q=`, `GET/PATCH/DELETE /api/sessions/{id}`, `POST /api/sessions/new`, `POST /api/sessions/{id}/load`, `POST /api/sessions/{id}/obsidian`.
- Los ids de sesión se validan (no se puede leer ni borrar archivos fuera de `data/sessions`).

### 💎 Obsidian (Fase 2)
- `agent/tools/obsidian_tools.py`: crear, añadir, leer, buscar notas y archivar sesiones en `01 - Diario/`.
- EDITH las usa sola cuando se lo pides ("guarda esto en Obsidian", "¿qué tengo anotado sobre X?").
- Las rutas siempre quedan dentro de la bóveda.
- Si una charla ya archivada se renombra, la nota se reemplaza en lugar de duplicarse.
- Config: `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_AUTO_SYNC`.
- API: `GET /api/obsidian/status`, `GET /api/obsidian/search?q=`.

### 📋 Portapapeles (Fase 5, parcial)
- `agent/tools/clipboard_tools.py`: `read_clipboard` y `write_clipboard` (UTF-8, probado con acentos y emojis).

### 🔊 Voz offline (Fase 4)
- `agent/voice/voice_engine.py`: si edge-tts falla o tarda más de 20 s, se sintetiza con SAPI5 (`.wav`, voz en español si existe). Validado: durante las pruebas edge-tts no tenía red y el respaldo habló solo.

### 🐛 Correcciones
- `capture_screen` y `analyze_screen` estaban declaradas pero el agente no las ejecutaba ("herramienta desconocida").
- Gemini: ahora combina varios mensajes `system` en lugar de quedarse solo con el último.
- La nota del plan en Obsidian tenía los acentos y emojis corruptos (`�`); se reescribió en UTF-8 limpio.

### 🧪 Pruebas realizadas
- Agente con proveedor simulado: herramientas de Obsidian, streaming y prompt estable entre pasos y turnos.
- API de historial completa (listar, buscar, abrir, renombrar, exportar, borrar, ids maliciosos → 404).
- Ollama real con `deepseek-r1:8b`: herramientas nativas aceptadas, respuesta correcta.
- IDE en navegador: streaming visible, historial, abrir charla antigua, búsqueda.

### 🔀 Fusión con los cambios locales (commit `37115e6`)
Había trabajo sin commitear en la carpeta principal del proyecto. Se integró sin perder nada:
- **Sincronización en caliente con Obsidian** vía el plugin *Local REST API*: cada nota que escribe EDITH se empuja a Obsidian abierto (`api_synced: true`, probado en esta bóveda). Si Obsidian está cerrado, la conexión se corta a los 0.3 s y no se reintenta en 30 s, para no frenar a EDITH.
- Nueva herramienta `obsidian_list_notes` (notas más recientes primero).
- Los nombres de la primera versión (`create_obsidian_note`, `append_to_obsidian_note`, `read_obsidian_note`, `list_obsidian_notes`) siguen funcionando como alias, así que nada que los use se rompe.
- **Logo propio** (`ide/static/logo.png`, `edith.ico`) en la barra, mensajes y equipo Co-Working, en lugar del emoji 👓.
- No se tocaron los datos personales del checkout principal (sesión modificada y audios).

### ⏭️ Pendiente
- Fase 3 (micrófono nativo), automatización de teclado (Fase 5), Fase 6 (hotkey global + toasts).
- Guardar notas del día y diagramas directo en la bóveda.

---

## v0.0.2 — Motor ML
- `OnlineRouter`, `SemanticMemory` y `compress_history`.

## v0.0.1 — Base
- Agente de razonamiento, voz neural, IDE web, control de laptop y visión de pantalla.
