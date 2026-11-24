def migrate(cr, version):
    # Run the standalone SQL before deploying when the legacy addon is installed.
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s",
               ('sales_contract_and_recurring_invoices',))
    row = cr.fetchone()
    if row and row[0] not in ('uninstalled', 'uninstallable'):
        raise RuntimeError(
            'Run gl_geniolibre/migrations/merge_contracts.sql with Odoo stopped '
            'before upgrading; do not uninstall the legacy addon.')
    cr.execute("SELECT count(*) FROM ir_model_data WHERE module = %s",
               ('sales_contract_and_recurring_invoices',))
    if cr.fetchone()[0]:
        raise RuntimeError('Legacy contract XML IDs remain; migration required.')
