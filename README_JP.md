# ComfyUI-NS-Util

ComfyUI用のノード集です。


## ノードの内容
### Utility
あると便利なノードを用意
### Graphics Filter
特殊効果を画像に適用するフィルターです
### LLM(テスト実装中、近い内にwikiに使い方を記述します)
外部LLMサービスに接続してやりとりする機能群、ローカルLLMはOllamaに対応します

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
wikiの各ノードページに日本語と英語を併記しました。

[wiki](https://github.com/NakamuraShippo/ComfyUI-NS-Util/wiki)

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
