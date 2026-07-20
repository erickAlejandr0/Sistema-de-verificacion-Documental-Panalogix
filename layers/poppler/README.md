# Lambda Layer — poppler (pdf2image)

El worker convierte PDF → imagen con `pdf2image`, que requiere los binarios
de **poppler** (`pdftoppm`, `pdfinfo`) en el runtime. Este directorio es el
`ContentUri` del recurso `LocalPopplerLayer` en `template.yaml`.

## Layout esperado

Al empaquetar, la capa se monta en `/opt`. Debe quedar:

```text
layers/poppler/
  bin/
    pdftoppm
    pdfinfo
    pdftocairo   # opcional
  lib/           # .so de poppler y dependencias
  README.md
```

En la Lambda, el runtime ya incluye `/opt/bin` en `PATH` y `/opt/lib` en
`LD_LIBRARY_PATH`. No redefinir esas variables en el template (rompen el
runtime).

## Opción A — construir binarios Amazon Linux 2023 (x86_64)

Compilar o extraer poppler en un contenedor alineado al runtime Lambda
`python3.12` / AL2023, copiar `bin/` + `lib/` aquí, y desplegar:

```bash
sam build
sam deploy
```

Con `PopplerLayerArn` vacío, SAM publica `LocalPopplerLayer` desde este
directorio.

## Opción B — ARN de capa ya publicada

Si ya tienes una capa poppler (otra cuenta/stack):

```bash
sam deploy --parameter-overrides \
  Environment=dev \
  PopplerLayerArn=arn:aws:lambda:us-east-1:ACCOUNT:layer:poppler:1
```

Entonces `LocalPopplerLayer` no se crea (`UseLocalPopplerLayer=false`).

## Notas

- Arquitectura del template: **x86_64** (no arm64).
- Sin poppler, `prepare_document_images` falla con `CorruptDocumentError`
  (“poppler no disponible”).
- No subir binarios propietarios ni builds enormes al repo si no es
  necesario; preferir Opción B o artefactos generados en CI.
- `.keep` en `bin/` solo marca el árbol vacío en git hasta empaquetar.
