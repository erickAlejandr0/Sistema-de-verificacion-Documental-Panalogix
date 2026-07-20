# Migraciones SQL — schema `verificaciones`

Scripts versionados para PostgreSQL **17** (RDS). Tipos, nulabilidad, defaults
y restricciones tomados de `docs/diccionario-de-datos.md`.

## Orden de ejecución

Aplicar (up):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_create_schema.up.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_create_tables.up.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/003_alerta_atendida.up.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/004_seed_tipos_campos_aplicables.up.sql
```

Revertir (down), en orden inverso:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/004_seed_tipos_campos_aplicables.down.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/003_alerta_atendida.down.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_create_tables.down.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_create_schema.down.sql
```
## Decisiones verificadas en PostgreSQL 17

### `documentos.eliminar_despues` — DEFAULT, no GENERATED

Se probó en PostgreSQL 17.10:

```sql
... GENERATED ALWAYS AS (subido_en::date + INTERVAL '90 days') STORED
```

Resultado: **ERROR** `generation expression is not immutable` (cast
`timestamptz → date` es STABLE).

La migración usa el equivalente al insert:

```sql
eliminar_despues DATE NOT NULL DEFAULT ((CURRENT_DATE + INTERVAL '90 days')::date)
```

Semánticamente alineado con `subido_en DEFAULT now()` en el mismo INSERT.

### `historial.tipo_detectado` — sin FK

Referencia libre a `tipos_documento.codigo` (no FK). La extracción
schema-agnostic (RF-09/RF-10) puede detectar tipos aún no catalogados.

### `patrones.subtipo` — NOT NULL DEFAULT `''` + UNIQUE

`subtipo` no es nullable: el patrón “sin variante” usa el centinela `''`.
Así el UNIQUE `(tipo_codigo, subtipo)` cubre ese caso (en PostgreSQL dos
`NULL` no colisionan). Habilita `INSERT ... ON CONFLICT DO UPDATE`.
