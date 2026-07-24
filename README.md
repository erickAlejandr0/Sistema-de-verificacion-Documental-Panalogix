<div align="center">

# SVD · Panalogix

**Sistema de Verificación Documental** — plataforma serverless de extracción y validación de documentos regulatorios mediante inteligencia artificial, desarrollada como servicio backend independiente para el ecosistema Panalogix.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white)
![AWS Lambda](https://img.shields.io/badge/AWS_Lambda-FF9900?style=for-the-badge&logo=awslambda&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)

</div>

---

## Resumen ejecutivo

Panalogix es un marketplace de logística de carga terrestre en Panamá. La habilitación operativa de cada transportista requiere verificar seis documentos regulatorios —licencia de conducir, cédula, SOAT, revisado técnico, CRCT y permiso de pesos—, cada uno con su propio formato, entidad emisora y criterio de vigencia. Realizado manualmente, este proceso toma entre 3 y 5 días hábiles y no escala con el crecimiento de la plataforma.

**SVD** automatiza el ciclo completo de verificación como un servicio independiente: recibe el documento, lo interpreta mediante inteligencia artificial, lo valida contra un motor de reglas de negocio configurable, calcula dos puntajes de confianza independientes, y determina en segundos si el documento se aprueba, se rechaza, o se escala a revisión humana. El sistema está desacoplado de Panalogix por contrato explícito —API REST y webhook firmado digitalmente—, sin acceso compartido a base de datos.

**Resultado medible:** un ciclo de verificación de días reducido a segundos, con una reducción de costo de inferencia de IA de aproximadamente 48% mediante una estrategia de escalamiento entre modelos, y trazabilidad verificable —matemática y de código fuente— de cada decisión automatizada del sistema.

---


## Arquitectura por capas de competencia

### Ingeniería de software

- Persistencia mediante SQL parametrizado exclusivamente, sin ORM — decisión de arquitectura fijada desde el inicio del proyecto para eliminar la clase de vulnerabilidad de inyección SQL por construcción, no por revisión posterior.
- Idempotencia como principio de diseño, no como corrección posterior: cada extracción se identifica por la combinación de documento, huella de extracción y versión de proceso. Un reintento nunca duplica el procesamiento de IA, pero garantiza la publicación de la notificación correspondiente.
- Cobertura de pruebas en tres niveles —unitarias, integración, contrato— que incluyen explícitamente rutas de fallo (eventos malformados, configuración inválida, errores de inicialización), no únicamente el camino de éxito.

### Arquitectura de software

- Cuatro funciones serverless con responsabilidad única, comunicadas exclusivamente por colas y tópicos de mensajería, sin acoplamiento directo entre componentes.
- Aislamiento de configuración y secretos por función, verificado de forma activa durante la revisión de infraestructura previa a cada despliegue.
- Entrega de resultados con redundancia de dos vías —notificación activa vía webhook firmado y reconciliación por consulta periódica—, eliminando la dependencia de un único mecanismo de entrega.
- Cada punto de fallo asíncrono cuenta con su propia cola de mensajes fallidos y una política de reintentos calibrada de forma explícita, no dejada en su valor por defecto.

### Procesamiento con inteligencia artificial

- Estrategia híbrida de dos modelos (Claude Haiku / Sonnet) con escalamiento condicionado por umbral de confianza de lectura — reducción de costo de inferencia de aproximadamente 48% sin degradar precisión.
- Extracción semántica sin plantilla fija ("schema-agnostic"), con vocabulario de salida controlado explícitamente para prevenir degradación silenciosa de la calidad de extracción.
- Doble puntaje de confianza independiente — calidad de lectura y probabilidad de autenticidad —, lo que permite distinguir un error de captura de una señal real de manipulación documental, con reglas de negocio distintas para cada caso.
- Mecanismo de aprendizaje incremental: acumulación de patrones por tipo de documento y registro de cada corrección humana como dato etiquetado, protegido matemáticamente contra contaminación por reprocesamiento idempotente.

### Infraestructura y soluciones cloud

- Infraestructura como código en su totalidad (AWS SAM), con red privada y sin puerta de salida a internet por defecto — decisión de costo documentada explícitamente como tal, no un descuido de configuración.
- Observabilidad en tres capas: logging estructurado, trazabilidad distribuida de extremo a extremo (AWS X-Ray) y métricas de negocio personalizadas (CloudWatch, formato EMF).
- Cifrado de datos personales en reposo mediante AWS KMS, en cumplimiento de la Ley 81 de Protección de Datos Personales de Panamá.
- Infraestructura desplegada y validada contra el entorno real de AWS, incluyendo la resolución de incompatibilidades exclusivas del entorno de producción, no identificables en fase de diseño.

---

## Arquitectura

```
                                   ┌──────────────┐
   App/Panalogix ──HTTPS──▶ API Gateway ──▶ ApiFunction ──▶ RDS (verificaciones)
        │                                                        │
        │ PUT (presigned URL)                                    │
        ▼                                                        │
    S3 (raw) ──S3 Event──▶ SQS (main) ──▶ WorkerFunction ─┬───────┘
                              │                            ├──▶ Claude (Haiku/Sonnet)
                          (3 fallos)                        ├──▶ S3 (verified)
                              ▼                             └──▶ SNS (results) ──▶ WebhookFunction ──HTTPS+HMAC──▶ Panalogix
                             DLQ

   EventBridge Scheduler (cron diario) ──▶ AlertsFunction ──▶ RDS + SNS (alertas de vencimiento)
```

Cuatro funciones Lambda en Python 3.12, cada una con un único disparador y una única responsabilidad:

| Función | Disparador | Responsabilidad |
|---|---|---|
| `WorkerFunction` | SQS (evento S3 → cola) | Pipeline completo: descarga, extracción híbrida, motor de reglas, scoring, persistencia, publicación |
| `ApiFunction` | HTTP API (API Gateway) | API REST servicio-a-servicio para Panalogix y el panel de gestión interno |
| `WebhookFunction` | SNS | Notificación HTTPS firmada digitalmente hacia el receptor externo |
| `AlertsFunction` | EventBridge Scheduler (cron diario) | Detección y publicación de alertas de vencimiento documental |

Diagramas C4 completos, vistas de contexto, contenedores, procesos y despliegue, junto con el registro completo de decisiones de arquitectura, en [`docs/`](docs/).

---

<details>
<summary><strong>Flujo de verificación, paso a paso</strong></summary>
<br>

1. Panalogix envía el documento junto con el contexto ya registrado del transportista (cédula, placa, nombre).
2. El documento se sube directamente a S3 mediante una URL firmada de un solo uso; el evento de S3 encola un mensaje de procesamiento.
3. `WorkerFunction` descarga el documento y ejecuta la extracción híbrida: modelo económico primero, con escalamiento al modelo más capaz únicamente si la confianza cae bajo el umbral configurado.
4. Se normalizan los campos extraídos y se aplican las reglas de negocio, universales y específicas del tipo de documento detectado.
5. Se calculan dos puntajes independientes: calidad de lectura y probabilidad de autenticidad.
6. Se persiste la extracción —separada del documento físico, habilitando reprocesamiento futuro— y se publica el resultado.
7. `WebhookFunction` consume el resultado publicado y notifica a Panalogix vía HTTPS firmado digitalmente, con política de reintentos acotada.
8. Si el resultado requiere revisión manual, se genera una alerta para el equipo operativo correspondiente.
9. `AlertsFunction` se ejecuta diariamente y notifica vencimientos próximos, sin duplicar alertas ya atendidas.

</details>

<details>
<summary><strong>Modelo de datos</strong></summary>
<br>

Schema `verificaciones` en PostgreSQL. Diagrama entidad-relación completo en [`docs/diagrams/ModeloDeDatos.png`](docs/diagrams/ModeloDeDatos.png).

| Entidad | Propósito |
|---|---|
| `documentos` | Documento físico subido (referencias S3, fecha de eliminación conforme a Ley 81) |
| `historial` | Cada extracción realizada: campos, doble score, modelo utilizado, costo, versión |
| `correcciones` | Intervención humana etiquetada: valor del modelo frente a valor corregido |
| `tipos_documento` | Catálogo de tipos con reglas de validación en JSONB, extensible sin modificar código |
| `patrones` | Conocimiento acumulado por tipo de documento (RF-22) |
| `alertas` | Notificaciones de vencimiento enviadas, sin duplicados |

Los datos personales (cédula, nombre, placa) se cifran con KMS antes de persistir, separados del resto de la extracción.

</details>

<details>
<summary><strong>Estructura del repositorio</strong></summary>
<br>

```
SVDPanalogix/
├── app/
│   ├── handlers/       # Orquestación de eventos (API Gateway, SQS, EventBridge, SNS)
│   ├── services/       # Reglas de negocio: OCR, normalización, scoring, motor de reglas, webhook
│   ├── repositories/   # Persistencia: RDS (psycopg2), S3, SQS
│   ├── models/         # Modelos Pydantic
│   ├── config/         # Configuración aislada por función
│   └── utils/          # Fechas, cifrado, imágenes, logging estructurado, métricas, trazabilidad
├── prompts/            # Templates de extracción, uno por tipo de documento
├── migrations/         # SQL plano versionado (up/down), sin ORM
├── layers/poppler/     # Lambda Layer para conversión de PDF
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── scripts/             # Smoke test end-to-end local
├── docs/                # Documentación completa de arquitectura y negocio
├── template.yaml        # Infraestructura como código (AWS SAM)
└── samconfig.toml
```

</details>

<details>
<summary><strong>Stack tecnológico completo</strong></summary>
<br>

- **Runtime**: Python 3.12 en AWS Lambda — sin framework web, ruteo explícito por evento.
- **Inteligencia artificial**: Anthropic Claude (Haiku / Sonnet), estrategia híbrida de escalamiento.
- **Datos**: PostgreSQL en RDS, SQL puro con `psycopg2`, sin ORM.
- **Validación y configuración**: `pydantic` + `pydantic-settings`.
- **AWS**: S3, SQS, SNS, RDS, VPC / VPC Endpoints, KMS, EventBridge Scheduler, API Gateway, CloudWatch, X-Ray.
- **Procesamiento de imágenes / PDF**: `Pillow`, `pdf2image`.
- **Infraestructura como código**: AWS SAM.
- **Testing**: `pytest`.
- **Calidad de código**: `black`, `ruff`, `isort`.
- **Asistencia de desarrollo**: Cursor (agente de implementación); Claude (Anthropic) — revisión de arquitectura y seguridad.

</details>

<details>
<summary><strong>Observabilidad — logging, trazas y métricas</strong></summary>
<br>

- **Logging estructurado** en formato JSON, sin datos personales en claro, en las cuatro funciones.
- **Trazabilidad distribuida (AWS X-Ray)** activa en las cuatro funciones Lambda; el mapa de servicios conecta API, cola, procesamiento, inferencia de IA, base de datos, notificación y receptor externo.
- **Verificación de privacidad previa a la activación**: se confirmó contra el código fuente del SDK que la instrumentación de base de datos no captura texto de consultas ni valores de parámetros — únicamente metadata de conexión.
- **Métricas de negocio personalizadas** (namespace `SVD`, formato EMF vía CloudWatch): volumen de verificaciones por resultado, patrones aprendidos por tipo, correcciones manuales por campo, documentos de tipo no reconocido.

</details>

<details>
<summary><strong>Entorno de desarrollo local</strong></summary>
<br>

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env
# Completar con valores reales. La configuración falla al arranque si falta alguna variable.
```

Aplicar migraciones sobre PostgreSQL local:

```bash
psql "$DATABASE_URL" -f migrations/001_create_schema.up.sql
psql "$DATABASE_URL" -f migrations/002_create_tables.up.sql
psql "$DATABASE_URL" -f migrations/003_alerta_atendida.up.sql
psql "$DATABASE_URL" -f migrations/004_seed_tipos_campos_aplicables.up.sql
```

Smoke test end-to-end (inferencia de IA y cifrado reales; almacenamiento y mensajería simulados):

```bash
PYTHONPATH=. python scripts/smoke_test_local.py --imagen ruta/al/documento.jpg
```

Suite de pruebas:

```bash
pytest                  # suite completa
pytest -m unit
pytest -m integration
pytest -m contract
```

</details>

<details>
<summary><strong>Despliegue en AWS</strong></summary>
<br>

Prerrequisitos en Parameter Store antes de desplegar:

```
/svd/{env}/DB_PASSWORD
/svd/{env}/ANTHROPIC_API_KEY
/svd/{env}/PANALOGIX_API_KEY
/svd/{env}/RETOOL_API_KEY
/svd/{env}/WEBHOOK_URL
/svd/{env}/WEBHOOK_HMAC_SECRET
```

```bash
sam build
sam deploy --guided     # primer despliegue
sam deploy               # despliegues posteriores
```

> Sin puerta de salida a internet por defecto, lo que evita un costo fijo mensual innecesario. Se habilita únicamente cuando se requiere alcanzar la API de inferencia directamente desde la red privada.

</details>

<details>
<summary><strong>API REST</strong></summary>
<br>

Autenticación mediante clave de servicio, con dos consumidores autorizados por matriz explícita — cada uno restringido exclusivamente a las rutas que le corresponden.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/verificaciones` | Encola un documento para verificación |
| `POST` | `/verificaciones/generar-url` | Genera una URL firmada de subida |
| `GET` | `/verificaciones/{transportista_id}` | Estado documental de un transportista |
| `GET` | `/verificaciones/pendientes` | Casos en revisión manual |
| `POST` | `/verificaciones/{historial_id}/resolver` | Registra resolución manual y correcciones etiquetadas |
| `GET` | `/admin/patrones` | Conocimiento acumulado por tipo de documento — uso interno exclusivo |

</details>

<details>
<summary><strong>Seguridad y cumplimiento</strong></summary>
<br>

- Sin secretos en código fuente — resueltos en tiempo de ejecución, nunca hardcodeados.
- Datos personales cifrados antes de persistir, en cumplimiento de la Ley 81 de Protección de Datos Personales de Panamá.
- SQL parametrizado de forma exclusiva — concatenación de strings en consultas explícitamente prohibida.
- Validación estricta de toda entrada externa: tipo de archivo, tamaño máximo, esquemas de datos.
- Permisos de mínimo privilegio; la base de datos es alcanzable únicamente desde la red privada del sistema.
- Los fallos irrecuperables se enrutan a una cola de mensajes fallidos — ningún error de procesamiento se descarta en silencio.

</details>

<details>
<summary><strong>Documentación completa</strong></summary>
<br>

| Documento | Contenido |
|---|---|
| [`docs/contexto-sistema.md`](docs/contexto-sistema.md) | Problema, objetivos y alcance |
| [`docs/arquitectura-sistema.md`](docs/arquitectura-sistema.md) | Introducción arquitectónica y decisiones registradas |
| [`docs/vista-de-contexto.md`](docs/vista-de-contexto.md) | Vista C4 — Nivel 1 |
| [`docs/vista-de-contenedores.md`](docs/vista-de-contenedores.md) | Vista C4 — Nivel 2 |
| [`docs/vista-de-procesos.md`](docs/vista-de-procesos.md) | Secuencia del flujo de verificación |
| [`docs/vista-de-despliegue.md`](docs/vista-de-despliegue.md) | Topología de despliegue en AWS |
| [`docs/modelo-de-datos.md`](docs/modelo-de-datos.md) | Entidad-relación del schema |
| [`docs/diccionario-de-datos.md`](docs/diccionario-de-datos.md) | Diccionario de datos detallado |
| [`docs/reglas-de-negocio.md`](docs/reglas-de-negocio.md) | Reglas de negocio (RN-XX) |
| [`docs/contrato-webhook-panalogix.md`](docs/contrato-webhook-panalogix.md) | Contrato del webhook de salida |
| [`docs/99-trazabilidad.md`](docs/99-trazabilidad.md) | Matriz de trazabilidad completa |

</details>

---

## Autores

[![GitHub](https://img.shields.io/badge/GitHub-erickAlejandr0-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/erickAlejandr0)

## Licencia
![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)

Proyecto privado. Todos los derechos reservados.



