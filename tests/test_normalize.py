import json
import os
import tempfile
from unittest.mock import patch

from mempalace_code.normalize import normalize


def test_plain_text():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write("Hello world\nSecond line\n")
    f.close()
    result = normalize(f.name)
    assert "Hello world" in result
    os.unlink(f.name)


def test_claude_json():
    data = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "Hi" in result
    os.unlink(f.name)


def test_empty():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.close()
    result = normalize(f.name)
    assert result.strip() == ""
    os.unlink(f.name)


def test_json_normalize_spellcheck_enabled_calls_user_text_speller():
    data = [{"role": "user", "content": "pleese help"}, {"role": "assistant", "content": "Ok"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(f.name, spellcheck=True)
    finally:
        os.unlink(f.name)

    assert "> please help" in result
    assert "pleese help" not in result


def test_json_normalize_spellcheck_disabled_preserves_user_text():
    data = [{"role": "user", "content": "pleese help"}, {"role": "assistant", "content": "Ok"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(f.name, spellcheck=False)
    finally:
        os.unlink(f.name)

    assert "> pleese help" in result
    assert "> please help" not in result
