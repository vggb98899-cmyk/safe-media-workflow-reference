from __future__ import annotations

import re
import sys
from pathlib import Path


EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----" + r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE " + r"KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "cloud_key": re.compile(r"\b(?:AKIA|LTAI)[A-Z0-9]{16,}\b"),
    "generic_secret_assignment": re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"\s]{8,}"),
}
FORBIDDEN_FILES = {".env", "state.db", "runtime.db"}


def public_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    for path in public_files(root):
        relative = path.relative_to(root)
        if path.name in FORBIDDEN_FILES or path.suffix.lower() in {".db", ".sqlite", ".log"}:
            findings.append(f"forbidden runtime file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"unexpected binary file: {relative}")
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{name}: {relative}")
    if findings:
        print("SECURITY_SCAN=FAIL")
        print("\n".join(findings))
        return 1
    print("SECURITY_SCAN=PASS")
    print(f"PUBLIC_FILE_COUNT={len(public_files(root))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
