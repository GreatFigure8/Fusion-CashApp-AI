-- Creates the application schema in the environment's Autonomous Database.
-- Run by the release (s44) as ADMIN with SQLcl or SQL*Plus:
--   sql ADMIN/<password from Vault>@<connect string> @infra/sql/schemas.sql CASHAPP_DEV <schema password from Vault>
--   &1 = schema name (CASHAPP_DEV or CASHAPP_PROD)
--   &2 = schema password; supplied by the release from Vault, never stored in this file.
-- Idempotent: an existing schema is left untouched. Alembic owns every table, so there is no table DDL here.

WHENEVER SQLERROR EXIT FAILURE
SET VERIFY OFF
SET SERVEROUTPUT ON

DECLARE
  l_exists NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_exists FROM dba_users WHERE username = UPPER('&1');
  IF l_exists = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER &1 IDENTIFIED BY "&2" QUOTA UNLIMITED ON DATA';
    DBMS_OUTPUT.PUT_LINE('created schema &1');
  ELSE
    DBMS_OUTPUT.PUT_LINE('schema &1 already exists');
  END IF;
END;
/

GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW, CREATE PROCEDURE TO &1;

EXIT
