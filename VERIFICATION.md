# Verification — Kometa-Features in pyrate

This is the end-to-end checklist for the Kometa-style smart collections,
overlays and mass-operations features (Phases A–J of `/root/.claude/plans/gentle-noodling-muffin.md`).

## What was built

| Area | Modules / Files |
|------|----------------|
| Models + migrations | `backend/src/pyrate/models/{smart_collection,overlay,mass_operation}.py` + 4 Alembic revisions ending at `seeddef001` |
| List-source adapters | `backend/src/pyrate/metadata/list_sources/` — TMDb, Trakt, IMDb, Letterboxd, MDBList, MAL (Jikan), AniList |
| Smart-collection engine | `backend/src/pyrate/smart_collections/` — Builders, Filter-DSL (in-mem + SQL), Resolver, Service, croniter |
| Overlay engine | `backend/src/pyrate/overlays/` + `backend/src/pyrate/services/image_cache.py` |
| Mass-operation engine | `backend/src/pyrate/services/mass_operation.py` |
| Workers | `backend/src/pyrate/workers/{smart_collection,overlay,mass_operation}_worker.py` (registered in `worker.py`) |
| Admin API | `backend/src/pyrate/api/v1/{smart_collections,overlays,mass_operations}.py` mounted in `api/router.py` |
| Pydantic schemas | `backend/src/pyrate/schemas/{smart_collection,overlay,mass_operation}.py` |
| Kometa defaults | `backend/src/pyrate/smart_collections/defaults.py` (~51 smart rules + 6 overlays) + seed migration |
| Frontend | `frontend/src/pages/admin/{SmartCollectionsPage,OverlayTemplatesPage,MassOperationsPage}.vue` + 3 services + router + i18n (DE/EN) + AdminLayout menu items |
| Settings | `models/setting.py`: `smart_collections.api_keys`, `smart_collections.enabled`, `smart_collections.cache_ttl_seconds`, `overlays.enabled`, `overlays.cache_dir` |

## Backend tests written

```
backend/tests/
├── test_list_sources.py                  # 7 adapters: registry, TMDb pagination, IMDb __NEXT_DATA__ parsing, Letterboxd regex
├── test_smart_collections.py             # Registry, cron, filter DSL (rating/year/genre/availability bands)
├── test_smart_collections_integration.py # End-to-end against in-memory DB: populate list, filter, unresolved
├── test_smart_collection_worker.py       # Tick lock, dispatch, run records events
├── test_overlays.py                      # Context, DSL, renderer E2E with synthetic JPEG
├── test_mass_operations.py               # Action validation, SQL translation, in-memory action application
├── test_mass_operations_integration.py   # DB-bound: dry-run, set_description, set_genre, clear
└── test_kometa_defaults.py               # Per-default schema validation, GUID stability, volume guard
```

## Running the full backend suite

```bash
cd /root/pyrate.media/backend
uv sync                                   # picks up the new croniter dep
uv run alembic upgrade head               # → head is seeddef001
uv run alembic downgrade -1               # smoke-test downgrade once
uv run alembic upgrade head

uv run pytest tests/test_list_sources.py \
              tests/test_smart_collections.py \
              tests/test_smart_collections_integration.py \
              tests/test_smart_collection_worker.py \
              tests/test_overlays.py \
              tests/test_mass_operations.py \
              tests/test_mass_operations_integration.py \
              tests/test_kometa_defaults.py -v
```

## Manual E2E smoke (requires running backend + worker + Postgres)

```bash
# Terminal 1 — backend
cd /root/pyrate.media/backend
uv run uvicorn pyrate.web:app --reload

# Terminal 2 — worker (needed for run-now to actually execute)
uv run taskiq worker pyrate.worker:broker --reload
```

Then in a third terminal:

```bash
# Set $TOK to a superuser bearer token (login flow per pyrate's normal auth).

# 1. Builders catalogue (powers the admin UI form)
curl -s -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/smart-collections/builders | jq

# 2. Confirm defaults landed
psql -h $PGHOST -U $PGUSER -d $PGDATABASE -c \
  "SELECT count(*) FROM smart_collection_rule WHERE is_system=true;"
# → 50+ expected
psql -h $PGHOST -U $PGUSER -d $PGDATABASE -c \
  "SELECT count(*) FROM overlay_template WHERE is_system=true;"
# → 6 expected

# 3. Create a custom smart collection (TMDb popular)
curl -X POST http://localhost:8000/api/smart-collections \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{
    "name": "TMDb Popular (manual)",
    "media_type": "MOVIE",
    "builder_type": "tmdb",
    "builder_config": {"mode": "chart", "chart": "popular"},
    "sync_mode": "SYNC",
    "item_limit": 20,
    "schedule_cron": "0 */6 * * *",
    "enabled": true
  }'

# 4. Run it now (requires TMDb API key in settings.smart_collections.api_keys.tmdb)
curl -X POST -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/smart-collections/<guid>/run

# 5. Inspect run history
curl -s -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/smart-collections/<guid>/runs | jq

# 6. Read the resulting list (assuming auth grants list access)
curl -s -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/lists/<list_guid>/items | jq

# 7. Create an overlay template and trigger render for one item
curl -X POST http://localhost:8000/api/overlays \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{
    "name": "4K badge",
    "media_scope": "BOTH", "target": "POSTER",
    "condition": {"all":[{"field":"resolution.height","op":"gte","value":2160}]},
    "elements": [{"type":"text","text":"4K","x":"right","y":"top",
                  "padding":16,"font_size":44,"color":"#fff",
                  "background":"#000000bb","background_radius":8}],
    "enabled": true
  }'

curl -X POST -H "Authorization: Bearer $TOK" \
  "http://localhost:8000/api/overlays/apply/<media_guid>?target=POSTER"

curl -s -H "Authorization: Bearer $TOK" \
  "http://localhost:8000/api/overlays/preview/<media_guid>?target=POSTER" \
  -o /tmp/preview.jpg
file /tmp/preview.jpg          # → "JPEG image data"

# 8. Mass-op dry run, then real run
curl -X POST http://localhost:8000/api/mass-operations \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{
    "name": "Tag 4K movies",
    "target_filter": {"media_type_in": ["MOVIES"]},
    "action": {"type": "set_description", "value": "Re-tagged"},
    "enabled": true
  }'

curl -X POST -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/mass-operations/<guid>/dry-run | jq
# → returns items_matched / changed_sample

curl -X POST -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/mass-operations/<guid>/run
```

## Frontend smoke

```bash
cd /root/pyrate.media/frontend
npm install
npm run dev
# → admin must log in, then navigate:
#   /admin/smart-collections   — list, toggle, run-now, edit, history
#   /admin/overlays            — list, edit with live-preview pane
#   /admin/mass-operations     — list, dry-run dialog, apply
```

Vitest tests for the new pages weren't bundled in this MVP — the
underlying services are thin axios wrappers and the pages are UI-only.
Component-level Vitest coverage is a follow-up.

## Known limitations / follow-ups

- **Auto-discover** of unknown external IDs: refs that don't resolve are logged as
  `items_unresolved` and skipped. A "stub-import then queue Sonarr/Radarr"
  flow could come next.
- **Backdrop overlays** are wired but no defaults ship for them — only posters.
- **Music / Books / Games** are out of scope for the MVP; many builders simply
  don't have analogues there.
- **Streaming-service logo assets**: defaults ship as text-only badges. To
  show actual logos, drop PNGs under the configured `overlays.cache_dir`
  asset root and create an `image` element overlay template pointing at them.
- **Token-bearing image preview**: `<img src="/api/overlays/preview/…">` relies
  on cookie auth (axios fallback) — if pyrate later disables cookie auth on
  the API, the preview pane will need a fetch-and-blob workaround.
