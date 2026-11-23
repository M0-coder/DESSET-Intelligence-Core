# DESSET Intelligence Core

**Estado:** código de prototipo offline, no operable en producción. Repositorio público. **No contiene datos observados ni algoritmos validados sobre rutas reales de Huacho.**

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
