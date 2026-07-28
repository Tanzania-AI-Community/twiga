"""Response cleaning shared by the eval pipelines.

Twiga's WhatsApp-style responses carry conversational framing — greetings,
teaching tips, "would you like…" follow-ups — that isn't factual content and
should never be judged against the textbook. Stripping it before metric
scoring keeps lexical scores and claim extraction focused on the curricular
substance of the answer.
"""

import re

_GREETING_RE = re.compile(
    r"^\s*(?:Hello|Hi|Hey|Good\s+(?:morning|afternoon|evening)|Great\s+question|"
    r"Good\s+question|Welcome|Dear\s+[Tt]eacher)(?:\s+[Tt]eachers?)?[,!.]?\s*",
    re.IGNORECASE,
)
_TEACHING_TIP_RE = re.compile(
    r"\n?(?:💡\s*)?(?:Teaching\s+)?Tip[:\s][^\n]*",
    re.IGNORECASE,
)
_WOULD_YOU_RE = re.compile(
    r"\s*(?:Would you like|Do you want|Is there anything)[^.?!]*[.?!]",
    re.IGNORECASE,
)
_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL)


def clean_response(text: str) -> str:
    """Strip non-factual conversational framing from a model response."""
    text = _THINK_RE.sub("", text).strip()
    text = _GREETING_RE.sub("", text)
    text = _TEACHING_TIP_RE.sub("", text)
    text = _WOULD_YOU_RE.sub("", text)
    return text.strip()
