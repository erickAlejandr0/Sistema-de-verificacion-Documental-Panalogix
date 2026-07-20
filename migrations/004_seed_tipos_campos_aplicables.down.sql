-- 004_seed_tipos_campos_aplicables.down.sql
-- Quita la clave campos_aplicables del JSONB. No elimina filas del catálogo
-- (pueden existir FKs desde patrones u otros usos operativos).

UPDATE verificaciones.tipos_documento
SET reglas_validacion = reglas_validacion - 'campos_aplicables'
WHERE codigo IN (
    'licencia',
    'soat',
    'cedula',
    'revisado',
    'crct',
    'permiso_pesos'
);
