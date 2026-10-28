# DGDeler 阿里国际站店铺分类索引快照

- 供应商主页：https://dgdeler.en.alibaba.com/
- 全部商品入口：https://dgdeler.en.alibaba.com/productlist.html
- 采集日期：2026-10-28
- 采集方法：读取已打开的供应商主页中可见的导航文本和链接。
- 原始 HTML：未保存；没有原始 HTML SHA-256。
- 证据等级：unverified（未验证的页面观察）。
- 覆盖状态：仅店铺首页可见导航；没有完成分类页、分页或商品详情页遍历。

## 公司页面显示的概览

- 公司名称：Dongguan Dele Hardware Technology Co., Ltd.
- 地区：Guangdong Province, China
- 平台标签：Brand Holder
- 平台展示年限：1yr
- 页面显示员工数：46
- 页面显示注册商标数量：1
- 页面显示主营类别：Door Lock, Pull Handle, Hinge, Damping Hinge Shaft
- 页面显示定制标签：Minor customization；Design-based customization

以上均为网页显示内容，不构成独立核验或认证证明。

## 可见分类导航

| 分类原文 | 页面链接 | 当前证据状态 |
|---|---|---|
| Hot sale products | https://dgdeler.en.alibaba.com/productgrouplist-969259699/Hot_sale_products.html | 已记录链接，分类内容未访问 |
| Accessories | https://dgdeler.en.alibaba.com/productgrouplist-915807484/Accessories.html | 已记录链接，分类内容未访问 |
| Hinge | https://dgdeler.en.alibaba.com/productgrouplist-965193907/Hinge.html | 已记录链接，分类内容未访问 |
| Damping Hinge | https://dgdeler.en.alibaba.com/productgrouplist-911685802/Damping_Hinge.html | 已记录链接，分类内容未访问 |
| Torque Hinge | https://dgdeler.en.alibaba.com/productgrouplist-911681003/Torque_Hinge.html | 已记录链接，分类内容未访问 |
| Hasp | https://dgdeler.en.alibaba.com/productgrouplist-911700201/Hasp.html | 已记录链接，分类内容未访问 |
| Lock | https://dgdeler.en.alibaba.com/productgrouplist-964646407/Lock.html | 已记录链接，分类内容未访问 |
| Lock cylinder | https://dgdeler.en.alibaba.com/productgrouplist-911340706/Lock_cylinder.html | 已记录链接，分类内容未访问 |
| Plane lock | https://dgdeler.en.alibaba.com/productgrouplist-963643922/Plane_lock.html | 已记录链接，分类内容未访问 |
| Handle | https://dgdeler.en.alibaba.com/productgrouplist-963528746/Handle.html | 已记录链接，分类内容未访问 |
| All products | https://dgdeler.en.alibaba.com/productlist.html | 已记录链接；已有单独的第 1 页快照，显示 1/139 |

## 分页与详情采集状态

现有商品列表快照记录：第 1 页 / 共 139 页，当前页可见 16 个商品。这个数字仅来自页面显示的分页文本，尚未通过完整遍历独立验证。

- 商品列表页：1/139 页有历史快照；其余 138 页没有当前已提交的分页检查点。
- 分类页面：已记录 10 个分类/商品入口链接，但未成功读取分类列表内容。
- 商品详情：第 1 页的 16 个商品链接已记录；各详情页尚未完成逐个核验。
- SKU 选项、材质、尺寸、规格、MOQ：必须以商品详情页的可见内容、选项或原始规格文件为准；本分类索引不补造这些字段。
- 价格与交期：若后续抓取，只能记录采集当时页面明确展示的值，需保留币种、采集时间与选项上下文。

## 下一步采集方式

使用仓库中的人工监督式 Playwright 流程，在已登录的浏览器会话中逐页保存检查点；如遇登录、验证码或访问限制，应停止并记录失败 URL，不绕过限制。完成列表后再按每个唯一商品链接采集详情。最后运行独立覆盖审计，只有所有分页、商品详情和来源对应关系均通过校验，才能标记为 complete。

建议命令（在可运行浏览器的本机环境执行）：

~~~powershell
.\scripts\run_full_supplier_capture.ps1 -MaxPages 139 -DelaySeconds 2.5
~~~

## 缺失项

- 139 页的完整商品链接总表和分类到商品的归属关系。
- 其他 138 页的原始分页快照。
- 每个商品的详情原文、SKU 选项与选项价格。
- 每个 SKU 的材质、尺寸/孔距/扭矩、MOQ 与单位。
- 原始 HTML 或截图证据、页面访问错误与重试记录。
- 需要登录或验证码时的人工访问结果。

本文件只记录可见导航与当前覆盖状态，不声称店铺商品已全部提取。
