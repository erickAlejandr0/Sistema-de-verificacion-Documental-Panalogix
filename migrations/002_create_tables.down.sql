-- 002_create_tables.down.sql
-- Elimina las tablas del schema verificaciones en orden inverso a las FKs.

DROP TABLE IF EXISTS verificaciones.alertas;
DROP TABLE IF EXISTS verificaciones.correcciones;
DROP TABLE IF EXISTS verificaciones.patrones;
DROP TABLE IF EXISTS verificaciones.historial;
DROP TABLE IF EXISTS verificaciones.documentos;
DROP TABLE IF EXISTS verificaciones.tipos_documento;
