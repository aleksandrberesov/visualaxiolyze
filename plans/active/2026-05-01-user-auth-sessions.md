# User authentication and session persistence

**Created:** 2026-05-01
**Status:** Completed
**Context:** Current architecture keys `pipeline_registry._store` by ephemeral `client_token`.
When a user closes and reopens the app they get a new token and cannot recover their
pipeline. A login system replaces the token with a stable `user_id`, enabling session
recovery and multi-project support.

All changes land in `deps/repo_vdag/GraphVision/` only.
Bridge layer and axiolyze backend are untouched.

## Phase status

- [x] Phase 1 — Auth foundation (login page + user state)
- [x] Phase 2 — Registry re-key (user_id replaces client_token)
- [x] Phase 3 — Pipeline persistence (save/load per user on disk)
- [x] Phase 4 — Multi-project support (named pipelines per user)

---

## Phase 1 — Auth foundation

### 1.1 Install reflex-local-auth
```
pip install reflex-local-auth
```
Add to project dependencies.

### 1.2 Auth state
**File:** new `GraphVision/models/auth_state.py`
- Subclass `LocalAuthState` from `reflex_local_auth`.
- Expose `user_id: str` computed var (username or user primary key as string).
- Expose `is_authenticated: bool` computed var.

### 1.3 Login / register page
**File:** new `GraphVision/pages/login.py`
- Use `reflex_local_auth` built-in login form or wrap it.
- Redirect to main page on successful login.
- Redirect unauthenticated users from main page to login.

### 1.4 Route protection
**File:** `GraphVision/GraphVision.py` (or app entry)
- Register `/login` route.
- Add auth guard on `/` — redirect to `/login` if not authenticated.

### 1.5 Logout button
**File:** `GraphVision/components/top_menu.py`
- Add logout item to File menu (or a separate user badge in the top bar).
- Calls `AuthState.logout` event.

---

## Phase 2 — Registry re-key

### 2.1 Update pipeline_registry to support user_id key
**File:** `GraphVision/models/pipeline_hooks.py`
- No change needed — hooks already accept `session_id: str`; we just pass a
  different value.

### 2.2 Replace client_token with user_id in GraphState
**File:** `GraphVision/models/graph.py`
- Replace every `self.router.session.client_token` with
  `(await self.get_state(AuthState)).user_id`.
- All pipeline_hooks calls automatically use the stable user key.

### 2.3 Replace client_token in ConfigState and SchemaState
**Files:**
- `GraphVision/models/config_state.py`
- `GraphVision/models/schema_state.py`
- Same substitution: `self.router.session.client_token` → `user_id` from AuthState.

---

## Phase 3 — Pipeline persistence (auto-save/load)

### 3.1 Per-user pipeline directory
**File:** `bridge_layer/pipeline_registry.py`
- Add `PIPELINES_DIR = Path("user_pipelines/")` (configurable).
- On `set(user_id, pipeline)`: also call `pipeline.save_to_yaml(PIPELINES_DIR / user_id / "default.yaml")`.
- Add `load_from_disk(user_id) -> Optional[PipelineGraph]` helper.

### 3.2 Restore pipeline on login
**File:** `GraphVision/models/auth_state.py`
- After successful login, call `GraphState.restore_session` event.

**File:** `GraphVision/models/graph.py`
- Add `restore_session` event:
  - Calls `pipeline_hooks.restore_pipeline(user_id)`.
  - If found: `sync_from_pipeline()` + `data_loaded = True`.
  - If not found: leave state empty (user sees "No dataset loaded" banner).

### 3.3 Auto-save on meaningful changes
**File:** `GraphVision/models/graph.py`
- After `add_transformation_node`, `manifest_node`, `create_graph_with_data`:
  call `pipeline_hooks.persist_pipeline(user_id)` (non-blocking, best-effort).

---

## Phase 4 — Multi-project support

### 4.1 Project name in registry key
**File:** `bridge_layer/pipeline_registry.py`
- Change key from `user_id` to `(user_id, project_name)`.
- `PIPELINES_DIR / user_id / f"{project_name}.yaml"`.

### 4.2 Project switcher UI
**File:** `GraphVision/components/top_menu.py`
- File menu: "New project…", "Open project…" (lists saved YAMLs for this user).
- `GraphState.project_name: str` tracks active project.

### 4.3 Session cleanup on logout
**File:** `GraphVision/models/auth_state.py`
- On logout: auto-save current pipeline, then clear `GraphState` nodes/edges.
- Registry entry for this user stays on disk; memory entry can be evicted.

---

## Notes

- `reflex-local-auth` stores credentials in a local SQLite DB by default —
  no external auth service needed for an initial version.
- `user_id` should be the username string (stable, human-readable) rather than
  an integer PK, so YAML paths are readable on disk.
- Phases 1 and 2 are the minimum viable change — after those two phases the
  session-recovery problem is solved even without auto-save.
- Phase 3 adds durability (survives server restart).
- Phase 4 adds multi-project (can be deferred).
