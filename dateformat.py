"""Cross-platform date formatting.

`%-d` and `%-I` (no zero padding) are a glibc extension: they work on Linux
and macOS and raise ValueError on Windows, which uses `%#d` / `%#I`. Rather
than pick one and break the other platform, format with the padded codes and
strip the padding ourselves -- correct everywhere, no platform branching.
"""

from __future__ import annotations

from datetime import datetime


def fmt(dt: datetime, pattern: str) -> str:
    """strftime with `%-d` / `%-I` support on every platform."""
    # Substitute the unpadded directives with placeholders, format normally,
    # then strip the leading zero from the placeholder values.
    # Sentinels must survive strftime untouched: NUL truncates the string on
    # some platforms, so use private-use-area characters instead.
    tokens = {"%-d": ("\ue000", dt.day),
              "%-I": ("\ue001", dt.hour % 12 or 12),
              "%-m": ("\ue002", dt.month),
              "%-H": ("\ue003", dt.hour)}
    pat = pattern
    for directive, (sentinel, _) in tokens.items():
        pat = pat.replace(directive, sentinel)
    out = dt.strftime(pat)
    for sentinel, value in tokens.values():
        out = out.replace(sentinel, str(value))
    return out
