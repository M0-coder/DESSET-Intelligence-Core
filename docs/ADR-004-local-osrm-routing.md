# ADR-004 — Consulta a OSRM local con vinculación de coordenadas (experimental)

**Candidato:** INT-005. **Estado:** implementación experimental aislada en PR draft, **NO apta para producción**. **Normativa aplicable:** [Doctrina ASI v3.3 — fuente maestra 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10), `ASI-NORM-TESTING-001`, `ASI-NORM-EVIDENCE-001`, `ASI-NORM-SUPPLY-CHAIN-001`, `ASI-NORM-CHANGE-001`. **Registro de proyecto:** [DESSET Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Alcance exacto y no objetivos

La lógica existente de `dispatch()` asigna repartidores a órdenes usando una matriz estimada, pero carece de generación de rutas. `fetch_local_osrm_table()` consulta una instancia **preexistente, operada por separado, en `127.0.0.1`**, pide la tabla OSRM con índices explícitos de fuentes y destinos, valida los waypoints de la respuesta contra las coordenadas originales y devuelve un `PickupMatrix` utilizable por `dispatch()`.

No incorpora un motor OSRM, no descarga mapas, no demuestra cartografía urbana de Huacho, no mide tráfico, no calcula un ETA observado, no conecta con apps ni despliega infraestructura. No adaptar este modelo de un pedido por repartidor directamente a DESSET prime.

## Contrato y fail-closed

- `RoadPoint(id, longitude, latitude)`: coordenadas **WGS84**, orden lon/lat; IDs únicos **por lado**, no se permite NaN/Inf/bool/latitud-longitud inválida.
- Entrada de pedidos: los puntos `pickups` deben representar el **lugar de recogida**, no el domicilio de entrega; posición/tiempo de reparto observados quedan fuera del Core.
- Endpoint: HTTP `127.0.0.1` con puerto explícito y sin otras rutas, usuarios, queries ni redirecciones; **no acepta servidores públicos o LAN**. Su despliegue seguro y autenticación local son responsabilidades de infraestructura.
- URL: `table/v1/driving/<couriers...;pickups...>?sources=0;...&destinations=N;...&annotations=duration`; **`driving` no selecciona el perfil real del OSRM instalado**: el perfil lo decide el preprocesamiento de la instancia.
- Límite provisional: 100 ubicaciones totales, 2 MB de respuesta, timeout 0.1–15 s, `max_snap_meters` configurable 0–500 (default 75 m, **no umbral validado para Huacho**).
- Deben existir waypoints `sources` y `destinations` en orden. Comprobar coordenadas retornadas y distancia de snapping tanto **reportada** como calculada geodésicamente. Si supera el umbral, **NO usar la matriz**.
- La verificación de snapping es una prueba de proximidad, **no prueba que la calle, perfil, sentido o vía concreta sea correcta**, ni que el servidor sea honesto.
- Datos ausentes, filas incorrectas y `fallback_speed_cells` no vacías → `MatrixInputError`; nunca inventar tiempos faltantes.
- `request_sha256` liga **camino de petición + IDs y su orden**; `response_sha256` identifica el contenido JSON recibido. Ambas son huellas, no firmas de autenticidad ni evidencia independiente de origen geográfico.
- Las etiquetas de `dataset_ref` y `transport_profile` son **declaraciones no verificadas**, no prueba de licencia, fecha de mapa o tipo de vehículo.

## Evidencia y límites técnicos

- Pruebas unitarias: formato/IDs/rangos, conexión HTTP loopback a servidor artificial, rutas unidireccionales, fallos HTTP/JSON, límites y waypoints maliciosos, redirecciones y prohibición de hosts externos.
- CI: verificar suite sobre SHA exacto, Ruff y cobertura. Un servidor HTTP de test **no es OSRM**; solo prueba integración de protocolo y contrato.
- PR draft, sin merge ni cambios en producción. Enlace al issue/PR y SHA se completará en la bitácora tras publicar.

## Camino de prueba con calles reales — pendiente, NO EJECUTADO

1. Obtener PBF Peru mediante [Geofabrik](https://download.geofabrik.de/south-america/peru/), registrar fecha, tamaño, SHA-256, licencia OSM ODbL y [condiciones de uso](https://www.openstreetmap.org/copyright).
2. Aprobar bbox/área Huacho y generar extracto con `osmium extract`, revisando continuidad de calles más allá del límite y cobertura urbana. Ninguna caja definida aquí es una geometría municipal certificada.
3. Seleccionar una imagen de [OSRM upstream](https://github.com/Project-OSRM/osrm-backend) por **digest SHA-256 verificado**, perfil vial explícito y recursos adecuados; ejecutar `osrm-extract`, `osrm-partition`, `osrm-customize`, `osrm-routed` en localhost. No usar `latest` ni imágenes no fijadas para evidencia reproducible.
4. Probar sobre puntos **públicos, no domicilios/clientes** cuya identidad esté validada, y registrar los waypoints devueltos, snaps, tiempos, rutas posibles y fuente con hash.
5. Comparar con recorridos observados autorizados solo cuando existan, bajo privacidad/consentimiento y licencia verificada; reportar errores de ETA, tiempo de ejecución, memoria y tasa de respuesta fallida. Sin esos datos, el claim de mejora real permanece `control_result=NOT_VERIFIED`.

## Decisión de riesgo

`candidate_decision=BLOCKED` para integración en app/producción: `missing_required_capability` (OSRM/OSM locales no disponibles), `required_control_not_verified` (cartografía/perfiles/ETA/seguridad operacional). Sólo es admisible el claim restringido de **prototipo HTTP offline contra servidor simulado**, condicionado a CI PASS del candidato. No confundir CI PASS con Verified Done global.
