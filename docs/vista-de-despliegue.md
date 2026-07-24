---

## title: Vista de Despliegue - Infraestructura Física

document_type: Software Architecture Document (SAD)
section: 6
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11

# Vista de Despliegue — Infraestructura Física

La vista de despliegue muestra dónde vive físicamente cada componente y los canales de red entre las distintas zonas. Detalla la postura de seguridad de la red del sistema.

## Diagrama

`docs/diagrams/VistaDespliegue-diagrama.png`

Vista de Despliegue — Infraestructura Física

*Figura 5. Diagrama de despliegue de la infraestructura del SVD.*

## 6.1 Zonas y canales de red

El sistema se despliega en la región us-east-1 de AWS, organizado en tres zonas lógicas: cómputo serverless (las funciones Lambda, SQS, EventBridge y SNS), almacenamiento (los buckets S3 y la base de datos RDS), y seguridad y observabilidad (SSM, KMS, CloudWatch, X-Ray e IAM). Fuera de AWS residen los servicios externos: la API de Anthropic, las plataformas SaaS Retool y Grafana, y el backend de Panalogix en DigitalOcean.

Las cuatro Lambdas llevan tracing X-Ray activo (`Globals.Function.Tracing: Active`). El topic SNS de resultados usa `TracingConfig: Active` con política resource-based hacia X-Ray. La HTTP API (API Gateway v2) **no** emite segmentos X-Ray: el Trace Map comienza en `ApiFunction`. Las colas SQS y el fan-out SNS producen trazas enlazadas (no un único segmento continuo). El patch de `psycopg2` del SDK no incluye texto SQL ni parámetros bound en los subsegmentos.

## 6.2 Postura de seguridad de red

- RDS aislado: la base de datos vive en una subnet privada, accesible únicamente desde las funciones Lambda. No está expuesta a internet.
- Tráfico cifrado: todo el tráfico externo — hacia Anthropic, hacia Panalogix, desde el dispositivo del transportista — viaja cifrado sobre HTTPS/TLS.
- Secretos gestionados: las credenciales y claves nunca viven en el código; se resuelven en **despliegue** con `{{resolve:ssm-secure:...}}` inyectado como variables de entorno de cada Lambda (la app no llama a SSM en runtime). Antes de `sam deploy` deben existir como SecureString: `/svd/{env}/DB_PASSWORD`, `ANTHROPIC_API_KEY`, `PANALOGIX_API_KEY`, `RETOOL_API_KEY`, `WEBHOOK_URL`, `WEBHOOK_HMAC_SECRET`.
- Acceso mediado: Retool / Panalogix consumen la HTTP API del sistema (sin CORS: solo servidor-a-servidor) y Grafana solo lee métricas de CloudWatch; ninguno accede directamente a la base de datos.
- Mínimo privilegio: cada función y servicio recibe únicamente los permisos IAM que necesita, siguiendo el principio de mínimo privilegio.
- Conectividad Lambda↔RDS por VPC Endpoints: las Lambdas que acceden a RDS se despliegan dentro de la VPC, en subnets con ruta a la subnet privada de la base de datos. La VPC y sus subnets privadas se crean como parte del propio template de infraestructura como código (Fase 5), sin depender de una red preexistente en la cuenta — el proyecto se despliega en una cuenta AWS estándar (Free Tier) con control total sobre sus recursos, no en un entorno de laboratorio restringido. Para alcanzar servicios AWS (S3, SNS, SQS, SSM) sin salir a internet, se usan VPC Endpoints — no NAT Gateway — evitando el costo fijo de un NAT corriendo 24/7. Solo el tráfico a la API de Anthropic, fuera de AWS, se evalúa caso por caso frente al costo de un NAT en el contexto del despliegue.
