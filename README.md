# 测序样本拼池 Web 工作台

实验员录入测序样本与拼池约束，系统自动给出**最优配液方案**：按
`取液量 = 目标投料量 ÷ 浓度` 计算每个样本的取液体积，在「同池索引序列不得重复」
「单池总体积不得超过上限」「取液量不得低于移液量下限 / 超过可用体积」「可用池数
有限」等约束下，以 **安排样本数最多、其次使用池数最少** 为目标精确求解，并输出
各池配液表与每个未安排样本的具体原因。复测浓度后可只重算未锁定池，锁定池保留
原配方、仅显示受影响警示并留下版本记录。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2 · OR-Tools CP-SAT（精确最优） |
| 前端 | React 18 · Vite |
| 数据库 | SQLite（挂载在 Docker 卷中持久化） |

所有体积/浓度计算在服务端使用 `Decimal` 定点完成，不使用浮点数。

## 目录结构

```
.
├── backend/            FastAPI 后端
│   ├── app/
│   │   ├── main.py         入口（API + 前端静态托管 + 启动建表）
│   │   ├── solver.py       CP-SAT 拼池求解器（样本数优先、池数最少）
│   │   ├── services.py     重算 / 锁定 / 复测 / 版本快照业务逻辑
│   │   ├── models.py       SQLAlchemy 模型
│   │   ├── schemas.py      输入输出模型（非正数拒绝等校验）
│   │   ├── calc.py         Decimal 定点计算
│   │   └── init_db.py      数据库初始化
│   ├── tests/          pytest 测试
│   └── requirements.txt
├── frontend/           React + Vite 前端
├── docker/entrypoint.sh  容器入口（先建表再启动）
├── Dockerfile          多阶段构建（前端构建 → 后端运行镜像）
└── docker-compose.yml  一键启动
```

## 一键启动（推荐）

需要已安装 Docker 与 Docker Compose 插件（`docker compose version` 可用）。

```bash
docker compose up --build -d
```

启动后打开浏览器访问：

- **工作台页面：<http://localhost:8000>**
- 健康检查：<http://localhost:8000/api/health>
- OpenAPI 文档：<http://localhost:8000/docs>

端口可通过环境变量修改，例如使用 9000 端口：

```bash
WEB_PORT=9000 docker compose up --build -d   # 然后访问 http://localhost:9000
```

停止与数据：

```bash
docker compose down          # 停止，数据保留在卷 pooling-data 中
docker compose down -v       # 停止并删除数据库卷（清空全部数据）
```

## 配置

均通过环境变量配置（见 `docker-compose.yml`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_PORT` | `8000` | 宿主机映射端口（容器内固定监听 8000） |
| `DB_PATH` | `/data/pooling.db` | SQLite 文件路径 |
| `SQLALCHEMY_URL` | `sqlite:///$DB_PATH` | 完整数据库连接串，设置后覆盖 `DB_PATH` |
| `SOLVER_TIME_LIMIT` | `30` | CP-SAT 单次最长求解秒数 |

数据库表会在容器启动时自动创建（幂等，可重复执行）。

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SQLALCHEMY_URL="sqlite:///./pooling.db"
python -m app.init_db                 # 初始化数据库（建表）
uvicorn app.main:app --reload --port 8000
```

### 前端（开发服务器，带 /api 代理）

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 ，/api 代理到 http://localhost:8000
```

如需把代理指向其它后端地址：

```bash
VITE_API_TARGET=http://其它主机:8000 npm run dev
```

### 运行测试

```bash
cd backend
pip install pytest httpx
pytest -q
```

## 使用流程

1. **新建计划**：填写可用池数、单池体积上限、移液量下限，逐条录入样本的
   浓度、可用体积、目标投料量与索引序列（碱基 A/C/G/T/N；双索引可用 `-`
   或空格分隔）。所有非正数与空索引都会被拒绝。
2. 提交后系统给出 **v1 方案**：
   - 「各池配液表」：池号、锁定状态、总体积/上限、每个样本的取液量；
   - 「未安排样本」：列出每个未入池样本及其具体原因（低于移液量下限、
     超过可用体积/单池上限、池位或索引冲突导致无可行分配等）。
     **不满足约束时绝不会生成虚假配方。**
3. **锁定池**：对已确认的池点击「锁定配方」。
4. **复测浓度**：在右侧录入一个或多个样本的复测浓度（可选同时更新可用体积）
   并提交：
   - **未锁定池**：按新数据重新求最优方案，生成新版本；
   - **锁定池**：配方原样保留；若复测影响到该池（取液量应变化、原取液量
     超过新可用体积、合计超限等），池卡片显示警示；
   - 每次计算都在「版本记录」中保存不可变快照，可逐版本查看当时配液表。
5. **追加样本**：在锁定池保留的前提下对未锁定池重算。
6. 解锁池后，下一次重算会把该池重新纳入优化。

## 优化模型说明

对每个「个体可行」的样本，取液量固定为 `投料量 ÷ 浓度`（4 位小数），建立
0-1 规划：

- 每个样本至多放入一个池；
- 每池取液量合计 ≤ 单池体积上限；
- 同索引的任意两个样本不得共池；
- 目标为字典序：`最大化安排样本数` ≫ `最小化使用池数`
  （样本数的目标权重大于池数可能带来的任何收益）。

由 OR-Tools CP-SAT 求**可证明的最优解**；若在时限内无法证明最优，系统会
中止并报错，而不是返回不可靠配方。
