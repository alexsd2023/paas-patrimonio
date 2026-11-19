# Contratos de eventos

Todo evento del bus es un **CloudEvent 1.0** que cumple dos esquemas:

1. `eventos/_base.schema.json`: el sobre común (id, source, type, time, subject, tenant…)
2. `eventos/<type>.schema.json`: lo propio de su tipo (`data`)

| type | Lo emite | Topic | Escena / tramo |
|---|---|---|---|
| `legajo.ingestado` | puente (al crear un ActivoPatrimonial) | `activos` | 3 / 6 |
| `htr.completado` | módulo HTR | `htr` | 4 / 10 |
| `transcripcion.validada` | proceso de transcripción (Temporal) | `htr` | 5 / 13 |
| `evidencia.anclada` | proceso de transcripción (Temporal), tras certificar con `certificacion-documental` | `certificacion` | 5 / certificación |
| `anclaje.confirmado` | confirmación periódica de certificaciones (Temporal) | `certificacion` | certificación |
| `deposito.medicion` | puente (al registrar el catastro una lectura de sensores) | `sensores` | gemelo |
| `conservacion.alerta` | servicio de conservación | `conservacion` | gemelo |
| `conservacion.normalizada` | servicio de conservación | `conservacion` | gemelo |
| `zona.medicion` | puente (al registrar el catastro una observación de un sensor de una zona) | `sensores` | gemelo patrimonial |
| `conservacion.evaluada` | servicio de conservación (cada evaluación EN 15757 de una zona) | `conservacion` | gemelo patrimonial |
| `conservacion.riesgo` | servicio de conservación (una alerta de zona se abre, agrava, reconoce, propone cerrar o cierra) | `conservacion` | gemelo patrimonial |

`conservacion.alerta` y `conservacion.normalizada` siguen siendo las de los umbrales fijos de los depósitos
(gemelo del archivo). Las del gemelo patrimonial son `conservacion.evaluada` y `conservacion.riesgo`.

## Contexto JSON-LD del gemelo patrimonial

`contextos/gdp-v1.jsonld` define el vocabulario del gemelo (HeritageBuilding, HeritageZone, sensores,
evaluaciones y alertas). La consola lo publica en `/contexts/v1/gdp.jsonld` (sin token). Versionado por ruta:
un cambio incompatible es `gdp-v2.jsonld` en `/contexts/v2/`, y la v1 se sigue sirviendo.

## Cómo viaja por Kafka (modo binario)

- **Clave del mensaje** = `subject` → todos los eventos de una entidad van a la misma partición, en orden.
- **Cabeceras** = atributos del sobre con prefijo `ce_`: `ce_specversion`, `ce_id`, `ce_source`, `ce_type`, `ce_time`, `ce_subject`, `ce_tenant` (+ `traceparent`).
- **Valor** = `data` en JSON; `content-type: application/json`.

Así un consumidor puede filtrar por tipo o tenant leyendo solo las cabeceras.

## Reglas para cambiar un contrato

- Añadir un campo **opcional** → compatible.
- Añadir un campo obligatorio, quitar o renombrar uno → tipo nuevo o versión nueva (`dataschema`), nunca en el mismo.
- Todo cambio lleva su ejemplo válido y, si es una restricción, un ejemplo en `ejemplos/invalidos/`.

Validar: `python scripts/validar_contratos.py`
