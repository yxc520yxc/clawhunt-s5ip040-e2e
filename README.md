# S5-IP-040 个人 IP 全链路端到端测试：上传到导出

本包是任务 #2380 的完整交付：**端到端测试代码 + Docker Compose 测试配置 + 桩服务与虚构夹具 + Playwright 脚本 + CI 配置 + README**。

## 一、这是什么

一套可独立运行的端到端测试工程，验证「个人 IP 助手」从新建项目、嘉宾授权、分片上传、流水线生成（章节 / 节目介绍 / 金句 / 切片）、敏感标记处置、复核回调、嘉宾确认包到导出 md/docx/srt 的完整链路。

本单依赖为「无」。为使测试真跑、可断言数据库状态，包内自带一个**最小可跑被测系统**（`app/`，FastAPI + 真实 PostgreSQL）与全部桩服务（`stubs/`）：模型网关桩返回固定虚构响应、复核队列桩回调 approved、本地转写桩、本地 MinIO 用文件目录模拟。被测系统可用接口桩 / mock 先行——这正是任务约定允许的做法。

> **SUT 定位声明**：`app/` 是**仅供本测试使用的最小被测实现，不是生产系统**。它只实现状态机主干与验收所需接口，业务表刻意采用 `TEXT` 主键与简化字段，**未按生产约定包含 `org_id` / `site_id` / `created_by` / `updated_at` / `deleted_at` 及 UUID 原生类型**。如需对接真实生产服务，替换 `app/` 与 `stubs/` 即可，`tests/` 的断言契约不变。虚构夹具中的 actor/org/site 标识均为假值，不接任何真实 IAM。

## 二、验收标准对照与证据

| # | 验收标准 | 测试 | 证据 |
|---|---------|------|------|
| 1 | 主链路从上传到导出全部通过，导出的 3 种文件存在 | `tests/e2e/test_pipeline.py::test_1_main_flow_upload_to_export` | 逐步断言 DB 状态；导出 md/docx/srt 真实落盘，docx 校验为有效 OOXML（PK 头） |
| 2 | 3 条异常链路期望状态码与项目状态断言全部通过 | `test_2/3/4_exc_*` | 授权缺失 409；转写失败重试 2 次后 failed；pending 敏感标记阻断 ready 409 |
| 3 | Playwright 3 个页面用例通过，附运行报告 | `tests/playwright/test_pages.py` | 真实无头浏览器操作新建/校对保存/敏感处置 3 页（channel 可配，默认 chromium / 本机 Edge）；报告 `evidence/playwright-report.html` |
| 4 | CI 整套 E2E 耗时 ≤ 15 分钟（附运行记录） | `.github/workflows/e2e.yml` + `RUN_LOG.txt` | 本机真跑 32.53s（API 18.09s + 浏览器 14.44s），远低于 900s；CI 分两个 job 并行 + PG service 复用（运行记录性质见"方式 C"说明） |

完整真实输出见 `RUN_LOG.txt`（4/4 checks passed，失败列表为空）。

## 三、目录结构

```
app/            最小被测系统（FastAPI），含完整状态机与所有 API、导出实现
stubs/          桩服务：模型网关 / 复核队列 / 本地转写 / 本地 MinIO
fixtures/       虚构夹具（全部假数据，无真实个人信息）
tests/e2e/      验收1、2：主链路 + 3 异常链路（真实 HTTP + 真实 PG）
tests/playwright/ 验收3：3 个页面用例（真实 Edge + HTML 报告）
web/            3 个页面：new.html / proofread.html / sensitive.html
.github/workflows/e2e.yml  验收4：CI 并行分组（API job + Browser job）
docker-compose.yml / Dockerfile  依赖栈编排与镜像
run_all.py / verify.cmd  一键复跑全部验收并生成 RUN_LOG
evidence/       运行证据（HTML 报告、时间戳日志）
```

## 四、运行与测试方法

### 方式 A：本机一键复跑（无需 Docker）

前置：Python 3.11+、PostgreSQL 16（可连）、Edge 浏览器、安装依赖。

```bat
pip install -r requirements.txt
set PY=python
verify.cmd
```

脚本会：确保库 `e2e2380` 存在 → 跑 `tests/e2e/`（4 条）→ 跑 `tests/playwright/`（4 条，无头浏览器）→ 写 `RUN_LOG.txt` 与 `SUMMARY.txt`。
DSN 可用环境变量 `E2E_PG_DSN` / `E2E_PG_ADMIN_DSN` 覆盖，默认 `postgresql://postgres@127.0.0.1:55439/e2e2380`。

**浏览器 channel**：`verify.cmd`（本机入口）默认设 `PW_CHANNEL=msedge` 使用本机 Edge。`tests/playwright/test_pages.py` 从环境变量 `PW_CHANNEL` 读取 channel，未设时用 Playwright 自带 `chromium`。CI 与 Docker 刻意**不设**该变量，走 `playwright install chromium` 装的 bundled 内核，因此不依赖 runner / 镜像内预装 Edge——self-hosted、无 Edge 环境同样可跑。HTML 报告会打印本次实际使用的 channel。若要在 Docker 内改用 Edge，可 `docker compose run -e PW_CHANNEL=msedge sut ...` 并预装 Edge。

### 方式 B：Docker Compose（完整依赖栈）

```bash
docker compose up -d --build      # PG16 + Redis7 + MinIO + SUT
docker compose run --rm sut pytest -q tests/e2e/
docker compose run --rm -e E2E_PG_DSN=postgresql://postgres:postgres@db:5432/e2e2380 \
  -e E2E_PG_ADMIN_DSN=postgresql://postgres:postgres@db:5432/postgres \
  sut pytest -q tests/playwright/   # 用镜像内 bundled chromium（Dockerfile 已 playwright install chromium）
docker compose down
```

`docker-compose.yml` 声明了验收要求的所有组件：PostgreSQL、Redis、本地 MinIO、以及承载模型网关桩 / 复核队列桩 / 本地转写桩的 SUT。CI 中这些服务用 GitHub Actions `services:` 复用（见 `e2e.yml`），避免每次重建，保证 15 分钟内完成。

### 方式 C：CI

推送即触发 `.github/workflows/e2e.yml`：两个 job 并行（`e2e-api` / `e2e-browser`），各自用 PG service，分别计时并上传 evidence artifact。

**关于验收 4 的"运行记录"性质（如实说明）**：本包 `RUN_LOG.txt` / `SUMMARY.txt` 中的耗时（如 `TOTAL_SECONDS=…`）是**本机一键复跑 `verify.cmd` 的真实输出**，在真实 PostgreSQL + 真实无头浏览器上测得，非伪造。它是"可在你本地复现"的运行记录，但**不是某个 GitHub Actions workflow run 的实际链接**——本单无代码仓库 / PR 授权，无法代建仓库并产生真实 CI run 链接。CI 配置（`.github/workflows/e2e.yml`）已按验收要求写齐并声明了计时与 artifact 上传；接入你自己的仓库后推送即会产生真实 run 链接（Actions 页面可见）。若验收方明确要求"CI 中实际运行的 run 链接"，需在接入仓库后补交，本包不编造该链接。

## 五、依赖与访问 / 对接点说明

- **外部账号**：无。全部桩化，不需要客户云、GitHub 私有仓库或第三方账号。
- **模型网关对接点**：`stubs/services.py::model_generate` 返回固定虚构内容。真实接入时替换为模型网关调用，接口契约（按 kind 返回文本）不变。
- **复核队列对接点**：`stubs/services.py::review_callback`。真实接入时改为监听复核回调事件。
- **对象存储对接点**：`stubs/services.py::store_chunk` / `export_dir`。Docker Compose 下指向 MinIO（`MINIO_ENDPOINT`）；本机用本地目录模拟。
- **转写服务对接点**：`stubs/services.py::transcribe`。真实接入时替换为本地转写服务或其桩。
- **S2-IAM 依赖**：本测试只填虚构的 actor / org / site 标识，不涉及真实 IAM。
- **数据保密**：所有数据均为虚构，交付物不出现客户名称，不引入任何向境外发送数据的第三方 SDK。
- **可重复性**：模型网关桩返回固定响应，测试前 reset schema，随机 UUID 只作主键不影响断言，无 flaky（连跑稳定通过）。
