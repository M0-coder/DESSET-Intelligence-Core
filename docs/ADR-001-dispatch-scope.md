# ADR-001 — Motor de despacho de una ola (draft)

**Estado:** prototipo propuesto, sin autorización para producción. **Dueño de decisión:** no asignado.
**Rastreo:** [Issue INT-001](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/2) · [Notion independiente](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Problema real y limitación de datos

DESSET requiere seleccionar repartidores para pedidos en un instante. El repositorio no contiene tiempos observados de Huacho, tarifas, GPS, órdenes de clientes ni disponibilidad real. **Ninguna de esas variables será inventada.** El prototipo consume exclusivamente una matriz de tiempos de recogida **ya calculados por un proveedor externo** y sus restricciones explícitas.

## Elección técnica y alternativa

- Python 3.12, biblioteca estándar, sin dependencias de ejecución. Se usa **flujo de costo mínimo** para emparejamiento bipartito; primero maximiza el número de pedidos asignados, después minimiza la suma de tiempos estimados de recogida.
- Comparador: greedy determinista (cada pedido toma el courier compatible con menor tiempo estimado); no se afirma que el comparador represente a un competidor real.
- Repartidor: `id`, `capacity_units`, `available`. Pedido: `id`, `load_units`, `max_pickup_seconds` opcional. Tiempo de recogida: entero no negativo por pareja (`courier_id`, `order_id`); dato ausente = no elegible.
- Una ola = a lo sumo **un pedido por courier**. Unidades de capacidad homogéneas suministradas por el cliente. Los tiempos son estimados de entrada, **no** ETA certificada ni horas observadas.
- No es motor de precios, tráfico, navegación, batch delivery, cadena de frío, SLA, fairness, geocodificación, WMS ni logística multimodal. No hacer afirmaciones sobre margen o kilómetros reales.
- Algoritmo exacto para esta formulación restringida; sin promesa de escala hasta probar performance con cargas realistas. En empates, ordenación por ID estabiliza la salida, sin pretensión de justicia distributiva.

## Contrato de fallo y privacidad

- Entradas inválidas: `ValueError` desde API, código de salida 2 desde CLI. Una matriz incompleta no se rellena con distancias rectas ni tiempos inventados.
- Órdenes no asignadas se marcan con razón de inviabilidad/capacidad en esta ola.
- Solo identificadores sintéticos en ejemplos. No se guardan coordenadas personales, tokens ni información comercial sensible. La librería no realiza solicitudes de red ni escrituras.

## Criterio de revisión y pruebas

1. Compilación sintáctica y tests unitarios offline, escenarios con capacidad/indisponibilidad, empates, tiempos faltantes e imposibilidad.
2. Comparación contra greedy con **idénticos insumos**, y salida reproducible; no extrapolar la diferencia del ejemplo a operaciones reales.
3. Análisis estático, cobertura y seguridad en CI mínimo sin permisos de escritura al repositorio.
4. **Sin validar todavía:** instrumentadas/end-to-end, objetivos de latencia y carga, cobertura efectiva en CI, mutation testing, auditoría de privacidad/terceros, evaluación de datos reales, verificación de salida en red viaria y costos financieros. Ninguno de estos gates se considera PASS hasta entregar la evidencia.
5. Prohibidos merge automático, release y despliegue. PR draft hasta autorización específica.

## Decisiones abiertas

- Fuente de matrices y términos de uso; validez y cobertura urbana en Huacho.
- Contrato operativo de pedidos/riders con las apps; privacidad, permisos y retención.
- Monitoreo real, tolerancias, rollback, robustez a estimaciones erróneas, fairness y latencia.
- Separación de dominios: DESSET prime usará modelos/algoritmos de paquetería especializados; no reutilizar reglas comerciales sin revisión.
