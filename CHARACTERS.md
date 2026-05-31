# キャラクター追加ガイド

現在のキャラ:

| ID | 表示名 | 必殺技(ult) |
|----|--------|-------------|
| `slime`  | 血まみれスライム | `blackhole`（ブラックホール） |
| `frog`   | かえる＆人間＆とけい | `the_world`（The World） |
| `lizard` | トカゲ | `poison`（毒へびー！）／パッシブ：接触で1dmg/秒・移動/ジャンプ/攻撃が1.25倍速 |
| `rock`   | 石 | `meteor`（隕石！！）／パッシブ：通常ダメ半減・移動0.75倍 |
| `macho`  | マッチョなおじさん | `dumbbell`（マッチョパワー！！！） |

新しいキャラを追加するときは、以下の4〜5か所を編集します。
「〇〇というキャラを追加して、必殺技は△△」と言ってもらえれば、この手順に沿って実装します。

---

## 1. サーバー側にキャラを登録（app.py）

`app.py` の `CHARACTERS` 辞書にエントリを追加する。

```python
CHARACTERS = {
    "slime": {"name": "血まみれスライム", "ult": "blackhole"},
    "frog":  {"name": "かえる＆人間＆とけい", "ult": "the_world"},
    "newid": {"name": "新キャラの名前", "ult": "blackhole"},  # ← 追加
}
```

- `name` … 表示名（クライアントの `CHAR_NAMES` と完全一致させること）
- `ult`  … 必殺技の種類。既存の `"blackhole"` か `"the_world"` を流用するなら追加実装は不要。
  新しい必殺技にするなら手順4へ。

入室時のキャラ割り当て（早い者勝ち）は `CHARACTERS` のキーから自動で処理されるので、ここの追加だけで選択対象になります。

## 2. クライアントの名前・アイコンを登録（templates/index.html）

`<script>` 内の以下2つにエントリを追加する。

```js
const CHAR_NAMES = {slime:'血まみれスライム', frog:'かえる＆人間＆とけい', newid:'新キャラの名前'};
const CHAR_ICONS = {slime:'🔴', frog:'🐸', newid:'🟦'};
```

`CHAR_NAMES[newid]` は app.py の `name` と一致させること。

## 3. タイトル画面に選択カードを追加（templates/index.html）

`<div class="char-cards">` の中にカードを1枚追加する。

```html
<div class="char-card" data-char="newid" onclick="selectChar('newid')">
  <div class="icon">🟦</div>            <!-- 絵文字 or 手順5のSVG -->
  <div class="cname">新キャラの名前</div>
  <div class="skill">必殺: 〇〇</div>
</div>
```

## 4.（新しい必殺技を作る場合のみ）必殺技ロジックを実装

- **app.py**: `do_ult()` 内の `if ult == "blackhole": ... elif ult == "the_world": ...` に
  `elif ult == "新ult名":` の分岐を追加。効果時間などは `CONFIG` に新しいキーを足し、PARAMETERS.md にも追記する。
- 継続効果が必要なら `tick_room()` にも処理を追加（ブラックホールの引き寄せ部分が参考になる）。
- **index.html**: 必要なら `socket.on('ult_start')` などの演出や `statusFor()` の表示を追加。

## 5.（見た目を作り込む場合）キャラの描画を追加

ゲーム中のキャラ絵は canvas に手描きしている。`templates/index.html` の `drawPlayer()` 内の分岐：

```js
if(pl.char==='slime'){ ...スライムの描画... }
else { ...かえるの描画... }
```

を、新キャラ用に分岐追加する。

```js
if(pl.char==='slime'){ ... }
else if(pl.char==='newid'){ ...新キャラの描画... }
else { ...かえるの描画... }
```

描画を追加しない場合は `else`（かえる）の見た目で表示される。
タイトルのカードに凝ったアイコンを出したい場合は、スライムのカードにある inline SVG が参考になる。

---

## チェックリスト
- [ ] app.py `CHARACTERS` に追加した
- [ ] index.html `CHAR_NAMES` / `CHAR_ICONS` に追加した（名前は app.py と一致）
- [ ] タイトルに `char-card` を追加した
- [ ] （新必殺技なら）`do_ult` 分岐・`CONFIG`・PARAMETERS.md を追加した
- [ ] （見た目を作るなら）`drawPlayer` に分岐を追加した
