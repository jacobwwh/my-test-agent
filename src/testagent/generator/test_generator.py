"""Test generation orchestration using LLM."""

from __future__ import annotations

import logging
import re

from testagent.generator.llm_client import LLMClient
from testagent.generator.prompt import build_generate_prompt, build_refine_prompt
from testagent.models import AnalysisContext, GeneratedTest, TestResult

__all__ = [
    "TestGenerator",
    "extract_code_block",
    "extract_java_code",  # backward-compat alias
    "normalize_test_class_name",
    "canonical_test_class_name",
]

logger = logging.getLogger(__name__)


def canonical_test_class_name(class_name: str) -> str:
    """根据被测类名生成规范测试类名。

    功能简介：
        将全限定类名转换为约定的测试类名格式 `<SimpleClassName>Test`，
        供测试代码规范化和真实项目测试文件合并时使用。

    输入参数：
        class_name:
            被测类的全限定类名，例如 `com.example.Calculator`。

    返回值：
        str:
            规范测试类名，例如 `CalculatorTest`。

    使用示例：
        >>> canonical_test_class_name("com.example.Calculator")
        'CalculatorTest'
    """
    simple = class_name.rsplit(".", 1)[-1]
    return f"{simple}Test"


def normalize_test_class_name(test_code: str, class_name: str) -> str:
    """将测试代码中的类名规范化为约定名称。

    功能简介：
        LLM 生成的测试类名可能不稳定；该函数会把测试代码中第一个类声明
        替换为规范名称，确保写入层可以把生成类体稳定合并到真实项目中
        对应的 `<SimpleClassName>Test`。

    输入参数：
        test_code:
            原始测试代码文本。
        class_name:
            被测类的全限定类名，用于计算规范测试类名。

    返回值：
        str:
            规范化类名后的测试代码；若未找到类声明，则返回原始代码。

    使用示例：
        >>> normalize_test_class_name("public class Foo {}", "com.example.Calculator")
        'public class CalculatorTest {}'
    """
    canonical = canonical_test_class_name(class_name)
    # Match the first top-level class declaration (public or package-private).
    new_code, count = re.subn(
        r'(?m)^(\s*(?:public\s+)?class\s+)(\w+)',
        lambda m: m.group(1) + canonical,
        test_code,
        count=1,
    )
    if count == 0:
        logger.warning(
            "Could not find class declaration to normalize; "
            "leaving test code unchanged."
        )
    return new_code


def extract_code_block(text: str) -> str:
    """从模型回复中提取代码块。

    功能简介：
        优先提取 Markdown 中带语言标记的 fenced code block（如 ```java），
        若不存在则回退到普通 ``` code block；再没有则返回去除首尾空白后的原始文本。

    输入参数：
        text:
            LLM 返回的原始文本内容。

    返回值：
        str:
            提取出的代码字符串。

    使用示例：
        >>> extract_code_block("```java\\nclass A {}\\n```")
        'class A {}'
    """
    # Try fenced block with language tag first (e.g. ```java, ```cpp)
    match = re.search(r"```\w+\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fall back to generic code block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No code fence found – return raw text
    logger.warning("No code fence found in LLM response, using raw text.")
    return text.strip()


# Backward-compatibility alias
extract_java_code = extract_code_block


class TestGenerator:
    """JUnit 测试生成与迭代优化器。

    功能简介：
        基于分析上下文构造 Prompt，调用 LLM 生成首版测试代码，
        或根据执行反馈继续优化已有测试。

    使用示例：
        >>> generator = TestGenerator("https://example.test/v1", "demo-key")
        >>> test = generator.generate(context)
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model: str = "qwen3.5-397b-a17b",
        timeout: int = 120,
        language: str = "java",
    ) -> None:
        """初始化测试生成器。

        功能简介：
            创建内部 LLM 客户端，为后续测试生成和修复流程提供统一访问入口。

        输入参数：
            api_base_url:
                OpenAI 兼容接口基础地址。
            api_key:
                接口认证密钥。
            model:
                默认调用的模型名称。
            timeout:
                单次请求超时时间，单位为秒。
            language:
                目标语言标识符（如 ``java``），用于选取对应语言的 Prompt 模板。

        返回值：
            None:
                构造函数仅完成初始化。

        使用示例：
            >>> generator = TestGenerator("https://example.test/v1", "demo-key", model="demo-model")
        """
        self._client = LLMClient(
            api_base_url=api_base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
        self._language = language

    def generate(self, context: AnalysisContext) -> GeneratedTest:
        """生成目标方法的首版测试代码。

        功能简介：
            根据分析上下文构造生成 Prompt，请求 LLM 生成测试代码，
            然后提取 Java 代码并规范化测试类名。

        输入参数：
            context:
                分析上下文，包含目标方法及其依赖源码。

        返回值：
            GeneratedTest:
                首轮生成的测试结果对象，其中 `iteration=1`。

        使用示例：
            >>> result = generator.generate(context)
            >>> result.iteration
            1
        """
        messages = build_generate_prompt(context, language=self._language)
        logger.info("Generating initial test for %s.%s",
                     context.target.class_name, context.target.method_name)
        raw_response = self._client.chat(messages)
        test_code = extract_code_block(raw_response)
        test_code = normalize_test_class_name(test_code, context.target.class_name)
        return GeneratedTest(test_code=test_code, iteration=1)

    def refine(
        self,
        context: AnalysisContext,
        previous_test: GeneratedTest,
        test_result: TestResult,
    ) -> GeneratedTest:
        """根据执行反馈优化上一轮测试代码。

        功能简介：
            使用上一轮测试代码和执行结果构造修复 Prompt，请求 LLM 输出优化版测试，
            再提取 Java 代码并规范化类名，同时将迭代次数加一。

        输入参数：
            context:
                分析上下文，包含目标方法与依赖信息。
            previous_test:
                上一轮生成的测试对象。
            test_result:
                上一轮执行结果，可能包含编译错误、失败测试和覆盖率信息。

        返回值：
            GeneratedTest:
                优化后的测试结果对象，`iteration` 比上一轮大 1。

        使用示例：
            >>> refined = generator.refine(context, previous_test, test_result)
            >>> refined.iteration == previous_test.iteration + 1
            True
        """
        messages = build_refine_prompt(context, previous_test, test_result, language=self._language)
        logger.info("Refining test for %s.%s (iteration %d -> %d)",
                     context.target.class_name, context.target.method_name,
                     previous_test.iteration, previous_test.iteration + 1)
        raw_response = self._client.chat(messages)
        test_code = extract_code_block(raw_response)
        test_code = normalize_test_class_name(test_code, context.target.class_name)
        return GeneratedTest(
            test_code=test_code,
            iteration=previous_test.iteration + 1,
        )
