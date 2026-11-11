# -*- coding: utf-8 -*-
"""构造 ComfyUI /prompt 可接受的 API 格式工作流（Qwen-Image 2.1 多图参考编辑）。

支持三种生成模式，参考图按「人物 → 服装（可选）→ 姿态（可选）」顺序上传，
<imageN> 编号与实际上传顺序严格一致：

  同时选中服装 + 姿态：3 张参考图，换装 + 换姿势
  只选服装            ：2 张参考图，保持原姿势、只换装
  只选姿态            ：2 张参考图，保持原服装、只换姿势
  两者都不选          ：禁止（ref_tags 会抛 ValueError）

姿态参考句统一为「让她的身体姿势、四肢位置、脸部朝向、身体朝向与镜头角度完全参照 <imageN>：」
加 _metadata.csv「姿态描述_中文」列的整段内容；该列已包含画幅、躯体姿势、四肢手指、
脸部朝向与镜头方向，因此不再按「角度」列额外拼「XX视角 / 脸部朝下」之类的短句。

提示词里的构图句有两个版本：全身系列用 FRAME_FULL，姿态库「上半身单人」系列
用 FRAME_UPPER（安卓版 Prompt.kt 与之逐字对应）。所有模式的文案只在
本文件里定义一份，避免界面 / 命令行 / 全裸模式出现写法不一致的副本。
"""
import random
import re

# 姿态库 CSV「系统」列的这个取值是半身 / 胸像素材，不能要求「人物完整入画、不裁切头脚」。
UPPER_BODY_SYSTEM = "上半身单人"

FRAME_FULL = "人物完整入画、不裁切头脚"
FRAME_UPPER = "半身取景，头部与上半身完整入画、不裁切头部与肩膀，腿部不必入画"

# 提示词末尾的通用「构图 / 光线 / 背景」整句。
# 勾选「保持原图背景」时，整句替换为 SCENE_TAIL_KEEP_BG（半身模式会补回半身约束）。
SCENE_TAIL = (
    "根据输出画幅合理构图，" + FRAME_FULL + "，光线自然柔和，背景简洁干净，"
    + "真实皮肤质感，高细节、高清晰度，专业人像摄影，无文字无水印。"
)
SCENE_TAIL_KEEP_BG = "保持<image1> 的背景、光线不变。"

# 上半身系列：只替换构图那一小句，光线 / 质感 / 画质描述保持不变。
SCENE_TAIL_UPPER = SCENE_TAIL.replace(FRAME_FULL, FRAME_UPPER)


def scene_tail(upper_body=False):
    """按是否半身构图返回末尾整句。默认参数保证旧调用行为不变。"""
    return SCENE_TAIL_UPPER if upper_body else SCENE_TAIL


def keep_bg_tail(upper_body=False):
    """「保持原图背景」的替换文案；半身模式额外保留半身构图约束。"""
    return SCENE_TAIL_KEEP_BG + (FRAME_UPPER if upper_body else "")


def apply_keep_background(text, upper_body=False):
    """把任意提示词中的默认构图/背景整句替换为「保持原图背景」文案（幂等）。

    upper_body=True 时按半身版本的整句匹配，避免用户手工改成半身句后替换失效。
    """
    if not text:
        return text
    return text.replace(scene_tail(upper_body), keep_bg_tail(upper_body))


def ref_tags(has_costume, has_pose):
    """按上传顺序给各类参考图分配 <imageN> 标签。"""
    if not has_costume and not has_pose:
        raise ValueError("服装和姿态至少要选择一项")
    tags = {"person": "<image1>"}
    n = 2
    if has_costume:
        tags["costume"] = "<image%d>" % n
        n += 1
    if has_pose:
        tags["pose"] = "<image%d>" % n
    return tags


# 姿态参考句的统一前缀（不含冒号后的内容）。安卓版 Prompt.kt 与之逐字一致。
POSE_REF_PREFIX = "让她的身体姿势、四肢位置、脸部朝向、身体朝向与镜头角度完全参照 %s"


def pose_reference_line(pose_tag, description="", pose_name="", pose_angle=""):
    """生成姿态参考句：统一前缀 + 冒号 + _metadata.csv「姿态描述_中文」整段。

    description 自带句末句号，不再补句号；CSV 缺该列（旧素材库）时降级为
    「姿态名，XX视角。」，但不追加任何按角度推断的脸部朝向短句。
    所有模式（换装 / 只换姿势 / 全裸）都调用本函数，保证文案单一来源。
    """
    desc = (description or "").strip()
    if not desc:
        name = (pose_name or "").strip()
        angle = (pose_angle or "").strip()
        bits = [x for x in (name, "%s视角" % angle if angle else "") if x]
        desc = "，".join(bits) + "。" if bits else ""
    elif not desc.endswith(("。", "！", "？", ".", "!", "?")):
        desc += "。"
    return POSE_REF_PREFIX % pose_tag + ("：" + desc if desc else "。")


def make_prompt(tags, costume_keywords="", pose_name="", pose_angle="",
                keep_background=False, upper_body=False, pose_description=""):
    """按当前模式生成提示词。tags 来自 ref_tags()，缺少的项表示「保持原样」。

    pose_description 是 _metadata.csv「姿态描述_中文」列内容，按当前选中的那张
    姿态图取值（同一姿态不同角度描述不同）；为空时降级为 pose_name + pose_angle。

    keep_background=True 时，末尾的通用构图/背景整句会被替换为
    「保持<image1> 的背景、光线不变。」（upper_body=True 时后面补半身构图句）。
    upper_body=True 表示姿态来自「上半身单人」系列，构图句改用半身版本。
    """
    if "costume" not in tags and "pose" not in tags:
        raise ValueError("服装和姿态至少要选择一项")
    person = tags["person"]
    costume = tags.get("costume")
    pose = tags.get("pose")

    lines = [
        "以 %s 中的女性为主角，严格保持她的面部特征、五官、发型发色、肤色与体型不变，"
        "生成一张自然写实的人像摄影照片。" % person,
    ]
    if costume:
        cloth = "（%s）" % costume_keywords if costume_keywords else ""
        lines.append(
            "让她换上 %s 中展示的整套服装，精确还原款式、颜色、图案、面料质感与搭配%s。"
            % (costume, cloth))
    else:
        lines.append(
            "严格保持 %s 中她原本的服装不变：款式、颜色、图案、面料质感与搭配都与原照片"
            "完全一致，不要更换、添加或改动任何衣物。" % person)

    if pose:
        lines.append(pose_reference_line(
            pose, pose_description, pose_name, pose_angle))
    else:
        lines.append(
            "严格保持 %s 中她原本的身体姿势、四肢位置、身体朝向与镜头角度不变，"
            "不要改变动作、站姿或坐姿。" % person)

    if keep_background:
        lines.append(keep_bg_tail(upper_body))
    else:
        lines.append(scene_tail(upper_body))
    return "\n".join(lines)


NEGATIVE_BASE = (
    "多个人物，多余肢体，畸形的手指，面部变形，身份不一致，"
    "低分辨率，模糊，过曝，卡通，插画，3D 渲染，文字，水印，logo，边框"
)


def make_negative(tags):
    """按模式调整负面词：哪一侧要保持原样，就显式抑制那一侧被改动。"""
    extra = []
    if "costume" in tags:
        extra.append("服装错乱")
    else:
        extra.append("服装被更换，衣物款式或颜色改变，换装")
    if "pose" in tags:
        extra.append("姿势不符")
    else:
        extra.append("姿势被改变，四肢位置变化，动作不符")
    return "，".join(extra + [NEGATIVE_BASE])


# 默认的完整三图模式负面词（build 未显式传 negative 时使用）
NEGATIVE = make_negative(ref_tags(True, True))


def validate_prompt(text, n_images):
    """检查提示词里的 <imageN> 引用不超出实际参考图数量。返回错误串或 None。"""
    used = sorted({int(x) for x in re.findall(r"<image(\d+)>", text or "")})
    if not used:
        return "提示词中没有 <image1> 等参考图引用，请重新点选素材或切换任一选项以重建提示词。"
    bad = [i for i in used if i < 1 or i > n_images]
    if bad:
        return ("提示词引用了不存在的参考图 %s；当前只有 %d 张参考图。"
                "请重新点选素材或切换任一选项以重建提示词。"
                % (", ".join("<image%d>" % i for i in bad), n_images))
    return None


def build(*, refs, width, height, prompt, negative=None,
          seed=None, steps=25, cfg=1.0, sampler="euler", scheduler="simple",
          unet="qwen-image-2.1-UC-int8_convrot.safetensors",
          clip=r"qwen_image_2.1\qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors",
          vae="qwen_image_2.1_vae_bf16.safetensors", clip_type="qwen_image",
          weight_dtype="default", ref_resolution=1024,
          cache_device="auto", cache_dtype="default", prefix="PoseWearStudio/result"):
    """返回 (prompt_dict, output_node_id)。

    refs: 按 <image1> <image2> ... 顺序排列的 ComfyUI 内部文件名，1~3 张。
    """
    refs = list(refs)
    if not 1 <= len(refs) <= 3:
        raise ValueError("参考图数量必须是 1~3 张，当前 %d 张" % len(refs))
    seed = random.randint(1, 2 ** 31 - 1) if seed is None else int(seed)
    # GGUF 量化基模不能用核心 UNETLoader：ComfyUI-GGUF 插件提供 UnetLoaderGGUF，
    # 其必填输入只有 unet_name（没有 weight_dtype），候选文件来自
    # diffusion_models / unet 目录下的 *.gguf。其余节点两种模型完全一致。
    if str(unet).lower().endswith(".gguf"):
        unet_loader = {"class_type": "UnetLoaderGGUF",
                       "inputs": {"unet_name": unet}}
    else:
        unet_loader = {"class_type": "UNETLoader", "inputs": {
            "unet_name": unet, "weight_dtype": weight_dtype}}
    p = {
        "1": unet_loader,
        "2": {"class_type": "QwenImage21Cache", "inputs": {
            "model": ["1", 0], "device": cache_device, "dtype": cache_dtype}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": clip, "type": clip_type, "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }

    # COMFY_AUTOGROW_V3 在 API 格式中使用 <组名>.<子项名> 作为键
    enc = {
        "clip": ["3", 0], "vae": ["4", 0],
        "prompt": prompt, "negative_prompt": negative or NEGATIVE,
        "resolution": int(ref_resolution),
    }
    for i, name in enumerate(refs, 1):
        node_id = str(9 + i)  # 10 / 11 / 12，与旧版三图工作流保持一致
        p[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        enc["images.image_%d" % i] = [node_id, 0]

    p.update({
        "20": {"class_type": "TextEncodeQwenImage21", "inputs": enc},
        # 显式指定目标画幅，取代节点自带的 latent 输出
        "21": {"class_type": "EmptyLatentImage", "inputs": {
            "width": int(width), "height": int(height), "batch_size": 1}},
        "30": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "seed": seed, "steps": int(steps),
            "cfg": float(cfg), "sampler_name": sampler, "scheduler": scheduler,
            "positive": ["20", 0], "negative": ["20", 1],
            "latent_image": ["21", 0], "denoise": 1.0}},
        "31": {"class_type": "VAEDecode", "inputs": {
            "samples": ["30", 0], "vae": ["4", 0]}},
        "32": {"class_type": "SaveImage", "inputs": {
            "images": ["31", 0], "filename_prefix": prefix}},
    })
    return p, "32"
