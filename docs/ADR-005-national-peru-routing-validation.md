# ADR-005 — Alcance vial nacional de Perú y criterio de evidencia

**Seguimiento:** [INT-006 · GitHub issue #11](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/11). **Estado:** IMPLEMENTACIÓN EXPERIMENTAL EN PR DRAFT; **NO-GO de red vial nacional/producción**. Este ADR complementa [ADR-004](ADR-004-local-osrm-routing.md) y sustituye cualquier interpretación de Huacho como ámbito del sistema. [Doctrina ASI v3.3 (fuente maestra 00)](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10) · [Notion del proyecto](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Decisión de producto (hecho)

- **Cobertura objetivo: todo Perú**, incluyendo repartos de DESSET en distintas ciudades y operaciones interurbanas/interprovinciales y de transporte nacional de DESSET prime.
- **Motor actual:** solo propone asignación de un pedido por courier; no es aún un VRP de múltiples paradas, ni motor de paquetería, ni intermodal, ni estima tráfico. El acceso a tiempos de OSRM utiliza una instancia local separada.
- **Huacho:** posible escenario piloto, no frontera arquitectónica. Se deben registrar resultados de varias regiones con criterios representativos antes de afirmar cobertura efectiva.

## Fuente vial oficial del experimento

- [Geofabrik — Peru OSM PBF](https://download.geofabrik.de/south-america/peru/) contiene un extracto del ámbito **Perú**; tamaño orientativo consultado el 23-11-2026: ~246 MB, sujeto a cambios. El catálogo ofrece snapshots fechados y sumas MD5, pero el contenido no se descargó ni verificó en esta sesión.
- [Geofabrik — technical](https://download.geofabrik.de/technical.html) aclara que el polígono de recorte incluye un buffer y **no equivale a fronteras nacionales oficiales**.
- Datos © OpenStreetMap contributors, licencia **ODbL 1.0**; atribuir y evaluar obligaciones por caso de uso. PBF público de Geofabrik omite campos personales de colaboradores (según documentación de Geofabrik).
- Un MD5 oficial, un hash local SHA-256 o una URL HTTPS son **controles de integridad/provenance limitados**, no prueban exactitud vial, perfiles, cumplimiento normativo ni continuidad de todas las vías.

## Arquitectura mínima

1. **Fuente:** un snapshot fechado `peru-YYMMDD.osm.pbf` procedente de Geofabrik, descargado por un operador externo y con digest esperado documentado de fuente independiente. No subir PBF al repositorio público.
2. **Construcción:** `scripts/build_peru_osrm.sh` exige un PBF existente, su SHA-256 esperado y una imagen OSRM por **digest inmutable**; verifica bytes contra SHA-256 esperado e inspecciona el marcador inicial OSMHeader (no es parsing integral) antes de invocar OSRM MLD `extract → partition → customize`. Los pasos no se ejecutan en este PR y no inician el daemon ni un despliegue. El perfil de ejemplo **car** no certifica motocicletas ni camiones.
3. **Consulta:** `fetch_local_osrm_table` sólo permite `127.0.0.1`, comprueba coordenadas, waypoints y snapping; motor vial gestionado fuera del Core. La implementación de smoke usa un par por petición (dentro del límite actual) y **no tiene estrategia de partición o caché nacional validada**.
4. **Escenarios:** `scenarios/peru-national-probes.json` registra 24 departamentos + Provincia Constitucional del Callao y **10 muestras aproximadas, no geocodificadas ni autenticadas** en ciudades/corredores urbanos, interprovinciales e interregionales. La lista está incompleta deliberadamente: el informe enumera jurisdicciones sin muestras.
5. **Prueba opt-in:** ejecutar `scripts/probe_peru_osrm.py` con PBF local verificado y daemon en loopback; produce JSON por probe con `PASS`/`FAIL`, tiempos calculados e hashes de petición/respuesta. **Ningún resultado concede `nationwide_coverage_control_result=PASS`**. `candidate_decision=BLOCKED` hasta evidencia independiente.

## Reproducción por operador externo (no ejecutado aquí)

Requisitos: Docker operativo, espacio/disponibilidad de RAM adecuados y acceso de descarga externo, `peru-YYMMDD.osm.pbf` local obtenido por HTTPS y checksum comparado con fuente de confianza. `IMAGE_DIGEST` debe venir del registry firmado/validado por el operador. No se usa `:latest`.

```bash
# No ejecutarlo a ciegas: valorar memoria, disco, licencias y recursos.
./scripts/build_peru_osrm.sh /ruta/peru-YYMMDD.osm.pbf <SHA256_VERIFICADO_DEL_PBF> ghcr.io/project-osrm/osrm-backend@sha256:<SHA256_VERIFICADO_DE_LA_IMAGEN>
# Con la imagen ya disponible y el grafo construido, lanzar OSRM sólo en 127.0.0.1:5000
# siguiendo la orden sugerida por el script (no iniciar automáticamente).
PYTHONPATH=src python scripts/probe_peru_osrm.py \
  --scenarios scenarios/peru-national-probes.json \
  --pbf /ruta/peru-YYMMDD.osm.pbf \
  --pbf-sha256 <SHA256_VERIFICADO_DEL_PBF> \
  --dataset-ref 'Geofabrik-peru-YYMMDD' \
  --profile 'car-unverified-for-motorcycles' \
  --base-url http://127.0.0.1:5000 \
  --output /ruta/peru-national-smoke.json
```

Las coordenadas actuales son **solo candidatas ilustrativas**; reemplazarlas con puntos públicos auditados, fuente y fecha antes de considerar esas consultas evidencia geográfica. Una ruta que falla, incluida una conexión imposible en la red vial, no debe imputarse ni contarse como éxito; su causa se investiga.

## Criterios de aceptación pendientes

| Claim / gate | Resultado a 23-11-2026 | Evidencia faltante |
| --- | --- | --- |
| Existe proveedor de extracto nacional | Fuente localizada | PBF concreto descargado; licencia y sumas verificadas |
| SHA-256 de PBF local | NOT_VERIFIED | Bytes reales y checksum externo anclados |
| OSRM sobre grafo Perú | NOT_VERIFIED | Binario/imagen fijada, compilación MLD real, logs y memoria |
| Waypoints y rutas de ciudades | NOT_VERIFIED | Muestras en vías públicas y observación del daemon real |
| Múltiples departamentos | NOT_VERIFIED | Muestreo representativo y resultados por región; 25 regiones no significa todas sus carreteras |
| Tráfico y ETA | NOT_VERIFIED | Tiempos observados legítimos y evaluación estadística |
| Seguridad/infraestructura y merge | BLOCKED | revisión independiente, aprobación y protección efectiva de `main` |

## Verificación de esta iteración

- Pruebas de contrato de escenario, cobertura de jurisdicciones, integridad contra hash, fallo de red, ruta imposible y prohibición de claim de cobertura nacional a partir de todas las muestras exitosas.
- Seguridad: loopback OSRM existente, PBF y Docker fuera del CI ordinario, ejecución opt-in; no secretos, producción ni puerto público.
- Control `build_peru_osrm.sh`: `bash -n` sobre el script; no prueba ejecución de Docker. GitHub Actions ejecutará las pruebas normales del PR para el SHA exacto.
- **Prohibido** inferir mejora comercial, tiempos de entrega reales, calidad vial nacional o capacidad multimodal a partir de este experimento.
