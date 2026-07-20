---
title: Diccionario de Datos
document_type: Data Dictionary
section: 1
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
database: PostgreSQL 17
schema: verificaciones
author: Panalogix
last_updated: 2026-07-11
---

# 1. Propósito y Convenciones

Este diccionario de datos especifica los tipos SQL exactos, la nulabilidad, los valores por defecto y las restricciones de cada columna del schema verificaciones. Complementa el diagrama entidad-relación: donde el diagrama muestra la estructura y las relaciones, este documento define la implementación precisa en PostgreSQL 17.

Es el insumo directo para la Fase 2 del desarrollo — la generación de las migraciones SQL (P2.1) y los modelos Pydantic (P2.2). Con este diccionario, la generación de código no necesita inferir tipos: los toma de aquí.

## 1.1 Convenciones generales

- Llaves primarias: todas las llaves primarias son UUID, generadas con gen_random_uuid(). No se usan enteros autoincrementales.
- Estados: los campos de estado (resultado, estado) se modelan como VARCHAR con una restricción CHECK que limita los valores permitidos. Se prefiere sobre ENUM nativo por flexibilidad para evolucionar los valores sin migración de tipo.
- Valores numéricos: los scores y montos usan NUMERIC de precisión exacta, no FLOAT ni DOUBLE PRECISION, para evitar errores de redondeo en dinero y umbrales.
- Fechas y tiempos: todas las marcas de tiempo usan TIMESTAMPTZ (con zona horaria) para consistencia entre ambientes. Solo se incluyen los timestamps definidos en el modelo.
- Datos flexibles: los datos semiestructurados y heterogéneos (campos extraídos, reglas, patrones) usan JSONB, que permite indexación y consulta.
- PII cifrado: los datos personales sensibles se almacenan cifrados en columnas JSONB separadas (campos_cifrados), nunca mezclados con los campos en claro.

## 1.2 Tipos de referencia usados

| Tipo SQL | Uso en el schema |
|----------|------------------|
| UUID | Llaves primarias y foráneas. |
| VARCHAR(n) | Cadenas de longitud acotada (estados, códigos, nombres). |
| TEXT | Cadenas de longitud variable sin límite (claves S3, valores libres). |
| NUMERIC(p,s) | Scores (precisión 4, escala 3) y costos (precisión 10, escala 6). |
| INTEGER | Contadores y días (dias_aviso, muestras). |
| BOOLEAN | Banderas (obligatorio). |
| DATE | Fechas sin hora (fecha_vencimiento, eliminar_despues). |
| TIMESTAMPTZ | Marcas de tiempo con zona horaria. |
| JSONB | Datos semiestructurados (campos, reglas, estructura, patrones). |

# 2. Diccionario por Tabla

## documentos — documento físico subido por el transportista

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Identificador único del documento físico. PK. |
| transportista_id | UUID | NO | — | Referencia al transportista en Panalogix (no FK local; sistemas desacoplados). |
| tipo_documento | VARCHAR(40) | NO | — | Tipo declarado al subir (licencia, soat, crct, cedula...). |
| s3_key_raw | TEXT | NO | — | Clave del objeto en el bucket S3 raw-docs. |
| s3_key_verified | TEXT | SÍ | NULL | Clave en S3 verified-docs; se llena solo si el documento es aprobado. |
| eliminar_despues | DATE | NO | subido_en + 90d | Columna generada. Fecha de eliminación por retención (Ley 81). |
| subido_en | TIMESTAMPTZ | NO | now() | Momento de la subida. |

**Llaves e índices:** PK (id). Índice en transportista_id para consultar el estado documental de un transportista.

**Nota:** eliminar_despues se define como columna generada: `GENERATED ALWAYS AS (subido_en::date + INTERVAL '90 days') STORED`. El proceso de retención elimina el objeto S3 y el registro cuando esta fecha pasa.

---

## historial — cada extracción realizada sobre un documento

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Identificador de la extracción. PK. |
| documento_id | UUID | NO | — | FK a documentos.id. Un documento puede tener varias extracciones. |
| tipo_detectado | VARCHAR(40) | SÍ | NULL | Tipo de documento detectado por la IA (puede diferir del declarado). |
| campos_extraidos | JSONB | NO | '{}' | Campos no sensibles extraídos, con valor y confianza por campo. |
| campos_cifrados | JSONB | SÍ | NULL | Campos PII cifrados con KMS (cédula, nombre, etc.). |
| resultado | VARCHAR(20) | NO | — | Clasificación. CHECK: APROBADO, RECHAZADO, REVISION_MANUAL. |
| score_lectura | NUMERIC(4,3) | SÍ | NULL | Confianza de la extracción (0.000 a 1.000). |
| score_autenticidad | NUMERIC(4,3) | SÍ | NULL | Probabilidad de autenticidad (0.000 a 1.000). |
| modelo_usado | VARCHAR(30) | SÍ | NULL | Modelo que resolvió la extracción (haiku, sonnet). |
| version_extraccion | VARCHAR(20) | SÍ | NULL | Versión del pipeline/prompt usado (p. ej. v2.3). |
| prompt_hash | VARCHAR(64) | SÍ | NULL | Hash del prompt usado, para trazabilidad. |
| costo_api | NUMERIC(10,6) | SÍ | NULL | Costo en USD de la llamada a Claude para esta extracción. |
| fecha_vencimiento | DATE | SÍ | NULL | Fecha de vencimiento del documento extraído. |
| procesado_en | TIMESTAMPTZ | NO | now() | Momento en que se completó la extracción. |

**Llaves e índices:** PK (id). FK documento_id → documentos(id). Índices en documento_id (reprocesamiento) y en fecha_vencimiento (alertas).

**Nota:** La separación entre campos_extraidos (en claro) y campos_cifrados (PII) es un requisito de la Ley 81. Ambos son JSONB, pero solo el segundo pasa por KMS antes de persistir.

---

## correcciones — intervención humana sobre una extracción

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Identificador de la corrección. PK. |
| historial_id | UUID | NO | — | FK a historial.id. Extracción corregida. |
| campo_corregido | VARCHAR(60) | NO | — | Nombre del campo que fue corregido. |
| valor_modelo | TEXT | SÍ | NULL | Valor que había extraído el modelo. |
| valor_correcto | TEXT | NO | — | Valor correcto ingresado por el revisor. |
| corregido_por | VARCHAR(255) | NO | — | Identificador del revisor en Retool (texto, p. ej. email de sesión). No es UUID relacional a una tabla de usuarios del SVD. |
| corregido_en | TIMESTAMPTZ | NO | now() | Momento de la corrección. |

**Llaves e índices:** PK (id). FK historial_id → historial(id). Índice en historial_id.

---

## tipos_documento — catálogo de tipos con sus reglas de validación

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| codigo | VARCHAR(40) | NO | — | Código del tipo de documento. PK (natural). |
| nombre | VARCHAR(100) | NO | — | Nombre legible del tipo. |
| reglas_validacion | JSONB | NO | '{}' | Reglas específicas del tipo, evaluadas por el Rules Engine. |
| obligatorio | BOOLEAN | NO | true | Si el documento es obligatorio para operar. |

**Llaves e índices:** PK (codigo). Llave primaria natural en lugar de UUID por ser un catálogo estable y referenciable por código legible.

**Nota:** reglas_validacion en JSONB permite ajustar las reglas de negocio de cada tipo sin cambiar código ni migrar el schema — cumple el principio Open/Closed de las reglas de Cursor.

---

## patrones — conocimiento acumulado por tipo y variante

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Identificador del patrón. PK. |
| tipo_codigo | VARCHAR(40) | NO | — | FK a tipos_documento.codigo. |
| subtipo | VARCHAR(60) | NO | `''` | Variante detectada (emisor/formato). Centinela `''` = sin subtipo (nunca NULL; permite UNIQUE). |
| estructura_detectada | JSONB | NO | '{}' | Estructura aprendida del documento. |
| confianza_promedio | NUMERIC(4,3) | SÍ | NULL | Confianza media de las extracciones de este patrón. |
| muestras | INTEGER | NO | 0 | Número de documentos que respaldan el patrón. |
| actualizado_en | TIMESTAMPTZ | NO | now() | Última actualización del patrón. |

**Llaves e índices:** PK (id). FK tipo_codigo → tipos_documento(codigo). UNIQUE (tipo_codigo, subtipo) para upsert atómico (`ON CONFLICT`). Índice en tipo_codigo.

---

## alertas — notificaciones de vencimiento enviadas

| Columna | Tipo SQL | Null | Default | Descripción |
|----------|----------|------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Identificador de la alerta. PK. |
| historial_id | UUID | NO | — | FK a historial.id. Extracción cuyo documento vence. |
| dias_aviso | INTEGER | NO | — | Umbral de aviso. CHECK: 30, 7 o 0. |
| estado | VARCHAR(20) | NO | 'PENDIENTE' | Estado de la alerta. CHECK: PENDIENTE, ENVIADA, FALLIDA, ATENDIDA. |
| enviada_en | TIMESTAMPTZ | SÍ | NULL | Momento del envío efectivo. |

**Llaves e índices:** PK (id). FK historial_id → historial(id). Índice único en (historial_id, dias_aviso) para evitar alertas duplicadas.

# 3. Dominios y Restricciones CHECK

Los campos de estado se restringen a un conjunto cerrado de valores mediante CHECK constraints. Esta es la referencia de todos los dominios del schema.

| Tabla.columna | Valores permitidos (CHECK) |
|----------------|----------------------------|
| historial.resultado | APROBADO · RECHAZADO · REVISION_MANUAL |
| alertas.dias_aviso | 30 · 7 · 0 |
| alertas.estado | PENDIENTE · ENVIADA · FALLIDA · ATENDIDA |
| historial.score_lectura | Rango 0.000 – 1.000 (CHECK >= 0 AND <= 1) |
| historial.score_autenticidad | Rango 0.000 – 1.000 (CHECK >= 0 AND <= 1) |
| patrones.confianza_promedio | Rango 0.000 – 1.000 (CHECK >= 0 AND <= 1) |

Los valores de resultado, estado y dias_aviso deben coincidir exactamente con los Enum/Literal que los modelos Pydantic definen en la Fase 2 (P2.2), garantizando consistencia entre la base de datos y la capa de aplicación.

# 4. Estructura Esperada de los Campos JSONB

Aunque JSONB es flexible, los campos siguen una estructura convenida que los modelos Pydantic validan. Esta es la forma esperada de cada uno.

## 4.1 campos_extraidos (historial)

Diccionario de campos no sensibles, cada uno con su valor y la confianza de la extracción:

```json
{
  "placa":            { "valor": "AB1234", "confianza": 0.97 },
  "categoria":        { "valor": "E3",     "confianza": 0.95 },
  "fecha_vencimiento":{ "valor": "2027-03-15", "confianza": 0.99 },
  "aseguradora":      { "valor": "ASSA",   "confianza": 0.92 }
}
```

## 4.2 campos_cifrados (historial)

Campos PII, cifrados con KMS. El valor es el texto cifrado en base64, nunca el dato en claro:

```json
{
  "cedula":         { "valor_cifrado": "AQICAHh...", "confianza": 0.98 },
  "nombre_titular": { "valor_cifrado": "AQICAHj...", "confianza": 0.96 }
}
```

## 4.3 reglas_validacion (tipos_documento)

Reglas específicas del tipo, evaluadas por el Rules Engine sin necesidad de cambiar código:

```json
{
  "categorias_validas": ["E3", "F", "G"],
  "requiere_placa": true,
  "dias_alerta": [30, 7, 0],
  "campos_obligatorios": ["cedula", "fecha_vencimiento"],
  "campos_aplicables": [
    "cedula",
    "nombre_titular",
    "categoria",
    "fecha_emision",
    "fecha_vencimiento"
  ]
}
```

**`campos_aplicables`:** labels canónicos que cuentan en `confianza_minima` (OCR)
y `score_lectura` (scoring). Campos presentes en la extracción pero no listados
(p. ej. `placa` en una licencia) se ignoran en esos cálculos. Distinto de
`campos_obligatorios` (semántica de obligatoriedad de negocio).
## 4.4 estructura_detectada (patrones)

Snapshot de la **muestra más reciente** que escribió el patrón (overwrite en
cada upsert). **No** es un agregado histórico de campos a lo largo del tiempo;
los agregados reales de la tabla son `muestras` (contador acumulativo) y
`confianza_promedio` (promedio móvil ponderado). Un análisis longitudinal de
frecuencia de campos (p. ej. RF-25) se consulta sobre `historial.campos_extraidos`.

MVP persistido por el pipeline tras cada extracción genuinamente nueva:

```json
{
  "emisor": "ATTT",
  "campos_tipicos": ["cedula", "categoria", "fecha_vencimiento"]
}
```

- `campos_tipicos`: solo nombres de campo con `valor != null` en esa extracción
  (no placeholders `null` del prompt). Solo strings de nombre — nunca valores
  PII (Ley 81; no hay cifrado KMS en esta tabla).
- No se filtra por `campos_aplicables`.
- No se escribe fila si `tipo_detectado` es `desconocido` u otro código fuera
  del catálogo FK de `tipos_documento` (6 códigos sembrados).
- `formato_fecha` (ejemplo histórico) no se rellena en el MVP actual.

# 5. Uso en la Fase 2

Este diccionario se usa como contexto directo en los prompts de la Fase 2 del playbook:

- P2.1 (Migraciones SQL): añade este documento al contexto junto con el diagrama ERD. Los tipos SQL de las migraciones deben tomarse de aquí, no inferirse.
- P2.2 (Modelos Pydantic): los modelos Pydantic deben reflejar exactamente estos tipos: NUMERIC → Decimal, los CHECK → Enum/Literal, las columnas nullable → Optional.
- P2.3 (Repositorios): los métodos de acceso deben respetar el cifrado de campos_cifrados al escribir y descifrar al leer, según lo definido aquí.

**Instrucción sugerida para añadir al prompt P2.1:** "Usa los tipos SQL exactos definidos en el diccionario de datos (docs/diccionario_datos.docx): VARCHAR+CHECK para estados, NUMERIC(4,3) para scores, NUMERIC(10,6) para costo_api, TIMESTAMPTZ para tiempos, columna generada para eliminar_despues."

Con este diccionario, la Fase 2 puede ejecutarse sin ambigüedad de tipos, garantizando que el schema físico, las migraciones y los modelos Pydantic sean consistentes entre sí y fieles al diseño.