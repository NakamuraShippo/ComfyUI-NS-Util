import torch
import torch.nn.functional as F
import comfy.sample
import comfy.samplers
import comfy.utils


# --- Evaluation Metrics ---

def eval_frequency(x0_pred):
    """x0_pred の高周波成分エネルギー（ラプラシアンフィルタ）"""
    b, c, h, w = x0_pred.shape
    kernel = torch.tensor([[0, 1, 0], [1, -4, 1], [0, 1, 0]],
                          dtype=x0_pred.dtype, device=x0_pred.device)
    kernel = kernel.reshape(1, 1, 3, 3).expand(c, -1, -1, -1)
    high_freq = F.conv2d(x0_pred, kernel, padding=1, groups=c)
    return high_freq.abs().mean().item()


def eval_stability(x0_pred, prev_x0_pred):
    """ステップ間の x0_pred 変化量"""
    if prev_x0_pred is None:
        return float("inf")
    return (x0_pred - prev_x0_pred).abs().mean().item()


def determine_switch_step(freq_metrics, stab_metrics, min_step, max_step,
                          sensitivity, metric_type):
    """メトリクスの飽和を検出して最適切替ステップを返す"""
    if metric_type == "frequency":
        return _switch_by_frequency(freq_metrics, min_step, max_step, sensitivity)
    elif metric_type == "stability":
        return _switch_by_stability(stab_metrics, min_step, max_step, sensitivity)
    else:  # combined
        step_f = _switch_by_frequency(freq_metrics, min_step, max_step, sensitivity)
        step_s = _switch_by_stability(stab_metrics, min_step, max_step, sensitivity)
        return min(step_f, step_s)


def _switch_by_stability(metrics, min_step, max_step, sensitivity):
    """stability が飽和したステップを検出

    sensitivity が高い → 閾値が高い → 飽和を検出しやすい → 早く切替
    """
    valid_early = [m for m in metrics[:min_step] if m < float("inf") and m > 0]
    if not valid_early:
        return max_step

    baseline = sum(valid_early) / len(valid_early)
    # sensitivity=0 → ratio=0.2（ほぼ切替しない）
    # sensitivity=1 → ratio=0.8（すぐ切替）
    threshold_ratio = 0.2 + sensitivity * 0.6
    threshold = baseline * threshold_ratio

    for i in range(min_step, min(max_step, len(metrics))):
        if metrics[i] < float("inf") and metrics[i] < threshold:
            return i + 1
    return max_step


def _switch_by_frequency(metrics, min_step, max_step, sensitivity):
    """高周波エネルギー増加率が鈍化したステップを検出

    sensitivity が高い → 閾値が高い → 増加率低下を検出しやすい → 早く切替
    """
    if len(metrics) < min_step + 2:
        return max_step

    for i in range(min_step + 1, min(max_step, len(metrics))):
        if metrics[i - 1] > 1e-8:
            rate = abs(metrics[i] - metrics[i - 1]) / metrics[i - 1]
            # sensitivity=0 → threshold=0.02（ほぼ切替しない）
            # sensitivity=1 → threshold=0.2（すぐ切替）
            threshold = 0.02 + sensitivity * 0.18
            if rate < threshold:
                return i + 1
    return max_step


# --- Node: RefinerBoundaryOptimizer ---

class NS_RefinerBoundaryOptimizer:
    """Base→Refiner 切替タイミングを画像内容に応じて適応的に決定する"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_base": ("MODEL",),
                "model_refiner": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "positive_refiner": ("CONDITIONING",),
                "negative_refiner": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "steps": ("INT", {"default": 30, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 7.0, "min": 0.0, "max": 100.0, "step": 0.1,
                                  "round": 0.01}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
                "min_base_ratio": ("FLOAT", {
                    "default": 0.5, "min": 0.3, "max": 0.9, "step": 0.05,
                }),
                "max_base_ratio": ("FLOAT", {
                    "default": 0.9, "min": 0.5, "max": 1.0, "step": 0.05,
                }),
                "evaluation_metric": (["combined", "stability", "frequency"],),
                "sensitivity": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1,
                }),
                "denoise": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                }),
            }
        }

    RETURN_TYPES = ("LATENT", "INT")
    RETURN_NAMES = ("LATENT", "switch_step")
    FUNCTION = "execute"
    OUTPUT_NODE = True
    CATEGORY = "NS/Sampling"

    def execute(self, model_base, model_refiner, positive, negative,
                positive_refiner, negative_refiner, latent_image, seed, steps, cfg,
                sampler_name, scheduler, min_base_ratio, max_base_ratio,
                evaluation_metric, sensitivity, denoise):

        if min_base_ratio >= max_base_ratio:
            min_base_ratio = max_base_ratio - 0.05

        min_base_step = max(1, int(steps * min_base_ratio))
        max_base_step = min(steps, int(steps * max_base_ratio))

        latent_samples = latent_image["samples"].clone()
        latent_samples = comfy.sample.fix_empty_latent_channels(model_base, latent_samples)
        batch_inds = latent_image.get("batch_index")
        noise_mask = latent_image.get("noise_mask")
        noise = comfy.sample.prepare_noise(latent_samples, seed, batch_inds)

        pbar = comfy.utils.ProgressBar(steps)

        # --- Phase 1: 分析パス（Base を max_base_step まで実行しメトリクス収集）---
        analysis_model = model_base.clone()
        freq_metrics = []
        stab_metrics = []
        prev_denoised = [None]
        analysis_output = [None]

        def eval_post_cfg(args):
            denoised = args["denoised"]
            freq_metrics.append(eval_frequency(denoised))
            stab_metrics.append(eval_stability(denoised, prev_denoised[0]))
            prev_denoised[0] = denoised.detach().clone()
            return denoised

        analysis_model.set_model_sampler_post_cfg_function(eval_post_cfg)

        def analysis_callback(step, x0, x, total_steps):
            pbar.update_absolute(step + 1, steps)

        analysis_output[0] = comfy.sample.sample(
            analysis_model, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent_samples,
            denoise=denoise, disable_noise=False,
            start_step=None, last_step=max_base_step,
            force_full_denoise=False,
            noise_mask=noise_mask,
            callback=analysis_callback, seed=seed,
        )

        # メモリ解放
        prev_denoised[0] = None

        # --- 切替ステップ決定 ---
        switch_step = determine_switch_step(
            freq_metrics, stab_metrics, min_base_step, max_base_step,
            sensitivity, evaluation_metric,
        )

        print(f"[NS-RBO] switch_step={switch_step}/{steps} "
              f"(range={min_base_step}-{max_base_step}, metric={evaluation_metric}, "
              f"sensitivity={sensitivity})")

        # --- Phase 2: Base を switch_step まで実行 ---
        # switch_step == max_base_step の場合、Phase 1 の結果を再利用（同一 seed で決定論的に同一結果）
        if switch_step >= max_base_step:
            base_output = analysis_output[0]
        else:
            def base_callback(step, x0, x, total_steps):
                pbar.update_absolute(step + 1, steps)

            base_output = comfy.sample.sample(
                model_base, noise, steps, cfg, sampler_name, scheduler,
                positive, negative, latent_samples,
                denoise=denoise, disable_noise=False,
                start_step=None, last_step=switch_step,
                force_full_denoise=False,
                noise_mask=noise_mask,
                callback=base_callback, seed=seed,
            )

        analysis_output[0] = None  # メモリ解放

        # --- Phase 3: Refiner を switch_step から実行 ---
        if switch_step >= steps:
            final_samples = base_output
        else:
            base_output = comfy.sample.fix_empty_latent_channels(
                model_refiner, base_output
            )
            zero_noise = torch.zeros_like(base_output)

            def refiner_callback(step, x0, x, total_steps):
                pbar.update_absolute(switch_step + step + 1, steps)

            final_samples = comfy.sample.sample(
                model_refiner, zero_noise, steps, cfg, sampler_name, scheduler,
                positive_refiner, negative_refiner, base_output,
                denoise=denoise, disable_noise=True,
                start_step=switch_step, last_step=steps,
                force_full_denoise=True,
                noise_mask=noise_mask,
                callback=refiner_callback, seed=seed,
            )

        out = latent_image.copy()
        out["samples"] = final_samples
        return (out, switch_step)


NODE_CLASS_MAPPINGS = {
    "NS-RefinerBoundaryOptimizer": NS_RefinerBoundaryOptimizer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-RefinerBoundaryOptimizer": "NS Refiner Boundary Optimizer",
}
