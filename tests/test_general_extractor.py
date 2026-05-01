import pytest

from mempalace_code.general_extractor import extract_memories

EMOTIONAL_TEXT = (
    "I feel worried and lonely about this migration. "
    "I miss the old workflow and I am grateful for the help."
)


def test_default_excludes_emotional_memories():
    memories = extract_memories(EMOTIONAL_TEXT)

    assert memories == []


def test_include_emotional_opt_in_extracts_emotional_memories():
    memories = extract_memories(
        EMOTIONAL_TEXT,
        categories=["decision", "preference", "milestone", "problem", "emotional"],
    )

    assert [memory["memory_type"] for memory in memories] == ["emotional"]
    assert memories[0]["content"] == EMOTIONAL_TEXT


def test_disabled_category_disambiguation_does_not_emit_emotional():
    text = (
        "The bug was fixed and I love the result because the solution is stable. "
        "It worked after the patched retry path."
    )

    default_memories = extract_memories(text)
    opt_in_memories = extract_memories(
        text,
        categories=["decision", "preference", "milestone", "problem", "emotional"],
    )

    assert [memory["memory_type"] for memory in default_memories] == ["milestone"]
    assert [memory["memory_type"] for memory in opt_in_memories] == ["emotional"]


def test_unknown_category_raises_value_error():
    with pytest.raises(ValueError, match="Unknown extraction categories: imaginary"):
        extract_memories(
            "This is long enough to be considered for extraction.",
            categories=["imaginary"],
        )


def test_string_category_argument_raises_value_error():
    with pytest.raises(ValueError, match="categories must be an iterable of category names"):
        extract_memories(
            "I feel worried and lonely about this migration.",
            categories="emotional",
        )
