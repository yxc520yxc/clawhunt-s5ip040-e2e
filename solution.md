# 交付说明 | S5-IP-040 个人 IP 全链路端到端测试：上传到导出

技术栈：pytest + httpx + Playwright(Edge) + FastAPI + PostgreSQL 16 + Docker Compose + GitHub Actions。全部依赖为桩或本地服务，无外部账号、无真实个人信息、不引入向境外发送数据的 SDK。

## 一、交付内容

本单交付的是一套**可独立运行的端到端测试工程**，并自带一个最小可跑被测系统（FastAPI + 真实 PG）与全部桩服务，使每条验收都能真跑、可断言数据库状态：

- `tests/e2e/`：主链路 + 3 条异常链路 E2E（真实 HTTP + 真实 PG，逐步断言 DB 状态）
- `tests/playwright/`：3 个关键页面用例（真实 Edge 浏览器，附 HTML 报告）
- `web/`：新建项目 / 校对保存 / 敏感处置 3 个页面
- `stubs/`：模型网关桩（固定虚构响应）、复核队列桩、本地转写桩、本地 MinIO
- `app/`：最小被测系统，完整状态机 + 导出 md/docx/srt 实现
- `docker-compose.yml` / `Dockerfile`：PostgreSQL16 + Redis7 + 本地 MinIO + SUT 编排
- `.github/workflows/e2e.yml`：CI 并行分组（API job + Browser job），服务复用
- `run_all.py` / `verify.cmd`：一键复跑全部验收并生成 RUN_LOG

> `app/` 为**仅供本测试使用的最小被测实现，非生产系统**：业务表刻意用 `TEXT` 主键与简化字段，未按生产约定含 `org_id`/`site_id`/`created_by`/`updated_at`/`deleted_at` 与 UUID 原生类型；对接真实服务时替换 `app/` 与 `stubs/`，`tests/` 断言契约不变。详见 README。

## 二、四条验收标准（逐条真跑证据）

1. **主链路从上传到导出全通过，导出 3 种文件存在**：新建虚构项目 → 嘉宾授权 → 分片上传 → 流水线生成章节/节目介绍/金句/切片 → 敏感标记全部处置 → 复核桩回调 approved → 生成确认包并 confirmed → 导出。每步同时断言接口返回与 DB 状态（upload_chunk=3、artifact=4、pipeline_step 全 done、sensitive_flag=2、status 到 exported）。导出 `deliverable.md` / `captions.srt` / `deliverable.docx` 真实落盘且 size>0，docx 校验为有效 OOXML（PK 头）。→ `test_1_main_flow_upload_to_export` **PASS**。
2. **3 条异常链路状态码与项目状态断言**：① 授权缺失上传 → 409，项目仍 staging、无分片落库；② 转写失败重试 2 次 → status=failed、transcribe 步 attempts=2；③ 存在 pending 敏感标记 → 进入 ready 被 409 拦截，项目仍 reviewing、pending=1。→ `test_2/3/4_exc_*` **3 PASS**。
3. **Playwright 3 个页面用例通过，附运行报告**：真实无头浏览器（channel 由 `PW_CHANNEL` 决定，本机 msedge / CI 与 Docker 默认 bundled chromium，headless）打开真实页面操作——新建项目（断言返回 status=staging）、校对保存（编辑后断言页面 saved 且 DB 内容更新）、敏感处置（点处置后断言 pending 数下降且 DB resolved）。报告 `evidence/playwright-report.html`（打印实际 channel）。→ **3/3 PASS**。
4. **CI 整套 E2E ≤ 15 分钟，附运行记录**：本机一键真跑 **32.53s**（API 18.09s + 浏览器 14.44s），远低于 900s 上限。CI 配置分两个 job 并行、PG 用 service 复用，分别计时并上传 evidence artifact。→ **PASS**。
   - **运行记录性质（如实说明）**：上述耗时是本机 `verify.cmd` 在真实 PG + 真实浏览器上的可复现输出，**不是 GitHub Actions 实际 run 链接**；本单无仓库 / PR 授权，不代建仓库、不编造 run 链接。CI 配置已写齐，接入你的仓库推送后即产生真实 run 链接；若验收方硬性要求"CI 中实际 run 链接"，需接入仓库后补交。

完整真实输出见 `RUN_LOG.txt`：**4/4 checks passed，failed=[]**。E2E 连跑 3 次均 `4 passed`，无 flaky。

## 三、内嵌运行证据（无需打开外部链接即可复核）

验收 3 的 Playwright 报告（真实无头浏览器，逐条摘录 `evidence/playwright-report.html`）：

| 页面用例 | 结果 | 证据 | 时间 |
|---|---|---|---|
| 新建项目页 | PASS | status=staging, pid=25c7e135…, 0.97s | 07:06:00 |
| 校对保存页 | PASS | msg=已保存 saved, db_updated=True, 2.48s | 07:06:03 |
| 敏感处置页 | PASS | pending 2→1, db_resolved=1, 2.36s | 07:06:06 |

结论：**3/3 PASS**（浏览器 Playwright chromium / channel=msedge（本机，`PW_CHANNEL` 可配）/ headless；页面由真实 uvicorn 服务承载，数据落真实 PostgreSQL）。

验收 4 的耗时记录（`SUMMARY.txt` 原文摘录）：

```
=== SUMMARY ===
[PASS] 验收1 主链路上传→导出+3文件存在
[PASS] 验收2 3条异常链路状态码/状态断言
[PASS] 验收3 Playwright 3页面用例+报告
[PASS] 验收4 整套E2E耗时<=15分钟
TOTAL_SECONDS=32.53 (API=18.09s BROWSER=14.44s)  LIMIT=900s
RESULT: 4/4 checks passed; failed=[]
```

API E2E `4 passed`、Playwright E2E `4 passed` 的真实 pytest 输出均在 `RUN_LOG.txt`；Playwright HTML 报告原件在 `evidence/playwright-report.html`。

## 三、依赖、对接点与可重复性

- **无需外部账号**：全部桩化，不需要客户云、私有仓库或第三方账号。
- **对接点**：模型网关 `stubs::model_generate`（按 kind 返回固定文本）、复核队列 `stubs::review_callback`、对象存储 `stubs::store_chunk/export_dir`（Docker 下指向 MinIO）、转写 `stubs::transcribe`——真实接入时替换实现，接口契约不变，README 已写明。
- **可重复**：模型网关桩返回固定虚构响应，测试前 reset schema，随机 UUID 仅作主键不影响断言。
- **数据保密**：全部虚构数据，不含真实个人信息，交付物不出现客户名称。
