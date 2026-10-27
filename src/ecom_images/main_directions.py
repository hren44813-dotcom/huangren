"""基于运营人员确认的信息，输出三个主图方向。不使用AI、不推断产品参数。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductBrief:
    name: str
    category: str = "工业五金"
    verified_features: str = ""
    confirmed_spec: str = ""
    confirmed_scene: str = ""
    buyer_concern: str = ""
    platform: str = "淘宝 / 天猫"


@dataclass(frozen=True)
class MainDirection:
    key: str
    name: str
    visual: str
    click_reason: str
    headline: str
    accent: str
    background: str
    limitations: str


def _clean(text: str, limit: int = 80) -> str:
    return " ".join(str(text or "").split())[:limit]


def plan_directions(brief: ProductBrief) -> tuple[dict[str, str], tuple[MainDirection, ...]]:
    name = _clean(brief.name, 60)
    if not name:
        raise ValueError("请先填写真实商品名称或型号")
    spec = _clean(brief.confirmed_spec, 60)
    scene = _clean(brief.confirmed_scene, 60)
    features = _clean(brief.verified_features, 120)
    concern = _clean(brief.buyer_concern, 100)
    info = {
        "商品": name,
        "类别": _clean(brief.category, 32) or "未确认",
        "已确认卖点": features or "未提供（不展示未经证实的功效）",
        "已确认规格": spec or "未提供（不写入数字和规格结论）",
        "已确认场景": scene or "未提供（不宣称已完成安装适配）",
        "买家顾虑": concern or "未提供（需要运营人员补充）",
        "平台": _clean(brief.platform, 40),
    }
    directions = (
        MainDirection(
            "appearance", "A · 产品识别型",
            "突出原始产品照片，主体完整放大；浅灰工业背景，文字只写真实产品名称。",
            "清晰展示外观，方便采购快速识别款式。",
            "实物外观清晰展示", "#0D7FF4", "#F4F7FA",
            "保留孔位、轮廓、配件和表面细节，不新增结构。",
        ),
        MainDirection(
            "spec", "B · 规格核对型",
            f"左侧突出已核实规格「{spec}」，右侧展示完整实物。" if spec
            else "保留规格说明位置，但没有真实参数时不写任何孔距或尺寸数字。",
            "帮助买家直接核对已确认采购规格。" if spec
            else "提醒买家核对规格，减少凭外观选错型号的风险。",
            f"规格：{spec}" if spec else "采购前请核对规格",
            "#087D83", "#ECF2F4",
            "规格必须来自人工填写的资料。" if spec
            else "未提供已核实规格，禁止捏造数字和材质。",
        ),
        MainDirection(
            "scene", "C · 应用需求型",
            f"把已确认的「{scene}」作为使用场景文案，产品保持原样。" if scene
            else "仅用抽象工业背景表达采购氛围；不得伪装成真实安装照片。",
            "帮助买家判断是否属于关注的使用场景。" if scene
            else "工业视觉风格更贴近目标采购人群。",
            f"应用场景：{scene}" if scene else "工业五金产品展示",
            "#A9671C", "#F7F4ED",
            "不得暗示额外的兼容性和适配数据。" if scene
            else "缺少已确认使用场景，不宣称设备兼容或已实装。",
        ),
    )
    return info, directions
