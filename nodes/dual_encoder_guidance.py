import math
import torch


class NS_DualEncoderTextEncode:
    """SDXLの2つのCLIPエンコーダに別々のプロンプトを入力し、
    content(被写体・構図)とstyle(画風・ライティング)の分離制御を実現する"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt_content": ("STRING", {
                    "multiline": True, "dynamicPrompts": True,
                    "tooltip": "Content prompt (subject, composition, color) -> CLIP ViT-L",
                }),
                "prompt_style": ("STRING", {
                    "multiline": True, "dynamicPrompts": True,
                    "tooltip": "Style prompt (aesthetics, lighting, medium) -> OpenCLIP ViT-bigG",
                }),
                "pooled_source": (["style", "content"], {
                    "default": "style",
                    "tooltip": "Which prompt's pooled output to use. Style (ViT-bigG) is default",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "NS/Conditioning"

    def encode(self, clip, prompt_content, prompt_style, pooled_source):
        # Non-SDXL fallback: clip_g が存在しない場合は prompt_content のみ使用
        tokens_test = clip.tokenize(prompt_content)
        if "g" not in tokens_test:
            print("[NS-DualEncoderTextEncode] Warning: Non-SDXL CLIP detected, using prompt_content only.")
            return (clip.encode_from_tokens_scheduled(tokens_test),)

        # style -> clip_g (1280dim), content -> clip_l (768dim)
        tokens = clip.tokenize(prompt_style)
        tokens["l"] = tokens_test["l"]

        # Balance token batch lengths (same as CLIPTextEncodeSDXL)
        empty = clip.tokenize("")
        while len(tokens["l"]) < len(tokens["g"]):
            tokens["l"] += empty["l"]
        while len(tokens["l"]) > len(tokens["g"]):
            tokens["g"] += empty["g"]

        cond = clip.encode_from_tokens_scheduled(tokens)

        if pooled_source == "content":
            # content プロンプトで再エンコードし、pooled_output を差し替え
            tokens_content_only = clip.tokenize(prompt_content)
            tokens_content_only["g"] = tokens_content_only.get("g", tokens_test.get("g"))
            # Balance
            empty_c = clip.tokenize("")
            while len(tokens_content_only["l"]) < len(tokens_content_only["g"]):
                tokens_content_only["l"] += empty_c["l"]
            while len(tokens_content_only["l"]) > len(tokens_content_only["g"]):
                tokens_content_only["g"] += empty_c["g"]

            content_cond = clip.encode_from_tokens_scheduled(tokens_content_only)
            # pooled_output を差し替え
            out = []
            for i, (cond_tensor, cond_dict) in enumerate(cond):
                new_dict = cond_dict.copy()
                if i < len(content_cond) and "pooled_output" in content_cond[i][1]:
                    new_dict["pooled_output"] = content_cond[i][1]["pooled_output"]
                out.append((cond_tensor, new_dict))
            return (out,)

        return (cond,)


def _scale_lg_components(cond_tensor, scale_L, scale_G, normalize):
    """Conditioning tensor の L/G 成分をスケーリングする共通処理"""
    c = cond_tensor.clone()

    if c.shape[-1] < 2048:
        return c  # non-SDXL: skip

    c_L = c[..., :768]
    c_G = c[..., 768:2048]
    c_rest = c[..., 2048:] if c.shape[-1] > 2048 else None

    orig_norm = c[..., :2048].norm(dim=-1, keepdim=True).clamp(min=1e-8)

    c_L = c_L * scale_L
    c_G = c_G * scale_G

    if c_rest is not None:
        c = torch.cat([c_L, c_G, c_rest], dim=-1)
    else:
        c = torch.cat([c_L, c_G], dim=-1)

    if normalize:
        new_norm = c[..., :2048].norm(dim=-1, keepdim=True).clamp(min=1e-8)
        c[..., :2048] = c[..., :2048] * (orig_norm / new_norm)

    return c


class NS_DualEncoderGuidanceScale:
    """Conditioning の ViT-L / ViT-bigG 成分に異なるスケールを適用する。
    blend_factor で元の conditioning との滑らかなブレンドが可能。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "scale_L_content": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "CLIP ViT-L (content prompt) component scale",
                }),
                "scale_G_style": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "OpenCLIP ViT-bigG (style prompt) component scale",
                }),
                "blend_factor": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "0.0 = no change, 1.0 = full scale applied",
                }),
                "normalize": (["enable", "disable"], {
                    "default": "enable",
                    "tooltip": "Re-normalize after scaling to preserve overall magnitude",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "apply_scale"
    CATEGORY = "NS/Conditioning"

    def apply_scale(self, conditioning, scale_L_content, scale_G_style, blend_factor, normalize):
        if blend_factor == 0.0 or (scale_L_content == 1.0 and scale_G_style == 1.0):
            return (conditioning,)

        do_normalize = normalize == "enable"
        # Compute effective scales with blend
        eff_L = 1.0 + (scale_L_content - 1.0) * blend_factor
        eff_G = 1.0 + (scale_G_style - 1.0) * blend_factor

        out = []
        for cond_tensor, cond_dict in conditioning:
            c = _scale_lg_components(cond_tensor, eff_L, eff_G, do_normalize)
            out.append((c, cond_dict.copy()))

        return (out,)


class NS_DualEncoderSchedule:
    """L/G スケールをサンプリング進行に応じて動的に変化させる。
    ComfyUI の conditioning scheduling を利用して、
    ステップごとに異なる L/G バランスを適用する。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "start_scale_L_content": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "ViT-L (content prompt) scale at sampling start",
                }),
                "end_scale_L_content": ("FLOAT", {
                    "default": 1.3, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "ViT-L (content prompt) scale at sampling end",
                }),
                "start_scale_G_style": ("FLOAT", {
                    "default": 1.3, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "ViT-bigG (style prompt) scale at sampling start",
                }),
                "end_scale_G_style": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "ViT-bigG (style prompt) scale at sampling end",
                }),
                "segments": ("INT", {
                    "default": 5, "min": 2, "max": 20,
                    "tooltip": "Number of scheduling segments",
                }),
                "normalize": (["enable", "disable"], {
                    "default": "enable",
                }),
                "interpolation": (["linear", "cosine"],),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "schedule"
    CATEGORY = "NS/Conditioning"

    def schedule(self, conditioning, start_scale_L_content, end_scale_L_content,
                 start_scale_G_style, end_scale_G_style, segments, normalize, interpolation):
        do_normalize = normalize == "enable"
        out = []

        for seg_idx in range(segments):
            t = seg_idx / (segments - 1) if segments > 1 else 0.0
            if interpolation == "cosine":
                t = (1 - math.cos(t * math.pi)) / 2
            start_pct = seg_idx / segments
            end_pct = (seg_idx + 1) / segments

            scale_L = start_scale_L_content + (end_scale_L_content - start_scale_L_content) * t
            scale_G = start_scale_G_style + (end_scale_G_style - start_scale_G_style) * t

            for cond_tensor, cond_dict in conditioning:
                c = _scale_lg_components(cond_tensor, scale_L, scale_G, do_normalize)
                d = cond_dict.copy()
                d["start_percent"] = start_pct
                d["end_percent"] = end_pct
                out.append((c, d))

        return (out,)


NODE_CLASS_MAPPINGS = {
    "NS-DualEncoderTextEncode": NS_DualEncoderTextEncode,
    "NS-DualEncoderGuidanceScale": NS_DualEncoderGuidanceScale,
    "NS-DualEncoderSchedule": NS_DualEncoderSchedule,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-DualEncoderTextEncode": "NS Dual Encoder Text Encode",
    "NS-DualEncoderGuidanceScale": "NS Dual Encoder Guidance Scale",
    "NS-DualEncoderSchedule": "NS Dual Encoder Schedule",
}
