import math
import torch


class NS_DualEncoderTextEncode:
    """SDXLの2つのCLIPエンコーダに別々のプロンプトを入力し、
    content(被写体・構図)とstyle(画風・ライティング)の分離制御を実現する。
    content_blend_G で content 情報を G encoder にも流す比率を調整可能。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt_content": ("STRING", {
                    "multiline": True, "dynamicPrompts": True,
                    "tooltip": "Content prompt (subject, composition, color) -> CLIP ViT-L + blended to ViT-bigG",
                }),
                "prompt_style": ("STRING", {
                    "multiline": True, "dynamicPrompts": True,
                    "tooltip": "Style prompt (aesthetics, lighting, medium) -> OpenCLIP ViT-bigG",
                }),
                "content_blend_G": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "How much content prompt influences G encoder & pooled output. 0.0=G is pure style, 1.0=G is pure content. Pooled output uses accelerated curve for stronger content influence.",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "NS/Conditioning"

    def _tokenize_and_balance(self, clip, prompt_l, prompt_g):
        """L/G それぞれのプロンプトでトークナイズし、バッチ長を揃える"""
        tokens_g = clip.tokenize(prompt_g)
        tokens_l = clip.tokenize(prompt_l)
        tokens_g["l"] = tokens_l["l"]
        empty = clip.tokenize("")
        while len(tokens_g["l"]) < len(tokens_g["g"]):
            tokens_g["l"] += empty["l"]
        while len(tokens_g["l"]) > len(tokens_g["g"]):
            tokens_g["g"] += empty["g"]
        return tokens_g

    def encode(self, clip, prompt_content, prompt_style, content_blend_G):
        # Non-SDXL fallback
        tokens_test = clip.tokenize(prompt_content)
        if "g" not in tokens_test:
            print("[NS-DualEncoderTextEncode] Warning: Non-SDXL CLIP detected, using prompt_content only.")
            return (clip.encode_from_tokens_scheduled(tokens_test),)

        # Encoding A: G=style, L=content（分離エンコード）
        tokens_style = self._tokenize_and_balance(clip, prompt_content, prompt_style)
        cond_style = clip.encode_from_tokens_scheduled(tokens_style)

        # blend=0 なら分離エンコードそのまま
        if content_blend_G <= 0.0:
            return (cond_style,)

        # Encoding B: G=content, L=content（標準エンコード相当）
        tokens_content = self._tokenize_and_balance(clip, prompt_content, prompt_content)
        cond_content = clip.encode_from_tokens_scheduled(tokens_content)

        # blend=1 なら content エンコードそのまま
        if content_blend_G >= 1.0:
            return (cond_content,)

        # G 成分 (768:2048) と pooled_output をブレンド
        # pooled output は影響力が大きいため、二次曲線で content 寄りに加速
        # blend=0.3 → hidden=0.3, pooled=0.51
        # blend=0.5 → hidden=0.5, pooled=0.75
        # blend=0.7 → hidden=0.7, pooled=0.91
        blend = content_blend_G
        pooled_blend = 1.0 - (1.0 - blend) ** 2
        out = []
        for i, (tensor_s, dict_s) in enumerate(cond_style):
            if i < len(cond_content):
                tensor_c, dict_c = cond_content[i]
                blended_tensor = tensor_s.clone()
                # G hidden states: 線形ブレンド
                if blended_tensor.shape[-1] >= 2048:
                    blended_tensor[..., 768:2048] = (
                        (1 - blend) * tensor_s[..., 768:2048]
                        + blend * tensor_c[..., 768:2048]
                    )
                new_dict = dict_s.copy()
                # pooled_output: 二次曲線ブレンド（content 寄りに加速）
                if "pooled_output" in dict_s and "pooled_output" in dict_c:
                    new_dict["pooled_output"] = (
                        (1 - pooled_blend) * dict_s["pooled_output"]
                        + pooled_blend * dict_c["pooled_output"]
                    )
                out.append((blended_tensor, new_dict))
            else:
                out.append((tensor_s, dict_s.copy()))

        return (out,)


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
