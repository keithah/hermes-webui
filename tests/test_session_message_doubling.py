"""Regression tests for exponential session-message duplication.

An interrupted/incomplete turn persists reasoning-only assistant rows (empty
content, no tool calls, no ``_partial`` flag). ``_message_identity()`` used to
return ``None`` for those rows, so the ``seen`` dedup in
``_merge_display_messages_after_agent_result`` could not track them. The
assistant/tool-only recovery branch does not apply ``_strip_replayed_prefix``,
so each such writeback re-appended every row already present and the count
DOUBLED per turn.

Observed in production: one sidecar reached 4,197,270 rows from 2,989 distinct
messages (6.4 GB), with per-message multiplicities of exactly 2^0..2^21.
"""

import api.streaming as S


def _reasoning_row(text, *, timestamp=1786763583.780455):
    """A reasoning-only assistant row exactly as an interrupted turn persists it."""
    return {
        'role': 'assistant',
        'content': '',
        'reasoning': text,
        'reasoning_content': text,
        'finish_reason': 'incomplete',
        'id': 17,
        'timestamp': timestamp,
        '_db_persisted': True,
    }


def _reasoning_rows(messages):
    return [
        m for m in messages
        if isinstance(m, dict) and m.get('role') == 'assistant' and m.get('content') == ''
    ]


def test_reasoning_only_row_has_stable_identity():
    """Without an identity the merge dedup cannot track the row at all."""
    row = _reasoning_row('**Designing Envoy HTTP provider methods**')
    identity = S._message_identity(row)
    assert identity is not None, (
        'reasoning-only rows must be trackable by the merge dedup; '
        'None identity is what caused exponential accumulation'
    )
    # Stable across equal rows, so duplicates collapse.
    assert identity == S._message_identity(_reasoning_row(
        '**Designing Envoy HTTP provider methods**'
    ))


def test_distinct_reasoning_rows_keep_distinct_identities():
    """The dedup key must not collapse genuinely different reasoning rows."""
    a = S._message_identity(_reasoning_row('**Planning patch for imports**'))
    b = S._message_identity(_reasoning_row('**Compiling tests before deployment**'))
    assert a != b

    # Long rows sharing a 200-char prefix must still be distinguished: a
    # truncated key would silently merge two different rows into one.
    prefix = 'x' * 250
    long_a = S._message_identity(_reasoning_row(prefix + 'ALPHA'))
    long_b = S._message_identity(_reasoning_row(prefix + 'BETA'))
    assert long_a != long_b


def test_interrupted_turn_recovery_does_not_double_transcript():
    """Repeated assistant/tool-only recovery writebacks must not grow the transcript.

    Before the fix this doubled every pass (1, 2, 4, ... 4096 by pass 12),
    reproducing the exact powers-of-two multiplicities seen in the wild.
    """
    display = [
        {'role': 'user', 'content': 'kick off the work', 'timestamp': 1.0},
        _reasoning_row('**Designing Envoy HTTP provider methods**'),
    ]
    context = list(display)

    for _ in range(12):
        # An interrupted turn's recovery returns an assistant/tool-only history.
        result_messages = [m for m in display if m.get('role') == 'assistant']
        display = S._merge_display_messages_after_agent_result(
            display, context, result_messages, 'kick off the work',
        )

    assert len(_reasoning_rows(display)) == 1, (
        f'reasoning rows accumulated: {len(_reasoning_rows(display))} copies '
        f'(exponential duplication regression)'
    )
    assert len(display) <= 4, f'transcript grew unexpectedly: {len(display)} rows'


def test_normal_turns_still_append_their_delta():
    """The dedup must not suppress ordinary new turns."""
    display = [{'role': 'user', 'content': 'q1', 'timestamp': 1.0}]
    context = list(display)
    user = {'role': 'user', 'content': 'q2', 'timestamp': 2.0}
    assistant = {'role': 'assistant', 'content': 'a2', 'timestamp': 3.0}

    merged = S._merge_display_messages_after_agent_result(
        display, context, list(context) + [user, assistant], 'q2',
    )
    contents = [m.get('content') for m in merged if isinstance(m, dict)]
    assert 'q2' in contents and 'a2' in contents
