"""Parse JaCoCo XML coverage reports.

JaCoCo XML format (jacoco.xml):

  <report name="...">
    <package name="com/example/service">
      <class name="com/example/service/OrderService"
             sourcefilename="OrderService.java">
        <method name="process" desc="(Lcom/example/model/Order;)..." line="12">
          <counter type="INSTRUCTION" missed="0" covered="8"/>
          <counter type="BRANCH"      missed="1" covered="1"/>
          <counter type="LINE"        missed="0" covered="4"/>
        </method>
        <counter type="LINE"   missed="2" covered="10"/>
        <counter type="BRANCH" missed="1" covered="3"/>
      </class>
      <sourcefile name="OrderService.java">
        <line nr="15" mi="0" ci="1" mb="0" cb="0"/>
        ...
      </sourcefile>
    </package>
  </report>
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from testagent.models import CoverageReport

logger = logging.getLogger(__name__)

# JaCoCo XML counter types
_LINE = "LINE"
_BRANCH = "BRANCH"


def _counter_values(node: ET.Element, counter_type: str) -> tuple[int, int]:
    """Return ``(missed, covered)`` for the given counter type under *node*."""
    for counter in node.findall("counter"):
        if counter.get("type") == counter_type:
            return int(counter.get("missed", 0)), int(counter.get("covered", 0))
    return 0, 0


def _coverage_ratio(missed: int, covered: int) -> float:
    total = missed + covered
    return covered / total if total > 0 else 0.0


def _branch_coverage_ratio(missed: int, covered: int) -> float:
    """Return branch coverage, treating 'no branches' as fully satisfied."""
    total = missed + covered
    return covered / total if total > 0 else 1.0


# ---------------------------------------------------------------------------
# Find the target class node in the XML
# ---------------------------------------------------------------------------

def _class_xml_name(class_name: str) -> str:
    """Convert ``"com.example.service.OrderService"`` → ``"com/example/service/OrderService"``."""
    return class_name.replace(".", "/")


def _find_class_node(root: ET.Element, class_name: str) -> ET.Element | None:
    """Locate the ``<class>`` element for *class_name* anywhere in the report."""
    xml_name = _class_xml_name(class_name)
    for cls in root.iter("class"):
        if cls.get("name") == xml_name:
            return cls
    return None


def _find_sourcefile_node(root: ET.Element, class_name: str) -> ET.Element | None:
    """Locate the ``<sourcefile>`` element for *class_name*."""
    simple_name = class_name.rsplit(".", 1)[-1] + ".java"
    package_path = "/".join(class_name.split(".")[:-1])

    for pkg in root.iter("package"):
        if pkg.get("name") == package_path:
            for sf in pkg.findall("sourcefile"):
                if sf.get("name") == simple_name:
                    return sf
    # Fallback: search globally
    for sf in root.iter("sourcefile"):
        if sf.get("name") == simple_name:
            return sf
    return None


# ---------------------------------------------------------------------------
# Uncovered lines / branches
# ---------------------------------------------------------------------------

def _line_in_range(line_nr: int, line_range: tuple[int, int] | None) -> bool:
    """Return whether *line_nr* falls inside *line_range* when provided."""
    if line_range is None:
        return True
    start, end = line_range
    return start <= line_nr <= end


def _uncovered_lines(
    sourcefile_node: ET.Element,
    line_range: tuple[int, int] | None = None,
) -> list[int]:
    """Return line numbers with no covered instructions (``ci == 0``)."""
    uncovered: list[int] = []
    for line in sourcefile_node.findall("line"):
        nr = int(line.get("nr", 0))
        if not _line_in_range(nr, line_range):
            continue
        ci = int(line.get("ci", 0))
        mi = int(line.get("mi", 0))
        if ci == 0 and mi > 0:
            uncovered.append(nr)
    return sorted(uncovered)


def _uncovered_branches(
    sourcefile_node: ET.Element,
    line_range: tuple[int, int] | None = None,
) -> list[str]:
    """Return human-readable descriptions of lines with missed branches."""
    descriptions: list[str] = []
    for line in sourcefile_node.findall("line"):
        nr = int(line.get("nr", 0))
        if not _line_in_range(nr, line_range):
            continue
        mb = int(line.get("mb", 0))  # missed branches
        cb = int(line.get("cb", 0))  # covered branches
        if mb > 0:
            total = mb + cb
            descriptions.append(
                f"Line {nr}: {mb}/{total} branch(es) not covered"
            )
    return descriptions


def _find_method_node(
    class_node: ET.Element, method_name: str,
) -> ET.Element | None:
    """Locate the ``<method>`` element for *method_name* inside *class_node*."""
    for method in class_node.findall("method"):
        if method.get("name") == method_name:
            return method
    return None


def _method_line_range(
    class_node: ET.Element,
    method_name: str,
    sourcefile_node: ET.Element,
) -> tuple[int, int] | None:
    """Estimate the source line range occupied by *method_name*.

    JaCoCo XML exposes a start line for each method but not an explicit end
    line, so we approximate the end as the line before the next method starts.
    For the last method we use the last source line present in the file.
    """
    methods_with_lines: list[tuple[int, str]] = []
    for method in class_node.findall("method"):
        line_text = method.get("line")
        if line_text and line_text.isdigit():
            methods_with_lines.append((int(line_text), method.get("name", "")))

    if not methods_with_lines:
        return None

    methods_with_lines.sort()
    target_index: int | None = None
    for index, (_, current_name) in enumerate(methods_with_lines):
        if current_name == method_name:
            target_index = index
            break
    if target_index is None:
        return None

    start_line = methods_with_lines[target_index][0]
    last_line = max(
        (int(line.get("nr", 0)) for line in sourcefile_node.findall("line")),
        default=start_line,
    )
    if target_index + 1 < len(methods_with_lines):
        end_line = methods_with_lines[target_index + 1][0] - 1
    else:
        end_line = last_line
    return start_line, max(start_line, end_line)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_jacoco_xml(
    xml_path: Path,
    class_name: str,
    method_name: str | None = None,
) -> CoverageReport | None:
    """Parse a JaCoCo XML report and return coverage for *class_name*.

    Parameters
    ----------
    xml_path:
        Path to ``jacoco.xml`` produced by JaCoCo.
    class_name:
        Fully-qualified class name, e.g. ``"com.example.Calculator"``.
    method_name:
        Optional method name.  When provided, LINE and BRANCH counters are
        read from the ``<method>`` element instead of the class-level
        aggregate, giving per-method coverage rather than whole-class coverage.

    Returns
    -------
    CoverageReport
        Coverage data for the target class (or method), or ``None`` if the
        class is not found in the report or the file cannot be parsed.
    """
    if not xml_path.is_file():
        logger.warning("JaCoCo XML not found: %s", xml_path)
        return None

    try:
        tree = ET.parse(xml_path)  # noqa: S314 — local file, not user-supplied
        root = tree.getroot()
    except ET.ParseError as exc:
        logger.warning("Failed to parse JaCoCo XML %s: %s", xml_path, exc)
        return None

    class_node = _find_class_node(root, class_name)
    if class_node is None:
        logger.warning(
            "Class '%s' not found in JaCoCo report %s", class_name, xml_path
        )
        return None

    # Prefer method-level counters when a specific method is requested.
    counter_node = class_node
    if method_name:
        method_node = _find_method_node(class_node, method_name)
        if method_node is not None:
            counter_node = method_node
        else:
            logger.warning(
                "Method '%s' not found in class '%s'; falling back to class-level counters.",
                method_name, class_name,
            )

    line_missed, line_covered = _counter_values(counter_node, _LINE)
    branch_missed, branch_covered = _counter_values(counter_node, _BRANCH)

    line_coverage = _coverage_ratio(line_missed, line_covered)
    branch_coverage = _branch_coverage_ratio(branch_missed, branch_covered)

    # Per-line details come from the <sourcefile> element.
    sourcefile_node = _find_sourcefile_node(root, class_name)
    uncovered_lines: list[int] = []
    uncovered_branches: list[str] = []
    if sourcefile_node is not None:
        line_range = None
        if method_name and method_node is not None:
            line_range = _method_line_range(class_node, method_name, sourcefile_node)
        uncovered_lines = _uncovered_lines(sourcefile_node, line_range)
        uncovered_branches = _uncovered_branches(sourcefile_node, line_range)

    return CoverageReport(
        line_coverage=line_coverage,
        branch_coverage=branch_coverage,
        uncovered_lines=uncovered_lines,
        uncovered_branches=uncovered_branches,
    )


def find_jacoco_xml(report_dir: Path, project_path: Path | None = None) -> Path | None:
    """Search *report_dir* for jacoco.xml and return its path, or ``None``.

    If the XML is not found in *report_dir*, falls back to the Maven/Gradle
    default locations under *project_path*/target/ (if provided).
    """
    candidates = [
        report_dir / "jacoco.xml",
        report_dir / "jacoco" / "jacoco.xml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    # Recursive search in report_dir
    found = list(report_dir.rglob("jacoco.xml"))
    if found:
        return found[0]
    # Fallback: Maven/Gradle default output locations
    if project_path is not None:
        fallbacks = [
            project_path / "target" / "site" / "jacoco" / "jacoco.xml",
            project_path / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml",
        ]
        for fb in fallbacks:
            if fb.is_file():
                return fb
    return None
