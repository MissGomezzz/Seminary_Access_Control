# Matriz de acceso

Estado: aprobada por el equipo. El detalle de las reglas está en `POLITICAS_ACCESO.md`.

## Niveles de sensibilidad

Orden de menor a mayor: `publico` < `interno` < `confidencial` < `restringido`. Se implementa como tipo enumerado en PostgreSQL y nunca como texto.

## Dependencias

- `institucional`: documentos generales visibles desde cualquier dependencia, sujetos al nivel.
- `academica` y `financiera`: dependencias sintéticas.

## Roles

| Rol | Nivel máximo | Alcance |
|---|---|---|
| empleado | interno | Dependencia `institucional`, su dependencia y sus registros propios (`owner_id`) hasta confidencial |
| supervisor | confidencial | Dependencia `institucional`, su dependencia y sus registros propios |
| administrador | confidencial | Las tres dependencias, con lista explícita, y sus registros propios |

Todos los roles ven los documentos de la dependencia `institucional` hasta el nivel que les corresponde.

## Nivel restringido

Ningún rol accede a `restringido` por su nivel. El acceso se concede solo mediante etiquetas ACL explícitas (`acl_tags`) asignadas al usuario. El administrador no es la excepción, de modo que se conserva la separación de funciones.

Etiquetas iniciales:

- `comite_disciplinario`, dependencia académica.
- `auditoria_interna`, dependencia financiera.

Al menos un supervisor tiene cada etiqueta, ningún administrador tiene etiquetas y un empleado no tiene ninguna.
