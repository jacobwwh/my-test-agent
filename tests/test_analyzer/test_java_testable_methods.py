# -*- coding: utf-8 -*-
"""Tests for Java testable method discovery."""

from pathlib import Path

from testagent.analyzer.java import JavaAnalyzer
from testagent.analyzer.java.java_parser import list_testable_methods


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_testable_methods_filters_non_testable_members(tmp_path):
    _write(
        tmp_path / "src" / "main" / "java" / "com" / "example" / "Sample.java",
        """\
package com.example;

public class Sample {
    public void publicMethod() {}
    protected void protectedMethod() {}
    void packagePrivateMethod() {}
    public static int staticMethod() { return 1; }
    private void privateHelper() {}
    native void nativeMethod();
}
""",
    )
    _write(
        tmp_path / "src" / "main" / "java" / "com" / "example" / "AbstractThing.java",
        """\
package com.example;

public abstract class AbstractThing {
    public abstract void abstractMethod();
    public void concreteMethod() {}
}
""",
    )
    _write(
        tmp_path / "src" / "main" / "java" / "com" / "example" / "Gateway.java",
        """\
package com.example;

public interface Gateway {
    void call();
}
""",
    )
    _write(
        tmp_path / "src" / "test" / "java" / "com" / "example" / "SampleTest.java",
        """\
package com.example;

public class SampleTest {
    public void testShouldNotBeDiscovered() {}
}
""",
    )

    assert list_testable_methods(tmp_path) == [
        ("com.example.AbstractThing", "concreteMethod"),
        ("com.example.Sample", "publicMethod"),
        ("com.example.Sample", "protectedMethod"),
        ("com.example.Sample", "packagePrivateMethod"),
        ("com.example.Sample", "staticMethod"),
    ]


def test_java_analyzer_exposes_testable_method_discovery(sample_project):
    targets = JavaAnalyzer(sample_project).list_testable_methods()

    assert ("com.example.Calculator", "add") in targets
    assert ("com.example.Calculator", "divide") in targets
    assert ("com.example.service.OrderService", "process") in targets
    assert ("com.example.service.OrderService", "findOrder") in targets
    assert ("com.example.service.OrderService", "calculateTotal") in targets
    assert all(not class_name.endswith("Test") for class_name, _method_name in targets)
