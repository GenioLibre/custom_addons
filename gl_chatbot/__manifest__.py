# -*- coding: utf-8 -*-
{
    'name': "GenioLibre - AI ChatBot",
    'version': '1.0.1',
    'author': 'GenioLibre',

    'summary': """
        ChatBot con Inteligencia Artificial integrado en Odoo""",

    'description': """
        Módulo personalizado que integra un ChatBot de Inteligencia Artificial
        para optimizar la gestión de clientes, mejorar la atención a usuarios
        y automatizar respuestas dentro de Odoo.
    """,

    'website': "geniolibre.com",
    'application': True,
    'license': 'LGPL-3',
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Customizations',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail', 'portal', 'base_setup'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',

        'views/gl_res_config_settings_views.xml',
        'views/gl_whatsapp_chatroom_views.xml',
        'views/chatbot_knowledge_views.xml',

    ],
    'assets': {
        'web.assets_backend': [
            'gl_chatbot/static/src/components/ChatroomView.js',
            'gl_chatbot/static/src/components/ChatroomView.xml',
            'gl_chatbot/static/src/components/ChatroomView.css',
        ],
    }, # only loaded in demonstration mode
    'demo': [

    ],
}
