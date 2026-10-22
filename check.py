"""Check the repository before anything is published, in one command.

    python3 check.py

- the firmware file matches its checksum, and every license it carries is
  in licenses/;
- the tests pass;
- the prose keeps the house style: no em dash, no semicolon;
- nothing tracked carries a personal address or a path on somebody's
  machine.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
LICENSES = ["micropython", "micropython-lib", "pico-sdk", "tinyusb", "btstack", "btstack-raspberry-pi",
            "cyw43-driver", "cyw43-driver-raspberry-pi", "micro-ecc", "lwip", "mbedtls"]
PUBLIC = [(r"(?i)[\w.+-]+@gmail\.com", "a personal address"), (r"(?i)/home/[a-z]", "a path on somebody's machine")]


def tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], cwd=HERE, capture_output=True, text=True, check=True).stdout.split()


def main() -> int:
    problems = []
    for line in (HERE / "firmware" / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        if hashlib.sha256((HERE / "firmware" / name).read_bytes()).hexdigest() != digest:
            problems.append(f"firmware/{name} does not match its checksum")
    for name in LICENSES:
        if not (HERE / "licenses" / f"{name}.txt").exists():
            problems.append(f"licenses/{name}.txt is missing")
    tests = subprocess.run([sys.executable, str(HERE / "tests" / "run.py")], capture_output=True, text=True)
    if tests.returncode != 0:
        problems.append("the tests failed:\n" + tests.stdout[-2000:])
    for name in tracked():
        path = HERE / name
        if name.startswith("patches/") or name.startswith("licenses/") or name == "check.py":
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if path.suffix == ".md":
            prose = re.sub(r"```.*?```", "", text, flags=re.S)
            prose = re.sub(r"`[^`]*`", "", prose)
            prose = re.sub(r"^\|.*$", "", prose, flags=re.M)
            if "—" in prose:
                problems.append(f"{name}: an em dash")
            if ";" in prose:
                problems.append(f"{name}: a semicolon in the prose")
        for pattern, why in PUBLIC:
            for m in re.finditer(pattern, text):
                problems.append(f"{name}: names {m.group(0)}, which is {why}")
    if problems:
        print(f"{len(problems)} problems:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("-" * 52)
    print("the firmware matches its checksum and carries its licenses, and the tests pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
