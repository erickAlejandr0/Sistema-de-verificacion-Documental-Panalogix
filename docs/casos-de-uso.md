---

## title: Casos de Uso

document_type: Software Requirements Specification (SRS)
section: 7
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11

# Casos de Uso

Este documento describe los principales casos de uso del Sistema de Verificación Documental (SVD) mediante especificaciones extendidas.

---

# CU-01 — Subir documento

## Información general


| Campo               | Descripción                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| **Actor principal** | Transportista                                                                                      |
| **Precondición**    | El transportista está autenticado en Panalogix y posee un documento pendiente de verificación.     |
| **Postcondición**   | El documento queda registrado con estado **Pendiente** y es encolado para procesamiento asíncrono. |




## Flujo principal

1. El transportista selecciona el tipo de documento que desea subir.
2. El sistema genera una URL temporal y firmada para la carga.
3. El transportista carga el documento directamente al almacenamiento.
4. El sistema valida el tipo y tamaño del archivo.
5. El sistema registra el documento y lo encola para procesamiento.
6. El sistema confirma la recepción del documento al transportista.

---



# CU-02 — Verificar documento (Automático)



## Información general


| Campo               | Descripción                                                                                   |
| ------------------- | --------------------------------------------------------------------------------------------- |
| **Actor principal** | Sistema (disparado por la cola de procesamiento)                                              |
| **Precondición**    | Existe un documento pendiente en la cola de procesamiento.                                    |
| **Postcondición**   | La verificación queda registrada y el resultado es notificado a Panalogix y al transportista. |




## Flujo principal

1. El worker consume el mensaje de la cola.
2. El sistema descarga el documento.
3. El sistema realiza el preprocesamiento de la imagen.
4. El sistema extrae los campos mediante Claude utilizando una estrategia híbrida.
5. El sistema normaliza los campos al modelo conceptual común.
6. El motor de reglas evalúa el documento contra las reglas universales y específicas.
7. El sistema calcula el score de lectura y el score de autenticidad.
8. El sistema clasifica el resultado y lo persiste.
9. El sistema publica el resultado y envía las notificaciones correspondientes.

---



# CU-03 — Revisar caso manual



## Información general


| Campo               | Descripción                                                                        |
| ------------------- | ---------------------------------------------------------------------------------- |
| **Actor principal** | Equipo Panalogix                                                                   |
| **Precondición**    | Existe una verificación clasificada como **Revisión Manual**.                      |
| **Postcondición**   | El caso queda resuelto y la corrección se incorpora al dataset de mejora continua. |




## Flujo principal

1. El sistema alerta al equipo Panalogix sobre un nuevo caso pendiente.
2. Un miembro del equipo accede al panel de gestión.
3. El sistema muestra el documento, los datos extraídos y las validaciones realizadas.
4. El miembro del equipo evalúa y decide aprobar o rechazar.
5. El sistema registra la decisión y almacena la corrección como dato etiquetado.
6. El sistema notifica el resultado definitivo.

---



# CU-04 — Generar alertas de vencimiento



## Información general


| Campo               | Descripción                                                                        |
| ------------------- | ---------------------------------------------------------------------------------- |
| **Actor principal** | Sistema (disparado por Amazon EventBridge)                                         |
| **Precondición**    | Existen documentos aprobados con fecha de vencimiento registrada.                  |
| **Postcondición**   | Los transportistas reciben alertas preventivas sobre documentos próximos a vencer. |




## Flujo principal

1. Amazon EventBridge ejecuta la tarea programada.
2. El sistema consulta los documentos que vencen en 30, 7 y 0 días.
3. El sistema genera una alerta por cada documento próximo a vencer.
4. El sistema publica las alertas para notificar a los transportistas.

---



# CU-05 — Consultar estado documental



## Información general


| Campo               | Descripción                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------ |
| **Actor principal** | Transportista                                                                              |
| **Precondición**    | El transportista está autenticado y posee documentos registrados en el sistema.            |
| **Postcondición**   | El transportista conoce el estado completo de su documentación y su nivel de verificación. |




## Flujo principal

1. El transportista accede a su panel documental.
2. El sistema muestra el estado de cada documento:
  - Vigente
  - Por vencer
  - Vencido
  - En revisión
3. El sistema muestra el sello de verificación cuando toda la documentación se encuentra vigente y aprobada.

