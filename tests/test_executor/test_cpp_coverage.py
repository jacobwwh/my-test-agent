# -*- coding: utf-8 -*-
"""Tests for gcovr Cobertura XML coverage parsing."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from testagent.executor.cpp.coverage import (
    build_gcovr_command,
    find_gcovr_xml,
    parse_gcovr_xml,
)


GCOVR_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<coverage line-rate="0.75" branch-rate="0.5" lines-covered="3" lines-valid="4"
          branches-covered="1" branches-valid="2" version="gcovr 8.6">
  <packages>
    <package name="shop" line-rate="0.75" branch-rate="0.5">
      <classes>
        <class name="discount_policy_cpp" filename="src/discount_policy.cpp"
               line-rate="0.75" branch-rate="0.5">
          <methods/>
          <lines>
            <line number="6" hits="1" branch="false"/>
            <line number="7" hits="1" branch="true" condition-coverage="50% (1/2)"/>
            <line number="8" hits="0" branch="false"/>
            <line number="10" hits="1" branch="false"/>
          </lines>
        </class>
        <class name="cart_cpp" filename="src/cart.cpp" line-rate="1.0" branch-rate="1.0">
          <methods/>
          <lines>
            <line number="3" hits="1" branch="false"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def test_find_gcovr_xml_prefers_report_dir_coverage_xml(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    expected = report_dir / "coverage.xml"
    expected.write_text(GCOVR_XML, encoding="utf-8")

    assert find_gcovr_xml(report_dir, tmp_path) == expected


def test_build_gcovr_command_uses_report_dir_as_object_directory(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    report_dir = tmp_path / "external-reports" / "iter1"
    output_xml = report_dir / "coverage.xml"

    command = build_gcovr_command(project_path, report_dir, output_xml)

    assert command[:3] == [sys.executable, "-m", "gcovr"]
    assert "--root" in command
    assert "." in command
    assert "--object-directory" in command
    assert str(report_dir.resolve()) in command
    assert "--output" in command
    assert str(output_xml.resolve()) in command
    assert "src/.*" not in command


def test_parse_gcovr_xml_returns_target_file_coverage(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(GCOVR_XML, encoding="utf-8")

    report = parse_gcovr_xml(xml_path, tmp_path / "src" / "discount_policy.cpp")

    assert report is not None
    assert report.line_coverage == pytest.approx(0.75)
    assert report.branch_coverage == pytest.approx(0.5)
    assert report.uncovered_lines == [8]
    assert report.uncovered_branches == ["Line 7: 1/2 branch(es) not covered"]


def test_parse_gcovr_xml_returns_none_when_target_file_missing(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(GCOVR_XML, encoding="utf-8")

    assert parse_gcovr_xml(xml_path, tmp_path / "src" / "missing.cpp") is None


def test_parse_gcovr_xml_treats_no_branch_data_as_satisfied(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        """\
<coverage line-rate="1.0" branch-rate="0.0">
  <packages>
    <package name="">
      <classes>
        <class name="cart_cpp" filename="src/cart.cpp" line-rate="1.0">
          <lines>
            <line number="3" hits="1" branch="false"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    report = parse_gcovr_xml(xml_path, tmp_path / "src" / "cart.cpp")

    assert report is not None
    assert report.branch_coverage == pytest.approx(1.0)
