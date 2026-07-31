# GL Clinic Management

Módulo para Odoo 19 Community que permite gestionar pacientes, historias clínicas, archivos adjuntos clínicos y un catálogo básico de medicinas.

## Instalación

1. Copiar el módulo en `custom_addons/gl_clinic_management`.
2. Actualizar la lista de aplicaciones.
3. Instalar **GL Clinic Management**.

## Actualización

```bash
./venv/bin/python odoo-bin -d NOMBRE_BD -u gl_clinic_management
```

## Seguridad

Incluye grupos para Recepción, Médico y Administrador clínico, con reglas multiempresa y restricciones Python para historias confirmadas.
