-- 002_create_tables.up.sql
-- Tablas del schema verificaciones según docs/diccionario-de-datos.md.
-- PostgreSQL 17. eliminar_despues usa DEFAULT (no GENERATED): cast
-- timestamptz::date no es IMMUTABLE y PG17 rechaza la columna generada.

-- ---------------------------------------------------------------------------
-- tipos_documento — catálogo con reglas JSONB
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.tipos_documento (
    codigo VARCHAR(40) PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    reglas_validacion JSONB NOT NULL DEFAULT '{}'::jsonb,
    obligatorio BOOLEAN NOT NULL DEFAULT true
);

-- ---------------------------------------------------------------------------
-- documentos — documento físico subido (Ley 81: retención 90 días)
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.documentos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transportista_id UUID NOT NULL,
    tipo_documento VARCHAR(40) NOT NULL,
    s3_key_raw TEXT NOT NULL,
    s3_key_verified TEXT NULL,
    subido_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- DEFAULT en lugar de GENERATED ALWAYS AS (subido_en::date + INTERVAL '90 days')
    -- STORED: verificado en PostgreSQL 17 — "generation expression is not immutable".
    eliminar_despues DATE NOT NULL DEFAULT ((CURRENT_DATE + INTERVAL '90 days')::date)
);

CREATE INDEX idx_documentos_transportista_id
    ON verificaciones.documentos (transportista_id);

-- ---------------------------------------------------------------------------
-- historial — cada extracción sobre un documento
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.historial (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    documento_id UUID NOT NULL REFERENCES verificaciones.documentos (id),
    -- tipo_detectado es referencia libre (no FK) a tipos_documento.codigo:
    -- la extracción schema-agnostic puede detectar tipos aún no catalogados.
    tipo_detectado VARCHAR(40) NULL,
    campos_extraidos JSONB NOT NULL DEFAULT '{}'::jsonb,
    campos_cifrados JSONB NULL,
    resultado VARCHAR(20) NOT NULL,
    score_lectura NUMERIC(4, 3) NULL,
    score_autenticidad NUMERIC(4, 3) NULL,
    modelo_usado VARCHAR(30) NULL,
    version_extraccion VARCHAR(20) NULL,
    prompt_hash VARCHAR(64) NULL,
    costo_api NUMERIC(10, 6) NULL,
    fecha_vencimiento DATE NULL,
    procesado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_historial_resultado
        CHECK (resultado IN ('APROBADO', 'RECHAZADO', 'REVISION_MANUAL')),
    CONSTRAINT chk_historial_score_lectura
        CHECK (score_lectura IS NULL OR (score_lectura >= 0 AND score_lectura <= 1)),
    CONSTRAINT chk_historial_score_autenticidad
        CHECK (
            score_autenticidad IS NULL
            OR (score_autenticidad >= 0 AND score_autenticidad <= 1)
        )
);

CREATE INDEX idx_historial_documento_id
    ON verificaciones.historial (documento_id);

CREATE INDEX idx_historial_fecha_vencimiento
    ON verificaciones.historial (fecha_vencimiento);

-- ---------------------------------------------------------------------------
-- correcciones — intervención humana sobre una extracción
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.correcciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    historial_id UUID NOT NULL REFERENCES verificaciones.historial (id),
    campo_corregido VARCHAR(60) NOT NULL,
    valor_modelo TEXT NULL,
    valor_correcto TEXT NOT NULL,
    -- Identificador Retool (texto, p. ej. email); no UUID de tabla de usuarios.
    corregido_por VARCHAR(255) NOT NULL,
    corregido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_correcciones_historial_id
    ON verificaciones.correcciones (historial_id);

-- ---------------------------------------------------------------------------
-- patrones — conocimiento acumulado por tipo y variante
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.patrones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_codigo VARCHAR(40) NOT NULL REFERENCES verificaciones.tipos_documento (codigo),
    -- Centinela '' = sin subtipo (nunca NULL): UNIQUE debe cubrir ese caso.
    subtipo VARCHAR(60) NOT NULL DEFAULT '',
    estructura_detectada JSONB NOT NULL DEFAULT '{}'::jsonb,
    confianza_promedio NUMERIC(4, 3) NULL,
    muestras INTEGER NOT NULL DEFAULT 0,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_patrones_confianza_promedio
        CHECK (
            confianza_promedio IS NULL
            OR (confianza_promedio >= 0 AND confianza_promedio <= 1)
        ),
    CONSTRAINT uq_patrones_tipo_subtipo UNIQUE (tipo_codigo, subtipo)
);

CREATE INDEX idx_patrones_tipo_codigo
    ON verificaciones.patrones (tipo_codigo);

-- ---------------------------------------------------------------------------
-- alertas — notificaciones de vencimiento (sin duplicados por umbral)
-- ---------------------------------------------------------------------------
CREATE TABLE verificaciones.alertas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    historial_id UUID NOT NULL REFERENCES verificaciones.historial (id),
    dias_aviso INTEGER NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',
    enviada_en TIMESTAMPTZ NULL,
    CONSTRAINT chk_alertas_dias_aviso CHECK (dias_aviso IN (30, 7, 0)),
    CONSTRAINT chk_alertas_estado
        CHECK (estado IN ('PENDIENTE', 'ENVIADA', 'FALLIDA')),
    CONSTRAINT uq_alertas_historial_dias_aviso UNIQUE (historial_id, dias_aviso)
);
