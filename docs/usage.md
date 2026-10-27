# 运行指南与配置字段

## 环境

- Python 3.10 或更新版本，Pillow 10.2 至 12.x。
- 中文文字推荐系统安装 `Noto Sans CJK` 或 Windows 微软雅黑。如果文字不显示，可在每个任务中填写 `"font_path": "字体文件实际路径"`。字体不要提交到公开仓库。
- 默认从仓库根目录解析 `source`、`output`、`logo`；可以使用命令行 `--base-dir` 修改。

## 单个任务举例

```json
{
  "jobs": [
    {
      "mode": "main",
      "source": "assets/input/MS705.png",
      "output": "output/MS705_main.jpg",
      "brand": "自有品牌名称",
      "title": "MS705 转舌锁",
      "subtitle": "按实际产品规格填写",
      "selling_points": ["仅填写已核实卖点"],
      "accent": "#0D7FF4",
      "background": "#F4F7FA"
    }
  ]
}
```

`mode` 是五种：`search_white` / `main` / `portrait` / `sku` / `detail`。`source`、`output` 为必填，SKU 模式还必须填写 `title`。

- `title`：主图、SKU、详情页可选或必填的产品标题。过长的文本会报错，防止挤压产品。
- `subtitle`：主图补充信息。
- `selling_points`：仅主图和详情页绘制，最多 3 个真实卖点。
- `accent`：色块与强调色，使用十六进制颜色。默认蓝色 `#0D7FF4`。
- `background`：主图、SKU、竖版、详情页背景色，默认浅灰 `#F4F7FA`。
- `brand` 或 `logo`：主图/详情页的文字品牌或透明 Logo 图片路径；不用于搜推图。
- `label`：3:4 竖图左上角的小字；不填写就无文字。
- `title_color`：SKU 顶部色块的文字颜色，例如黄色背景用 `#000000`。
- `specs`：SKU 最多 4 组，如 `[{"label":"型号","value":"MS705"}]`；必须人工确认值。

## 批量 SKU

`configs/batch_sku.json` 用 `source_glob` 自动匹配文件，`output_pattern` 包含 `{stem}` 变量代表文件名（不带后缀）；`title` 也支持 `{stem}`。

```json
{
  "jobs": [
    {
      "mode": "sku",
      "source_glob": "assets/input/*.png",
      "output_pattern": "output/sku/{stem}_sku.jpg",
      "title": "{stem} 产品规格图",
      "accent": "#0D7FF4",
      "specs": []
    }
  ]
}
```

批量任务请让原始文件名与型号一一对应。没有可靠的数据时，请不要批量填造规格参数。

## 保留原有尺寸图

尺寸线/尺寸数字已画在源图片上时，程序将 **整张原图等比例放置**，不会重画、修正或篡改现有标注。若新 SKU 规格需要不同尺寸，应提供相应的、已确认的尺寸源图，而不是批量复制一个型号的尺寸到其他型号。

## 限制

1. 本版本是本地图片排版与导出工具，**不自动抠复杂背景、不修复低清晰度、不修改工业五金结构**。
2. 不是淘宝、天猫、阿里国际站官方尺寸核验接口；规格来自本项目预设，发布前以目标平台实时要求为准。
3. `detail` 暂为宽 800px、高 1600px 的单模块，可按模块分开生成后人工组合；未实现可变高度的整页详情设计器。
4. 输出同名文件默认会被重新生成覆盖。请用不同目录或备份保护正式版本。
5. 为避免意外处理错误，源图像应保持单个清晰主体，建议透明 PNG；场景照片需要人工核对排版及版权。
