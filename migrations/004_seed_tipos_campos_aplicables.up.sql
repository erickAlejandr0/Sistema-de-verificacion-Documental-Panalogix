-- 004_seed_tipos_campos_aplicables.up.sql
-- Semilla / actualización de tipos_documento con campos_aplicables en
-- reglas_validacion. ON CONFLICT mergea JSONB (||) para no borrar overrides
-- manuales previos; la clave campos_aplicables del seed gana en colisión.

INSERT INTO verificaciones.tipos_documento (codigo, nombre, reglas_validacion, obligatorio)
VALUES
    (
        'licencia',
        'Licencia de conducir',
        '{
            "campos_aplicables": [
                "cedula", "nombre_titular", "categoria",
                "fecha_emision", "fecha_vencimiento"
            ],
            "categorias_validas": ["E3", "F", "G"]
        }'::jsonb,
        true
    ),
    (
        'soat',
        'SOAT',
        '{
            "campos_aplicables": [
                "placa", "aseguradora", "poliza",
                "fecha_emision", "fecha_vencimiento", "nombre_titular"
            ],
            "aseguradoras_autorizadas": []
        }'::jsonb,
        true
    ),
    (
        'cedula',
        'Cédula de identidad',
        '{
            "campos_aplicables": [
                "cedula", "nombre_titular", "fecha_nacimiento",
                "fecha_emision", "fecha_vencimiento"
            ],
            "edad_minima": 18
        }'::jsonb,
        true
    ),
    (
        'revisado',
        'Revisado técnico',
        '{
            "campos_aplicables": [
                "placa", "resultado", "centro",
                "fecha_emision", "fecha_vencimiento"
            ],
            "resultados_validos": ["aprobado", "aprobado condicionalmente"]
        }'::jsonb,
        true
    ),
    (
        'crct',
        'CRCT',
        '{
            "campos_aplicables": [
                "cedula", "nombre_titular", "numero_certificado",
                "fecha_emision", "fecha_vencimiento"
            ]
        }'::jsonb,
        true
    ),
    (
        'permiso_pesos',
        'Permiso de pesos y dimensiones',
        '{
            "campos_aplicables": [
                "placa", "peso_maximo", "dimensiones",
                "fecha_emision", "fecha_vencimiento"
            ]
        }'::jsonb,
        true
    )
ON CONFLICT (codigo) DO UPDATE
SET
    nombre = EXCLUDED.nombre,
    reglas_validacion = verificaciones.tipos_documento.reglas_validacion
        || EXCLUDED.reglas_validacion,
    obligatorio = EXCLUDED.obligatorio;
