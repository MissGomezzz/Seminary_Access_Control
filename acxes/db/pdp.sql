-- Atributos del sujeto para el PDP (etapa 3). La base es la fuente de verdad para autorizar:
-- el PDP consulta aquí el rol, la dependencia y las etiquetas en cada evaluación, de modo
-- que una revocación surte efecto sin esperar a que expire el token (ARQUITECTURA.md 5.5).
-- El rol acxes_pdp solo puede ejecutar esta función. No lee ninguna tabla directamente.

CREATE FUNCTION pdp_subject(p_user_id UUID)
RETURNS TABLE (roles TEXT[], dept TEXT, acl_tags TEXT[])
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT
        COALESCE(
            (SELECT array_agg(r.name ORDER BY r.name)
               FROM user_roles ur JOIN roles r ON r.id = ur.role_id
              WHERE ur.user_id = u.id),
            '{}'
        ),
        u.dept,
        u.acl_tags
    FROM users u
    WHERE u.id = p_user_id
$$;

REVOKE EXECUTE ON FUNCTION pdp_subject(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pdp_subject(UUID) TO acxes_pdp;
