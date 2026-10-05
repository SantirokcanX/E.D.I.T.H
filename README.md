# 👓 E.D.I.T.H.
### *Enhanced Dialectical Intelligence & Tactical Heuristics*
**Agente de IA con Razonamiento Abstracto, Búsqueda Web, Co-Working Multi-Agente, Memoria Persistente, Voz Neural e IDE Web.**

---

## 🌟 Novedades y Capacidades

1. **🧠 Pensamiento Abstracto & Primeros Principios:**
   - Deconstrucción ontológica de problemas en sus leyes y fundamentos esenciales.
   - Analogías interdisciplinarias ricas (física, computación, filosofía, biología).
   - Metacognición dialéctica: contrasta premisas y audita sus propios sesgos antes de responder.

2. **🎙️ Voz Neural Táctica (EDITH Voice):**
   - Síntesis de voz neural ultra-natural y fluida mediante `edge-tts` (voz serena, inteligente y precisa: `es-MX-DaliaNeural`).
   - Sin coste, sin límites y sin claves API requeridas.
   - Alternable mediante `/voice on|off` en consola o botón en el IDE.

3. **👥 Co-Working Multi-Agente & Espacio Compartido:**
   - **EDITH (Líder & Estratega):** Deconstruye el objetivo, coordina y realiza la síntesis maestra.
   - **Scout (Investigador Web):** Rastreos en tiempo real con DuckDuckGo y lectura de artículos.
   - **Auditor (Crítico Dialéctico):** Cuestiona vacíos, sesgos e inconsistencias lógicas.
   - **Workspace Compartido (`workspace/`):** Creación y edición colaborativa de archivos, informes y código entre tú y el equipo de IA.

4. **💾 Memoria Persistente entre Sesiones:**
   - Guarda automáticamente cada conversación en `data/sessions/`.
   - Recuperación de sesiones históricas (`/sessions`, `/load <id>`, `/new`).
   - Memoria semántica a largo plazo de hechos clave sobre ti y tus proyectos.

5. **🔁 Auto-Corrección y Aprendizaje de Errores:**
   - Si una herramienta o razonamiento falla, EDITH formula y registra una heurística preventiva en `data/learnings/error_learnings.json`.
   - Inyecta estas reglas en sesiones futuras para no cometer el mismo error dos veces.

6. **💻 EDITH Studio (IDE Web Integrado):**
   - Interfaz visual futurista y táctica con editor de código, explorador de archivos del `workspace/`, panel de razonamiento en vivo, monitor de equipo y reproductor de voz.

7. **🔓 Sin Filtros Artificiales:**
   - Comunicación directa y sin intermediarios ni censura moral impuesta en el código.

---

## 📁 Estructura del Proyecto

```text
EDITH_proyecto/
├── data/
│   ├── sessions/             # Historial de sesiones guardadas en JSON
│   ├── learnings/            # Base de datos de auto-corrección y errores superados
│   ├── memory/               # Perfil y memoria a largo plazo
│   └── audio/                # Archivos de voz sintetizados
├── workspace/                # Espacio de trabajo compartido (archivos, reportes, código)
├── ide/
│   ├── server.py             # Servidor FastAPI y WebSockets de EDITH Studio
│   └── static/               # Frontend web (index.html, styles.css, app.js)
├── agent/
│   ├── voice/                # Motor de voz neural (VoiceEngine)
│   ├── memory/               # Gestor de persistencia de sesiones (MemoryManager)
│   ├── learning/             # Sistema de auto-aprendizaje (ErrorLearner)
│   ├── coworking/            # Orquestador del equipo multi-agente (CoworkingTeam)
│   ├── tools/                # Herramientas de búsqueda y workspace
│   ├── providers/            # Proveedores de LLM (Ollama y Gemini)
│   ├── core/                 # Razonamiento abstracto y ciclo ReAct
│   └── cli/                  # Interfaz de terminal interactiva Rich
├── main.py                   # Punto de entrada unificado
├── run.bat                   # Lanzador de la Consola Interactiva
└── run_ide.bat               # Lanzador de EDITH Studio (Web IDE)
```

---

## 🚀 Cómo Ejecutar

### 1. Iniciar EDITH Studio (IDE Web)
Simplemente haz doble clic en `run_ide.bat` o ejecuta:
```powershell
.\run_ide.bat
```
*(Se abrirá automáticamente tu navegador en `http://localhost:8000` con el editor, explorador de workspace y chat).*

### 2. Iniciar la Consola Interactiva (CLI)
Si prefieres la terminal:
```powershell
.\run.bat
```

### 3. Ejecución directa por línea de comandos:
- Para iniciar el IDE en un puerto específico:
  ```powershell
  .venv\Scripts\python main.py --ide --port 8080
  ```
- Para iniciar la consola directamente en modo Co-Working:
  ```powershell
  .venv\Scripts\python main.py --coworking
  ```

---

## 💬 Comandos Disponibles en la Consola

- `/coworking [on|off]`: Alterna entre el modo directo y el equipo multi-agente (EDITH + Scout + Auditor).
- `/voice [on|off]`: Activa o silencia la locución neural de EDITH.
- `/sessions`: Lista todas las sesiones previas guardadas.
- `/load <id>`: Reanuda una conversación histórica.
- `/new`: Inicia una conversación limpia preservando los hechos recordados.
- `/learnings`: Muestra las reglas y lecciones aprendidas de errores anteriores.
- `/provider <ollama|gemini>`: Alterna entre modelos locales y en la nube.
- `/model <nombre>`: Cambia el modelo activo en caliente.
- `/clear`: Limpia la sesión actual.
- `/help`: Muestra la lista de comandos.
- `/exit`: Pone a EDITH en reposo.
