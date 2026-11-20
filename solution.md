# 交付说明 | S5-IP-040 个人 IP 全链路端到端测试：上传到导出

技术栈：pytest + httpx + Playwright + FastAPI + PostgreSQL 16 + Redis 7 + MinIO + Docker Compose + GitHub Actions。桩服务 + 虚构夹具，无真实个人信息、不引入向境外发送数据的 SDK。

**公开仓库（无需登录可克隆）**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e
**CI 实跑 run（conclusion=success）**：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e/actions/runs/44737304568

## 一、交付内容（对应返工 blocker-1：公开可克隆仓库）

全部代码已推送到上述公开 GitHub 仓库（main 分支，无需登录即可 `git clone`），含 README（运行与测试方法）、CI 配置、测试结果与 artifact。仓库内文件：

- `tests/e2e/`：主链路 + 3 条异常链路 E2E（真实 HTTP + 真实 PG + 真 MinIO + 真 Redis，逐步断言 DB 状态）
- `tests/playwright/`：3 个关键页面用例（bundled chromium，附 HTML 报告）
- `web/`：新建项目 / 校对保存 / 敏感处置 3 个页面
- `stubs/`：模型网关桩、复核队列桩（真写 Redis）、转写桩、对象存储（真写 MinIO / 本地桩双模式）
- `app/`：最小被测系统，完整状态机 + 导出 md/docx/srt 实现
- `docker-compose.yml` / `Dockerfile`：PG16 + Redis7 + MinIO + minio-init 建桶 + SUT 编排
- `.github/workflows/e2e.yml`：CI 两 job 并行，各自 `docker compose up` 起真栈、pytest `-v -s` 逐用例名输出、计时并上传 artifact
- `run_all.py` / `verify.cmd`：本机一键复跑（桩模式）并生成 RUN_LOG

> `app/` 为**仅供本测试使用的最小被测实现，非生产系统**：业务表刻意用 `TEXT` 主键与简化字段，未按生产约定含 `org_id`/`site_id`/`created_by`/`updated_at`/`deleted_at` 与 UUID 原生类型；对接真实服务时替换 `app/` 与 `stubs/`，`tests/` 断言契约不变。详见 README。

## 二、四条验收标准（CI run #3 逐条真跑证据）

CI run：https://github.com/yxc520yxc/clawhunt-s5ip040-e2e/actions/runs/44737304568 （run #3，success，2026-11-20T12:37Z）

1. **主链路从上传到导出全通过，导出 3 种文件存在**：CI 逐用例日志 `test_1_main_flow_upload_to_export -> PASS`。逐步断言接口与 DB 状态（upload_chunk=3、artifact=4、pipeline_step 全 done、sensitive_flag=2、status=exported）。日志含 `[EXPORT-ARTIFACT] ['deliverable.docx','deliverable.md','deliverable.srt'] storage=minio`，三文件已作为 artifact 上传（md 352B / srt 109B / docx 36,843B，docx 有效 OOXML）。→ **PASS**。
2. **3 条异常链路状态码与项目状态断言**：CI 逐用例日志三条均 `-> PASS`：`test_2_exc_missing_authorization_409`（授权缺失 409，项目仍 staging）、`test_3_exc_transcribe_fail_retry_then_failed`（转写失败重试 2 次→failed）、`test_4_exc_pending_sensitive_blocks_ready_409`（pending 敏感标记→ready 409）。→ **PASS**。
3. **Playwright 3 个页面用例通过，附运行报告**：CI 逐用例日志**恰好 3 条** `-> PASS`（`test_pw_1_new_project` / `test_pw_2_proofread_save` / `test_pw_3_sensitive_resolve`），`3 passed in 5.07s`。报告 `playwright-report.html`（bundled chromium，3/3 PASS）已作为 artifact 上传，可直接打开。第 4 条"报告生成"已改为 session teardown，不再计入用例数——因此用例数与报告一致。→ **PASS**。
4. **CI 整套 E2E 耗时 ≤ 15 分钟（附运行记录）**：真实 run 中 API job **29s**（其中 `API_E2E_SECONDS=2`）、Browser job **71s**（其中 `BROWSER_E2E_SECONDS=6`），远低于 900s。两 job 并行、各自计时并上传 evidence artifact。→ **PASS**。

**真实后端证明（对应返工 major-3）**：CI 日志出现 `storage=minio`，证明分片与导出真写入 MinIO 对象存储；复核队列通过 `REDIS_URL` 真写 Redis；PostgreSQL 为 compose 起的真实 16 实例。`docker-compose.yml` 声明 PgSQL/Redis/MinIO/minio-init 全栈。本机一键复跑（`RUN_LOG.txt`）另附，作为本地可复现记录。

> 关于耗时链接的如实说明：验收 4 的 run 链接是**真实 GitHub Actions run #3**（非本机），本机 `RUN_LOG.txt` 仅为补充。CI 耗时数字取自 run 的 jobs API（job 总耗时）与 artifact 内 `timings*.txt`（纯测试计时），两者都列出。

## 三、内嵌运行证据（无需打开外部链接即可复核）

CI run #3 的 API 逐用例日志（`evidence/ci-run3/api__e2e-api.log` 原文摘录）：

```
tests/e2e/test_pipeline.py::test_1_main_flow_upload_to_export
[EXPORT-ARTIFACT] ['deliverable.docx', 'deliverable.md', 'deliverable.srt'] storage=minio
[CASE] ...::test_1_main_flow_upload_to_export -> PASS
[CASE] ...::test_2_exc_missing_authorization_409 -> PASS
[CASE] ...::test_3_exc_transcribe_fail_retry_then_failed -> PASS
[CASE] ...::test_4_exc_pending_sensitive_blocks_ready_409 -> PASS
============================== 4 passed in 1.41s ===============================
```

CI run #3 的 Playwright 逐用例日志（`evidence/ci-run3/browser__e2e-browser.log`）：

```
[CASE] tests/playwright/test_pages.py::test_pw_1_new_project -> PASS
[CASE] tests/playwright/test_pages.py::test_pw_2_proofread_save -> PASS
[CASE] tests/playwright/test_pages.py::test_pw_3_sensitive_resolve -> PASS
============================== 3 passed in 5.07s ===============================
```

CI 计时（`timings.txt` / `timings-browser.txt` 原文）：

```
API_E2E_SECONDS=2      API_E2E_EXIT=0
BROWSER_E2E_SECONDS=6  BROWSER_E2E_EXIT=0
```

Playwright 报告（`evidence/ci-run3/playwright-report.html`）：浏览器 Playwright bundled chromium / headless，页面由真实 uvicorn 服务承载、数据落真实 PostgreSQL，结论 **3/3 PASS**。导出物原件在 `evidence/ci-run3/api__exports/`，run 元数据在 `evidence/ci-run3/RUN_META.json`。

## 四、依赖、对接点与可重复性

- **无需外部账号**：全部桩化 + 公开仓库，不需要客户云或私有仓库。
- **对接点**：模型网关 `stubs::model_generate`、复核队列 `stubs::review_callback`（真写 Redis）、对象存储 `stubs::store_chunk/put_export/export_exists`（CI 真写 MinIO）、转写 `stubs::transcribe`——真实接入时替换实现，接口契约不变，README 已写明。
- **MinIO 镜像来源**：社区版已从 Docker Hub / quay.io 下架（2026 上游变更），本包用公开 GHCR 社区重建镜像 `ghcr.io/intikhab49/minio-from-source:RELEASE.2025-10-15T17-29-55Z`（内置 mc，免登录可拉）。CI run #1/#2 因旧镜像下架起栈失败，run #3 改用后全绿。
- **可重复**：桩返回固定虚构响应，测试前 reset schema，随机 UUID 仅作主键不影响断言，无 flaky。
- **数据保密**：全部虚构数据，不含真实个人信息，交付物不出现客户名称。
