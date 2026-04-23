# 测试用例生成模块文档

## 概述

测试用例生成模块（`testagent.generator`）负责接收程序分析模块输出的 `AnalysisContext`，调用大语言模型（LLM）生成 JUnit 5 测试用例，并在迭代修复流程中根据执行反馈对测试进行改进。

模块由三个子组件组成：

| 文件 | 职责 |
|------|------|
| `llm_client.py` | 封装 OpenAI 兼容 API，处理网络错误 |
| `prompt.py` | 加载并渲染 Jinja2 Prompt 模板 |
| `test_generator.py` | 编排生成/修复流程，提取响应中的 Java 代码 |

对应的 Prompt 模板按语言存放在 `prompts/<language>/` 下：

| 文件 | 用途 |
|------|------|
| `prompts/java/generate_test.txt` | Java：首次生成测试用例 |
| `prompts/java/fix_test.txt` | Java：基于反馈迭代修复 |
| `prompts/cpp/generate_test.txt` | C++：占位模板（未实现） |
| `prompts/cpp/fix_test.txt` | C++：占位模板（未实现） |

---

## 模块结构

```
src/testagent/generator/
├── __init__.py          # 公开导出
├── llm_client.py        # LLM API 客户端
├── prompt.py            # Prompt 构建（支持 language 参数）
└── test_generator.py    # 主入口：TestGenerator + extract_code_block
```

---

## 核心类与函数

### `TestGenerator`

**位置**：`testagent/generator/test_generator.py`

测试生成的主入口类，持有一个 `LLMClient` 实例并提供两个公开方法。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_base_url` | `str` | 必填 | OpenAI 兼容 API 的 base URL |
| `api_key` | `str` | 必填 | API 鉴权密钥 |
| `model` | `str` | `"qwen3.5-397b-a17b"` | 模型名称 |
| `timeout` | `int` | `120` | 请求超时时间（秒） |
| `language` | `str` | `"java"` | 目标语言，用于选取对应的 Prompt 模板目录 |

#### `generate(context: AnalysisContext) -> GeneratedTest`

首次调用，根据分析上下文生成初始测试用例。

- 使用 `prompts/<language>/generate_test.txt` 模板构建 Prompt
- 返回 `GeneratedTest(test_code=..., iteration=1)`

#### `refine(context, previous_test, test_result) -> GeneratedTest`

迭代修复，将上一轮的测试代码和执行反馈一并发给 LLM。

- 使用 `prompts/<language>/fix_test.txt` 模板构建 Prompt
- 返回 `GeneratedTest(test_code=..., iteration=previous_test.iteration + 1)`

**调用示例**：

```python
from testagent.generator.test_generator import TestGenerator

generator = TestGenerator(
    api_base_url="https://yunwu.ai/v1",
    api_key="your-api-key",
    model="qwen3.5-397b-a17b",
    language="java",   # 选择 prompts/java/ 下的模板
)

# 首次生成
result = generator.generate(context)           # iteration=1
print(result.test_code)

# 迭代修复（传入上一轮结果）
refined = generator.refine(context, result, test_result)  # iteration=2
```

---

### `extract_code_block(text: str) -> str`

**位置**：`testagent/generator/test_generator.py`

从 LLM 的 Markdown 格式响应中提取代码块。优先级如下：

1. 匹配带语言标记的围栏（如 ` ```java `、` ```cpp `）（最优先）
2. 匹配通用 ` ``` ... ``` ` 围栏
3. 如果没有任何代码围栏，直接返回原始文本（并打印 warning 日志）

`extract_java_code` 是该函数的向后兼容别名，行为相同。

```python
from testagent.generator.test_generator import extract_code_block

code = extract_code_block("Sure, here it is:\n```java\npublic class FooTest {}\n```")
# → "public class FooTest {}"
```

---

### `LLMClient`

**位置**：`testagent/generator/llm_client.py`

对 OpenAI Python SDK 的轻量封装，支持任何 OpenAI 兼容接口（yunwu API、vLLM、官方 OpenAI 等）。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_base_url` | `str` | 必填 | API base URL |
| `api_key` | `str` | 必填 | API 密钥 |
| `model` | `str` | `"qwen3.5-397b-a17b"` | 模型名称 |
| `timeout` | `int` | `120` | 超时（秒） |

#### `chat(messages: list[dict[str, str]]) -> str`

发送 Chat Completion 请求，返回模型的文本回复。

`messages` 格式遵循 OpenAI chat 标准：

```python
[{"role": "user", "content": "..."}]
```

#### 异常

| 异常 | 触发条件 |
|------|----------|
| `LLMConnectionError` | 网络不通或请求超时 |
| `LLMAPIError` | API 返回非 2xx 状态码（如 401、429、500） |

**调用示例**：

```python
from testagent.generator.llm_client import LLMClient, LLMConnectionError, LLMAPIError

client = LLMClient(
    api_base_url="https://yunwu.ai/v1",
    api_key="your-key",
    model="qwen3.5-397b-a17b",
    timeout=60,
)

try:
    reply = client.chat([{"role": "user", "content": "Say hello."}])
except LLMConnectionError as e:
    print(f"网络错误: {e}")
except LLMAPIError as e:
    print(f"API 错误: {e}")
```

---

### Prompt 构建函数

**位置**：`testagent/generator/prompt.py`

两个函数均返回 `list[dict[str, str]]`，可直接传给 `LLMClient.chat()`。

#### `build_generate_prompt(context, prompts_dir=None, language="java")`

渲染 `generate_test.txt` 模板，注入以下变量：

| 模板变量 | 来源 |
|----------|------|
| `target` | `context.target`（`TargetMethod`） |
| `dependencies` | `context.dependencies`（`list[Dependency]`） |
| `imports` | `context.imports`（`list[str]`） |
| `package` | `context.package`（目标源码文件的包名） |
| `existing_test_summary` | `context.existing_test_summary`（对应真实项目测试文件的摘要，可能为 `None`） |

#### `build_refine_prompt(context, previous_test, test_result, prompts_dir=None, language="java")`

渲染 `fix_test.txt` 模板，额外注入：

| 模板变量 | 来源 |
|----------|------|
| `previous_test` | `GeneratedTest`（上一轮生成的测试） |
| `test_result` | `TestResult`（编译/运行/覆盖度结果） |

`prompts_dir` 为 `None` 时，模板目录自动解析为 `prompts/<language>/`。显式传入 `prompts_dir` 时忽略 `language` 参数。测试时可传入自定义路径。

---

## Prompt 模板说明

### `prompts/java/generate_test.txt`

初始生成模板，内容结构：

```
角色定位（expert Java developer）
→ 目标方法签名
→ 被测类完整源码
→ [可选] 依赖类/接口/枚举源码
→ [可选] Import 语句
→ [可选] 已存在测试文件摘要（import、类签名、字段/helper、测试方法签名）
→ 生成要求（JUnit 5、覆盖边界条件、Mockito、输出格式）
```

生成要求摘要：
- 生成完整的、可独立编译运行的 JUnit 5 测试类
- 测试类使用目标源码的同一 package 和规范名称 `<SourceClass>Test`
- 只为当前被测方法生成测试，不为同一类中的其他方法补测
- 当 `existing_test_summary` 存在时，复用兼容的 import、字段、对象和 helper，避免重复 test method 名称
- 使用 `org.junit.jupiter.api.@Test`
- 覆盖正常、边界、异常场景
- 如需 Mock，使用 Mockito
- 只输出 Java 代码，用 ` ```java ` 围栏包裹

### `prompts/java/fix_test.txt`

迭代修复模板，在初始模板基础上新增：

```
→ 上一轮测试代码（标注迭代轮次）
→ 反馈（三选一，取决于失败类型）：
    - 编译错误：完整编译器错误信息
    - 测试失败：测试输出 + 失败的方法名列表
    - 覆盖度不足：行覆盖率、分支覆盖率、未覆盖行号、未覆盖分支描述
```

模板通过 Jinja2 条件块（`{% if not test_result.compiled %}`、`{% elif not test_result.passed %}`、`{% if test_result.coverage %}`）自动选择对应的反馈片段。

---

## 数据流

```
AnalysisContext
      │
      ▼
build_generate_prompt()   ←── prompts/<language>/generate_test.txt (Jinja2)
      │
      ▼
LLMClient.chat()          ←── OpenAI-compatible API (yunwu / 生产端点)
      │
      ▼  (原始 Markdown 文本)
extract_code_block()
      │
      ▼
GeneratedTest(test_code, iteration=1)
      │
  [执行后有反馈]
      │
      ▼
build_refine_prompt()     ←── prompts/<language>/fix_test.txt (Jinja2)
      │
      ▼
LLMClient.chat()
      │
      ▼
extract_code_block()
      │
      ▼
GeneratedTest(test_code, iteration=N+1)
```

---

## 配置

### 配置字段

生成模块的参数通过 `Config` 数据类传入，默认值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `api_base_url` | `"https://yunwu.ai/v1"` | OpenAI 兼容 API 的 base URL |
| `api_key` | `""` | API 鉴权密钥，可通过 `YUNWU_API_KEY` 环境变量设置 |
| `model` | `"qwen3.5-397b-a17b"` | 模型名称 |
| `timeout` | `120` | 单次请求超时（秒） |
| `language` | `"java"` | 目标语言，用于选取 `prompts/<language>/` 下的模板 |

### 配置优先级

配置值按以下优先级从低到高覆盖：

```
configs/default.yaml  <  YUNWU_API_KEY 环境变量  <  CLI 参数
```

### 方式一：修改 `configs/default.yaml`

适合长期固定使用某个 API 端点的场景：

```yaml
llm:
  api_base_url: "https://yunwu.ai/v1"   # 替换为你的 API endpoint
  api_key: "your-api-key-here"           # 直接写入（注意不要提交到 git）
  model: "qwen3.5-397b-a17b"
  timeout: 120

pipeline:
  max_iterations: 5

executor:
  keep_test: false
  jacoco_enabled: true
```

> **注意**：`api_key` 写入配置文件存在泄露风险，建议使用环境变量代替。

### 方式二：环境变量（推荐）

`api_key` 可通过 `YUNWU_API_KEY` 环境变量注入，无需修改任何文件：

```bash
export YUNWU_API_KEY=your-key-here
python test_generator.py
```

`api_base_url` 目前不支持环境变量，需在 `default.yaml` 或通过 CLI 指定。

### 方式三：CLI 参数

CLI 参数优先级最高，会覆盖配置文件和环境变量：

```bash
testagent generate \
  --project /path/to/project \
  --class com.example.Calculator \
  --method add \
  --ollama-url https://your-api/v1 \
  --model qwen3.5-397b-a17b
```

### 方式四：Python API

在代码中调用 `load_config()` 时通过关键字参数覆盖：

```python
from testagent.config import load_config

config = load_config(
    api_base_url="https://your-api/v1",
    api_key="your-key",
    model="qwen3.5-397b-a17b",
)
```

传入 `None` 的参数不会覆盖配置文件中的值，可安全地将 Click 的 `None` 默认值直接透传。

---

## 错误处理

| 场景 | 异常 | 建议处理 |
|------|------|----------|
| API 地址无法访问 | `LLMConnectionError` | 检查 `api_base_url` 是否正确，网络是否通畅 |
| 请求超时 | `LLMConnectionError` | 增大 `timeout`，或减少 Prompt 长度 |
| API Key 无效 / 限流 | `LLMAPIError` | 检查 `api_key`，或等待后重试 |
| 响应无代码围栏 | 无异常，打印 warning | 检查模型是否遵循 Prompt 格式要求 |

---

## 单元测试

测试位于 `tests/test_generator/`，无需真实 API（使用 `unittest.mock.patch` Mock LLM）：

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_extract_code.py` | `extract_code_block`（及 `extract_java_code` 别名）的 7 种输入场景 |
| `test_prompt.py` | `build_generate_prompt` 和 `build_refine_prompt` 的内容正确性 |
| `test_llm_client.py` | `LLMClient` 正常响应、空内容、连接错误、超时、API 错误、构造参数 |
| `test_test_generator.py` | `generate`/`refine` 端到端、迭代计数、反馈注入 |

运行方式：

```bash
pytest tests/test_generator/ -v
```

---

## 端到端集成测试

项目根目录下的 `test_generator.py` 提供了完整的 Analyzer + Generator 流程测试：

```bash
# 查看可测方法列表
python test_generator.py --list

# 测试单个方法
python test_generator.py --target Calculator.divide

# 测试所有预设目标
python test_generator.py
```

生成的测试文件保存在 `generated_tests/<项目名>/` 下，文件名格式为 `<ClassName>_<methodName>_Test.java`。

注意：这里描述的是根目录 `test_generator.py` 的“只生成不执行”脚本行为。完整执行脚本 `test_executor.py` 会进一步把通过验证的 Java 测试合并到真实项目的 `src/test/java/<package>/<ClassName>Test.java` 中。
