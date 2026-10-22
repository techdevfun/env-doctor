"""Core audit logic for env-doctor. Standard library only."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

PLACEHOLDER_WORDS = (
    "changeme",
    "change-me",
    "your-key",
    "your_key",
    "your-api-key",
    "your_api_key",
    "replace-me",
    "replace_me",
    "todo",
    "example",
    "xxx",
    "123456",
    "password123",
)

KNOWN_SECRET_PREFIXES = ("ghp_", "gho_", "github_pat_", "sk-", "AKIA", "xoxb-", "xoxp-", "glpat-")

ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def looks_like_real_secret(key: str, value: str) -> bool:
    if value.startswith(KNOWN_SECRET_PREFIXES):
        return True
    if len(value) >= 24 and shannon_entropy(value) >= 4.4:
        # Long, high-entropy values are rarely placeholders.
        # Require mixed character classes to cut false positives on URLs.
        classes = sum([
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(not c.isalnum() for c in value),
        ])
        return classes >= 3
    return False


def is_placeholder(value: str) -> bool:
    low = value.strip().lower().strip('"').strip("'")
    if low == "":
        return True
    return any(w in low for w in PLACEHOLDER_WORDS)


def parse_env_file(path: Path) -> tuple[dict[str, str], list[dict]]:
    """Parse a .env-style file. Returns (values, issues)."""
    values: dict[str, str] = {}
    issues: list[dict] = []
    if not path.exists():
        return values, [{"severity": "error", "code": "missing-file",
                         "message": f"File not found: {path}", "key": None}]
    seen: Counter = Counter()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            issues.append({"severity": "warning", "code": "invalid-line",
                           "message": f"Line {lineno}: no '=' found, skipped: {raw[:80]}", "key": None})
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not ENV_KEY_RE.match(key):
            issues.append({"severity": "warning", "code": "invalid-key",
                           "message": f"Line {lineno}: invalid key name: {key!r}", "key": key})
            continue
        seen[key] += 1
        if seen[key] > 1:
            issues.append({"severity": "error", "code": "duplicate-key",
                           "message": f"Duplicate key {key!r} (line {lineno})", "key": key})
        values[key] = value
    return values, issues


def find_referenced_vars(root: Path) -> set[str]:
    """Scan code for env var references: getenv('X'), process.env.X, $X, ${X}."""
    patterns = [
        re.compile(r"""getenv\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""),
        # Both os.environ["X"] and os.environ.get("X") forms.
        re.compile(r"""os\.environ(?:\[\s*["']|\.get\(\s*["'])([A-Za-z_][A-Za-z0-9_]*)["']"""),
        re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
        re.compile(r"""\$\{([A-Za-z_][A-Za-z0-9_]*)\}"""),
    ]
    found: set[str] = set()
    exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".rb", ".go", ".rs", ".java"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in exts:
            continue
        # Skip common vendored / generated dirs.
        if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"} for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            found.update(pat.findall(text))
    return found


def audit(env_path: Path, example_path: Path | None = None, scan_root: Path | None = None) -> dict:
    env_values, issues = parse_env_file(env_path)
    example_values: dict[str, str] = {}
    if example_path is not None:
        example_values, ex_issues = parse_env_file(example_path)
        # Missing-file for the example is a warning, not an error: many
        # small projects do not ship one yet.
        for it in ex_issues:
            if it["code"] == "missing-file":
                issues.append({"severity": "warning", "code": "missing-example",
                               "message": f"Example file not found: {example_path}. "
                                          "Add one so new devs know which vars to set.", "key": None})
            else:
                issues.append(it)
        for key in sorted(set(example_values) - set(env_values)):
            issues.append({"severity": "error", "code": "missing-in-env",
                           "message": f"{key!r} is in {example_path.name} but missing in {env_path.name}", "key": key})
        for key in sorted(set(env_values) - set(example_values)):
            issues.append({"severity": "warning", "code": "missing-in-example",
                           "message": f"{key!r} is in {env_path.name} but missing in {example_path.name}. "
                                      "Add it so teammates know it exists.", "key": key})

    for key, value in env_values.items():
        if value == "":
            issues.append({"severity": "warning", "code": "empty-value",
                           "message": f"{key!r} is empty", "key": key})
        elif is_placeholder(value):
            issues.append({"severity": "warning", "code": "placeholder-value",
                           "message": f"{key!r} still looks like a placeholder value", "key": key})
        if looks_like_real_secret(key, value):
            issues.append({"severity": "warning", "code": "possible-real-secret",
                           "message": f"{key!r} looks like a real secret (high entropy / known prefix). "
                                      "Make sure this file is gitignored and never committed.", "key": key})

    if scan_root is not None and scan_root.exists():
        referenced = find_referenced_vars(scan_root)
        # Only flag unused when we found at least one reference, otherwise
        # the scan root probably has no code (e.g. docs-only folder).
        if referenced:
            for key in sorted(set(env_values) - referenced):
                issues.append({"severity": "warning", "code": "possibly-unused",
                               "message": f"{key!r} is defined but not referenced in scanned code. "
                                          "Remove it if it is really dead.", "key": key})

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    return {
        "env_file": str(env_path),
        "example_file": str(example_path) if example_path else None,
        "keys": sorted(env_values),
        "errors": errors,
        "warnings": warnings,
        "issues": sorted(issues, key=lambda i: (i["severity"] != "error", i["code"], str(i["key"]))),
        "ok": errors == 0,
    }
