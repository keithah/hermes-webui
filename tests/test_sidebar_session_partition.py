"""Regression coverage for single-pass sidebar session partitioning."""

from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _function_block(name: str) -> str:
    start = SESSIONS_JS.index(f"function {name}(")
    brace = SESSIONS_JS.index("{", start)
    depth = 0
    for idx in range(brace, len(SESSIONS_JS)):
        char = SESSIONS_JS[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return SESSIONS_JS[start : idx + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _partition_block() -> str:
    return _function_block("_partitionSidebarSessionRows")


def test_render_uses_single_pass_partition_helper():
    render_body = _function_block("renderSessionListFromCache")

    assert "_partitionSidebarSessionRows(allMatched, activeSidForSidebar)" in render_body
    assert "_renderSidebarRowsFromRawSessions(sessionsRaw, [...referenceRaw, ..._scopedSidebarReferenceRows()])" in render_body
    assert "const renderedWebuiSessionCount=_serverWebuiSessionCount===null" in render_body
    assert "const renderedCliSessionCount=_serverCliSessionCount===null" in render_body
    assert "? _renderSidebarRowsFromRawSessions(webuiSessionsRaw, [...webuiReferenceRaw, ..._scopedSidebarReferenceRows(false)]).length" in render_body
    assert "? _renderSidebarRowsFromRawSessions(cliSessionsRaw, [...cliReferenceRaw, ..._scopedSidebarReferenceRows(true)]).length" in render_body
    assert ": null;" in render_body
    assert "null is a deliberate \"not computed\" sentinel" in render_body
    assert "const webuiSessionTabCount=_sessionSourceTabCount('webui', renderedWebuiSessionCount, renderedCliSessionCount);" in render_body
    assert "const cliSessionTabCount=_sessionSourceTabCount('cli', renderedWebuiSessionCount, renderedCliSessionCount);" in render_body
    assert "withMessages.filter(" not in render_body


def test_partition_helper_applies_message_source_project_and_archive_gates():
    block = _partition_block()

    assert "function _sidebarRowHasVisibleMessages(s, activeSidForSidebar)" in SESSIONS_JS
    assert "_sidebarRowHasVisibleMessages(s, activeSidForSidebar)" in block
    assert "activeSourceFilters.some(source=>source!=='webui')" not in block
    assert "const selectedOrigins=new Set(activeSourceFilters);" in block
    assert "selectedOrigins.has(effectiveOrigin(s))" in block
    assert "parent&&_isChildSession(s)?_sessionOrigin(parent):_sessionOrigin(s)" in block
    assert "if(!_showArchived&&s.archived) continue;" in block
    assert "if(s.archived){" in block
    assert "? _selectedSessionOriginArchivedCount([...selectedOrigins])" in block
    assert "archivedCount: Math.max(showCliOnly ? cliArchivedCount : webuiArchivedCount, Number(serverArchivedCount||0))," in block
    assert "return {" in block
    assert "profileFiltered: selectedProfileFiltered," in block
    assert "sessionsRaw: selectedSessionsRaw," in block


def test_partition_helper_keeps_raw_source_counts_while_render_owns_visible_counts():
    render_body = _function_block("renderSessionListFromCache")

    assert "webuiSessionCount," not in _partition_block()
    assert "cliSessionCount," in _partition_block()
    assert "webuiReferenceRaw," in _partition_block()
    assert "cliReferenceRaw," in _partition_block()
    assert "webuiSessionsRaw," in _partition_block()
    assert "cliSessionsRaw," in _partition_block()
    assert "const renderedWebuiSessionCount=_serverWebuiSessionCount===null" in render_body
    assert "const renderedCliSessionCount=_serverCliSessionCount===null" in render_body
    assert "? _renderSidebarRowsFromRawSessions(webuiSessionsRaw, [...webuiReferenceRaw, ..._scopedSidebarReferenceRows(false)]).length" in render_body
    assert "? _renderSidebarRowsFromRawSessions(cliSessionsRaw, [...cliReferenceRaw, ..._scopedSidebarReferenceRows(true)]).length" in render_body
    assert "function _countRenderedSidebarRowsFromRawSessions" not in SESSIONS_JS
    assert "function _renderSidebarRowsFromRawSessions(sessionsRaw, referenceSessionsRaw){" in SESSIONS_JS
    assert "_attachChildSessionsToSidebarRows(_collapseSessionLineageForSidebar(sessionsRaw), sessionsRaw, referenceRows)" in SESSIONS_JS


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_partition_preserves_explicit_matrix_selection_when_cli_display_is_off():
    script = f"""
global.window = {{ _showCliSessions: false }};
global._sessionSourceFilters = ['matrix'];
global._sessionSourceFilter = 'matrix';
global._activeProject = null;
global.NO_PROJECT_FILTER = '__none__';
global._showArchived = false;
global._archivedWebuiCount = 0;
global._archivedCliCount = 0;
global._serverArchivedSessionOriginCounts = {{}};
global.S = {{ session: null }};
global._sessionAttentionState = () => null;
global._isSessionEffectivelyStreaming = () => false;
global._isChildSession = () => false;
global._isCliSession = () => false;
global._sessionOrigin = session => session.session_origin;
{_function_block('_selectedSessionOriginArchivedCount')}
{_function_block('_sidebarRowHasVisibleMessages')}
{_function_block('_partitionSidebarSessionRows')}
const row = {{ session_id: 'matrix-1', session_origin: 'matrix', message_count: 1 }};
const result = _partitionSidebarSessionRows([row], null);
console.log(JSON.stringify({{
  selected: _sessionSourceFilters,
  legacy: _sessionSourceFilter,
  ids: result.sessionsRaw.map(session => session.session_id),
}}));
"""
    completed = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    )
    body = json.loads(completed.stdout)

    assert body == {
        "selected": ["matrix"],
        "legacy": "matrix",
        "ids": ["matrix-1"],
    }


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_partition_uses_authoritative_archived_counts_for_selected_origins():
    source = SESSIONS_JS
    helper = _function_block("_selectedSessionOriginArchivedCount")
    script = f"""
global._serverArchivedSessionOriginCounts = {{matrix: 2, telegram: 3, webui: 4}};
global._archivedWebuiCount = 99;
global._archivedCliCount = 88;
{helper}
console.log(JSON.stringify({{
  matrix: _selectedSessionOriginArchivedCount(['matrix']),
  externalUnion: _selectedSessionOriginArchivedCount(['matrix', 'telegram']),
  mixed: _selectedSessionOriginArchivedCount(['webui', 'matrix']),
}}));
"""
    completed = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    )
    body = json.loads(completed.stdout)

    assert body == {"matrix": 2, "externalUnion": 5, "mixed": 6}


def test_archive_load_more_uses_source_wide_loaded_count_and_hides_under_filters():
    render_body = _function_block("renderSessionListFromCache")

    assert "function _sessionArchivePagingFilterActive()" in SESSIONS_JS
    assert "const archivePagingFilterActive=_sessionArchivePagingFilterActive();" in render_body
    assert "if(_showArchived&&!archivePagingFilterActive){" in render_body
    assert "const loadedArchivedCount=sidebarRows.filter" in render_body
    assert "const archiveLoadCapReached=Number(_archivedRowsLoadedLimit||0)>=SESSION_ARCHIVED_MAX_LOADED_LIMIT;" in render_body
    assert "const remainingArchived=archiveLoadCapReached?0:Math.max(0, Number(activeArchivedTotal||0)-loadedArchivedCount);" in render_body
    assert "const remainingArchived=Math.max(0, Number(activeArchivedTotal||0)-loadedArchivedCount);" not in render_body
    assert "orderedSessions.filter(s=>s&&s.archived).length" not in render_body
