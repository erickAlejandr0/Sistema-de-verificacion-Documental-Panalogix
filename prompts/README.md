# Prompts de extracción SVD

Plantillas versionadas para Claude (extracción schema-agnostic). No hardcodear
el texto del prompt en `app/services/ocr.py`: cargar desde este directorio.

## Archivos

| Archivo | Uso |
|---------|-----|
| `extraction_universal.txt` | Base universal (default actual de `OcrService`) |
| `extraction_licencia.txt` | Licencia de conducir (ATTT, E3/F/G) |
| `extraction_soat.txt` | SOAT |
| `extraction_revisado.txt` | Revisado técnico |
| `extraction_crct.txt` | CRCT |
| `extraction_cedula.txt` | Cédula (Tribunal Electoral) |
| `extraction_permiso_pesos.txt` | Permiso de pesos y dimensiones |

Códigos `tipo_detectado`: `licencia` | `cedula` | `soat` | `revisado` | `crct` | `permiso_pesos` | `desconocido`.

## Contrato JSON común

Todos los templates piden **solo** JSON (sin markdown), con al menos:

```json
{
  "tipo_detectado": "licencia",
  "entidad_emisora": "ATTT",
  "campos": {
    "campo": { "valor": "... o null", "confianza": "0.970" }
  },
  "anomalias": [],
  "validacion_temporal": {
    "emision_antes_vencimiento": true,
    "detalle": null
  }
}
```

- `confianza`: string decimal de 3 dígitos (nunca float JSON).
- Campo ilegible → `"valor": null` (nunca inventar).
- Fechas: `DD/MM/YYYY` cuando apliquen.
- Marcador de contexto runtime: `{{CONTEXT_BLOCK}}` (lo sustituye el OCR).

## Marcadores de dominio

Bloques para que el equipo inserte conocimiento panameño sin romper la
estructura:

```
<<<DOMAIN_KNOWLEDGE:nombre_del_tema>>>
...
<<<END_DOMAIN_KNOWLEDGE>>>
```

## Compatibilidad con el parser OCR (verificado)

Revisado en `app/services/ocr.py` (P3.1 cerrado con `pdf2image`):

- `_parse_extraction_payload` solo consume `tipo_detectado`, `campos` y
  `anomalias` vía `.get()`.
- `ExtractionResult` se construye con kwargs explícitos; su `ConfigDict` no
  usa `extra="forbid"` (default Pydantic v2: `extra="ignore"`).

Por tanto, `entidad_emisora` y `validacion_temporal` **no rompen** el parseo
actual: se ignoran hasta que una fase posterior los modele. Comportamiento
**verificado en código**, no supuesto.

## prompt_hash

`prompt_hash` = SHA-256 UTF-8 del contenido del archivo de template **antes**
de sustituir `{{CONTEXT_BLOCK}}`. Se persiste en `historial.prompt_hash`.
