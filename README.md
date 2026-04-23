# my-test-agent

基于本地部署 LLM（使用 OpenAI API 调用）的多语言单元测试自动生成框架。当前支持 Java（通过分析源码生成 JUnit 5 测试用例，经 Maven/Gradle 编译执行并收集 JaCoCo 覆盖率，根据编译错误、测试失败和覆盖率缺口迭代优化），并通过 `--language` 参数预留了对 C++ 等其他语言的扩展接口。

## 配置

配置文件位于 `configs/default.yaml`，同时支持环境变量和 CLI 参数覆盖。

### 配置文件

```yaml
llm:
  api_base_url: "https://yunwu.ai/v1"   # OpenAI API 兼容端点
  api_key: ""                            # 留空则从环境变量读取
  model: "qwen3.5-397b-a17b"
  timeout: 120                           # LLM 请求超时（秒）

project:
  path: ""                               # 被测项目根目录；留空则使用内置 sample 项目
  language: "java"                       # 目标语言：java（后续支持 cpp 等）

pipeline:
  max_iterations: 5                      # 最大迭代优化次数
  min_branch_coverage: 1.0               # 目标分支覆盖率（0.0–1.0）

executor:
  keep_test: false                       # Executor API 执行后是否保留/恢复测试文件
  jacoco_enabled: true
```

### 环境变量（仅用于本机调试，实际部署中不要设置）

```bash
export YUNWU_API_KEY="your-api-key"
```

环境变量 `YUNWU_API_KEY` 优先于配置文件中的 `llm.api_key`。

### 设置被测项目根目录和语言

项目根目录优先级如下：

1. CLI 参数 `--project`
2. 配置文件 `project.path`
3. 默认示例项目 `under_test/sample-java-project`

语言优先级如下：

1. CLI 参数 `--language`
2. 配置文件 `project.language`
3. 默认值 `java`

示例：

```yaml
project:
  path: "/path/to/java-project"
  language: "java"
```

### CLI 参数覆盖

所有脚本支持通过命令行参数覆盖配置文件中的值，CLI 参数优先级最高。常用参数包括：

| 参数 | 说明 |
|------|------|
| `--target` | 使用预设目标，例如 `Calculator.add` |
| `--class` | 指定任意目标的全限定类名，例如 `com.example.Calculator` |
| `--method` | 与 `--class` 搭配，指定目标方法名 |
| `--language` | 目标语言（默认 `java`，后续支持 `cpp` 等） |
| `--model` | 覆盖 LLM 模型名称 |
| `--max-iterations` | 覆盖最大迭代次数 |
| `--keep-test` | Executor API 兼容参数；完整 `test_executor.py` 流水线始终保留合并后的真实项目测试文件 |
| `--min-branch-coverage` | 覆盖目标分支覆盖率（0.0–1.0） |
| `--project` | 指定被测项目路径 |
| `--reports-dir` | 指定 JaCoCo 报告输出目录 |

## 脚本说明与使用

### test_analyzer.py — 分析器单元测试

运行 `tests/test_analyzer/` 下的 pytest 单元测试，验证 Java 源码解析和依赖提取功能是否正确。不需要 LLM 或 Java 环境。

```bash
# 交互式选择要运行的测试
python test_analyzer.py

# 运行全部测试
python test_analyzer.py -a

# 传递额外 pytest 参数（如按关键字过滤）
python test_analyzer.py -k "parse"
```

### test_generator.py — 分析 + 生成集成测试

执行 **Analyzer -> Generator** 流程：分析被测类源码，调用 LLM 生成测试用例，将结果保存到 `generated_tests/<project-name>/`。不执行测试、不收集覆盖率。需要配置 API Key。

```bash
# 列出可用目标
python test_generator.py --list

# 为所有预设目标生成测试
python test_generator.py

# 为单个目标生成测试
python test_generator.py --target Calculator.add

# 为任意项目中的任意方法生成测试
python test_generator.py --project /path/to/java-project --class com.acme.OrderService --method submit

# 使用指定模型
python test_generator.py --target Calculator.divide --model gpt-4o

# 指定目标语言（当前仅支持 java）
python test_generator.py --language java --target Calculator.add
```

### test_executor.py — 完整流水线（生成 + 执行 + 迭代优化）

执行 **Analyzer -> Generator -> Executor** 完整流程：生成测试 -> 写入真实项目测试文件 -> 编译执行 -> 收集覆盖率 -> 根据错误和覆盖率缺口迭代优化，直到测试通过且覆盖率达标或达到最大迭代次数。需要配置 API Key 和本地 Maven/Gradle 环境。

Java 测试会合并到真实项目中与被测类对应的测试文件：
`src/test/java/<package>/<ClassName>Test.java`。若文件不存在则新建；若已存在则追加/替换当前被测方法对应的 `testagent` marker block。不同被测方法的测试位于各自独立 block 中，import、字段、helper 等共享代码会尽量复用并去重。完整 `test_executor.py` 流水线始终保留这些合并后的项目测试文件，`--keep-test` 仅作为兼容参数保留。

```bash
# 列出可用目标
python test_executor.py --list

# 运行所有预设目标
python test_executor.py

# 运行单个目标，限制迭代次数
python test_executor.py --target Calculator.divide --max-iterations 3

# 设置覆盖率阈值为 80%；--keep-test 为兼容参数，完整流水线始终保留合并后的测试文件
python test_executor.py --keep-test --min-branch-coverage 0.8

# 自定义项目路径和报告目录
python test_executor.py --project /path/to/java-project --reports-dir /tmp/reports

# 执行任意项目中的指定类方法
python test_executor.py --project /path/to/java-project --class com.acme.OrderService --method submit

# 指定目标语言
python test_executor.py --language java --target Calculator.add
```

### test_repair.py — 修复已有失败测试

执行 **Executor -> Refine** 修复流程：读取 `failed_test_case/` 目录下的失败测试文件，通过迭代优化修复编译错误、测试失败，并提升覆盖率。修复后的测试保存到 `generated_tests/<project-name>/`。

```bash
# 列出可修复的文件
python test_repair.py --list

# 修复所有失败测试
python test_repair.py

# 修复单个文件
python test_repair.py --file CalculatorTest_partial_coverage.java

# 限制迭代次数并保留测试文件
python test_repair.py --file CalculatorTest_failing.java --max-iterations 3 --keep-test

# 使用配置文件之外的被测项目根目录
python test_repair.py --project /path/to/java-project --file CalculatorTest_failing.java

# 指定目标语言
python test_repair.py --language java --file CalculatorTest_failing.java
```

## 预设测试目标

以下目标仅针对内置示例项目有效。对于任意外部项目，请使用 `--class` 和 `--method` 指定目标。

| 目标 | 类 |
|------|-----|
| `Calculator.add` | `com.example.Calculator` |
| `Calculator.divide` | `com.example.Calculator` |
| `OrderService.process` | `com.example.service.OrderService` |
| `OrderService.findOrder` | `com.example.service.OrderService` |
| `OrderService.calculateTotal` | `com.example.service.OrderService` |

## 环境要求

- Python 3.10+（与 `pyproject.toml` 中 `requires-python = ">=3.10"` 一致）
- Java 11+（被测项目编译执行）
- Maven 或 Gradle（构建工具）
- LLM API 访问（OpenAI API 兼容端点）

### Python 运行时依赖

以下依赖来自 `pyproject.toml` 的 `project.dependencies`：

| 库 | 版本要求 | 用途 |
|------|------|------|
| `tree-sitter` | `>=0.20` | 解析源码语法树 |
| `tree-sitter-java` | 未显式限制版本 | Java 语法支持 |
| `openai` | `>=1.0` | 调用 OpenAI 兼容 LLM API |
| `click` | `>=8.0` | CLI 支持 |
| `PyYAML` | `>=6.0` | 读取 YAML 配置 |
| `Jinja2` | `>=3.0` | 生成 Prompt 模板 |

### Python 开发/测试依赖

以下依赖来自 `pyproject.toml` 的 `project.optional-dependencies.dev`：

| 库 | 版本要求 | 用途 |
|------|------|------|
| `pytest` | `>=7.0` | 单元测试 |
| `pytest-cov` | 未显式限制版本 | 测试覆盖率统计 |
| `pytest-mock` | 未显式限制版本 | 测试中的 mock 支持 |
