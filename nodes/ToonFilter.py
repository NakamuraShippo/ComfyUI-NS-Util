# toon_filter_node.py
import cv2
import numpy as np
import torch
from PIL import Image

class NS_ToonFilter:
    @classmethod
    
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "num_colors": ("INT", {"default": 8, "min": 2, "max": 64}),
                "bilateral_d": ("INT", {"default": 9, "min": 1, "max": 50}),
                "sigma_color": ("INT", {"default": 75, "min": 1, "max": 255}),
                "sigma_space": ("INT", {"default": 75, "min": 1, "max": 255}),
                "blur_ksize": ("INT", {"default": 7, "min": 1, "max": 64}),
                "block_size": ("INT", {"default": 9, "min": 3, "max": 51, "step": 2}),
                "c": ("INT", {"default": 2, "min": 0, "max": 20}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "apply_toon_filter"
    CATEGORY = "NS/Filter"

    def apply_toon_filter(self, image, num_colors, bilateral_d, sigma_color, sigma_space, blur_ksize, block_size, c):
        # テンソル → NumPy画像
        img = image[0].cpu().numpy()
        img = (img * 255).astype(np.uint8)

        # 1. 平滑化（ノイズ除去）
        img_color = cv2.bilateralFilter(img, d=bilateral_d, sigmaColor=sigma_color, sigmaSpace=sigma_space)

        # 2. 減色（K-meansクラスタリング）
        Z = img_color.reshape((-1, 3)).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers = cv2.kmeans(Z, num_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        centers = np.uint8(centers)
        quantized = centers[labels.flatten()]
        img_quant = quantized.reshape(img_color.shape)

        # 3. エッジ検出
        img_gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        img_blur = cv2.medianBlur(img_gray, blur_ksize)
        img_edge = cv2.adaptiveThreshold(img_blur, 255,
                                        cv2.ADAPTIVE_THRESH_MEAN_C,
                                        cv2.THRESH_BINARY,
                                        blockSize=block_size,
                                        C=c)

        # 4. エッジと減色画像を合成
        img_edge = cv2.cvtColor(img_edge, cv2.COLOR_GRAY2RGB)
        toon_image = cv2.bitwise_and(img_quant, img_edge)

        # NumPy → float32テンソル (0〜1)
        toon_image = toon_image.astype(np.float32) / 255.0
        toon_image = torch.from_numpy(toon_image).unsqueeze(0)  # (1, H, W, C)

        return (toon_image,)

NODE_CLASS_MAPPINGS = {
    "NS-ToonFilter": NS_ToonFilter
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-ToonFilter": "NS Toon Filter"
}
