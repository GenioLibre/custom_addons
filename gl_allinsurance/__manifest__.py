# -*- coding: utf-8 -*-
{
    "name": "GL AllInsurance",
    "version": "1.0.0",
    "author": "GenioLibre",
    "summary": "Workflow, pendientes y templates de email",
    "description": """
        Modulo para gestionar workflow, pendientes, templates de email e historial.
    """,
    "website": "GenioLibre.com",
    "application": True,
    "license": "LGPL-3",
    "category": "Customizations",
    "depends": ["base", "mail", "contacts"],
    "data": [
        "security/ir.model.access.csv",
        "security/gl_allinsurance_ui.xml",
        "views/gl_allinsurance_views.xml",
        "data/gl_allinsurance_user_defaults.xml",
    ],
    "demo": [],
}
