"""Regression tests for small pure helpers in agent/nodes.py.

Both bugs covered here only surfaced against the real Gemini API / a real
Docker container - not against any fake/mocked LLM or in-process MCP client -
so they're worth pinning down explicitly rather than relying on manual
end-to-end checks alone.
"""

from app.agent.nodes import extract_text


def test_extract_text_passes_through_plain_string():
    assert extract_text("hello") == "hello"


def test_extract_text_handles_gemini_style_content_blocks():
    # Actual shape observed from ChatGoogleGenerativeAI: a list of content
    # blocks with a "text" field and provider-specific "extras" metadata
    # (e.g. a grounding/thought signature) that must be ignored.
    content = [
        {
            "type": "text",
            "text": "Hello there!",
            "extras": {"signature": "EnEKb...=="},
        }
    ]
    assert extract_text(content) == "Hello there!"


def test_extract_text_joins_multiple_text_blocks():
    content = [
        {"type": "text", "text": "Part one. "},
        {"type": "text", "text": "Part two."},
    ]
    assert extract_text(content) == "Part one. Part two."


def test_extract_text_handles_list_of_plain_strings():
    assert extract_text(["a", "b"]) == "ab"
