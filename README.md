# DESSET Intelligence Core

**Estado:** código de prototipo offline, no operable en producción. Repositorio público. **No contiene datos observados ni algoritmos validados sobre rutas reales del Perú.**

## Identidad y ámbito

- **DESSET:** plataforma de comercio y entrega inmediata; primera prueba: asignación a repartidores.
- **DESSET prime:** paquetería, fulfillment y red logística; más adelante importaciones y operaciones marítimas/portuarias. Su modelo de decisión requiere reglas y contratos propios, **no** debe reutilizar el despacho urbano sin revisión.
- **Intelligence Core:** biblioteca de algoritmos, reglas y pruebas; no tiene usuarios finales, transacciones, pagos ni despliegues.

**Documentación canónica:** [Notion — DESSET Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda). **Trabajo:** [INT-001](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/2) · [ADR-001](docs/ADR-001-dispatch-scope.md).

## Ejecutar el prototipo (Python 3.12+)

Sin librerías externas durante la ejecución:

```bash
PYTHONPATH=src python -m desset_core --input examples/synthetic-two-orders.json --strategy optimal
PYTHONPATH=src python -m desset_core --input examples/synthetic-two-orders.json --strategy greedy
PYTHONPATH=src python -m unittest discover -s tests -v
```

**Todos los pedidos, repartidores y tiempos del ejemplo son sintéticos.** El motor no calcula rutas ni tráfico. Recibe una matriz de tiempos estimados cuyo origen, precisión y legalidad se deberán comprobar aparte. La comparación `optimal` frente a `greedy` **no acredita superioridad comercial ni operativa**.

## Límite del primer algoritmo

Una ola; máximo un pedido por repartidor; capacidad y disponibilidad duras; posible límite de espera de recogida; combinación de máximo número de asignaciones y mínimo total de segundos estimados. Resultado auditado por IDs y motivos de no asignación. No es un sistema de replanificación dinámica ni despacho de varios paquetes por vehículo.

## Ingeniería obligatoria

Primero fijar el alcance: arquitectura, compilación, pruebas unitarias e instrumentadas si aplican, cobertura, análisis estático, calidad de CI, seguridad, reproducibilidad, mutation testing, deuda técnica y evidencia de ejecución. Esos gates **no se presumen aprobados** por existir código. Ver ADR-001 para lo pendiente.

## Cambio controlado

Nada de auto-merge, producción, DNS, releases ni publicación. No introducir secretos, PII, datos de clientes o parámetros comerciales protegidos. Cada PR deberá referenciar decisiones de Notion, issues y commit SHA, e indicar evidencia PASS/FAIL/PENDIENTE. No existe sincronización automática de decisiones entre GitHub y Notion.

## INT-002: contrato experimental de matrices (PR apilado)

`routing_matrix.parse_osrm_table` convierte una **respuesta OSRM Table suministrada** (sin red) en el mapa `pickup_seconds` que ya acepta `dispatch()`, con huella SHA-256 del JSON y trazabilidad declarativa. No confirma cartografía real, tráfico, dataset o perfil de motocicleta. No realiza HTTP.

[ADR-002](docs/ADR-002-routing-matrix-contract.md) · [Issue #4 — INT-002](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/4) · [Notion](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

El código contiene un ejemplo **sintético** en `examples/synthetic-osrm-table.json`. Ninguna capacidad logística nueva está operativa.

## INT-006: validación territorial nacional (propuesta experimental)

**Objetivo definitivo de cobertura: TODO EL PERÚ.** Huacho es una zona piloto posible, no la frontera del motor. DESSET urbano y DESSET prime interprovincial necesitan restricciones y métricas propias.

- [ADR-005 — protocolo de validación nacional](docs/ADR-005-national-peru-routing-validation.md).
- [Inventario de 25 jurisdicciones y 10 probes ILUSTRATIVOS](scenarios/peru-national-probes.json).
- [Verificador de SHA-256 y consulta opt-in a OSRM local](scripts/probe_peru_osrm.py).
- [Preprocesamiento OSRM MLD con PBF e imagen por digests obligatorios](scripts/build_peru_osrm.sh).

[Issue INT-006](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/11). **No se ha ejecutado OSRM real ni descargado el PBF de Perú.** Los casos y coordenadas son aproximados, no validados en el terreno. Una batería de consultas que resulte verde sigue declarando `nationwide_coverage_control_result=NOT_VERIFIED`. Ningún cambio activa una descarga, merge o despliegue automáticamente.

## INT-007 — Algoritmo exacto multientrega (prototipo, PR en revisión)

`desset_core.optimize_multistop(...)` calcula la **secuencia de recogidas y entregas**
para un vehículo a partir de una matriz dirigida de segundos estimados. Respeta
precedencia de recogida→entrega, capacidad a bordo, rutas inaccesibles y un
presupuesto opcional de duración. Optimiza tiempo **de recorrido estimado**,
no márgenes, tarifa, tráfico, ETA certificado ni equidad de repartidores.

```python
from desset_core import DeliveryJob, optimize_multistop

jobs = [DeliveryJob("A", "A-PICKUP", "A-DELIVERY", 1)]
legs = {("START", "A-PICKUP"): 120, ("A-PICKUP", "A-DELIVERY"): 300}
plan = optimize_multistop("START", 1, jobs, legs)
assert plan.total_estimated_travel_seconds == 420
```

**Límite deliberado:** hasta siete pedidos obligatorios por vehículo; nodos
de recogida/entrega diferentes, sin ventanas horarias, tiempos de servicio,
replanificación, selección de vehículos, turno, ruta de retorno ni optimización
interprovincial a gran escala. Estas son etapas posteriores con otros modelos.
No sustituye a `dispatch()` y **no demuestra calidad de ruta en Perú** sin
OSRM verdadero y datos viales auditados. El origen de las matrices debe
quedar trazado; los tests actuales usan tiempos sintéticos.

[Decisión técnica ADR-006](docs/ADR-006-multistop-exact-routing.md) · [Notion](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## INT-008 — Optimización exacta de flota pequeña (prototipo experimental)

`desset_core.optimize_fleet(...)` distribuye hasta **6 pedidos entre 4 vehículos** y genera para cada vehículo una ruta con recogida previa a entrega y capacidad a bordo válida. Maximiza pedidos servidos y después minimiza segundos estimados de recorrido; no inventa conexiones de carretera ausentes. Los pedidos que no puedan cubrirse se devuelven explícitamente.

```python
from desset_core import DeliveryJob, FleetVehicle, optimize_fleet

vehicles = [FleetVehicle("R1", "START1", 2), FleetVehicle("R2", "START2", 1)]
jobs = [DeliveryJob("J1", "PICKUP", "DROP", 1)]
seconds = {("START1", "PICKUP"): 60, ("START2", "PICKUP"): 120,
           ("PICKUP", "DROP"): 180}
plan = optimize_fleet(vehicles, jobs, seconds)
assert plan.served_job_count == 1
assert plan.total_estimated_travel_seconds == 240
```

[Issue #15 · INT-008](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/15) · [ADR-007](docs/ADR-007-fleet-exact-smallbatch.md) · [Benchmark sintético reproducible](benchmarks/bench_fleet.py). El alcance objetivo sigue siendo **todo el Perú**; los ejemplos son **100 % sintéticos**. Esta función no conecta por sí sola con OSRM real ni demuestra cobertura de la red peruana, fiabilidad de ETA o escalabilidad comercial. Para múltiples paradas reales se necesitan matrices dirigidas con origen cartográfico auditado y reglas específicas de DESSET y DESSET prime.
