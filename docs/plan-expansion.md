# Plan de Expansión Estratégica: PortMaster 2.0 (Ecosistema Completo de Desarrollo)

Fecha: 14 de agosto de 2026.  
Rama: `feature/expansion-plan`

Este documento define la evolución de PortMaster desde un orquestador de *stacks* locales hacia una **plataforma integral de productividad, diagnóstico, automatización y control del entorno de desarrollo local**.

---

## 1. Arquitectura y Nuevas Dimensiones

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PORTMASTER ECOSYSTEM                              │
├───────────────────────────────┬───────────────────────────────┬─────────────┤
│ 1. ORQUESTACIÓN DE STACK      │ 2. RUNNER DE TAREAS           │ 3. TÚNELES  │
│ - Topological sort & health   │ - Scripts y pipelines locales │ - ngrok     │
│ - env_file & pre_start hooks  │ - Inyección de variables      │ - cloudflare│
│ - Monorrepos (pnpm/turbo/uv)  │ - portmaster run <tarea>      │ - share     │
├───────────────────────────────┼───────────────────────────────┼─────────────┤
│ 4. MULTI-PROYECTO COMPUESTO   │ 5. HIGIENE Y MANTENIMIENTO    │ 6. MCP & AI │
│ - Inclusión inter-repositorios│ - Docker prune inteligente    │ - Tools MCP │
│ - Grupos de servicios         │ - Detección de zombies        │ - AI Agent  │
│ - Matriz de colisiones        │ - portmaster clean            │   Diagnosis │
└───────────────────────────────┴───────────────────────────────┴─────────────┘
```

---

## 2. Especificación de Fases y Módulos

### Fase 1: Variables de Entorno y Hooks del Stack
*   **Módulo**: [`portmaster/config.py`](file:///a:/Proyectos/PortMaster/portmaster/config.py), [`portmaster/runner.py`](file:///a:/Proyectos/PortMaster/portmaster/runner.py)
*   **`env_file`**: Carga de `.env`, `.env.local` o lista ordenada sin dependencias externas.
*   **Hooks de Ciclo de Vida**:
    *   `pre_start`: Ejecución síncrona preparatoria (ej. migraciones, build).
    *   `post_start`: Ejecución tras confirmación de salud (ej. `seed`, notificación).
*   **Bóveda Global (`~/.portmaster/env.global`)**: Herencia automática de variables comunes entre proyectos.

### Fase 2: Runner de Tareas y Scripts de Proyecto (`portmaster run`)
*   **Módulo**: [`portmaster/scripts.py`](file:///a:/Proyectos/PortMaster/portmaster/scripts.py), [`portmaster/cli.py`](file:///a:/Proyectos/PortMaster/portmaster/cli.py)
*   **Declaración en `stack.yaml`**:
    ```yaml
    scripts:
      test: pytest tests/ -v
      lint: ruff check .
      migrate: alembic upgrade head
      check: [lint, test]  # Pipeline secuencial o paralelo
    ```
*   **Comando CLI**: `portmaster run <script>` ejecuta en el `cwd` y contexto de variables del proyecto.

### Fase 3: Exposición Segura y Compartir (`portmaster share`)
*   **Módulo**: [`portmaster/tunnel.py`](file:///a:/Proyectos/PortMaster/portmaster/tunnel.py), [`portmaster/cli.py`](file:///a:/Proyectos/PortMaster/portmaster/cli.py)
*   **Integración de Túneles**: Detección y manejo de binarios locales (`cloudflared`, `ngrok`, `tailscale`).
*   **Comando CLI & Web**: `portmaster share web` genera URL pública temporal, QR en consola y botón directo en la UI web.

### Fase 4: Orquestación Multi-Proyecto y Dependencias Inter-Repositorios
*   **Módulo**: [`portmaster/registry.py`](file:///a:/Proyectos/PortMaster/portmaster/registry.py), [`portmaster/runner.py`](file:///a:/Proyectos/PortMaster/portmaster/runner.py)
*   **Proyectos Compuestos (`includes`)**:
    ```yaml
    # frontend/stack.yaml
    name: frontend
    includes:
      - ../backend-api  # Levanta backend automáticamente si no está corriendo
    ```
*   **Grupos de Proyectos**: `portmaster group up <nombre_grupo>` y matriz preventiva de colisión de puertos.

### Fase 5: Higiene del Sistema y Docker (`portmaster clean / prune`)
*   **Módulo**: [`portmaster/doctor.py`](file:///a:/Proyectos/PortMaster/portmaster/doctor.py), [`portmaster/docker.py`](file:///a:/Proyectos/PortMaster/portmaster/docker.py)
*   **Limpieza Asistida**:
    *   `portmaster docker prune`: Remueve contenedores parados, redes no usadas y volúmenes huérfanos.
    *   `portmaster doctor --fix`: Auto-reparación (iniciar Docker Desktop, purgar procesos zombies huérfanos).

### Fase 6: Servidor MCP e Integración con Agentes de IA
*   **Módulo**: [`portmaster/mcp.py`](file:///a:/Proyectos/PortMaster/portmaster/mcp.py)
*   **Herramientas MCP Expuestas**:
    *   `list_services`: Estado de salud, puertos y procesos.
    *   `restart_service`: Reinicio atómico de un servicio específico.
    *   `get_service_logs`: Consulta de logs con filtrado de errores para depuración autónoma.
    *   `free_port`: Liberación de puertos conflictivos.

### Fase 7: Detección Avanzada (Monorrepos, `uv`, Frameworks) y UI Web Polish
*   **Módulo**: [`portmaster/detect.py`](file:///a:/Proyectos/PortMaster/portmaster/detect.py), [`portmaster/web/`](file:///a:/Proyectos/PortMaster/portmaster/web)
*   Detección de `pnpm-workspace.yaml`, `turbo.json`, `uv.lock`, Astro (`4321`), Vite (`5173`).
*   UI Web: Pausa y búsqueda en streaming de logs, editor de `stack.yaml` y disparador de tareas `run`.

---

## 3. Principios de Implementación

1.  **Zero Bloat (Lazy Senior Dev / Ponytail)**: No añadir dependencias pesadas innecesarias. El soporte de túneles y MCP utiliza subprocesos y protocolos JSON-RPC estándar sobre stdio.
2.  **Seguridad y Aislamiento**: Toda API expuesta mantiene validación de cabecera `Host` y autenticación de token estricta.
3.  **Compatibilidad Multiplataforma**: Verificación en Windows (pwsh/cmd), Linux (bash) y macOS (zsh).
