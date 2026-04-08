# Test Agent Framework - Design Spec

## Context

We are building a framework that automatically generates unit tests for Java methods using locally deployed LLMs. The framework accepts a Java method as input, analyzes its dependencies via program analysis, generates test cases via LLM (Ollama), executes them, and iteratively refines based on feedback (compilation errors, test failures, coverage gaps).

This addresses the challenge of manual test writing being time-consuming and LLMs lacking sufficient context about project dependencies when generating tests.

## Architecture: Pipeline

A linear pipeline with a feedback loop:

```
User Input (project path, class, method)
       |
  [Analyzer] --> AnalysisContext
       |
  [Generator] <-- AnalysisContext + previous TestResult (if iterating)
  [Ollama]    --> GeneratedTest
       |
  [Executor]  --> TestResult (compile/run/coverage)
       |
  Pass? --Yes--> Final output
    |
   No (iteration < max)
    |
    └--> back to Generator with feedback
```

Modules communicate via well-defined dataclasses. Each module is an independent Python package with a clear interface.

## Technology Choices

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Framework language | Python | Rich ecosystem for AST parsing, LLM clients, rapid prototyping |
| Java parsing | tree-sitter (tree-sitter-java) | Lightweight, no JDK dependency, good enough for dependency extraction |
| LLM backend | Ollama REST API | Simple, local deployment, supports qwen3.5-9b and others |
| Test execution | Maven/Gradle + JaCoCo | Standard Java build tools, JaCoCo for coverage |
| CLI | click | Declarative CLI with auto-generated help |
| Config | YAML | Human-readable configuration |

## Project Structure

```
my-test-agent/
├── pyproject.toml
├── src/
│   └── testagent/
│       ├── __init__.py
│       ├── cli.py              # CLI entry point (click)
│       ├── core.py             # Pipeline orchestration
│       ├── models.py           # Dataclass definitions
│       ├── config.py           # Configuration loading
│       ├── analyzer/
│       │   ├── __init__.py
│       │   ├── java_parser.py  # tree-sitter Java AST parsing
│       │   └── dependency.py   # Dependency extraction logic
│       ├── generator/
│       │   ├── __init__.py
│       │   ├── ollama_client.py # Ollama REST API client
│       │   ├── prompt.py       # Prompt template management
│       │   └── test_generator.py # Test generation orchestration
│       └── executor/
│           ├── __init__.py
│           ├── builder.py      # Maven/Gradle build invocation
│           ├── runner.py       # Test execution
│           └── coverage.py     # JaCoCo XML report parsing
├── tests/                      # Framework's own tests
│   ├── test_analyzer/
│   ├── test_generator/
│   └── test_executor/
├── prompts/                    # Prompt templates (Jinja2 or plain text)
│   ├── generate_test.txt
│   └── fix_test.txt
└── configs/
    └── default.yaml
```

## Data Models

### TargetMethod
The method under test.

```python
@dataclass
class TargetMethod:
    class_name: str           # e.g., "com.example.MyService"
    method_name: str          # e.g., "processOrder"
    method_signature: str     # Full method source code
    file_path: Path           # Absolute path to the .java file
    class_source: str         # Full source of the containing class
```

### Dependency
A single dependency extracted by the analyzer.

```python
@dataclass
class Dependency:
    kind: str          # "class", "interface", "enum"
    qualified_name: str # e.g., "com.example.Order"
    source: str        # Source code of the dependency
    file_path: Path    # Where it was found
```

### AnalysisContext
Output of the Analyzer module.

```python
@dataclass
class AnalysisContext:
    target: TargetMethod
    dependencies: list[Dependency]
    imports: list[str]         # Import statements from the target file
    package: str               # Package declaration
```

### GeneratedTest
Output of the Generator module.

```python
@dataclass
class GeneratedTest:
    test_code: str       # Full JUnit test class source
    iteration: int       # Which iteration produced this
```

### TestResult
Output of the Executor module.

```python
@dataclass
class TestResult:
    compiled: bool
    compile_errors: str       # Empty if compiled successfully
    passed: bool              # All tests passed?
    test_output: str          # stdout/stderr from test run
    coverage: CoverageReport | None
    failed_tests: list[str]   # Names of failed test methods
```

### CoverageReport

```python
@dataclass
class CoverageReport:
    line_coverage: float       # 0.0 - 1.0
    branch_coverage: float     # 0.0 - 1.0
    uncovered_lines: list[int]
    uncovered_branches: list[str]  # Human-readable descriptions
```

### PipelineResult
Final output of the pipeline.

```python
@dataclass
class PipelineResult:
    success: bool              # Tests compiled and passed?
    iterations: int            # How many iterations were run
    final_test: GeneratedTest  # Last generated test
    final_result: TestResult   # Last test execution result
    history: list[tuple[GeneratedTest, TestResult]]  # All iterations
```

### Config
Framework configuration.

```python
@dataclass
class Config:
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen3.5:latest"
    max_iterations: int = 5
    timeout: int = 120
    keep_test: bool = False
    jacoco_enabled: bool = True
```

## Module Details

### 1. Analyzer (`testagent/analyzer/`)

**Responsibility**: Given a Java project path and target method identifier, extract the method source and its dependencies.

**Key behaviors**:
- Parse the target .java file using tree-sitter-java to build AST
- Locate the target method by class name + method name
- Extract the full method source code
- Identify referenced types: field types, parameter types, return type, types used in method body, parent class, implemented interfaces
- For each referenced type, search the project source tree to find its .java file
- Extract the source of each found dependency
- If a dependency is not found in the project (e.g., JDK or third-party), skip it (LLM knows standard libraries)

**MVP scope**:
- File-internal dependencies: fields, other methods in the same class, inner classes
- Cross-file dependencies: imported classes, parent class, interfaces
- Does NOT resolve transitive dependencies (depth=1 only)
- Does NOT resolve dependencies from compiled .class files or JARs

**Interface**:
```python
class JavaAnalyzer:
    def __init__(self, project_path: Path): ...
    def analyze(self, class_name: str, method_name: str) -> AnalysisContext: ...
```

### 2. Generator (`testagent/generator/`)

**Responsibility**: Call Ollama to generate or refine JUnit test code.

**Key behaviors**:
- Build a prompt containing: target method source, class context, dependency sources, and (if iterating) previous test result feedback
- Call Ollama `/api/chat` endpoint with the constructed prompt
- Extract the Java code block from the LLM response
- Return structured GeneratedTest

**Prompt strategy**:
- First iteration: "Generate JUnit 5 test cases for this method. Here is the method, its class, and its dependencies..."
- Subsequent iterations: "The previous test had these issues: [compile errors / test failures / uncovered branches]. Fix the test..."
- Include uncovered lines/branches in the feedback prompt to guide coverage improvement

**Interface**:
```python
class TestGenerator:
    def __init__(self, ollama_url: str, model: str): ...
    def generate(self, context: AnalysisContext) -> GeneratedTest: ...
    def refine(self, context: AnalysisContext, previous_test: GeneratedTest,
               test_result: TestResult) -> GeneratedTest: ...
```

### 3. Executor (`testagent/executor/`)

**Responsibility**: Compile and run the generated test, collect results and coverage.

**Key behaviors**:
- Detect build tool (Maven if pom.xml exists, Gradle if build.gradle exists)
- Write the generated test file to the appropriate test directory in the project
- Run the build tool's test command targeting only the generated test class
- Parse build output for compile errors and test failures
- Parse JaCoCo XML report for coverage data specific to the target class/method
- Clean up: remove the generated test file after execution (or keep it if user wants)

**Build tool commands**:
- Maven: `mvn test -pl <module> -Dtest=<TestClass> -Djacoco.destFile=...`
- Gradle: `gradle test --tests <TestClass>`

**Interface**:
```python
class TestExecutor:
    def __init__(self, project_path: Path): ...
    def execute(self, test: GeneratedTest, context: AnalysisContext) -> TestResult: ...
```

### 4. Pipeline Orchestrator (`testagent/core.py`)

**Responsibility**: Wire the modules together and manage the iteration loop.

```python
class Pipeline:
    def __init__(self, config: Config): ...

    def run(self, project_path: Path, class_name: str,
            method_name: str) -> PipelineResult: ...
```

**Flow**:
1. `analyzer.analyze(class_name, method_name)` -> `context`
2. `generator.generate(context)` -> `test`
3. `executor.execute(test, context)` -> `result`
4. If `result.passed` and coverage is acceptable: return success
5. If iteration < max_iterations: `generator.refine(context, test, result)` -> new `test`, goto 3
6. If max iterations reached: return final result with whatever was achieved

### 5. CLI (`testagent/cli.py`)

```bash
# Basic usage
testagent generate \
  --project /path/to/java-project \
  --class com.example.MyService \
  --method processOrder

# Options
  --model qwen3.5:latest          # Ollama model name (default: qwen2.5-coder:7b)
  --ollama-url http://localhost:11434  # Ollama server URL
  --max-iterations 5              # Max refinement iterations (default: 5)
  --output ./generated_tests      # Copy final test to this directory
  --keep-test                     # Don't delete test from project after execution
  --verbose                       # Show detailed output
```

### 6. Python API

```python
from testagent import Pipeline, Config

config = Config(
    ollama_url="http://localhost:11434",
    model="qwen3.5:latest",
    max_iterations=5,
)
pipeline = Pipeline(config)
result = pipeline.run(
    project_path=Path("/path/to/project"),
    class_name="com.example.MyService",
    method_name="processOrder",
)
print(result.final_test.test_code)
print(result.final_result.coverage)
```

## Configuration (`configs/default.yaml`)

```yaml
ollama:
  url: http://localhost:11434
  model: qwen3.5:latest
  timeout: 120  # seconds

pipeline:
  max_iterations: 5

executor:
  keep_test: false
  jacoco_enabled: true
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Ollama unreachable | Raise clear error: "Cannot connect to Ollama at {url}. Is it running?" |
| Target method not found | Raise error with list of methods found in the class |
| tree-sitter parse failure | Log warning, fall back to regex-based extraction |
| Build tool not found | Raise error: "Neither pom.xml nor build.gradle found in {path}" |
| Compile failure persists after max iterations | Return last GeneratedTest with compile errors attached |
| No JaCoCo report found | Return TestResult with coverage=None, log warning |

## Dependencies

```
tree-sitter >= 0.20
tree-sitter-java
requests           # For Ollama REST API
click              # CLI framework
pyyaml             # Configuration
jinja2             # Prompt templates
```

## Verification Plan

1. **Unit tests**: Test each module in isolation with fixtures (sample Java projects)
2. **Integration test**: End-to-end test with a simple Java project + Ollama running locally
3. **Manual verification**:
   - Run against a real Java project with known methods
   - Verify generated tests compile and run
   - Verify coverage report is correctly parsed
   - Verify iteration loop improves tests across rounds

## Future Extensions (Not in MVP)

- Support for C++ and Python as target languages
- Transitive dependency resolution (depth > 1)
- Multiple LLM backend support (vLLM, OpenAI API)
- Parallel test generation for multiple methods
- Web UI
- Agent/Tool architecture where LLM can request additional analysis during generation
