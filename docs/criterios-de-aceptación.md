---

## title: Criterios de Aceptación
document_type: Software Requirements Specification (SRS)
section: 13
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11

# Criterios de Aceptación

El sistema se considera aceptable cuando cumple los siguientes criterios verificables:


| ID    | Criterio de aceptación                                                                                                          |
| ----- | ------------------------------------------------------------------------------------------------------------------------------- |
| CA-01 | Un transportista puede subir un documento y recibir un resultado de verificación sin intervención manual en el flujo normal.    |
| CA-02 | El sistema extrae correctamente los campos clave de al menos el 90% de los documentos legibles de prueba.                       |
| CA-03 | El sistema clasifica cada verificación como Aprobado, Rechazado o Revisión Manual de forma coherente con las reglas de negocio. |
| CA-04 | Un documento vencido nunca se clasifica como Aprobado.                                                                          |
| CA-05 | Un documento con señales de manipulación se escala a Revisión Manual y no se aprueba automáticamente.                           |
| CA-06 | El sistema genera alertas de vencimiento a 30, 7 y 0 días de la expiración.                                                     |
| CA-07 | Ningún documento se pierde ante un fallo de procesamiento; los fallos irrecuperables quedan en la DLQ.                          |
| CA-08 | Los datos personales sensibles se almacenan cifrados.                                                                           |
| CA-09 | El resultado de cada verificación se publica y es consumible por Panalogix vía webhook.                                         |
| CA-10 | El equipo puede resolver un caso de revisión manual y la corrección queda registrada.                                           |
| CA-11 | Las métricas de precisión, volumen y costo son visibles en el panel de monitoreo.                                               |
| CA-12 | La infraestructura completa se despliega desde código (IaC) con un comando.                                                     |


