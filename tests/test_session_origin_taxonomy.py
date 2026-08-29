"""Tests for the sidebar's high-level session-origin taxonomy."""

from pathlib import Path
import json
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _extract_function(source_text, function_name):
    marker = f"function {function_name}("
    return _extract_from_marker(source_text, marker)


def _extract_from_marker(source_text, marker):
    """Brace-match a code block starting at the first `{` after `marker`.

    Unlike `_extract_function`, `marker` need not be a `function name(...)`
    declaration — this also pulls out `const x=(...)=>{...}` closures like
    `effectiveOrigin`, so the test exercises the actual literal source instead
    of a hand-copied reimplementation that can silently drift from it.
    """
    start = source_text.index(marker)
    brace_start = source_text.index("{", start)
    depth = 0
    for index in range(brace_start, len(source_text)):
        char = source_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source_text[start : index + 1]
    raise AssertionError(f"Could not extract block at marker: {marker!r}")


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_source_filter_model_keeps_every_origin_readable_without_a_tab_strip():
    """Dropping or truncating dynamic adapters must break the source-control contract."""
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    normalize_fn = _extract_function(source, "_normalizeSessionSourceFilters")
    model_fn = _extract_function(source, "_sessionSourceFilterModel")
    script = f"""
global._sessionSourceFilters = ['matrix', 'telegram', 'slack', 'discord'];
global._serverSessionOriginCounts = {{webui: 17, cli: 2, matrix: 220, telegram: 14, slack: 8, discord: 5}};
global._serverSessionOriginLabels = {{
  webui: 'WebUI sessions',
  cli: 'CLI sessions',
  matrix: 'Matrix sessions',
  telegram: 'Telegram sessions',
  slack: 'Slack sessions',
  discord: 'Discord sessions',
}};
global._sessionOriginKeys = () => ['webui', 'cli', 'matrix', 'telegram', 'slack', 'discord'];
global._sessionSourceTabCount = (origin) => global._serverSessionOriginCounts[origin];
global._sessionSourceLabel = (origin, count) => `${{global._serverSessionOriginLabels[origin]}} (${{count}})`;
global._sessionOriginLabel = (origin) => global._serverSessionOriginLabels[origin];
{normalize_fn}
{model_fn}
console.log(JSON.stringify(_sessionSourceFilterModel(null, null)));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    model = json.loads(result.stdout)

    assert model == {
        "selectedOrigins": ["matrix", "telegram", "slack", "discord"],
        "visibleChips": [
            {"origin": "matrix", "label": "Matrix sessions"},
            {"origin": "telegram", "label": "Telegram sessions"},
        ],
        "overflowCount": 2,
        "originCount": 6,
        "items": [
            {"origin": "webui", "label": "WebUI sessions", "count": 17, "selected": False},
            {"origin": "cli", "label": "CLI sessions", "count": 2, "selected": False},
            {"origin": "matrix", "label": "Matrix sessions", "count": 220, "selected": True},
            {"origin": "telegram", "label": "Telegram sessions", "count": 14, "selected": True},
            {"origin": "slack", "label": "Slack sessions", "count": 8, "selected": True},
            {"origin": "discord", "label": "Discord sessions", "count": 5, "selected": True},
        ],
    }


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_source_menu_item_uses_checkbox_and_reports_immediate_checked_state():
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    render_fn = _extract_function(source, "_renderSessionSourceMenuItem")
    script = f"""
global.document = {{
  createElement(tag) {{
    return {{
      tagName: tag.toUpperCase(), type: '', className: '', textContent: '', checked: false,
      dataset: {{}}, attrs: {{}},
      children: [],
      appendChild(child) {{ this.children.push(child); }},
      setAttribute(key, value) {{ this.attrs[key] = value; }},
    }};
  }},
}};
{render_fn}
const changes = [];
const row = _renderSessionSourceMenuItem(
  {{origin:'slack', label:'Slack sessions', count:8, selected:false}},
  (origin, selected) => changes.push([origin, selected])
);
const checkbox = row.children[0];
checkbox.checked = true;
checkbox.onchange({{stopPropagation(){{}}}});
console.log(JSON.stringify({{
  rowTag: row.tagName,
  checkboxTag: checkbox.tagName,
  checkboxType: checkbox.type,
  origin: checkbox.dataset.origin,
  initialSelected: checkbox.attrs['aria-checked'],
  rowRole: row.attrs['role'],
  checkboxRole: checkbox.attrs['role'],
  changes,
}}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        "rowTag": "DIV",
        "checkboxTag": "INPUT",
        "checkboxType": "checkbox",
        "origin": "slack",
        "initialSelected": "false",
        "rowRole": "presentation",
        "checkboxRole": "menuitemcheckbox",
        "changes": [["slack", True]],
    }


def test_sidebar_origin_preserves_raw_channel_identity():
    from api.routes import _normalize_sidebar_source_flags, _sidebar_session_origin

    cases = {
        "webui": "webui",
        "cli": "cli",
        "tui": "tui",
        "matrix": "matrix",
        "telegram": "telegram",
        "slack": "slack",
        "discord": "discord",
        "api_server": "api",
    }
    for raw, expected in cases.items():
        row = {"source_tag": raw, "session_source": "messaging"}
        assert _sidebar_session_origin(row) == expected
        assert _normalize_sidebar_source_flags(row)["session_origin"] == expected


def test_sidebar_origin_defaults_blank_rows_to_webui_and_unknown_rows_to_their_source():
    from api.routes import _sidebar_session_origin

    assert _sidebar_session_origin({"session_id": "native"}) == "webui"
    assert _sidebar_session_origin({"source_tag": "new_adapter"}) == "new_adapter"
    assert _sidebar_session_origin({"session_source": "cli", "is_cli_session": True}) == "cli"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_client_origin_preserves_legacy_webui_markers():
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    origin_fn = _extract_function(source, "_sessionOrigin")
    script = f"""
const _SESSION_ORIGIN_ORDER = ['webui','cli','subagent','other'];
function _isCliSession() {{ return false; }}
{origin_fn}
console.log(JSON.stringify([
  _sessionOrigin({{source:'webui', session_source:'webui'}}),
  _sessionOrigin({{raw_source:'webui'}}),
  _sessionOrigin({{source_tag:'webui'}}),
]));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["webui", "webui", "webui"]


def test_sidebar_payload_exposes_origin_metadata_and_dynamic_filtering_contract(monkeypatch):
    import api.routes as routes
    import api.profiles as profiles

    rows = []
    for sid, source in (("matrix-1", "matrix"), ("telegram-1", "telegram"), ("tui-1", "tui")):
        rows.append({
            "session_id": sid,
            "title": sid,
            "profile": "default",
            "source_tag": source,
            "raw_source": source,
            "session_source": "messaging" if source in {"matrix", "telegram"} else "cli",
            "source_label": source.title(),
            "message_count": 2,
            "actual_message_count": 2,
            "updated_at": 10,
            "last_message_at": 10,
            "archived": False,
        })
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [])
    monkeypatch.setattr(routes, "get_cli_sessions", lambda **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda _rows: None)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=True,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        show_matrix_sessions=True,
        sidebar_source="matrix",
        visible_only=True,
    )
    assert [row["session_id"] for row in payload["sessions"]] == ["matrix-1"]
    assert payload["session_origin_counts"] == {"matrix": 1, "telegram": 1, "tui": 1}
    assert payload["session_origin_labels"]["matrix"] == "Matrix sessions"


def test_webui_filtered_payload_counts_available_state_db_origins(monkeypatch, tmp_path):
    import sqlite3
    import api.routes as routes

    db_path = tmp_path / "state.db"
    con = sqlite3.connect(db_path)
    con.execute("create table sessions (id text primary key, source text)")
    con.executemany(
        "insert into sessions (id, source) values (?, ?)",
        [("matrix-1", "matrix"), ("telegram-1", "telegram")],
    )
    con.commit()
    con.close()

    monkeypatch.setattr(routes, "_active_state_db_path", lambda: db_path)
    webui_row = {
        "session_id": "webui-1",
        "title": "WebUI session",
        "profile": "default",
        "source": "webui",
        "message_count": 2,
        "updated_at": 20,
        "last_message_at": 20,
        "archived": False,
    }
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [dict(webui_row)])
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(routes, "get_cli_sessions", lambda **_kwargs: [])

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        show_matrix_sessions=False,
        sidebar_source="webui",
    )

    assert [row["session_id"] for row in payload["sessions"]] == ["webui-1"]
    # session_origin_counts now only from filtered scoped rows, not max-merged state.db aggregate
    assert payload["session_origin_counts"] == {
        "webui": 1,
    }


def test_sidebar_payload_exposes_origin_metadata_fields():
    routes = REPO_ROOT / "api" / "routes.py"
    source = routes.read_text(encoding="utf-8")
    assert '"session_origin_counts"' in source
    assert '"session_origin_labels"' in source
    assert "_effective_sidebar_origin(s) in selected_sidebar_source_set" in source
    assert '"session_origin",' in source


def test_sidebar_frontend_renders_origin_tabs_and_accepts_non_cli_origins():
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    assert "_serverSessionOriginCounts" in source
    assert "session_origin_counts" in source
    assert "_sessionOriginKeys" in source
    assert "selectedOrigins.has(_sessionOrigin(s))" in source
    assert "session_origin" in source


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_effective_origin_inherits_plain_webui_grandparent_through_subagent_child():
    """A legacy subagent-marked child with no explicit session_origin must
    resolve to its grandparent's real origin, not stay stuck on the
    'subagent' compatibility sentinel — the exact case CHANGES_REQUESTED
    review round 2 on #6985 flagged: the walk previously fell back to
    `_sessionOrigin(s)` (the *original* argument) instead of `_sessionOrigin(cur)`
    (the resolved ancestor), silently discarding the walk whenever every
    hop in the chain was itself a placeholder ('webui' or 'subagent')."""
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    order_line = next(line for line in source.splitlines() if line.startswith("const _SESSION_ORIGIN_ORDER="))
    origin_fn = _extract_function(source, "_sessionOrigin")
    is_child_fn = _extract_function(source, "_isChildSession")
    is_cli_fn = _extract_function(source, "_isCliSession")
    is_messaging_fn = _extract_function(source, "_isMessagingSession")
    # Pull the REAL sourceRowsById + effectiveOrigin closure straight out of
    # sessions.js (not a hand-copied reimplementation) so this test tracks the
    # actual shipped fix instead of silently drifting from it.
    source_rows_line = next(
        line for line in source.splitlines()
        if line.strip().startswith("const sourceRowsById=")
    )
    effective_origin_block = _extract_from_marker(source, "const effectiveOrigin=s=>{")
    script = f"""
{order_line}
const _MESSAGING_RAW_SOURCES = new Set();
{is_messaging_fn}
{is_cli_fn}
{origin_fn}
{is_child_fn}
const allMatched = [
  {{session_id:'grandparent', title:'root'}},
  {{session_id:'child', parent_session_id:'grandparent', relationship_type:'child_session', session_origin:'subagent'}},
  {{session_id:'grandchild', parent_session_id:'child', relationship_type:'child_session', session_origin:'subagent'}},
];
{source_rows_line}
const effectiveOrigin={effective_origin_block.split("=", 1)[1]}
console.log(JSON.stringify({{
  child: effectiveOrigin(sourceRowsById.get('child')),
  grandchild: effectiveOrigin(sourceRowsById.get('grandchild')),
}}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"child": "webui", "grandchild": "webui"}


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_effective_origin_resolves_real_external_ancestor_and_falls_back_deterministically_on_cycle():
    """#6985 review round 3: the client walk's exhausted-chain fallback must
    return the single deterministic 'webui' sentinel, not re-derive from
    `cur`/`s` (which could echo a non-standard explicit marker raw). Covers
    two cases against the REAL effectiveOrigin closure (not a reimplementation):
    (1) a genuine external ancestor present in the loaded row set is inherited
    correctly through a subagent child, and (2) a parent_session_id cycle among
    loaded rows terminates via the existing visited-set bound and falls back
    to 'webui' instead of hanging or returning something else raw."""
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    order_line = next(line for line in source.splitlines() if line.startswith("const _SESSION_ORIGIN_ORDER="))
    origin_fn = _extract_function(source, "_sessionOrigin")
    is_child_fn = _extract_function(source, "_isChildSession")
    is_cli_fn = _extract_function(source, "_isCliSession")
    is_messaging_fn = _extract_function(source, "_isMessagingSession")
    source_rows_line = next(
        line for line in source.splitlines()
        if line.strip().startswith("const sourceRowsById=")
    )
    effective_origin_block = _extract_from_marker(source, "const effectiveOrigin=s=>{")
    script = f"""
{order_line}
const _MESSAGING_RAW_SOURCES = new Set();
{is_messaging_fn}
{is_cli_fn}
{origin_fn}
{is_child_fn}
const allMatched = [
  {{session_id:'external-ancestor', session_origin:'matrix'}},
  {{session_id:'subagent-child', parent_session_id:'external-ancestor', relationship_type:'child_session', session_origin:'subagent'}},
  {{session_id:'cycle-a', parent_session_id:'cycle-b', relationship_type:'child_session', session_origin:'subagent'}},
  {{session_id:'cycle-b', parent_session_id:'cycle-a', relationship_type:'child_session', session_origin:'subagent'}},
];
{source_rows_line}
const effectiveOrigin={effective_origin_block.split("=", 1)[1]}
console.log(JSON.stringify({{
  externalAncestor: effectiveOrigin(sourceRowsById.get('subagent-child')),
  cycle: effectiveOrigin(sourceRowsById.get('cycle-a')),
}}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"externalAncestor": "matrix", "cycle": "webui"}


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_source_chip_labels_pass_scalar_args_not_objects():
    """#6985 review round 2: the localized source-chip controls called
    `t(key, {{count: n}})` / `t(key, {{label: x}})`, but `t()` forwards its
    arguments positionally to the locale function, which expects a bare
    scalar. The object form rendered literal '[object Object]' text and
    made `Number({{count:1}})` (NaN) so the singular branch could never
    fire. Assert both the count-1 (singular) and count-many (plural) shapes
    render real text, not '[object Object]' or 'NaN'."""
    source = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
    trigger_line = next(
        line for line in source.splitlines()
        if "t('session_source_trigger'" in line and "textContent" in line
    )
    remove_line = next(
        line for line in source.splitlines()
        if "t('session_source_remove'" in line
    )
    assert "{count:" not in trigger_line and "{ count:" not in trigger_line
    assert "{label:" not in remove_line and "{ label:" not in remove_line
    script = """
global.t = (key, arg) => {
  if (key === 'session_source_trigger') {
    const n = Number(arg);
    return n === 1 ? 'Source' : `Sources (${n})`;
  }
  if (key === 'session_source_remove') return `Remove ${arg}`;
  return key;
};
console.log(JSON.stringify({
  singular: global.t('session_source_trigger', 1),
  plural: global.t('session_source_trigger', 5),
  remove: global.t('session_source_remove', 'Slack'),
}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    rendered = json.loads(result.stdout)
    assert rendered == {"singular": "Source", "plural": "Sources (5)", "remove": "Remove Slack"}
    assert "[object Object]" not in json.dumps(rendered)
    assert "NaN" not in json.dumps(rendered)


def _make_state_db_rows(path, rows):
    """Create a minimal state.db at ``path`` with one row per (sid, source,
    parent_session_id) in ``rows``. Schema mirrors the subset
    _state_db_lineage_lookup actually reads."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT)"
    )
    for sid, source, parent_session_id in rows:
        conn.execute(
            "INSERT INTO sessions (id, source, parent_session_id) VALUES (?, ?, ?)",
            (sid, source, parent_session_id),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def origin_fallback_env(tmp_path, monkeypatch):
    """Isolated environment for the missing-ancestor state.db fallback:
    an empty WebUI sessions dir (so Session.load_metadata_only() always
    misses — no sidecar exists for any id used here, matching the real
    delegated-subagent shape from #5307) plus per-profile state.db files
    the fallback can be pointed at via _get_profile_home.
    """
    import api.models as models
    import api.routes as routes

    sessions_dir = tmp_path / "webui-sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(models, "SESSION_DIR", sessions_dir)

    profile_homes = {}

    def _get_profile_home(profile):
        home = profile_homes.setdefault(str(profile), tmp_path / f"profile-{profile}")
        home.mkdir(parents=True, exist_ok=True)
        return home

    monkeypatch.setattr(models, "_get_profile_home", _get_profile_home)

    default_db = tmp_path / "default-state.db"
    monkeypatch.setattr(models, "_active_state_db_path", lambda: default_db)

    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(routes, "get_cli_sessions", lambda **_kwargs: [])

    return {"sessions_dir": sessions_dir, "profile_homes": profile_homes, "default_db": default_db}


def _run_payload(routes, leaf_row, *, active_profile, sidebar_source):
    import api.routes as _routes  # noqa: F401  (routes param kept for readability)

    payload = routes._build_session_list_cache_payload(
        active_profile=active_profile,
        all_profiles=False,
        show_cli_sessions=True,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        show_matrix_sessions=True,
        sidebar_source=sidebar_source,
    )
    return [s["session_id"] for s in payload["sessions"]]


def test_effective_sidebar_origin_resolves_external_ancestor_with_no_sidecar_via_state_db(
    origin_fallback_env, monkeypatch,
):
    """#6985 review round 3: the missing-ancestor fallback only read the
    WebUI sidecar (Session.load_metadata_only), which misses every delegated
    subagent ancestor — those ran server-side and have NO sidecar at all
    (#5307), only a state.db row. Covers external parent -> subagent child
    -> grandchild, with BOTH ancestors omitted from the payload builder's
    loaded rows (only the leaf grandchild is 'in scope'), proving the
    grandchild inherits the external origin through two state.db-only hops.
    """
    import api.routes as routes

    # Use the fixture's _get_profile_home so the path matches exactly what
    # _agent_state_db_path(profile="default") will resolve.
    from api.models import _get_profile_home
    home = _get_profile_home("default")
    db_path = home / "state.db"
    _make_state_db_rows(
        db_path,
        [
            ("external-ancestor", "matrix", None),
            ("subagent-child", "subagent", "external-ancestor"),
        ],
    )
    assert not (origin_fallback_env["sessions_dir"] / "external-ancestor.json").exists()
    assert not (origin_fallback_env["sessions_dir"] / "subagent-child.json").exists()

    grandchild_row = {
        "session_id": "grandchild-of-ghost",
        "parent_session_id": "subagent-child",
        "message_count": 1,
        "project_id": None,
        "profile": "default",
        "updated_at": 5,
    }
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [grandchild_row])

    assert _run_payload(routes, grandchild_row, active_profile="default", sidebar_source="matrix") == [
        "grandchild-of-ghost"
    ]
    assert _run_payload(routes, grandchild_row, active_profile="default", sidebar_source="webui") == []


def test_effective_sidebar_origin_does_not_leak_ancestor_across_profiles(
    origin_fallback_env, monkeypatch,
):
    """The state.db fallback must be profile-scoped: an ancestor that only
    exists in a DIFFERENT profile's state.db must not be found when
    resolving a child under the active profile — the sidebar filter must
    fall back to 'webui', not leak the other profile's classification.

    Deliberately does NOT create the "default" profile's own state.db file
    first. Verified this reproduces a real leak against the original
    implementation: ``_state_db_lineage_lookup`` used to resolve the target
    profile's db via ``_agent_state_db_path()``, which falls back to
    ``_active_state_db_path()`` (the server-wide currently-active session's
    db, independent of the profile this payload is being built for)
    whenever the named profile's own db file doesn't exist yet — silently
    serving a foreign profile's data instead of correctly resolving to
    nothing. Populating the mocked "active" db (not "default"'s own) with
    the foreign row reproduces that leak; the fix resolves the named
    profile's path directly with no such fallback.
    """
    import api.routes as routes
    from api.models import _get_profile_home

    other_home = _get_profile_home("other-profile")
    _make_state_db_rows(other_home / "state.db", [("cross-profile-ancestor", "matrix", None)])
    _make_state_db_rows(origin_fallback_env["default_db"], [("cross-profile-ancestor", "matrix", None)])

    child_row = {
        "session_id": "child-of-cross-profile-ghost",
        "parent_session_id": "cross-profile-ancestor",
        "message_count": 1,
        "project_id": None,
        "profile": "default",
        "updated_at": 5,
    }
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [child_row])

    assert _run_payload(routes, child_row, active_profile="default", sidebar_source="matrix") == []
    assert _run_payload(routes, child_row, active_profile="default", sidebar_source="webui") == [
        "child-of-cross-profile-ghost"
    ]


def test_effective_sidebar_origin_missing_ancestor_row_falls_back_to_webui(
    origin_fallback_env, monkeypatch,
):
    """A parent_session_id that exists in NEITHER a sidecar NOR any state.db
    row (already deleted, or never existed) must fall back to the
    deterministic 'webui' sentinel, not raise or misclassify."""
    import api.routes as routes
    from api.models import _get_profile_home

    _make_state_db_rows(_get_profile_home("default") / "state.db", [])

    child_row = {
        "session_id": "child-of-nothing",
        "parent_session_id": "truly-gone",
        "message_count": 1,
        "project_id": None,
        "profile": "default",
        "updated_at": 5,
    }
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [child_row])

    assert _run_payload(routes, child_row, active_profile="default", sidebar_source="webui") == [
        "child-of-nothing"
    ]
    assert _run_payload(routes, child_row, active_profile="default", sidebar_source="matrix") == []


def test_effective_sidebar_origin_cycle_falls_back_to_webui_without_hanging(
    origin_fallback_env, monkeypatch,
):
    """A parent_session_id cycle resolved entirely through the state.db
    fallback (A -> B -> A) must terminate via the existing visited-set bound
    and fall back to 'webui', not loop forever."""
    import api.routes as routes
    from api.models import _get_profile_home

    _make_state_db_rows(
        _get_profile_home("default") / "state.db",
        [("cycle-a", None, "cycle-b"), ("cycle-b", None, "cycle-a")],
    )

    child_row = {
        "session_id": "child-of-cycle",
        "parent_session_id": "cycle-a",
        "message_count": 1,
        "project_id": None,
        "profile": "default",
        "updated_at": 5,
    }
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [child_row])

    assert _run_payload(routes, child_row, active_profile="default", sidebar_source="webui") == [
        "child-of-cycle"
    ]


def test_effective_origin_fallback_lookup_queries_state_db_at_most_once_per_ancestor(
    origin_fallback_env, monkeypatch,
):
    """Repeated-miss/query-bound (#6985 review round 3, item 1).

    A HIT (the ancestor resolves successfully) is already deduped by the
    pre-existing ``_effective_session_by_id`` cache regardless of whether
    ``_effective_origin_fallback_lookup``'s own ``_origin_fallback_cache``
    exists at all: `_effective_session_by_id[pid] = parent` only runs on a
    successful resolution, so re-testing that path proves nothing about the
    NEW memoization layer (verified: deleting `_origin_fallback_cache`'s
    early-return still passes a same-ancestor-HIT version of this test).

    The new cache's actual, distinct value is deduping repeated MISSES: on
    a miss `_effective_origin_fallback_lookup` returns None and the caller
    `break`s BEFORE ever writing to `_effective_session_by_id` — so without
    `_origin_fallback_cache` covering the miss too, every child referencing
    the same nonexistent ancestor re-triggers a full sidecar-then-state.db
    lookup. Assert both the sidecar read (`Session.load_metadata_only`) and
    the state.db read are each invoked at most once despite 5 children all
    missing on the same nonexistent ancestor id.
    """
    import api.models as models
    import api.routes as routes
    from api.models import _get_profile_home

    home = _get_profile_home("default")
    _make_state_db_rows(home / "state.db", [])  # ancestor id never exists

    sidecar_calls = {"n": 0}
    state_db_calls = {"n": 0}
    real_state_db_lookup = routes._state_db_lineage_lookup
    real_load_metadata_only = models.Session.load_metadata_only

    def _counting_state_db_lookup(pid, profile):
        state_db_calls["n"] += 1
        return real_state_db_lookup(pid, profile)

    def _counting_load_metadata_only(pid):
        sidecar_calls["n"] += 1
        return real_load_metadata_only(pid)

    monkeypatch.setattr(routes, "_state_db_lineage_lookup", _counting_state_db_lookup)
    monkeypatch.setattr(models.Session, "load_metadata_only", staticmethod(_counting_load_metadata_only))

    rows = [
        {
            "session_id": f"child-{i}",
            "parent_session_id": "nonexistent-ancestor",
            "message_count": 1,
            "project_id": None,
            "profile": "default",
            "updated_at": i,
        }
        for i in range(5)
    ]
    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: rows)

    result = _run_payload(routes, rows[0], active_profile="default", sidebar_source="webui")
    assert sorted(result) == [f"child-{i}" for i in range(5)]
    assert sidecar_calls["n"] == 1, f"expected exactly one sidecar lookup for the shared missing ancestor, got {sidecar_calls['n']}"
    assert state_db_calls["n"] == 1, f"expected exactly one state.db query for the shared missing ancestor, got {state_db_calls['n']}"
