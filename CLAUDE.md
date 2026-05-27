# CLAUDE.md — このプロジェクトでの作業手順

バトルアリーナ v2（Flask + SocketIO のオンライン対戦ゲーム）。よくやる作業をここにまとめる。

## デプロイ手順（毎回これ）

1. **push/デプロイの前に一度ユーザーに確認する**（作業中に追加要望が出るので、要求はまとめて一括で反映してからpushする）。ただしユーザーが「まとめてデプロイして」等で事前承認したらそのまま進めてよい。
2. コミット → push（pushでRenderが自動デプロイ）：
   - リポジトリ: GitHub `https://github.com/sayu182905/claude-game1`（ブランチ `main`）
   - commit時の著者: `user.name="sayu182905" user.email="yuuki.oka@jp.ricoh.com"`
   - **pushは PowerShell ツールで実行する**（Git Credential Manager がブラウザ認証を出すため。Bashツールからのpushは認証で失敗する）。コマンド例: `git push origin main`
3. **デプロイ（push）が完了したら `仕様書.md` を最新の仕様に更新する**。

## デプロイ先

- このゲームは基本 **同じRenderサイト**（上記リポジトリ）にデプロイする。
- **ゲームの種類が違えばデプロイ先も当然違う**。別ゲームのときはリポジトリ／Renderサービスを確認する。
- Render設定: Build `pip install -r requirements.txt` / Start `python app.py`。`app.py` は `$PORT` 対応済み。

## ローカルテスト

- 対戦に2人必要。`python app.py`（port 5000, background）→ ブラウザ2画面を自動で開く（確認不要）。同じルームIDで対戦開始。
- 描画/レイアウト確認は preview ツール（preview_start, preview_resize 等）。**`debug=False` でテンプレートがキャッシュされるため、index.html を編集したら preview_stop → preview_start で再起動**しないと反映されない。
- preview と `python app.py` は同じ port 5000 を使うので競合する。片方を止めてから使う。

## パラメータ調整・キャラ追加

- 数値調整: `app.py` の `CONFIG` 辞書に全集約。意味と現在値は `PARAMETERS.md`。
- キャラ追加: 手順は `CHARACTERS.md` のチェックリスト通り。
- 新パラメータ/必殺技を足したら `PARAMETERS.md` / `CHARACTERS.md` / `仕様書.md` も更新する。
