"""Read and parse config.kdl for the BrowserMCP server.

KDL (Knot Description Language) config parser — minimal but correct for the
subset used in config.kdl: nested blocks, key/value pairs, strings, numbers,
booleans, and comments.
"""

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    "server": {"host": "127.0.0.1", "port": 8000, "transport": "sse"},
    "proxy": {"enabled": False, "file": "proxies.txt"},
    "browser": {
        "engine": "camoufox",
        "drission_enabled": False,
        "drission_headless": False,
    },
    "browser_use": {
        "enabled": True,
        "headless": True,
        "model": "gpt-4o",
    },
}


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    transport: str = "sse"


@dataclass
class ProxyConfig:
    enabled: bool = False
    file: str = "proxies.txt"


@dataclass
class BrowserConfig:
    engine: str = "camoufox"
    drission_enabled: bool = False
    drission_headless: bool = False


@dataclass
class BrowserUseConfig:
    enabled: bool = True
    headless: bool = True
    model: str = "gpt-4o"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    browser_use: BrowserUseConfig = field(default_factory=BrowserUseConfig)


# --- KDL tokenizer / parser ---------------------------------------------------

_TOK_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'     # quoted string
    r'|#[^\n]*'              # line comment (#)
    r'|//[^\n]*'             # line comment (//)
    r'|/\*.*?\*/'            # block comment /* */
    r'|[{}]'                 # block delimiters
    r'|true|false|null'      # literals
    r'|[0-9]+\.[0-9]+'      # float
    r'|0x[0-9a-fA-F]+'      # hex int
    r'|[0-9]+'              # decimal int
    r'|[a-zA-Z_][a-zA-Z0-9_\-./]*'  # idents with dashes / paths / urls
)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _TOK_RE.finditer(text):
        tok = m.group(0)
        if tok.startswith("#") or tok.startswith("/"):
            continue
        tokens.append(tok)
    return tokens


def _parse_value(raw: str) -> Any:
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "null":
        return None
    if raw.startswith('"'):
        # strip quotes, then unescape
        inner = raw[1:-1]
        return inner.encode().decode("unicode_escape")
    try:
        return int(raw, 0)  # handles decimal + hex 0x
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw  # bare identifier


def _parse(tokens: list[str], pos: int, parent: dict[str, Any]) -> int:
    """Recursive parser.  Each call parses one *level* of `key value` pairs
    and nested `node { … }` blocks.  Returns the new position."""
    n = len(tokens)
    while pos < n:
        tok = tokens[pos]
        if tok == "}":
            return pos + 1
        if tok == "{":
            # anonymous block — unlikely in our format
            return _parse(tokens, pos + 1, parent)

        # `tok` is the node name (or property key).
        # Look ahead: if next token is `{`, it's a nested block (node with children).
        if pos + 1 < n and tokens[pos + 1] == "{":
            child: dict[str, Any] = {}
            parent[tok] = child
            pos = _parse(tokens, pos + 2, child)
            continue

        # Otherwise it's a property: `key value`
        if pos + 1 < n:
            val = _parse_value(tokens[pos + 1])
            parent[tok] = val
            pos += 2
        else:
            pos += 1
    return pos


def _parse_kdl(text: str) -> dict[str, Any]:
    tokens = _tokenize(text)
    root: dict[str, Any] = {}
    _parse(tokens, 0, root)
    return root


# --- public API ---------------------------------------------------------------

def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load config.kdl from *path* (default: ``config.kdl`` in the same
    directory as this file, or PWD)."""
    base = Path(__file__).resolve().parent
    kdl_path = Path(path) if path else (base / "config.kdl")

    if not kdl_path.exists():
        return Config()

    raw = kdl_path.read_text(encoding="utf-8")
    parsed = _parse_kdl(raw)

    def section(name: str, dataclass_cls) -> Any:
        defaults = DEFAULTS.get(name, {})
        user_vals = parsed.get(name, {})
        merged = {**defaults, **user_vals}
        try:
            return dataclass_cls(**merged)
        except TypeError:
            # ignore unexpected keys
            fields = {f.name for f in dataclass_cls.__dataclass_fields__.values()}
            clean = {k: v for k, v in merged.items() if k in fields}
            return dataclass_cls(**clean)

    return Config(
        server=section("server", ServerConfig),
        proxy=section("proxy", ProxyConfig),
        browser=section("browser", BrowserConfig),
        browser_use=section("browser_use", BrowserUseConfig),
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


if __name__ == "__main__":
    import json

    cfg = load_config()
    print(json.dumps(
        {
            "server": {"host": cfg.server.host, "port": cfg.server.port, "transport": cfg.server.transport},
            "proxy": {"enabled": cfg.proxy.enabled, "file": cfg.proxy.file},
            "browser": {
                "engine": cfg.browser.engine,
                "drission_enabled": cfg.browser.drission_enabled,
                "drission_headless": cfg.browser.drission_headless,
            },
            "browser_use": {
                "enabled": cfg.browser_use.enabled,
                "headless": cfg.browser_use.headless,
                "model": cfg.browser_use.model,
            },
        },
        indent=2,
    ))
