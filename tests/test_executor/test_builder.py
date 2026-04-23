"""Tests for testagent.executor.builder."""

from pathlib import Path
from unittest.mock import patch

import pytest

from testagent.executor.java.builder import (
    _make_banner,
    _resolve_gradle,
    _resolve_mvn,
    build_gradle_command,
    build_maven_command,
    cleanup_generated_tests,
    detect_build_tool,
    extract_class_name_from_code,
    extract_package_from_code,
    expected_test_file_path,
    find_test_source_dir,
    write_test_file,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

SIMPLE_TEST_CODE = """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {
    @Test
    void testAdd() {
        assertEquals(3, 1 + 2);
    }
}
"""

NO_PACKAGE_TEST_CODE = """\
import org.junit.jupiter.api.Test;

public class FooTest {
    @Test
    void testSomething() {}
}
"""

PACKAGE_PRIVATE_TEST_CODE = """\
package com.example.service;

class OrderServiceTest {
}
"""

WRONG_GENERATED_TEST_CODE = """\
package com.generated.wrong;

import java.util.List;
import org.junit.jupiter.api.Test;

public class TotallyWrongName {
    @Test
    void generatedMethod() {
        assert true;
    }
}
"""

SECOND_GENERATED_TEST_CODE = """\
package com.generated.wrong;

import java.util.List;
import org.junit.jupiter.api.Test;

public class TotallyWrongName {
    @Test
    void generatedMethod() {
        assert 1 + 1 == 2;
    }
}
"""

EXISTING_TARGET_TEST_CODE = """\
package com.example.service;

import org.junit.jupiter.api.Test;

public class OrderServiceTest {
    @Test
    void keepsHumanTest() {
        assert true;
    }
}
"""

BRACE_RICH_GENERATED_TEST_CODE = """\
package com.generated.wrong;

import org.junit.jupiter.api.Test;

public class TotallyWrongName {
    @Test
    void generatedMethod() {
        String value = "}";
        // block comment with { and }
        String block = \"\"\"
            package fake.body;
            import java.util.Set;
            {
            }
            \"\"\";
        assertEquals("}", value);
    }
}
"""

NON_ASCII_HEADER_GENERATED_TEST_CODE = """\
// 中文 header
package com.generated.wrong;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    @Test
    void generatedMethod() {
        assert true;
    }
}
"""


# ---------------------------------------------------------------------------
# detect_build_tool
# ---------------------------------------------------------------------------

class TestDetectBuildTool:
    def test_detects_maven(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        assert detect_build_tool(tmp_path) == "maven"

    def test_detects_gradle(self, tmp_path):
        (tmp_path / "build.gradle").touch()
        assert detect_build_tool(tmp_path) == "gradle"

    def test_detects_gradle_kts(self, tmp_path):
        (tmp_path / "build.gradle.kts").touch()
        assert detect_build_tool(tmp_path) == "gradle"

    def test_maven_takes_priority_over_gradle(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        (tmp_path / "build.gradle").touch()
        assert detect_build_tool(tmp_path) == "maven"

    def test_raises_when_no_build_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="pom.xml nor build.gradle"):
            detect_build_tool(tmp_path)

    def test_detects_maven_in_sample_project(self, sample_project):
        assert detect_build_tool(sample_project) == "maven"


# ---------------------------------------------------------------------------
# find_test_source_dir
# ---------------------------------------------------------------------------

class TestFindTestSourceDir:
    def test_finds_existing_src_test_java(self, tmp_path):
        d = tmp_path / "src" / "test" / "java"
        d.mkdir(parents=True)
        assert find_test_source_dir(tmp_path) == d

    def test_finds_src_test_fallback(self, tmp_path):
        d = tmp_path / "src" / "test"
        d.mkdir(parents=True)
        assert find_test_source_dir(tmp_path) == d

    def test_returns_default_when_none_exists(self, tmp_path):
        result = find_test_source_dir(tmp_path)
        assert result == tmp_path / "src" / "test" / "java"
        # Should NOT create the directory
        assert not result.exists()


# ---------------------------------------------------------------------------
# extract_package_from_code / extract_class_name_from_code
# ---------------------------------------------------------------------------

class TestExtractFromCode:
    def test_extract_package(self):
        assert extract_package_from_code(SIMPLE_TEST_CODE) == "com.example"

    def test_extract_package_empty_when_absent(self):
        assert extract_package_from_code(NO_PACKAGE_TEST_CODE) == ""

    def test_extract_class_name(self):
        assert extract_class_name_from_code(SIMPLE_TEST_CODE) == "CalculatorTest"

    def test_extract_class_name_no_package(self):
        assert extract_class_name_from_code(NO_PACKAGE_TEST_CODE) == "FooTest"

    def test_extract_class_name_package_private(self):
        assert extract_class_name_from_code(PACKAGE_PRIVATE_TEST_CODE) == "OrderServiceTest"

    def test_extract_class_name_raises_when_missing(self):
        with pytest.raises(ValueError, match="Cannot find class declaration"):
            extract_class_name_from_code("interface Foo {}")


# ---------------------------------------------------------------------------
# _make_banner
# ---------------------------------------------------------------------------

class TestMakeBanner:
    def test_contains_chinese_label(self):
        banner = _make_banner("com.example.Foo", "bar", 1)
        assert "大模型生成" in banner

    def test_contains_target_info(self):
        banner = _make_banner("com.example.Foo", "bar", 2)
        assert "com.example.Foo#bar" in banner
        assert "Iteration: 2" in banner

    def test_is_block_comment(self):
        banner = _make_banner("X", "y", 1)
        assert banner.startswith("/*")
        assert banner.rstrip().endswith("*/")


# ---------------------------------------------------------------------------
# write_test_file
# ---------------------------------------------------------------------------

class TestWriteTestFile:
    def test_expected_test_file_path_mirrors_package_layout(self, tmp_path):
        path = expected_test_file_path(tmp_path, "com.example.service.OrderService")
        assert path == (
            tmp_path / "src" / "test" / "java" / "com" / "example" / "service" / "OrderServiceTest.java"
        )

    def test_creates_file_at_correct_path(self, tmp_path):
        (tmp_path / "src" / "test" / "java").mkdir(parents=True)
        dest = write_test_file(
            SIMPLE_TEST_CODE, tmp_path,
            class_name="com.example.Calculator",
            method_name="add",
            iteration=1,
        )
        expected = tmp_path / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
        assert dest == expected
        assert dest.is_file()

    def test_creation_ignores_wrong_generated_package_and_class(self, tmp_path):
        dest = write_test_file(
            WRONG_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.service.OrderService",
            "process",
            1,
        )

        expected = expected_test_file_path(tmp_path, "com.example.service.OrderService")
        assert dest == expected
        content = dest.read_text()
        assert "package com.example.service;" in content
        assert "public class OrderServiceTest" in content
        assert "TotallyWrongName" not in content
        assert "大模型生成" in content
        assert "com/generated/wrong" not in str(dest)

    def test_banner_prepended_before_package(self, tmp_path):
        (tmp_path / "src" / "test" / "java").mkdir(parents=True)
        dest = write_test_file(
            SIMPLE_TEST_CODE, tmp_path, "com.example.Calculator", "add", 1,
        )
        content = dest.read_text()
        banner_pos = content.index("大模型生成")
        pkg_pos = content.index("package com.example;")
        assert banner_pos < pkg_pos

    def test_banner_at_top_when_no_package(self, tmp_path):
        (tmp_path / "src" / "test" / "java").mkdir(parents=True)
        dest = write_test_file(
            NO_PACKAGE_TEST_CODE, tmp_path, "Foo", "something", 1,
        )
        content = dest.read_text()
        assert content.startswith("/*")
        assert "大模型生成" in content

    def test_original_code_preserved(self, tmp_path):
        (tmp_path / "src" / "test" / "java").mkdir(parents=True)
        dest = write_test_file(
            SIMPLE_TEST_CODE, tmp_path, "com.example.Calculator", "add", 1,
        )
        content = dest.read_text()
        assert "assertEquals(3, 1 + 2)" in content
        assert "public class CalculatorTest" in content

    def test_creates_parent_directories(self, tmp_path):
        # No test dir pre-created
        dest = write_test_file(
            SIMPLE_TEST_CODE, tmp_path, "com.example.Calculator", "add", 1,
        )
        assert dest.is_file()

    def test_iteration_reflected_in_banner(self, tmp_path):
        dest = write_test_file(
            SIMPLE_TEST_CODE, tmp_path, "com.example.Calculator", "add", 3,
        )
        content = dest.read_text()
        assert "Iteration: 3" in content

    def test_raises_when_no_public_class(self, tmp_path):
        bad_code = "package com.example;\ninterface Foo {}"
        with pytest.raises(ValueError):
            write_test_file(bad_code, tmp_path, "com.example.Foo", "bar", 1)

    def test_accepts_package_private_test_class(self, tmp_path):
        dest = write_test_file(
            PACKAGE_PRIVATE_TEST_CODE, tmp_path, "com.example.service.OrderService", "process", 1,
        )
        assert dest.name == "OrderServiceTest.java"
        assert "class OrderServiceTest" in dest.read_text()

    def test_merges_existing_file_without_dropping_human_tests(self, tmp_path):
        dest = expected_test_file_path(tmp_path, "com.example.service.OrderService")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(EXISTING_TARGET_TEST_CODE, encoding="utf-8")

        written = write_test_file(
            WRONG_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.service.OrderService",
            "process",
            1,
        )

        content = written.read_text()
        assert written == dest
        assert "void keepsHumanTest()" in content
        assert "大模型生成" not in content
        assert "// BEGIN testagent generated tests for com.example.service.OrderService#process" in content
        assert "// END testagent generated tests for com.example.service.OrderService#process" in content
        assert "void generatedMethod()" in content
        assert content.count("import java.util.List;") == 1
        assert content.count("import org.junit.jupiter.api.Test;") == 1

    def test_second_write_replaces_existing_generated_block(self, tmp_path):
        dest = write_test_file(
            WRONG_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.service.OrderService",
            "process",
            1,
        )

        dest = write_test_file(
            SECOND_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.service.OrderService",
            "process",
            2,
        )

        content = dest.read_text()
        begin_marker = "// BEGIN testagent generated tests for com.example.service.OrderService#process"
        end_marker = "// END testagent generated tests for com.example.service.OrderService#process"
        assert content.count(begin_marker) == 1
        assert content.count(end_marker) == 1
        assert "assert true;" not in content
        assert "assert 1 + 1 == 2;" in content

    def test_generated_body_with_braces_in_strings_comments_and_text_blocks_is_preserved(self, tmp_path):
        dest = write_test_file(
            BRACE_RICH_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.service.OrderService",
            "process",
            1,
        )

        content = dest.read_text()
        assert 'assertEquals("}", value);' in content
        assert "package fake.body;" in content
        assert "import java.util.Set;" in content
        assert "// block comment with { and }" in content

    def test_non_ascii_header_before_class_does_not_corrupt_output(self, tmp_path):
        dest = write_test_file(
            NON_ASCII_HEADER_GENERATED_TEST_CODE,
            tmp_path,
            "com.example.Calculator",
            "add",
            1,
        )

        content = dest.read_text(encoding="utf-8")
        assert "public class CalculatorTest" in content
        assert "void generatedMethod()" in content

    def test_cleanup_preserves_human_file_with_markers_but_no_banner(self, tmp_path):
        test_file = tmp_path / "src" / "test" / "java" / "com" / "example" / "HumanTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(
            """\
package com.example;

public class HumanTest {
    // BEGIN testagent generated tests for com.example.OrderService#process
    void generatedBlock() {}
    // END testagent generated tests for com.example.OrderService#process
}
""",
            encoding="utf-8",
        )

        deleted = cleanup_generated_tests(tmp_path)

        assert deleted == []
        assert test_file.is_file()


# ---------------------------------------------------------------------------
# build_maven_command / build_gradle_command
# ---------------------------------------------------------------------------

class TestBuildCommands:
    def test_maven_command_structure(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        report_dir = tmp_path / "reports"
        cmd = build_maven_command(tmp_path, "CalculatorTest", "com.example", report_dir)
        assert cmd[0] == "mvn"
        assert "test" in cmd
        assert "jacoco:report" in cmd
        assert any("com.example.CalculatorTest" in arg for arg in cmd)
        assert any(str(report_dir) in arg for arg in cmd)

    def test_maven_command_uses_wrapper(self, tmp_path):
        wrapper = tmp_path / "mvnw"
        wrapper.touch()
        wrapper.chmod(0o755)
        cmd = build_maven_command(tmp_path, "FooTest", "com.example", tmp_path)
        assert cmd[0] == str(wrapper)

    def test_maven_command_no_package(self, tmp_path):
        cmd = build_maven_command(tmp_path, "FooTest", "", tmp_path / "r")
        assert any("FooTest" in arg and "." not in arg.split("=")[-1] for arg in cmd)

    def test_gradle_command_structure(self, tmp_path):
        (tmp_path / "build.gradle").touch()
        report_dir = tmp_path / "reports"
        cmd = build_gradle_command(tmp_path, "CalculatorTest", "com.example", report_dir)
        assert cmd[0] == "gradle"
        assert "test" in cmd
        assert "jacocoTestReport" in cmd
        assert any("com.example.CalculatorTest" in arg for arg in cmd)
        assert any(str(report_dir) in arg for arg in cmd)

    def test_gradle_command_uses_wrapper(self, tmp_path):
        wrapper = tmp_path / "gradlew"
        wrapper.touch()
        wrapper.chmod(0o755)
        cmd = build_gradle_command(tmp_path, "FooTest", "com.example", tmp_path)
        assert cmd[0] == str(wrapper)
