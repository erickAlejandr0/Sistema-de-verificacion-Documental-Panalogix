# Matriz de Trazabilidad — SVD Panalogix

> Fuente de verdad para relacionar requerimientos funcionales (RF), casos de uso (CU),
> historias de usuario (HU), módulos del sistema y fase/prompt del playbook donde se implementan.
> Derivada exclusivamente de: documento de Ingeniería de Software, documento de Arquitectura
> (vista de desarrollo) y Playbook de Cursor. No introduce información nueva.
>
> **Uso:** contexto fijo para Cursor y control de avance del proyecto. La columna **Estado**
> se actualiza conforme se completa cada prompt del playbook.
>
> Estados posibles: `Pendiente` · `En progreso` · `Implementado` · `Verificado`

---

## 1. Módulos del sistema (vista de desarrollo)

| ID módulo | Ruta | Responsabilidad |
|-----------|------|-----------------|
| M-ING | `app/handlers/api_handler.py` (ingesta) + `app/repositories/s3_repository.py` | Ingesta: presigned URLs, validación de archivo, registro y encolado. |
| M-OCR | `app/services/ocr_service.py` + `prompts/` | Extracción semántica híbrida (Haiku/Sonnet), detección de tipo, anomalías. |
| M-NORM | `app/services/normalizador.py` | Normalización de campos heterogéneos a conceptos comunes. |
| M-RULES | `app/services/rules_engine.py` | Reglas universales, específicas y validación cruzada. |
| M-SCORE | `app/services/scoring.py` | Cálculo de score de lectura y score de autenticidad. |
| M-PERSIST | `app/repositories/verificacion_repository.py` | Persistencia en RDS (documentos, historial, correcciones). |
| M-NOTIF | `app/services/sns_service.py` | Publicación de resultados y alertas en SNS. |
| M-WEBHOOK | `app/services/webhook_service.py` | Notificación a Panalogix vía webhook firmado. |
| M-ORQ | `app/handlers/lambda_handler.py` | Orquestación del pipeline de verificación. |
| M-ALERT | `app/handlers/expiration_handler.py` | Generación de alertas de vencimiento (EventBridge). |
| M-API | `app/handlers/api_handler.py` | API REST de ingesta, consulta, resolución manual y observación interna de patrones (`GET /admin/patrones`, solo Retool). |
| M-PATRON | `app/repositories/patron.py` + `app/services/pattern_learning.py` | Acumulación y consulta de patrones aprendidos (RF-22). |
| M-FRONT | Vista transportista (Next.js) + Retool + Grafana | Interfaces de usuario y gestión. |

---

## 2. Casos de uso (documento de Ingeniería, sección 7)

| CU | Nombre | Actor principal |
|----|--------|-----------------|
| CU-01 | Subir documento | Transportista |
| CU-02 | Verificar documento (automático) | Sistema (disparado por cola) |
| CU-03 | Revisar caso manual | Equipo Panalogix |
| CU-04 | Generar alertas de vencimiento | Sistema (disparado por EventBridge) |
| CU-05 | Consultar estado documental | Transportista |

---

## 3. Historias de usuario (documento de Ingeniería, sección 8)

| HU | Rol | Historia |
|----|-----|----------|
| HU-01 | Transportista | Subir documentos desde el celular para completar la verificación sin trámites presenciales. |
| HU-02 | Transportista | Recibir notificación cuando un documento sea verificado, para saber si puede operar. |
| HU-03 | Transportista | Recibir aviso antes de que venza un documento, para renovarlo a tiempo. |
| HU-04 | Transportista | Ver un sello de verificación en su perfil, para generar confianza y acceder a más fletes. |
| HU-05 | Equipo | Revisar los casos dudosos en un panel centralizado, para resolverlos con toda la información. |
| HU-06 | Equipo | Que sus correcciones alimenten el sistema, para que mejore su precisión con el tiempo. |
| HU-07 | Equipo | Consultar métricas de precisión y volumen, para entender el desempeño del sistema. |
| HU-08 | Equipo | Ver el costo por documento y el gasto acumulado, para controlar el presupuesto. |
| HU-09 | Empresa | Contratar transportistas cuya documentación ya esté verificada, para reducir riesgo. |
| HU-10 | Empresa | Ver el estado de verificación de un transportista antes de asignarle un flete. |

---

## 4. Matriz principal — RF → CU → HU → Módulo → Fase/Prompt → Estado

> Prioridad MoSCoW según sección 14 del documento de Ingeniería.

| RF | Descripción | Prioridad | CU | HU | Módulo | Fase / Prompt | Estado |
|----|-------------|-----------|----|----|--------|---------------|--------|
| RF-01 | Generar URLs de subida temporales y firmadas. | Must | CU-01 | HU-01 | M-ING / M-API | Fase 6 / P6.1 | Pendiente |
| RF-02 | Restringir tipo (JPG/PNG/PDF) y tamaño máx. (10 MB). | Must | CU-01 | HU-01 | M-ING / M-API | Fase 6 / P6.1 | Pendiente |
| RF-03 | Registrar metadatos de cada documento subido. | Must | CU-01 | HU-01 | M-PERSIST | Fase 2 / P2.3 | Pendiente |
| RF-04 | Encolar cada documento para procesamiento asíncrono. | Must | CU-01 | HU-01 | M-ING / M-API | Fase 6 / P6.1 | Pendiente |
| RF-05 | Preprocesar la imagen antes de la extracción. | Should | CU-02 | — | M-OCR | Fase 3 / P3.1 | Pendiente |
| RF-06 | Convertir documentos PDF a imágenes. | Must | CU-02 | — | M-OCR | Fase 3 / P3.1 | Pendiente |
| RF-07 | Extraer campos mediante extracción semántica con Claude. | Must | CU-02 | HU-01 | M-OCR | Fase 3 / P3.1, P3.2 | Pendiente |
| RF-08 | Estrategia híbrida: modelo económico primero, escalar si baja confianza. | Should | CU-02 | — | M-OCR | Fase 3 / P3.1 | Pendiente |
| RF-09 | Normalizar los campos extraídos a un modelo conceptual común. | Must | CU-02 | — | M-NORM | Fase 3 / P3.3 | Pendiente |
| RF-10 | Detectar automáticamente el tipo de documento. | Must | CU-02 | — | M-OCR | Fase 3 / P3.1, P3.2 | Pendiente |
| RF-11 | Aplicar reglas universales de validación. | Must | CU-02 | — | M-RULES | Fase 3 / P3.4 | Pendiente |
| RF-12 | Aplicar reglas específicas según el tipo detectado. | Must | CU-02 | — | M-RULES | Fase 3 / P3.4 | Pendiente |
| RF-13 | Validación cruzada con datos del transportista de Panalogix. | Must | CU-02 | — | M-RULES | Fase 3 / P3.4 | Pendiente |
| RF-14 | Calcular score de lectura y score de autenticidad independientes. | Must | CU-02 | — | M-SCORE | Fase 3 / P3.4 | Pendiente |
| RF-15 | Clasificar resultado (Aprobado/Rechazado/Revisión Manual). | Must | CU-02 | HU-04 | M-RULES / M-SCORE | Fase 3 / P3.4 | Pendiente |
| RF-16 | Publicar el resultado de cada verificación para Panalogix. | Must | CU-02 | HU-04, HU-09, HU-10 | M-NOTIF / M-WEBHOOK | Fase 4 / P4.1 · Fase 6 / P6.2 | Pendiente |
| RF-17 | Notificar al transportista el resultado de su verificación. | Must | CU-02 | HU-02 | M-NOTIF | Fase 4 / P4.1 | Pendiente |
| RF-18 | Generar alertas de vencimiento a 30, 7 y 0 días. | Should | CU-04 | HU-03 | M-ALERT | Fase 4 / P4.3 | Pendiente |
| RF-19 | Alertar al equipo cuando un caso llega a revisión manual. | Should | CU-03 | HU-05 | M-NOTIF | Fase 4 / P4.1, P4.2 | Pendiente |
| RF-20 | Permitir al equipo aprobar o rechazar manualmente. | Must | CU-03 | HU-05 | M-API | Fase 6 / P6.1 | Pendiente |
| RF-21 | Registrar cada corrección humana como dato etiquetado. | Should | CU-03 | HU-06 | M-PERSIST | Fase 2 / P2.3 · Fase 6 / P6.1 | Pendiente |
| RF-22 | Acumular patrones aprendidos por tipo y variante. | Could | — | HU-06 | M-PATRON / M-API | Fase 2 / P2.3 · Fase 4 / P4.2 · Fase 6 / P6.1 (`GET /admin/patrones`) | Hecho |
| RF-23 | Exponer métricas de precisión, volumen y costo. | Should | — | HU-07, HU-08 | M-FRONT | Fase 8 / P8.2 | Pendiente |
| RF-24 | Versionar la configuración de extracción de cada verificación. | Should | CU-02 | — | M-OCR / M-PERSIST | Fase 3 / P3.1 · Fase 2 / P2.3 | Pendiente |
| RF-25 | Permitir reprocesamiento de documentos históricos con prompts mejorados. | Could | — | HU-06 | M-PERSIST / M-OCR | Fase 2 / P2.3 · Fase 3 / P3.1 | Pendiente |

---

## 5. Cobertura de casos de uso

| CU | RF que lo componen | Módulos | Fase principal |
|----|--------------------|---------|----------------|
| CU-01 Subir documento | RF-01, RF-02, RF-03, RF-04 | M-ING, M-API, M-PERSIST | Fase 6 (ingesta) + Fase 2 (registro) |
| CU-02 Verificar documento | RF-05 a RF-17, RF-24 | M-OCR, M-NORM, M-RULES, M-SCORE, M-PERSIST, M-NOTIF, M-ORQ | Fase 3 + Fase 4 |
| CU-03 Revisar caso manual | RF-19, RF-20, RF-21 | M-API, M-NOTIF, M-PERSIST | Fase 6 + Fase 4 |
| CU-04 Generar alertas | RF-18 | M-ALERT | Fase 4 |
| CU-05 Consultar estado documental | (consulta; se apoya en RF-16/RF-20 de escritura) | M-API, M-FRONT | Fase 6 + Fase 8 |

> Nota: CU-05 es un caso de uso de consulta. No introduce RF de escritura propios en el
> catálogo de la sección 5 del documento de Ingeniería; se materializa mediante el endpoint
> de consulta de la API (P6.1) y la vista del transportista (P8.1), consumiendo datos ya
> persistidos por los RF de escritura.

---

## 6. Historias de usuario → RF

| HU | Rol | RF relacionados |
|----|-----|-----------------|
| HU-01 | Transportista | RF-01, RF-02, RF-03, RF-04, RF-07 |
| HU-02 | Transportista | RF-17 |
| HU-03 | Transportista | RF-18 |
| HU-04 | Transportista | RF-15, RF-16 (sello depende del resultado aprobado) |
| HU-05 | Equipo | RF-19, RF-20 |
| HU-06 | Equipo | RF-21, RF-22, RF-25 |
| HU-07 | Equipo | RF-23 |
| HU-08 | Equipo | RF-23 |
| HU-09 | Empresa | RF-16 (consume verificación aprobada vía Panalogix) |
| HU-10 | Empresa | RF-16 |

> Nota: HU-04 (sello de verificación) y HU-09/HU-10 (empresa) se satisfacen dentro del
> ecosistema Panalogix consumiendo los resultados que el SVD publica (RF-16). El SVD produce
> el dato; la visualización del sello y la vista de empresa viven en Panalogix, sistema
> desacoplado.

---

## 7. RF sin caso de uso directo

Estos RF son capacidades transversales o de la dimensión investigativa; no corresponden a un
CU del catálogo pero sí a HU y módulos:

| RF | Razón | HU | Módulo |
|----|-------|----|----|
| RF-22 | Acumulación de patrones — proceso interno de aprendizaje, no interacción de actor. | HU-06 | M-PATRON |
| RF-23 | Métricas — se consumen vía dashboards, no un CU operativo. | HU-07, HU-08 | M-FRONT |
| RF-25 | Reprocesamiento — operación de mantenimiento/investigación. | HU-06 | M-PERSIST, M-OCR |

---

## 8. Convención de actualización

Al cerrar cada prompt del playbook, actualizar la columna **Estado** de los RF cubiertos:

- `Pendiente` → aún no iniciado.
- `En progreso` → prompt ejecutado, en validación contra checklist.
- `Implementado` → checklist del prompt superado.
- `Verificado` → cubierto por tests (Fase 7) o validado contra criterios de aceptación.

> Regla de consistencia: cada RF debe alcanzar al menos `Implementado` antes de considerar
> cerrada su fase. Los criterios de aceptación (documento de Ingeniería, sección 13) son la
> referencia para pasar a `Verificado`.
