# 测试执行模块文档

## 概述

测试执行模块（`testagent.executor`）负责将 Generator 生成的测试代码写入目标项目，通过构建工具编译并运行测试，解析构建输出，最后读取覆盖率报告——将这些结果封装为 `TestResult` 返回给上层的迭代精炼循环。当前实现支持 Java（Maven/Gradle + JaCoCo）；其他语言通过工厂函数扩展。

模块结构如下：

| 文件 | 职责 |
|------|------|
| `executor/__init__.py` | 工厂函数 `create_executor()` 及向后兼容的 `TestExecutor` 导出 |
| `executor/base.py` | 抽象基类 `BaseExecutor` |
| `executor/java/__init__.py` | Java 实现：`JavaTestExecutor`（别名 `TestExecutor`） |
| `executor/java/builder.py` | 构建工具检测、测试文件写入、命令构造与执行 |
| `executor/java/runner.py` | 纯函数：解析 Maven / Gradle 构建输出 |
| `executor/java/coverage.py` | 解析 JaCoCo XML 报告，提取覆盖率数据 |

---

## 模块结构

```
src/testagent/executor/
├── __init__.py          # 工厂函数 create_executor()，向后兼容导出 TestExecutor
├── base.py              # 抽象基类 BaseExecutor
└── java/
    ├── __init__.py      # JavaTestExecutor（别名 TestExecutor）
    ├── builder.py       # 构建工具检测、文件注入、命令执行
    ├── runner.py        # 构建输出解析（纯函数）
    └── coverage.py      # JaCoCo XML 解析
```

---

## 工厂函数：`create_executor`

**位置**：`testagent/executor/__init__.py`

```python
from testagent.executor import create_executor

executor = create_executor("java", project_path, reports_dir=..., keep_test=False)
```

根据 `language` 参数从内部注册表中查找对应的执行器类并实例化。当前支持的语言：

| `language` 值 | 对应实现 |
|--------------|---------|
| `"java"` | `JavaTestExecutor` |

传入不支持的语言时抛出 `ValueError`。

---

## Java 实现：`JavaTestExecutor`

**位置**：`testagent/executor/java/__init__.py`（也可通过 `testagent.executor.TestExecutor` 向后兼容导入）

执行模块的 Java 主入口，将测试文件写入/合并、运行构建、解析结果、读取覆盖率、按配置清理或恢复测试文件几个步骤串联为一次 `execute()` 调用。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project_path` | `Path` | 必填 | 被测 Java 项目的根目录 |
| `reports_dir` | `Path \| None` | `<testagent_root>/tmp/reports` | JaCoCo XML 报告的存储根目录 |
| `keep_test` | `bool` | `False` | 若为 `True`，执行完毕后保留合并后的项目测试文件；若为 `False`，新建测试文件会删除，执行前已存在的测试文件会恢复原内容 |
| `build_timeout` | `int` | `300` | 等待构建进程的最长秒数 |

构造时自动调用 `detect_build_tool()` 检测 `project_path` 下使用的构建工具（Maven 或 Gradle），若两者都不存在则抛出 `FileNotFoundError`。

#### `execute(test: GeneratedTest, context: AnalysisContext) -> TestResult`

对单次迭代的生成测试执行完整的编译—运行—覆盖率收集流程。

**执行步骤**：

1. **写文件**：调用 `write_test_file()` 将测试代码写入或合并到项目的规范测试文件：`src/test/java/<package>/<ClassName>Test.java`。目标路径由被测类 `context.target.class_name` 推导，不依赖 LLM 生成代码中的 package/class。若测试文件已存在，则合并 import、替换当前目标方法对应的 `testagent` marker block，并尽量复用已有字段/helper；若文件不存在，则新建完整测试文件。若写文件失败（例如代码中找不到可识别的 class 声明），立即返回 `compiled=False` 的 `TestResult`。

2. **构造命令**：根据检测到的构建工具，调用 `build_maven_command()` 或 `build_gradle_command()` 生成命令列表。命令中包含 `-Dtest`（Maven）或 `--tests`（Gradle）参数，将本次运行限定在被测类对应的 `<ClassName>Test` 上，并同时触发 JaCoCo 报告生成。

3. **运行构建**：调用 `run_build()` 在 `project_path` 目录下执行命令，合并 stdout + stderr，返回 `(returncode, output)`。构建超时或进程异常时返回 `compiled=False`。

4. **解析输出**：调用 `parse_build_result()` 分派给 `parse_maven_result()` 或 `parse_gradle_result()`，返回包含 `compiled`、`passed`、`compile_errors`、`failed_tests` 等字段的字典。

5. **解析覆盖率**：仅当编译成功时，在以下路径查找 `jacoco.xml`：
   ```
   <reports_dir>/<class_name_dotted>/<method_name>/iter<N>/jacoco.xml
   ```
   找到则调用 `parse_jacoco_xml()` 解析并填充 `CoverageReport`，否则覆盖率字段为 `None`。

6. **清理/恢复**：若 `keep_test=False`，本轮新建的测试文件会删除；如果测试文件执行前已存在，则恢复为写入前的原始内容。若 `keep_test=True`，保留合并后的项目测试文件。根目录的完整流水线脚本 `test_executor.py` 会固定以 `keep_test=True` 创建 executor，用于累积真实项目测试集合。

**调用示例**：

```python
from pathlib import Path
from testagent.executor import create_executor
from testagent.models import GeneratedTest, AnalysisContext

executor = create_executor(
    "java",
    Path("under_test/sample-java-project"),
    reports_dir=Path("tmp/reports"),
    keep_test=False,
)

result = executor.execute(test, context)

if result.passed:
    print("测试通过")
    if result.coverage:
        print(f"行覆盖率: {result.coverage.line_coverage * 100:.1f}%")
        print(f"分支覆盖率: {result.coverage.branch_coverage * 100:.1f}%")
elif not result.compiled:
    print("编译错误:")
    print(result.compile_errors)
else:
    print("测试失败:", result.failed_tests)
    print(result.test_output[-2000:])
```

---

## 子模块详解

### `java/builder.py`

#### `detect_build_tool(project_path: Path) -> str`

通过检查文件系统判断构建工具。

| 存在的文件 | 返回值 |
|-----------|--------|
| `pom.xml` | `"maven"` |
| `build.gradle` 或 `build.gradle.kts` | `"gradle"` |
| 两者都不存在 | 抛出 `FileNotFoundError` |

Maven 优先于 Gradle 检测。

---

#### `find_test_source_dir(project_path: Path) -> Path`

按以下顺序查找测试源码目录，若均不存在则返回 Maven 默认约定路径（不做创建）：

1. `<project>/src/test/java`
2. `<project>/src/test`

---

#### `extract_package_from_code(test_code: str) -> str`

使用 Java AST 从生成的测试代码中提取 `package` 声明，未找到时返回空字符串。该函数仅用于兼容和辅助解析；最终测试文件路径由被测类名推导。

#### `extract_class_name_from_code(test_code: str) -> str`

使用 Java AST 从生成的测试代码中提取第一个顶层 class 的类名。若找不到，抛出 `ValueError`。最终测试类名会按被测类规范化为 `<ClassName>Test`。

---

#### `write_test_file(test_code, project_path, class_name, method_name, iteration) -> Path`

将测试代码写入或合并到项目的测试源码树。

- 目标路径固定由被测类推导：`src/test/java/<package_path>/<ClassName>Test.java`。
- LLM 生成代码中的 package/class 不用于决定最终路径；写入时会按被测类的包名和规范测试类名重建文件头。
- 若目标测试文件不存在：创建新文件，并在 `package` 声明之前插入"大模型生成"横幅注释：

  ```java
  /*
   * 大模型生成 - 由 testagent 自动生成，请勿手动修改
   * Generated by: testagent (AI-powered test generation)
   * Target:    com.example.Calculator#add
   * Iteration: 1
   */
  ```

- 若目标测试文件已存在：不向人工文件添加横幅注释；保留原有测试、字段、helper 和 import，合并生成测试中的新 import；移除同一 `class_name#method_name` 的旧 marker block 后插入新 block。
- 每个生成 block 以 `// BEGIN testagent generated tests for <Class>#<method>` 和 `// END ...` 包围，不同被测方法互不覆盖。
- 重复字段声明会基于归一化签名去重，允许不同被测方法共享对象/fixture。
- 返回写入文件的绝对路径。

---

#### `cleanup_generated_tests(project_path: Path, clean_marker: str = "大模型生成") -> list[Path]`

清理被测项目测试源码目录下的生成文件。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project_path` | `Path` | 必填 | 被测 Java 项目的根目录 |
| `clean_marker` | `str` | `"大模型生成"` | 仅删除文件内容包含该标记且文件头部有生成横幅的 `.java` 文件；若传入**空字符串**，则删除测试目录下的所有 `.java` 文件 |

**行为**：

1. 通过 `find_test_source_dir()` 定位测试源码根目录（通常为 `src/test/java`）。
2. 递归扫描目录下所有 `.java` 文件：
   - `clean_marker` 非空：读取文件内容，仅删除包含该标记字符串且带生成横幅的文件。只有 marker block 但没有横幅的人工测试文件不会被默认删除。
   - `clean_marker` 为空字符串：直接删除所有 `.java` 文件。
3. 删除文件后，自下而上清理遗留的空目录。
4. 返回已删除文件的路径列表。

**调用示例**：

```python
from pathlib import Path
from testagent.executor.java.builder import cleanup_generated_tests

# 仅清理带"大模型生成"标记的文件（默认行为）
deleted = cleanup_generated_tests(Path("under_test/sample-java-project"))

# 清理带自定义标记的文件
deleted = cleanup_generated_tests(Path("under_test/sample-java-project"), clean_marker="Auto-generated")

# 清理测试目录下的所有测试文件
deleted = cleanup_generated_tests(Path("under_test/sample-java-project"), clean_marker="")

print(f"已删除 {len(deleted)} 个文件")
```

---

#### `build_maven_command(project_path, test_class_name, package, report_dir) -> list[str]`

构造 Maven 构建命令，优先使用项目本地的 `mvnw` wrapper。

生成的命令示例：

```bash
mvn --batch-mode test jacoco:report \
    -Dtest=com.example.CalculatorTest \
    -Djacoco.outputDirectory=/path/to/reports/... \
    -DfailIfNoTests=false
```

| 参数 | 作用 |
|------|------|
| `--batch-mode` | 禁用交互式输出，便于日志解析 |
| `test jacoco:report` | 依次执行测试和 JaCoCo 报告生成 |
| `-Dtest=<FQCN>` | 限定仅运行生成的测试类 |
| `-Djacoco.outputDirectory` | 将报告写入指定目录 |
| `-DfailIfNoTests=false` | 若测试类不匹配任何测试也不报错 |

---

#### `build_gradle_command(project_path, test_class_name, package, report_dir) -> list[str]`

构造 Gradle 构建命令，优先使用项目本地的 `gradlew` wrapper。

生成的命令示例：

```bash
gradle test jacocoTestReport \
    --tests=com.example.CalculatorTest \
    -PjacocoReportDir=/path/to/reports/... \
    --continue
```

> **注意**：`-PjacocoReportDir` 是一个项目属性，目标项目的 `build.gradle` 必须读取该属性并将 JaCoCo 报告输出到对应路径，否则覆盖率将无法收集。

---

#### `run_build(project_path: Path, command: list[str], timeout: int = 300) -> tuple[int, str]`

在 `project_path` 目录下以子进程运行 `command`，合并 stdout 和 stderr，返回 `(returncode, combined_output)`。

超过 `timeout` 秒时抛出 `subprocess.TimeoutExpired`，上层 `TestExecutor.execute()` 会捕获并将其转换为 `compiled=False` 的结果。

---

### `java/runner.py`

所有函数均为纯函数，不执行 I/O，仅接收字符串进行正则解析。

#### `parse_maven_result(returncode: int, output: str) -> dict`

解析 Maven 的 stdout/stderr，返回统一结构的字典：

| 字段 | 类型 | 说明 |
|------|------|------|
| `compiled` | `bool` | 是否通过编译（不含 `COMPILATION ERROR`） |
| `compile_errors` | `str` | 编译错误行，编译成功时为空字符串 |
| `passed` | `bool` | 所有测试通过且 returncode 为 0 |
| `test_output` | `str` | 完整原始构建输出 |
| `failed_tests` | `list[str]` | 失败的测试方法名列表 |

**编译错误检测**：匹配 `[ERROR] COMPILATION ERROR` 行。

**测试通过判定**：

- 若找到 `Tests run: X, Failures: Y, Errors: Z`，则 `Y + Z == 0` 且 `returncode == 0`
- 若未找到测试摘要，则以 `returncode == 0` 为准

**失败方法提取**：匹配 Surefire 输出中的 `<<< FAILURE!` / `<<< ERROR` 行。

---

#### `parse_gradle_result(returncode: int, output: str) -> dict`

解析 Gradle 的 stdout/stderr，返回与 `parse_maven_result` 相同结构的字典。

**编译错误检测**：匹配 `Compilation failed`、`compileTestJava FAILED`、`> Could not resolve` 等关键词。

**测试通过判定**：

- 若找到 `X tests completed, Y failed`，则 `Y == 0` 且 `returncode == 0`
- 若未找到摘要，则以 `returncode == 0` 为准

**失败方法提取**：匹配以下两种 Gradle 输出格式：

```
CalculatorTest > testDivideByZero FAILED
FAILED com.example.CalculatorTest > testDivideByZero
```

重复的方法名自动去重（保留原始顺序）。

---

#### `parse_build_result(build_tool: str, returncode: int, output: str) -> dict`

根据 `build_tool`（`"maven"` 或 `"gradle"`）分派给对应的解析函数。传入其他值时抛出 `ValueError`。

---

### `java/coverage.py`

#### `parse_jacoco_xml(xml_path: Path, class_name: str) -> CoverageReport | None`

解析 JaCoCo 生成的 `jacoco.xml`，提取指定类的覆盖率数据。

**返回 `None` 的情况**：

- 文件不存在
- XML 解析失败
- 报告中未找到对应 `<class>` 节点

**覆盖率计算**：

```
line_coverage   = covered_lines   / (missed_lines   + covered_lines)
branch_coverage = covered_branches / (missed_branches + covered_branches)
```

分母为 0 时返回 0.0。

**未覆盖信息**：

- `uncovered_lines`：`ci == 0` 且 `mi > 0` 的行号列表（升序）
- `uncovered_branches`：`mb > 0` 的行的描述字符串，格式为  
  `"Line 15: 1/2 branch(es) not covered"`

JaCoCo XML 结构参考：

```xml
<report name="...">
  <package name="com/example">
    <class name="com/example/Calculator">
      <counter type="LINE"   missed="2" covered="10"/>
      <counter type="BRANCH" missed="1" covered="3"/>
    </class>
    <sourcefile name="Calculator.java">
      <line nr="15" mi="0" ci="1" mb="1" cb="1"/>
    </sourcefile>
  </package>
</report>
```

---

#### `find_jacoco_xml(report_dir: Path) -> Path | None`

在 `report_dir` 中查找 `jacoco.xml`，按以下顺序尝试：

1. `<report_dir>/jacoco.xml`
2. `<report_dir>/jacoco/jacoco.xml`
3. `<report_dir>` 下的递归查找（`rglob`）

返回第一个匹配路径，未找到返回 `None`。

---

## 数据流

```
GeneratedTest + AnalysisContext
          │
          ▼
   write_test_file()          ──→  create/merge <project>/src/test/java/.../XxxTest.java
          │
          ▼
build_maven_command()
  或 build_gradle_command()
          │
          ▼
     run_build()              ──→  subprocess (mvn / gradle)
          │
          ▼ (returncode, stdout+stderr)
  parse_build_result()
          │
          ├── compiled=False  ──→  TestResult(compiled=False, ...)
          │
          └── compiled=True
                    │
                    ▼
          find_jacoco_xml()
                    │
                    ├── None  ──→  coverage=None
                    │
                    └── Path
                              │
                              ▼
                   parse_jacoco_xml()  ──→  CoverageReport
                              │
                              ▼
                   [delete new test file or restore pre-existing file if keep_test=False]
                              │
                              ▼
                         TestResult
```

---

## 报告目录结构

每次 `execute()` 调用对应一个独立的报告子目录，路径格式为：

```
<reports_dir>/
└── <class_name_with_dots_replaced_by_underscores>/
    └── <method_name>/
        └── iter<N>/
            └── jacoco.xml
```

示例：

```
tmp/reports/
└── com_example_Calculator/
    └── add/
        ├── iter1/
        │   └── jacoco.xml
        └── iter2/
            └── jacoco.xml
```

不同迭代轮次写入独立目录，互不覆盖，便于事后对比和调试。

---

## 数据模型

执行模块使用以下 `testagent.models` 数据类：

### 输入

| 类型 | 字段 | 说明 |
|------|------|------|
| `GeneratedTest` | `test_code: str` | 完整 JUnit 测试类源码 |
| | `iteration: int` | 当前迭代轮次，决定报告目录名 |
| `AnalysisContext` | `target.class_name` | 被测类的全限定名 |
| | `target.method_name` | 被测方法名 |
| | `package` | 被测源码文件的包名，用于规范测试文件 package |
| | `existing_test_summary` | 既有测试文件摘要，生成阶段使用；执行阶段主要依赖目标类和方法 |

### 输出

**`TestResult`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `compiled` | `bool` | 测试代码是否编译通过 |
| `compile_errors` | `str` | 编译错误文本（编译成功时为空字符串） |
| `passed` | `bool` | 所有测试方法是否通过 |
| `test_output` | `str` | 完整构建输出（stdout + stderr） |
| `coverage` | `CoverageReport \| None` | 覆盖率报告，无 JaCoCo XML 时为 `None` |
| `failed_tests` | `list[str]` | 失败的测试方法名列表 |

**`CoverageReport`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `line_coverage` | `float` | 行覆盖率，范围 0.0–1.0 |
| `branch_coverage` | `float` | 分支覆盖率，范围 0.0–1.0 |
| `uncovered_lines` | `list[int]` | 未被覆盖的行号列表（升序） |
| `uncovered_branches` | `list[str]` | 未覆盖分支的描述字符串列表 |

---

## 配置

执行模块的行为通过 `Config` 数据类或直接构造 `TestExecutor` 控制：

| 配置字段 | 默认值 | 说明 |
|---------|--------|------|
| `keep_test` | `False` | 是否保留合并后的项目测试文件；为 `False` 时新建文件删除、已有文件恢复 |
| `jacoco_enabled` | `True` | 是否启用 JaCoCo 覆盖率收集（当前由命令中包含 `jacoco:report` 实现） |

在 `configs/default.yaml` 中对应的节：

```yaml
executor:
  keep_test: false
  jacoco_enabled: true
```

---

## 错误处理

| 场景 | 行为 |
|------|------|
| 测试代码缺少可识别的 class 声明 | 返回 `compiled=False`，`compile_errors` 中包含错误描述 |
| 目录创建失败 / 文件写入失败 | 返回 `compiled=False`，`compile_errors` 中包含异常信息 |
| 构建进程超时 | 捕获 `TimeoutExpired`，返回 `compiled=False` |
| 构建进程其他异常 | 捕获通用 `Exception`，返回 `compiled=False` |
| 编译错误（Maven/Gradle 输出中检测到） | `compiled=False`，`compile_errors` 包含相关错误行 |
| 测试失败（编译通过但测试不通过） | `compiled=True`，`passed=False`，`failed_tests` 列出失败方法名 |
| JaCoCo XML 不存在或解析失败 | `coverage=None`，记录 warning 日志，不影响其他字段 |

---

## 单元测试

测试位于 `tests/test_executor/`，全部使用 mock，无需真实 Java 环境：

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_test_executor.py` | `TestExecutor` 初始化、`execute()` 正常路径、失败路径、报告目录结构、Gradle 支持 |
| `test_builder.py` | `detect_build_tool`、`write_test_file`、`build_maven_command`、`build_gradle_command` |
| `test_runner.py` | `parse_maven_result`、`parse_gradle_result`（编译错误、测试失败、构建失败等多种输入） |
| `test_coverage.py` | `parse_jacoco_xml`（正常、类不存在、XML 损坏）、`find_jacoco_xml` |

运行方式：

```bash
pytest tests/test_executor/ -v
```

---

## 端到端集成测试

项目根目录下的 `test_executor.py` 提供了 Analyzer → Generator → Executor 完整流程的集成测试脚本：

```bash
# 列出可用测试目标
python test_executor.py --list

# 测试单个方法（最多 3 次迭代）
python test_executor.py --target Calculator.add --max-iterations 3

# 测试所有预设目标；完整脚本始终保留合并后的项目测试文件，--keep-test 为兼容参数
python test_executor.py --keep-test

# 指定自定义项目路径和报告目录
python test_executor.py \
    --project /path/to/java-project \
    --reports-dir /tmp/jacoco-reports
```

预设测试目标：

| 目标 | 类 |
|------|-----|
| `Calculator.add` | `com.example.Calculator` |
| `Calculator.divide` | `com.example.Calculator` |
| `OrderService.process` | `com.example.service.OrderService` |
| `OrderService.findOrder` | `com.example.service.OrderService` |
| `OrderService.calculateTotal` | `com.example.service.OrderService` |

脚本对每个目标依次执行 分析 → 生成 → 写入/合并 → 执行（→ 精炼 → 执行）的循环，最终打印通过/失败汇总，任意目标失败时以非零状态码退出。该脚本会把通过验证的 Java 测试集合保留在真实项目的 `src/test/java/<package>/<ClassName>Test.java` 中，并校验每个成功目标对应的 marker block 仍存在。
