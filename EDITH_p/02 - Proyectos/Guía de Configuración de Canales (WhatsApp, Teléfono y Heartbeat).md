---
title: Guía de Configuración de Canales (WhatsApp, Teléfono y Heartbeat)
aliases: [Configurar WhatsApp EDITH, Configurar Twilio EDITH]
tags:
  - edith
  - guia
  - whatsapp
  - telefonia
  - heartbeat
created: 2026-10-15
version: 0.0.5
---

# ⚙️ Configurar los canales de EDITH (v0.0.5)

Todo se configura en el archivo `.env` de la carpeta del proyecto y se aplica al reiniciar EDITH. Plan: [[Plan de Cambios y Evolución de EDITH]] · Seguridad: [[Auditoria de Seguridad y Protecciones de EDITH]].

> [!important] Paso 0 — obligatorio para WhatsApp y teléfono
> ```ini
> AUTHORIZED_PHONE_NUMBERS=+52155XXXXXXXX
> ```
> Sin esta lista **nadie** puede hablar con EDITH por WhatsApp ni por teléfono. El primer número es también a quien EDITH avisa (o define `OWNER_PHONE_NUMBER`).

---

## 💬 WhatsApp (Fase 9)

> [!warning] Usa un número secundario
> El bridge usa **Baileys**, un cliente no oficial de WhatsApp. Lo recomendable es vincular un número que no sea el principal: WhatsApp puede restringir cuentas que usan clientes no oficiales.

1. En `.env`:
   ```ini
   WHATSAPP_ENABLED=true
   WHATSAPP_VOICE_REPLIES=auto   # nota de voz cuando tú mandas nota de voz
   WHISPER_MODEL=small           # la 1.ª nota de voz descarga el modelo (~460 MB)
   ```
2. Reinicia EDITH. Ella arranca el bridge sola (necesita Node 20+; ya instalado).
3. Abre **Laptop → Canales y autonomía**: aparece un QR.
4. En el celular de EDITH: **WhatsApp → Dispositivos vinculados → Vincular dispositivo** y escanea.
5. Desde tu número autorizado escríbele "hola" o mándale una nota de voz.

| Escribes | EDITH hace |
|---|---|
| Cualquier texto | Responde con su memoria de esa conversación |
| Nota de voz | La transcribe y responde con nota de voz + texto |
| `/nuevo` | Empieza una conversación limpia |
| `ok` / `listo` | Confirma la última alarma crítica (no te llama) |

*Si prefieres ver el QR en una terminal:* `run_whatsapp_bridge.bat`. Registro del bridge: `data/channels/whatsapp/bridge.log`.

---

## 📞 Teléfono con Twilio (Fase 10)

> [!info] Depende de la Fase 8
> Twilio tiene que poder llegar a EDITH por internet con HTTPS (`PUBLIC_BASE_URL`). Eso llega con el servidor 24/7 (Tailscale Funnel o Cloudflare Tunnel). Mientras tanto todo está listo y probado localmente.

1. Crea una cuenta en Twilio y compra un número con voz.
2. En `.env`:
   ```ini
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_PHONE_NUMBER=+1...
   PUBLIC_BASE_URL=https://tu-servidor.ts.net
   TWILIO_VOICE_MODE=gather      # o relay (tiempo real)
   ```
3. En la consola de Twilio → tu número → *A call comes in* → **Webhook** `POST {PUBLIC_BASE_URL}/api/voice/incoming`.
4. Llama desde tu número autorizado. Cualquier otro número es rechazado sin contestar.

| Modo | Cómo se siente | Requisito |
|---|---|---|
| `gather` | Por turnos: hablas, EDITH contesta | Ninguno extra |
| `relay` | Conversación fluida, puedes interrumpir | Activar **ConversationRelay** en la consola de Twilio (no es inmediato) |

**Alarmas por llamada**: una alarma crítica sin confirmar en `ESCALATE_AFTER_MINUTES` (10) hace que EDITH te llame; pulsas **1** para confirmar.

---

## ⏰ Heartbeat (Fase 11) — activo por defecto

```ini
HEARTBEAT_ENABLED=true
HEARTBEAT_MINUTES=15              # salud de la laptop y tareas de Obsidian
MORNING_BRIEFING_TIME=08:00       # vacío = sin resumen
QUIET_HOURS=23:00-07:00           # de noche solo lo crítico
HEARTBEAT_NEWS_TOPICS=inteligencia artificial,tecnología
NOTIFY_CHANNELS=ui,toast,whatsapp
```

- **Recordatorios**: pídeselos a EDITH ("recuérdame mañana a las 9…", "alarma urgente el viernes 7:30, si no contesto llámame") o usa **Laptop → Recordatorios**.
- **Tareas de Obsidian** que EDITH vigila: `- [ ] Entregar informe 📅 2026-10-20` (también `due:: 2026-10-20` o `@2026-10-20`).
- **Resumen matutino**: llega por WhatsApp/interfaz y se guarda en `01 - Diario/AAAA-MM-DD - Resumen matutino`.

---

## 🛡️ Opciones de seguridad

| Variable | Por defecto | Efecto |
|---|---|---|
| `REMOTE_ALLOW_SYSTEM_TOOLS` | `false` | Si es `true`, desde WhatsApp/teléfono EDITH podría ejecutar PowerShell y abrir apps. **No recomendado** hasta la Fase 14 |
| `AUTHORIZED_PHONE_NUMBERS` | vacío | Vacío = canales remotos cerrados |
