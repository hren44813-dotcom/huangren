# 仓库智能体协作说明

- 跨境电商详情/A+/PDP 模块创作：优先阅读 `.agents/skills/xinghe-crossborder-detail-3/SKILL.md`，并按需求阅读其 `references/`。要求真实用户产品图、明确平台和尺寸时，按实际输入执行，绝不编造参数或认证。
- 淘宝/天猫本地模板批量排版（白底 1440×1440、SKU、3:4）：使用 `src/ecom_images/generator.py` 及 `scripts/build_images.py`，保留产品原图，不做 AI 产品结构重绘。
- 电商主图方向策划与正式主图工作流：优先阅读 `.agents/skills/ecom-main-image-skill/SKILL.md`，先识别商品信息和买家顾虑，再提供 3 个主图方向；用户选定后再生成正式主图，并执行变形、卖点、平台尺寸检查。
- 两种方式边界不同：跨境 AI Skill 不允许通过本地拼接生成它自己的最终详情模块；本地 Pillow 工具则用于明确要求的模板排版。不要把两种方式混用造成产品细节改变。
- API 密钥必须通过环境变量或未纳入版本控制的 `.env` 配置。禁止上传任何真实 API key、密码、客户机密图纸。没有密钥时只验证本地语法与配置，不承诺真实生图完成。
- 所有成品在实际平台发布前必须人工验收结构、尺寸、文字、合规和视觉质量。

- 工业五金主图/SKU 制作前先读 `docs/knowledge-industrial-hardware.md`。SKU 预设样式使用 `src/ecom_images/sku_template_v3.py`；尺寸图作为原图完整缩放，不能修改图中的孔位、引线和数字。用户未提供证据的性能与兼容性不可声称。
