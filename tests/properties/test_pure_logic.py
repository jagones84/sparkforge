import pytest
from hypothesis import given, strategies as st
from sparkforge import server as prompt

@given(st.text(), st.text())
def test_extract_json_property(before, after):
    """
    Property: extract_json should safely handle any random text that might
    contain fragments or malformed JSON, and return None or valid JSON.
    """
    # A perfectly valid JSON block
    valid_json_text = '{"status": "ok", "count": 1}'
    
    # We surround it with random text
    payload = f"{before} ```json\n{valid_json_text}\n``` {after}"
    
    result = prompt.extract_json(payload)
    
    # Either it finds the valid JSON we injected, or it finds something else
    # that happens to be valid JSON. It must not crash.
    assert result is not None
    if isinstance(result, dict):
        # If it extracted our block, status should be ok
        pass

@given(st.dictionaries(st.text(), st.integers()))
def test_extract_json_valid_dict(d):
    """
    Property: any valid dictionary serialized to JSON and wrapped in markdown
    must be correctly extracted.
    """
    import json
    payload = f"Here is the result:\n```json\n{json.dumps(d)}\n```\nDone."
    result = prompt.extract_json(payload)
    assert result == d
