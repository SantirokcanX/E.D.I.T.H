---
title: Centro de Mando E.D.I.T.H.
aliases: [Dashboard EDITH, Home EDITH]
tags:
  - edith
  - dashboard
  - home
created: 2026-10-15
updated: 2026-10-17
version: 0.1.2
---

# 🎛️ Centro de Mando: E.D.I.T.H.

> [!quote] "Even Dead, I'm The Hero" - Enhanced Dialectical Intelligence & Tactical Heuristics

Bienvenido a tu centro de control en **Obsidian**. Desde aquí puedes monitorear el estado de EDITH, sus notas de arquitectura, su diario de reflexiones y el progreso hacia su autonomía total.

---

## 🧭 Navegación Rápida

| Sección                      | Nota Principal                                                        | Descripción                                      |
| ---------------------------- | --------------------------------------------------------------------- | ------------------------------------------------ |
| 🧭 **Roadmap Maestro**       | [[Plan de Cambios y Evolución de EDITH]]                              | Plan de 15 fases tácticas de desarrollo          |
| 📦 **App de escritorio**     | [[Diseño de EDITH Setup (Aplicación de Escritorio)]]                  | Instalador `EDITH-Setup.exe` y app nativa        |
| ⚙️ **Configurar canales**    | [[Guía de Configuración de Canales (WhatsApp, Teléfono y Heartbeat)]] | Activar WhatsApp, llamadas y Heartbeat           |
| 🛡️ **Seguridad**            | [[Auditoria de Seguridad y Protecciones de EDITH]]                    | Riesgos, mitigaciones y Fase 14                  |
| 🖥️ **Servidor & Teléfono**  | [[Arquitectura Servidor 24-7 y Comunicaciones (WhatsApp y Telefono)]] | Blueprint de PC 24/7, WhatsApp y llamadas VoIP   |
| 📜 **Bitácora de Versiones** | [[Registro de Cambios de EDITH]]                                      | Historial técnico de commits, benchmarks y fixes |
| 📓 **Diario de Charlas**     | `01 - Diario/`                                                        | Conversaciones archivadas automáticamente        |
| 🧠 **Conocimiento Atómico**  | `03 - Conocimiento/`                                                  | Notas y mapas conceptuales generados por EDITH   |
| 🧩 **Heurísticas y Memoria** | `04 - Memoria EDITH/`                                                 | Reglas aprendidas y auto-corrección de errores   |

---

## ⚡ Estado Actual del Sistema (v0.1.2)

```mermaid
pie title Distribución de Capacidades
    "Completadas (Fases 1, 2, 4, 7, 9, 10, 11)" : 7
    "En configuración (Fase 8)" : 1
    "En marcha (Fases 3, 14 y 15)" : 3
    "Planificadas (Fases 5, 6, 12, 13)" : 4
```

- **Motor IA**: `qwen3:4b-instruct` (modo rápido ~1 s) / `qwen3:4b Thinking` (modo profundo).
- **Voz**: Neural `edge-tts` (Elvira, Dalia, Ximena, Salomé y «Viernes») + SAPI5 offline de respaldo. «Oye EDITH» con Whisper local (v0.0.10).
- **Sentidos**: Screen Vision (captura completa y ventana) + LaTeX KaTeX + Highlight.js.
- **Almacenamiento**: Bóveda Obsidian `EDITH_p` con auto-sync en tiempo real.
- **Canales (v0.0.5)**: WhatsApp con notas de voz, llamadas Twilio (falta URL pública) y Heartbeat con recordatorios, alarmas y resumen matutino.
- **App de escritorio (v0.0.6, v0.0.8 y v0.0.9)**: `EDITH.exe` con icono junto al reloj, asistente de primer arranque y panel ⚙️ Ajustes. Desde la v0.0.9 se empaqueta y funciona sin la carpeta del proyecto ni Python.
- **Seguridad (v0.0.7 y v0.1.0)**: token de acceso, permiso antes de actuar (también por WhatsApp), respuestas saneadas, CSP estricta, secretos cifrados con DPAPI y límites de peticiones.
- **Nuevo en v0.1.0**: teclado, navegador propio (Edge), Home Assistant, calendario y correo, fotos y documentos por WhatsApp, visión local, LaTeX numerado, ▶ Ejecutar, aviso al terminar tareas largas e instalador `EDITH-Setup.exe`.
- **Nuevo en v0.1.2**: archivos de cualquier formato en el chat (📎, arrastrar o pegar) y por WhatsApp; EDITH los lee y hace lo que le pidas. Desde la v0.1.1, abrir una versión nueva reemplaza a la vieja que siguiera abierta.

---

## 🎯 Próximos 3 Grandes Objetivos

```mermaid
graph LR
    O1["🖥️ 1. PC Servidor 24/7 (Tailscale)"] --> O2["💬 2. WhatsApp (Notas de Voz)"]
    O2 --> O3["📞 3. Llamadas Telefónicas (Twilio)"]
```

1. **🖥️ Home Server en PC de Escritorio**:
   - Dejar de depender de la batería de la laptop.
   - Acceso remoto cifrado mediante malla Tailscale desde cualquier lugar.
2. **💬 WhatsApp Táctico**:
   - Enviar y recibir notas de voz sintetizadas con la voz de EDITH directamente en tu WhatsApp.
   - Recordatorios y alertas proactivas a tu celular.
3. **📞 Telefonía en Tiempo Real**:
   - Llamar a EDITH por teléfono o que ella te llame para urgencias y alarmas críticas.

---
*Centro de Mando actualizado automáticamente por E.D.I.T.H. - 15/10/2026.*