-- Revertir ATENDIDA: alertas en ese estado vuelven a PENDIENTE antes del CHECK.
UPDATE verificaciones.alertas
SET estado = 'PENDIENTE'
WHERE estado = 'ATENDIDA';

ALTER TABLE verificaciones.alertas
    DROP CONSTRAINT chk_alertas_estado;

ALTER TABLE verificaciones.alertas
    ADD CONSTRAINT chk_alertas_estado
        CHECK (estado IN ('PENDIENTE', 'ENVIADA', 'FALLIDA'));
