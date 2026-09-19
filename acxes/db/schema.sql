-- Esquema mínimo del corpus institucional.
-- Se mantiene deliberadamente simple para la línea base Unsecure (B1, Hito 1).
-- Las columnas dept/sensitivity ya están presentes para que el mismo corpus
-- pueda reutilizarse sin cambios cuando se implemente la arquitectura Secure
-- (ver Documents/MATRIZ_ACCESO.md). B1 las ignora por completo: esa es
-- precisamente la falla que este hito busca evidenciar.

DROP TABLE IF EXISTS teams CASCADE;
DROP TABLE IF EXISTS employees CASCADE;

CREATE TABLE teams (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    dept        TEXT NOT NULL DEFAULT 'institucional',
    manager_id  INTEGER  -- se referencia a employees.id, sin FK circular estricta
);

CREATE TABLE employees (
    id          SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('empleado', 'supervisor', 'administrador')),
    team_id     INTEGER REFERENCES teams(id),
    salary      NUMERIC(12, 2) NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'confidencial'
);

ALTER TABLE teams
    ADD CONSTRAINT teams_manager_fk
    FOREIGN KEY (manager_id) REFERENCES employees(id);
