# -*- coding: utf-8 -*-
{
    "name": "GenioLibre - Branding Lite",
    "version": "1.0.0",
    "author": "GenioLibre",
    "summary": "Branding basico para el backend de Odoo",
    "description": """
        Branding basico: titulo de ventana, limpieza del menu de usuario
        y ocultar Powered by Odoo en login.
    """,
    "website": "GenioLibre.com",
    "application": False,
    "installable": True,
    "license": "LGPL-3",
    "category": "Customizations",
    "depends": ["base", "base_setup", "web"],
    "data": [
        "views/gl_branding_lite.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "gl_branding_lite/static/src/js/gl_hide_user_menus.js",
            "gl_branding_lite/static/src/js/gl_web_window_title.js",
        ],
    },
}
