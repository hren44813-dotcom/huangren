# 架构概览

本文基于当前仓库的运行入口、核心模块和数据流整理。项目是本地运行的工业五金电商图片排版与商品资料管理工具；它不连接电商平台后台，也不会自动发布商品。

```mermaid
flowchart LR
    operator[运营人员]

    subgraph entry[运行入口]
        ui[Streamlit 界面<br/>app.py]
        cli[命令行工具<br/>scripts/]
        cfg[JSON 配置<br/>configs/]
    end

    subgraph app[本地应用层 · Python]
        direction[主图方向策划<br/>main_direction_ui.py]
        batchui[图片 / SKU 工作流界面<br/>sku_batch_ui.py]
        imageflow[离线批处理与输入校验<br/>workflow.py]
        sku[Excel SKU 解析与逐行制图<br/>sku_batch.py]
        render[Pillow 模板渲染<br/>generator.py<br/>sku_template_v3.py / sku_layout_v4.py]
        quality[尺寸、格式自动质检<br/>quality.py]
        dbui[数据库查询与商品档案界面<br/>db_reporting_ui_v11.py<br/>catalog_ui_v12.py]
        ai[可选星河 AI 桥接<br/>ai_bridge.py]
    end

    subgraph local[本机数据与文件]
        input[用户提供的产品图、Excel、配置]
        output[图片预览 / ZIP / 报告]
        sqlite[(SQLite 元数据<br/>.local/huangren.sqlite3<br/>任务、审核摘要、模板、商品档案、知识库)]
        sources[本机知识来源文件<br/>.local/knowledge_sources/]
        evidence[(V15 独立证据登记库<br/>按命令指定数据库路径)]
    end

    thirdparty[星河第三方 API<br/>需主动同意与 API Key]
    platform[淘宝 / 天猫 / 阿里国际站<br/>不自动连接或上架]

    operator --> ui
    operator --> cli
    cfg --> cli
    input --> ui
    input --> cli
    ui --> direction
    ui --> batchui
    ui --> dbui
    batchui --> imageflow
    batchui --> sku
    direction --> render
    imageflow --> render
    sku --> render
    render --> quality
    quality --> output
    cli --> render
    dbui <--> sqlite
    cli <--> sqlite
    cli --> sources
    cli --> evidence
    ui -. 显式同意后发送参考图与提示词 .-> ai
    ai <--> thirdparty
    output -. 人工检查后自行发布 .-> platform

    tests[unittest 测试集] -. 覆盖核心模块 .-> app
    ci[GitHub Actions<br/>语法检查 + 离线测试] -. 验证 .-> tests
```

## 主要数据流

- **标准制图（本地离线）**：界面或 `scripts/build_images.py` 读取用户图片与参数，`workflow.py` / `sku_batch.py` 校验输入并调用 `generator.py` 或 SKU 模板。`quality.py` 检查可自动验证的输出属性，结果以预览、ZIP 和报告提供；产品真实性、结构和平台合规仍由人员审核。
- **资料与商品管理（本机）**：`database_v9.py` 管理 SQLite 任务、审核摘要和布局模板；`catalog_v12.py` 扩展商品 / SKU 档案；V13 知识模块对本地资料建立可检索索引与证据定位。数据库不保存产品原图或 API 密钥。V15 `evidence_registry_v15.py` 的证据登记与正式 SKU 档案隔离。
- **可选 AI 制图（外部服务）**：只有用户在界面显式同意并提供密钥后，`ai_bridge.py` 才将所选参考图与提示词发送给星河服务。该路径不同于离线 Pillow 排版。
- **验证**：`tests/` 中的 unittest 覆盖图片生成、SKU、数据库、证据登记与相关安全约束；`.github/workflows/ci.yml` 在 Python 3.10 和 3.12 上执行语法检查及离线测试。

## 重要边界

- 传统排版只对原图等比例缩放和布局，不重绘产品结构；未知参数、认证或性能不得推断。
- 图像生成与资料库均为本机流程；向第三方发送图片仅限可选 AI 功能并需明确同意。
- 发布前须人工检查产品结构、尺寸、文字、合规和视觉质量。平台节点表示人工发布目标，不代表项目集成了平台 API。
