-- Privilegios por rol de base de datos (etapa 1). Se aplica después de crear los roles.
--   acxes_owner: propietario del esquema, migraciones e ingesta. B1 lo usa como credencial amplia
--   acxes_app:   servicio de recuperación de S. Lee documentos y fragmentos, solo inserta en auditoría
--   acxes_audit: lectura del registro de auditoría desde un script (P16)
--   acxes_pdp:   PDP. Solo ejecuta pdp_subject (pdp.sql), sin acceso directo a tablas

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM acxes_app, acxes_audit, acxes_pdp;

GRANT USAGE ON SCHEMA public TO acxes_app, acxes_audit, acxes_pdp;

GRANT SELECT ON documents, chunks TO acxes_app;
GRANT INSERT ON audit_log TO acxes_app;

GRANT SELECT, INSERT ON audit_log TO acxes_audit;
