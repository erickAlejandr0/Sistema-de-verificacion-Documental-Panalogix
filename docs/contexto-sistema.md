---

## title: Contexto, Objetivos y Alcance

document_type: Software Requirements
version: 1.0
status: Approved
project: Sistema de Verificación Documental (SVD)
product: Panalogix

# Contexto del Proyecto

## 1.2 El problema específico

La verificación de la documentación de un transportista —licencia con categoría de carga, SOAT vigente, revisado técnico, Certificado de Registro de Carga Terrestre (CRCT), cédula y permisos especiales— es actualmente un proceso manual, lento y propenso a errores.

No existe un registro público unificado que permita validar de forma automática el cumplimiento documental de un operador de carga en Panamá.

Esta situación genera tres problemas principales:

- **Fricción de contratación:** Una empresa que necesita contratar un flete urgente no puede verificar en tiempo razonable si el transportista cumple con todos los requisitos documentales, incrementando el riesgo legal y operativo.
- **Riesgo de incumplimiento:** Los documentos vencidos pueden pasar desapercibidos hasta que ocurre una fiscalización o un incidente, cuando las consecuencias ya son inevitables.
- **Falta de escalabilidad:** La verificación manual no escala. A medida que aumenta la cantidad de transportistas registrados, el esfuerzo humano se convierte en el principal cuello de botella del negocio.

---



## 1.3 La oportunidad

El **Sistema de Verificación Documental (SVD)** transforma un proceso que actualmente requiere entre **tres y cinco días hábiles** en una operación automatizada que puede completarse en **segundos**, utilizando inteligencia artificial para la extracción y validación de información documental.

Además de automatizar el proceso operativo, el sistema construye un **corpus propietario de documentos de transporte panameños**, constituyendo:

- una barrera competitiva de entrada;
- un activo estratégico para investigación;
- una base de conocimiento para la mejora continua de los modelos de IA.

---



# Objetivos del Sistema



## 2.1 Objetivo general

Diseñar e implementar un sistema propietario de verificación documental inteligente que automatice la extracción, validación y control de vigencia de los documentos legales de transportistas de carga terrestre en Panamá, integrable con el ecosistema **Panalogix**, garantizando:

- fiabilidad operativa;
- cumplimiento normativo;
- generación de conocimiento a partir de los datos procesados.

---



## 2.2 Objetivos específicos



### 1. Extracción automática

Automatizar la extracción de información desde documentos mediante extracción semántica universal utilizando modelos de lenguaje, sin depender del formato específico de cada documento.

### 2. Validación de reglas

Definir y aplicar reglas de negocio que determinen si un documento cumple con los requisitos legales necesarios para operar dentro de la plataforma.

### 3. Verificación de autenticidad

Separar la evaluación de la calidad de lectura de la evaluación de laevaluación de autenticidad del documento, escalando a revisión humana los casos dudosos.

### 4. Control de vigencia

Notificar proactivamente a los transportistas sobre documentos próximos a vencer, reduciendo interrupciones operativas.

### 5. Generación de conocimiento

Construir un dataset propietario de documentos panameños de transporte con anotaciones de extracción, permitiendo identificar patrones y mejorar continuamente el sistema.

### 6. Cumplimiento normativo

Garantizar el tratamiento de datos personales conforme a la **Ley 81 de 2019 de Protección de Datos Personales de Panamá**.

---



# Alcance



## 3.1 Dentro del alcance

El sistema incluye las siguientes funcionalidades:

- Ingesta de documentos de transportistas en formato **JPG**, **PNG** y **PDF**.
- Extracción semántica mediante modelos Claude (**Haiku** y **Sonnet**) utilizando una estrategia híbrida.
- Normalización de la información extraída hacia un modelo conceptual común, independiente del formato del documento.
- Motor de reglas con validaciones universales y validaciones específicas según el tipo de documento detectado.
- Cálculo independiente del puntaje de calidad de lectura y del puntaje de autenticidad, con escalamiento automático a revisión manual cuando corresponda.
- Persistencia de verificaciones, patrones aprendidos y correcciones realizadas por operadores humanos.
- Notificaciones automáticas de resultados y alertas de vencimiento documental.
- Panel de gestión interna, panel de métricas de investigación y portal del transportista.
- Integración con el sistema principal de Panalogix mediante **API REST** y **Webhooks**.

---



## 3.2 Fuera del alcance

El sistema **no contempla**:

- Scraping o consultas automatizadas a portales gubernamentales (ATTT, Tribunal Electoral), debido a restricciones relacionadas con la Ley 81 de 2019.
- Emisión, renovación o gestión de documentos ante entidades oficiales.
- Detección forense avanzada de falsificaciones a nivel pericial; el sistema únicamente genera indicadores de riesgo.
- El desarrollo del marketplace de fletes de Panalogix, el cual constituye un sistema independiente.
- La verificación de documentos que no pertenezcan al dominio del transporte terrestre de carga en Panamá.

---



## 3.3 Tipos de documentos soportados


| Documento                                         | Entidad emisora        | Obligatorio | Renovación   |
| ------------------------------------------------- | ---------------------- | ----------- | ------------ |
| Licencia de conducir (E3, F, G)                   | ATTT                   | Sí          | Cada 4 años  |
| Cédula de identidad                               | Tribunal Electoral     | Sí          | Cada 10 años |
| SOAT                                              | Aseguradora autorizada | Sí          | Anual        |
| Revisado técnico                                  | Centro autorizado      | Sí          | Anual        |
| CRCT (Certificado de Registro de Carga Terrestre) | ATTT                   | Sí          | Variable     |
| Permiso de Pesos y Dimensiones                    | ATTT                   | Condicional | Anual        |


