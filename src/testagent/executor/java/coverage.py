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
    """读取指定计数器的 missed/covered 值。

    功能简介：
        在 JaCoCo XML 节点下查找给定类型的 `counter` 元素，并返回
        `(missed, covered)` 数值对；若不存在则返回 `(0, 0)`。

    输入参数：
        node:
            JaCoCo XML 中的 class、method 或其他含有 counter 的节点。
        counter_type:
            计数器类型，例如 `LINE` 或 `BRANCH`。

    返回值：
        tuple[int, int]:
            `(missed, covered)` 二元组。

    使用示例：
        >>> _counter_values(node, "LINE")
        (1, 5)
    """
    for counter in node.findall("counter"):
        if counter.get("type") == counter_type:
            return int(counter.get("missed", 0)), int(counter.get("covered", 0))
    return 0, 0


def _coverage_ratio(missed: int, covered: int) -> float:
    """计算通用覆盖率比例。

    功能简介：
        根据 missed 和 covered 数量计算覆盖率；当总数为 0 时返回 `0.0`。

    输入参数：
        missed:
            未覆盖数量。
        covered:
            已覆盖数量。

    返回值：
        float:
            覆盖率，范围通常在 `0.0` 到 `1.0` 之间。

    使用示例：
        >>> _coverage_ratio(1, 3)
        0.75
    """
    total = missed + covered
    return covered / total if total > 0 else 0.0


def _branch_coverage_ratio(missed: int, covered: int) -> float:
    """计算分支覆盖率比例。

    功能简介：
        计算分支覆盖率，并将“没有分支”的情况视为已满足覆盖要求，返回 `1.0`。

    输入参数：
        missed:
            未覆盖分支数。
        covered:
            已覆盖分支数。

    返回值：
        float:
            分支覆盖率。

    使用示例：
        >>> _branch_coverage_ratio(0, 0)
        1.0
    """
    total = missed + covered
    return covered / total if total > 0 else 1.0


# ---------------------------------------------------------------------------
# Find the target class node in the XML
# ---------------------------------------------------------------------------

def _class_xml_name(class_name: str) -> str:
    """将全限定类名转换为 JaCoCo XML 中的类路径格式。

    功能简介：
        将点分隔的 Java 全限定类名转换成 JaCoCo XML 使用的斜杠路径格式。

    输入参数：
        class_name:
            Java 全限定类名。

    返回值：
        str:
            JaCoCo XML 中对应的类名格式。

    使用示例：
        >>> _class_xml_name("com.example.Calculator")
        'com/example/Calculator'
    """
    return class_name.replace(".", "/")


def _find_class_node(root: ET.Element, class_name: str) -> ET.Element | None:
    """在 JaCoCo 报告中查找目标类节点。

    功能简介：
        遍历整个 XML 树，定位与目标全限定类名对应的 `<class>` 元素。

    输入参数：
        root:
            JaCoCo XML 根节点。
        class_name:
            目标类的全限定类名。

    返回值：
        ET.Element | None:
            匹配的 `<class>` 节点；未找到时返回 `None`。

    使用示例：
        >>> _find_class_node(root, "com.example.Calculator")
    """
    xml_name = _class_xml_name(class_name)
    for cls in root.iter("class"):
        if cls.get("name") == xml_name:
            return cls
    return None


def _find_sourcefile_node(root: ET.Element, class_name: str) -> ET.Element | None:
    """查找目标类对应的 `<sourcefile>` 节点。

    功能简介：
        先按包路径和源码文件名精确匹配，再在整个 XML 中做兜底搜索，
        用于提取逐行覆盖率信息。

    输入参数：
        root:
            JaCoCo XML 根节点。
        class_name:
            目标类的全限定类名。

    返回值：
        ET.Element | None:
            匹配的 `<sourcefile>` 节点；未找到时返回 `None`。

    使用示例：
        >>> _find_sourcefile_node(root, "com.example.Calculator")
    """
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
    """判断行号是否落在指定范围内。

    功能简介：
        用于按方法行范围过滤逐行覆盖率数据；若未提供范围，则所有行都视为命中。

    输入参数：
        line_nr:
            当前源码行号。
        line_range:
            目标行范围 `(start, end)`；为 `None` 时不过滤。

    返回值：
        bool:
            行号是否命中范围。

    使用示例：
        >>> _line_in_range(10, (8, 12))
        True
    """
    if line_range is None:
        return True
    start, end = line_range
    return start <= line_nr <= end


def _uncovered_lines(
    sourcefile_node: ET.Element,
    line_range: tuple[int, int] | None = None,
) -> list[int]:
    """提取未覆盖的源码行号。

    功能简介：
        遍历 `<sourcefile>` 下的逐行覆盖率记录，找出没有任何已覆盖指令的行。

    输入参数：
        sourcefile_node:
            JaCoCo XML 中的 `<sourcefile>` 节点。
        line_range:
            可选的行号过滤范围；通常用于只保留某个方法内部的行。

    返回值：
        list[int]:
            未覆盖的行号列表，按升序返回。

    使用示例：
        >>> _uncovered_lines(sourcefile_node)
        [10, 12]
    """
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
    """提取未覆盖分支的可读描述。

    功能简介：
        遍历 `<sourcefile>` 下的逐行数据，对存在 missed branch 的行生成
        可直接展示给 LLM 或用户的描述文本。

    输入参数：
        sourcefile_node:
            JaCoCo XML 中的 `<sourcefile>` 节点。
        line_range:
            可选的行号过滤范围。

    返回值：
        list[str]:
            未覆盖分支描述列表，例如 `Line 9: 1/2 branch(es) not covered`。

    使用示例：
        >>> _uncovered_branches(sourcefile_node)
        ['Line 9: 1/2 branch(es) not covered']
    """
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
    """在类节点中查找目标方法节点。

    功能简介：
        遍历 `<class>` 节点下的所有 `<method>` 元素，按名称定位目标方法。

    输入参数：
        class_node:
            JaCoCo XML 中的 `<class>` 节点。
        method_name:
            目标方法名。

    返回值：
        ET.Element | None:
            匹配的 `<method>` 节点；未找到时返回 `None`。

    使用示例：
        >>> _find_method_node(class_node, "add")
    """
    for method in class_node.findall("method"):
        if method.get("name") == method_name:
            return method
    return None


def _method_line_range(
    class_node: ET.Element,
    method_name: str,
    sourcefile_node: ET.Element,
) -> tuple[int, int] | None:
    """估算方法在源码中的行号范围。

    功能简介：
        JaCoCo 只给出方法起始行，不直接提供结束行；该函数会用下一个方法的
        起始行减一作为结束行，最后一个方法则回退到文件最后一行。

    输入参数：
        class_node:
            JaCoCo XML 中的 `<class>` 节点。
        method_name:
            目标方法名。
        sourcefile_node:
            对应源码文件的 `<sourcefile>` 节点。

    返回值：
        tuple[int, int] | None:
            估算得到的 `(start_line, end_line)`；无法估算时返回 `None`。

    使用示例：
        >>> _method_line_range(class_node, "divide", sourcefile_node)
        (9, 13)
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
    """解析 JaCoCo XML 并生成覆盖率结果。

    功能简介：
        从 JaCoCo XML 报告中读取目标类或目标方法的 LINE/BRANCH 覆盖率，
        并提取未覆盖行与未覆盖分支明细，最终封装为 `CoverageReport`。

    输入参数：
        xml_path:
            JaCoCo XML 报告路径。
        class_name:
            目标类的全限定类名。
        method_name:
            可选的方法名；提供时优先读取方法级覆盖率，否则读取类级覆盖率。

    返回值：
        CoverageReport | None:
            覆盖率结果对象；若报告文件不存在、XML 无法解析或目标类不存在则返回 `None`。

    使用示例：
        >>> report = parse_jacoco_xml(Path("/tmp/jacoco.xml"), "com.example.Calculator", "add")
        >>> report.branch_coverage
        1.0
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
    """查找 JaCoCo XML 报告文件。

    功能简介：
        先在指定报告目录及其常见子路径中搜索 `jacoco.xml`，
        若未找到，再回退到 Maven/Gradle 默认输出路径。

    输入参数：
        report_dir:
            优先搜索的报告目录。
        project_path:
            被测项目根目录；提供时用于补充搜索默认构建输出路径。

    返回值：
        Path | None:
            命中的 `jacoco.xml` 路径；若未找到则返回 `None`。

    使用示例：
        >>> find_jacoco_xml(Path("/tmp/reports"), Path("/repo/demo"))
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
