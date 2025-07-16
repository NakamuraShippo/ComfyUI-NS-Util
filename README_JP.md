# ComfyUI-NS-Util

ComfyUI用のノード集です。


## ノードの内容

### NS-FlexPresetノード
int float stringのパラメーターをプリセットで一括管理するノード


https://github.com/user-attachments/assets/17fd46d7-cb1c-4e81-abe8-3d86d2feeb0b


## インストール

### [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager)をインストールしている場合
1. メインメニューのManager -> Install via Git URLの順にクリックする
2. ウインドウ上部に出てくるテキストボックスにURLを貼り付けてOKを押す  
    https://github.com/NakamuraShippo/ComfyUI-NS-Util
3. インストールが完了したら、ComfyUIを再起動

### [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager)をインストールしていない場合
1. ComfyUIのカスタムノードディレクトリに移動します。（通常は ComfyUI/custom_nodes/）
2. このリポジトリをクローンします。  
`git clone https://github.com/NakamuraShippo/ComfyUI-NS-Util`
3. ComfyUIを再起動します。
4. ComfyUI\venv\ScriptsでShift+右クリック→ターミナルで開く -> activate
  ```python
pip install pyyaml watchdog
  ```

## 使い方

### NS-FlexPresetノード

1. **ノードを追加**: ノードメニューの「NS」カテゴリから「NS Flex Preset」を探す

2. **YAMLプリセットの作成/編集**:
   - YAMLファイルは `ComfyUI/custom_nodes/ComfyUI-NS-Util/nodes/presets/` に保存されます
   - YAML構造の例：
   ```yaml
    positive prompt:
      type: string
      value: daytime sky nature dark blue galaxy bottle
    negative prompt:
      type: string
      value: text, watermark
    steps:
      type: int
      value: '22'
    cfg:
      type: float
      value: '4.55'
   ```

3. **ComfyUIでの使用**:
   - select_yamlからYAMLファイルを選択
   - select_presetを選択または入力
   - ノードは各値に対して型付き出力ポートを自動作成
   - これらの出力をワークフローの他のノードに接続

4. **UI内での値の編集**:
   - 「Add Value」をクリックして新しいプリセット値を作成
   - ノード上で直接値を変更
     - int floatの場合は入力ウィジェットがスライダーになっていて、クリックすると入力、左右にドラッグして値が調整できます
   - 値の削除方法
     - select_valueでキー名を選択 -> Delete [キー名]ボタンをクリック
     - Nameを重複させた場合も最後に入力した値を残して削除されます
   - すべての変更はYAMLファイルに自動保存
   - YAMLを直接編集してもOKです
     - ComfyUI起動中に編集した場合は、プリセットを切り替えるかブラウザの更新をしてください

## ノードインターフェース

- **select_yaml**: 利用可能なYAMLファイルから選択
- **select_title**: 選択したYAML内の既存プリセットタイトルから選択
- **input_title**: カスタムタイトルを入力（存在しない場合は新規作成）
- **値パネル**: 各プリセット値を表示・編集：
  - 名前（編集可能）
  - 型セレクター（int/float/string）
  - 値入力フィールド
- **追加/削除ボタン**: プリセット値の管理

## 必要要件

- ComfyUI (0.3以降を推奨、他のバージョンでは動作検証を行っていません)
- Pythonパッケージ（ComfyUIに自動的に含まれています）：
  - pyyaml
  - watchdog
  - aiohttp

## ロードマップ

これはNS-Utilコレクションの最初のノードです。今後の追加予定：
 - [ManySliders](https://github.com/NakamuraShippo/ComfyUI-NS-ManySliders)
   - プリセットで切り替えられるように作り直してから追加します

## コントリビューション

コントリビューションを歓迎します！プルリクエストの提出やバグ・機能リクエストのイシュー作成をお気軽にどうぞ。

## ライセンス

このプロジェクトはMITライセンスの下でライセンスされています - 詳細は[LICENSE](LICENSE)ファイルを参照してください。

## サポート

問題が発生した場合や質問がある場合：
- GitHubでイシューを作成
- [なかむらしっぽ lit.link](https://lit.link/nakamurashippo)

## 謝辞

- 素晴らしいプラットフォームを作成したComfyUIチームに感謝
- AIどうぶつ達にアイデアを戴きました、感謝感謝
