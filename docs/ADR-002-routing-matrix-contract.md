# ADR-002 — Contrato offline de matriz vial / OSRM Table

**Estado:** propuesta implementada en PR draft, no adoptada en producción.
**Origen:** [INT-002](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/4) y [Notion independiente](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Qué resuelve

El motor `dispatch.py` recibe tiempos de recogida estimados por pareja repartidor/pedido, pero no calcula las rutas. El adaptador `routing_matrix.py` transforma la matriz `durations` de una **respuesta OSRM Table ya obtenida por otro sistema** en el contrato de tiempos de DESSET. No ejecuta OSRM ni realiza solicitudes HTTP. La procedencia y el estado legal de la cartografía quedan fuera de alcance.

## Contrato

- Filas: **courier_ids**; columnas: **order_ids**. Las coordenadas (si existen) y su orden se resuelven fuera del Core, antes de invocar la función.
- Unidades: segundos. OSRM proporciona decimales; se aplica `ceil` conservador al convertir a enteros. `null` = viaje imposible o sin ruta, sin imputación silenciosa.
- `fallback_speed_cells` **no vacío** = rechazo explícito: no aceptar tiempos generados como aproximaciones rectas.
- Restricciones de entrada: IDs distintos, etiquetas no vacías, forma de matriz exacta, números finitos no negativos, máximo **10 000 celdas** para este prototipo.
- `dataset_ref` y `transport_profile` son metadatos **declarados por el llamador**; nunca se marcan como verificados automáticamente.
- `response_sha256` identifica un JSON serializado de forma canónica; **no autentica** que los datos provengan de OSRM, ni su exactitud, ni su licencia.
- No calcular márgenes, tiempos de entrega finales ni demanda a partir de este contrato. Las duraciones corresponden solo a `courier -> pickup` cuando las posiciones de origen y destino estén realmente definidas así.

## Fuentes y licencias para contrastar

- [OSRM Table Service](https://project-osrm.org/docs/v26.4.0/http), [OSRM backend (BSD-2-Clause)](https://github.com/Project-OSRM/osrm-backend/blob/master/LICENSE.TXT).
- [OSM Foundation — licencia de datos y FAQ](https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ).
- [Política de uso de teselas OSM](https://operations.osmfoundation.org/policies/tiles/). No usar servicios públicos sin validar términos de uso.

## Pruebas y gates

Pruebas unitarias de forma, segundos, `null`, fallback, hash, seguridad de entradas, matriz asimétrica, límites y compatibilidad con Dispatch. Pruebas generativas con Hypothesis (invariantes de asignación y optimalidad por fuerza bruta para casos pequeños) cuando la dependencia esté instalada. Ruff revisará estilo y errores sintácticos. No se declara PASS antes de ejecutar cada herramienta.

**Pendiente:** matriz real y licencia de extracto OSM de Huacho, benchmark de latencia y memoria de OSRM local, perfiles reales de motocicleta, pruebas instrumentadas, mutation testing, provenance externa, revisión de seguridad, y objetivo de ETA calibrado. Este PR no cambia el dominio DESSET prime ni conecta con producción.
