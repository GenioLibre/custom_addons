# Merge of sales contracts into gl_geniolibre

The legacy addon has been incorporated into gl_geniolibre 1.0.2. The original models, table names and business IDs are unchanged. Original Cybrosys attribution and AGPL-3 license notices are retained in docs/contracts; the combined addon declares AGPL-3.

## Existing databases (both modules installed)

Do not click Uninstall in Odoo. Use a restored staging copy before production. Stop all Odoo workers and cron processes, make a verified PostgreSQL dump and filestore backup, and record the current Git revision. Save counts and IDs for subscription_contracts, subscription_contracts_line and account_move where contract_origin is positive. The SQL script must run BEFORE starting Odoo with the new code, because the legacy addon directory no longer exists.

From the new checkout, using the appropriate database owner:
```sh
psql -v ON_ERROR_STOP=1 -1 -d DB_NAME -f gl_geniolibre/migrations/merge_contracts.sql
```

Then, using your normal Odoo executable, virtualenv and config:
```sh
odoo-bin -c /etc/odoo.conf -d DB_NAME -u gl_geniolibre --stop-after-init --no-http --test-enable --test-tags /gl_geniolibre
```

Inspect logs; compare the original counts and IDs, confirm invoice history, contracts and customer portal list/detail/PDF access, test a manual renewal in staging, verify only the status refresh cron is active, and check existing marketing functionality. Only start production after successful validation. If any step fails, restore both the database and filestore and the original code revision together. Do not proceed with a partial migration. For a database with only the old addon installed, first install the original gl_geniolibre version on a staging copy; the migration intentionally rejects that configuration.

Fresh databases: install gl_geniolibre normally; no migration is needed. Databases with only gl_geniolibre installed: upgrade normally (the SQL script is a no-op when no legacy metadata exists).

The SQL transfers XML ID ownership and module constraint/relation metadata without copying or deleting business records. It refuses conflicting IDs, pending module states or installed dependencies. Old unknown cron jobs are disabled. Portal endpoints retain the same URLs and enforce contract ownership for details/PDF; direct portal ACLs from the old module are removed, because the portal uses owner-filtered sudo reads.

Runtime validation requires an Odoo and PostgreSQL environment; this commit does not assert tests have passed.
