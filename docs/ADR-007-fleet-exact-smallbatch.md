# ADR-007 — Optimización coordinada de flota pequeña (INT-008)

**Decisión:** prototipo propuesto, PR en borrador, no autorizado para producción.

**Seguimiento:** [INT-008 · Issue #15](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/15).

**Trazabilidad:** [Notion DESSET Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda) · [ASI v3.3 — doctrina maestra](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10) · [PR #14 / INT-007](https://github.com/M0-coder/DESSET-Intelligence-Core/pull/14). La doctrina define normas universales, esta ADR solo describe decisiones específicas del proyecto.

## Objetivo verificable

Coordinar **múltiples vehículos** y pedidos de recogida→entrega usando una matriz **dirigida** de segundos estimados ya calculados. Cada pedido se sirve exactamente una vez o se informa no asignado; cada vehículo tiene capacidad y presupuesto de duración opcional. **Prioridad lexicográfica explícita:** (1) maximizar número de pedidos servidos, (2) minimizar suma de segundos de recorrido entre los vehículos usados. Empates deterministas por orden de IDs. No afirmar minimización de coste monetario, justicia, demanda o SLA. No asume que usar más repartidores sea siempre mejor; los vehículos inactivos quedan fuera del resultado.

## Algoritmo y límites

1. Se fijan IDs y nodos, capacidades y tiempos dirigidos; arcos ausentes son imposibles, sin imputación.
2. Para cada uno de hasta **4 vehículos** y cada subconjunto de hasta **6 pedidos** se calcula un recorrido óptimo factible con el motor exacto INT-007, con precedencia de recogida antes de entrega.
3. Programación dinámica por bitmask asigna subconjuntos disjuntos a vehículos. Ordena resultados por cobertura de pedidos y coste estimado. No duplica un pedido entre vehículos.
4. Se devuelven rutas activas, pedidos no asignados, total de pedidos servidos y segundos estimados. La complejidad crece exponencialmente; no utilizar para grandes volúmenes sin evaluación y otro algoritmo escalable.

La formulación no representa ventanas horarias, tiempos de servicio, turnos, retorno al almacén, prioridades, reparto equitativo, viajes interregionales continuos, facturación ni restricciones operativas de DESSET prime. Diseñar modelos específicos de cada dominio antes de aplicar a Prime.

## Interfaz con red vial

La API recibe un diccionario de tiempos por par de IDs de nodos. El cliente OSRM existente puede solicitar una **matriz todos-contra-todos** usando la misma lista de puntos como fuentes y destinos, siempre dentro del límite de ubicaciones. La prueba integrada usa un **servidor HTTP simulado** y posiciones ficticias, no OSRM ni carreteras peruanas. La procedencia de dataset y request SHA debe mantenerse en la capa llamadora; `FleetPlan` no certifica su origen.

## Assurance y límites

- Tests sobre separación de pedidos, capacidad, precedencia, tiempos dirigidos/asimétricos, límites de vehículo, validación adversarial, orden reproducible, parcialidad, presupuestos y decisiones globales vs greedy.
- Oráculo independiente: enumerar asignaciones por vehículo y órdenes de hasta tres pedidos, con matrices aleatorias deterministas; contrastar cobertura y coste óptimo.
- Mutación puntual: cambiar la prioridad para elegir menor cobertura debe hacer fallar la suite; no es mutation testing exhaustivo.
- Compilación, lint, cobertura y CI por SHA. Benchmark local con datos sintéticos, sin inferencia de latencia en producción.
- `control_result = NOT_VERIFIED` para OSRM verdadero con dataset Perú, perfiles de motocicletas/camión, calidad de rutas, tasas de no-servicio, latencia por volumen real, revisión independiente y uso productivo.
- `candidate_decision = BLOCKED` para operaciones reales: faltan dataset nacional verificado, enforcement de main, revisión independiente y gates operativos. No merge, release ni despliegue sin autorización específica.

## Alternativas

Para lotes medianos/grandes o VRP industrial, comparar [PyVRP](https://github.com/PyVRP/PyVRP), [VROOM](https://github.com/VROOM-Project/vroom) y [OR-Tools](https://github.com/google/or-tools) con los **mismos** datos y función objetivo. No instalar por reputación ni declarar un solver superior sin benchmark. 
