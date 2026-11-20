# S5-IP-040 个人 IP 全链路端到端测试：上传到导出

**公开仓库**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e （无需登录即可 clone）
**CI 实跑（run #3，success）**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e/actions/runs/44737304568

本包是任务 #2380 的完整交付：**端到端测试代码 + Docker Compose 测试配置 + 桩服务与虚构夹具 + Playwright 脚本 + CI 配置 + README**。全部代码已推送到上述公开仓库，并在 GitHub Actions 上实际跑通（非本机模拟），run 链接与逐用例日志、导出物、Playwright 报告均作为 CI artifact 留存。

## 一、这是什么

一套可独立运行的端到端测试工程，验证「个人 IP 助手」从新建项目、嘉宾授权、分片上传、流水线生成（章节 / 节目介绍 / 金句 / 切片）、敏感标记处置、复核回调、嘉宾确认包到导出 md/docx/srt 的完整链路。

本单依赖为「无」。为使测试真跑、可断言数据库状态，包内自带一个**最小可跑被测系统**（`app/`，FastAPI + 真实 PostgreSQL）与全部桩服务（`stubs/`）：模型网关桩返回固定虚构响应、复核队列桩回调 approved、本地转写桩。对象存储与复核队列采用**双模式**：CI/Docker Compose 设了 `MINIO_ENDPOINT` / `REDIS_URL` 时走**真实 MinIO 对象存储 + 真实 Redis**；本机未设时用文件目录 + fakeredis 桩。被测系统可用接口桩 / mock 先行——这正是任务约定允许的做法。

> **SUT 定位声明**：`app/` 是**仅供本测试使用的最小被测实现，不是生产系统**。它只实现状态机主干与验收所需接口，业务表刻意采用 `TEXT` 主键与简化字段，**未按生产约定包含 `org_id` / `site_id` / `created_by` / `updated_at` / `deleted_at` 及 UUID 原生类型**。如需对接真实生产服务，替换 `app/` 与 `stubs/` 即可，`tests/` 的断言契约不变。虚构夹具中的 actor/org/site 标识均为假值，不接任何真实 IAM。

## 二、验收标准对照与证据

| # | 验收标准 | 测试 | CI 实跑证据（run #3） |
|---|---------|------|------|
| 1 | 主链路从上传到导出全部通过，导出的 3 种文件存在 | `tests/e2e/test_pipeline.py::test_1_main_flow_upload_to_export` | CI 逐用例日志 `test_1 ... -> PASS`，`[EXPORT-ARTIFACT] ['deliverable.docx','deliverable.md','deliverable.srt'] storage=minio`；三文件已上传为 artifact（md 357B / srt 116B / docx 36,843B，docx 有效 OOXML） |
| 2 | 3 条异常链路期望状态码与项目状态断言全部通过 | `test_2/3/4_exc_*` | CI 逐用例日志 3 条均 `-> PASS`：授权缺失 409；转写失败重试 2 次后 failed；pending 敏感标记阻断 ready 409 |
| 3 | Playwright 3 个页面用例通过，附运行报告 | `tests/playwright/test_pages.py` | CI 逐用例日志恰好 3 条 `-> PASS`（new_project / proofread_save / sensitive_resolve）；`playwright-report.html`（bundled chromium，3/3 PASS）已上传 artifact，可直接打开 |
| 4 | CI 整套 E2E 耗时 ≤ 15 分钟（附运行记录） | `.github/workflows/e2e.yml` | 真实 run：API job **29s**（其中 API_E2E_SECONDS=2）、Browser job **71s**（其中 BROWSER_E2E_SECONDS=6），远低于 900s；两 job 并行、各自计时并上传 evidence artifact |

**CI run 链接**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e/actions/runs/44737304568 （conclusion=success）
**真实后端证明**：CI 日志出现 `storage=minio`，证明分片/导出真写入 MinIO 对象存储；Redis 复核队列通过 `REDIS_URL` 走真服务（`review_callback` 真写 Redis）；PostgreSQL 为 compose 起的真实 16 实例。本机一键复跑（`RUN_LOG.txt`）另附，作为本地可复现的运行记录。

## 三、目录结构

```
app/            最小被测系统（FastAPI），含完整状态机与所有 API、导出实现
stubs/          桩服务：模型网关 / 复核队列 / 本地转写 / 本地 MinIO
fixtures/       虚构夹具（全部假数据，无真实个人信息）
tests/e2e/      验收1、2：主链路 + 3 异常链路（真实 HTTP + 真实 PG）
tests/playwright/ 验收3：3 个页面用例（bundled chromium / 本机可切 Edge + HTML 报告）
web/            3 个页面：new.html / proofread.html / sensitive.html
.github/workflows/e2e.yml  验收4：CI 并行分组（API job + Browser job，真 compose 栈）
docker-compose.yml / Dockerfile  PG16 + Redis7 + MinIO + minio-init + SUT
evidence/       运行证据（HTML 报告、导出物 md/docx/srt、时间戳日志）
```

## 四、运行与测试方法

### 方式 A：本机一键复跑（无需 Docker）

前置：Python 3.11+、PostgreSQL 16（可连）、Edge 浏览器、安装依赖。

```bat
pip install -r requirements.txt
set PY=python
verify.cmd
```

脚本会：确保库 `e2e2380` 存在 → 跑 `tests/e2e/`（4 条）→ 跑 `tests/playwright/`（3 条，无头浏览器）→ 写 `RUN_LOG.txt` 与 `SUMMARY.txt`。
DSN 可用环境变量 `E2E_PG_DSN` / `E2E_PG_ADMIN_DSN` 覆盖，默认 `postgresql://postgres@127.0.0.1:55439/e2e2380`。本机模式未设 `MINIO_ENDPOINT` / `REDIS_URL`，故走文件目录 + fakeredis 桩；CI/Compose 模式走真 MinIO + 真 Redis。

**浏览器 channel**：`verify.cmd`（本机入口）默认设 `PW_CHANNEL=msedge` 使用本机 Edge。`tests/playwright/test_pages.py` 从环境变量 `PW_CHANNEL` 读取 channel，未设时用 Playwright 自带 `chromium`。CI 与 Docker 刻意**不设**该变量，走 `playwright install chromium` 装的 bundled 内核，因此不依赖 runner / 镜像内预装 Edge——self-hosted、无 Edge 环境同样可跑。HTML 报告会打印本次实际使用的 channel。若要在 Docker 内改用 Edge，可 `docker compose run -e PW_CHANNEL=msedge sut ...` 并预装 Edge。

### 方式 B：Docker Compose（完整依赖栈，真 MinIO + 真 Redis）

```bash
docker compose up -d postgres redis minio minio-init   # PG16 + Redis7 + MinIO + 建桶
# 注意：MinIO 社区版镜像已 from Docker Hub / quay.io 下架，本包用公开 GHCR
# 社区重建镜像 ghcr.io/intikhab49/minio-from-source（内置 mc，免登录可拉）
export E2E_PG_DSN=postgresql://postgres:postgres@127.0.0.1:5432/e2e2380
export E2E_PG_ADMIN_DSN=postgresql://postgres:postgres@127.0.0.1:5432/postgres
export REDIS_URL=redis://127.0.0.1:6379/0
export MINIO_ENDPOINT=http://127.0.0.1:9000 MINIO_ACCESS_KEY=e2euser \
       MINIO_SECRET_KEY=e2epassword123 MINIO_BUCKET=e2e-2380
pytest -v -s tests/e2e/         # 分片真写 MinIO、复核队列真写 Redis
pytest -v -s tests/playwright/  # bundled chromium（Dockerfile 已 playwright install chromium）
docker compose down
```

`docker-compose.yml` 声明了验收要求的所有组件：PostgreSQL、Redis、MinIO（含 minio-init 建桶）、以及承载模型网关桩 / 复核队列桩 / 本地转写桩的 SUT。CI 用同样的 compose 命令起栈（见 `e2e.yml`），两个 job 各自起一套，保证隔离与 15 分钟内完成。

### 方式 C：GitHub Actions CI（已实跑，run #3 success）

公开仓库 https://github.com/yxc520yxc/clawhunt-s5ip040-e2e 推送即触发 `.github/workflows/e2e.yml`：两个 job 并行（`e2e-api` / `e2e-browser`），各自 `docker compose up` 起真 PG16 + Redis7 + MinIO 全栈，设 `REDIS_URL` / `MINIO_ENDPOINT` 走真后端，pytest `-v -s` 逐用例名输出，分别计时并上传 evidence artifact（含逐用例日志、导出物 md/docx/srt、Playwright 报告）。

**真实 run 链接**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e/actions/runs/44737304568 （run #3，conclusion=success，2026-11-20）

| Job | 结论 | Job 总耗时 | 其中测试计时 |
|-----|------|-----------|-------------|
| 主链路 + 异常链路 (API) | success | 29s | API_E2E_SECONDS=2 |
| Playwright 3 页面用例 (Browser) | success | 71s | BROWSER_E2E_SECONDS=6 |

两个 job 远低于 900s（15 分钟）上限。artifact：`e2e-api-evidence`（逐用例日志 + 导出物 + `timings.txt`）、`e2e-browser-evidence`（逐用例日志 + Playwright 报告 + `timings-browser.txt`），在 run 页面可直接下载。此前 run #1/#2 因 MinIO 镜像从 Docker Hub/quay.io 下架而起栈失败，run #3 改用 GHCR 社区镜像后全绿——这是 2026 年上游变更，非本测试代码问题。

## 五、依赖与访问 / 对接点说明

- **外部账号**：无。全部桩化，不需要客户云、GitHub 私有仓库或第三方账号。
- **模型网关对接点**：`stubs/services.py::model_generate` 返回固定虚构内容。真实接入时替换为模型网关调用，接口契约（按 kind 返回文本）不变。
- **复核队列对接点**：`stubs/services.py::review_callback`。真实接入时改为监听复核回调事件。
- **对象存储对接点**：`stubs/services.py::store_chunk` / `put_export` / `export_exists` / `export_bytes`。设 `MINIO_ENDPOINT` 走真实 MinIO（CI 已实跑，run #3 日志 `storage=minio` 证明分片与导出真写入对象存储）；本机未设时用文件目录桩。真实接入生产 S3/MinIO 时接口契约不变。
- **转写服务对接点**：`stubs/services.py::transcribe`。真实接入时替换为本地转写服务或其桩。
- **S2-IAM 依赖**：本测试只填虚构的 actor / org / site 标识，不涉及真实 IAM。
- **数据保密**：所有数据均为虚构，交付物不出现客户名称，不引入任何向境外发送数据的第三方 SDK。
- **可重复性**：模型网关桩返回固定响应，测试前 reset schema，随机 UUID 只作主键不影响断言，无 flaky（连跑稳定通过）。
