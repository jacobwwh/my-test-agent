"""Tests for Java code extraction from LLM responses."""

import pytest

from testagent.generator.test_generator import extract_java_code


class TestExtractJavaCode:
    """Tests for the extract_java_code helper."""

    def test_extracts_from_java_fence(self):
        text = (
            "Here is the test:\n\n"
            "```java\n"
            "import org.junit.jupiter.api.Test;\n"
            "\n"
            "public class FooTest {\n"
            "    @Test\n"
            "    void testFoo() {}\n"
            "}\n"
            "```\n"
            "\nHope this helps!"
        )
        result = extract_java_code(text)
        assert "public class FooTest" in result
        assert "@Test" in result
        assert "```" not in result

    def test_extracts_from_generic_fence(self):
        text = (
            "```\n"
            "public class BarTest {\n"
            "    @Test void testBar() {}\n"
            "}\n"
            "```"
        )
        result = extract_java_code(text)
        assert "public class BarTest" in result

    def test_prefers_java_fence_over_generic(self):
        text = (
            "```\n"
            "generic block\n"
            "```\n"
            "\n"
            "```java\n"
            "java block\n"
            "```"
        )
        result = extract_java_code(text)
        assert result == "java block"

    def test_returns_raw_text_when_no_fence(self):
        text = "public class RawTest { @Test void test() {} }"
        result = extract_java_code(text)
        assert result == text.strip()

    def test_handles_empty_code_block(self):
        text = "```java\n\n```"
        result = extract_java_code(text)
        assert result == ""

    def test_handles_multiline_code(self):
        code = (
            "package com.example;\n"
            "\n"
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.*;\n"
            "\n"
            "public class CalcTest {\n"
            "    @Test\n"
            "    void testAdd() {\n"
            "        assertEquals(3, 1 + 2);\n"
            "    }\n"
            "\n"
            "    @Test\n"
            "    void testSubtract() {\n"
            "        assertEquals(1, 3 - 2);\n"
            "    }\n"
            "}"
        )
        text = f"Sure, here you go:\n\n```java\n{code}\n```\n\nLet me know if you need changes."
        result = extract_java_code(text)
        assert result == code

    def test_extracts_first_java_block_when_multiple(self):
        text = (
            "```java\nfirst block\n```\n"
            "```java\nsecond block\n```"
        )
        result = extract_java_code(text)
        assert result == "first block"
