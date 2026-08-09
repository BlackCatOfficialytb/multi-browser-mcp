"""Read and parse config.kdl for the BrowserMCP server.

KDL (Knot Description Language) config parser — minimal but correct for the
subset used in config.kdl: nested blocks, key/value pairs, arrays, strings,
numbers, booleans, and comments.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    "server": {"host": "127.0.0.1", "port": 8000, "transport": "sse"},
    "credential": {"method": "env", "env_file": ".env", "api_key": "", "base_url": "", "model": ""},
    "proxy": {"enabled": False, "file": "proxies.txt"},
    "camoufox_browser": {
        "enabled": True,
        "headless": False,
        "geoip": False,
        "humanize": True,
        "locale": "en-US",
        "args": [],
        "options": {},
    },
    "drissionpage_browser": {
        "enabled": False,
        "headless": True,
        "browser_path": "",
        "user_data_dir": "",
        "local_port": "",
        "args": [],
    },
    "browser_use": {"enabled": True, "headless": False, "model": "gpt-4o"},
}


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    transport: str = "sse"


@dataclass
class CredentialConfig:
    method: str = "env"  # env | dotenv | config
    env_file: str = ".env"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@dataclass
class ProxyConfig:
    enabled: bool = False
    file: str = "proxies.txt"


@dataclass
class CamoufoxConfig:
    enabled: bool = True
    headless: bool = False
    geoip: bool = False
    humanize: bool = True
    locale: str = "en-US"
    args: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DrissionPageConfig:
    enabled: bool = False
    headless: bool = True
    browser_path: str = ""
    user_data_dir: str = ""
    local_port: str = ""
    args: list[str] = field(default_factory=list)


@dataclass
class BrowserUseConfig:
    enabled: bool = True
    headless: bool = False
    model: str = "gpt-4o"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    credential: CredentialConfig = field(default_factory=CredentialConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    camoufox_browser: CamoufoxConfig = field(default_factory=CamoufoxConfig)
    drissionpage_browser: DrissionPageConfig = field(default_factory=DrissionPageConfig)
    browser_use: BrowserUseConfig = field(default_factory=BrowserUseConfig)


# --- KDL tokenizer / parser ---------------------------------------------------

_TOK_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'          # quoted string
    r'|#[^\n]*'                   # line comment (#)
    r'|//[^\n]*'                  # line comment (//)
    r'|/\*.*?\*/'                 # block comment /* */
    r'|[{}[\]]'                   # delimiters
    r'|true|false|null'           # literals
    r'|[0-9]+\.[0-9]+'            # float
    r'|0x[0-9a-fA-F]+'            # hex int
    r'|[+-]?[0-9]+'               # decimal int
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
        return raw[1:-1]
    try:
        return int(raw, 0)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw  # bare identifier


def _parse(tokens: list[str], pos: int, parent: dict[str, Any]) -> int:
    """Recursive parser.  Parses one level of `key value` / `key [ .. ]` /
    `node { … }` entries.  Returns the new position."""
    n = len(tokens)
    while pos < n:
        tok = tokens[pos]
        if tok in ("}", "]"):
            return pos + 1
        if tok == "{":
            return _parse(tokens, pos + 1, parent)
        if tok == "[":
            return _parse_list(tokens, pos + 1, parent)

        nxt = tokens[pos + 1] if pos + 1 < n else None

        if nxt == "[":
            parent[tok] = []
            pos = _parse_list(tokens, pos + 2, parent[tok])
        elif nxt == "{":
            child: dict[str, Any] = {}
            parent[tok] = child
            pos = _parse(tokens, pos + 2, child)
        elif nxt is not None:
            parent[tok] = _parse_value(nxt)
            pos += 2
        else:
            pos += 1
    return pos


def _parse_list(tokens: list[str], pos: int, out: list[Any]) -> int:
    """Parse array items until `]`.  `out` is the target list."""
    n = len(tokens)
    while pos < n:
        tok = tokens[pos]
        if tok in ("}", "]"):
            return pos + 1
        nxt = tokens[pos + 1] if pos + 1 < n else None

        if tok == "[":
            sub: list[Any] = []
            pos = _parse_list(tokens, pos + 1, sub)
            out.append(sub)
        elif tok == "{":
            child: dict[str, Any] = {}
            pos = _parse(tokens, pos + 1, child)
            out.append(child)
        elif nxt == "[":
            sub = []
            pos = _parse_list(tokens, pos + 2, sub)
            out.append({tok: sub})
        elif nxt == "{":
            child = {}
            pos = _parse(tokens, pos + 2, child)
            out.append({tok: child})
        elif nxt == "]":
            out.append(_parse_value(tok))
            return pos + 2  # value then closing ]
        elif nxt is not None:
            out.append(_parse_value(tok))
            pos += 2
        else:
            out.append(_parse_value(tok))
            pos += 1
    return pos


def _parse_kdl(text: str) -> dict[str, Any]:
    tokens = _tokenize(text)
    root: dict[str, Any] = {}
    _parse(tokens, 0, root)
    return root


# --- public API ---------------------------------------------------------------

def load_config(path: str | os.PathLike | None = None) -> Config:
    base = Path(__file__).resolve().parent
    kdl_path = Path(path) if path else (base / "config.kdl")

    if not kdl_path.exists():
        return Config()

    parsed = _parse_kdl(kdl_path.read_text(encoding="utf-8"))

    def section(name: str, cls) -> Any:
        defaults = DEFAULTS.get(name, {})
        merged = {**defaults, **(parsed.get(name) or {})}
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in merged.items() if k in fields}
        return cls(**clean)

    return Config(
        server=section("server", ServerConfig),
        credential=section("credential", CredentialConfig),
        proxy=section("proxy", ProxyConfig),
        camoufox_browser=section("camoufox_browser", CamoufoxConfig),
        drissionpage_browser=section("drissionpage_browser", DrissionPageConfig),
        browser_use=section("browser_use", BrowserUseConfig),
    )


def load_env_file(path: str) -> None:
    """Minimal .env loader: sets KEY=VALUE pairs into os.environ."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


def load_llm_credentials(cfg: Config) -> tuple[str, str, str]:
    """Resolve (base_url, api_key, model) per the credential input method.

    Returns empty strings for unset values; callers decide how to fail."""
    cred = cfg.credential
    if cred.method == "config":
        return cred.base_url, cred.api_key, cred.model
    if cred.method == "dotenv":
        load_env_file(cred.env_file)
    base_url = os.environ.get("NINEROUTER_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    api_key = os.environ.get("NINEROUTER_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("BROWSER_USE_MODEL") or os.environ.get("NINEROUTER_MODEL") or cred.model
    return base_url, api_key, model


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
            "credential": {"method": cfg.credential.method, "env_file": cfg.credential.env_file},
            "proxy": {"enabled": cfg.proxy.enabled, "file": cfg.proxy.file},
            "camoufox_browser": {
                "enabled": cfg.camoufox_browser.enabled,
                "headless": cfg.camoufox_browser.headless,
                "geoip": cfg.camoufox_browser.geoip,
                "humanize": cfg.camoufox_browser.humanize,
                "locale": cfg.camoufox_browser.locale,
                "args": cfg.camoufox_browser.args,
                "options": cfg.camoufox_browser.options,
            },
            "drissionpage_browser": {
                "enabled": cfg.drissionpage_browser.enabled,
                "headless": cfg.drissionpage_browser.headless,
                "browser_path": cfg.drissionpage_browser.browser_path,
                "user_data_dir": cfg.drissionpage_browser.user_data_dir,
                "local_port": cfg.drissionpage_browser.local_port,
                "args": cfg.drissionpage_browser.args,
            },
            "browser_use": {
                "enabled": cfg.browser_use.enabled,
                "headless": cfg.browser_use.headless,
                "model": cfg.browser_use.model,
            },
        },
        indent=2,
    ))
