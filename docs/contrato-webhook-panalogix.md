# Contrato webhook SVD → receptor (Panalogix u otro)

Especificación formal del acople de **salida** del Sistema de Verificación
Documental (SVD). El receptor (panel / backend que consume resultados) es una
integración futura: el SVD deja este contrato listo y **no** depende de que
exista un endpoint activo.

Configuración operativa (sin valores hardcodeados de dominio):

| Parámetro SSM / env | Descripción |
|---------------------|-------------|
| `WEBHOOK_URL` | URL **HTTPS** del receptor |
| `WEBHOOK_HMAC_SECRET` | Secreto compartido para HMAC-SHA256 |

Implementación de referencia: `app/services/webhook_service.py`.

---

## 1. Transporte

- Método: `POST`
- Body: JSON UTF-8 (bytes exactos del `Message` SNS; el emisor **no**
  re-serializa)
- Headers obligatorios:

| Header | Descripción |
|--------|-------------|
| `Content-Type` | `application/json; charset=utf-8` |
| `X-SVD-Event-Type` | Tipo de evento (ver §3) |
| `X-SVD-Signature` | Firma HMAC (ver §4) |
| `User-Agent` | `svd-webhook/1.0` |

---

## 2. Payload JSON

### 2.1 Resultado de verificación

`X-SVD-Event-Type: verificacion_resultado`

```json
{
  "transportista_id": "<uuid>",
  "tipo_documento": "<string ≤40>",
  "resultado": "APROBADO | RECHAZADO | REVISION_MANUAL",
  "score_lectura": "<string NUMERIC(4,3) o null>",
  "score_autenticidad": "<string NUMERIC(4,3) o null>",
  "fecha_vencimiento": "<YYYY-MM-DD o null>"
}
```

Scores como **string** (nunca float JSON) para preservar precisión.

### 2.2 Alerta (vencimiento o revisión manual)

Mismos 6 campos, más:

```json
{
  "...": "...",
  "dias_aviso": 30,
  "event_type": "alerta_vencimiento_30"
}
```

Valores típicos de `event_type` / `X-SVD-Event-Type`:

| Valor | Significado |
|-------|-------------|
| `verificacion_resultado` | Resultado de verificación |
| `alerta_vencimiento_30` | Aviso a 30 días |
| `alerta_vencimiento_7` | Aviso a 7 días |
| `vencimiento_critico` | Vencido o día 0 |
| `revision_manual` | Caso en revisión manual |

---

## 3. Entrega y reintentos (lado SVD)

1. El worker/alertas publica en SNS (at-least-once).
2. La Lambda webhook consume el mensaje y POST-ea al `WEBHOOK_URL`.
3. Reintentos **locales**: hasta 3 intentos; backoff `1s`, `2s`, `4s`.
4. Reintenta ante timeout/red, `408`, `429`, `5xx`.
5. Ante otros `4xx`: no reintenta; registra warning.
6. Tras agotar intentos: log de severidad **ERROR**; el fallo **no** se
   propaga como error crítico del SVD (el pipeline principal ya persistió y
   publicó SNS).

El receptor debe tratar entregas como **at-least-once** y deduplicar (p. ej.
por `transportista_id` + `tipo_documento` + `resultado` + `fecha_vencimiento`
o un id propio cuando exista).

---

## 4. Firma HMAC (paso a paso)

1. Tomar el **body crudo** del POST (secuencia de bytes recibida; no
   pretty-print ni reordenar claves).
2. Tomar el secreto `WEBHOOK_HMAC_SECRET` como cadena UTF-8.
3. Calcular `HMAC-SHA256(key=secret_utf8, message=raw_body_bytes)`.
4. Codificar el digest en **hexadecimal minúsculas**.
5. Enviar el header:

```http
X-SVD-Signature: sha256=<hex>
```

6. El receptor recalcula con el mismo algoritmo sobre el body recibido y
   compara en tiempo constante (`hmac.compare_digest` o equivalente).
7. Si no coincide → responder `401` (u otro 4xx); el SVD **no** reintentará
   firmas inválidas por diseño de status (tratar `401` como no reintentable).

---

## 5. Códigos de respuesta esperados del receptor

| Código | Significado para el SVD |
|--------|-------------------------|
| `2xx` | Éxito; no más reintentos |
| `408`, `429`, `5xx` | Reintento con backoff |
| Otros `4xx` (p. ej. `400`, `401`, `403`, `404`) | Fallo definitivo de esa entrega; log warning, sin más retries locales |

---

## 6. Ejemplo completo (request + firma)

Secreto de ejemplo (solo documentación; **no** usar en producción):

```text
example-webhook-secret-do-not-use-in-prod
```

Body exacto (194 bytes UTF-8; una sola línea, sin espacios tras `:`/`,`):

```json
{"transportista_id":"11111111-1111-1111-1111-111111111111","tipo_documento":"cedula","resultado":"APROBADO","score_lectura":"0.955","score_autenticidad":"0.850","fecha_vencimiento":"2027-06-15"}
```

Firma calculada:

```text
X-SVD-Signature: sha256=493f91ad97202c2b8282daba96607bbfe0da011b424bb8c4dc0d4b2e9d3b1ec0
```

Request ilustrativo:

```http
POST /hooks/svd HTTP/1.1
Host: receptor.example.com
Content-Type: application/json; charset=utf-8
User-Agent: svd-webhook/1.0
X-SVD-Event-Type: verificacion_resultado
X-SVD-Signature: sha256=493f91ad97202c2b8282daba96607bbfe0da011b424bb8c4dc0d4b2e9d3b1ec0
Content-Length: 194

{"transportista_id":"11111111-1111-1111-1111-111111111111","tipo_documento":"cedula","resultado":"APROBADO","score_lectura":"0.955","score_autenticidad":"0.850","fecha_vencimiento":"2027-06-15"}
```

Verificación en Python (receptor):

```python
import hashlib
import hmac

secret = b"example-webhook-secret-do-not-use-in-prod"
body = open("body.bin", "rb").read()  # bytes crudos del request
expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
# comparar expected con header X-SVD-Signature
```

---

## 7. Fuera de alcance de este contrato

- Autenticación de persona / JWT en el receptor (responsabilidad Panalogix).
- Suscripción SNS → Lambda y variables en SAM (infra del SVD, prompt aparte).
- Garantía exactly-once (el contrato es at-least-once).
