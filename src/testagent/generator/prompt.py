"""Prompt template loading and rendering."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from testagent.models import AnalysisContext, GeneratedTest, TestResult

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _get_env(prompts_dir: Path | None = None, language: str = "java") -> Environment:
    """创建 Prompt 模板渲染环境。

    功能简介：
        基于指定的 prompts 目录创建一个 Jinja2 `Environment`，
        用于加载和渲染测试生成与修复模板。当 `prompts_dir` 为 `None` 时，
        自动使用 `_PROMPTS_ROOT / language` 作为模板目录。

    输入参数：
        prompts_dir:
            Prompt 模板目录；为 `None` 时根据 `language` 选择默认目录。
        language:
            目标语言标识符（如 ``java``），用于定位语言子目录。
            仅在 `prompts_dir` 为 `None` 时生效。

    返回值：
        Environment:
            已配置 `FileSystemLoader` 的 Jinja2 渲染环境。

    使用示例：
        >>> env = _get_env(language="java")
        >>> env.get_template("generate_test.txt")
    """
    resolved_dir = prompts_dir if prompts_dir is not None else _PROMPTS_ROOT / language
    return Environment(
        loader=FileSystemLoader(str(resolved_dir)),
        keep_trailing_newline=True,
    )


def build_generate_prompt(
    context: AnalysisContext,
    prompts_dir: Path | None = None,
    language: str = "java",
) -> list[dict[str, str]]:
    """构造首次生成测试用例的聊天消息。

    功能简介：
        将分析阶段得到的目标方法、依赖源码和 import 信息渲染进
        `generate_test.txt` 模板，生成可直接发送给 LLM 的消息列表。

    输入参数：
        context:
            分析上下文，包含目标方法、依赖源码、imports 和 package 信息。
        prompts_dir:
            自定义 Prompt 模板目录；为 `None` 时根据 `language` 选择默认目录。
        language:
            目标语言标识符（如 ``java``），用于定位语言子目录。
            仅在 `prompts_dir` 为 `None` 时生效。

    返回值：
        list[dict[str, str]]:
            符合 OpenAI Chat API 结构的消息列表，通常为单条 `user` 消息。

    使用示例：
        >>> messages = build_generate_prompt(context)
        >>> messages[0]["role"]
        'user'
    """
    env = _get_env(prompts_dir, language)
    template = env.get_template("generate_test.txt")
    rendered = template.render(
        target=context.target,
        dependencies=context.dependencies,
        imports=context.imports,
        package=context.package,
        existing_test_summary=context.existing_test_summary,
    )
    return [{"role": "user", "content": rendered}]


def build_refine_prompt(
    context: AnalysisContext,
    previous_test: GeneratedTest,
    test_result: TestResult,
    prompts_dir: Path | None = None,
    language: str = "java",
) -> list[dict[str, str]]:
    """构造测试修复/迭代优化的聊天消息。

    功能简介：
        将目标方法上下文、上一轮测试代码以及编译/执行/覆盖率反馈渲染进
        `fix_test.txt` 模板，生成下一轮优化测试用例所需的输入消息。

    输入参数：
        context:
            分析上下文，包含目标方法及依赖信息。
        previous_test:
            上一轮生成的测试代码。
        test_result:
            上一轮执行结果，包含编译错误、失败测试和覆盖率信息。
        prompts_dir:
            自定义 Prompt 模板目录；为 `None` 时根据 `language` 选择默认目录。
        language:
            目标语言标识符（如 ``java``），用于定位语言子目录。
            仅在 `prompts_dir` 为 `None` 时生效。

    返回值：
        list[dict[str, str]]:
            符合 OpenAI Chat API 结构的消息列表。

    使用示例：
        >>> messages = build_refine_prompt(context, previous_test, test_result)
        >>> messages[0]["role"]
        'user'
    """
    env = _get_env(prompts_dir, language)
    template = env.get_template("fix_test.txt")
    rendered = template.render(
        target=context.target,
        dependencies=context.dependencies,
        previous_test=previous_test,
        test_result=test_result,
    )
    return [{"role": "user", "content": rendered}]
