---
title: Restricciones
document_type: Software Requirements Specification (SRS)
section: 10
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11
---

# Restricciones

## 10.1 Restricciones técnicas

- Construcción asistida por IA: El desarrollo del código se delega a herramientas de IA (Cursor); el rol del equipo es de orquestación y arquitectura.
- Plataforma AWS: La infraestructura debe implementarse sobre AWS, alineada con la certificación AWS Solutions Architect Associate.
- Dependencia de Claude: La extracción documental depende de la API de Anthropic y está sujeta a sus límites de tasa y disponibilidad.
- Presupuesto limitado: El MVP debe operar dentro de los niveles gratuitos de los servicios utilizados.

## 10.2 Restricciones legales y regulatorias

- Ley 81 de 2019: El tratamiento de datos personales está regido por la Ley 81 de 2019 de Panamá.
- No scraping oficial: No se permite el scraping de portales gubernamentales; los transportistas aportan sus propios documentos.
- Normativa ATTT: Los requisitos documentales siguen la normativa de la ATTT para operadores de carga.

## 10.3 Restricciones de negocio

- Sistema propietario: El sistema es propietario del equipo Panalogix y de uso exclusivo dentro de su ecosistema.
- Limitación de pagos: Stripe Connect no está disponible para producción en Panamá; los pagos operan en modo sandbox (aplica al ecosistema Panalogix, no al SVD directamente).