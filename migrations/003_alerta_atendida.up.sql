-- ---------------------------------------------------------------------------
-- 003 — alertas.estado: añadir ATENDIDA (resolución manual / panel Retool)
-- ---------------------------------------------------------------------------
ALTER TABLE verificaciones.alertas
    DROP CONSTRAINT chk_alertas_estado;

ALTER TABLE verificaciones.alertas
    ADD CONSTRAINT chk_alertas_estado
        CHECK (estado IN ('PENDIENTE', 'ENVIADA', 'FALLIDA', 'ATENDIDA'));
