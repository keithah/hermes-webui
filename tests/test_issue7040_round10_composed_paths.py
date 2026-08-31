import json, subprocess, shutil, textwrap
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
MESSAGES_JS = REPO / "static" / "messages.js"
UI_JS = REPO / "static" / "ui.js"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"

DRIVER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extractFunc(name) {
  const start = src.search(new RegExp('function\\s+' + name + '\\s*\\('));
  if (start < 0) throw new Error(name + ' not found in source');
  let cursor = src.indexOf('{', start) + 1;
  let depth = 1;
  while (depth && cursor < src.length) {
    if (src[cursor] === '{') depth++;
    else if (src[cursor] === '}') depth--;
    cursor++;
  }
  return src.slice(start, cursor);
}
function extractLine(re, label) {
  const m = src.match(re);
  if (!m) throw new Error(label + ' not found in source');
  return m[0];
}

// The claim sets hang off the inflight record and are created lazily by
// upsertLiveToolCall itself, so nothing extra has to be declared here. Assert
// the production reset point still exists -- without it a reattach would keep
// stale claims and a replayed event would mint a duplicate.
extractLine(/delete INFLIGHT\[activeSid\]\._startClaimedRecords;/, 'per-attach claim reset');

const parts = [
  extractFunc('_coerceLiveToolCallSeq'),
  extractFunc('_coerceLiveToolCallSignature'),
  extractFunc('activityBurstFallbackFromCandidate'),
  extractFunc('activitySegmentSeqFallbackFromCandidate'),
  extractFunc('_stableStringify'),
  extractFunc('_hashString'),
  extractFunc('_toolCallSignature'),
  extractFunc('_liveToolTid'),
  extractFunc('_findPendingLiveToolCallIndex'),
  extractFunc('upsertLiveToolCall'),
];

// Minimal environment the producer touches.
const preamble = `
const activeSid = 'sess-1';
const uploaded = [];
const S = { toolCalls: [], messages: [], session: { session_id: activeSid } };
const INFLIGHT = {};
function persistInflightState(){}
let __anchor = { burstId: 7, segmentSeq: 2 };
function _currentLiveToolAnchor(){ return __anchor; }
`;

const mod = preamble + parts.join('\n') + `
module.exports = { upsertLiveToolCall, INFLIGHT, S, activeSid };
`;
const path = process.argv[3];
fs.writeFileSync(path, mod);
const M = require(path);

const ARGS = { path: '/tmp/x.txt' };
function ev(){ return { name: 'read_file', args: ARGS, preview: 'p' }; }

const out = {};

// --- Case A: two equal ID-less STARTs, then their two completions ---
M.upsertLiveToolCall(ev(), 'start');
M.upsertLiveToolCall(ev(), 'start');
let calls = M.INFLIGHT[M.activeSid].toolCalls;
out.startOnly_count = calls.length;
out.startOnly_tids = calls.map(c => c.tid);
out.startOnly_occurrences = calls.map(c => c._occurrence);

M.upsertLiveToolCall(Object.assign(ev(), { snippet: 'first-result' }), 'complete');
M.upsertLiveToolCall(Object.assign(ev(), { snippet: 'second-result' }), 'complete');
calls = M.INFLIGHT[M.activeSid].toolCalls;
out.afterComplete_count = calls.length;
out.afterComplete_done = calls.map(c => c.done === true);
out.afterComplete_snippets = calls.map(c => c.snippet);

// --- Case B: completion-only events (no preceding start) ---
delete M.INFLIGHT[M.activeSid];
M.upsertLiveToolCall(Object.assign(ev(), { snippet: 'c1' }), 'complete');
M.upsertLiveToolCall(Object.assign(ev(), { snippet: 'c2' }), 'complete');
const c2 = M.INFLIGHT[M.activeSid].toolCalls;
out.completeOnly_count = c2.length;
out.completeOnly_tids = c2.map(c => c.tid);
out.completeOnly_occurrences = c2.map(c => c._occurrence);
out.completeOnly_snippets = c2.map(c => c.snippet);

console.log(JSON.stringify(out));
"""


def _run(tmp_path):
    driver = tmp_path / "driver.js"
    driver.write_text(DRIVER)
    proc = subprocess.run(
        [NODE, str(driver), str(MESSAGES_JS), str(tmp_path / "mod.js")],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError("node driver failed:\n" + proc.stdout + proc.stderr)
    return json.loads(proc.stdout)


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not available")
def test_equal_idless_live_calls_get_distinct_occurrences_via_producer(tmp_path):
    """#7040 round 10 finding 2, driven through the PRODUCER.

    ``upsertLiveToolCall()`` looked a record up by signature/name *before* the
    occurrence was minted, so a second equal ID-less start -- or a second
    completion-only event -- reused the first record and never received its own
    occurrence/tid.

    The round-9 lifecycle test called ``_liveToolTid(..., 0/1)`` directly and
    hand-assembled the later stages, so it could not see this: the collapse
    happens in the producer, before any tid is computed. This test drives
    ``upsertLiveToolCall`` itself -- the outermost function the two SSE handlers
    (``tool`` / ``tool_complete``) actually call -- and asserts on the records
    the producer produced.
    """
    out = _run(tmp_path)

    # Two equal ID-less starts must be two records with distinct identities.
    assert out["startOnly_count"] == 2, (
        "two equal ID-less starts collapsed into %d record(s)" % out["startOnly_count"]
    )
    assert out["startOnly_occurrences"] == [0, 1], out["startOnly_occurrences"]
    assert len(set(out["startOnly_tids"])) == 2, (
        "aliased tids across two distinct calls: %r" % (out["startOnly_tids"],)
    )

    # Their completions must pair one-to-one, in order -- not both onto record 0.
    assert out["afterComplete_count"] == 2, out["afterComplete_count"]
    assert out["afterComplete_done"] == [True, True], out["afterComplete_done"]
    assert out["afterComplete_snippets"] == ["first-result", "second-result"], (
        "completions did not pair with starts in arrival order: %r"
        % (out["afterComplete_snippets"],)
    )

    # Completion-only events (no preceding start) must also not collapse.
    assert out["completeOnly_count"] == 2, (
        "two completion-only events collapsed into %d record(s)"
        % out["completeOnly_count"]
    )
    assert out["completeOnly_occurrences"] == [0, 1], out["completeOnly_occurrences"]
    assert len(set(out["completeOnly_tids"])) == 2, out["completeOnly_tids"]
    assert out["completeOnly_snippets"] == ["c1", "c2"], out["completeOnly_snippets"]


ANCHOR_DRIVER = r"""
const fs = require('fs');
const msgSrc = fs.readFileSync(process.argv[2], 'utf8');
const uiSrc  = fs.readFileSync(process.argv[3], 'utf8');

function cut(src, name, kw) {
  const re = new RegExp((kw || 'function') + '\\s+' + name + '\\s*[\\(=]');
  const start = src.search(re);
  if (start < 0) throw new Error(name + ' not found');
  let cursor = src.indexOf('{', start) + 1;
  let depth = 1;
  while (depth && cursor < src.length) {
    if (src[cursor] === '{') depth++;
    else if (src[cursor] === '}') depth--;
    cursor++;
  }
  return src.slice(start, cursor);
}
function line(src, re, label) {
  const m = src.match(re);
  if (!m) throw new Error(label + ' not found');
  return m[0];
}

// Real projector chain from ui.js.
const uiParts = [
  line(uiSrc, /^.*_TRANSCRIPT_DISPLAY_OPAQUE_RUN_LIMIT\s*=.*$/m, 'RUN_LIMIT'),
  line(uiSrc, /^.*_TRANSCRIPT_DISPLAY_OPAQUE_HEAD\s*=.*$/m, 'HEAD'),
  line(uiSrc, /^.*_TRANSCRIPT_DISPLAY_NOTICE\s*=.*$/m, 'NOTICE'),
  line(uiSrc, /^.*_TRANSCRIPT_DISPLAY_OPAQUE_DATA_RE\s*=.*$/m, 'DATA_RE'),
  line(uiSrc, /^.*_candidateScanRe\s*=.*$/m, 'candidateScanRe'),
  cut(uiSrc, '_isB64Code'),
  cut(uiSrc, '_scanBase64Gap'),
  cut(uiSrc, '_opaqueRunSpans'),
  cut(uiSrc, '_boundOpaqueRuns'),
  cut(uiSrc, '_createIncrementalOpaqueRunCache'),
  cut(uiSrc, '_projectTranscriptTextForDisplay'),
];

// Real anchor renderer from messages.js.
const msgParts = [
  line(msgSrc, /const _anchorProseSmdCache\s*=\s*new Map\(\);/, '_anchorProseSmdCache'),
  cut(msgSrc, '_finalizeAnchorProseIncrementalNode'),
  cut(msgSrc, '_anchorProseIncrementalNode'),
];

const stubs = `
// --- minimal DOM/smd environment ---
function mkEl(){
  return { className:'', classList:{toggle(){},add(){},remove(){}}, dataset:{},
           children:[], appendChild(c){this.children.push(c);},
           setAttribute(){}, querySelector(){ return this._body || null; } };
}
const document = { createElement(){ const e=mkEl(); e._body=mkEl(); return e; } };
const window = {
  smd: { parser(){ return {}; }, parser_write(){}, parser_end(){} },
};
function _safeSmdRenderer(){ return {}; }
function _smdRendererWithoutUnderscoreEmphasis(r){ return r; }
function _smdBindParserIdentity(){}
function _shouldUseLiveProseFade(){ return false; }
function _streamFadeRenderer(){ return {}; }
function _smdMediaTailFlush(){}
function _smdMediaTailClear(){}
function _smdClearParserIdentity(){}
function _sanitizeSmdLinks(){}
function enhanceMarkdownTables(){}
function _streamFadeMuteRenderedPrefix(){}
// --- instrumentation counters ---
const COUNT = { project: 0, scanBytes: 0 };
`;

// Wrap the two functions whose input size IS the work, after they are defined.
const instrument = `
const __proj = _projectTranscriptTextForDisplay;
_projectTranscriptTextForDisplay = function(t, o){ COUNT.project++; return __proj(t, o); };
const __bound = _boundOpaqueRuns;
_boundOpaqueRuns = function(raw, streaming){ COUNT.scanBytes += String(raw||'').length; return __bound(raw, streaming); };
const __spans = _opaqueRunSpans;
_opaqueRunSpans = function(raw){ COUNT.scanBytes += String(raw||'').length; return __spans(raw); };
`;

const mod = stubs + uiParts.join('\n') + '\n' + msgParts.join('\n') + '\n' + instrument + `
module.exports = { _anchorProseIncrementalNode, COUNT };
`;
const path = process.argv[4];
fs.writeFileSync(path, mod);
const M = require(path);

// Drive the ANCHOR renderer the way a live stream does: one repaint per chunk,
// text growing monotonically. Plain prose (no opaque runs) is the common case.
const CHUNK = 'lorem ipsum dolor sit amet consectetur adipiscing elit sed do. ';
const N = 120;
let text = '';
for (let i = 0; i < N; i++) {
  text += CHUNK;
  M._anchorProseIncrementalNode('anchor-key-1', text, {});
}
const finalLen = text.length;
console.log(JSON.stringify({
  repaints: N,
  finalLen,
  projectCalls: M.COUNT.project,
  scanBytes: M.COUNT.scanBytes,
}));
"""

def _run_anchor(tmp_path):
    driver = tmp_path / "anchor_driver.js"
    driver.write_text(ANCHOR_DRIVER)
    proc = subprocess.run(
        [NODE, str(driver), str(MESSAGES_JS), str(UI_JS), str(tmp_path / "anchor_mod.js")],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError("node driver failed:\n" + proc.stdout + proc.stderr)
    return json.loads(proc.stdout)


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not available")
def test_anchor_repaints_do_not_reproject_full_text(tmp_path):
    """#7040 round 10 finding 1, driven through the ANCHOR renderer.

    Round 9 gave the main live path an owner-scoped incremental projection
    cache, but ``_scheduleRender()`` also calls ``_upsertAnchorProcessProse()``
    on every repaint, which reaches ``_anchorProseIncrementalNode`` -- and that
    projected the FULL accumulated text with no ``liveCache``, then projected
    the result a second time for ``dataset.rawText``. So a long live payload
    still cost O(n) per update, O(n^2) cumulatively.

    The round-9 perf test drove ``_projectTranscriptTextForDisplay`` directly,
    so it could not see this composed cost. This test drives the Anchor renderer
    itself and accounts for the work two ways:

    * exactly one projector call per repaint (the second, ``dataset.rawText``
      projection is gone), and
    * total bytes handed to the underlying scanners stays near-linear in the
      final text length rather than quadratic in the repaint count.
    """
    out = _run_anchor(tmp_path)

    # One projection per repaint -- not two.
    assert out["projectCalls"] == out["repaints"], (
        "expected 1 projector call per repaint, got %d for %d repaints"
        % (out["projectCalls"], out["repaints"])
    )

    # Work accounting: a full re-scan every repaint is ~ n*final/2 bytes.
    quadratic = out["finalLen"] * out["repaints"] / 2.0
    assert out["scanBytes"] < quadratic / 10.0, (
        "anchor repaints scanned %d bytes; a full re-scan per repaint is ~%d, "
        "so this is still quadratic" % (out["scanBytes"], quadratic)
    )
