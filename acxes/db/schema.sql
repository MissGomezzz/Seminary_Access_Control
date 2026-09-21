-- Esquema compartido del corpus institucional (etapa 1).
-- Lo usan B1, B2 y S. Ninguna línea base tiene esquema propio, de modo que la
-- comparación cambie solo la autorización. Aplicar con `python -m acxes.db.apply`.
-- Es seguro volver a correrlo: elimina y recrea las tablas.

DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS role_permissions CASCADE;
DROP TABLE IF EXISTS permissions CASCADE;
DROP TABLE IF EXISTS resources CASCADE;
DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS roles CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS policy_version CASCADE;
DROP FUNCTION IF EXISTS chunks_inherit_from_document() CASCADE;
DROP FUNCTION IF EXISTS documents_propagate_to_chunks() CASCADE;
-- Al eliminar el tipo se elimina también app_row_visible, que depende de él (rls.sql)
DROP TYPE IF EXISTS sensitivity_level CASCADE;

-- Sensibilidad como enumerado con orden explícito, nunca TEXT
CREATE TYPE sensitivity_level AS ENUM ('publico', 'interno', 'confidencial', 'restringido');

-- Espejo mínimo de Keycloak para las pruebas. La fuente de verdad de la sesión es el JWT
CREATE TABLE users (
    id          UUID PRIMARY KEY,
    full_name   TEXT NOT NULL UNIQUE,
    dept        TEXT NOT NULL CHECK (dept IN ('institucional', 'academica', 'financiera')),
    clearance   sensitivity_level NOT NULL,
    acl_tags    TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE roles (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE CHECK (name IN ('empleado', 'supervisor', 'administrador'))
);

CREATE TABLE user_roles (
    user_id     UUID NOT NULL REFERENCES users(id),
    role_id     INT NOT NULL REFERENCES roles(id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,  -- P10: el PDP no lo evalúa en la versión base
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE resources (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE permissions (
    id           SERIAL PRIMARY KEY,
    resource_id  INT NOT NULL REFERENCES resources(id),
    action       TEXT NOT NULL CHECK (action IN ('read', 'search'))
);

CREATE TABLE role_permissions (
    role_id        INT NOT NULL REFERENCES roles(id),
    permission_id  INT NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);

-- P15: formato AAAA-MM-DD.n
CREATE TABLE policy_version (
    version       TEXT PRIMARY KEY CHECK (version ~ '^\d{4}-\d{2}-\d{2}\.\d+$'),
    activated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    description   TEXT
);

CREATE TABLE documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    dept         TEXT NOT NULL CHECK (dept IN ('institucional', 'academica', 'financiera')),
    sensitivity  sensitivity_level NOT NULL,
    owner_id     UUID REFERENCES users(id),
    acl_tags     TEXT[] NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- P5: las etiquetas solo existen en el nivel restringido
    CONSTRAINT documents_acl_tags_only_restricted
        CHECK (sensitivity = 'restringido' OR acl_tags = '{}')
);

-- Cada fragmento hereda la clasificación del documento. Sin vector en la versión base
CREATE TABLE chunks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id       UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL DEFAULT 0,
    dept         TEXT NOT NULL,
    sensitivity  sensitivity_level NOT NULL,
    owner_id     UUID,
    acl_tags     TEXT[] NOT NULL DEFAULT '{}',
    content      TEXT NOT NULL,
    content_tsv  TSVECTOR GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chunks_acl_tags_only_restricted
        CHECK (sensitivity = 'restringido' OR acl_tags = '{}')
);

CREATE INDEX chunks_tsv_idx ON chunks USING GIN (content_tsv);
CREATE INDEX chunks_doc_idx ON chunks (doc_id);

-- Registro de solo inserción para el rol de aplicación (ver grants.sql)
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         UUID,
    query           TEXT,
    tool_calls      JSONB,
    decision        JSONB,
    policy_version  TEXT,
    chunk_ids       UUID[],
    response        TEXT,
    detail          JSONB
);

-- Al insertar un fragmento se copian los metadatos del documento, no se recalculan.
-- La ingesta corre con el rol propietario, que no está sujeto a RLS en el entorno local.
CREATE FUNCTION chunks_inherit_from_document() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    SELECT d.dept, d.sensitivity, d.owner_id, d.acl_tags
      INTO NEW.dept, NEW.sensitivity, NEW.owner_id, NEW.acl_tags
      FROM documents d
     WHERE d.id = NEW.doc_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'documento inexistente para el fragmento';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER chunks_inherit_before_insert
    BEFORE INSERT ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_inherit_from_document();

-- Un cambio de clasificación del documento llega a sus fragmentos en la misma transacción
CREATE FUNCTION documents_propagate_to_chunks() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE chunks
       SET dept = NEW.dept,
           sensitivity = NEW.sensitivity,
           owner_id = NEW.owner_id,
           acl_tags = NEW.acl_tags
     WHERE doc_id = NEW.id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER documents_propagate_after_update
    AFTER UPDATE OF dept, sensitivity, owner_id, acl_tags ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_propagate_to_chunks();
