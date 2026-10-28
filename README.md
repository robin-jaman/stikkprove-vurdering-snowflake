# Stikkprøvevurdering

Intern Streamlit-app der saksbehandlere vurderer stikkprøver av historiske avvik og varsler fra lønnsfilmottaket. Svarene brukes som treningsgrunnlag for en KI-modell.

Saksbehandlere laster **ikke** opp data. Datagrunnlag, saksbehandlere og tildeling styres under **Administrasjon**.

## Kom i gang

I PowerShell, fra prosjektmappen:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start appen med `start_app.bat`, eller:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Appen åpnes i nettleseren på `http://localhost:8503`.

Bruk `.venv`, ikke `python -m streamlit run app.py` uten den. Den globale Python-installasjonen på denne maskinen har en eldre Streamlit, og appen trenger 1.51. Starter du feil, sier appen fra i nettleseren i stedet for å krasje.

### Windows-koding

Streamlit leser `.py`-filer som UTF-8. På Windows blir de lett lagret som Windows-1252 eller UTF-16. Da krasjer appen med `utf-8 codec can't decode byte ...` (ofte bokstaven ø).

Kjør da `python ensure_utf8.py` og start appen på nytt. Ikke bruk bare **Rerun** i Streamlit-menyen som fiks.

## Slik brukes appen

To sider i menyen:

1. **Vurdering** – saksbehandler velger navnet sitt, bekrefter, og går gjennom køen.
2. **Administrasjon** – PIN-beskyttet (standard `2233`, kan overstyres med `STIKKPROVE_ADMIN_PIN`). Her lastes filer opp, saksbehandlere registreres og grunnlag tildeles. Lagrede svar lastes ned under **Fremdrift og svar**.

På vurderingssiden:

1. Velg navnet ditt og trykk **Fortsett som …**. Navnet låses til økten. Svar lagres på dette navnet.
2. Kopier *SPK person-ID*, slå den opp i ADA, og finn linjen.
3. Svar på spørsmålene og lagre. Ufullstendige skjemaer lagres ikke.
4. Hent neste stikkprøve i køen.

Én saksbehandler vurderer hver stikkprøve. Når noen har lagret, er saken ferdig i køen.

## Datagrunnlag

Filer lastes opp under **Administrasjon → Datagrunnlag** (CSV med `;` eller Excel). Flere grunnlag kan være aktive samtidig.

Hvis databasen er tom ved første oppstart, kan appen automatisk ta i bruk:

1. `STIKKPROVE_FILE` i `.env`, hvis filen finnes
2. `data/samples.csv` eller `data/samples.xlsx`

Vurderinger lagres lokalt i `data/assessments.sqlite`, nøklet på `(kilde_id, stikkprove_nr, saksbehandler)`.

## Snowflake

Denne kopien kan kjøre lokalt med SQLite, og i Snowflake når den er lastet opp som Streamlit in Snowflake. Excel- og CSV-opplasting og nedlasting av svar virker i begge.

Lokalt er lagringen `data/assessments.sqlite`. Opplastede filer lagres i tillegg som innhold i databasen, så samme kode kan lese dem i Snowflake.

Sett `STIKKPROVE_BACKEND=snowflake` for å bruke Snowflake-tabeller også lokalt. Inne i Streamlit in Snowflake oppdages tilkoblingen av seg selv, uten passord i `.env`. Appen trenger sju tabeller, og oppretter dem ved oppstart i skjemaet den kjører i, med prefiks `STIKKPROVE_` (kan endres med `STIKKPROVE_TABLE_PREFIX`):

```
STIKKPROVE_ASSESSMENTS    svarene
STIKKPROVE_REVIEWERS      saksbehandlerne
STIKKPROVE_CLAIMS         hvem som sitter med hvilken sak nå
STIKKPROVE_ASSIGNMENTS    fordelingen av saker
STIKKPROVE_SOURCES        datagrunnlagene
STIKKPROVE_SOURCE_FILES   innholdet i opplastede filer
STIKKPROVE_SETTINGS       innstillinger, administratorer og endringslogg
```

Mangler rollen `CREATE TABLE` i skjemaet, kan en med rettigheter kjøre `snowflake_tabeller.sql` i stedet. Kildetabellen med stikkprøvene er ikke en av disse; den ligger der den ligger, og appen bare leser fra den.

```
STIKKPROVE_BACKEND=auto
STIKKPROVE_QUERY
STIKKPROVE_ADMIN_USERS
STIKKPROVE_USER
STIKKPROVE_LIVE_SECONDS
SNOWFLAKE_ACCOUNT
SNOWFLAKE_USER
SNOWFLAKE_WAREHOUSE
SNOWFLAKE_DATABASE
SNOWFLAKE_SCHEMA
SNOWFLAKE_ROLE
SNOWFLAKE_PASSWORD
SNOWFLAKE_AUTHENTICATOR
```

Miljøvariabler finnes ikke i Snowflake. Det som må kunne endres der, settes derfor i appen i stedet: spørringen under **Datagrunnlag → Snowflake → Spørring**, og administratorene under **Saksbehandlere**. Variablene under gjelder lokal kjøring, og er bare startverdier i Snowflake.

`STIKKPROVE_ADMIN_USERS` er en kommaseparert liste med Snowflake-brukere som åpner Administrasjon uten PIN. De kan også registreres i appen under Saksbehandlere. PIN `2233` virker fortsatt.

På Vurdering kan hver saksbehandler få et Snowflake-brukernavn. Da velges navnet automatisk når vedkommende åpner appen i Snowflake. `CURRENT_USER()` brukes ikke, fordi appen kjører med eierens rettigheter. Navnet hentes fra den innloggede visningen.

Fremdriften oppdateres hvert 30. sekund i Snowflake, og hvert 6. sekund lokalt. `STIKKPROVE_LIVE_SECONDS` overstyrer intervallet.

Appen åpnes på port **8503** lokalt, så den kan kjøre ved siden av originalen i `stikkprove-vurdering`.

### Sett opp appen i Snowsight

**Velg kjøremiljø og Streamlit-versjon.** Appen er laget for **warehouse runtime**, der pakkene kommer fra Snowflakes Anaconda-kanal og appen ikke trenger tilgang til internett. Container runtime henter pakker fra PyPI og krever enten en External Access Integration eller et artifact repository. Sett `runtime_name: SYSTEM$WAREHOUSE_RUNTIME` i `snowflake.yml`.

Appen krever **Streamlit 1.51 eller nyere**, som warehouse-kjøring tilbyr. Velger du en eldre versjon, starter ikke appen; den viser en melding om hvilken versjon som mangler, i stedet for å krasje.

Av samme grunn bruker appen ingen Components v2. De er ikke tillatt på warehouse runtime. SPK person-ID vises derfor med `st.code`, som har en innebygd kopiknapp som virker i begge miljøer.

Oppsettet hos SPK bruker warehouset `COMPUTE_WH` og to schemaer i databasen `TEST`. Stikkprøvene leses fra `DATAFORVALTNING_RAPPORTERING.BT_STIKKPROEVER_PAA_VARSLER_FOR_KI_LOENNSFILMOTTAK` og blir liggende der. Appens sju hjelpetabeller havner i `DATAFORVALTNING_STAGING`. Kildetabellen står i `src/snowflake_client.py`, og schemaet for hjelpetabellene i `src/db.py`, begge som standardverdier du kan overstyre.

**1. Last opp filene.** Femten filer skal med, så bruk Snowflake CLI framfor å lime dem inn én og én:

```powershell
.\.venv\Scripts\snow.exe streamlit deploy --replace --connection SPK-DATAINNSIKT
```

Den lager stagen, laster opp alt med mappestrukturen intakt, og oppretter appen. Kjører du kommandoen igjen senere, oppdateres bare det som er endret. Vil du heller gjøre det manuelt i Snowsight, er det **Projects → Streamlit → + Streamlit App**, og disse filene:

```
app.py                 (hovedfil)
environment.yml        (pakker)
src/*.py               (alle 13)
.streamlit/config.toml (tema)
```

`data/`, `.venv/`, `tests/`, `*.bat`, `*.sql` og `fix_encoding.ps1` skal ikke med. Linjen `port = 8503` i `config.toml` ignoreres i Snowflake og gjør ingen skade.

**2. Legg til pakker.** `pandas` og `openpyxl`, enten med **Packages** i editoren eller med `environment.yml`. Bare pakker fra Snowflakes Anaconda-kanal kan brukes på warehouse-kjøring. `python-dotenv` og `tzdata` er valgfrie; uten `tzdata` vises klokkeslett som UTC+1 hele året.

**3. Start appen.** Den oppdager Snowflake selv og lager tabellene `STIKKPROVE_*`. Schemaet må finnes fra før; appen oppretter aldri schemaer. Kontroller med `SHOW TABLES LIKE 'STIKKPROVE_%' IN SCHEMA TEST.DATAFORVALTNING_STAGING`. Mangler rollen `CREATE TABLE` der, sier appen fra hvilke tabeller den ikke fikk laget, og da kan `snowflake_tabeller.sql` kjøres i et worksheet i stedet.

**4. Koble til kildetabellen.** Åpne **Administrasjon** med PIN `2233`, legg til Snowflake som grunnlag, og åpne **Kildetabell**. Tabellnavnet er fylt inn på forhånd; trykk **Sjekk tabell**. Appen leser kolonnene og sier hvilke den kjenner igjen. Den finner dem selv om de heter `STIKKPROVE_NR` eller `LOENN`, så du trenger ikke endre tabellen eller skrive om spørringen. Mangler kolonnen for stikkprøvenummer, sier appen fra med en gang.

Skal svarene skrives inn i raden stikkprøven kom fra, slår du på **Skriv svarene tilbake til raden i denne tabellen**. Appen finner svarkolonnene på samme måte, og melder fra om hvilke spørsmål som mangler kolonne. Finnes `VURDERT_AV` og `VURDERT_DT`, fylles de med navn og tidspunkt. Rollen må ha `UPDATE` på tabellen.

**5. Resten av innholdet.** Registrer saksbehandlere med Snowflake-brukernavn, og legg deg selv til som administrator. Excel og CSV kan fortsatt lastes opp ved siden av, som egne grunnlag.

**6. Gi teamet tilgang.**

```sql
GRANT USAGE ON STREAMLIT TEST.DATAFORVALTNING_RAPPORTERING.STIKKPROVEVURDERING
  TO ROLE <TEAMROLLE>;
```

Appen kjører med eierens rettigheter, så kollegene trenger ikke tilgang til tabellene bak. Test med én kollega først.

**Kostnad.** Fremdriften oppdateres hvert 30. sekund, så warehouset holdes i gang så lenge noen har appen åpen. Sett `AUTO_SUSPEND` lavt, og bruk `STIKKPROVE_LIVE_SECONDS` hvis intervallet skal ned.

Originalen i `C:\Users\roj\stikkprove-vurdering` er urørt.

## Hva appen samler inn

- Hvordan varselet bør håndteres
- Begrunnelse, inkludert vilkår, rutine eller regelverksendring
- Vanlig praksis, særtilfelle eller unntak
- Særtrekk ved periode, arbeidsgiver, stilling, tillegg eller lønn
- Om den historiske behandlingen vurderes som korrekt
- Valgfri kommentar

## Personvern

Filene kan inneholde lønn, arbeidsgiver og personnøkler. Ikke commit `data/assessments.sqlite`, opplastede filer under `data/sources/` eller `.env`. Kjør appen lokalt eller i et internt miljø.
