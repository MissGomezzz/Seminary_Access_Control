-- Datos base sintéticos (etapa 1): usuarios de prueba, roles, permisos y versión de política.
-- Los documentos y fragmentos no están aquí: los carga la ingesta a partir del corpus versionado
-- en data/corpus (python -m acxes.ingestion.load, que `apply` invoca al final).
-- Ejecutar después de schema.sql, grants.sql y rls.sql. El propietario no está sujeto a RLS.

TRUNCATE audit_log, chunks, documents, role_permissions, permissions, resources,
         user_roles, roles, users, policy_version RESTART IDENTITY CASCADE;

INSERT INTO policy_version (version, description) VALUES
    ('2026-09-21.1', 'Versión inicial de la política, matriz y políticas P1 a P17');

INSERT INTO roles (name) VALUES ('empleado'), ('supervisor'), ('administrador');

INSERT INTO resources (name) VALUES ('documentos');
INSERT INTO permissions (resource_id, action)
    SELECT r.id, a.action FROM resources r, (VALUES ('read'), ('search')) AS a(action);
-- P11: las dos herramientas están disponibles para los tres roles
INSERT INTO role_permissions (role_id, permission_id)
    SELECT ro.id, p.id FROM roles ro, permissions p;

-- Usuarios de prueba. El nivel sale del rol (P7) y las etiquetas siguen a P6
INSERT INTO users (id, full_name, dept, clearance, acl_tags) VALUES
    ('00000000-0000-4000-a000-000000000001', 'Sofía Ariza',     'financiera',    'interno',      '{}'),
    ('00000000-0000-4000-a000-000000000002', 'Belén Quintero',  'financiera',    'interno',      '{}'),
    ('00000000-0000-4000-a000-000000000003', 'Ángela Gómez',    'academica',     'interno',      '{}'),
    ('00000000-0000-4000-a000-000000000004', 'Laura Martínez',  'financiera',    'confidencial', '{auditoria_interna}'),
    ('00000000-0000-4000-a000-000000000005', 'Carlos Rentería', 'academica',     'confidencial', '{comite_disciplinario}'),
    ('00000000-0000-4000-a000-000000000006', 'Diego Fajardo',   'institucional', 'confidencial', '{}');

INSERT INTO user_roles (user_id, role_id)
    SELECT u.id, r.id FROM (VALUES
        ('Sofía Ariza', 'empleado'),
        ('Belén Quintero', 'empleado'),
        ('Ángela Gómez', 'empleado'),
        ('Laura Martínez', 'supervisor'),
        ('Carlos Rentería', 'supervisor'),
        ('Diego Fajardo', 'administrador')
    ) AS m(full_name, role_name)
    JOIN users u ON u.full_name = m.full_name
    JOIN roles r ON r.name = m.role_name;
