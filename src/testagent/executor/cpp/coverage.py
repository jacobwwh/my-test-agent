# -*- coding: utf-8 -*-
"""Parse gcovr Cobertura XML coverage reports for C++ projects."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from testagent.models import CoverageReport

logger = logging.getLogger(__name__)

_CONDITION_COVERAGE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")


def build_gcovr_command(
    project_path: Path,
    report_dir: Path,
    output_xml: Path,
) -> list[str]:
    """构造 gcovr Cobertura XML 生成命令。

    功能简介：
        以被测项目目录作为 gcovr root，同时显式传入本轮报告目录作为
        object directory。这样即使 `REPORT_DIR` 位于被测项目之外，gcovr
        也能找到 `.gcno/.gcda` 文件。命令不写死 `src/.*` 过滤规则，避免
        漏掉源码位于 `source/`、`lib/` 或其他目录的 C++ 项目；后续解析
        阶段会按目标源码文件筛选。
    """
    del project_path
    return [
        sys.executable,
        "-m",
        "gcovr",
        "--root",
        ".",
        "--object-directory",
        str(report_dir.resolve()),
        "--exclude",
        "tests/testagent/generated/.*",
        "--cobertura-pretty",
        "--output",
        str(output_xml.resolve()),
    ]


def run_gcovr(
    project_path: Path,
    command: list[str],
    timeout: int = 300,
) -> tuple[int, str]:
    """运行 gcovr 并返回退出码与输出。"""
    logger.info("Running C++ coverage command: %s", " ".join(command))
    result = subprocess.run(
        command,
        cwd=project_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        text=True,
    )
    return result.returncode, result.stdout


def _coverage_ratio(missed: int, covered: int) -> float:
    """计算覆盖率比例。"""
    total = missed + covered
    return covered / total if total > 0 else 0.0


def _branch_coverage_ratio(missed: int, covered: int) -> float:
    """计算分支覆盖率；没有分支时视为已满足。"""
    total = missed + covered
    return covered / total if total > 0 else 1.0


def _normalize_path(value: str | Path) -> str:
    """将路径转换为跨平台可比较的 POSIX 形式。"""
    return Path(value).as_posix().replace("\\", "/")


def _path_matches(xml_filename: str, target_file: Path) -> bool:
    """判断 Cobertura class filename 是否对应目标源码文件。"""
    xml_path = _normalize_path(xml_filename)
    target_path = _normalize_path(target_file)
    return target_path.endswith(xml_path) or xml_path.endswith(target_path)


def _find_class_node(root: ET.Element, target_file: Path) -> ET.Element | None:
    """在 gcovr Cobertura XML 中查找目标源码文件对应的 class 节点。"""
    for class_node in root.iter("class"):
        filename = class_node.get("filename")
        if filename and _path_matches(filename, target_file):
            return class_node
    return None


def _line_hits(line_node: ET.Element) -> int:
    """读取 Cobertura line 节点的命中次数。"""
    return int(line_node.get("hits", 0))


def _line_branch_counts(line_node: ET.Element) -> tuple[int, int]:
    """读取单行分支的 covered/total 数量。"""
    if line_node.get("branch", "false").lower() != "true":
        return 0, 0

    condition_coverage = line_node.get("condition-coverage", "")
    match = _CONDITION_COVERAGE.search(condition_coverage)
    if match:
        return int(match.group(1)), int(match.group(2))

    conditions = line_node.find("conditions")
    if conditions is None:
        return 0, 0

    covered = 0
    total = 0
    for condition in conditions.findall("condition"):
        total += 1
        raw_coverage = condition.get("coverage", "0").rstrip("%")
        try:
            if float(raw_coverage) > 0:
                covered += 1
        except ValueError:
            continue
    return covered, total


def _lines_node(class_node: ET.Element) -> ET.Element | None:
    """返回 class 节点下的 lines 子节点。"""
    return class_node.find("lines")


def parse_gcovr_xml(
    xml_path: Path,
    target_file: str | Path,
    method_name: str | None = None,
) -> CoverageReport | None:
    """解析 gcovr Cobertura XML 覆盖率。

    功能简介：
        从 gcovr 生成的 Cobertura XML 中查找目标 C++ 源文件，并将文件级
        line/branch 覆盖率转换为项目统一的 `CoverageReport`。gcovr 的
        Cobertura 输出通常不包含稳定的方法级计数，因此 `method_name`
        作为兼容参数保留，当前不做方法级过滤。

    输入参数：
        xml_path:
            gcovr Cobertura XML 文件路径。
        target_file:
            目标 C++ 源文件路径。
        method_name:
            可选目标方法名，当前仅用于保持与 Java coverage parser 相近的接口形态。

    返回值：
        CoverageReport | None:
            成功解析时返回覆盖率对象；报告不存在、XML 损坏或目标文件不存在时返回 `None`。
    """
    del method_name

    if not xml_path.is_file():
        logger.warning("gcovr XML not found: %s", xml_path)
        return None

    try:
        tree = ET.parse(xml_path)  # noqa: S314 — local report file
        root = tree.getroot()
    except ET.ParseError as exc:
        logger.warning("Failed to parse gcovr XML %s: %s", xml_path, exc)
        return None

    target_path = Path(target_file)
    class_node = _find_class_node(root, target_path)
    if class_node is None:
        logger.warning(
            "Source file '%s' not found in gcovr report %s", target_path, xml_path,
        )
        return None

    lines_node = _lines_node(class_node)
    if lines_node is None:
        return CoverageReport(
            line_coverage=0.0,
            branch_coverage=1.0,
            uncovered_lines=[],
            uncovered_branches=[],
        )

    line_missed = 0
    line_covered = 0
    branch_missed = 0
    branch_covered = 0
    uncovered_lines: list[int] = []
    uncovered_branches: list[str] = []

    for line_node in lines_node.findall("line"):
        line_number = int(line_node.get("number", 0))
        hits = _line_hits(line_node)
        if hits > 0:
            line_covered += 1
        else:
            line_missed += 1
            uncovered_lines.append(line_number)

        covered, total = _line_branch_counts(line_node)
        if total > 0:
            missed = total - covered
            branch_covered += covered
            branch_missed += missed
            if missed > 0:
                uncovered_branches.append(
                    f"Line {line_number}: {missed}/{total} branch(es) not covered"
                )

    return CoverageReport(
        line_coverage=_coverage_ratio(line_missed, line_covered),
        branch_coverage=_branch_coverage_ratio(branch_missed, branch_covered),
        uncovered_lines=sorted(uncovered_lines),
        uncovered_branches=uncovered_branches,
    )


def find_gcovr_xml(report_dir: Path, project_path: Path | None = None) -> Path | None:
    """查找 gcovr Cobertura XML 报告文件。

    功能简介：
        优先在本轮 `REPORT_DIR` 中查找 `coverage.xml`，再查找常见文件名和
        子目录中的 XML 文件。提供 `project_path` 时，会额外检查项目默认
        build/testagent 目录，便于兼容手工 Makefile 配置。

    输入参数：
        report_dir:
            本轮执行报告目录。
        project_path:
            被测项目根目录。

    返回值：
        Path | None:
            找到的 XML 路径；未找到时返回 `None`。
    """
    candidates = [
        report_dir / "coverage.xml",
        report_dir / "cobertura.xml",
        report_dir / "gcovr.xml",
    ]
    if project_path is not None:
        candidates.extend(
            [
                project_path / "build" / "testagent" / "coverage.xml",
                project_path / "build" / "testagent" / "cobertura.xml",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if report_dir.is_dir():
        for candidate in sorted(report_dir.rglob("*.xml")):
            if candidate.is_file():
                return candidate

    return None
