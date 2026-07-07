---
kind: dependency_management
name: Python 依赖管理（requirements.txt + PyInstaller 打包）
category: dependency_management
scope:
    - '**'
source_files:
    - requirements.txt
    - build_exe.py
    - CMW500_BLE_Test.spec
---

本项目采用 Python 生态中最基础的依赖声明方式，通过根目录的 requirements.txt 集中声明所有第三方库，并使用 PyInstaller 将应用打包为 Windows 可执行文件。

1. 使用的系统与工具
- 依赖声明：requirements.txt，未使用 pipenv、poetry、conda 等更现代的锁定/环境管理工具。
- 后端驱动：pyvisa-py 作为纯 Python 的 VISA 后端，避免安装 NI-VISA 原生驱动。
- 打包工具：PyInstaller，提供两种构建入口——build_exe.py（Python 脚本形式）和 CMW500_BLE_Test.spec（标准 spec 文件），均输出到 dist/CMW500_BLE_Test/ 目录。
- 压缩：启用 UPX 对产物进行压缩。

2. 关键文件与包
- requirements.txt：唯一依赖清单，包含仪器控制（pyvisa、pyvisa-py、pyusb、pyserial）、GUI（PyQt6）、数据处理（pandas、openpyxl、matplotlib）、配置（PyYAML）及打包（pyinstaller）。
- build_exe.py：以 Python 脚本形式定义 PyInstaller 的 Analysis/PYZ/EXE/COLLECT 阶段，显式列出 hiddenimports（如 pyvisa_py.protocols.*、usb.core、serial.tools 等），确保动态导入的模块被正确捕获。
- CMW500_BLE_Test.spec：PyInstaller 标准 spec 文件，作用与 build_exe.py 等价，便于直接使用 pyinstaller CMW500_BLE_Test.spec 命令构建。
- config.yaml：运行时配置文件，通过 datas=[('config.yaml', '.')] 被打包进 exe 同目录，支持运行时修改。

3. 架构与约定
- 无版本锁定：requirements.txt 中所有包均未指定版本号，意味着每次 pip install -r requirements.txt 都会拉取 pip 索引中的最新兼容版本，存在环境不一致风险。
- 无虚拟环境约束：仓库未包含 .venv、Pipfile.lock、poetry.lock 或 environment.yml 等锁定文件，也未在 README 中说明虚拟环境创建流程。
- 双构建入口并存：同时维护 build_exe.py 和 CMW500_BLE_Test.spec 两个 PyInstaller 配置，二者内容高度重复，缺少单一真相源。
- 隐藏导入集中管理：由于 pyvisa-py、PyQt6、matplotlib 等库大量使用动态导入，必须在 hiddenimports 中显式声明子模块，否则打包后运行会报 ModuleNotFoundError。
- 数据文件内嵌：config.yaml 通过 datas 字段打包到输出目录，而非作为外部资源加载。

4. 开发者应遵循的规则
- 新增依赖时，务必同步更新 requirements.txt 并建议添加明确版本号（如 PyQt6==6.x.y），以保证构建可重现性。
- 若引入新的动态导入库，需检查其是否需要在 build_exe.py 或 CMW500_BLE_Test.spec 的 hiddenimports 中补充子模块。
- 二选一维护 PyInstaller 配置：优先保留 CMW500_BLE_Test.spec（PyInstaller 官方推荐格式），删除冗余的 build_exe.py，避免两处配置不同步。
- 建议在项目根目录增加 .gitignore 排除 dist/、build/、.venv/ 等生成目录，并在 CI 中固定 Python 版本与 pip 缓存策略。