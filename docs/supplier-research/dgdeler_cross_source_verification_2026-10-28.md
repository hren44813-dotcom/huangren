# DGDeler 供应商交叉核验补充

> 目的：把阿里巴巴国际站主页与供应商自有网站的可见信息并列记录。网站自述、页面分类和搜索索引内容均不是独立审计结论。

## 来源

| 来源 | 用途 |
|---|---|
| https://dgdeler.en.alibaba.com/ | 阿里巴巴供应商主页：公司名称、地区、平台标签、员工数和产品分类。 |
| https://www.dg-deler.com/ | 供应商自有网站首页：产品分类、公司自述、厂区/团队/认证等宣传信息。 |
| https://www.dg-deler.com/aboutus/ | 公司介绍和联系信息。 |
| https://www.dg-deler.com/Handle/ | 拉手分类介绍及型号列表。 |
| https://www.dg-deler.com/Limit-Stop/ | 限位器分类及型号列表。 |
| https://www.dg-deler.com/best-heavy-duty-industrial-hinge.html | 推荐产品型号列表；页面是选型文章，不代表销量榜单或产品认证。 |

## 产品分类和型号线索

### 拉手分类

供应商网站拉手页面列出的型号字符串：

- HC-XAG61/62/66
- HC-XAG51/52
- HC-XAG91
- HC-XAG42
- HC-XAG22/23/24
- HC-XAG11（页面同时显示 LS516）
- HC-XAE33/34
- HC-XAE11/12
- HC-XAC26/27/29

页面对拉手分类的通用描述提到嵌入式、拉式、折叠式、管状、旋钮式和门用拉手；材料举例包括不锈钢、锌合金、铝合金、PA6/ABS 塑料。这些是分类级说明，不能直接套用到每个型号。

### 限位器分类

供应商网站限位器页面列出的型号字符串：

- HC-HFX45
- HC-HFX26
- HC-HFX03
- HC-TX92-2
- HC-TX90-3
- HC-TX90-2
- HC-TX90-1
- HC-TX80-2
- HC-TX80-1

### 主页/文章中出现的推荐型号

- 工业柜锁：HC-RV-A-240-3、HC-MS888、HC-MS861、HC-MS819。
- 重型工业铰链：HC-013-1、HC-076A、HC-076、HC-059A。

以上仅记录页面可见的型号字符串。当前没有逐个打开产品详情页，故未记录价格、MOQ、材质牌号、尺寸、扭矩、承载、寿命或认证适用范围。

## 供应商自述信息中的不一致

| 字段 | 页面显示 | 处理结论 |
|---|---|---|
| 公司名称 | 阿里巴巴主页和自有网站首页显示 Dongguan Dele Hardware Technology Co., Ltd.；About Us 页面正文/版权处出现 Dongguan Dele Hardware Products Co., Ltd. | 法律签约主体需厂家确认；不可自动视为同一法定实体。 |
| 团队规模 | 阿里巴巴主页显示 46 人；自有网站首页显示 over 50 people；About Us 页面显示 200+ Skilled Employees。 | 数值不一致，需确认统计口径、日期和所属公司/工厂范围。 |
| 厂区面积 | 自有网站首页称 8000 square meters；About Us 页面宣传栏显示 6000 m²。 | 数值不一致，需厂家提供可核验说明。 |
| 经验年限 | 首页介绍公司 established in 2020；About Us 页面同时出现 20+ Production Experience。 | 可能指公司年限或团队行业经验，但页面没有解释；不得自行统一。 |
| ISO 9001 | 自有网站首页宣称已通过 ISO 9001。 | 尚未核对证书原件、证书编号、持证主体、认证范围、发证机构及有效期。 |
| TÜV Rheinland | 阿里巴巴主页可见相关品牌标识/字样。 | 不能据此确认存在有效证书或具体产品认证。 |

## 公开联系信息

供应商自有网站 About Us 页面显示：

- 联系人：Mr. Fan
- 电话 / WhatsApp / WeChat：13725774420 / 13790201096
- 邮箱：112741218@qq.com
- 地址：Building 1, No. 110 Dayuan Road, Zhangcun, Dongcheng Street, Dongguan City, Guangdong Province

以上是网站公开展示的联系信息，尚未通过独立渠道验证；用于商务联系前建议在阿里巴巴站内再次确认。

## 对 V13 知识库的录入建议

1. 将本文件和 JSON 作为供应商背景线索导入，source kind 选 other，authority level 选 unverified。
2. 供应商页面上的公司自述只能作为带来源的声明，不直接提升为已验证事实。
3. 每个产品型号应单独创建产品记录；拿到原始产品详情页、图纸、规格表或检测报告后再录入参数证据。
4. 对员工数、厂区面积、公司主体名称和认证信息建立待核实事项，不覆盖原始页面说法。
5. 选型文章中出现的通用承载、寿命、盐雾等数值不应直接作为具体产品型号的性能参数。

最后更新：2026-10-28