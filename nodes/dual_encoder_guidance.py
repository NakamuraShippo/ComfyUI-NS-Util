import math

import torch


# ============================================
# Base Text Encode (L+G 分離)
# ============================================

class NS_DualEncoderTextEncode:
    """SDXLの2つのCLIPエンコーダに別々のプロンプトを入力し、
    content(被写体・構図)とstyle(画風・ライティング)の分離制御を実現する。
    L encoder に content、G encoder に style を割り当てる。"""

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

    def encode(self, clip, prompt_content, prompt_style):
        # Non-SDXL fallback
        tokens_test = clip.tokenize(prompt_content)
        if "g" not in tokens_test:
            print("[NS-DualEncoderTextEncode] Warning: Non-SDXL CLIP detected, using prompt_content only.")
            return (clip.encode_from_tokens_scheduled(tokens_test),)

        # Encoding 1: L=content, G=style（分離エンコード → G hidden states を使用）
        tokens_style = self._tokenize_and_balance(clip, prompt_content, prompt_style)
        cond_style = clip.encode_from_tokens_scheduled(tokens_style)

        # Encoding 2: L=content, G=content（統一エンコード → pooled_output を使用）
        tokens_content = self._tokenize_and_balance(clip, prompt_content, prompt_content)
        cond_content = clip.encode_from_tokens_scheduled(tokens_content)

        # pooled_output を content 側から取得して差し替え
        # G hidden states は style、pooled_output は content という組み合わせ
        out = []
        for i, (tensor_s, dict_s) in enumerate(cond_style):
            new_dict = dict_s.copy()
            if i < len(cond_content):
                _, dict_c = cond_content[i]
                if "pooled_output" in dict_c:
                    new_dict["pooled_output"] = dict_c["pooled_output"]
            out.append((tensor_s, new_dict))

        return (out,)


# ============================================
# Refiner Text Encode (G 単体 + aesthetic_score)
# ============================================

class NS_RefinerTextEncode:
    """SDXL Refiner 用テキストエンコード。
    Refiner CLIP (OpenCLIP ViT-bigG 単体) に最適化。
    aesthetic_score を conditioning に付与する。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {
                    "multiline": True, "dynamicPrompts": True,
                    "tooltip": "Refiner prompt -> OpenCLIP ViT-bigG",
                }),
                "aesthetic_score": ("FLOAT", {
                    "default": 6.0, "min": 1.0, "max": 10.0, "step": 0.5,
                    "tooltip": "Aesthetic score for Refiner conditioning (higher = more aesthetic)",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "NS/Conditioning"

    def encode(self, clip, prompt, aesthetic_score):
        tokens = clip.tokenize(prompt)
        cond = clip.encode_from_tokens_scheduled(tokens)

        # aesthetic_score を各 conditioning エントリに付与
        out = []
        for tensor, cond_dict in cond:
            d = cond_dict.copy()
            d["aesthetic_score"] = aesthetic_score
            out.append((tensor, d))

        return (out,)


# ============================================
# 共通スケーリング処理
# ============================================

def _scale_base_components(cond_tensor, scale_L, scale_G, normalize):
    """Base conditioning tensor (2048d: L=768 + G=1280) の L/G 成分をスケーリング"""
    c = cond_tensor.clone()
    dim = c.shape[-1]

    if dim < 2048:
        print("[NS-DualEncoderGuidanceScale] Warning: Non-Base conditioning detected, skipping.")
        return c

    c_L = c[..., :768]
    c_G = c[..., 768:2048]
    c_rest = c[..., 2048:] if dim > 2048 else None

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


def _scale_refiner_components(cond_tensor, scale_G, normalize):
    """Refiner conditioning tensor (1280d: G のみ) の G 成分をスケーリング"""
    c = cond_tensor.clone()
    dim = c.shape[-1]

    if dim < 1280:
        print("[NS-RefinerGuidanceScale] Warning: Unexpected conditioning dimension, skipping.")
        return c

    orig_norm = c[..., :1280].norm(dim=-1, keepdim=True).clamp(min=1e-8)

    c[..., :1280] = c[..., :1280] * scale_G

    if normalize:
        new_norm = c[..., :1280].norm(dim=-1, keepdim=True).clamp(min=1e-8)
        c[..., :1280] = c[..., :1280] * (orig_norm / new_norm)

    return c


# ============================================
# Base Guidance Scale (L+G)
# ============================================

class NS_DualEncoderGuidanceScale:
    """Base conditioning の ViT-L / ViT-bigG 成分に異なるスケールを適用する。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "scale_L_content": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "CLIP ViT-L (content) scale",
                }),
                "scale_G_style": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "OpenCLIP ViT-bigG (style) scale",
                }),
                "normalize": (["disable", "enable"], {
                    "default": "disable",
                    "tooltip": "Re-normalize after scaling. L/G の比率のみ変化させたい場合に有効。",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "apply_scale"
    CATEGORY = "NS/Conditioning"

    def apply_scale(self, conditioning, scale_L_content, scale_G_style, normalize):
        if scale_L_content == 1.0 and scale_G_style == 1.0:
            return (conditioning,)

        do_normalize = normalize == "enable"
        out = []
        for cond_tensor, cond_dict in conditioning:
            c = _scale_base_components(cond_tensor, scale_L_content, scale_G_style, do_normalize)
            out.append((c, cond_dict.copy()))

        return (out,)


# ============================================
# Refiner Guidance Scale (G のみ)
# ============================================

class NS_RefinerGuidanceScale:
    """Refiner conditioning の ViT-bigG 成分にスケールを適用する。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "scale_G": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "OpenCLIP ViT-bigG scale",
                }),
                "normalize": (["disable", "enable"], {
                    "default": "disable",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "apply_scale"
    CATEGORY = "NS/Conditioning"

    def apply_scale(self, conditioning, scale_G, normalize):
        if scale_G == 1.0:
            return (conditioning,)

        do_normalize = normalize == "enable"
        out = []
        for cond_tensor, cond_dict in conditioning:
            c = _scale_refiner_components(cond_tensor, scale_G, do_normalize)
            out.append((c, cond_dict.copy()))

        return (out,)


# ============================================
# Base Schedule (L+G)
# ============================================

class NS_DualEncoderSchedule:
    """Base 用: L/G スケールをサンプリング進行に応じて動的に変化させる。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "start_scale_L_content": ("FLOAT", {
                    "default": 0.7, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-L (content) scale at schedule start",
                }),
                "end_scale_L_content": ("FLOAT", {
                    "default": 1.3, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-L (content) scale at schedule end",
                }),
                "start_scale_G_style": ("FLOAT", {
                    "default": 1.3, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-bigG (style) scale at schedule start",
                }),
                "end_scale_G_style": ("FLOAT", {
                    "default": 0.7, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-bigG (style) scale at schedule end",
                }),
                "schedule_start": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Schedule range start (0.0=sampling start)",
                }),
                "schedule_end": ("FLOAT", {
                    "default": 0.8, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Schedule range end. Base は通常 0.8 まで。",
                }),
                "segments": ("INT", {
                    "default": 5, "min": 2, "max": 20,
                    "tooltip": "Number of scheduling segments",
                }),
                "normalize": (["disable", "enable"], {
                    "default": "disable",
                }),
                "interpolation": (["linear", "cosine"],),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "schedule"
    CATEGORY = "NS/Conditioning"

    def schedule(self, conditioning, start_scale_L_content, end_scale_L_content,
                 start_scale_G_style, end_scale_G_style, schedule_start, schedule_end,
                 segments, normalize, interpolation):
        do_normalize = normalize == "enable"

        if schedule_start >= schedule_end:
            return (conditioning,)

        range_span = schedule_end - schedule_start
        out = []

        for seg_idx in range(segments):
            t = seg_idx / (segments - 1) if segments > 1 else 0.0
            if interpolation == "cosine":
                t = (1 - math.cos(t * math.pi)) / 2

            start_pct = schedule_start + (seg_idx / segments) * range_span
            end_pct = schedule_start + ((seg_idx + 1) / segments) * range_span

            scale_L = start_scale_L_content + (end_scale_L_content - start_scale_L_content) * t
            scale_G = start_scale_G_style + (end_scale_G_style - start_scale_G_style) * t

            for cond_tensor, cond_dict in conditioning:
                c = _scale_base_components(cond_tensor, scale_L, scale_G, do_normalize)
                d = cond_dict.copy()
                d["start_percent"] = start_pct
                d["end_percent"] = end_pct
                out.append((c, d))

        return (out,)


# ============================================
# Refiner Schedule (G のみ)
# ============================================

class NS_RefinerSchedule:
    """Refiner 用: G スケールをサンプリング進行に応じて動的に変化させる。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "start_scale_G": ("FLOAT", {
                    "default": 1.2, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-bigG scale at schedule start",
                }),
                "end_scale_G": ("FLOAT", {
                    "default": 0.8, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "ViT-bigG scale at schedule end",
                }),
                "schedule_start": ("FLOAT", {
                    "default": 0.8, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Schedule range start. Refiner は通常 0.8 から。",
                }),
                "schedule_end": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Schedule range end (1.0=sampling end)",
                }),
                "segments": ("INT", {
                    "default": 3, "min": 2, "max": 20,
                    "tooltip": "Number of scheduling segments",
                }),
                "normalize": (["disable", "enable"], {
                    "default": "disable",
                }),
                "interpolation": (["linear", "cosine"],),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "schedule"
    CATEGORY = "NS/Conditioning"

    def schedule(self, conditioning, start_scale_G, end_scale_G,
                 schedule_start, schedule_end, segments, normalize, interpolation):
        do_normalize = normalize == "enable"

        if schedule_start >= schedule_end:
            return (conditioning,)

        range_span = schedule_end - schedule_start
        out = []

        for seg_idx in range(segments):
            t = seg_idx / (segments - 1) if segments > 1 else 0.0
            if interpolation == "cosine":
                t = (1 - math.cos(t * math.pi)) / 2

            start_pct = schedule_start + (seg_idx / segments) * range_span
            end_pct = schedule_start + ((seg_idx + 1) / segments) * range_span

            scale_G = start_scale_G + (end_scale_G - start_scale_G) * t

            for cond_tensor, cond_dict in conditioning:
                c = _scale_refiner_components(cond_tensor, scale_G, do_normalize)
                d = cond_dict.copy()
                d["start_percent"] = start_pct
                d["end_percent"] = end_pct
                out.append((c, d))

        return (out,)


# ============================================
# Node Registration
# ============================================

NODE_CLASS_MAPPINGS = {
    "NS-DualEncoderTextEncode": NS_DualEncoderTextEncode,
    "NS-RefinerTextEncode": NS_RefinerTextEncode,
    "NS-DualEncoderGuidanceScale": NS_DualEncoderGuidanceScale,
    "NS-RefinerGuidanceScale": NS_RefinerGuidanceScale,
    "NS-DualEncoderSchedule": NS_DualEncoderSchedule,
    "NS-RefinerSchedule": NS_RefinerSchedule,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-DualEncoderTextEncode": "NS Dual Encoder Text Encode",
    "NS-RefinerTextEncode": "NS Refiner Text Encode",
    "NS-DualEncoderGuidanceScale": "NS Dual Encoder Guidance Scale",
    "NS-RefinerGuidanceScale": "NS Refiner Guidance Scale",
    "NS-DualEncoderSchedule": "NS Dual Encoder Schedule",
    "NS-RefinerSchedule": "NS Refiner Schedule",
}
