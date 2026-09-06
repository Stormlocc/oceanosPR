# Arquitectura de Fase 0

La arquitectura mantiene fronteras explícitas entre adquisición, procesamiento
científico, compuestos, almacenamiento/catalogación, publicación y API. En esta
fase cada frontera existe como paquete importable, pero no contiene lógica de
dominio.

La única funcionalidad implementada es transversal: carga de configuración
tipada. No se conecta a servicios externos y no crea ni modifica directorios de
datos al cargar la configuración.

