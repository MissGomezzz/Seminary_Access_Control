-- Datos sintéticos para probar T01-T05 de la propuesta (Hito 1).
-- Dos equipos, cada uno con un supervisor propio, y un administrador global.
-- Ejecutar después de schema.sql. Es seguro volver a correrlo: limpia antes de insertar.

TRUNCATE employees, teams RESTART IDENTITY CASCADE;

-- Equipos (el manager_id se completa después de crear a los empleados)
INSERT INTO teams (name, dept) VALUES
    ('Nómina', 'financiera'),
    ('Investigación', 'academica');

-- Empleados
INSERT INTO employees (full_name, role, team_id, salary) VALUES
    ('Sofía Ariza',    'empleado',      1, 4200000),
    ('Belén Quintero', 'empleado',      1, 4350000),
    ('Ángela Gómez',   'empleado',      2, 4100000),
    ('Laura Martínez', 'supervisor',    1, 6800000),
    ('Carlos Rentería','supervisor',    2, 7000000),
    ('Diego Fajardo',  'administrador', NULL, 9500000);

-- Asigna cada equipo a su supervisor real (usado por T03: "un equipo que no dirige")
UPDATE teams SET manager_id = (SELECT id FROM employees WHERE full_name = 'Laura Martínez')
    WHERE name = 'Nómina';
UPDATE teams SET manager_id = (SELECT id FROM employees WHERE full_name = 'Carlos Rentería')
    WHERE name = 'Investigación';
