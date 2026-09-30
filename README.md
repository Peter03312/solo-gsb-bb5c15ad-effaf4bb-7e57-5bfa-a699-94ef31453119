# 测序样本拼池 Web 工作台

面向测序实验员的样本拼池（Pooling）工作台。录入样本信息与拼池约束后，系统用混合整数规划
（MILP，HiGHS）**精确求解**：在满足全部硬约束的前提下，**先最大化可安排样本数，再最小化
使用池数**，输出每个池的配液表；无法安排的样本给出明确原因，绝不生成虚假配方。

## 功能

- **批次参数**：可用池数、单池体积上限、移液量下限。
- **样本录入**：样本名称、浓度、可用体积、目标投料量、索引序列（Index）；支持单条录入与
  批量粘贴（制表符/逗号分隔）。
  - **取液量 = 目标投料量 ÷ 浓度**，录入时实时计算并提示越限。
  - 所有数量字段必须**严格为正数**，非正数、空名称、非法索引一律拒绝（HTTP 422）。
  - 同批次样本名称不得重复。
- **配液方案**：
  - 硬约束：取液量 ≥ 移液量下限；取液量 ≤ 样本可用体积；取液量 ≤ 单池体积上限；
    池内总取液量 ≤ 单池体积上限；**同一池内索引序列不得重复**。
  - 输出各池配液表（样本、索引、浓度、目标投料、取液量、合计体积）与**未安排样本及具体原因**。
- **复测浓度后重算**：
  - 样本在**未锁定池**：以新浓度重算取液量，仅对未锁定池重新优化。
  - 样本在**已锁定池**：**原配方完整保留**，只显示受影响警示（新旧取液量对比、越限提示），
    并写入版本记录。
- **池锁定 / 解锁**：锁定即固化该池配方（含锁定时浓度快照）；解锁后该池样本重新参与全局优化。
- **版本记录**：每次生成 / 重算 / 锁定池复测均产生一个版本，含触发方式、统计与警示时间线。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、scipy MILP（HiGHS）、SQLite（标准库 `sqlite3`） |
| 前端 | React 18、Vite |
| 部署 | 多阶段 Dockerfile、Docker Compose（单容器同时提供 API 与静态页面） |

## 目录结构

```
.
├── backend/            FastAPI 应用
│   ├── app/
│   │   ├── main.py         HTTP 路由、异常处理、静态文件挂载
│   │   ├── service.py      业务逻辑（拼池流程、锁定、复测）
│   │   ├── optimizer.py    MILP 模型（scipy.optimize.milp）
│   │   ├── db.py           SQLite 连接与建表脚本
│   │   └── schemas.py      Pydantic 输入校验（正数约束等）
│   ├── init_db.py          初始化数据库
│   ├── entrypoint.sh       容器入口：先建库再起服务
│   └── requirements.txt
├── frontend/           React + Vite 前端
│   └── src/
├── Dockerfile          多阶段构建（前端构建 → Python 运行时）
├── docker-compose.yml  一键启动 + 数据卷持久化
└── .env.example        端口配置示例
```

## 一键启动（推荐，Docker Compose）

前置：已安装 Docker 与 Docker Compose 插件。

```bash
# 可选：修改宿主机访问端口（默认 8000）
cp .env.example .env
# 编辑 .env 设置 WEB_PORT=8000

# 构建并后台启动（自动安装依赖、初始化数据库）
docker compose up -d --build

# 查看状态 / 日志
docker compose ps
docker compose logs -f
```

启动后打开浏览器：

- **页面地址**：<http://localhost:8000>
- **API 健康检查**：<http://localhost:8000/api/health>
- **交互式 API 文档（Swagger）**：<http://localhost:8000/docs>

> 若在 `.env` 中把 `WEB_PORT` 改为其他端口（如 9000），则访问
> <http://localhost:9000>。容器内服务始终监听 8000，由端口映射对外暴露。

停止与数据：

```bash
docker compose down          # 停止（数据保留在 Docker 卷 pooling-data 中）
docker compose down -v       # 停止并删除数据库卷（清空全部数据，谨慎使用）
```

数据库文件持久化在卷 `pooling-data`（容器内 `/app/data/pooling.db`）。

## 本地开发（不使用 Docker）

需要 Python 3.11+ 与 Node 18+。

### 1. 启动后端

```bash
cd backend
python -m pip install -r requirements.txt
export POOL_DB_PATH="$(pwd)/data/pooling.db"
python init_db.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 启动前端（开发服务器，自动代理 /api）

```bash
cd frontend
npm install
npm run dev          # 默认 http://localhost:5173 ，/api 代理到 http://localhost:8000
```

- 前端开发页面：<http://localhost:5173>
- 若后端不在本机 8000，可用 `VITE_API_TARGET=http://主机:端口 npm run dev` 指定。

生产构建：`cd frontend && npm run build`，产物在 `frontend/dist`；设置
`POOL_STATIC_DIR` 指向前端构建目录后，FastAPI 会在根路径直接托管该页面。

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_PORT` | `8000` | 容器内 uvicorn 监听端口；Compose 中同时用于宿主机映射 |
| `POOL_DB_PATH` | `backend/data/pooling.db`（本地）/ `/app/data/pooling.db`（容器） | SQLite 数据库文件路径 |
| `POOL_STATIC_DIR` | `backend/static`（本地）/ `/app/static`（容器） | 前端构建产物目录，存在时挂载到 `/` |
| `VITE_API_TARGET` | `http://localhost:8000` | 仅本地 `npm run dev` 时的后端代理目标 |

## 计算规则与约束

设样本浓度为 `C`（ng/µL）、目标投料量为 `T`（ng）、可用体积为 `V`（µL）：

- 取液量 `Q = T / C`（µL）。
- 单样本可行性：`Q ≥ 移液量下限`、`Q ≤ V`、`Q ≤ 单池体积上限`，否则不参与排池并给出原因。
- 池约束：`ΣQ（池内样本）≤ 单池体积上限`；池内各样本索引互不相同。
- 优化目标（字典序）：① 最大化安排样本数；② 在样本数相同的方案中最小化使用池数；
  ③ 同分时使用编号连续的池（确定性输出）。
- 池数上限为批次设置的「可用池数」。索引相同的样本数超过可用池数时，多余样本必然无法安排，
  系统会给出聚合警示。

## 主要 HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/batches` | 批次列表 |
| POST | `/api/batches` | 创建批次（参数须为正数） |
| GET | `/api/batches/{id}` | 批次详情：样本、各池配方、未安排、版本 |
| DELETE | `/api/batches/{id}` | 删除批次 |
| POST | `/api/batches/{id}/samples` | 批量新增样本（正数校验，重名 409） |
| DELETE | `/api/batches/{id}/samples/{sid}` | 删除样本（锁定池样本拒绝，409） |
| POST | `/api/batches/{id}/plan` | 生成 / 重算配液方案（仅未锁定池） |
| POST | `/api/batches/{id}/pools/{no}/lock` | 锁定池配方 |
| POST | `/api/batches/{id}/pools/{no}/unlock` | 解锁并重算 |
| POST | `/api/batches/{id}/samples/{sid}/remeasure` | 复测浓度（body: `{"concentration": 正数}`） |

非正数或格式不合法的输入返回 **422**，错误体定位到具体字段；业务冲突（重名、锁定池操作等）
返回 **409**；求解失败不会写入任何配方（返回 500 且保留上一版方案）。
