# huangren 自动化系统审计与交付说明（2026-10-28）

## 已检查的系统

- 电商主图与 SKU 排版：Python 3.10/3.12 单元测试之外，CI 会运行五类演示图片的真实 CLI 生成流程并校验文件存在与像素尺寸。演示图不是可上架商品，不允许凭空生成商品规格。
- V9/V12/V13：通过全新临时数据库的初始化、SQLite integrity 与 foreign_key_check 检查验证 schema 兼容性。不会改动生产数据库。
- 供应商采集：用已提交的首屏商品资料作测试基线，真实站点抓取与离线检查解耦。
- 商品数据库：规范化商品、价格/MOQ/销量历史、可见 SKU 选项、错误日志和来源追溯。
- 数据真实性：独立验证工具逐个读取实际 page_*.json、catalog.json、details/*.json 和正文文件，不信任旧的 complete 标记。
- 数据安全：只允许自动浏览器访问 HTTPS Alibaba 页面；本地数据库、登录 profile、cookie 不写进公开 Git。
- V13 导入：从详情 Markdown 建立待核验资料索引，不会自动生成已接受的参数主张。
- Windows 采集脚本：CI 会使用 Windows PowerShell 语法解析器检查是否存在语法错误。

## 自动化边界

离线 CI 在每次 Pull Request 时检测图像、数据库、采集和 V13 集成；每周离线健康工作流在合并到默认分支后自动运行，生成可下载报告。全量网站抓取是独立的按需工作流，避免在 GitHub 上反复触发登录/验证码限制。访问限制出现时记录失败并停止，不绕过验证码。

若需要全部 139 页数据，必须在允许访问的环境执行可见浏览器采集，并通过全量独立核验和详情覆盖检查。第 1 页快照只有 16 条商品，不能标记为全量完成。

## 主要入口

- scripts/system_healthcheck.py：离线临时数据库集成健康检查
- scripts/verify_supplier_pipeline.py：独立来源文件审计
- scripts/run_full_supplier_capture.ps1：Windows 可见浏览器采集 -> SQLite -> V13
- scripts/sync_supplier_catalog_db.py：规范化数据库同步、审计和导出
- scripts/import_supplier_capture_v13.py：资料索引与未验证来源导入
- .github/workflows/ci.yml：单元测试、五类电商图片 CLI 生成、离线数据库集成和 Windows PowerShell 语法
- .github/workflows/weekly-offline-health.yml：定期离线自动体检
- .github/workflows/supplier-catalog-collection.yml：手动触发网页采集并保存数据工件

## 尚未具备的证明

- 139 页真实商品目录及每个商品详情的完整性验证。
- 动态价格/销售的跨多个实际采集日期变化验证。
- Windows 本机浏览器可完成供应商验证后的实测运行记录。
- 所有技术参数的制造商图纸/实测/第三方报告交叉证明。

完整数据库状态与完整数据覆盖是不同的验收指标，不可混为一谈。
