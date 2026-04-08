# Analyzer 模块文档

`testagent.analyzer` 模块负责对 Java 源码进行静态分析，提取目标方法及其项目内依赖的上下文信息，为后续 LLM 生成测试用例提供输入。

模块由三部分组成：

| 文件 | 职责 |
|------|------|
| `analyzer/__init__.py` | 对外门面类 `JavaAnalyzer` |
| `analyzer/java_parser.py` | 基于 tree-sitter 的 Java AST 解析 |
| `analyzer/dependency.py` | 依赖类型解析与源码提取 |

---

## 快速上手

```python
from pathlib import Path
from testagent.analyzer import JavaAnalyzer

analyzer = JavaAnalyzer(Path("/path/to/java-project"))
ctx = analyzer.analyze("com.example.service.OrderService", "process")

# 目标方法源码
print(ctx.target.method_signature)

# 所属类源码
print(ctx.target.class_source)

# 项目内依赖列表
for dep in ctx.dependencies:
    print(f"{dep.kind} {dep.qualified_name}")
```

---

## 门面类：`JavaAnalyzer`

**所在模块**：`testagent.analyzer`

### `__init__(self, project_path: Path)`

创建分析器实例。

| 参数 | 类型 | 说明 |
|------|------|------|
| `project_path` | `Path` | Java 项目根目录，需包含 `src/main/java`、`src/java` 或 `src` 源码目录之一 |

### `analyze(self, class_name: str, method_name: str) -> AnalysisContext`

分析指定类中的目标方法，返回完整上下文。

| 参数 | 类型 | 说明 |
|------|------|------|
| `class_name` | `str` | 全限定类名，如 `"com.example.service.OrderService"` |
| `method_name` | `str` | 方法名，如 `"process"` |

**返回值**：`AnalysisContext` 数据类（见下方数据模型部分）。

**异常**：

| 异常类型 | 触发条件 |
|----------|----------|
| `FileNotFoundError` | 无法在项目源码目录中找到对应的 `.java` 文件 |
| `ValueError` | 文件中找不到指定的类名或方法名。方法未找到时，错误信息会列出该类中所有可用的方法名 |

```python
analyzer = JavaAnalyzer(Path("my-project"))

# 正常调用
ctx = analyzer.analyze("com.example.Calculator", "add")

# 类文件不存在 -> FileNotFoundError
analyzer.analyze("com.example.Missing", "foo")

# 方法不存在 -> ValueError: Method 'bad' not found ... Available methods: ['add', 'divide']
analyzer.analyze("com.example.Calculator", "bad")
```

---

## 底层 API：`java_parser` 模块

**所在模块**：`testagent.analyzer.java_parser`

以下函数可单独使用，适合需要对 Java 源码进行细粒度操作的场景。

### `find_java_file(project_path: Path, class_name: str) -> Path | None`

根据全限定类名在项目中查找对应的 `.java` 文件。

按以下顺序搜索源码目录：`src/main/java` > `src/java` > `src`。

```python
from testagent.analyzer.java_parser import find_java_file

path = find_java_file(Path("my-project"), "com.example.model.Order")
# -> Path("my-project/src/main/java/com/example/model/Order.java") 或 None
```

### `parse_source(source: bytes) -> ts.Node`

将 Java 源码字节串解析为 tree-sitter AST，返回根节点。

```python
from testagent.analyzer.java_parser import parse_source

root = parse_source(b"package com.example; public class Foo { }")
print(root.type)  # "program"
```

### `extract_package(root: ts.Node) -> str`

从 AST 根节点提取包声明。

```python
root = parse_source(Path("Foo.java").read_bytes())
pkg = extract_package(root)  # "com.example"
```

无包声明时返回空字符串 `""`。

### `extract_imports(root: ts.Node) -> list[str]`

提取所有 import 语句，每条作为完整字符串返回。

```python
imports = extract_imports(root)
# ["import java.util.List;", "import com.example.model.Order;"]
```

### `find_method_node(class_node: ts.Node, method_name: str) -> ts.Node | None`

在类节点中按名称查找方法声明节点。

```python
from testagent.analyzer.java_parser import parse_source, _find_class_node, find_method_node

root = parse_source(source_bytes)
cls = _find_class_node(root, "Calculator")
method = find_method_node(cls, "add")  # ts.Node 或 None
```

### `list_method_names(class_node: ts.Node) -> list[str]`

返回类中所有方法的名称列表。

```python
names = list_method_names(cls)  # ["add", "divide"]
```

### `extract_type_refs(class_node: ts.Node, method_node: ts.Node | None) -> TypeRefs`

从类声明和方法声明中提取所有引用的类型名称。

```python
from testagent.analyzer.java_parser import extract_type_refs

refs = extract_type_refs(cls, method)
print(refs.superclass)    # "BaseService" 或 None
print(refs.interfaces)    # ["Processable"]
print(refs.field_types)   # ["OrderDao", "List"]
print(refs.return_type)   # "Order"
print(refs.param_types)   # ["Order"]
print(refs.body_types)    # ["IllegalArgumentException"]
```

当 `method_node` 为 `None` 时，只提取类级别的引用（字段、父类、接口），不提取方法级别的引用（返回类型、参数、方法体）。

### `all_referenced_types(refs: TypeRefs) -> set[str]`

将 `TypeRefs` 中所有类型名称合并为去重集合。

```python
from testagent.analyzer.java_parser import all_referenced_types

types = all_referenced_types(refs)
# {"Order", "OrderDao", "BaseService", "Processable", "IllegalArgumentException", "List"}
```

### `parse_target(project_path: Path, class_name: str, method_name: str) -> ParseResult`

高层封装：定位文件 -> 解析 AST -> 提取包/import/类源码/方法源码/类型引用，一步完成。

```python
from testagent.analyzer.java_parser import parse_target

result = parse_target(Path("my-project"), "com.example.Calculator", "add")
print(result.package)         # "com.example"
print(result.imports)         # [...]
print(result.class_source)    # 完整类源码
print(result.method_source)   # 目标方法源码
print(result.type_refs)       # TypeRefs 实例
print(result.file_path)       # Path 对象
```

**异常**：与 `JavaAnalyzer.analyze` 相同（`FileNotFoundError` / `ValueError`）。

---

## 底层 API：`dependency` 模块

**所在模块**：`testagent.analyzer.dependency`

### `resolve_dependencies(project_path, type_names, imports, target_package) -> list[Dependency]`

将一组类型名称解析为项目内的 `.java` 源文件，返回 `Dependency` 列表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `project_path` | `Path` | Java 项目根目录 |
| `type_names` | `set[str]` | 待解析的简单类型名集合，如 `{"Order", "OrderDao"}` |
| `imports` | `list[str]` | 目标文件的 import 语句列表 |
| `target_package` | `str` | 目标类的包名，用于同包类型推断 |

**解析策略**（按优先级）：

1. 跳过内置类型（JDK / 基本类型，如 `String`、`List`、`int`）
2. 从显式 import 语句映射全限定名
3. 假设类型与目标类在同一包下
4. 尝试通配符 import 的包前缀

只有在项目中实际找到 `.java` 文件的类型才会被返回。

```python
from testagent.analyzer.dependency import resolve_dependencies

deps = resolve_dependencies(
    project_path=Path("my-project"),
    type_names={"Order", "String", "OrderDao"},
    imports=["import com.example.model.Order;", "import com.example.dao.OrderDao;"],
    target_package="com.example.service",
)
# String 被跳过（内置类型），返回 Order 和 OrderDao 两个 Dependency
```

---

## 数据模型

### `TargetMethod`

| 字段 | 类型 | 说明 |
|------|------|------|
| `class_name` | `str` | 全限定类名，如 `"com.example.MyService"` |
| `method_name` | `str` | 方法名，如 `"processOrder"` |
| `method_signature` | `str` | 方法完整源码 |
| `file_path` | `Path` | `.java` 文件的绝对路径 |
| `class_source` | `str` | 所属类的完整源码 |

### `Dependency`

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | `str` | 类型种类：`"class"`、`"interface"` 或 `"enum"` |
| `qualified_name` | `str` | 全限定名，如 `"com.example.model.Order"` |
| `source` | `str` | 依赖的完整源码 |
| `file_path` | `Path` | `.java` 文件路径 |

### `AnalysisContext`

`JavaAnalyzer.analyze()` 的返回值，包含生成测试所需的全部上下文。

| 字段 | 类型 | 说明 |
|------|------|------|
| `target` | `TargetMethod` | 目标方法信息 |
| `dependencies` | `list[Dependency]` | 项目内已解析的依赖列表 |
| `imports` | `list[str]` | 目标文件的 import 语句 |
| `package` | `str` | 目标文件的包声明 |

### `TypeRefs`

`java_parser` 内部使用的中间数据类，记录从 AST 中提取的类型引用。

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_types` | `list[str]` | 类字段的类型名 |
| `param_types` | `list[str]` | 方法参数的类型名 |
| `return_type` | `str \| None` | 方法返回类型名 |
| `body_types` | `list[str]` | 方法体中引用的类型名 |
| `superclass` | `str \| None` | 父类名 |
| `interfaces` | `list[str]` | 实现的接口名列表 |

### `ParseResult`

`parse_target()` 的返回值。

| 字段 | 类型 | 说明 |
|------|------|------|
| `package` | `str` | 包声明 |
| `imports` | `list[str]` | import 语句列表 |
| `class_source` | `str` | 类完整源码 |
| `method_source` | `str` | 方法完整源码 |
| `type_refs` | `TypeRefs` | 提取的类型引用 |
| `file_path` | `Path` | `.java` 文件路径 |

---

## 设计约束

- **仅解析项目源码**：不解析 `.class` 文件或 JAR 包中的依赖
- **深度为 1**：只解析目标方法的直接依赖，不做传递依赖解析
- **跳过标准库**：`java.lang`、`java.util` 等常见 JDK 类型会被自动过滤，不会尝试在项目中查找
- **源码目录约定**：按 `src/main/java` > `src/java` > `src` 的优先级搜索
