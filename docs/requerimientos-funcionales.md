---
title: Requerimientos Funcionales
document_type: Software Requirements Specification (SRS)
section: 5
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11
---

# Requerimientos Funcionales

Los requerimientos funcionales identifican las capacidades que debe proporcionar el Sistema de Verificación Documental (SVD).

Cada requerimiento utiliza el prefijo **RF** y su prioridad se clasifica mediante la metodología **MoSCoW**:

- **Must:** indispensable para el funcionamiento del sistema.
- **Should:** altamente recomendable.
- **Could:** funcionalidad deseable para futuras iteraciones.

---

# 5.1 Módulo de Ingesta

| ID | Requerimiento | Prioridad |
|----|---------------|-----------|
| RF-01 | El sistema debe generar URLs de subida temporales y firmadas para que el transportista cargue documentos directamente al almacenamiento. | Must |
| RF-02 | El sistema debe restringir los archivos permitidos a **JPG**, **PNG** y **PDF**, con un tamaño máximo de **10 MB**. | Must |
| RF-03 | El sistema debe registrar los metadatos de cada documento cargado, incluyendo transportista, tipo de documento, fecha de carga y estado inicial. | Must |
| RF-04 | El sistema debe encolar cada documento recibido para su procesamiento asíncrono. | Must |

---

# 5.2 Módulo de Procesamiento

| ID | Requerimiento | Prioridad |
|----|---------------|-----------|
| RF-05 | El sistema debe preprocesar las imágenes (contraste, orientación y redimensionado) antes de iniciar la extracción de información. | Should |
| RF-06 | El sistema debe convertir documentos PDF a imágenes antes del procesamiento. | Must |
| RF-07 | El sistema debe extraer los campos del documento mediante extracción semántica universal utilizando Claude. | Must |
| RF-08 | El sistema debe utilizar una estrategia híbrida, ejecutando inicialmente un modelo de menor costo y escalando a uno de mayor precisión cuando el nivel de confianza sea insuficiente. | Should |
| RF-09 | El sistema debe normalizar la información extraída hacia un modelo conceptual común, independiente del formato del documento. | Must |
| RF-10 | El sistema debe detectar automáticamente el tipo de documento procesado. | Must |

---

# 5.3 Módulo de Validación

| ID | Requerimiento | Prioridad |
|----|---------------|-----------|
| RF-11 | El sistema debe aplicar reglas universales de validación (vigencia, identificación del titular y reconocimiento como documento oficial). | Must |
| RF-12 | El sistema debe aplicar reglas específicas según el tipo de documento detectado. | Must |
| RF-13 | El sistema debe realizar validaciones cruzadas entre la información extraída del documento y los datos del transportista enviados por Panalogix. | Must |
| RF-14 | El sistema debe calcular de forma independiente un puntaje de calidad de lectura y un puntaje de autenticidad. | Must |
| RF-15 | El sistema debe clasificar cada verificación como **Aprobada**, **Rechazada** o **Revisión Manual**, utilizando umbrales configurables. | Must |

---

# 5.4 Módulo de Notificaciones y Alertas

| ID | Requerimiento | Prioridad |
|----|---------------|-----------|
| RF-16 | El sistema debe publicar el resultado de cada verificación para su consumo por Panalogix. | Must |
| RF-17 | El sistema debe notificar al transportista el resultado de la verificación realizada. | Must |
| RF-18 | El sistema debe generar alertas automáticas de vencimiento con **30**, **7** y **0 días** de anticipación. | Should |
| RF-19 | El sistema debe notificar al equipo Panalogix cuando una verificación sea escalada a revisión manual. | Should |

---

# 5.5 Módulo de Gestión e Investigación

| ID | Requerimiento | Prioridad |
|----|---------------|-----------|
| RF-20 | El sistema debe permitir al equipo Panalogix aprobar o rechazar manualmente verificaciones pendientes. | Must |
| RF-21 | El sistema debe registrar cada corrección realizada por un operador como dato etiquetado para la mejora continua del sistema. | Should |
| RF-22 | El sistema debe acumular patrones aprendidos por tipo y variante de documento. | Could |
| RF-23 | El sistema debe exponer métricas de precisión, volumen procesado y costo por documento. | Should |
| RF-24 | El sistema debe versionar la configuración de extracción utilizada en cada verificación. | Should |
| RF-25 | El sistema debe permitir el reprocesamiento de documentos históricos utilizando nuevas versiones del prompt o de la estrategia de extracción. | Could |