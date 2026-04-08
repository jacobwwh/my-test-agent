"""Convenience script to run analyzer tests from the project root.

Usage:
    python test_analyzer.py                # list all tests and prompt for selection
    python test_analyzer.py -a             # run all tests directly
    python test_analyzer.py <extra args>   # pass extra args to pytest (e.g. -k "parse")
"""

import subprocess
import sys


TEST_DIR = "tests/test_analyzer/"


def _collect_tests() -> list[str]:
    """Use pytest --collect-only to get all test node IDs."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_DIR, "--collect-only", "-q"],
        capture_output=True, text=True,
    )
    tests = [
        line for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    return tests


def _interactive_select(tests: list[str]) -> list[str]:
    """Print a numbered menu and let the user pick tests to run."""
    print(f"\nFound {len(tests)} test(s):\n")
    for i, t in enumerate(tests, 1):
        print(f"  [{i:>2}] {t}")

    print(
        "\nEnter test numbers to run (comma-separated), "
        "a range (e.g. 1-5), 'a' for all, or 'q' to quit:"
    )
    choice = input("> ").strip()

    if choice.lower() == "q":
        return []
    if choice.lower() == "a":
        return tests

    selected: list[str] = []
    for part in choice.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            for idx in range(int(lo), int(hi) + 1):
                if 1 <= idx <= len(tests):
                    selected.append(tests[idx - 1])
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(tests):
                selected.append(tests[idx - 1])
    return selected


def main() -> int:
    args = sys.argv[1:]

    # If any args given, delegate directly to pytest.
    if args:
        if args == ["-a"]:
            args = []
        return subprocess.call(
            [sys.executable, "-m", "pytest", TEST_DIR, "-v", *args],
        )

    # Interactive mode: collect, select, run.
    tests = _collect_tests()
    if not tests:
        print("No tests found.")
        return 1

    selected = _interactive_select(tests)
    if not selected:
        print("No tests selected.")
        return 0

    print(f"\nRunning {len(selected)} test(s)...\n")
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-v", *selected],
    )


if __name__ == "__main__":
    sys.exit(main())
