# -*- coding: utf-8 -*-
{
    'name': "GenioLibre - Custom Development",
    'version': '1.0.1',
    'author': 'GenioLibre',

    'summary': """
        GenioLibre Custom""",

    'description': """
        Desarrollo personalizado para gestion de GenioLibre
    """,

    'website': "GenioLibre.com",
    'application': True,
    'license': 'LGPL-3',
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Customizations',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail', 'portal', 'base_setup','web','website','sale','sale_management','project',],

    # always loaded
    'data': [
        'security/ir.model.access.csv',

        'views/gl_res_config_settings_views.xml',
        'views/gl_res_partner.xml',
        'views/gl_project_task.xml',
        'views/gl_project_project.xml',
        'views/gl_project_portal.xml',
        'views/gl_project_portal_calendar.xml',
        'views/gl_social_monthly_metrics.xml',
        'views/gl_contenido_flujo.xml',
        'views/sale_order_line_tax_view.xml',

        'report/gl_print_task.xml',
        'report/gl_print_marketing_report.xml',
        'report/gl_print_recibo_venta.xml',
        'report/sale_order_report_tax.xml',

        'cron/gl_cron_jobs.xml',
    ],
    "assets": {
        "web.assets_backend": [
            'gl_geniolibre/static/src/js/gl_many2many_attachment_preview.js',
            'gl_geniolibre/static/src/js/clipboard.js',
            'gl_geniolibre/static/src/xml/gl_many2many_attachment_preview_template.xml',
        ],
        "web.report_assets_common": [
            'gl_geniolibre/static/src/scss/custom_font.css',
            'gl_geniolibre/static/src/scss/custom_css.css',
        ],
        'web.assets_frontend': [
            'https://cdn.jsdelivr.net/npm/fullcalendar@5.10.1/main.min.css',
            'https://cdn.jsdelivr.net/npm/fullcalendar@5.10.1/main.min.js',  
            'gl_geniolibre/static/src/js/calendar_init.js',
        ],


    },
    # only loaded in demonstration mode
    'demo': [

    ],
}
