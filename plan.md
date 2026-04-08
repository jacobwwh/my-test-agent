# 实现计划：基于本地大模型的测试用例生成框架

## 背景

构建一个 Python 框架，利用本地部署的大语言模型（LLM）自动为 Java 方法生成单元测试。框架包含 3 个模块：程序分析（tree-sitter）、测试生成（Ollama）、测试执行（Maven/Gradle + JaCoCo），通过管道式架构串联，并支持基于反馈的迭代修复。

完整设计文档：`docs/superpowers/specs/2026-04-08-test-agent-framework-design.md`

## 实现步骤

### 第 1 步：项目脚手架搭建

- 创建 `pyproject.toml`，声明依赖项（tree-sitter、tree-sitter-java、requests、click、pyyaml、jinja2）
- 创建包结构：`src/testagent/` 及所有子包（analyzer/、generator/、executor/）
- 创建 `configs/default.yaml` 默认配置文件
- 创建 `src/testagent/models.py`，定义所有数据类（TargetMethod、Dependency、AnalysisContext、GeneratedTest、TestResult、CoverageReport、PipelineResult、Config）
- 创建 `src/testagent/config.py`，实现 YAML 配置加载及 CLI 参数覆盖

**涉及文件**：`pyproject.toml`、`src/testagent/__init__.py`、`src/testagent/models.py`、`src/testagent/config.py`、`configs/default.yaml`、所有 `__init__.py` 文件

---

### 第 2 步：程序分析模块 - Java 解析器

- 实现 `src/testagent/analyzer/java_parser.py`：
  - 使用 tree-sitter-java 将 .java 文件解析为 AST
  - 根据全限定类名在项目源码目录中查找目标类文件
  - 在类中定位目标方法
  - 提取方法源码和类源码
  - 提取类型引用：字段类型、参数类型、返回类型、方法体中使用的类型、父类、实现的接口
- 实现 `src/testagent/analyzer/dependency.py`：
  - 根据提取的类型名称，在项目源码树中搜索对应的 .java 文件
  - 将 import 语句映射到文件路径
  - 提取依赖项的源码
- 实现 `src/testagent/analyzer/__init__.py`：
  - 导出 `JavaAnalyzer` 类，提供 `analyze(class_name, method_name) -> AnalysisContext` 接口

**涉及文件**：`src/testagent/analyzer/java_parser.py`、`src/testagent/analyzer/dependency.py`、`src/testagent/analyzer/__init__.py`

---

### 第 3 步：测试生成模块 - Ollama + Prompt 模板

- 在 `prompts/` 目录下创建 Prompt 模板：
  - `generate_test.txt`：首次生成测试用例的 Prompt（Jinja2 模板）
  - `fix_test.txt`：基于错误/覆盖度反馈的修复 Prompt
- 实现 `src/testagent/generator/ollama_client.py`：
  - 封装 Ollama `/api/chat` REST 接口
  - 处理连接错误和超时
  - 提取文本响应
- 实现 `src/testagent/generator/prompt.py`：
  - 加载并渲染 Jinja2 Prompt 模板
  - 根据 AnalysisContext + 可选的 TestResult 反馈构建完整 Prompt
- 实现 `src/testagent/generator/test_generator.py`：
  - `TestGenerator.generate(context)`：首次生成
  - `TestGenerator.refine(context, previous_test, test_result)`：迭代修复
  - 从 LLM 响应中提取 Java 代码块（解析 Markdown 代码围栏）

**涉及文件**：`prompts/generate_test.txt`、`prompts/fix_test.txt`、`src/testagent/generator/ollama_client.py`、`src/testagent/generator/prompt.py`、`src/testagent/generator/test_generator.py`、`src/testagent/generator/__init__.py`

---

### 第 4 步：测试执行模块 - 构建与覆盖度

- 实现 `src/testagent/executor/builder.py`：
  - 自动检测构建工具（pom.xml → Maven，build.gradle → Gradle）
  - 将生成的测试文件写入项目的正确测试目录
  - 调用构建工具运行指定的测试类
  - 捕获标准输出/标准错误
- 实现 `src/testagent/executor/runner.py`：
  - 解析构建输出，提取编译错误和测试失败信息
  - 判断通过/失败状态
  - 提取失败的测试方法名称
- 实现 `src/testagent/executor/coverage.py`：
  - 解析 JaCoCo XML 报告
  - 提取目标类/方法的行覆盖率和分支覆盖率
  - 识别未覆盖的行和分支
- 实现 `src/testagent/executor/__init__.py`：
  - 导出 `TestExecutor`，提供 `execute(test, context) -> TestResult` 接口

**涉及文件**：`src/testagent/executor/builder.py`、`src/testagent/executor/runner.py`、`src/testagent/executor/coverage.py`、`src/testagent/executor/__init__.py`

---

### 第 5 步：管道编排 + CLI 命令行

- 实现 `src/testagent/core.py`：
  - `Pipeline` 类串联 Analyzer → Generator → Executor
  - 迭代循环，支持 max_iterations 最大迭代次数
  - 返回 PipelineResult，包含完整的迭代历史
- 实现 `src/testagent/cli.py`：
  - `testagent generate` 命令，支持所有配置选项
  - 从 YAML 加载配置，CLI 参数优先覆盖
  - 格式化输出结果（通过/失败、覆盖率、生成的测试代码）
- 更新 `src/testagent/__init__.py`，导出 Pipeline 和 Config 以支持 Python API 调用

**涉及文件**：`src/testagent/core.py`、`src/testagent/cli.py`、`src/testagent/__init__.py`

---

### 第 6 步：测试与测试夹具

- 在 `tests/fixtures/sample-java-project/` 下创建最小化的示例 Java 项目作为测试夹具：
  - 简单的 Maven 项目，包含一个有待测方法的类
  - 包含配置了 JaCoCo 插件的 pom.xml
- 编写单元测试：
  - `tests/test_analyzer/`：测试 Java 解析和依赖提取（使用测试夹具）
  - `tests/test_generator/`：测试 Prompt 构建和代码提取（Mock Ollama）
  - `tests/test_executor/`：测试构建输出解析和 JaCoCo XML 解析
- 编写集成测试（需要 Ollama 运行）：
  - `tests/test_integration.py`：使用示例项目的端到端管道测试

**涉及文件**：`tests/fixtures/`、`tests/test_analyzer/`、`tests/test_generator/`、`tests/test_executor/`、`tests/test_integration.py`

---

## 验证方式

1. `pip install -e .` - 验证包可以正常安装
2. `pytest tests/ -k "not integration"` - 运行单元测试，无需 Ollama 即可全部通过
3. `testagent generate --help` - 验证 CLI 命令正常工作
4. 启动 Ollama 后运行：`testagent generate --project tests/fixtures/sample-java-project --class com.example.Calculator --method add` - 验证端到端流程
5. 检查生成的测试能够在示例项目中成功编译和运行
