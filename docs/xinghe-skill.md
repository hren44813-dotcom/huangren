# 星河跨境电商详情 4.0：仓库内技能使用手册

本仓库将用户提供的技能包安装在 `.agents/skills/xinghe-crossborder-detail-3/`。Codex 在仓库内可自动发现 `SKILL.md`；如果没有出现，在相应的 Codex 客户端重新打开会话。

此技能专注于**跨境详情页 / Amazon A+ / AliExpress / Temu / Shopify / TikTok Shop / Ozon / Wildberries** 的模块策划与图片生成，遵循买家问题、产品真实性、逐屏独立出图、平台适配和质量复查原则。

## 两种工作模式（互不替代）

- `python scripts/build_images.py --config configs/example.json`：已有 Pillow 模板排版器，不使用外部 AI API，适合淘宝/天猫白底图、主图和 SKU 批量排版。
- `python .agents/skills/xinghe-crossborder-detail-3/scripts/generate_image.py`：本技能的 AI 接口生图程序，适合跨境详情页多屏独立生图；图片会发送到所配置的**第三方服务接口**，可能产生费用。生成结果必须人工复核，尤其是机械结构、尺寸和文案。

## 1. 本地配置（不要将真实密钥提交到 GitHub）

在仓库根目录复制配置文件，然后填写从接口服务方获得的合法密钥：

```bash
cp .agents/skills/xinghe-crossborder-detail-3/.env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .agents/skills/xinghe-crossborder-detail-3/.env.example .env
```

`.env` 已通过 `.gitignore` 排除。上传产品参考图之前也请检查是否涉及保密图纸或客户资料，公有仓库内容对所有人可见。

**注意：** 示例中的 `https://xinghe.xin/v1` 是压缩包原有的第三方 API 地址，不代表 OpenAI 官方接口或可用性承诺。需要账号和密钥；本次安装不调用接口。

## 2. 单张生成（示例）

将真实产品图放入 `assets/input/MS705.png`（只作为举例，不提供真实图片），然后执行：

```bash
python .agents/skills/xinghe-crossborder-detail-3/scripts/generate_image.py \
  --env-file .env \
  --prompt-file prompts/examples/industrial_hardware_module_01.txt \
  --image assets/input/MS705.png \
  --size 16:9 --resolution 2k \
  --output-dir output/xinghe-detail/module-01
```

## 3. 多屏批量生成

每张详情模块对应一个不同的 `*.txt` 提示词文件，脚本按文件名顺序逐张提交。示例文件只有第一屏，**需要多屏时必须先补充其余屏幕的真实产品信息和模块提示词**：

```bash
python .agents/skills/xinghe-crossborder-detail-3/scripts/generate_batch.py \
  --env-file .env \
  --prompt-dir prompts/examples \
  --image assets/input/MS705.png \
  --size 16:9 --resolution 2k \
  --output-dir output/xinghe-detail
```

如需 1440×1440、800 宽、900×1200 等指定图片尺寸，请先核对第三方接口是否支持该准确像素；**`--size` 请求参数不保证服务端输出必然符合像素值**。上传平台前应逐张核对尺寸和规则。

## 4. 使用 Codex 技能

在本仓库的 Codex 工作区中，可以输入：

> 使用 `$xinghe-crossborder-detail-3`，参考我上传的真实 MS705 锁具产品图，规划并生成 8 张跨境平台详情页；严格保持锁体、锁片、钥匙、孔位结构不变，任何未提供的数据禁止臆造。

技能将读取 `SKILL.md` 与 `references/`。**将技能放进 GitHub 仓库不会在 ChatGPT 当前会话中自动注册成可调用的插件，也不会自动执行出图。**

## 5. 核验和风险

- **已离线检查**：Python 语法、`--help` 参数、技能文件完整性。未进行真实 API 生图。
- **人工验收**：文字错别字、锁片孔位/钥匙结构、比例与阴影、参数真实性、平台实际尺寸。
- **注意费用与隐私**：脚本经第三方 API 上传提示词和参考产品图片；密钥勿公开，敏感工程图勿上传至第三方服务。
