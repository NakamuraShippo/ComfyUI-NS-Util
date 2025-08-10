import torch
import numpy as np
from PIL import Image
import cv2

class AlbedoMapGenerator:
    """
    高品質なアルベドマップを生成するComfyUIカスタムノード
    Height、Normal、AOマップを参考にして、入力画像からアルベドマップを生成
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                # アルベドマップ生成の基本設定
                "brightness": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.1,
                    "max": 2.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "contrast": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.1,
                    "max": 2.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "saturation": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                # ディテール除去設定
                "remove_shadows": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "remove_highlights": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                # カラー補正
                "color_temperature": ("FLOAT", {
                    "default": 0.0,
                    "min": -1.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "tint": ("FLOAT", {
                    "default": 0.0,
                    "min": -1.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                # 処理方法
                "processing_mode": (["Standard", "Advanced", "AI-Enhanced"],),
                # デノイズ
                "denoise_strength": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
            },
            "optional": {
                "height_map": ("IMAGE",),
                "normal_map": ("IMAGE",),
                "ao_map": ("IMAGE",),
                # マップの影響度
                "height_influence": ("FLOAT", {
                    "default": 0.3,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "normal_influence": ("FLOAT", {
                    "default": 0.3,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
                "ao_influence": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "display": "slider"
                }),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("albedo_map",)
    FUNCTION = "generate_albedo"
    CATEGORY = "NS/Filter"
    
    def tensor_to_np(self, tensor):
        """テンソルをnumpy配列に変換"""
        if len(tensor.shape) == 4:
            tensor = tensor.squeeze(0)
        return (tensor.cpu().numpy() * 255).astype(np.uint8)
    
    def np_to_tensor(self, np_array):
        """numpy配列をテンソルに変換"""
        tensor = torch.from_numpy(np_array.astype(np.float32) / 255.0)
        return tensor.unsqueeze(0)
    
    def adjust_brightness_contrast(self, image, brightness, contrast):
        """明度とコントラストを調整"""
        # 明度調整
        image = image * brightness
        # コントラスト調整
        mean = np.mean(image)
        image = (image - mean) * contrast + mean
        return np.clip(image, 0, 255).astype(np.uint8)
    
    def adjust_saturation(self, image, saturation):
        """彩度を調整"""
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:,:,1] = hsv[:,:,1] * saturation
        hsv[:,:,1] = np.clip(hsv[:,:,1], 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    
    def remove_lighting(self, image, shadow_strength, highlight_strength):
        """照明効果を除去してフラットなアルベドを生成"""
        # ガウシアンブラーで大まかな照明成分を抽出
        blurred = cv2.GaussianBlur(image, (51, 51), 0)
        
        # グレースケールで明暗を検出
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        
        # 影の除去
        if shadow_strength > 0:
            shadow_mask = (gray < np.mean(gray)).astype(np.float32)
            shadow_mask = cv2.GaussianBlur(shadow_mask, (21, 21), 0)
            for i in range(3):
                image[:,:,i] = image[:,:,i] * (1 - shadow_mask * shadow_strength) + \
                               blurred[:,:,i] * shadow_mask * shadow_strength
        
        # ハイライトの除去
        if highlight_strength > 0:
            highlight_mask = (gray > np.mean(gray) * 1.3).astype(np.float32)
            highlight_mask = cv2.GaussianBlur(highlight_mask, (21, 21), 0)
            for i in range(3):
                image[:,:,i] = image[:,:,i] * (1 - highlight_mask * highlight_strength) + \
                               blurred[:,:,i] * highlight_mask * highlight_strength
        
        return np.clip(image, 0, 255).astype(np.uint8)
    
    def apply_color_correction(self, image, temperature, tint):
        """色温度と色合いを調整"""
        result = image.astype(np.float32)
        
        # 色温度調整（暖色/寒色）
        if temperature != 0:
            result[:,:,0] += temperature * 20  # Red
            result[:,:,2] -= temperature * 20  # Blue
        
        # 色合い調整（緑/マゼンタ）
        if tint != 0:
            result[:,:,1] += tint * 20  # Green
            result[:,:,0] -= tint * 10  # Red
            result[:,:,2] -= tint * 10  # Blue
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def apply_denoise(self, image, strength):
        """ノイズ除去"""
        if strength <= 0:
            return image
        
        # Non-local Means Denoisingを使用
        h = 10 * strength
        return cv2.fastNlMeansDenoisingColored(image, None, h, h, 7, 21)
    
    def process_with_maps(self, albedo, height_map, normal_map, ao_map, 
                         height_inf, normal_inf, ao_inf):
        """Height、Normal、AOマップを使用してアルベドを調整"""
        result = albedo.astype(np.float32)
        
        # AOマップの影響を適用
        if ao_map is not None and ao_inf > 0:
            ao_gray = cv2.cvtColor(ao_map, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
            # AOの暗い部分は汚れや影ではなく、ジオメトリによる遮蔽として扱う
            # アルベドから陰影成分を除去
            ao_factor = 1.0 - (1.0 - ao_gray) * ao_inf * 0.5
            for i in range(3):
                result[:,:,i] = result[:,:,i] / np.maximum(ao_factor, 0.5)
        
        # Normalマップの影響を適用
        if normal_map is not None and normal_inf > 0:
            # Normalマップから表面の向きを推定し、照明の影響を補正
            normal_gray = cv2.cvtColor(normal_map, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
            normal_factor = (normal_gray - 0.5) * 2.0 * normal_inf
            
            # 法線の向きによる明度変化を補正
            brightness_correction = 1.0 - normal_factor * 0.2
            result = result * brightness_correction[:,:,np.newaxis]
        
        # Heightマップの影響を適用
        if height_map is not None and height_inf > 0:
            height_gray = cv2.cvtColor(height_map, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
            
            # 高さの変化から細かいディテールを抽出
            height_detail = cv2.Laplacian(height_gray, cv2.CV_32F)
            height_detail = np.abs(height_detail) * height_inf
            
            # ディテールに基づいて色のバリエーションを減らす
            blur_size = int(5 + height_inf * 10)
            if blur_size % 2 == 0:
                blur_size += 1
            smoothed = cv2.GaussianBlur(result, (blur_size, blur_size), 0)
            
            # ディテールが強い部分は平滑化された色を使用
            for i in range(3):
                result[:,:,i] = result[:,:,i] * (1 - height_detail) + \
                                smoothed[:,:,i] * height_detail
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def advanced_processing(self, image):
        """高度な処理モード"""
        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        lab[:,:,0] = clahe.apply(lab[:,:,0])
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        
        # エッジ保持フィルタ
        result = cv2.bilateralFilter(result, 9, 75, 75)
        
        return result
    
    def generate_albedo(self, image, brightness, contrast, saturation,
                       remove_shadows, remove_highlights,
                       color_temperature, tint, processing_mode,
                       denoise_strength,
                       height_map=None, normal_map=None, ao_map=None,
                       height_influence=0.3, normal_influence=0.3, 
                       ao_influence=0.5):
        """
        アルベドマップを生成するメイン関数
        """
        # 入力画像をnumpy配列に変換
        img_np = self.tensor_to_np(image)
        
        # オプションのマップをnumpy配列に変換
        height_np = self.tensor_to_np(height_map) if height_map is not None else None
        normal_np = self.tensor_to_np(normal_map) if normal_map is not None else None
        ao_np = self.tensor_to_np(ao_map) if ao_map is not None else None
        
        # 基本的な画像処理
        result = img_np.copy()
        
        # 照明効果の除去
        result = self.remove_lighting(result, remove_shadows, remove_highlights)
        
        # マップを使用した処理
        if height_np is not None or normal_np is not None or ao_np is not None:
            result = self.process_with_maps(result, height_np, normal_np, ao_np,
                                           height_influence, normal_influence, 
                                           ao_influence)
        
        # 明度とコントラストの調整
        result = self.adjust_brightness_contrast(result, brightness, contrast)
        
        # 彩度の調整
        result = self.adjust_saturation(result, saturation)
        
        # 色補正
        result = self.apply_color_correction(result, color_temperature, tint)
        
        # 処理モードに応じた追加処理
        if processing_mode == "Advanced":
            result = self.advanced_processing(result)
        elif processing_mode == "AI-Enhanced":
            # AI強化モード（将来的な実装用プレースホルダー）
            result = self.advanced_processing(result)
            # ここに機械学習ベースの処理を追加可能
        
        # デノイズ
        if denoise_strength > 0:
            result = self.apply_denoise(result, denoise_strength)
        
        # テンソルに変換して返す
        return (self.np_to_tensor(result),)

# ComfyUIに登録するためのマッピング
NODE_CLASS_MAPPINGS = {
    "AlbedoMapGenerator": AlbedoMapGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AlbedoMapGenerator": "NS-Albedo Map Filter"
}