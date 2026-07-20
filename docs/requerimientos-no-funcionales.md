---

## title: Requerimientos No Funcionales
document_type: Software Requirements Specification (SRS)
section: 6
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix
author: Panalogix
last_updated: 2026-07-11

# Requerimientos No Funcionales

Los requerimientos no funcionales definen las restricciones, atributos de calidad y características operativas que debe cumplir el Sistema de Verificación Documental (SVD).

---


| ID     | Categoría         | Requerimiento                                                                                                                                                                   |
| ------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RNF-01 | Rendimiento       | El procesamiento de un documento debe completarse en menos de **15 segundos** en al menos el **95 %** de los casos.                                                             |
| RNF-02 | Escalabilidad     | El sistema debe soportar picos de carga (por ejemplo, **4 000 documentos** en pocas horas) sin pérdida de información mediante procesamiento asíncrono basado en colas.         |
| RNF-03 | Fiabilidad        | Ningún documento debe perderse ante fallos de procesamiento. Los errores irrecuperables deben aislarse en una **Dead Letter Queue (DLQ)**.                                      |
| RNF-04 | Disponibilidad    | El sistema debe ejecutarse sobre servicios gestionados con alta disponibilidad y mínima intervención humana.                                                                    |
| RNF-05 | Seguridad         | Los datos personales deben cifrarse en reposo. Las credenciales deberán gestionarse mediante un servicio de almacenamiento de secretos y nunca almacenarse en el código fuente. |
| RNF-06 | Privacidad        | El tratamiento de datos personales debe cumplir la **Ley 81 de 2019** de Panamá, incluyendo políticas de retención y derecho de eliminación.                                    |
| RNF-07 | Costo             | El costo de infraestructura en etapa MVP debe mantenerse dentro de los niveles gratuitos de los servicios utilizados.                                                           |
| RNF-08 | Mantenibilidad    | El sistema debe seguir una arquitectura en capas (**Handlers**, **Services** y **Repositories**) con responsabilidades claramente separadas.                                    |
| RNF-09 | Observabilidad    | El sistema debe exponer métricas operativas, incluyendo errores, profundidad de las colas, tiempos de procesamiento y costos asociados a los modelos de IA.                     |
| RNF-10 | Portabilidad      | Toda la infraestructura debe definirse como **Infrastructure as Code (IaC)** para facilitar su reproducción entre ambientes.                                                    |
| RNF-11 | Interoperabilidad | La integración con Panalogix debe realizarse mediante contratos desacoplados (**API REST** y **Webhooks**), evitando el acceso compartido a bases de datos.                     |
| RNF-12 | Usabilidad        | Las interfaces de usuario deben respetar el branding de Panalogix y ofrecer una experiencia moderna, consistente y profesional.                                                 |


