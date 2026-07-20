---
title: Reglas de Negocio
document_type: Business Rules Specification
section: 9
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11
---

# Reglas de Negocio

Las reglas de negocio (RN) codifican el conocimiento del dominio logístico panameño y constituyen propiedad intelectual del equipo.

## 9.1 Reglas universales

| ID | Regla | Efecto si falla |
|----|--------|-----------------|
| RN-01 | Todo documento debe estar vigente a la fecha de verificación. Si la fecha de vencimiento no es legible/parseable → revisión manual (no rechazo). Si es parseable y está vencido → rechazo. | Revisión manual / Rechazo |
| RN-02 | Si el tipo espera identidad de persona (`campos_aplicables` con cédula/nombre), el documento debe identificar a un titular. Tipos centrados en vehículo (revisado, permiso_pesos) omiten la regla. | Rechazo (o omitida) |
| RN-03 | El documento debe ser reconocido como oficial. | Rechazo |
| RN-04 | Si el tipo espera persona: el titular debe coincidir con el transportista. Sin contexto en la llamada → revisión manual (integración). Mismatch → rechazo. Tipos sin persona omiten la regla. | Revisión manual / Rechazo (o omitida) |
| RN-05 | Un documento con score de autenticidad bajo se escala a revisión manual. | Revisión manual |

## 9.2 Reglas específicas por documento

| ID | Documento | Regla | Efecto |
|----|-----------|--------|---------|
| RN-06 | Licencia | Debe tener categoría E3, F o G para transporte de carga. | Rechazo |
| RN-07 | Tipos con placa (SOAT, revisado, permiso_pesos) | La placa debe coincidir con el vehículo registrado. Sin placa en contexto → revisión manual. | Revisión manual / Rechazo |
| RN-08 | SOAT | La aseguradora debe estar autorizada por la SBP. | Rechazo |
| RN-09 | Revisado técnico | El resultado debe ser Aprobado o Aprobado condicionalmente. | Rechazo |
| RN-10 | CRCT | La cédula debe coincidir con el transportista registrado. | Rechazo |
| RN-11 | Cédula | El titular debe ser mayor de edad. | Rechazo |
| RN-12 | Licencia/SOAT/otros | Si vence en menos de 30 días, generar alerta. | Alerta (no rechazo) |