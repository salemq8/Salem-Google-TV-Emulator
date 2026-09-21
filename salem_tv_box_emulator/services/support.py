"""Local, sanitized support reports. No telemetry or automatic upload."""
import os
import re


def sanitize(text: str) -> str:
    text = re.sub(r'(?im)((?:authorization|cookie|set-cookie|password|passwd|token|api[_-]?key|secret)\s*[:=]\s*)([^\r\n]+)', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(https?://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)([?&](?:access_token|token|api_key|key|secret|password)=)[^&\s]+', r'\1[REDACTED]', text)
    home = os.environ.get("USERPROFILE", "")
    if home:
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.IGNORECASE)
    return text
