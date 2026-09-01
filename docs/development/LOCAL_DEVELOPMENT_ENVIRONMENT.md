# My Funds 本地开发环境与 Luna 执行手册

> 最后验证：2026-09-01
> 本地项目：`E:\myfund11111`
> 原则：本地保存源码、依赖、合成数据和构建产物；生产数据、服务器秘密和真实持仓始终留在服务器。

## 1. 当前结论

本地环境已经达到可继续开发和回归测试的状态：

- 后端使用 Python `3.12.13`，与生产后端服务进程一致。
- 后端依赖已锁定，分析引擎与后端测试可以共用 `fund-advisor\.venv`。
- 前端使用 Node `24.15.0`、npm `11.12.1`，已按 `package-lock.json` 完成生产构建。
- 本地 MySQL 使用 `mysql:8.0.43`，只绑定 `127.0.0.1:3307`。
- Alembic 三段迁移已在空的合成数据库上成功执行。
- 本地后端 `/health` 和 SQLAlchemy `SELECT 1` 已通过。
- 本地配置关闭调度器和启动净值回补，不会因启动 API 自动抓取外部数据。

这套环境用于验证代码正确性、迁移、API 和前端构建，不代表本地复制了生产数据，也不保证投资盈利。盈利能力必须通过无未来函数的回测、样本外验证、费用建模和真实执行归因逐步验证。

## 2. 环境版本矩阵

| 组件 | 本地开发 | 服务器只读发现 | 约定 |
| --- | --- | --- | --- |
| 操作系统 | Windows 11 + WSL 2.7.12.0 | Rocky Linux | 业务代码保持跨平台 |
| Python | 3.12.13 | 后端主进程 3.12.13 | 后端测试以 3.12.13 为准 |
| Node.js | 24.15.0 | 24.16.0 | 当前可构建，后续建议统一补丁版本 |
| npm | 11.12.1 | 11.13.0 | 以 `package-lock.json` 为依赖事实来源 |
| 数据库 | MySQL 8.0.43 合成库 | 精确版本尚未确认 | 数据库兼容发布前必须在 staging 验证 |
| Docker | Server 29.6.1 / Compose 5.2.0 | 服务器存在 Docker，但业务库是主机进程 | 本地只承载合成 MySQL |

生产后端虽然由 `/usr/bin/python3.12` 运行，但该解释器的标准包元数据无法列出 FastAPI、SQLAlchemy 等业务依赖。这表明线上可能依赖自定义搜索路径、面板环境或未纳入仓库的部署状态。不要复制这种隐式状态；应以仓库依赖锁和可重复部署脚本逐步替代。

## 3. 本地目录职责

| 路径 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `E:\myfund11111\fund-advisor\.venv` | Python 3.12.13 后端与测试环境 | 否 |
| `E:\myfund11111\.runtime\python` | uv 管理的便携 Python | 否 |
| `E:\myfund11111\.runtime\uv-cache` | Python 与依赖缓存 | 否 |
| `E:\myfund11111\.tools\uv-venv` | 固定版本 uv 工具 | 否 |
| `E:\myfund11111\fund-advisor\frontend\node_modules` | 前端锁定依赖 | 否 |
| `E:\myfund11111\fund-advisor\frontend\dist` | 前端构建产物 | 否 |
| Docker 卷 `my-funds-local_fund_advisor_local_mysql` | 合成测试数据库 | 否 |
| `E:\myfund11111\fund-advisor\.env` | 本地合成环境配置 | 否 |
| `E:\myfund11111\ops\.env` | SSH 连接参数 | 否 |

不得把生产数据库导出、真实 Excel 持仓、服务器 `.env`、SSH 私钥、API Key 或完整运行日志放入上述本地项目目录。

## 4. 一次性初始化

在 PowerShell 执行：

```powershell
# 固定安装 Python 3.12.13、锁定后端依赖，并按 package-lock.json 安装前端依赖。
& 'E:\myfund11111\ops\Initialize-LocalDevelopment.ps1'
```

脚本行为：

1. 在 `E:\myfund11111\.tools\uv-venv` 引导固定版本 uv。
2. 在 `E:\myfund11111\.runtime\python` 安装 Python 3.12.13。
3. 创建或校准 `E:\myfund11111\fund-advisor\.venv`。
4. 按 `requirements-lock-py312-windows.txt` 精确同步依赖。
5. 仅在不存在时，从本地模板创建 `.env` 和 `alembic.ini`，绝不覆盖已有文件。
6. 执行 `npm ci`，不自动运行可能破坏兼容性的 `npm audit fix --force`。

只需要后端时可跳过前端依赖：

```powershell
# 跳过 npm ci，其余初始化照常执行。
& 'E:\myfund11111\ops\Initialize-LocalDevelopment.ps1' -SkipFrontendInstall
```

## 5. 合成 MySQL 生命周期

启动数据库：

```powershell
# 启动只绑定 127.0.0.1:3307 的本地 MySQL。
docker compose -f 'E:\myfund11111\fund-advisor\docker-compose.local.yml' up -d mysql
```

查看状态：

```powershell
# 查看容器健康状态和本地端口映射。
docker compose -f 'E:\myfund11111\fund-advisor\docker-compose.local.yml' ps
```

应用迁移：

```powershell
# 在合成数据库执行迁移；工作目录决定 Alembic 和 .env 的读取位置。
Set-Location -LiteralPath 'E:\myfund11111\fund-advisor'
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m alembic upgrade head
```

停止但保留合成数据：

```powershell
# 停止容器，保留 Docker 命名卷，便于下次继续测试。
docker compose -f 'E:\myfund11111\fund-advisor\docker-compose.local.yml' stop mysql
```

`docker compose down --volumes` 会删除合成数据库卷，属于破坏性重置。只有确认不需要本地测试数据时才能执行，并应先核对 Compose 项目名为 `my-funds-local`。它不会影响服务器数据库，但仍不可作为日常停止命令。

## 6. 启动本地服务

后端：

```powershell
# 本地 .env 已关闭调度器和启动净值回补，不会自动抓取外部净值。
Set-Location -LiteralPath 'E:\myfund11111\fund-advisor'
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8200 --reload
```

前端：

```powershell
# Vite 开发服务器在 8201，/api 代理到本地 8200。
Set-Location -LiteralPath 'E:\myfund11111\fund-advisor\frontend'
npm run dev
```

本地前端只用于开发预览。用户日常看到的正式页面仍由服务器提供；本地开发结果必须经过提交、staging 验证和明确发布后才会影响服务器展示。

## 7. 统一验证

```powershell
# 运行 Python 语法、敏感信息、Git 差异、分析引擎、后端和前端构建检查。
& 'E:\myfund11111\ops\Invoke-LocalChecks.ps1' -RunPythonTests -BuildFrontend
```

当前已验证结果：

- `fund-analyzer`：165 项测试通过。
- `fund-advisor/backend/tests`：5 项服务级回归测试通过。
- 前端：Vite 生产构建通过，转换 2102 个模块。
- 本地 API：`GET /health` 返回 `status=ok`。
- 本地数据库：MySQL 健康，三段迁移成功，`SELECT 1` 成功。

仓库根目录旧的 `.pytest_cache` 当前存在 ACL 权限问题，统一检查脚本可能在递归枚举 Python 文件时提前退出。不要直接删除未知来源目录；在脚本修复前可使用以下命令复验两套测试：

```powershell
# 禁用 pytest 缓存，避免旧缓存目录 ACL 影响测试。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m pytest `
  'E:\myfund11111\fund-analyzer\tests' -q -p no:cacheprovider

# 后端测试使用合成夹具和伪造 Session，不连接服务器数据库。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m pytest `
  'E:\myfund11111\fund-advisor\backend\tests' -q -p no:cacheprovider
```

完整 P0 验收证据见 `docs/development/P0_ACCEPTANCE_REPORT.md`。

## 8. 已知问题与下一批任务

### 8.1 前端依赖和体积

`npm ci` 报告 11 个漏洞，其中 3 个中等、8 个高危；排除开发依赖后，生产依赖链仍有 9 个漏洞，其中 3 个中等、6 个高危。不得直接执行 `npm audit fix --force`。Luna 应先运行 `npm audit`，逐项确认受影响依赖、运行路径、可用修复版本和 Vue/Vite 兼容性，再分批升级并回归构建。

当前入口 JavaScript 约 2.36 MB，gzip 后约 768 KB。应使用路由懒加载和稳定的 `manualChunks` 拆分 Vue、Element Plus、ECharts 及业务页面，并用构建结果比较首屏体积。

### 8.2 风控配置冲突

用户已经确认组合最大可接受回撤暂定为 20%，但 `backend/config.py` 的 `DD_HARD_STOP_PCT` 默认值仍为 25%。本地模板已设为 20%，生产默认尚未调整。Luna 必须把“业务风险上限”和“策略动作阈值”是否为同一个概念核对清楚；在未确认前，不得静默修改生产参数或宣称满足 20% 上限。

### 8.3 生产运行时漂移

服务器存在以下发布风险：

- systemd 后端进程是 Python 3.12.13，但依赖来源无法由标准包元数据复现。
- 系统默认 Python 3.9 不是后端真实运行时，不得再以它作为部署基线。
- 运行中的 `mysqld` 链接到 `/usr/sbin/mysqld`，直接执行该进程映像时提示缺少 `libssl.so.1.1`。这意味着数据库在未经维护验证前不应重启。
- 数据库没有监听 `127.0.0.1:3306`，精确版本和连接方式尚未确认。

在服务器维护窗口前，Luna 只能只读核实，不得重启数据库、替换库文件或修改生产连接配置。应先确认实际安装来源、共享库、数据目录、Socket/端口、备份工具和恢复演练。

## 9. Luna 接手清单

1. 完整阅读 `E:\myfund11111\00_LUNA_START_HERE.md` 及其中列出的文档。
2. 执行 `git status --short` 和 `git diff --check`，保留当前未提交工作，不覆盖服务器热修或用户改动。
3. 运行统一验证命令，确认本机环境仍为绿色。
4. 检查本地 MySQL 只绑定 `127.0.0.1:3307`，禁止改成 `0.0.0.0`。
5. 第一批盈利正确性修复已经在本地实现；先审查差异和测试，不要重复重写。
6. 后续优先完成交易确认与持仓同步、费用和到账状态、回测样本外验证、前端依赖安全与拆包。
7. 所有生产发布必须使用明确 Git SHA、服务器端备份、staging 验证和回滚记录。

## 10. 依赖升级规则

- 修改 `requirements.txt`、`fund-analyzer/requirements.txt` 或 `requirements-dev.txt` 后，必须重新创建 Python 3.12.13 环境、运行完整测试，再更新锁文件。
- 不得在服务器临时 `pip install` 后不回写依赖文件。
- 修改 `package.json` 后必须同步提交 `package-lock.json`，使用 `npm ci` 验证。
- 数据库镜像升级前必须在新命名卷上从零迁移，并测试 staging 的真实结构兼容性。
- 依赖升级和策略参数调整分开提交，便于定位收益变化究竟来自代码、数据还是参数。
