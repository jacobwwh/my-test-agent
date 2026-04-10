# 2026-04-10 最小修复清单

本文档只列“最小且必要”的修复动作，目标是先消除已确认的显性缺陷，不做额外重构。

## P0

### 1. 修复安装后 CLI 入口失效

- 问题：`pyproject.toml` 暴露了 `testagent = "testagent.cli:main"`，但仓库中不存在 `src/testagent/cli.py`。
- 最小修复：
  - 二选一：
  - 新增 `src/testagent/cli.py`，提供 `main()` 并显式复用现有脚本入口。
  - 或修改 `pyproject.toml`，移除/替换这个不存在的入口。
- 验证：
  - `python -c "import testagent.cli"`
  - 重新安装后执行 `testagent --help`

### 2. 修复覆盖率未达标却仍被判定成功

- 问题：`test_executor.py` 和 `test_repair.py` 在达到最大迭代后，只要 `result.passed` 为真就返回成功，即使 `min_branch_coverage` 未达标。
- 最小修复：
  - 将最终成功条件统一为：
  - `result.passed and _coverage_met(result, min_branch_coverage)`
  - `test_repair.py` 仅在上述条件满足时才保存“修复成功”产物。
- 验证：
  - 构造 `passed=True` 但 `branch_coverage < min_branch_coverage` 的结果。
  - 确认 summary 显示失败，repair 流程不保存成功产物。

### 3. 修复构建异常时测试文件残留

- 问题：`TestExecutor.execute()` 在 `run_build()` 抛异常时提前返回，跳过清理逻辑。
- 最小修复：
  - 把测试文件清理放进 `finally`，并保持 `keep_test=True` 时不删除。
  - 不要改变现有返回结构。
- 验证：
  - mock `run_build()` 抛异常。
  - 确认 `keep_test=False` 时注入的测试文件已删除。

## P1

### 4. 修正 `YUNWU_API_KEY` 优先级实现

- 问题：代码当前是“配置文件优先于环境变量”，与 README 和注释声明相反。
- 最小修复：
  - 若文档口径不改，则将 `load_config()` 改为环境变量始终覆盖配置文件中的 `llm.api_key`。
  - 同步补一条单测覆盖“文件值 + 环境变量同时存在”的场景。
- 验证：
  - 配置文件写 `from-file`，环境变量设 `from-env`。
  - 结果应为 `from-env`。

### 5. 修复导出测试文件名与类名不一致

- 问题：导出的文件名是 `Calculator_add_Test.java`，但类名被规范成 `CalculatorTest`；该文件离开执行器后本身不可直接编译。
- 最小修复：
  - `test_generator.py` 和 `test_repair.py` 的导出文件名改为与最终类名一致。
  - 最小做法是直接复用 `canonical_test_class_name()`，输出 `<CanonicalName>.java`。
- 验证：
  - 生成产物文件名与 `public class` 名完全一致。

## P2

### 6. 修复仓库根目录执行 `pytest` 的收集失败

- 问题：顶层脚本 `test_analyzer.py`、`test_generator.py`、`test_executor.py` 与 `tests/test_*` 包目录重名，导致 `pytest` 从仓库根执行时收集失败。
- 最小修复：
  - 优先重命名顶层脚本，避免与测试包重名。
  - 或增加明确的 `pytest` 配置限制收集范围，但这只是绕过，不如改名直接。
- 验证：
  - `pytest -q`
  - `pytest -q tests`
  - 两者都应通过。

## 建议修复顺序

1. CLI 入口
2. 覆盖率成功判定
3. 构建异常清理
4. API Key 优先级
5. 导出文件名
6. 顶层脚本命名冲突

## 建议补充的最小测试

- `tests/test_config.py`
  - 增加环境变量覆盖配置文件中 `api_key` 的测试。
- `tests/test_executor/test_test_executor.py`
  - 增加“build 异常后测试文件被清理”的测试。
  - 增加“覆盖率不达标时 execute/调用方不应判成功”的调用层测试。
- 新增脚本级测试或轻量验证
  - 校验导出文件名与类名一致。
  - 校验 `pytest -q` 不再因命名冲突失败。
