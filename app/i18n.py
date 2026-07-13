"""Lightweight two-language (en/de) i18n.

One shared catalog (static/i18n.json) drives both server-rendered Jinja text
and the dynamic JavaScript strings: templates use ``t('key')`` via a request
context processor, and ``/i18n.js`` serves the current language's strings to
the browser as ``window.T`` before common.js loads.

Language resolution: ``lang`` cookie if valid, else Accept-Language header
(anything starting with "de" -> German), else English.
"""

import json
from pathlib import Path

from fastapi import Request

SUPPORTED = ("en", "de")
DEFAULT = "en"

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "static" / "i18n.json"
_catalog: dict = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def reload_catalog() -> None:
    """Re-read the catalog from disk (used by tests / dev tweaking)."""
    global _catalog
    _catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def get_lang(request: Request) -> str:
    cookie = request.cookies.get("lang")
    if cookie in SUPPORTED:
        return cookie
    accept = (request.headers.get("accept-language") or "").lower()
    for part in accept.split(","):
        code = part.split(";")[0].strip()
        if code.startswith("de"):
            return "de"
        if code.startswith("en"):
            return "en"
    return DEFAULT


def make_t(lang: str):
    def t(key: str, **kwargs) -> str:
        entry = _catalog.get(key)
        if entry is None:
            return key
        text = entry.get(lang) or entry.get("en") or key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text

    return t


def strings_for(lang: str) -> dict:
    """Flat {key: text} map for one language (served to the browser)."""
    out = {}
    for key, entry in _catalog.items():
        out[key] = entry.get(lang) or entry.get("en") or key
    return out


def i18n_context(request: Request) -> dict:
    """Jinja context processor: every template gets `lang` and `t`."""
    lang = get_lang(request)
    return {"lang": lang, "t": make_t(lang)}
