# axiolyze
adapter between glm and vdag

## Install and set up

```bash
git submodule update --init --recursive
git submodule sync --recursive
python -m venv .dev
.dev\Scripts\Activate          # Windows
pip install -e ./deps/repo_vdag
pip install -e ./deps/repo_glm
```

### First-time database init (required for user auth)

```bash
cd deps/repo_vdag
reflex db init
cd ../..
```

This creates the local SQLite database for user accounts (`deps/repo_vdag/reflex_db/`).

## Run

```bash
python bridge_layer/main.py
```

The app starts at `http://localhost:3000`.

## First login

Navigate to `/register` to create your first account, then log in at `/login`.
Sessions and pipelines are persisted per user under `user_pipelines/<username>/`.

## Multi-project support

Each user can have multiple named projects. Use **File → New project…** to create
a project or **File → Open project…** to switch between saved ones.
Each project is stored as a separate YAML file on disk.

## Dependencies

| Package | Role |
|---------|------|
| `reflex` | Reactive Python web UI framework |
| `reflex-local-auth` | Username/password auth + session management |
| `axiolyze` (repo_glm) | Core GLM pipeline and transformers |
