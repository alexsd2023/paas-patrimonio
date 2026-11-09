# Contratos de eventos

Todo evento del bus es un **CloudEvent 1.0** que cumple dos esquemas:

1. `eventos/_base.schema.json`: el sobre común (id, source, type, time, subject, tenant…)
2. `eventos/<type>.schema.json`: lo propio de su tipo (`data`)

| type | Lo emite | Topic | Escena / tramo |
|---|---|---|---|
| `legajo.ingestado` | puente (al crear un ActivoPatrimonial) | `activos` | 3 / 6 |
| `htr.completado` | módulo HTR | `htr` | 4 / 10 |
| `transcripcion.validada` | proceso de transcripción (Temporal) | `htr` | 5 / 13 |
| `deposito.medicion` | puente (al registrar el catastro una lectura de sensores) | `sensores` | gemelo |
| `conservacion.alerta` | servicio de conservación | `conservacion` | gemelo |
| `conservacion.normalizada` | servicio de conservación | `conservacion` | gemelo |

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
