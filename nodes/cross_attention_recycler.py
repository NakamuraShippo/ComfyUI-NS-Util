import torch
import torch.nn.functional as F


# --- Helper functions ---

def sigma_to_progress(sigma, model_sampling):
    """sigma 値を 0.0(開始) → 1.0(終了) の進行率に変換"""
    s = sigma.item() if isinstance(sigma, torch.Tensor) else sigma
    s_max = model_sampling.sigma_max.item()
    s_min = model_sampling.sigma_min.item()
    if s_max > s_min:
        progress = 1.0 - (s - s_min) / (s_max - s_min)
    else:
        progress = 0.0
    return max(0.0, min(1.0, progress))


def compute_attention(q, k, v, heads, dim_head, attn_precision=None):
    """Q, K, V からアテンション計算を行い (output, attn_map) を返す。

    Args:
        q: (batch, seq_len, inner_dim)
        k: (batch, ctx_len, inner_dim)
        v: (batch, ctx_len, inner_dim)
        heads: int
        dim_head: int
        attn_precision: optional dtype

    Returns:
        output: (batch, seq_len, inner_dim)
        attn_map: (batch, heads, seq_len, ctx_len)
    """
    b, seq_len, inner_dim = q.shape
    ctx_len = k.shape[1]

    q_h = q.reshape(b, seq_len, heads, dim_head).permute(0, 2, 1, 3)
    k_h = k.reshape(b, ctx_len, heads, dim_head).permute(0, 2, 1, 3)
    v_h = v.reshape(b, ctx_len, heads, dim_head).permute(0, 2, 1, 3)

    scale = dim_head ** -0.5

    if attn_precision is not None:
        q_h = q_h.to(attn_precision)
        k_h = k_h.to(attn_precision)

    attn_map = torch.softmax(q_h @ k_h.transpose(-2, -1) * scale, dim=-1)
    attn_map = attn_map.to(v_h.dtype)

    out = attn_map @ v_h  # (b, heads, seq_len, dim_head)
    out = out.permute(0, 2, 1, 3).reshape(b, seq_len, inner_dim)

    return out, attn_map


def optimized_attention_no_map(q, k, v, heads, dim_head, attn_precision=None):
    """アテンションマップを返さない高速版（収集/注入不要フェーズ用）"""
    b, seq_len, inner_dim = q.shape
    ctx_len = k.shape[1]

    q_h = q.reshape(b, seq_len, heads, dim_head).permute(0, 2, 1, 3)
    k_h = k.reshape(b, ctx_len, heads, dim_head).permute(0, 2, 1, 3)
    v_h = v.reshape(b, ctx_len, heads, dim_head).permute(0, 2, 1, 3)

    if attn_precision is not None:
        q_h = q_h.to(attn_precision)
        k_h = k_h.to(attn_precision)

    out = F.scaled_dot_product_attention(q_h, k_h, v_h)
    out = out.permute(0, 2, 1, 3).reshape(b, seq_len, inner_dim)
    return out


def _block_matches_target(block_key, target_layers):
    """ブロックキーが target_layers フィルタに一致するか判定"""
    if target_layers == "all":
        return True
    block_type = block_key[0]
    if target_layers == "mid_only":
        return block_type == "middle"
    elif target_layers == "up_only":
        return block_type == "output"
    elif target_layers == "down_and_mid":
        return block_type in ("input", "middle")
    return True


# --- SDXL / SD1.5 のブロック位置定義 ---

# 広めに登録（存在しないブロックは呼ばれないだけ）
_ALL_BLOCK_POSITIONS = []
for i in range(12):
    _ALL_BLOCK_POSITIONS.append(("input", i))
_ALL_BLOCK_POSITIONS.append(("middle", 0))
for i in range(12):
    _ALL_BLOCK_POSITIONS.append(("output", i))


# --- Node: CrossAttentionMapRecycler ---

class NS_CrossAttentionMapRecycler:
    """初期ステップのクロスアテンションマップを後半ステップに注入し、
    プロンプトの空間的追従性を安定化させる MODEL パッチ"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "collection_end": ("FLOAT", {
                    "default": 0.3, "min": 0.05, "max": 0.5, "step": 0.05,
                }),
                "injection_start": ("FLOAT", {
                    "default": 0.3, "min": 0.1, "max": 0.8, "step": 0.05,
                }),
                "injection_strength": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05,
                }),
                "decay": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                }),
                "target_layers": (["all", "mid_only", "up_only", "down_and_mid"],),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "NS/Attention"

    def apply(self, model, collection_end, injection_start, injection_strength,
              decay, target_layers):

        m = model.clone()
        model_sampling = m.get_model_object("model_sampling")

        # 収集されたアテンションマップを保持する共有辞書
        # key: layer_id 文字列
        # value: Tensor (heads, seq_len, ctx_len) — バッチ次元はcond側のみ平均
        stored_maps = {}
        collection_count = {}
        _last_progress = [1.0]  # 前回の進行率（リセット検出用）

        def make_replace_fn(block_key):
            """各ブロック用の attn2_replace コールバックを生成"""

            def replace_fn(q, k, v, extra_options):
                heads = extra_options["n_heads"]
                dim_head = extra_options["dim_head"]
                attn_precision = extra_options.get("attn_precision")
                block = extra_options.get("block")
                block_index = extra_options.get("block_index", 0)
                sigmas = extra_options.get("sigmas")
                cond_or_uncond = extra_options.get("cond_or_uncond", [0])

                # ブロック識別キー
                layer_id = f"{block}_{block_index}" if block else f"{block_key}_{block_index}"

                # このレイヤーが target_layers フィルタに一致するか
                effective_block = block if block else block_key
                if not _block_matches_target(effective_block, target_layers):
                    return optimized_attention_no_map(q, k, v, heads, dim_head, attn_precision)

                # 現在の進行率を取得
                if sigmas is not None and len(sigmas) > 0:
                    progress = sigma_to_progress(sigmas[0], model_sampling)
                else:
                    return optimized_attention_no_map(q, k, v, heads, dim_head, attn_precision)

                # 新規生成検出: 進行率が大きく戻ったらリセット
                if progress < _last_progress[0] - 0.5:
                    stored_maps.clear()
                    collection_count.clear()
                _last_progress[0] = progress

                # --- 収集フェーズ ---
                if progress <= collection_end:
                    out, attn_map = compute_attention(q, k, v, heads, dim_head, attn_precision)

                    # conditional 側のみ収集
                    # cond_or_uncond: [0]=cond, [1]=uncond
                    # バッチ内の cond 部分を特定
                    batch_size = q.shape[0]
                    n_conds = len(cond_or_uncond)
                    items_per_cond = batch_size // n_conds if n_conds > 0 else batch_size

                    cond_indices = []
                    for i, cu in enumerate(cond_or_uncond):
                        if cu == 0:  # conditional
                            start = i * items_per_cond
                            end = start + items_per_cond
                            cond_indices.extend(range(start, end))

                    if cond_indices:
                        # cond 側のマップを平均して保存 (heads, seq_len, ctx_len)
                        cond_map = attn_map[cond_indices].mean(dim=0).detach()

                        if layer_id not in stored_maps:
                            stored_maps[layer_id] = cond_map
                            collection_count[layer_id] = 1
                        else:
                            # EMA 平均化
                            alpha = 0.7
                            stored_maps[layer_id] = (
                                alpha * stored_maps[layer_id] + (1 - alpha) * cond_map
                            )
                            collection_count[layer_id] += 1

                    return out

                # --- 注入フェーズ ---
                if progress >= injection_start and layer_id in stored_maps:
                    out, attn_map = compute_attention(q, k, v, heads, dim_head, attn_precision)

                    # 減衰付き注入強度
                    if injection_start < 1.0:
                        phase_progress = (progress - injection_start) / (1.0 - injection_start)
                    else:
                        phase_progress = 0.0

                    if decay < 1.0 and phase_progress > 0:
                        effective_strength = injection_strength * (decay ** phase_progress)
                    else:
                        effective_strength = injection_strength

                    if effective_strength > 0.001:
                        ref_map = stored_maps[layer_id]

                        # ref_map (heads, seq_len, ctx_len) をバッチ次元に展開
                        # 空間解像度が一致するか確認
                        if ref_map.shape[-2] == attn_map.shape[-2] and ref_map.shape[-1] == attn_map.shape[-1]:
                            ref_expanded = ref_map.unsqueeze(0).expand_as(attn_map)
                            blended_map = (
                                (1 - effective_strength) * attn_map
                                + effective_strength * ref_expanded.to(attn_map.device, dtype=attn_map.dtype)
                            )

                            # blended_map で V を再計算
                            b, seq_len, inner_dim = q.shape
                            ctx_len = v.shape[1]
                            v_h = v.reshape(b, ctx_len, heads, dim_head).permute(0, 2, 1, 3)
                            blended_out = blended_map @ v_h
                            blended_out = blended_out.permute(0, 2, 1, 3).reshape(b, seq_len, inner_dim)
                            return blended_out

                    return out

                # --- ニュートラルフェーズ（収集終了〜注入開始の間）---
                return optimized_attention_no_map(q, k, v, heads, dim_head, attn_precision)

            return replace_fn

        # 全候補ブロックに replace パッチを登録
        for block_type, block_id in _ALL_BLOCK_POSITIONS:
            fn = make_replace_fn((block_type, block_id))
            m.set_model_attn2_replace(fn, block_type, block_id)

        return (m,)


NODE_CLASS_MAPPINGS = {
    "NS-CrossAttentionMapRecycler": NS_CrossAttentionMapRecycler,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-CrossAttentionMapRecycler": "NS Cross-Attention Map Recycler",
}
