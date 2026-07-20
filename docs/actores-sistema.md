---

## title: Actores del Sistema
document_type: Software Requirements Specification
section: 4
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11

# Actores del Sistema

## 4.1 Actores primarios

Los actores primarios representan a los usuarios humanos que interactúan directamente con el Sistema de Verificación Documental (SVD).


| Actor                | Tipo   | Descripción y responsabilidad                                                                                                                                              |
| -------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Transportista**    | Humano | Sube sus documentos, consulta el estado de sus verificaciones documentales y recibe alertas sobre próximos vencimientos.                                                   |
| **Equipo Panalogix** | Humano | Revisa verificaciones que requieren intervención manual, aprueba o rechaza casos dudosos, administra reglas de validación y consulta métricas operativas e investigativas. |


---



## 4.2 Actores secundarios (Sistemas)

Los actores secundarios corresponden a sistemas o servicios externos con los que el SVD interactúa para cumplir sus procesos de negocio.


| Actor                  | Tipo           | Descripción y responsabilidad                                                       |
| ---------------------- | -------------- | ----------------------------------------------------------------------------------- |
| **Sistema Panalogix**  | Sistema        | Envía documentos con contexto de validación y recibe resultados vía webhook.        |
| **Claude (Anthropic)** | Servicio de IA | Realiza la extracción semántica universal de los campos presentes en los documentos |
| **Amazon EventBridge** | Servicio AWS   | Dispara la revisión programada de vencimientos de forma automática.                 |


---



## Resumen de responsabilidades



### Actores humanos

- **Transportista**
  - Cargar documentos.
  - Consultar el estado de las verificaciones.
  - Recibir notificaciones y alertas de vencimiento.
- **Equipo Panalogix**
  - Revisar verificaciones manuales.
  - Resolver casos ambiguos.
  - Administrar reglas del sistema.
  - Supervisar métricas e indicadores.



### Sistemas externos

- **Sistema Panalogix**
  - Iniciar solicitudes de verificación.
  - Consumir resultados del proceso.
  - Integrarse mediante API REST y Webhooks.
- **Claude (Anthropic)**
  - Extraer información estructurada desde documentos.
  - Generar la salida semántica utilizada por el motor de validación.
- **Amazon EventBridge**
  - Ejecutar tareas programadas.
  - Disparar revisiones automáticas de vencimientos.

