-- Run with Odoo stopped, a verified backup, and psql -v ON_ERROR_STOP=1 -1.
-- Never uninstall the old module through Odoo.
DO $merge$
DECLARE
    old_id integer;
    new_id integer;
    old_state text;
    new_state text;
    old_name constant text := 'sales_contract_and_recurring_invoices';
    new_name constant text := 'gl_geniolibre';
BEGIN
    SELECT id, state INTO old_id, old_state FROM ir_module_module WHERE name = old_name FOR UPDATE;
    SELECT id, state INTO new_id, new_state FROM ir_module_module WHERE name = new_name FOR UPDATE;
    IF old_id IS NULL OR old_state = 'uninstalled' THEN
        IF EXISTS (SELECT 1 FROM ir_model_data WHERE module = old_name) THEN
            RAISE EXCEPTION 'Unexpected legacy XML IDs; inspect module state before proceeding';
        END IF;
        RETURN;
    END IF;
    IF old_state <> 'installed' OR new_state IS DISTINCT FROM 'installed' THEN
        RAISE EXCEPTION 'Both modules must be installed and stable before migrating: %, %', old_state, new_state;
    END IF;
    IF EXISTS (
        SELECT 1 FROM ir_module_module_dependency d
        JOIN ir_module_module m ON m.id = d.module_id
        WHERE d.name = old_name AND m.id <> old_id AND m.state IN ('installed','to install','to upgrade')
    ) THEN
        RAISE EXCEPTION 'An installed module depends on the old addon; migrate its dependency first';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ir_model_data a JOIN ir_model_data b ON b.name = a.name
        WHERE a.module = old_name AND b.module = new_name
        AND (a.model, a.res_id) IS DISTINCT FROM (b.model, b.res_id)
    ) THEN
        RAISE EXCEPTION 'Conflicting XML IDs; no records were moved';
    END IF;
    -- Disable any retired scheduled jobs, without deleting historical records.
    UPDATE ir_cron SET active = false WHERE id IN (
        SELECT res_id FROM ir_model_data WHERE module = old_name
        AND model = 'ir.cron' AND name <> 'ir_cron_refresh_contract_status'
    );
    UPDATE ir_model_data SET noupdate = true WHERE module = old_name
        AND (model IN ('subscription.contracts','subscription.contracts.line','account.move','sale.order.line')
        OR (model = 'ir.cron' AND name <> 'ir_cron_refresh_contract_status'));
    DELETE FROM ir_model_data a USING ir_model_data b
        WHERE a.module = old_name AND b.module = new_name AND a.name = b.name
        AND a.model = b.model AND a.res_id = b.res_id;
    UPDATE ir_model_data SET module = new_name WHERE module = old_name;
    -- Reassign the technical metadata used for module cleanup, not business rows.
    UPDATE ir_model_constraint SET module = new_id WHERE module = old_id;
    UPDATE ir_model_relation SET module = new_id WHERE module = old_id;
    UPDATE ir_ui_view SET key = new_name || substring(key FROM length(old_name) + 1)
        WHERE key LIKE old_name || '.%';
    -- Retire the module without invoking destructive Odoo uninstall hooks.
    UPDATE ir_module_module SET state = 'uninstalled' WHERE id = old_id;
END
$merge$;
