дава# CLAUDE.md — GenAI Dashboard Project Context

## Project Overview

GenAI Dashboard is a multi-tenant analytical platform built on Streamlit that integrates:
- Data connectors (Google Sheets, YTsaurus, ClickHouse/SuperSet, local CSV/Excel)
- ETL pipelines (user-written `handle(df)` Python scripts)
- AI-powered chart generation (Text-to-Chart via OpenAI/Gemini/DeepSeek)
- S3-backed file storage (MinIO)
- Background task processing (Celery + Redis)
- PostgreSQL for all persistent state (users, workspaces, charts, sources, LLM keys)

## Tech Stack

| Layer | Technology |
| --- | --- |
| Web UI | Streamlit 1.30+ |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 15 |
| Task Queue | Celery + Redis 7 |
| File Storage | MinIO (S3-compatible, boto3) |
| AI/LLM | OpenAI SDK, google-generativeai |
| Auth | streamlit-authenticator (password) + Google OAuth 2.0 |
| Encryption | cryptography.fernet (for LLM API keys in DB) |
| Container | Docker + docker-compose (5 services) |

## How to Run

```bash
docker compose up --build    # starts all 5 services
docker compose exec app python debug_utils/create_user.py   # add user (interactive)
```

App at `http://localhost:8501`. No local run — Docker only.

## Docker Services

| Service | Container Name | Role |
| --- | --- | --- |
| app | genai_dashboard_web | Streamlit UI on :8501 |
| worker | genai_celery_worker | Celery background tasks |
| db | genai_postgres | PostgreSQL on :5432 |
| redis | genai_redis | Celery broker on :6379 |
| minio | genai_minio | S3 API :9000, Console :9001 |

## Project Structure

```
├── app.py                  # Entry point — all Streamlit UI & routing
├── modules/                # Core platform
│   ├── models.py           #   8 ORM models + 3 association tables
│   ├── db_manager.py       #   SQLAlchemy engine & session
│   ├── auth.py             #   Google OAuth (tokens stored in DB)
│   ├── llm_manager.py      #   AI layer (encrypt keys, get/save providers, ask_llm)
│   ├── data_loader.py      #   ETL pipeline: Extract → Transform → Load
│   ├── connector_loader.py #   Dynamic import of connector plugins
│   ├── connectors/         #   Data source plugins (BaseConnector interface)
│   │   ├── base.py         #     Abstract class: get_meta, get_fields, validate, load_data
│   │   ├── gsheets.py      #     Google Sheets (gspread)
│   │   ├── ytsaurus.py     #     YTsaurus (YQL queries)
│   │   └── superset.py     #     ClickHouse / SuperSet API
│   ├── tasks.py            #   Celery tasks (8 tasks — see below)
│   ├── wizards.py          #   Streamlit dialogs (charts, sources, pages, LLM, workspaces)
│   ├── io_manager.py       #   Import/export .geb bundles (ZIP with manifest.json)
│   ├── s3_storage.py       #   MinIO S3 client (singleton: s3_client)
│   ├── settings.py         #   Paths, constants, env vars
│   └── utils.py            #   Encryption, ChartExporter (HTML), load/save JSON
├── handlers/               # User ETL scripts (handle.py format)
├── charts/                 # AI-generated chart modules (.py with render() function)
├── data_sources/           # CSV/Excel/.geb data files
├── config/                 # Runtime config (auto-created)
├── debug_utils/            # Admin scripts (create_user, seed_users, migrations)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh           # Container entrypoint
└── .flake8                 # max-line-length=120, excludes generated dirs
```

## Database Models (models.py)

8 ORM tables:

- **User** — username, password_hash, name, email, google_token (JSON), default_theme_id
- **Workspace** — multi-tenancy: owner_id, users (M2M via workspace_user_link)
- **Page** — belongs to workspace, has M2M with Chart
- **Chart** — technical_name (.py filename), display_name, M2M with DataSource
- **DataSource** — connector_id, filename, config_json, handler_id (FK to ETLHandler)
- **ETLHandler** — name, technical_name (.py filename)
- **LLMProvider** — per-user: api_type, api_key (encrypted), base_url, models (comma-separated)
- **ChartTheme** — per-user: name, colors (comma-separated), dark_mode

## Celery Tasks (tasks.py)

All heavy operations run in the background via Celery:

| Task | Purpose |
| --- | --- |
| `update_source_task` | ETL pipeline for a single source |
| `generate_chart_task` | AI generates new chart code |
| `edit_chart_task` | AI edits existing chart code |
| `analyze_chart_task` | AI analysis of chart data |
| `chat_llm_task` | Free-form AI chat in sidebar |
| `export_bundle_task` | Build .geb archive (chart + data) |
| `import_bundle_task` | Extract .geb archive from base64 |
| `upload_local_file_task` | Upload file to S3 + register in DB |

## Key Architecture Patterns

### S3 Sync Pattern
All files (charts, handlers, data) are stored in S3 first, then optionally cached locally.
- `s3_client.put_text()` — store string directly to S3
- `s3_client.upload_file()` — upload local file to S3
- `s3_client.download_file()` — pull from S3 to local cache
- S3 buckets: `charts`, `handlers`, `data-sources`

### Workspace Isolation
Every entity (Page, Chart, DataSource, ETLHandler) is scoped to a Workspace via `workspace_id`.
Queries always filter by `st.session_state.active_ws_id`.

### AI Chart Generation Flow
1. User fills form in `wizard_create_chart` (goal, format, data sources, theme)
2. Prompt is built with column metadata and palette info
3. Task sent to Celery (`generate_chart_task.delay()`)
4. Celery calls `ask_llm()` → generates Python code with `def render(files, chart_key)`
5. Code saved to S3 + DB, tracked via `st.session_state.active_tasks`
6. `visual_chart_tracker` polls every 2s, picks up result, triggers rerun

### LLM Key Encryption
API keys are encrypted with Fernet before writing to DB (`encrypt_token`).
Decrypted on read (`decrypt_token`). Backward-compatible: if decryption fails, returns raw value.

### ETL Pipeline (data_loader.py)
```
Extract: connector.load_data(config) → DataFrame
Transform: handler.handle(df) → DataFrame (dynamic import from handlers/)
Load: df.to_csv/excel → local + S3
```

## Where Things Live

| What | Location |
| --- | --- |
| Google OAuth secret | `config/client_secret.json` |
| User passwords | `users.yaml` → PostgreSQL (streamlit-authenticator) |
| LLM API keys | PostgreSQL `llm_providers` table (encrypted) |
| Chart code | `charts/*.py` + S3 `charts/` bucket |
| ETL handlers | `handlers/*.py` + S3 `handlers/` bucket |
| Data files | `data_sources/*` + S3 `data-sources/` bucket |
| ENCRYPTION_KEY | env var or hardcoded default in `settings.py` |
| DB URL | `DATABASE_URL` env var (default: postgresql://genai_admin:superpassword@localhost:5432/genai_platform) |
| Redis URL | `REDIS_URL` env var (default: redis://redis:6379/0) |
| MinIO creds | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` env vars |

## Flake8

```bash
python -m flake8 app.py modules/
```

Config in `.flake8`: max-line-length=120, excludes `.venv`, `.git`, `__pycache__`, `.ipynb_checkpoints`, `charts/`, `handlers/`, `data_sources/`, `debug_utils/`.

## How to Add a New Data Connector

1. Create `modules/connectors/<name>.py`
2. Implement class extending `BaseConnector` (base.py):
   - `get_meta()` → dict with id, name, icon
   - `get_fields()` → list of field dicts (key, label, type)
   - `validate(config)` → (bool, message)
   - `load_data(config)` → pd.DataFrame
3. It is auto-discovered by `connector_loader.load_connectors()`

## How to Add a User

```bash
docker compose exec app python debug_utils/create_user.py
# Interactive: username, name, email, password
```

Or directly via Python:
```python
from modules.db_manager import SessionLocal
from modules.models import User, Workspace
import streamlit_authenticator as stauth

db = SessionLocal()
creds = {'usernames': {'login': {'password': 'pass'}}}
stauth.Hasher.hash_passwords(creds)
user = User(username='login', name='Name', email='e@mail', password_hash=creds['usernames']['login']['password'])
db.add(user)
db.commit()
```

## Important Notes

- **Never touch** placeholder strings like `api_key=safe_api_key`, `m.shakurov99@gmail.com`, `VK` — they are redacted secrets and company names.
- Star import `from modules.settings import *` in app.py is intentional — it provides FOLDER constants and config URLs used throughout the UI. Flake8 ignores it via `.flake8` per-file-ignores.
- `sync_single_source`, `BundleManager`, `ask_llm`, `Chart` are imported in app.py but may appear unused — they are used indirectly (via string references, Celery tasks, or queries). Marked with `# noqa: F401`.
- Streamlit sessions are fragile: `st.session_state` must always be guarded with `.get()` or `in` checks.
- Charts directory contains auto-generated code from AI — do not manually edit unless fixing a specific chart.
- `.geb` files are ZIP archives with `manifest.json` + `source/` + `data/` directories.
