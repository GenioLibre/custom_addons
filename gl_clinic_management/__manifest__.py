# -*- coding: utf-8 -*-

{
    "name": "GL Clinic Management",
    "version": "1.0.0",
    "category": "Healthcare",
    "summary": "Gestión básica de pacientes, historias clínicas y medicinas",
    "author": "GenioLibre",
    "website": "https://geniolibre.com",
    "license": "LGPL-3",
    "application": True,
    "installable": True,
    "depends": ["base", "mail", "web"],
    "data": [
        "security/gl_clinic_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "report/medical_history_report.xml",
        "views/clinic_medicine_views.xml",
        "views/clinic_patient_views.xml",
        "views/clinic_medical_history_views.xml",
        "views/clinic_dashboard_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "gl_clinic_management/static/src/js/voice_dictation_field.js",
            "gl_clinic_management/static/src/xml/voice_dictation_field.xml",
            "gl_clinic_management/static/src/scss/gl_clinic_management.scss",
        ],
    },
}
