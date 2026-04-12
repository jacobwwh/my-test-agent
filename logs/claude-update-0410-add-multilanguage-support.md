 Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Refactoring: Multi-Language Support (--language Parameter)

 Context

 The pipeline currently only supports Java. To prepare for C++ and other languages, we need to reorganize
 language-specific code (analyzer, executor, prompts) into per-language subdirectories and add a --language CLI
 parameter. This refactoring is structural — only Java is functional; C++ directories will be stubs.

 Target Directory Structure

 src/testagent/
 ├── analyzer/
 │   ├── __init__.py          # Factory create_analyzer() + backward-compat re-export of JavaAnalyzer
 │   ├── base.py              # NEW: BaseAnalyzer ABC
 │   └── java/
 │       ├── __init__.py      # JavaAnalyzer class (MOVED from analyzer/__init__.py)
 │       ├── java_parser.py   # MOVED from analyzer/java_parser.py
 │       └── dependency.py    # MOVED from analyzer/dependency.py
 ├── executor/
 │   ├── __init__.py          # Factory create_executor() + backward-compat re-export of TestExecutor
 │   ├── base.py              # NEW: BaseExecutor ABC
 │   └── java/
 │       ├── __init__.py      # JavaTestExecutor (MOVED from executor/__init__.py, alias TestExecutor kept)
 │       ├── builder.py       # MOVED from executor/builder.py
 │       ├── runner.py        # MOVED from executor/runner.py
 │       └── coverage.py      # MOVED from executor/coverage.py
 ├── generator/
 │   ├── __init__.py          # Unchanged
 │   ├── llm_client.py        # Unchanged
 │   ├── prompt.py            # MODIFIED: add language param to _get_env, build_generate_prompt, build_refine_prompt
 │   └── test_generator.py    # MODIFIED: add language param to __init__, pass to prompt functions; rename
 extract_java_code -> extract_code_block (keep alias)
 ├── cli_utils.py             # Unchanged
 ├── config.py                # MODIFIED: read project.language from YAML
 └── models.py                # MODIFIED: Config gains language field
 prompts/
 ├── java/
 │   ├── generate_test.txt    # MOVED from prompts/generate_test.txt
 │   └── fix_test.txt         # MOVED from prompts/fix_test.txt
 └── cpp/
     ├── generate_test.txt    # Placeholder stub
     └── fix_test.txt         # Placeholder stub

 Implementation Steps

 Phase 1: Abstract base classes (no moves, no breakage)

 1. Create src/testagent/analyzer/base.py — BaseAnalyzer(ABC) with abstract analyze(class_name, method_name) ->
 AnalysisContext and shared __init__(project_path)
 2. Create src/testagent/executor/base.py — BaseExecutor(ABC) with abstract execute(test, context) -> TestResult and
 shared __init__(project_path, reports_dir, keep_test, build_timeout)
 3. Make existing JavaAnalyzer inherit from BaseAnalyzer in its current location (additive)
 4. Make existing TestExecutor inherit from BaseExecutor in its current location (additive)
 5. Run tests to verify

 Phase 2: Move analyzer files into analyzer/java/

 6. Create src/testagent/analyzer/java/__init__.py — move JavaAnalyzer class here
 7. Move analyzer/java_parser.py → analyzer/java/java_parser.py (no content changes)
 8. Move analyzer/dependency.py → analyzer/java/dependency.py — update internal import: from
 testagent.analyzer.java_parser → from testagent.analyzer.java.java_parser
 9. Update JavaAnalyzer imports in analyzer/java/__init__.py to use new submodule paths
 10. Rewrite analyzer/__init__.py — factory create_analyzer(language, project_path) + backward-compat from
 testagent.analyzer.java import JavaAnalyzer
 11. Update test imports:
   - tests/test_analyzer/test_java_parser.py: from testagent.analyzer.java.java_parser import ...
   - tests/test_analyzer/test_dependency.py: from testagent.analyzer.java.dependency import ... and from
 testagent.analyzer.java.java_parser import ...
   - tests/test_analyzer/test_java_analyzer.py: no change needed (backward-compat re-export)
 12. Run tests

 Phase 3: Move executor files into executor/java/

 13. Create src/testagent/executor/java/__init__.py — move TestExecutor here, rename to JavaTestExecutor, keep
 TestExecutor = JavaTestExecutor alias
 14. Move executor/builder.py → executor/java/builder.py
 15. Move executor/runner.py → executor/java/runner.py
 16. Move executor/coverage.py → executor/java/coverage.py
 17. Update JavaTestExecutor imports in executor/java/__init__.py to use new submodule paths
 18. Rewrite executor/__init__.py — factory create_executor(language, project_path, **kwargs) + backward-compat from
 testagent.executor.java import TestExecutor
 19. Update test imports:
   - tests/test_executor/test_builder.py: from testagent.executor.java.builder import ...
   - tests/test_executor/test_runner.py: from testagent.executor.java.runner import ...
   - tests/test_executor/test_coverage.py: from testagent.executor.java.coverage import ...
   - tests/test_executor/test_test_executor.py: no change needed (backward-compat re-export)
 20. Run tests

 Phase 4: Move prompts into language subdirectories

 21. Create prompts/java/ directory
 22. Move prompts/generate_test.txt → prompts/java/generate_test.txt
 23. Move prompts/fix_test.txt → prompts/java/fix_test.txt
 24. Update generator/prompt.py:
   - Rename _PROMPTS_DIR → _PROMPTS_ROOT
   - Add language: str = "java" param to _get_env(), build_generate_prompt(), build_refine_prompt()
   - Default template path: _PROMPTS_ROOT / language
   - When prompts_dir is explicitly provided, it still takes precedence
 25. Update generator/test_generator.py:
   - Add language: str = "java" to TestGenerator.__init__(), store as self._language
   - Pass language=self._language to build_generate_prompt() and build_refine_prompt()
   - Rename extract_java_code() → extract_code_block(), keep extract_java_code = extract_code_block alias for backward
 compat
 26. Update tests/test_generator/test_prompt.py if it passes explicit prompts_dir (likely no change needed since tests
 use prompts_dir override or defaults)
 27. Run tests

 Phase 5: Config and CLI wiring

 28. Add language: str = "java" to Config dataclass in models.py
 29. Update config.py load_config(): read project.language from YAML into flat["language"]
 30. Update configs/default.yaml: add language: "java" under project:
 31. Add --language argument to all entry-point scripts:
   - test_executor.py: add to parse_args(), pass as override to load_config(), use create_analyzer/create_executor +
 pass language to TestGenerator
   - test_generator.py: same pattern
   - test_repair.py: same pattern
 32. Run tests

 Phase 6: C++ stubs (optional, minimal)

 33. Create prompts/cpp/generate_test.txt and prompts/cpp/fix_test.txt with placeholder text
 34. No analyzer/cpp/ or executor/cpp/ directories needed yet — the factory will raise ValueError for unsupported
 languages, which is the correct behavior until C++ is implemented

 Key Files to Modify

 ┌────────────────────────────────────────────┬──────────────────────────────────────────────┐
 │                    File                    │                    Change                    │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/analyzer/__init__.py         │ Rewrite: factory + re-export                 │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/analyzer/base.py             │ NEW: BaseAnalyzer ABC                        │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/analyzer/java/__init__.py    │ NEW: JavaAnalyzer moved here                 │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/analyzer/java/java_parser.py │ MOVED from analyzer/                         │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/analyzer/java/dependency.py  │ MOVED + fix import path                      │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/__init__.py         │ Rewrite: factory + re-export                 │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/base.py             │ NEW: BaseExecutor ABC                        │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/java/__init__.py    │ NEW: JavaTestExecutor moved here             │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/java/builder.py     │ MOVED from executor/                         │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/java/runner.py      │ MOVED from executor/                         │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/executor/java/coverage.py    │ MOVED from executor/                         │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/generator/prompt.py          │ Add language param                           │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/generator/test_generator.py  │ Add language param, rename extract_java_code │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/models.py                    │ Config gains language field                  │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ src/testagent/config.py                    │ Read project.language from YAML              │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ configs/default.yaml                       │ Add language: "java"                         │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ test_executor.py                           │ Add --language, use factories                │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ test_generator.py                          │ Add --language, use factories                │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ test_repair.py                             │ Add --language, use factories                │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ prompts/java/*.txt                         │ MOVED from prompts/                          │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ tests/test_analyzer/test_java_parser.py    │ Fix import path                              │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ tests/test_analyzer/test_dependency.py     │ Fix import path                              │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ tests/test_executor/test_builder.py        │ Fix import path                              │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ tests/test_executor/test_runner.py         │ Fix import path                              │
 ├────────────────────────────────────────────┼──────────────────────────────────────────────┤
 │ tests/test_executor/test_coverage.py       │ Fix import path                              │
 └────────────────────────────────────────────┴──────────────────────────────────────────────┘

 Factory Pattern

 Simple lazy-init dict registry in each module's __init__.py:

 # analyzer/__init__.py
 from testagent.analyzer.base import BaseAnalyzer

 def create_analyzer(language: str, project_path: Path) -> BaseAnalyzer:
     from testagent.analyzer.java import JavaAnalyzer
     registry = {"java": JavaAnalyzer}
     cls = registry.get(language)
     if cls is None:
         raise ValueError(f"Unsupported language: {language!r}. Supported: {sorted(registry)}")
     return cls(project_path)

 Same pattern for executor.

 Verification

 1. python -m pytest tests/ — all existing tests must pass
 2. python test_executor.py --list — should work as before
 3. python test_executor.py --language java --target Calculator.add — should work identically to current behavior
 4. python test_executor.py --language cpp — should fail with clear "unsupported language" error (or
 NotImplementedError)
 5. Verify imports: python -c "from testagent.analyzer import JavaAnalyzer; from testagent.executor import
 TestExecutor" — backward compat