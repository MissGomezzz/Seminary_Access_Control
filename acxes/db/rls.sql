-- Row Level Security con FORCE (etapa 1). La regla es la de documents/POLITICAS_ACCESO.md
-- y debe coincidir con el predicado del PDP. Variables de sesión en docs/VARIABLES_SESION.md.
-- Las listas (app.allowed_depts y app.acl_tags) son texto separado por comas.
-- Si falta cualquier variable usada, la condición correspondiente es NULL y no devuelve filas.

CREATE FUNCTION app_row_visible(
    row_dept TEXT,
    row_sensitivity sensitivity_level,
    row_owner UUID,
    row_acl_tags TEXT[]
) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
    SELECT
        -- 1. Dependencia permitida y nivel dentro del tope. Nunca restringido por esta vía
        (
            row_dept = ANY (string_to_array(NULLIF(current_setting('app.allowed_depts', true), ''), ','))
            AND row_sensitivity < 'restringido'
            AND row_sensitivity <= NULLIF(current_setting('app.clearance', true), '')::sensitivity_level
        )
        -- 2. Propiedad hasta confidencial
        OR (
            row_owner = NULLIF(current_setting('app.user_id', true), '')::uuid
            AND row_sensitivity <= 'confidencial'
        )
        -- 3. Restringido solo por intersección de etiquetas
        OR (
            row_sensitivity = 'restringido'
            AND row_acl_tags && string_to_array(NULLIF(current_setting('app.acl_tags', true), ''), ',')
        )
$$;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;

CREATE POLICY documents_access_policy ON documents FOR SELECT
    USING (app_row_visible(dept, sensitivity, owner_id, acl_tags));

CREATE POLICY chunks_access_policy ON chunks FOR SELECT
    USING (app_row_visible(dept, sensitivity, owner_id, acl_tags));
