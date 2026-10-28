-- Tabeller for Stikkprovevurdering i TEST.DATAFORVALTNING_STAGING.
--
-- Stikkprovene leses fra TEST.DATAFORVALTNING_RAPPORTERING og blir liggende
-- der. Det er bare appens egne arbeidstabeller som havner i STAGING.
--
-- Du trenger normalt ikke denne filen. Appen oppretter de sju tabellene
-- selv forste gang noen apner den. Bruk den hvis du vil se hva som lages
-- for appen kjorer, eller hvis appen melder at den ikke fikk opprettet dem.
--
-- Alt kan kjores om igjen uten skade: ingenting overskrives.

-- Schemaet forutsettes aa finnes fra for. Verken appen eller denne filen
-- oppretter schemaer.

USE DATABASE TEST;
USE SCHEMA DATAFORVALTNING_STAGING;


-- ---------------------------------------------------------------
-- 1. Appens egne tabeller, sju i alt
--
-- Dette er arbeidsbordet til appen: hvem som sitter med hvilken sak
-- akkurat naa, hvem som har faatt tildelt hva, hvem som er
-- saksbehandler, og hvilke innstillinger som gjelder.
-- Ingen av dem inneholder kildedata. De er smaa.
-- ---------------------------------------------------------------

-- Svarene, slik appen jobber med dem underveis.
-- Trengs ogsaa naar svaret til slutt skrives tilbake til kildetabellen,
-- fordi appen lagrer kladd og viser hvem som har gjort hva.
CREATE TABLE IF NOT EXISTS STIKKPROVE_ASSESSMENTS (
  KILDE_ID VARCHAR NOT NULL DEFAULT '',
  STIKKPROVE_NR VARCHAR NOT NULL,
  SAKSBEHANDLER VARCHAR NOT NULL,
  VARSELKODE VARCHAR,
  HANDLING VARCHAR,
  HANDLING_ANNET VARCHAR,
  BEGRUNNELSE VARCHAR,
  VANLIGHET VARCHAR,
  UNNTAK_FORKLARING VARCHAR,
  PERIODE_SPESIELT VARCHAR,
  HISTORISK_KORREKT VARCHAR,
  KOMMENTAR VARCHAR,
  UPDATED_AT VARCHAR NOT NULL,
  KILDE VARCHAR,
  PRIMARY KEY (KILDE_ID, STIKKPROVE_NR, SAKSBEHANDLER)
);

-- Saksbehandlerne, og hvilken Snowflake-bruker de logger inn med.
CREATE TABLE IF NOT EXISTS STIKKPROVE_REVIEWERS (
  NAVN VARCHAR NOT NULL,
  CREATED_AT VARCHAR NOT NULL,
  SNOWFLAKE_BRUKER VARCHAR
);

-- Hvem som sitter med hvilken stikkprove akkurat naa.
-- Dette er det som hindrer at to personer faar samme sak.
CREATE TABLE IF NOT EXISTS STIKKPROVE_CLAIMS (
  KILDE_ID VARCHAR NOT NULL DEFAULT '',
  STIKKPROVE_NR VARCHAR NOT NULL,
  SAKSBEHANDLER VARCHAR NOT NULL,
  CLAIMED_AT VARCHAR NOT NULL,
  OPENED_AT VARCHAR
);

-- Fordeling av saker fra administrator til saksbehandler.
CREATE TABLE IF NOT EXISTS STIKKPROVE_ASSIGNMENTS (
  KILDE_ID VARCHAR NOT NULL DEFAULT '',
  STIKKPROVE_NR VARCHAR NOT NULL,
  SAKSBEHANDLER VARCHAR NOT NULL,
  ASSIGNED_AT VARCHAR NOT NULL
);

-- Datakildene appen henter stikkprover fra.
CREATE TABLE IF NOT EXISTS STIKKPROVE_SOURCES (
  SOURCE_ID VARCHAR NOT NULL,
  NAME VARCHAR NOT NULL,
  KIND VARCHAR NOT NULL,
  PATH VARCHAR,
  ORIGINAL_NAME VARCHAR,
  ACTIVE NUMBER NOT NULL DEFAULT 1,
  CREATED_AT VARCHAR NOT NULL,
  URL VARCHAR,
  FILE_UPDATED_AT VARCHAR
);

-- Innholdet i opplastede Excel- og CSV-filer.
-- En app i Snowflake har ingen harddisk, saa filen maa ligge i en tabell.
CREATE TABLE IF NOT EXISTS STIKKPROVE_SOURCE_FILES (
  SOURCE_ID VARCHAR NOT NULL,
  FILENAME VARCHAR,
  CONTENT_B64 VARCHAR NOT NULL,
  UPDATED_AT VARCHAR NOT NULL
);

-- Innstillinger som settes i appen, blant annet kildetabellen.
-- Rommer ogsaa hvem som slipper inn paa Administrasjon uten PIN,
-- og loggen over hva administrator har gjort. De ligger som egne navn.
CREATE TABLE IF NOT EXISTS STIKKPROVE_SETTINGS (
  NAVN VARCHAR NOT NULL,
  VERDI VARCHAR,
  UPDATED_AT VARCHAR NOT NULL
);


-- ---------------------------------------------------------------
-- 2. Rettigheter for kollegene
--
-- Appen kjorer med eierens rettigheter. Siden du selv oppretter appen og
-- tabellene, har du alt du trenger. Kollegene trenger bare tilgang til
-- selve appen, ikke til tabellene bak.
--
-- Kjores etter at appen er opprettet. <APP_NAVN> er STIKKPROVEVURDERING
-- hvis du bruker snowflake.yml som den star.
-- ---------------------------------------------------------------

-- GRANT USAGE ON STREAMLIT TEST.DATAFORVALTNING_RAPPORTERING.<APP_NAVN>
--   TO ROLE <TEAMROLLE>;

-- Mangler appen tilgang til noe, er dette de som trengs:
-- GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE <APPROLLE>;
-- INSERT trengs fordi appen legger inn en ny rad hvis en stikkprove fra et
-- opplastet regneark ikke finnes i tabellen fra for.
-- GRANT SELECT, UPDATE, INSERT ON TABLE
--   TEST.DATAFORVALTNING_RAPPORTERING.BT_STIKKPROEVER_PAA_VARSLER_FOR_KI_LOENNSFILMOTTAK
--   TO ROLE <APPROLLE>;

-- Appen ligger i ett schema og lager tabellene sine i et annet, saa den
-- trenger tilgang til begge.
-- GRANT USAGE ON SCHEMA TEST.DATAFORVALTNING_STAGING TO ROLE <APPROLLE>;
-- GRANT CREATE TABLE ON SCHEMA TEST.DATAFORVALTNING_STAGING TO ROLE <APPROLLE>;


-- ---------------------------------------------------------------
-- 2b. Valgfritt: hvem som svarte, og naar
--
-- Appen fyller disse hvis de finnes, og klarer seg uten dem.
-- Uten VURDERT_AV kan ikke administrasjonssiden vise fremdrift per person
-- naar svarene bare lagres i kildetabellen.
-- ---------------------------------------------------------------

-- ALTER TABLE TEST.DATAFORVALTNING_RAPPORTERING.BT_STIKKPROEVER_PAA_VARSLER_FOR_KI_LOENNSFILMOTTAK
--   ADD COLUMN IF NOT EXISTS VURDERT_AV VARCHAR,
--       COLUMN IF NOT EXISTS VURDERT_DT VARCHAR;


-- ---------------------------------------------------------------
-- 3. Kontroll
-- ---------------------------------------------------------------

SHOW TABLES LIKE 'STIKKPROVE_%' IN SCHEMA TEST.DATAFORVALTNING_STAGING;
