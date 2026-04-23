# Merge Generated Java Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the Java test pipeline so generated tests for different methods in the same source class are accumulated in the corresponding real project test file instead of overwriting each other, and give the generator a concise analyzer-produced summary of any existing test file.

**Architecture:** Keep `TestGenerator` returning a complete Java test class, because the current prompt, extraction, normalization, and refinement loop already depend on that contract. Extend the analyzer so `AnalysisContext` optionally carries an `existing_test_summary` for the corresponding real project test file. Move the new write behavior into the Java executor write layer: resolve the canonical test path from the target class, create a test file when absent, or merge the new generated class body into an existing test file under a target-method block. `test_executor.py` will preserve the merged project test files and validate the accumulated collection after each generation-write-execute loop.

**Tech Stack:** Python 3.10+, pytest, Java/JUnit 5 source text handling, Maven/Gradle execution through the existing executor.

---

## File Structure

- Modify `prompts/java/generate_test.txt`
  - Include an existing test file summary when present, then tighten requirements so each LLM response contains test methods only for the current target method and uses the canonical `<SourceClass>Test` test class.
- Modify `prompts/java/fix_test.txt`
  - Keep refinement output as a complete class, but tell the LLM to preserve target-method-only scope.
- Modify `src/testagent/models.py`
  - Add a small optional `TestFileSummary` model to `AnalysisContext`.
- Create `src/testagent/analyzer/java/test_summary.py`
  - Locate the corresponding real project test file and summarize imports, class signature, class-level object/field declarations, helper method signatures, and all JUnit test method signatures.
- Modify `src/testagent/analyzer/java/__init__.py`
  - Attach the analyzer-produced summary to `AnalysisContext`.
- Modify `tests/test_analyzer/test_java_test_summary.py`
  - Cover missing test file, summary extraction, and analyzer integration.
- Modify `tests/test_generator/test_prompt.py`
  - Assert the prompt includes the existing test file summary and the new target-method-only requirements.
- Modify `src/testagent/executor/java/builder.py`
  - Add canonical test file path resolution based on `class_name`, not generated package text.
  - Add import deduplication and generated class body extraction.
  - Replace `write_test_file()` overwrite behavior with create-or-merge behavior.
  - Mark each target method block so later refinement replaces the same method's previous generated code instead of appending duplicates.
- Modify `src/testagent/executor/java/__init__.py`
  - Preserve existing human test files when `keep_test=False` by restoring pre-existing content instead of deleting the whole file.
  - Keep current `keep_test=True` behavior for real project merged tests.
- Modify `tests/test_executor/test_builder.py`
  - Cover canonical path creation, existing-file merge, import deduplication, and same-target block replacement.
- Modify `tests/test_executor/test_test_executor.py`
  - Cover restoring an existing project test file when `keep_test=False`.
- Modify `test_executor.py`
  - Pass `keep_test=True` to the executor for the full generation-execution pipeline so accumulated test collections remain in the real project.
  - Add a collection validation helper that checks expected test files exist under `src/test/java/<package>/`, contain blocks for successful target methods, and retain one test file per source class.

## Design Decisions

Use the target class as the source of truth for file placement:

```text
com.example.service.OrderService
  -> src/test/java/com/example/service/OrderServiceTest.java
```

The generated code can still include a `package` declaration and imports, but `write_test_file()` must not use the generated package to decide the destination path. That prevents an LLM package mistake from breaking the required source/test directory symmetry.

Use target-method block markers:

```java
    // BEGIN testagent generated tests for com.example.Calculator#add
    @Test
    void testAddPositiveNumbers() {
        Calculator calculator = new Calculator();
        assertEquals(3, calculator.add(1, 2));
    }
    // END testagent generated tests for com.example.Calculator#add
```

When refining the same target method, remove the previous block and insert the refined block. When generating a different method in the same class, append a new block before the test class closing brace. This keeps different target methods isolated while still sharing the enclosing package, imports, class declaration, fields, helper methods, and dependencies.

Do not add a full Java parser dependency for merging. The current project already uses text-based extraction in the executor, and the minimal implementation only needs class body boundaries, imports, and top-level class insertion. Use a small brace scanner in `builder.py` and cover it with focused tests.

## Task 1: Add Analyzer Existing Test Summary

**Files:**
- Modify: `src/testagent/models.py`
- Create: `src/testagent/analyzer/java/test_summary.py`
- Modify: `src/testagent/analyzer/java/__init__.py`
- Test: `tests/test_analyzer/test_java_test_summary.py`

- [ ] **Step 1: Add failing analyzer summary tests**

Create `tests/test_analyzer/test_java_test_summary.py` with:

```python
from pathlib import Path

from testagent.analyzer.java import JavaAnalyzer
from testagent.analyzer.java.test_summary import (
    expected_test_file_path,
    summarize_existing_test_file,
)


def test_expected_test_file_path_matches_source_package_layout(tmp_path):
    path = expected_test_file_path(tmp_path, "com.example.service.OrderService")

    assert path == (
        tmp_path
        / "src"
        / "test"
        / "java"
        / "com"
        / "example"
        / "service"
        / "OrderServiceTest.java"
    )


def test_summarize_existing_test_file_returns_none_when_missing(tmp_path):
    summary = summarize_existing_test_file(tmp_path, "com.example.Calculator")

    assert summary is None


def test_summarize_existing_test_file_extracts_imports_fields_and_test_signatures(tmp_path):
    test_file = tmp_path / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """\
package com.example;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class CalculatorTest {
    private Calculator calculator;

    @BeforeEach
    void setUp() {
        calculator = new Calculator();
    }

    @Test
    void testAddPositiveNumbers() {
        assertEquals(3, calculator.add(1, 2));
    }
}
""",
        encoding="utf-8",
    )

    summary = summarize_existing_test_file(tmp_path, "com.example.Calculator")

    assert summary is not None
    assert summary.file_path == test_file
    assert "import org.junit.jupiter.api.Test;" in summary.imports
    assert summary.class_signature == "public class CalculatorTest"
    assert "private Calculator calculator;" in summary.field_declarations
    assert any("void setUp()" in sig for sig in summary.helper_method_signatures)
    assert any("void testAddPositiveNumbers()" in sig for sig in summary.test_method_signatures)


def test_java_analyzer_attaches_existing_test_summary(sample_project):
    test_file = sample_project / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        """\
package com.example;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    private Calculator calculator = new Calculator();

    @Test
    void testExistingAdd() {
        calculator.add(1, 2);
    }
}
""",
        encoding="utf-8",
    )

    ctx = JavaAnalyzer(sample_project).analyze("com.example.Calculator", "add")

    assert ctx.existing_test_summary is not None
    assert ctx.existing_test_summary.class_signature == "public class CalculatorTest"
    assert any("testExistingAdd" in sig for sig in ctx.existing_test_summary.test_method_signatures)
```

- [ ] **Step 2: Run analyzer summary tests and verify failure**

Run:

```bash
pytest tests/test_analyzer/test_java_test_summary.py -q
```

Expected: fail because `test_summary.py` and `AnalysisContext.existing_test_summary` do not exist.

- [ ] **Step 3: Add `TestFileSummary` to `src/testagent/models.py`**

Insert this dataclass before `AnalysisContext`:

```python
@dataclass
class TestFileSummary:
    """真实项目中已有测试文件的结构摘要。"""

    file_path: Path
    imports: list[str] = field(default_factory=list)
    class_signature: str = ""
    field_declarations: list[str] = field(default_factory=list)
    helper_method_signatures: list[str] = field(default_factory=list)
    test_method_signatures: list[str] = field(default_factory=list)
```

Then add this field to `AnalysisContext`:

```python
    existing_test_summary: TestFileSummary | None = None
```

- [ ] **Step 4: Create `src/testagent/analyzer/java/test_summary.py`**

Create the file with:

```python
"""Summarize existing Java test files for prompt context."""

from __future__ import annotations

from pathlib import Path

import tree_sitter as ts

from testagent.analyzer.java.java_parser import (
    _find_class_node,
    _node_text,
    extract_imports,
    parse_source,
)
from testagent.models import TestFileSummary

_TEST_SRC_ROOT = Path("src") / "test" / "java"


def expected_test_file_path(project_path: Path, class_name: str) -> Path:
    """根据被测类名计算真实项目中对应测试文件路径。"""
    simple_class = class_name.rsplit(".", 1)[-1]
    package = class_name.rsplit(".", 1)[0] if "." in class_name else ""
    test_root = project_path / _TEST_SRC_ROOT
    if package:
        return test_root / Path(package.replace(".", "/")) / f"{simple_class}Test.java"
    return test_root / f"{simple_class}Test.java"


def _class_signature(class_node: ts.Node) -> str:
    """提取 class 声明签名，不包含类体。"""
    source = _node_text(class_node)
    return source.split("{", 1)[0].strip()


def _method_signature(method_node: ts.Node) -> str:
    """提取方法签名，不包含方法体。"""
    source = _node_text(method_node)
    head = source.split("{", 1)[0].strip()
    return f"{head};" if not head.endswith(";") else head


def _has_test_annotation(method_node: ts.Node) -> bool:
    """判断方法声明是否带有 JUnit @Test 注解。"""
    return "@Test" in _node_text(method_node).split("{", 1)[0]


def _class_body_children(class_node: ts.Node) -> list[ts.Node]:
    """返回 class_body 下的直接子节点。"""
    for child in class_node.children:
        if child.type == "class_body":
            return list(child.children)
    return []


def summarize_existing_test_file(project_path: Path, class_name: str) -> TestFileSummary | None:
    """读取并摘要真实项目中目标类对应的测试文件；文件不存在时返回 None。"""
    test_file = expected_test_file_path(project_path, class_name)
    if not test_file.is_file():
        return None

    source_bytes = test_file.read_bytes()
    root = parse_source(source_bytes)
    simple_test_class = f"{class_name.rsplit('.', 1)[-1]}Test"
    class_node = _find_class_node(root, simple_test_class)
    if class_node is None:
        return TestFileSummary(file_path=test_file, imports=extract_imports(root))

    fields: list[str] = []
    helper_methods: list[str] = []
    test_methods: list[str] = []

    for child in _class_body_children(class_node):
        if child.type == "field_declaration":
            fields.append(_node_text(child).strip())
        elif child.type == "method_declaration":
            signature = _method_signature(child)
            if _has_test_annotation(child):
                test_methods.append(signature)
            else:
                helper_methods.append(signature)

    return TestFileSummary(
        file_path=test_file,
        imports=extract_imports(root),
        class_signature=_class_signature(class_node),
        field_declarations=fields,
        helper_method_signatures=helper_methods,
        test_method_signatures=test_methods,
    )
```

- [ ] **Step 5: Attach summary in `JavaAnalyzer.analyze()`**

Update imports in `src/testagent/analyzer/java/__init__.py`:

```python
from testagent.analyzer.java.test_summary import summarize_existing_test_file
```

Then pass the summary when constructing `AnalysisContext`:

```python
        return AnalysisContext(
            target=target,
            dependencies=dependencies,
            imports=result.imports,
            package=result.package,
            existing_test_summary=summarize_existing_test_file(
                self.project_path,
                class_name,
            ),
        )
```

- [ ] **Step 6: Run analyzer tests and verify pass**

Run:

```bash
pytest tests/test_analyzer/test_java_test_summary.py tests/test_analyzer/test_java_analyzer.py -q
```

Expected: all selected analyzer tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/testagent/models.py src/testagent/analyzer/java/test_summary.py src/testagent/analyzer/java/__init__.py tests/test_analyzer/test_java_test_summary.py
git commit -m "feat: summarize existing Java test files"
```

## Task 2: Include Existing Test Summary in Generator Prompt

**Files:**
- Modify: `prompts/java/generate_test.txt`
- Modify: `prompts/java/fix_test.txt`
- Test: `tests/test_generator/test_prompt.py`

- [ ] **Step 1: Add failing prompt tests**

Append these tests to `tests/test_generator/test_prompt.py`:

```python
def test_generate_prompt_includes_existing_test_summary(sample_context, prompts_dir):
    sample_context.existing_test_summary = TestFileSummary(
        file_path=Path("/project/src/test/java/com/example/CalculatorTest.java"),
        imports=[
            "import org.junit.jupiter.api.Test;",
            "import static org.junit.jupiter.api.Assertions.assertEquals;",
        ],
        class_signature="public class CalculatorTest",
        field_declarations=["private Calculator calculator;"],
        helper_method_signatures=["@BeforeEach\nvoid setUp();"],
        test_method_signatures=["@Test\nvoid testExistingAdd();"],
    )

    messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
    content = messages[0]["content"]

    assert "## Existing Test File Summary" in content
    assert "CalculatorTest.java" in content
    assert "private Calculator calculator;" in content
    assert "void testExistingAdd();" in content


def test_generate_prompt_requires_target_method_only_tests(sample_context, prompts_dir):
    messages = build_generate_prompt(sample_context, prompts_dir=prompts_dir)
    content = messages[0]["content"]

    assert "only for the target method" in content
    assert "Do not generate tests for other methods" in content
    assert "same package as the target class" in content


def test_refine_prompt_preserves_target_method_only_scope(
    sample_context,
    previous_test,
    compile_fail_result,
    prompts_dir,
):
    messages = build_refine_prompt(
        sample_context,
        previous_test,
        compile_fail_result,
        prompts_dir=prompts_dir,
    )
    content = messages[0]["content"]

    assert "only for the target method" in content
    assert "Do not add tests for other methods" in content
    assert "complete Java test class" in content
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run:

```bash
pytest tests/test_generator/test_prompt.py -q
```

Expected: the new tests fail because the current prompts do not include the existing test summary or target-method-only wording.

- [ ] **Step 3: Import `TestFileSummary` in prompt tests**

Update `tests/test_generator/test_prompt.py` imports:

```python
from testagent.models import (
    AnalysisContext,
    CoverageReport,
    Dependency,
    GeneratedTest,
    TargetMethod,
    TestFileSummary,
    TestResult,
)
```

- [ ] **Step 4: Pass existing summary to prompt rendering**

Update `build_generate_prompt()` in `src/testagent/generator/prompt.py` so `template.render(...)` includes:

```python
        existing_test_summary=context.existing_test_summary,
```

- [ ] **Step 5: Update `prompts/java/generate_test.txt`**

Insert this section after the import statements section and before `## Requirements`:

```text
{% if existing_test_summary %}
## Existing Test File Summary

The corresponding real project test file already exists:
`{{ existing_test_summary.file_path }}`

### Existing Imports

```java
{% for imp in existing_test_summary.imports %}
{{ imp }}
{% endfor %}
```

### Existing Test Class

```java
{{ existing_test_summary.class_signature }}
```

{% if existing_test_summary.field_declarations %}
### Existing Class-Level Objects and Fields

```java
{% for field in existing_test_summary.field_declarations %}
{{ field }}
{% endfor %}
```
{% endif %}

{% if existing_test_summary.helper_method_signatures %}
### Existing Shared Helper Method Signatures

```java
{% for sig in existing_test_summary.helper_method_signatures %}
{{ sig }}
{% endfor %}
```
{% endif %}

{% if existing_test_summary.test_method_signatures %}
### Existing Test Method Signatures

```java
{% for sig in existing_test_summary.test_method_signatures %}
{{ sig }}
{% endfor %}
```
{% endif %}

Use this summary to avoid duplicating existing imports, fields, helpers, or test method names. You may reuse compatible existing class-level objects and helper methods.
{% endif %}
```

Replace the current requirements block with:

```text
## Requirements

1. Generate a complete JUnit 5 test class that compiles and runs independently.
2. Name the test class exactly `{{ target.class_name.split('.')[-1] }}Test` (e.g. if the class is `Calculator`, name it `CalculatorTest`).
3. Put the test class in the same package as the target class.
4. Generate tests only for the target method `{{ target.method_name }}`.
5. Do not generate tests for other methods in the target class.
6. Use `@Test` annotations from `org.junit.jupiter.api`.
7. Cover normal cases, edge cases, and boundary conditions for the target method.
8. Use descriptive test method names that include or clearly refer to `{{ target.method_name }}`.
9. Include necessary imports.
10. If the method depends on external services or complex objects, use Mockito for mocking.
11. If an existing test file summary is provided, avoid duplicate imports, fields, helper methods, and test method names.
12. Output ONLY the complete Java test class source code, wrapped in a single ```java code block.
```

- [ ] **Step 6: Update `prompts/java/fix_test.txt`**

Replace the current requirements block with:

```text
## Requirements

1. Output the COMPLETE fixed test class, not just the changed parts.
2. Keep the test class name exactly `{{ target.class_name.split('.')[-1] }}Test`.
3. Keep the test class in the same package as the target class.
4. Keep tests scoped only for the target method `{{ target.method_name }}`.
5. Do not add tests for other methods in the target class.
6. Ensure the test compiles and all assertions are correct.
7. Maintain or improve coverage for the target method.
8. Output ONLY the complete Java test class source code, wrapped in a single ```java code block.
```

- [ ] **Step 7: Run prompt tests and verify pass**

Run:

```bash
pytest tests/test_generator/test_prompt.py -q
```

Expected: all prompt tests pass.

- [ ] **Step 8: Commit**

```bash
git add prompts/java/generate_test.txt prompts/java/fix_test.txt tests/test_generator/test_prompt.py
git commit -m "test: specify target-method scoped Java generation"
```

## Task 3: Add Java Test File Merge Helpers

**Files:**
- Modify: `src/testagent/executor/java/builder.py`
- Test: `tests/test_executor/test_builder.py`

- [ ] **Step 1: Add failing builder tests**

Update the import list in `tests/test_executor/test_builder.py`:

```python
from testagent.executor.java.builder import (
    _make_banner,
    _resolve_gradle,
    _resolve_mvn,
    build_gradle_command,
    build_maven_command,
    detect_build_tool,
    expected_test_file_path,
    extract_class_name_from_code,
    extract_package_from_code,
    find_test_source_dir,
    write_test_file,
)
```

Append these tests inside `class TestWriteTestFile`:

```python
    def test_expected_test_file_path_uses_target_class_package(self, tmp_path):
        path = expected_test_file_path(tmp_path, "com.example.service.OrderService")

        assert path == (
            tmp_path
            / "src"
            / "test"
            / "java"
            / "com"
            / "example"
            / "service"
            / "OrderServiceTest.java"
        )

    def test_creates_file_at_source_matching_package_path(self, tmp_path):
        code = """\
package wrong.package_name;

import org.junit.jupiter.api.Test;

public class WrongNameTest {
    @Test
    void testProcess() {}
}
"""

        dest = write_test_file(
            code,
            tmp_path,
            class_name="com.example.service.OrderService",
            method_name="process",
            iteration=1,
        )

        assert dest == (
            tmp_path
            / "src"
            / "test"
            / "java"
            / "com"
            / "example"
            / "service"
            / "OrderServiceTest.java"
        )
        content = dest.read_text(encoding="utf-8")
        assert "package com.example.service;" in content
        assert "class OrderServiceTest" in content
        assert "wrong.package_name" not in content

    def test_merges_new_method_block_into_existing_test_file(self, tmp_path):
        existing = tmp_path / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
        existing.parent.mkdir(parents=True)
        existing.write_text(
            """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class CalculatorTest {
    @Test
    void existingHumanTest() {
        assertEquals(4, 2 + 2);
    }
}
""",
            encoding="utf-8",
        )

        divide_code = """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertThrows;

public class CalculatorTest {
    @Test
    void testDivideByZero() {
        Calculator calculator = new Calculator();
        assertThrows(ArithmeticException.class, () -> calculator.divide(1, 0));
    }
}
"""

        dest = write_test_file(
            divide_code,
            tmp_path,
            class_name="com.example.Calculator",
            method_name="divide",
            iteration=1,
        )

        content = dest.read_text(encoding="utf-8")
        assert "void existingHumanTest()" in content
        assert "void testDivideByZero()" in content
        assert "BEGIN testagent generated tests for com.example.Calculator#divide" in content
        assert "import static org.junit.jupiter.api.Assertions.assertEquals;" in content
        assert "import static org.junit.jupiter.api.Assertions.assertThrows;" in content

    def test_replaces_same_target_block_on_refinement(self, tmp_path):
        first = """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class CalculatorTest {
    @Test
    void testAddOriginal() {
        Calculator calculator = new Calculator();
        assertEquals(3, calculator.add(1, 2));
    }
}
"""
        second = """\
package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

public class CalculatorTest {
    @Test
    void testAddRefined() {
        Calculator calculator = new Calculator();
        assertEquals(0, calculator.add(1, -1));
    }
}
"""

        write_test_file(first, tmp_path, "com.example.Calculator", "add", 1)
        dest = write_test_file(second, tmp_path, "com.example.Calculator", "add", 2)

        content = dest.read_text(encoding="utf-8")
        assert "void testAddRefined()" in content
        assert "void testAddOriginal()" not in content
        assert content.count("BEGIN testagent generated tests for com.example.Calculator#add") == 1
```

- [ ] **Step 2: Run builder tests and verify failure**

Run:

```bash
pytest tests/test_executor/test_builder.py::TestWriteTestFile -q
```

Expected: failures because `expected_test_file_path()` does not exist and `write_test_file()` still overwrites rather than merges.

- [ ] **Step 3: Add helper functions to `src/testagent/executor/java/builder.py`**

Insert this code after `find_test_source_dir()`:

```python
def _canonical_test_class_name(class_name: str) -> str:
    """根据被测类名生成规范测试类名。"""
    simple = class_name.rsplit(".", 1)[-1]
    return f"{simple}Test"


def _target_package(class_name: str) -> str:
    """从全限定类名中提取目标 package。"""
    if "." not in class_name:
        return ""
    return class_name.rsplit(".", 1)[0]


def expected_test_file_path(project_path: Path, class_name: str) -> Path:
    """根据被测类名计算真实项目中对应测试文件路径。"""
    package = _target_package(class_name)
    test_src_root = find_test_source_dir(project_path)
    dest_dir = test_src_root / Path(package.replace(".", "/")) if package else test_src_root
    return dest_dir / f"{_canonical_test_class_name(class_name)}.java"
```

Insert this code before `write_test_file()`:

```python
def _normalize_generated_test_code(test_code: str, class_name: str) -> str:
    """将生成测试代码的 package 和类名修正为目标类对应的测试文件约定。"""
    package = _target_package(class_name)
    test_class = _canonical_test_class_name(class_name)

    code = re.sub(
        r"(?m)^\s*package\s+[\w.]+\s*;\s*\n*",
        "",
        test_code,
        count=1,
    ).strip()

    code, count = re.subn(
        r"(?m)^(\s*(?:public\s+)?class\s+)(\w+)",
        lambda m: m.group(1) + test_class,
        code,
        count=1,
    )
    if count == 0:
        raise ValueError("Cannot find class declaration in generated test code.")

    if package:
        return f"package {package};\n\n{code}\n"
    return f"{code}\n"


def _extract_imports(test_code: str) -> list[str]:
    """提取 import 语句并保持原始顺序。"""
    return re.findall(r"(?m)^\s*import\s+[^;]+;", test_code)


def _find_class_body_bounds(test_code: str) -> tuple[int, int]:
    """返回第一个 class 的 body 起止位置，位置不包含外层花括号。"""
    class_match = re.search(r"(?m)^\s*(?:public\s+)?class\s+\w+[^{]*\{", test_code)
    if not class_match:
        raise ValueError("Cannot find class declaration in generated test code.")

    open_brace = test_code.find("{", class_match.start())
    depth = 0
    for index in range(open_brace, len(test_code)):
        char = test_code[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return open_brace + 1, index
    raise ValueError("Cannot find closing brace for generated test class.")


def _extract_class_body(test_code: str) -> str:
    """提取生成测试类的类体内容。"""
    start, end = _find_class_body_bounds(test_code)
    return test_code[start:end].strip("\n")


def _method_block_marker(class_name: str, method_name: str, start: bool) -> str:
    """生成目标方法测试块的边界标记。"""
    edge = "BEGIN" if start else "END"
    return f"// {edge} testagent generated tests for {class_name}#{method_name}"


def _make_method_block(test_code: str, class_name: str, method_name: str) -> str:
    """将生成测试类体包装为可替换的目标方法测试块。"""
    body = _extract_class_body(test_code).rstrip()
    start = _method_block_marker(class_name, method_name, True)
    end = _method_block_marker(class_name, method_name, False)
    if body:
        return f"    {start}\n{body}\n    {end}\n"
    return f"    {start}\n    {end}\n"


def _remove_method_block(existing_code: str, class_name: str, method_name: str) -> str:
    """删除同一目标方法之前插入的测试块，用于 refinement 覆盖旧版本。"""
    start = re.escape(_method_block_marker(class_name, method_name, True))
    end = re.escape(_method_block_marker(class_name, method_name, False))
    pattern = rf"(?ms)^[ \t]*{start}\n.*?^[ \t]*{end}\n?"
    return re.sub(pattern, "", existing_code, count=1)


def _merge_imports(existing_code: str, generated_code: str) -> str:
    """将生成测试中的新 import 合并到现有测试文件中，并去重。"""
    existing_imports = set(_extract_imports(existing_code))
    new_imports = [imp for imp in _extract_imports(generated_code) if imp not in existing_imports]
    if not new_imports:
        return existing_code

    insert_text = "\n".join(new_imports) + "\n"
    imports = list(re.finditer(r"(?m)^\s*import\s+[^;]+;", existing_code))
    if imports:
        insert_pos = imports[-1].end()
        return existing_code[:insert_pos] + "\n" + insert_text + existing_code[insert_pos:]

    package_match = re.search(r"(?m)^\s*package\s+[\w.]+\s*;", existing_code)
    if package_match:
        insert_pos = package_match.end()
        return existing_code[:insert_pos] + "\n\n" + insert_text + existing_code[insert_pos:]

    return insert_text + existing_code


def _insert_method_block(existing_code: str, block: str) -> str:
    """把目标方法测试块插入到现有测试类最后一个外层右花括号之前。"""
    _start, end = _find_class_body_bounds(existing_code)
    prefix = existing_code[:end].rstrip()
    suffix = existing_code[end:]
    return f"{prefix}\n\n{block}{suffix}"


def _replace_class_body(test_code: str, block: str) -> str:
    """用目标方法测试块替换生成测试类的原始类体。"""
    start, end = _find_class_body_bounds(test_code)
    prefix = test_code[:start].rstrip()
    suffix = test_code[end:]
    return f"{prefix}\n{block}{suffix}"
```

- [ ] **Step 4: Replace `write_test_file()` implementation**

Replace the body of `write_test_file()` with:

```python
    normalized = _normalize_generated_test_code(test_code, class_name)
    dest_file = expected_test_file_path(project_path, class_name)
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    banner = _make_banner(class_name, method_name, iteration)
    block = _make_method_block(normalized, class_name, method_name)

    if dest_file.is_file():
        existing = dest_file.read_text(encoding="utf-8", errors="replace")
        merged = _remove_method_block(existing, class_name, method_name)
        merged = _merge_imports(merged, normalized)
        merged = _insert_method_block(merged, block)
        dest_file.write_text(merged, encoding="utf-8")
        logger.info("Merged generated test into: %s", dest_file)
        return dest_file

    pkg_match = re.search(r"^\s*package\s+[\w.]+\s*;", normalized, re.MULTILINE)
    if pkg_match:
        annotated = normalized[:pkg_match.start()] + banner + normalized[pkg_match.start():]
    else:
        annotated = banner + normalized
    annotated = _replace_class_body(annotated, block)
    dest_file.write_text(annotated, encoding="utf-8")
    logger.info("Wrote test file: %s", dest_file)
    return dest_file
```

- [ ] **Step 5: Run builder tests and verify pass**

Run:

```bash
pytest tests/test_executor/test_builder.py::TestWriteTestFile -q
```

Expected: all `TestWriteTestFile` tests pass.

- [ ] **Step 6: Run full builder tests**

Run:

```bash
pytest tests/test_executor/test_builder.py -q
```

Expected: all builder tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/testagent/executor/java/builder.py tests/test_executor/test_builder.py
git commit -m "feat: merge generated Java tests by target method"
```

## Task 4: Make Executor Cleanup Safe for Existing Test Files

**Files:**
- Modify: `src/testagent/executor/java/__init__.py`
- Test: `tests/test_executor/test_test_executor.py`

- [ ] **Step 1: Add failing executor restoration test**

Append this test inside `class TestExecuteSuccess` in `tests/test_executor/test_test_executor.py`:

```python
    @patch("testagent.executor.java.run_build", return_value=(0, MAVEN_SUCCESS_OUTPUT))
    def test_existing_test_file_restored_when_keep_test_false(self, mock_run, maven_project, tmp_path):
        existing = maven_project / "src" / "test" / "java" / "com" / "example" / "CalculatorTest.java"
        existing.parent.mkdir(parents=True)
        original = """\
package com.example;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    @Test
    void existingHumanTest() {}
}
"""
        existing.write_text(original, encoding="utf-8")

        executor = TestExecutor(maven_project, reports_dir=tmp_path / "r", keep_test=False)
        executor.execute(_make_test(), _make_context())

        assert existing.read_text(encoding="utf-8") == original
```

- [ ] **Step 2: Run executor test and verify failure**

Run:

```bash
pytest tests/test_executor/test_test_executor.py::TestExecuteSuccess::test_existing_test_file_restored_when_keep_test_false -q
```

Expected: fail because the current executor deletes the test file when `keep_test=False`.

- [ ] **Step 3: Update imports in `src/testagent/executor/java/__init__.py`**

Add `expected_test_file_path` to the builder import list:

```python
from testagent.executor.java.builder import (
    build_gradle_command,
    build_maven_command,
    cleanup_generated_tests,
    detect_build_tool,
    expected_test_file_path,
    extract_class_name_from_code,
    extract_package_from_code,
    run_build,
    write_test_file,
)
```

- [ ] **Step 4: Capture pre-existing test file state before writing**

Insert this code after `method_name = context.target.method_name` in `JavaTestExecutor.execute()`:

```python
        expected_file = expected_test_file_path(self.project_path, class_name)
        preexisting_test_code: str | None = None
        if expected_file.is_file():
            preexisting_test_code = expected_file.read_text(encoding="utf-8", errors="replace")
```

- [ ] **Step 5: Replace cleanup logic**

Replace the current `finally` cleanup block with:

```python
        finally:
            if not self.keep_test and test_file and test_file.is_file():
                if preexisting_test_code is None:
                    test_file.unlink()
                    logger.info("Removed test file: %s", test_file)
                else:
                    test_file.write_text(preexisting_test_code, encoding="utf-8")
                    logger.info("Restored pre-existing test file: %s", test_file)
```

- [ ] **Step 6: Run executor tests and verify pass**

Run:

```bash
pytest tests/test_executor/test_test_executor.py -q
```

Expected: all executor tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/testagent/executor/java/__init__.py tests/test_executor/test_test_executor.py
git commit -m "fix: restore existing Java tests after temporary execution"
```

## Task 5: Keep and Validate Merged Test Collections in `test_executor.py`

**Files:**
- Modify: `test_executor.py`

- [ ] **Step 1: Add collection validation helpers**

Add these helper functions near the display helper section in `test_executor.py`:

```python
def _expected_test_file(project_path: Path, class_name: str) -> Path:
    """根据被测类名推导真实项目中的测试文件路径。"""
    simple_class = class_name.rsplit(".", 1)[-1]
    package = class_name.rsplit(".", 1)[0] if "." in class_name else ""
    test_root = project_path / "src" / "test" / "java"
    if package:
        return test_root / Path(package.replace(".", "/")) / f"{simple_class}Test.java"
    return test_root / f"{simple_class}Test.java"


def _method_block_marker(class_name: str, method_name: str) -> str:
    """生成 executor 写入测试集合时使用的目标方法块标记。"""
    return f"BEGIN testagent generated tests for {class_name}#{method_name}"


def _validate_test_collection(project_path: Path, successful_targets: list[tuple[str, str]]) -> bool:
    """验证生成的测试集合是否写入真实项目并保持源/test 目录结构一致。"""
    ok = True
    for class_name, method_name in successful_targets:
        expected = _expected_test_file(project_path, class_name)
        if not expected.is_file():
            print(f"  Collection check FAILED: missing {expected}")
            ok = False
            continue
        content = expected.read_text(encoding="utf-8", errors="replace")
        marker = _method_block_marker(class_name, method_name)
        if marker not in content:
            print(f"  Collection check FAILED: missing marker {class_name}#{method_name} in {expected}")
            ok = False
    if ok and successful_targets:
        print("  Collection check: generated tests are present in project test files.")
    return ok
```

- [ ] **Step 2: Force the full pipeline to keep merged real-project test files**

Replace executor construction in `main()`:

```python
    executor = create_executor(
        config.language,
        project_path,
        reports_dir=args.reports_dir,
        keep_test=config.keep_test,
    )
```

with:

```python
    executor = create_executor(
        config.language,
        project_path,
        reports_dir=args.reports_dir,
        keep_test=True,
    )
```

Replace the printed line:

```python
    print(f"  Keep test:     {config.keep_test}")
```

with:

```python
    print("  Keep test:     True (required for merged generated test collections)")
```

- [ ] **Step 3: Validate the collection after each successful target**

Replace the target loop result append in `main()`:

```python
        results.append((label, ok))
```

with:

```python
        results.append((label, ok))
        successful_targets = [(cls, method) for (cls, method), (_, passed) in zip(targets, results) if passed]
        if successful_targets:
            collection_ok = _validate_test_collection(project_path, successful_targets)
            if not collection_ok:
                results[-1] = (label, False)
```

- [ ] **Step 4: Run syntax check**

Run:

```bash
python -m py_compile test_executor.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add test_executor.py
git commit -m "feat: keep and validate merged Java test collections"
```

## Task 6: End-to-End CPU Verification Loop

**Files:**
- Uses existing code and tests only.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
pytest tests/test_generator/test_prompt.py tests/test_executor/test_builder.py tests/test_executor/test_test_executor.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run a real Java build smoke test without LLM if possible**

If Maven is available locally, run the existing executor tests against the sample Maven project through mocked build paths first:

```bash
pytest tests/test_executor -q
```

Expected: all executor tests pass.

- [ ] **Step 4: Run one actual generation-write-execute loop only when API credentials are configured**

Check whether the API key is configured:

```bash
python - <<'PY'
from testagent.config import load_config
cfg = load_config()
print("configured" if cfg.api_key else "missing")
PY
```

Expected when credentials are absent: print `missing`; skip this step and report that LLM-backed validation still needs credentials.

Expected when credentials are present: run one small target first:

```bash
python test_executor.py --target Calculator.add --max-iterations 1 --min-branch-coverage 0.0
```

Then inspect:

```bash
test -f under_test/sample-java-project/src/test/java/com/example/CalculatorTest.java
rg -n "BEGIN testagent generated tests for com.example.Calculator#add|void test.*Add" under_test/sample-java-project/src/test/java/com/example/CalculatorTest.java
```

Expected: the file exists under `src/test/java/com/example/CalculatorTest.java`, contains the `add` marker, and contains at least one generated JUnit test method for `add`.

- [ ] **Step 5: Run the multi-method collection loop when credentials are configured**

Run:

```bash
python test_executor.py --target Calculator.divide --max-iterations 1 --min-branch-coverage 0.0
```

Then inspect:

```bash
rg -n "BEGIN testagent generated tests for com.example.Calculator#add|BEGIN testagent generated tests for com.example.Calculator#divide" under_test/sample-java-project/src/test/java/com/example/CalculatorTest.java
```

Expected: the same `CalculatorTest.java` file contains separate blocks for `add` and `divide`; the directory structure mirrors `src/main/java/com/example/Calculator.java`.

- [ ] **Step 6: Repeat refinement only if the generated collection fails compile or structure validation**

If `test_executor.py` reports compile failure, failed tests, missing markers, or missing files, rerun the smallest failing target with one more iteration:

```bash
python test_executor.py --target Calculator.divide --max-iterations 2 --min-branch-coverage 0.0
```

Expected: the target method block for `divide` is replaced, not duplicated. Confirm:

```bash
rg -c "BEGIN testagent generated tests for com.example.Calculator#divide" under_test/sample-java-project/src/test/java/com/example/CalculatorTest.java
```

Expected output:

```text
1
```

- [ ] **Step 7: Commit verification-only documentation updates if any were needed**

If no docs changed during verification, do not commit. If the README needs a brief note about merged project test files, add only this line under the `test_executor.py` section and commit it:

```markdown
Generated Java tests are merged into the corresponding real project test file under `src/test/java/<package>/<ClassName>Test.java`.
```

Commit:

```bash
git add README.md
git commit -m "docs: document merged Java test output"
```

## Self-Review

Spec coverage:
- Detect whether the corresponding real project test file exists: covered by `expected_test_file_path()` and `write_test_file()`.
- Provide an analyzer-produced existing test file summary to the generation prompt: covered by `TestFileSummary`, `summarize_existing_test_file()`, `AnalysisContext.existing_test_summary`, and prompt tests.
- Create the test file when absent: covered by Task 2 creation tests and implementation.
- Edit existing test file by appending new generated test cases: covered by Task 2 merge tests.
- Directory structure mirrors source package: covered by canonical path tests and `test_executor.py` validation.
- Different target methods stay isolated: covered by target-method block markers and same-target replacement tests.
- Shared imports/classes/helpers remain possible: imports are deduped at file level and class-level body content is preserved inside the shared test class.
- Minimal changes to generator, executor, and `test_executor.py`: generator changes are prompt-only; executor changes are localized to Java builder and cleanup; `test_executor.py` only keeps and validates merged files.
- Loop validation of generation-write-execute: covered by existing refinement loop plus Task 5 structure and compile validation commands.

Placeholder scan:
- No task uses deferred placeholder wording.
- Each code-changing step includes exact code to add or replace.

Type consistency:
- `expected_test_file_path(project_path: Path, class_name: str) -> Path` is defined in Task 2 and imported by Task 3.
- Marker text in `builder.py` and `test_executor.py` intentionally matches: `BEGIN testagent generated tests for {class_name}#{method_name}`.
