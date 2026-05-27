# バトルアリーナ v2 - セットアップ手順

## フォルダ構成
```
battle_game_v2/
├── app.py
├── requirements.txt
├── PARAMETERS.md       ← 調整用パラメータ一覧（ダメージ等の微調整はここを見る）
├── CHARACTERS.md       ← キャラ追加手順
├── templates/
│   └── index.html
```

---

## STEP 1: ローカルで動かす

### 1-1. ライブラリのインストール
```bash
pip install -r requirements.txt
```

### 1-2. 起動
```bash
python app.py
```

ブラウザで `http://localhost:5000` を開く。

### 1-3. 1台でテスト（2画面）
対戦には2人必要なので、同じPCで**ブラウザ画面を2つ**開き、両方で同じルームID（例: room1）を入力して入室すると対戦できる。

### 1-4. スマホ2台でテスト（同じWiFi内）
1. PCのIPアドレスを確認
   - Windows: `ipconfig` → IPv4アドレス（例: 192.168.1.10）
2. スマホ2台で `http://192.168.1.10:5000` を開く
3. 同じルームID（例: room1）を入力して入室
4. 2人揃うとゲーム開始！

---

## STEP 2: Renderで公開する（インターネットで遊べるようにする）

### 2-1. GitHubにアップロード

1. https://github.com でアカウント作成
2. 新しいリポジトリを作成（例: battle-arena）
3. battle_game_v2フォルダの中身をアップロード

### 2-2. Renderでデプロイ

1. https://render.com でアカウント作成（GitHub連携）
2. 「New +」→「Web Service」
3. GitHubリポジトリを選択
4. 設定：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
5. 「Create Web Service」

数分後に `https://xxxx.onrender.com` のURLが発行される。
スマホでこのURLを開けばどこからでも遊べる！

---

## 操作方法

バーチャルパッドで操作します。

| ボタン | 動作 |
|--------|------|
| ◀▶ | 左右移動 |
| ↑ | ジャンプ |
| 弱 | 弱攻撃 |
| 強 | 強攻撃（弱より遅いが高威力）|
| 🛡 | ガード |
| 必殺 | 必殺技（ゲージ100で使用可）|

各種ダメージや速度などの数値は [PARAMETERS.md](PARAMETERS.md) にまとまっている。

## キャラクター

- 🔴 血まみれスライム … 必殺: ブラックホール（相手だけを引き寄せ＋継続ダメージ）
- 🐸 かえる＆人間＆とけい … 必殺: The World（相手を一定時間停止）

キャラはタイトル画面で選択。入室は早い者勝ちで、相手が先に同じキャラを取っていた場合はもう一方になる。
キャラを増やす手順は [CHARACTERS.md](CHARACTERS.md) を参照。

---

## 注意事項

- Renderの無料プランはしばらくアクセスがないとスリープします
  （最初のアクセスから起動まで30秒ほどかかることがある）
