import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "NoN-Related-Mods-zh_CN-1.21.11" / "assets"
MODS = Path(r"E:\Minecraft\.minecraft\versions\1.21.11-Fabric-0.19.3\mods")
RESOURCEPACKS = Path(r"E:\Minecraft\.minecraft\versions\1.21.11-Fabric-0.19.3\resourcepacks")


def read_zip_json(archive: Path, member: str) -> dict[str, str]:
    with zipfile.ZipFile(archive) as zf, zf.open(member) as fp:
        return json.load(fp)


def load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict[str, str]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


non_en = read_zip_json(
    MODS / "needsofnature-1.3.1.jar", "assets/needsofnature/lang/en_us.json"
)
non_en.update(
    read_zip_json(
        RESOURCEPACKS / "needs_of_nature_default_packv1.3.0.zip",
        "assets/needsofnature/lang/en_us.json",
    )
)
non_path = ASSETS / "needsofnature" / "lang" / "zh_cn.json"
non_zh = load(non_path)

for key, english in non_en.items():
    value = non_zh[key]
    value = value.replace("香草", "原版")
    value = value.replace("育种", "繁殖")
    if re.search(r"\bcum\b", english, re.IGNORECASE):
        value = value.replace("暨", "精液").replace("兼", "精液").replace("累积", "精液")
    if "tank" in english.lower() and "cum" in english.lower():
        value = value.replace("水箱", "储罐").replace("坦克", "储罐")
    if "egg" in english.lower():
        value = value.replace("鸡蛋", "卵").replace("Egg", "卵").replace("egg", "卵")
    if "pregnan" in english.lower():
        value = value.replace("怀孕机会", "怀孕概率")
    non_zh[key] = value

non_zh.update(
    {
        "config.needsofnature.category.liquid": "精液",
        "config.needsofnature.liquid_decay": "精液衰减量/秒（0-20）：",
        "config.needsofnature.liquid_gain_button": "精液获取量……",
        "config.needsofnature.liquid_gain_reset_title": "重置精液获取量？",
        "config.needsofnature.liquid_gain_title": "各实体精液获取量",
        "config.needsofnature.liquid_settings_title": "Needs of Nature 精液设置",
        "config.needsofnature.liquid_tank_capacity": "精液储罐容量（毫升）：",
        "config.needsofnature.pregnancy_title": "Needs of Nature 怀孕设置",
        "config.needsofnature.section.breeding": "繁殖",
        "config.needsofnature.section.liquid_tank": "精液储罐",
        "config.needsofnature.toggle.liquid_tank": "启用精液储罐：",
        "config.needsofnature.ui_liquid": "精液储罐",
        "config.needsofnature.ui_liquid_x": "精液储罐 X：",
        "config.needsofnature.ui_liquid_y": "精液储罐 Y：",
        "config.needsofnature.egg_profile_title": "卵设置",
        "config.needsofnature.entity_profile_column.egg": "卵",
        "config.needsofnature.entity_profile_egg_button": "卵",
        "config.needsofnature.offspring_count_button": "实体怀孕配置……",
        "config.needsofnature.offspring_count_reset_title": "重置怀孕配置？",
        "config.needsofnature.offspring_count_title": "各实体怀孕配置",
        "config.needsofnature.pregnancy_chance_percent": "怀孕概率（0-100）：",
        "config.needsofnature.tooltip.egg_profile_health": "卵的生命值，以 Minecraft 原始生命值点数计。",
        "config.needsofnature.tooltip.entity_profile_entry_birth_entity": "此次怀孕生成的实体 ID。留空则使用来源实体。",
        "config.needsofnature.tooltip.entity_profile_entry_chance": "覆盖该实体的怀孕概率。留空则使用显示的默认值或全局值。",
        "config.needsofnature.tooltip.liquid_decay": "玩家精液储罐每秒减少的毫升数。",
        "config.needsofnature.tooltip.liquid_gain_add": "添加一条新的实体精液配置。",
        "config.needsofnature.tooltip.liquid_gain_button": "打开各实体精液获取量和颜色覆盖编辑器。",
        "config.needsofnature.tooltip.liquid_gain_entry_ml": "该实体作为注入方时给予的精液量（毫升）。",
        "config.needsofnature.tooltip.liquid_gain_reset": "将所有精液获取量和颜色配置恢复默认。",
        "config.needsofnature.tooltip.liquid_puddle_despawn_seconds": "生成的精液池粒子的存在时间（秒）。",
        "config.needsofnature.tooltip.liquid_tank_capacity": "玩家精液储罐可容纳的最大精液量。",
        "config.needsofnature.tooltip.offspring_count_add": "添加一条新的实体怀孕配置。",
        "config.needsofnature.tooltip.offspring_count_button": "打开各实体怀孕配置编辑器。",
        "config.needsofnature.tooltip.offspring_count_reset": "将怀孕配置恢复为 NoN 内容包默认值。",
        "config.needsofnature.tooltip.pregnancy_chance_percent": "玩家动画达到高潮时触发怀孕的概率。",
        "config.needsofnature.tooltip.require_male_female_breeding": "启用后，动画繁殖仅允许一个雄性亲本和一个雌性亲本。",
        "config.needsofnature.tooltip.toggle.liquid_tank": "全局启用或禁用玩家精液储罐机制。",
        "config.needsofnature.tooltip.use_animation_breeding": "启用后，进入求爱状态的动物会先尝试通过 NoN 动画繁殖，再生成幼崽。",
        "entity.needsofnature.horse_liquid_collector": "马用精液收集器",
        "item.needsofnature.horse_liquid_collector": "马用精液收集器",
        "stat.needsofnature.liquid_gained_ml_total": "NoN：获得精液（毫升）",
        "stat.needsofnature.offspring_spawned_total": "NoN：已生成后代",
        "stat.needsofnature.pregnancies_completed_total": "NoN：已完成怀孕",
        "stat.needsofnature.pregnancies_started_total": "NoN：已开始怀孕",
    }
)
save(non_path, non_zh)


af_path = ASSETS / "animationframework" / "lang" / "zh_cn.json"
af_zh = load(af_path)
for key, value in af_zh.items():
    value = value.replace("香草", "原版")
    value = value.replace("演员", "参与者").replace("actor", "参与者")
    value = value.replace("mod ", "模组").replace("mod未", "模组未").replace("mod 缺", "模组缺")
    af_zh[key] = value

af_zh.update(
    {
        "config.animationframework.force_vanilla_entity_textures": "强制使用原版实体纹理（忽略资源包）",
        "config.animationframework.block_search_radius": "方块搜索半径",
        "config.animationframework.debug_damage_behavior": "动画开始后的受伤行为",
        "config.animationframework.debug_damage_behavior.stop_on_damage": "受伤时停止动画",
        "config.animationframework.debug_damage_behavior.ignore_damage": "忽略伤害",
        "config.animationframework.debug_damage_behavior.block_damage": "阻止伤害",
        "debug.animationframework.start_cancelled_players_too_far_from_requester": "[AFW] 已取消开始：所选玩家必须在请求者周围 %s 格以内。",
        "debug.animationframework.queue_skipped_no_actors_resolved": "[AFW] 已跳过 %s 的队列（参与者：%s）：未能解析任何参与者。",
        "debug.animationframework.instance_in_different_world": "[AFW] 实例位于另一个世界，无法从这里停止。",
    }
)
save(af_path, af_zh)

print("refined NoN and AnimationFramework translations")
