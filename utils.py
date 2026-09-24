import json
import logging

logger = logging.getLogger("elevplads_scraper")


def extract_json_payload(text_content: str) -> dict:
    """Extract and parse JSON object from LLM response text, stripping markdown codeblocks if present."""
    text_content = text_content.strip()
    if text_content.startswith("```"):
        lines = text_content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text_content = "\n".join(lines).strip()
    start = text_content.find("{")
    end = text_content.rfind("}")
    if start != -1 and end != -1:
        text_content = text_content[start:end + 1]
    return json.loads(text_content, strict=False)
