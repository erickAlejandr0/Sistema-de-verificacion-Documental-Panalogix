---
title: Introducción Arquitectónica y Registro de Decisiones Arquitectónicas
document_type: Software Architecture Document (SAD)
section: 1-7
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11
---

# 1. Introducción Arquitectónica

## 1.1 Propósito del documento

Este documento consolida la arquitectura oficial del Sistema de Verificación Documental (SVD) de Panalogix. Reúne los diagramas del sistema, el modelo de datos, y el detalle técnico de cómo se comunican los componentes entre sí — los medios, protocolos y contratos que gobiernan cada interacción. Es la referencia arquitectónica autoritativa sobre la que se construye la implementación.

## 1.2 Naturaleza del sistema

El SVD es un sistema propietario e independiente que automatiza la extracción, validación y control de vigencia de los documentos legales de transportistas de carga terrestre en Panamá. Originado como un módulo de Panalogix, evolucionó a un sistema autónomo que se comunica con la plataforma principal mediante contratos explícitos y desacoplados. Utiliza inteligencia artificial (Claude) para la extracción semántica de documentos heterogéneos y una infraestructura serverless en AWS para operar de forma escalable y resiliente.

---

# 7. Registro de Decisiones Arquitectónicas

Esta sección consolida las decisiones técnicas que definen la arquitectura, con su justificación. Constituyen el fundamento sobre el que se sostiene todo el diseño.

| Decisión | Justificación |
|----------|---------------|
| Presigned URLs para subida | El archivo viaja directo a S3 sin consumir cómputo; el sistema escala sin cuello de botella. |
| SQS entre S3 y el worker | Garantiza que ningún documento se pierda y absorbe picos de tráfico (resiliencia). |
| Dead Letter Queue | Aísla los documentos irrecuperables sin bloquear la cola; da visibilidad de fallos. |
| Lambda serverless | Cómputo bajo demanda; costo proporcional al uso, sin servidores siempre activos. |
| Estrategia híbrida Haiku/Sonnet | Reduce el costo de IA cerca del 48% sin sacrificar precisión en documentos difíciles. |
| Extracción schema-agnostic | Permite procesar documentos heterogéneos sin conocer su layout; habilita la dimensión investigativa. |
| Doble score (lectura/autenticidad) | Separa leer bien de ser auténtico; un documento falso bien leído se escala a revisión. |
| Fan-out con SNS | Permite agregar suscriptores (email, auditoría) sin modificar el productor. |
| EventBridge para vencimientos | Automatiza las alertas proactivas sin mantener procesos siempre activos. |
| Schema separado en RDS | Aislamiento lógico del módulo sin el costo de una instancia dedicada. |
| Integración por API + webhook | Desacopla el SVD de Panalogix; cada sistema es dueño de sus datos. |
| Cifrado PII con KMS | Cumple la Ley 81 de 2019 de protección de datos personales de Panamá. |
| Infraestructura como código (SAM) | Despliegue reproducible entre ambientes con un comando; versionable en Git. |