---
kind: configuration_system
name: YAML 单文件配置系统（PyInstaller 兼容）
category: configuration_system
scope:
    - '**'
source_files:
    - config.yaml
    - main.py
    - build.bat
    - build_exe.py
    - CMW500_BLE_Test.spec
---

## 1. 系统概述
本项目采用**单一 YAML 配置文件 + 启动期加载与规范化**的轻量级配置方案，通过 `main.py` 中的 `load_config()` 和 `_normalize_config()` 完成配置读取、默认值补全与向后兼容。打包后由 PyInstaller 将 `config.yaml` 嵌入 exe 同目录，运行时可直接编辑生效。

## 2. 核心文件与职责
- `config.yaml`：唯一持久化配置源，包含仪器连接参数、BLE 测试项及限值、导出路径等。
- `main.py`：集中实现配置加载 (`load_config`)、兼容性归一化 (`_normalize_config`)、APP_DIR 计算 (`get_app_dir`)，并将配置字典注入到 GUI/CLI 子流程。
- `build.bat` / `build_exe.py` / `CMW500_BLE_Test.spec`：构建阶段把 `config.yaml` 作为数据文件打包进 dist 目录，确保 exe 运行期可找到。

## 3. 架构与约定
- **加载位置**：优先从 `sys.executable` 所在目录（PyInstaller 打包后）或 `__file__` 同级目录读取 `config.yaml`；支持通过 `load_config(config_path)` 传入自定义路径。
- **解析方式**：使用 `yaml.safe_load`，仅允许安全标量/映射/序列类型，避免任意对象反序列化风险。
- **缺失字段处理**：`_normalize_config()` 在内存中补齐旧版格式缺少的 `instrument.lan/gpib/usb/interface_type/timeout` 等键，并写入默认值，保证后续模块直接按新结构访问而不崩溃。
- **传播方式**：配置以 Python dict 形式在进程内传递，被 `run_cli`、`run_gui`、`DataExporter`、`BLETxModulationTest` 等模块消费，无全局单例或独立 Config 类。
- **运行时修改**：由于配置在启动时一次性加载，运行时修改 `config.yaml` 不会自动热重载；需重启程序生效。

## 4. 开发者规则
- 新增配置项应在 `config.yaml` 中声明，并在 `_normalize_config()` 中补充默认值，保持向后兼容。
- 所有模块应通过接收到的 `config` 字典取值，禁止自行硬编码路径或再次调用 `load_config()`。
- 敏感信息（如 IP、序列号）仍存放在明文 YAML 中，如需升级应引入环境变量覆盖机制或加密存储层。
- 构建产物必须包含 `config.yaml`，否则程序启动会抛出 `RuntimeError` 提示找不到配置文件。