# huangren · 工业五金电商图批量制作工具

可运行的 **Python + Pillow** 图片自动排版脚本，适用于淘宝、天猫等电商平台的工业拉手、锁具、铰链、阻尼转轴等产品。支持单个配置制作多种图片，也支持按文件夹批量生成 SKU 图。

**核心原则：不编造产品结构、尺寸和卖点。** 所有产品图只做裁掉透明外边距、等比例缩放、居中叠合；不会用 AI 重画锁片、孔位、钥匙或改动原有尺寸标注。原始文件不覆盖。图片压缩可能产生轻微视觉差异，正式上架前必须人工核对。

## 生成模式

| 模式 | 尺寸 | 场景与约束 |
| --- | --- | --- |
| `search_white` | 1440×1440 | RGB 白底 JPG，小于 3MB；不添加文字、边框、阴影、Logo |
| `main` | 1440×1440 | 工业浅灰主图；产品与左侧文案分离；无四周边框 |
| `portrait` | 1440×1920 | 3:4 竖图；简洁背景，角落可选简短型号文字 |
| `sku` | 1440×1440 | 彩色标题+原产品/原尺寸图+用户填写的参数区 |
| `detail` | 800×1600 | 800px 宽单页详情模块；可增加多项真实卖点 |


## 🖥 中文可视化界面（运营助理优先使用）

除命令行外，本仓库已新增基于 Streamlit 的中文操作面板，无需改 JSON 就能上传多张实物图、选择淘宝/天猫或阿里国际站、选择主图/白底图/SKU/竖图/详情模块、填写真实文案、自动批量排版并下载 ZIP 和校验报告。

```bash
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
```

浏览器按终端提示访问本地界面（通常为 `http://localhost:8501`）。

面板第二页接入已安装的**星河跨境电商详情技能**，可在显式同意后调用第三方 AI 服务。需要自行提供有效 API Key，可能收费；真实图片与提示词会发送给第三方，不保证 AI 输出机械结构绝对一致。

详细操作说明见 [docs/web-ui.md](docs/web-ui.md)。

## 立即运行

先安装 Python 3.10+，然后在项目根目录：

```bash
python -m pip install -r requirements.txt
python scripts/create_demo_asset.py
python scripts/build_images.py --config configs/example.json --report output/report.json
```

生成图在 `output/`。**DEMO_only.png 是程序绘制的教学占位图，不是真实商品；严禁直接用于上架。**

### 替换为真实商品图

1. 将已抠图的透明 PNG（最好清晰的原始产品照片）放入 `assets/input/`。
2. 打开 `configs/example.json`，把 `source` 换为真实文件，例如 `assets/input/MS705.png`；将 `output`、`title`、`selling_points`、`specs` 改为真实信息。
3. 执行 `python scripts/build_images.py --config configs/example.json`。
4. 批量 SKU：执行 `python scripts/build_images.py --config configs/batch_sku.json`，它会读取 `assets/input/*.png` 并输出到 `output/sku/`。

如果标题是黄色色块，设置 `accent: "#F5C518"`、`title_color: "#000000"`。蓝色模板可用 `#0D7FF4`。品牌 Logo 仅在 `main`/`detail` 设置 `logo` 路径后显示；白底搜推图始终不加 Logo。

## 仓库结构

```text
huangren/
├── README.md
├── app.py                # 中文 Streamlit 界面
├── requirements-ui.txt   # 界面额外依赖
├── requirements.txt
├── .gitignore
├── configs/
│   ├── example.json
│   └── batch_sku.json
├── src/ecom_images/
│   ├── __init__.py
│   └── generator.py
├── scripts/
│   ├── build_images.py
│   └── create_demo_asset.py
├── tests/test_generator.py
├── docs/usage.md
└── assets/input/          # 放真实商品 PNG（不自动传到任何平台）
```

## 质量与合规说明

- **不失真**：等比例缩放，完整保留原产品及其已有标注；不做产品结构编辑。
- **纯白搜推图**：建议使用干净透明 PNG；若是非白底环境照片，脚本会拒绝直接生成，避免误认为已成功抠图。带内置阴影的原图需人工清理。
- **文案来源**：仅输出你在 JSON 中填写的内容。开孔尺寸、材质、盐雾/扭矩/寿命等不能凭模板推断。
- **格式检查**：输出后检查实际像素；搜推 JPG 额外验证白角和小于 3MB。JPEG 压缩画面内部可能有细微像素差异。
- **发布前**：仍需人工检查主体、细节、文字排版、画质和平台最新审核要求。

## 测试

```bash
python -m unittest discover -s tests -v
```

更多参数和注意事项见 [docs/usage.md](docs/usage.md)。


## 跨境电商详情 AI 技能（星河 4.0）

已安装用户上传的 **星河跨境电商详情4.0** 技能到 Codex 仓库级技能目录：`.agents/skills/xinghe-crossborder-detail-3/SKILL.md`。内含 20 篇参考规范、脚本、可选第三方 API 示例配置与使用说明。该 Skill 专注于跨境详情模块独立 AI 生图；上面介绍的本地 Pillow 排版工具继续负责淘宝/天猫主图、SKU 和白底素材。这是两种不同工作流程。

技能指令可以在仓库中被兼容的 Codex 智能体发现，但**不会仅因提交 GitHub 就自动连接 ChatGPT 或启动生成**。要实际通过星河接口生图，需要自行配置第三方 API 密钥；不得把 `.env` 或客户敏感图上传到公共仓库。

完整操作方法和命令见 [星河技能使用说明](docs/xinghe-skill.md)。
