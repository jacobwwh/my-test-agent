"""Tests for testagent.executor.coverage."""

from pathlib import Path

import pytest

from testagent.executor.java.coverage import (
    _branch_coverage_ratio,
    _class_xml_name,
    _coverage_ratio,
    _find_class_node,
    _find_sourcefile_node,
    _uncovered_branches,
    _uncovered_lines,
    find_jacoco_xml,
    parse_jacoco_xml,
)
from testagent.models import CoverageReport


# ---------------------------------------------------------------------------
# Fixtures: minimal JaCoCo XML content
# ---------------------------------------------------------------------------

FULL_JACOCO_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">
<report name="sample-java-project">
  <package name="com/example">
    <class name="com/example/Calculator" sourcefilename="Calculator.java">
      <method name="add" desc="(II)I" line="5">
        <counter type="INSTRUCTION" missed="0" covered="4"/>
        <counter type="LINE" missed="0" covered="1"/>
      </method>
      <method name="divide" desc="(II)I" line="9">
        <counter type="INSTRUCTION" missed="3" covered="5"/>
        <counter type="BRANCH" missed="1" covered="1"/>
        <counter type="LINE" missed="1" covered="2"/>
      </method>
      <counter type="LINE" missed="1" covered="3"/>
      <counter type="BRANCH" missed="1" covered="1"/>
    </class>
    <sourcefile name="Calculator.java">
      <line nr="5"  mi="0" ci="1" mb="0" cb="0"/>
      <line nr="9"  mi="0" ci="1" mb="1" cb="1"/>
      <line nr="10" mi="1" ci="0" mb="0" cb="0"/>
      <line nr="13" mi="0" ci="1" mb="0" cb="0"/>
    </sourcefile>
  </package>
  <package name="com/example/service">
    <class name="com/example/service/OrderService" sourcefilename="OrderService.java">
      <counter type="LINE" missed="2" covered="8"/>
      <counter type="BRANCH" missed="0" covered="4"/>
    </class>
    <sourcefile name="OrderService.java">
      <line nr="20" mi="0" ci="1" mb="0" cb="0"/>
      <line nr="21" mi="1" ci="0" mb="0" cb="0"/>
      <line nr="22" mi="1" ci="0" mb="0" cb="0"/>
    </sourcefile>
  </package>
</report>
"""

EMPTY_CLASS_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<report name="test">
  <package name="com/example">
    <class name="com/example/Empty">
      <counter type="LINE" missed="0" covered="0"/>
      <counter type="BRANCH" missed="0" covered="0"/>
    </class>
    <sourcefile name="Empty.java"/>
  </package>
</report>
"""

MALFORMED_XML = "this is not xml <<<"


@pytest.fixture
def jacoco_xml(tmp_path) -> Path:
    p = tmp_path / "jacoco.xml"
    p.write_text(FULL_JACOCO_XML, encoding="utf-8")
    return p


@pytest.fixture
def empty_class_xml(tmp_path) -> Path:
    p = tmp_path / "jacoco.xml"
    p.write_text(EMPTY_CLASS_XML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_class_xml_name(self):
        assert _class_xml_name("com.example.Calculator") == "com/example/Calculator"

    def test_class_xml_name_simple(self):
        assert _class_xml_name("Calculator") == "Calculator"

    def test_coverage_ratio_normal(self):
        assert _coverage_ratio(1, 3) == pytest.approx(0.75)

    def test_coverage_ratio_full(self):
        assert _coverage_ratio(0, 5) == pytest.approx(1.0)

    def test_coverage_ratio_zero(self):
        assert _coverage_ratio(5, 0) == pytest.approx(0.0)

    def test_coverage_ratio_no_data(self):
        assert _coverage_ratio(0, 0) == pytest.approx(0.0)

    def test_branch_coverage_ratio_no_data_is_satisfied(self):
        assert _branch_coverage_ratio(0, 0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# XML node finders
# ---------------------------------------------------------------------------

class TestFindNodes:
    def _root(self, xml_text):
        import xml.etree.ElementTree as ET
        return ET.fromstring(xml_text)

    def test_find_class_node_found(self):
        root = self._root(FULL_JACOCO_XML)
        node = _find_class_node(root, "com.example.Calculator")
        assert node is not None
        assert node.get("name") == "com/example/Calculator"

    def test_find_class_node_not_found(self):
        root = self._root(FULL_JACOCO_XML)
        assert _find_class_node(root, "com.example.Missing") is None

    def test_find_sourcefile_node_found(self):
        root = self._root(FULL_JACOCO_XML)
        sf = _find_sourcefile_node(root, "com.example.Calculator")
        assert sf is not None
        assert sf.get("name") == "Calculator.java"

    def test_find_sourcefile_node_not_found(self):
        root = self._root(FULL_JACOCO_XML)
        assert _find_sourcefile_node(root, "com.example.Missing") is None


# ---------------------------------------------------------------------------
# Uncovered lines / branches
# ---------------------------------------------------------------------------

class TestUncoveredExtraction:
    def _sourcefile(self, xml_text, class_name):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        return _find_sourcefile_node(root, class_name)

    def test_uncovered_lines(self):
        sf = self._sourcefile(FULL_JACOCO_XML, "com.example.Calculator")
        lines = _uncovered_lines(sf)
        assert lines == [10]   # nr=10 has mi=1, ci=0

    def test_uncovered_lines_empty_when_all_covered(self):
        sf = self._sourcefile(FULL_JACOCO_XML, "com.example.service.OrderService")
        lines = _uncovered_lines(sf)
        assert 21 in lines
        assert 22 in lines

    def test_uncovered_branches(self):
        sf = self._sourcefile(FULL_JACOCO_XML, "com.example.Calculator")
        branches = _uncovered_branches(sf)
        assert len(branches) == 1
        assert "Line 9" in branches[0]
        assert "1/2" in branches[0]

    def test_uncovered_branches_none_missed(self):
        sf = self._sourcefile(EMPTY_CLASS_XML, "com.example.Empty")
        assert _uncovered_branches(sf) == []


# ---------------------------------------------------------------------------
# parse_jacoco_xml
# ---------------------------------------------------------------------------

class TestParseJacocoXml:
    def test_returns_coverage_report(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator")
        assert isinstance(report, CoverageReport)

    def test_line_coverage(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator")
        # missed=1, covered=3 → 3/4 = 0.75
        assert report.line_coverage == pytest.approx(0.75)

    def test_branch_coverage(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator")
        # missed=1, covered=1 → 1/2 = 0.5
        assert report.branch_coverage == pytest.approx(0.5)

    def test_uncovered_lines_populated(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator")
        assert 10 in report.uncovered_lines

    def test_uncovered_branches_populated(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator")
        assert len(report.uncovered_branches) >= 1
        assert any("Line 9" in b for b in report.uncovered_branches)

    def test_returns_none_when_file_missing(self, tmp_path):
        result = parse_jacoco_xml(tmp_path / "nonexistent.xml", "com.example.Foo")
        assert result is None

    def test_returns_none_when_class_missing(self, jacoco_xml):
        result = parse_jacoco_xml(jacoco_xml, "com.example.NoSuchClass")
        assert result is None

    def test_returns_none_on_malformed_xml(self, tmp_path):
        p = tmp_path / "bad.xml"
        p.write_text(MALFORMED_XML)
        result = parse_jacoco_xml(p, "com.example.Foo")
        assert result is None

    def test_zero_coverage_when_no_data(self, empty_class_xml):
        report = parse_jacoco_xml(empty_class_xml, "com.example.Empty")
        assert report is not None
        assert report.line_coverage == pytest.approx(0.0)
        assert report.branch_coverage == pytest.approx(1.0)

    def test_full_coverage(self, jacoco_xml):
        # OrderService has missed=0 branches → branch_coverage=1.0
        report = parse_jacoco_xml(jacoco_xml, "com.example.service.OrderService")
        assert report.branch_coverage == pytest.approx(1.0)

    def test_method_without_branches_is_treated_as_fully_covered(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator", "add")
        assert report is not None
        assert report.line_coverage == pytest.approx(1.0)
        assert report.branch_coverage == pytest.approx(1.0)
        assert report.uncovered_lines == []
        assert report.uncovered_branches == []

    def test_method_filters_uncovered_details_to_its_own_lines(self, jacoco_xml):
        report = parse_jacoco_xml(jacoco_xml, "com.example.Calculator", "divide")
        assert report is not None
        assert report.line_coverage == pytest.approx(2 / 3)
        assert report.branch_coverage == pytest.approx(0.5)
        assert report.uncovered_lines == [10]
        assert report.uncovered_branches == ["Line 9: 1/2 branch(es) not covered"]


# ---------------------------------------------------------------------------
# find_jacoco_xml
# ---------------------------------------------------------------------------

class TestFindJacocoXml:
    def test_finds_direct_jacoco_xml(self, tmp_path):
        f = tmp_path / "jacoco.xml"
        f.touch()
        assert find_jacoco_xml(tmp_path) == f

    def test_finds_nested_jacoco_xml(self, tmp_path):
        d = tmp_path / "jacoco"
        d.mkdir()
        f = d / "jacoco.xml"
        f.touch()
        assert find_jacoco_xml(tmp_path) == f

    def test_finds_deeply_nested_via_rglob(self, tmp_path):
        d = tmp_path / "a" / "b" / "c"
        d.mkdir(parents=True)
        f = d / "jacoco.xml"
        f.touch()
        assert find_jacoco_xml(tmp_path) == f

    def test_returns_none_when_absent(self, tmp_path):
        assert find_jacoco_xml(tmp_path) is None
