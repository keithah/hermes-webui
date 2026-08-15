"""Executable coverage for bounded, non-mutating transcript display text."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
UI_JS_PATH = REPO_ROOT / "static" / "ui.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

_DRIVER_SRC = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extractConst(name) {
  const match = src.match(new RegExp('const ' + name + '=([^\\n]*);'));
  if (!match) throw new Error(name + ' not found');
  globalThis[name] = eval('(' + match[1] + ')');
}

function extractFunc(name) {
  const start = src.search(new RegExp('function\\s+' + name + '\\s*\\('));
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

extractConst('_DATA_IMAGE_RE');
extractConst('_DATA_IMAGE_SVG_RE');
extractConst('_DATA_IMAGE_MAX_LEN');
extractConst('_TRANSCRIPT_DISPLAY_OPAQUE_RUN_LIMIT');
extractConst('_TRANSCRIPT_DISPLAY_NOTICE');
eval(extractFunc('_isSafeDataImageUri'));
eval(extractFunc('_projectTranscriptTextForDisplay'));

let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const payload = JSON.parse(input);
  const source = payload.value;
  const display = _projectTranscriptTextForDisplay(source, payload.options || {});
  process.stdout.write(JSON.stringify({source, display}));
});
"""


@pytest.fixture(scope="module")
def driver_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("transcript_projection") / "driver.js"
    path.write_text(_DRIVER_SRC, encoding="utf-8")
    return str(path)


def _project(driver_path: str, value: str, *, surface: str = "message") -> dict[str, str]:
    assert NODE is not None
    result = subprocess.run(
        [NODE, driver_path, str(UI_JS_PATH)],
        input=json.dumps({"value": value, "options": {"surface": surface}}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def test_opaque_data_payload_is_bounded_without_mutating_source(driver_path: str) -> None:
    payload = "prefix data:application/octet-stream;base64," + ("A" * 200_000)

    result = _project(driver_path, payload, surface="tool")

    assert result["source"] == payload
    assert len(result["display"]) < 70_000
    assert "opaque payload abbreviated for display" in result["display"]


def test_long_unbroken_base64_run_is_bounded(driver_path: str) -> None:
    payload = '{"screenshot":"' + ("A" * 200_000) + '"}'

    result = _project(driver_path, payload, surface="tool")

    assert result["source"] == payload
    assert len(result["display"]) < 70_000
    assert "opaque payload abbreviated for display" in result["display"]


def test_ordinary_long_prose_is_unchanged(driver_path: str) -> None:
    prose = "A normal paragraph with normal wrapping. " * 5_000

    result = _project(driver_path, prose, surface="assistant")

    assert result == {"source": prose, "display": prose}


def test_supported_data_image_is_left_for_media_renderer(driver_path: str) -> None:
    image = "data:image/png;base64,iVBORw0KGgo="

    result = _project(driver_path, f"![screenshot]({image})", surface="assistant")

    assert result["display"] == f"![screenshot]({image})"


def test_repeated_projection_is_deterministic(driver_path: str) -> None:
    payload = "data:application/octet-stream;base64," + ("B" * 200_000)

    first = _project(driver_path, payload, surface="reasoning")
    second = _project(driver_path, payload, surface="reasoning")

    assert first == second
    assert first["source"] == payload
