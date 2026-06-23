# Bitácora — Actualización automática de resultados

Runbook del sistema que jala los marcadores del Mundial 2026 y los escribe en
Firestore. Léelo antes de tocar nada o cuando el torneo cambie de fase.

> **Estado:** operativo desde el 23-jun-2026. Corre solo vía GitHub Actions.

---

## 1. Cómo funciona (resumen)

```
GitHub Actions (cron)  →  actualizar_resultados.py  →  football-data.org (API)
                                      │
                                      └──────────────→  Firestore (meta/partidos)
                                                              │
                                              app Streamlit lee y muestra
```

- **Fuente de datos:** football-data.org, competición `WC`, plan **Free** (10 req/min).
- **El robot** (`actualizar_resultados.py`) lee la BD, decide si vale la pena
  llamar a la API, jala los partidos del día, escribe los marcadores finales y
  rellena los equipos de eliminatorias.
- **La app** (`modules/ui_*.py`) solo lee de Firestore; no llama a la API.

---

## 2. Hechos clave (no olvidar)

| Cosa | Valor |
|------|-------|
| Zona horaria de `fecha` en la BD | **Hora local de México** (NO UTC), aunque coincida con el `utcDate` de la API |
| México respecto a UTC | **UTC−6** todo el año (sin horario de verano) |
| Documento de partidos | `meta/partidos` = `{ "lista": [ {…}, … ], "actualizado": iso }` |
| Campos de cada partido | `id`, `fase`, `grupo`, `jornada`, `equipo_local`, `equipo_visitante` (español), `fecha`, `bloqueado`, `marcador_real {local, visitante}` |
| Duración estimada de partido | `DURACION_ESTIMADA_MIN = 125` (90+15+8+12) en `modules/horario.py` |
| Tope de revisión por partido | `POLL_MAX_H = 6` h tras el kickoff (`actualizar_resultados.py`) |
| Cron (UTC) | `*/5 0-6,18-23` = **12:00–01:00 hora de México** |
| Puntuación | 5 pts exacto · 3 pts resultado · 0 (en `modules/scoring.py`) |

### Emparejado API ↔ BD
- **Fase de grupos:** por **par de equipos** (traducido a español y normalizado).
  Independiente de la hora. **Probado y confiable.**
- **Eliminatorias:** por **orden cronológico** dentro de cada fase (la API trae
  UTC y la BD hora de México, así que no se puede emparejar por hora).
  **Verificar en vivo la primera vez** (ver §5).
- Orientación del marcador: se alinea al `equipo_local`/`visitante` de la BD, así
  que aunque la API mande home/away invertidos, el marcador no se voltea.

---

## 3. Lógica de cuota (por qué casi no gasta llamadas)

El robot **solo llama a la API** si, al momento de correr, hay:
- (A) un partido de **hoy** que ya pasó su hora estimada de fin
  (`kickoff + 125 min`) y aún **no** tiene marcador, dentro de la ventana
  `[fin_estimado, kickoff + 6 h]`; o
- (B) un partido **eliminatorio** que arranca en menos de 12 h y cuyos equipos
  siguen en "Por definir".

Si no hay nada de eso → **0 llamadas** y termina. Una sola llamada cubre todos
los partidos del rango. Nunca re-revisa partidos ya finalizados.

---

## 4. Operación normal — qué revisar

**No hay que hacer nada en el día a día.** Para confirmar que está vivo:

1. GitHub → repo `Ivncitto/quiniela` → pestaña **Actions** → "Actualizar marcadores".
2. Abre la última corrida → paso "Ejecutar robot de resultados". Esperado:
   - `Partidos en BD: 104 …`
   - y `⏸️ Nada que revisar…` (fuera de horario) o `Sin cambios` / `💾 Guardado en meta/partidos (N cambios)`.
3. En la app, los marcadores aparecen en ≤10 min (caché) o con el botón
   "🔄 Actualizar".

**Disparar a mano** (cualquier momento): Actions → "Actualizar marcadores" →
**Run workflow**.

---

## 5. ⚠️ Cuando empiecen las ELIMINATORIAS (~28-jun-2026)

Aquí es donde hay que poner atención, porque el emparejado es por orden, no por
equipos. Pasos:

1. En cuanto football-data publique los partidos de 16avos (Round of 32), corre
   **en local** una prueba sin escribir:
   ```powershell
   python actualizar_resultados.py --test
   ```
2. Revisa la salida:
   - Líneas `🔵 16avos: equipos → X vs Y` → confirma que **X vs Y** sea el cruce real.
   - Si aparece `⚠️ 16avos: API trae N y la BD M (no se emparejan por orden)` →
     hay desajuste de conteo; **no confiar**, revisar manualmente.
3. Si el orden cuadra, deja que el robot lo escriba solo (o corre sin `--test`).
4. Repite la verificación para Octavos, Cuartos, Semifinal, Tercer Lugar y Final.

> Mapa de fases (stage de la API → fase de la BD), en `_STAGE_A_FASE`:
> `GROUP_STAGE→Grupos`, `LAST_32/ROUND_OF_32→16avos`, `LAST_16→Octavos`,
> `QUARTER_FINALS→Cuartos`, `SEMI_FINALS→Semifinal`, `THIRD_PLACE→Tercer Lugar`,
> `FINAL→Final`. Si la API usa otro nombre de stage, se ve un aviso
> `⚠️ stage desconocido` y hay que agregarlo al diccionario.

---

## 6. Comandos útiles (local)

Requiere `.streamlit/secrets.toml` con `[firebase]` y `[footballdata] token`.

```powershell
python actualizar_resultados.py --test      # 1 llamada, MUESTRA cambios, NO escribe (dry-run)
python actualizar_resultados.py --forzar     # 1 llamada y ESCRIBE (ignora el gating)
python actualizar_resultados.py --dry-run    # respeta el gating pero NO escribe
python actualizar_resultados.py              # modo normal (gating + escribe)
streamlit run app.py                          # ver la app (bloqueo + panel del día)
```

---

## 7. Problemas comunes y solución

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `[ERROR] No hay token` / `No hay credenciales` en Actions | Faltan secretos | Crear `FOOTBALL_DATA_TOKEN` y `FIREBASE_CREDENTIALS_JSON` en Settings → Secrets and variables → Actions |
| `errors: {plan: ...}` de la API | Plan no cubre la temporada | football-data Free SÍ cubre WC; si cambia, revisar plan |
| `⚠️ sin match en BD (grupos)` | Nombre de equipo nuevo/distinto | Agregar alias en `_EN_A_ES` dentro de `actualizar_resultados.py` |
| `⚠️ {fase}: API trae N y la BD M` | Conteo de eliminatorias no cuadra | Revisar manualmente en el panel admin; ajustar emparejado |
| Marcador volteado | Orientación | No debería pasar (se alinea a la BD); si pasa, revisar `_clave_equipo` |
| Las horas se ven corridas en la app | Cambió la zona de los datos | Ajustar `TZ_LOCAL` en `modules/horario.py` |
| Gasta muchas llamadas | Ventana mal calculada | Revisar `DURACION_ESTIMADA_MIN` y `POLL_MAX_H` |
| Se acaban los minutos de GitHub (repo privado) | Cron muy frecuente | Subir intervalo a `*/10`/`*/15` o hacer el repo público |

**Plan B siempre disponible:** capturar el marcador a mano en el **Panel Admin**
de la app. El robot no pelea con eso (si el marcador ya está y coincide, no hace nada).

---

## 8. Archivos del sistema

- `actualizar_resultados.py` — el robot.
- `modules/horario.py` — zona horaria, bloqueo por hora, estado, "partidos de hoy".
- `modules/ui_tablero.py` — bloqueo de pronósticos al kickoff.
- `modules/ui_tabla_general.py` — panel "Partidos de hoy".
- `modules/ui_admin.py` — captura manual (plan B) + horas en hora de México.
- `.github/workflows/resultados.yml` — cron y ejecución en Actions.
- `requirements-bot.txt` — dependencias del robot (sin Streamlit).

---

## 9. Pendientes / notas

- [ ] **Rotar la llave de Firebase** (se compartió una vez): Console → Cuentas de
      servicio → Generar nueva clave; actualizar el secreto `FIREBASE_CREDENTIALS_JSON`.
- [ ] Verificar emparejado de **eliminatorias** la primera vez (§5).
- [ ] Limpiar archivos basura del repo (`'`, `(ahora`, `5`, `cerrado`, `kickoff\``,
      `450`, `None`, `button`, etc.).
- Si cambian mucho los horarios de los partidos, **recalcular la franja del cron**
  (los inicios iban de 10:00 a 22:00 MX; por eso `0-6,18-23` UTC).

---

_Última actualización de esta bitácora: 23-jun-2026._
