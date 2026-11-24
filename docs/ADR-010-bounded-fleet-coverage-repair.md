# ADR-010 — INT-010 · Reparación acotada de cobertura de flota

**Estado:** implementación experimental en PR borrador, sin autorización para merge ni producción. **Ámbito empresarial:** DESSET en todo el Perú; DESSET prime requiere un contrato operativo propio. **Doctrina:** [ASI v3.3](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10), aplicación específica, no una redefinición normativa. **Base:** PR #21 INT-009.1, SHA `ef7f733540ee1f1162d2c97098b2e3908cb1d6e2`. [Expediente Notion](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Problema detectado

La heurística de inserción `fleet-insertion-v0.1` decide en un orden fijo. Puede asignar un pedido a un vehículo que impide atender otro, aun cuando ambos cabrían conjuntamente en una ruta diferente. Contraejemplo sintético existente: **1 de 2 pedidos** servidos por heurística frente a **2 de 2** en solución exacta. Los lotes superiores a los límites exactos (4 vehículos/6 pedidos) necesitaban otra forma de recuperar cobertura.

## Solución específica

`optimize_fleet_repaired` ejecuta **sin cambios** el algoritmo de inserción y, si quedan pedidos fuera:

1. Examina cada pedido no asignado y una asignación activa candidata para extraer temporalmente un pedido atendido.
2. Para cada vehículo destinatario con hasta cinco trabajos después de la pareja, calcula mediante **INT-007 exacto** una secuencia que incluya **ambos** pedidos: el extraído y el pendiente, más los que ya atendía ese vehículo. Esto permite encontrar dos pedidos factibles conjuntamente aunque ninguno tenga ruta individual desde ese origen.
3. Si el vehículo donante no es el receptor, revalida su secuencia restante: un arco intermedio puede desaparecer o ser inaccesible en una matriz dirigida dispersa. Si no es factible, se rechaza la modificación.
4. Solo considera candidatos que conservan **todos** los pedidos inicialmente servidos y añaden **uno**. Entre los que sirven la misma cantidad, elige menor tiempo total estimado; desempata por IDs.
5. Acepta hasta dos rondas y como máximo **48 evaluaciones exactas por ronda**; si no encuentra mejora dentro del límite, devuelve el plan original sin modificación. La heurística puede seguir siendo subóptima.

Para lotes pequeños `optimize_fleet_adaptive` sigue usando el óptimo exacto existente. Para lotes mayores invoca la heurística con reparación: el plan conserva el nombre de algoritmo del método utilizado para dejar trazabilidad. No se cambia el objetivo lexicográfico existente: **primero máxima cantidad servida, luego menor tiempo estimado**. Es posible que aumente el tiempo global al lograr atender más pedidos.

## Alcance de pruebas y falsabilidad

- **RED:** las pruebas nuevas de mejora fallan en el código anterior porque `fleet_repair` no existía y la heurística daba 6/7 o 1/2. Este fallo demuestra nueva capacidad ausente, no una regresión antigua.
- **GREEN:** pruebas de casos conocidos (2/2 y 7/7), dos rondas, 40 matrices asimétricas dispersas aleatorias, invariante de capacidad, precedencia, unicidad, arcos, duraciones y determinismo al permutar la entrada.
- **Mutación localizada:** al deshabilitar el solucionador del receptor, el test registra pérdida del pedido recuperado; código restaurado. No afirma puntuación global de mutantes.
- **Comparación pareada:** benchmark sintético semillado de 24 instancias de 7, 16 y 32 pedidos con exactamente las mismas matrices en ambos algoritmos; contabiliza decisiones mejoradas y tiempo local. Ninguna instancia representa cartografía del Perú ni tiempos observados.
- **Cobertura y CI por SHA:** solo declarar PASS después de leer ejecución oficial de GitHub Actions; el script de benchmark **no** se ejecuta en CI, salvo que se indique y verifique posteriormente.

## Limitaciones y condiciones de rechazo

No calcula mapas, latencia del servicio OSRM, tráfico ni ETAs. No soporta ventanas horarias, turnos, horarios de comercio, compatibilidad de vehículos, preferencias, costes monetarios, logística interprovincial ni despacho en vivo. La reparación solo cambia un pedido asignado por un par; no alcanza cadenas de intercambios arbitrarias y se salta vehículos con seis o más trabajos al ampliar. El límite de 48 evaluaciones prioriza reproducibilidad y tiempo de cálculo, no una garantía matemática de calidad o SLA. El benchmark es local, secuencial y sintético; **no** constituye p95/p99, mejora operativa nacional ni afirmación de superiority frente a OR-Tools/PyVRP/VROOM.

**Decision:** `candidate_decision=BLOCKED` para integración/producción; requeridos OSRM con PBF real nacional y licencia, benchmarking operacional, revisión independiente y branch protection. No merge, despliegue, secrets, DNS ni releases.
