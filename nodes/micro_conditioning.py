import math
import torch


# --- Helper functions ---

def is_sdxl_model(model):
    """SDXL モデルか判定（inner_model に embedder 属性があるか）"""
    inner = getattr(model, "inner_model", None)
    if inner is None:
        inner = getattr(model, "model", None)
    return inner is not None and hasattr(inner, "embedder")


def get_embedder(model):
    """モデルから Timestep embedder を取得"""
    inner = getattr(model, "inner_model", None)
    if inner is None:
        inner = getattr(model, "model", None)
    return getattr(inner, "embedder", None)


def rebuild_y_with_micro_cond(embedder, y_original, h, w, crop_h, crop_w, target_h=None, target_w=None):
    """y ベクトルの micro-conditioning 部分を再構築する。

    SDXL の y ベクトル構造 (各 Fourier embedding は 256 次元):
      [clip_pooled(1280) | h(256) | w(256) | crop_h(256) | crop_w(256) | target_h(256) | target_w(256)]
    target_h/target_w が None の場合、元のベクトルの該当部分を保持する。
    """
    device = y_original.device
    dtype = y_original.dtype
    batch = y_original.shape[0]
    pooled = y_original[:, :1280]

    embeds = []
    for val in [h, w, crop_h, crop_w]:
        embeds.append(embedder(torch.Tensor([val]).to(device)))

    new_part = torch.flatten(torch.cat(embeds)).unsqueeze(0).repeat(batch, 1)
    new_part = new_part.to(device=device, dtype=dtype)

    if target_h is not None and target_w is not None:
        target_embeds = []
        for val in [target_h, target_w]:
            target_embeds.append(embedder(torch.Tensor([val]).to(device)))
        target_part = torch.flatten(torch.cat(target_embeds)).unsqueeze(0).repeat(batch, 1)
        target_part = target_part.to(device=device, dtype=dtype)
    else:
        target_part = y_original[:, 2304:]

    return torch.cat((pooled, new_part, target_part), dim=1)


def interpolate_value(start, end, progress, mode, switch_step=0.5):
    """進行率に基づく補間"""
    if mode == "linear":
        return start + (end - start) * progress
    elif mode == "cosine":
        return start + (end - start) * (1 - math.cos(progress * math.pi)) / 2
    elif mode == "step":
        return start if progress < switch_step else end
    return start


# --- Node 3: MicroConditioningOverride ---

class NS_MicroConditioningOverride:
    """既存 Conditioning の Micro-Conditioning 値を手動で上書きする"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "original_width": ("INT", {"default": 1024, "min": 0, "max": 8192, "step": 64}),
                "original_height": ("INT", {"default": 1024, "min": 0, "max": 8192, "step": 64}),
                "crop_left": ("INT", {"default": 0, "min": 0, "max": 4096}),
                "crop_top": ("INT", {"default": 0, "min": 0, "max": 4096}),
                "target_width": ("INT", {"default": 1024, "min": 0, "max": 8192, "step": 64}),
                "target_height": ("INT", {"default": 1024, "min": 0, "max": 8192, "step": 64}),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "override"
    CATEGORY = "NS/Conditioning"

    def override(self, conditioning, original_width, original_height,
                 crop_left, crop_top, target_width, target_height):
        out = []
        for cond_tensor, cond_dict in conditioning:
            new_dict = cond_dict.copy()
            new_dict["width"] = original_width
            new_dict["height"] = original_height
            new_dict["crop_w"] = crop_left
            new_dict["crop_h"] = crop_top
            new_dict["target_width"] = target_width
            new_dict["target_height"] = target_height
            out.append([cond_tensor, new_dict])
        return (out,)


# --- Node 1: MicroConditioningSchedule ---

class NS_MicroConditioningSchedule:
    """サンプリング中に Micro-Conditioning を動的に変化させる MODEL パッチ"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "start_original_size": ("INT", {"default": 4096, "min": 64, "max": 8192, "step": 64}),
                "end_original_size": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
                "start_crop_offset": ("INT", {"default": 0, "min": 0, "max": 2048}),
                "end_crop_offset": ("INT", {"default": 0, "min": 0, "max": 2048}),
                "interpolation": (["linear", "cosine", "step"],),
                "switch_step": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "NS/Conditioning"

    def apply(self, model, start_original_size, end_original_size,
              start_crop_offset, end_crop_offset, interpolation, switch_step):

        if not is_sdxl_model(model):
            print("[NS-MicroConditioningSchedule] Warning: Non-SDXL model detected, returning unpatched model.")
            return (model,)

        m = model.clone()
        embedder = get_embedder(m)
        model_sampling = m.get_model_object("model_sampling")

        def unet_wrapper(apply_model_fn, args):
            c = args["c"]
            timestep = args["timestep"]

            if "y" not in c:
                return apply_model_fn(args["input"], timestep, **c)

            # sigma → progress (0.0=start, 1.0=end)
            sigma = timestep[0].item()
            sigma_max = model_sampling.sigma_max.item()
            sigma_min = model_sampling.sigma_min.item()
            if sigma_max > sigma_min:
                progress = 1.0 - (sigma - sigma_min) / (sigma_max - sigma_min)
            else:
                progress = 0.0
            progress = max(0.0, min(1.0, progress))

            size = interpolate_value(start_original_size, end_original_size, progress, interpolation, switch_step)
            crop = interpolate_value(start_crop_offset, end_crop_offset, progress, interpolation, switch_step)

            y = c["y"]
            new_y = rebuild_y_with_micro_cond(
                embedder, y,
                h=size, w=size,
                crop_h=crop, crop_w=crop,
            )
            c = c.copy()
            c["y"] = new_y

            return apply_model_fn(args["input"], timestep, **c)

        m.set_model_unet_function_wrapper(unet_wrapper)
        return (m,)


# --- Node 2: MicroConditioningGuidance ---

def _modify_cond_y(cond_list, embedder, size):
    """conditioning リスト内の model_conds['y'] を指定サイズの micro-conditioning で差し替えたコピーを返す"""
    import comfy.conds
    out = []
    for item in cond_list:
        new_item = item.copy()
        mc = new_item.get("model_conds", {}).copy()
        if "y" in mc:
            y_tensor = mc["y"].cond
            new_y = rebuild_y_with_micro_cond(
                embedder, y_tensor,
                h=size, w=size,
                crop_h=0, crop_w=0,
            )
            mc["y"] = comfy.conds.CONDRegular(new_y)
        new_item["model_conds"] = mc
        out.append(new_item)
    return out


class NS_MicroConditioningGuidance:
    """高解像度/低解像度条件の予測差分をガイダンスとして加算する MODEL パッチ"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "high_res_size": ("INT", {"default": 2048, "min": 64, "max": 8192, "step": 64}),
                "low_res_size": ("INT", {"default": 256, "min": 64, "max": 8192, "step": 64}),
                "mcg_scale": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                "start_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "end_percent": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "NS/Conditioning"

    def apply(self, model, high_res_size, low_res_size, mcg_scale, start_percent, end_percent):

        if not is_sdxl_model(model):
            print("[NS-MicroConditioningGuidance] Warning: Non-SDXL model detected, returning unpatched model.")
            return (model,)

        # high > low を保証
        if high_res_size <= low_res_size:
            print("[NS-MicroConditioningGuidance] Warning: high_res_size <= low_res_size, swapping values.")
            high_res_size, low_res_size = low_res_size, high_res_size

        m = model.clone()
        embedder = get_embedder(m)
        model_sampling = m.get_model_object("model_sampling")

        def post_cfg_fn(args):
            denoised = args["denoised"]
            sigma = args["sigma"]
            cond = args["cond"]
            x = args["input"]
            inner_model = args["model"]
            model_options = args["model_options"]

            if mcg_scale == 0.0:
                return denoised

            # sigma → progress
            s = sigma[0].item()
            s_max = model_sampling.sigma_max.item()
            s_min = model_sampling.sigma_min.item()
            if s_max > s_min:
                progress = 1.0 - (s - s_min) / (s_max - s_min)
            else:
                progress = 0.0
            progress = max(0.0, min(1.0, progress))

            if progress < start_percent or progress > end_percent:
                return denoised

            if cond is None:
                return denoised

            from comfy.samplers import calc_cond_batch

            high_cond = _modify_cond_y(cond, embedder, high_res_size)
            low_cond = _modify_cond_y(cond, embedder, low_res_size)

            high_pred = calc_cond_batch(inner_model, [high_cond, None], x, sigma, model_options)[0]
            low_pred = calc_cond_batch(inner_model, [low_cond, None], x, sigma, model_options)[0]

            mcg_direction = high_pred - low_pred

            # denoised の信号強度に対して相対的にスケーリング
            denoised_std = denoised.std()
            mcg_std = mcg_direction.std()
            if mcg_std > 1e-8:
                mcg_normalized = mcg_direction * (denoised_std / mcg_std)
            else:
                mcg_normalized = mcg_direction

            return denoised + mcg_scale * mcg_normalized

        m.set_model_sampler_post_cfg_function(post_cfg_fn, disable_cfg1_optimization=True)
        return (m,)


NODE_CLASS_MAPPINGS = {
    "NS-MicroConditioningOverride": NS_MicroConditioningOverride,
    "NS-MicroConditioningSchedule": NS_MicroConditioningSchedule,
    "NS-MicroConditioningGuidance": NS_MicroConditioningGuidance,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-MicroConditioningOverride": "NS Micro Conditioning Override",
    "NS-MicroConditioningSchedule": "NS Micro Conditioning Schedule",
    "NS-MicroConditioningGuidance": "NS Micro Conditioning Guidance",
}
