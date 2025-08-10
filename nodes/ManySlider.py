import yaml
import os
from pathlib import Path

class NS_ManySliders:
    """NS-ManySliders Node for ComfyUI"""
    
    @classmethod
    def INPUT_TYPES(cls):
        # 設定ファイルのパスを nodes/ManySliders/settings.yaml に変更
        settings_dir = Path(__file__).parent / "ManySliders"
        settings_path = settings_dir / "settings.yaml"
        
        # ディレクトリが存在しない場合は作成
        settings_dir.mkdir(exist_ok=True)
        
        # 設定ファイルが存在しない場合はデフォルトを作成
        if not settings_path.exists():
            default_settings = {
                'sliders': {
                    'count': 15,
                    'min_value': -1.0,
                    'max_value': 1.0,
                    'default_value': 0.0,
                    'step': 0.1
                }
            }
            with open(settings_path, 'w', encoding='utf-8') as f:
                yaml.dump(default_settings, f, default_flow_style=False)
            settings = default_settings
        else:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = yaml.safe_load(f)
        
        # エラーハンドリング: 設定が不正な場合のデフォルト値
        if not settings or 'sliders' not in settings:
            settings = {
                'sliders': {
                    'count': 15,
                    'min_value': -1.0,
                    'max_value': 1.0,
                    'default_value': 0.0,
                    'step': 0.1
                }
            }
        
        sliders_config = settings['sliders']
        step = sliders_config.get('step', 0.1)
        count = sliders_config.get('count', 15)
        default_value = sliders_config.get('default_value', 0.0)
        min_value = sliders_config.get('min_value', -1.0)
        max_value = sliders_config.get('max_value', 1.0)
        
        required = {
            "slider_count": ("INT", {
                "default": count,
                "min": 1,
                "max": count,
                "display": "number"
            })
        }
        
        # 各スライダーをrequiredとして定義
        for i in range(count):
            required[f"value_{i}"] = ("FLOAT", {
                "default": default_value,
                "min": min_value,
                "max": max_value,
                "step": step,
                "display": "slider"
            })
        
        return {"required": required}
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("values",)
    FUNCTION = "run"
    CATEGORY = "NS/Utility"  # 他のNSノードと同じカテゴリに統一
    
    def run(self, slider_count, **kwargs):
        """Main execution function"""
        # 設定ファイルのパス
        settings_path = Path(__file__).parent / "ManySliders" / "settings.yaml"
        
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = yaml.safe_load(f)
        except Exception as e:
            print(f"Error reading settings: {e}")
            # エラー時のデフォルト設定
            settings = {
                'sliders': {
                    'count': 15,
                    'min_value': -1.0,
                    'max_value': 1.0,
                    'default_value': 0.0,
                    'step': 0.1
                }
            }
        
        sliders_config = settings.get('sliders', {})
        max_sliders = sliders_config.get('count', 15)
        min_value = sliders_config.get('min_value', -1.0)
        max_value = sliders_config.get('max_value', 1.0)
        default_value = sliders_config.get('default_value', 0.0)
        
        # 有効なスライダー数を決定
        effective_count = min(slider_count, max_sliders)
        values = []
        
        for i in range(effective_count):
            value_key = f'value_{i}'
            value = kwargs.get(value_key, default_value)
            # 値を範囲内にクランプ
            value = max(min(float(value), max_value), min_value)
            values.append(str(value))
        
        # カンマ区切りの文字列として返す
        return (",".join(values),)
    
    @classmethod
    def VALIDATE_INPUTS(cls, slider_count, **kwargs):
        """Validate inputs"""
        try:
            settings_path = Path(__file__).parent / "ManySliders" / "settings.yaml"
            
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = yaml.safe_load(f)
            else:
                # 設定ファイルがない場合でも動作を継続
                return True
            
            if not settings or 'sliders' not in settings:
                return True
            
            sliders_config = settings['sliders']
            max_count = sliders_config.get('count', 15)
            min_value = sliders_config.get('min_value', -1.0)
            max_value = sliders_config.get('max_value', 1.0)
            
            # スライダー数の検証
            if not (1 <= slider_count <= max_count):
                return False
            
            # 各スライダー値の検証
            for i in range(slider_count):
                value_key = f'value_{i}'
                if value_key in kwargs:
                    value = kwargs[value_key]
                    if not (min_value <= value <= max_value):
                        return False
            
            return True
            
        except Exception as e:
            print(f"Validation error: {e}")
            # エラーが発生しても動作を継続
            return True
    
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """Check if the node needs to be re-executed"""
        # 設定ファイルの更新を検知
        try:
            settings_path = Path(__file__).parent / "ManySliders" / "settings.yaml"
            if settings_path.exists():
                # ファイルの更新時刻を使用して変更を検知
                mtime = os.path.getmtime(settings_path)
                return str(mtime)
        except:
            pass
        
        # デフォルトでは常に実行
        return float("NaN")


# ComfyUIへの登録情報
NODE_CLASS_MAPPINGS = {
    "NS-ManySliders": NS_ManySliders
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-ManySliders": "NS Many Sliders"
}