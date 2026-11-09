# -*- coding: utf-8 -*-
"""构造 ComfyUI /prompt 可接受的 API 格式工作流（Qwen-Image 2.1 多图参考编辑）。

支持三种生成模式，参考图按「人物 → 服装（可选）→ 姿态（可选）」顺序上传，
<imageN> 编号与实际上传顺序严格一致：

  同时选中服装 + 姿态：3 张参考图，换装 + 换姿势
  只选服装            ：2 张参考图，保持原姿势、只换装
  只选姿态            ：2 张参考图，保持原服装、只换姿势
  两者都不选          ：禁止（ref_tags 会抛 ValueError）
"""
import random
import re

# 提示词末尾的通用「构图 / 光线 / 背景」整句。
# 勾选「保持原图背景」时，整句替换为 SCENE_TAIL_KEEP_BG。
# 界面与全裸提示词也复用这两个常量，避免出现多份写法不一致的副本。
SCENE_TAIL = (
    "根据输出画幅合理构图，人物完整入画、不裁切头脚，光线自然柔和，背景简洁干净，"
    "真实皮肤质感，高细节、高清晰度，专业人像摄影，无文字无水印。"
)
SCENE_TAIL_KEEP_BG = "保持<image1> 的背景、光线不变。"


def apply_keep_background(text):
    """把任意提示词中的默认构图/背景整句替换为「保持原图背景」文案（幂等）。"""
    if not text:
        return text
    return text.replace(SCENE_TAIL, SCENE_TAIL_KEEP_BG)


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


def make_prompt(tags, costume_keywords="", pose_name="", pose_angle="",
                keep_background=False):
    """按当前模式生成提示词。tags 来自 ref_tags()，缺少的项表示「保持原样」。

    keep_background=True 时，末尾的通用构图/背景整句会被替换为
    「保持<image1> 的背景、光线不变。」
    """
    if "costume" not in tags and "pose" not in tags:
        raise ValueError("服装和姿态至少要选择一项")
    person = tags["person"]
    costume = tags.get("costume")
    pose = tags.get("pose")

    lines = [
        "以 %s 中的成年女性为主角，严格保持她的面部特征、五官、发型发色、肤色与体型不变，"
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
        desc = "：%s" % pose_name if pose_name else ""
        angle = "，%s视角" % pose_angle if pose_angle else ""
        lines.append(
            "让她的身体姿势、四肢位置、身体朝向与镜头角度完全参照 %s%s%s。"
            % (pose, desc, angle))
    else:
        lines.append(
            "严格保持 %s 中她原本的身体姿势、四肢位置、身体朝向与镜头角度不变，"
            "不要改变动作、站姿或坐姿。" % person)

    lines.append(SCENE_TAIL_KEEP_BG if keep_background else SCENE_TAIL)
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
    p = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": unet, "weight_dtype": weight_dtype}},
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
