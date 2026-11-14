# -*- coding: utf-8 -*-
"""MiniMax-H3-Image 的提示词与 API 工作流（与 Qwen 侧的 workflow.py 独立）。

官网与本机 ComfyUI 内置节点的关键约束：

* 生成与编辑统一在一个 checkpoint；参考图按上传顺序称为 <Picture 1>、
  <Picture 2> ……（不是 Qwen 的 <imageN>）。image_1 是被编辑的图，其余是参考。
* 提示词需要一段**详细的英文整图描述**。按 WorkBuddy 的
  h3-image-prompt-writing（edit 指南）写成单段落：
  源内容定义 → 目标图总览与各 <Subject N> 的关系 → 变化与新增细节。
  姿态部分直接取 _metadata.csv 的「姿态描述_英文」列。
* 6 个采样步、CFG=1、euler/simple；**不支持负面提示词**，官方工作流用
  ConditioningZeroOut(positive) 当作 KSampler 的 negative。
* 有效范围约 4~20 MP、16 MP 左右最佳；宽高必须是 32 的倍数
  （与 resolution.calc 的 UNIT 一致）。

节点结构与本机官方「MiniMax H3 Image Edit」模板一致：
UNETLoader / CLIPLoader(type=minimax) / VAELoader →
MiniMaxH3ImageConditioning → KSampler → VAEDecode → SaveImage。
"""
import random
import re

from config import (H3_UNET, H3_CLIP, H3_VAE, H3_CLIP_TYPE,
                    H3_STEPS, H3_CFG, rmbg_inputs, DEFAULT_BG_MODE)

# 姿态英文描述列缺列（旧素材库）时的兜底句，仍是英文整图叙述。
POSE_FALLBACK_EN = (
    "The body, arms, hands, legs and gaze follow the arrangement shown in the "
    "pose reference, with the same body orientation and camera direction."
)

# 「保持原姿势」时 <Subject N> 的完整保留句：原大小 / 原位置 / 原姿势 / 原表情。
KEEP_POSE_RELATION_EN = (
    "<Subject %d> is fully preserved, together with the girl's original scale "
    "and placement inside the frame: she is not enlarged, shrunk, shifted, "
    "cropped or recomposed, and the distances from her head, hands and feet to "
    "the frame edges stay exactly as in %s. Her body pose, limb placement, "
    "finger positions, body orientation, head tilt and camera angle stay exactly "
    "the same, and her facial expression, gaze direction, eyebrow and eye shape, "
    "mouth shape and every subtle micro-expression remain untouched."
)

# 保持原姿势时的构图句：不再要求 full-length / half-body / 按新画幅重新构图。
KEEP_POSE_FRAMING_EN = (
    "The original framing, subject scale and subject placement from %s are "
    "preserved; the composition is not recomputed for a different output canvas."
)


# 「背景」下拉的三种英文描述（与安卓版 H3Prompt.kt 逐字一致）。
BG_KEEP_EN = ("The same background and soft illumination from %s sit behind "
              "<Subject 1> at the same depth.")
BG_WHITE_EN = (
    "The original background, scenery, objects and shadows behind the subject "
    "are replaced by a perfectly uniform, evenly lit pure white studio backdrop "
    "with no texture, no objects, no gradient and no cast shadow. The subject "
    "silhouette stays sharp and clearly separated from the pure white backdrop, "
    "with clean edges around the hair, clothing and limbs. Soft natural light "
    "falls evenly across the subject."
)
BG_TRANSPARENT_EN = (
    "The original background, scenery, objects and shadows behind the subject "
    "are replaced by a perfectly flat, uniform, evenly lit light studio backdrop "
    "with no texture, no objects, no gradient and no cast shadow. The subject "
    "silhouette stays sharp and clearly separated from the backdrop, with clean "
    "edges around the hair, clothing and limbs, so the figure can be extracted "
    "onto a transparent background. Soft natural light falls evenly across the subject."
)


def bg_en(bg_mode=DEFAULT_BG_MODE, person="<Picture 1>"):
    """按「背景」下拉返回英文背景句。未知值回落为 keep。"""
    if bg_mode == "white":
        return BG_WHITE_EN
    if bg_mode == "transparent":
        return BG_TRANSPARENT_EN
    return BG_KEEP_EN % person


def h3_ref_tags(has_costume, has_pose):
    """按上传顺序分配 <Picture N> 标签：人物 → 服装（可选）→ 姿态（可选）。

    与 workflow.ref_tags() 的顺序严格一致，因此 generator 的上传顺序无需改动。
    全裸 + 保持原姿势是合法的 1 张参考图模式，此时两个参数都为 False。
    """
    tags = {"person": "<Picture 1>"}
    n = 2
    if has_costume:
        tags["costume"] = "<Picture %d>" % n
        n += 1
    if has_pose:
        tags["pose"] = "<Picture %d>" % n
    return tags


def make_h3_prompt(tags, costume_keywords="", pose_name="", pose_angle="",
                   bg_mode=DEFAULT_BG_MODE, upper_body=False,
                   pose_description_en="", nude=False, half_body=False):
    """生成符合 H3-Image 规范的单段落英文提示词。

    tags 来自 h3_ref_tags()；pose_description_en 取 _metadata.csv 的
    「姿态描述_英文」列（同一姿态不同角度各有一行）。
    costume_keywords / pose_name / pose_angle 仅为与 Qwen 侧签名对齐而保留：
    服装库关键词是中文、姿态名也是中文，按 H3 规范不写入英文提示词，
    服装与姿态的内容一律由参考图本身定义。

    nude=True 时用中性的英文叙述表达「无衣物」，不写入 Qwen 侧的标签串
    （H3 是自然语言模型，标签串既不符合规范也会干扰指令跟随）。
    """
    person = tags["person"]
    costume = tags.get("costume")
    pose = tags.get("pose")
    keep_background = (bg_mode == "keep")

    parts = ["The girl in %s is <Subject 1>." % person]
    subject_no = 2

    # ---- 1. 源内容定义（每个需要独立关系的范围各给一个 Subject）----
    costume_sub = pose_sub = None
    if costume:
        costume_sub = subject_no
        parts.append("The complete outfit displayed in %s is <Subject %d>."
                     % (costume, costume_sub))
        subject_no += 1
    if pose:
        pose_sub = subject_no
        parts.append("The full pose and camera setup shown in %s is <Subject %d>."
                     % (pose, pose_sub))
        subject_no += 1

    keep_costume_sub = keep_pose_sub = bg_sub = None
    if not costume and not nude:
        keep_costume_sub = subject_no
        parts.append("The complete outfit worn by the girl in %s is <Subject %d>."
                     % (person, keep_costume_sub))
        subject_no += 1
    if not pose:
        keep_pose_sub = subject_no
        parts.append("The original pose arrangement in %s is <Subject %d>."
                     % (person, keep_pose_sub))
        subject_no += 1
    if keep_background:
        bg_sub = subject_no
        parts.append("The original background and lighting setup in %s is <Subject %d>."
                     % (person, bg_sub))
        subject_no += 1

    # ---- 2. 目标图总览 ----
    # 不带冠词：前面已有 "a naturalistic"，避免 "a naturalistic a ..." 的双冠词
    keep_pose = pose is None
    # 保持原姿势时不能写 full-length / upper-body：原图可能是任意取景，
    # 强行指定画幅会让模型重新摆位、缩放人物。
    framing = ("portrait" if keep_pose else
               ("upper-body portrait" if upper_body else "full-length portrait"))
    overview = ("The target image is a naturalistic %s photograph of <Subject 1>"
                % framing)
    if nude:
        overview += ", shown without clothing"
    overview += "."
    parts.append(overview)

    # ---- 3. 各 Source 与目标的关系 ----
    changed = []
    if costume or nude:
        changed.append("her outfit changes" if costume else "she is shown without clothing")
    if pose:
        changed.append("her body pose changes")
    if not changed:
        changed.append("only the presentation changes")
    parts.append(
        "<Subject 1> is largely preserved; her facial features, facial expression, "
        "hairstyle, hair color, skin tone and body shape remain unchanged while %s."
        % " and ".join(changed))

    if keep_costume_sub:
        parts.append("<Subject %d> is fully preserved." % keep_costume_sub)
    if keep_pose_sub:
        parts.append(KEEP_POSE_RELATION_EN % (keep_pose_sub, person))
    if bg_sub:
        parts.append("<Subject %d> is fully preserved." % bg_sub)

    if costume_sub:
        parts.append(
            "<Subject %d> supplies the exact garments transferred to <Subject 1>. "
            "The transferred outfit keeps its cut, color, pattern, fabric texture "
            "and styling without importing anything else from %s."
            % (costume_sub, costume))
    if pose_sub:
        parts.append(
            "<Subject %d> supplies the exact body pose, limb placement, face "
            "direction, body orientation and camera angle transferred to <Subject 1>."
            % pose_sub)
        desc = (pose_description_en or "").strip()
        parts.append(desc if desc else POSE_FALLBACK_EN)

    # ---- 4. 变化与新增细节（构图 / 光线 / 背景 / 质感）----
    if nude:
        if half_body:
            parts.append(
                "The garments visible in %s are absent from the target image; "
                "no clothing appears on <Subject 1>. She has a slim, hourglass "
                "figure with a narrow waist and large breasts, rosy nipples, "
                "smooth bare skin." % person)
        else:
            parts.append(
                "The garments visible in %s are absent from the target image; "
                "no clothing appears on <Subject 1>. She has a slim, hourglass "
                "figure with a narrow waist and large breasts, rosy nipples, "
                "smooth bare skin, and sparse pubic hair." % person)
    if keep_pose:
        parts.append(KEEP_POSE_FRAMING_EN % person)
    elif upper_body:
        parts.append(
            "The framing is a half-body portrait with the head and upper torso "
            "fully in frame, the head and shoulders uncropped, and the legs "
            "outside the image.")
    else:
        parts.append(
            "The entire figure stays inside the frame with the head and feet uncropped.")
    parts.append(bg_en(bg_mode, person))
    parts.append(
        "Believable skin texture, fine fabric detail and high-resolution "
        "photographic clarity complete the portrait. No lettering, text or "
        "watermarks appear.")

    # edit 指南要求一个连续段落，不分段、不列点、不写编辑指令句。
    return " ".join(parts)


def validate_h3_prompt(text, n_images):
    """检查 <Picture N> 引用与上传数量一致，并排除混入 Qwen 的 <imageN>。"""
    if "<image" in (text or ""):
        return ("当前使用 MiniMax-H3-Image，提示词里仍是 Qwen 的 <imageN> 标签。"
                "请重新点选素材或切换一次分辨率档位以重建英文提示词。")
    used = sorted({int(x) for x in re.findall(r"<Picture\s+(\d+)>", text or "")})
    if not used or 1 not in used:
        return ("提示词中没有 <Picture 1> 等参考图引用（H3-Image 用英文描述）。"
                "请重新点选素材或切换任一选项以重建提示词。")
    bad = [i for i in used if i < 1 or i > n_images]
    if bad:
        return ("提示词引用了不存在的参考图 %s；当前只有 %d 张参考图。"
                "请重新点选素材或切换任一选项以重建提示词。"
                % (", ".join("<Picture %d>" % i for i in bad), n_images))
    return None


def make_h3_plain_prompt(bg_mode=DEFAULT_BG_MODE, upper_body=False):
    """「保持原服装 + 保持原姿势」的 H3 英文单段落提示词（只引用 <Picture 1>）。

    背景由 bg_mode 决定；该模式本质是保持原姿势，不指定 full-length /
    upper-body 画幅，并完整保留人物的原大小、原位置、原姿势与原表情。
    H3 不支持负面提示词。upper_body 仅为与 Qwen 侧签名对齐而保留。
    """
    person = "<Picture 1>"
    keep = (bg_mode == "keep")
    parts = [
        "The girl in %s is <Subject 1>." % person,
        "The complete outfit worn by the girl in %s is <Subject 2>." % person,
        "The original pose arrangement in %s is <Subject 3>." % person,
    ]
    if keep:
        parts.append("The original background and lighting setup in %s is <Subject 4>."
                     % person)
    parts += [
        "The target image is a naturalistic portrait photograph of <Subject 1>.",
        "<Subject 1> is largely preserved; her facial features, facial expression, "
        "hairstyle, hair color, skin tone and body shape remain unchanged while %s."
        % ("only the presentation changes" if keep else "only the background changes"),
        "<Subject 2> is fully preserved.",
        KEEP_POSE_RELATION_EN % (3, person),
    ]
    if keep:
        parts.append("<Subject 4> is fully preserved.")
        parts.append(BG_KEEP_EN % person)
    else:
        parts.append(BG_WHITE_EN if bg_mode == "white" else BG_TRANSPARENT_EN)
    parts += [
        KEEP_POSE_FRAMING_EN % person,
        "Believable skin texture, fine fabric detail and high-resolution "
        "photographic clarity complete the portrait. No lettering, text or "
        "watermarks appear.",
    ]
    return " ".join(parts)


def make_h3_strip_bg_prompt(upper_body=False):
    """兼容旧调用：等价于 transparent 背景的双保持模式。"""
    return make_h3_plain_prompt("transparent", upper_body)


def build_h3(*, refs, width, height, prompt, seed=None,
             steps=H3_STEPS, cfg=H3_CFG, sampler="euler", scheduler="simple",
             unet=H3_UNET, clip=H3_CLIP, vae=H3_VAE,
             prefix="PoseWearStudio/result", strip_background=False):
    """构造 H3-Image 的 ComfyUI API 工作流，返回 (prompt_dict, 输出节点 id)。

    refs: 按 <Picture 1> <Picture 2> ... 顺序排列的 ComfyUI 内部文件名，1~3 张。
    MiniMaxH3ImageConditioning 的 Autogrow 输入键是 images.image_<N>，
    与本机官方模板里实际连接参考图的键一致（image_1 是被编辑的图）。
    """
    refs = list(refs)
    if not 1 <= len(refs) <= 3:
        raise ValueError("参考图数量必须是 1~3 张，当前 %d 张" % len(refs))
    seed = random.randint(1, 2 ** 31 - 1) if seed is None else int(seed)

    p = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": unet, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": clip, "type": H3_CLIP_TYPE, "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }

    cond = {
        "clip": ["3", 0], "vae": ["4", 0],
        "prompt": prompt,
        "width": int(width), "height": int(height),
    }
    for i, name in enumerate(refs, 1):
        node_id = str(9 + i)  # 10 / 11 / 12，与 Qwen 侧保持一致
        p[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        cond["images.image_%d" % i] = [node_id, 0]

    # 双保持「去背」模式：VAEDecode 之后先抠图，输出节点仍是 32（SaveImage）。
    out_image = ["31", 0]
    if strip_background:
        # 统一先过 SplitImageWithAlpha：4 通道取 RGB，3 通道原样返回，
        # 避免 BiRefNet 收到 4 通道时报错 tensor a (4) vs tensor b (3)。
        p["41"] = {"class_type": "SplitImageWithAlpha",
                   "inputs": {"image": out_image}}
        p["40"] = {"class_type": "BiRefNetRMBG",
                   "inputs": rmbg_inputs(["41", 0])}
        out_image = ["40", 0]

    p.update({
        # 输出 0 = positive conditioning，输出 1 = 目标尺寸的空白 latent
        "20": {"class_type": "MiniMaxH3ImageConditioning", "inputs": cond},
        # H3 无 classifier-free guidance 且不支持负面提示词：
        # 官方模板用 zero-out 的 positive 作为 KSampler 的 negative。
        "33": {"class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["20", 0]}},
        "30": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": int(steps),
            "cfg": float(cfg), "sampler_name": sampler, "scheduler": scheduler,
            "positive": ["20", 0], "negative": ["33", 0],
            "latent_image": ["20", 1], "denoise": 1.0}},
        "31": {"class_type": "VAEDecode", "inputs": {
            "samples": ["30", 0], "vae": ["4", 0]}},
        "32": {"class_type": "SaveImage", "inputs": {
            "images": out_image, "filename_prefix": prefix}},
    })
    return p, "32"
