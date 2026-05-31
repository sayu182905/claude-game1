from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import threading, time, os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'battlearena-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# =====================================================================
# 調整用パラメータ。値の意味と一覧は PARAMETERS.md を参照。
# 数値を変えたいときは基本ここだけ触ればOK。
# =====================================================================
CONFIG = {
    # ステージ
    "stage_w": 800,
    "stage_h": 300,
    "ground_y": 240,
    "gravity": 0.5,

    # プレイヤー基本
    "max_hp": 100,
    "move_speed": 4,
    "jump_vy": -11,
    "p1_spawn_x": 150,
    "p2_spawn_x": 608,

    # 攻撃
    "attack_range": 95,
    "attack_v_range": 55,        # 攻撃が当たる縦方向の差（px）。これより高低差があると当たらない
    "weak_dmg": 5,
    "weak_cd": 20,
    "strong_dmg": 10,
    "strong_cd": 60,
    "guard_divisor": 3,          # ガード時ダメージを 1/n に
    "knockback_vx_factor": 1.8,  # 吹っ飛び横速度 = ダメージ × この値
    "knockback_vy_factor": 0.7,  # 打ち上げ速度 = ダメージ × この値

    # 必殺ゲージ
    "ult_cost": 100,
    "sp_gain_on_attack": 5,      # 攻撃を出した側の増加量
    "sp_gain_on_hit": 10,        # 被弾した側の増加量

    # 必殺技：ブラックホール
    "blackhole_duration_sec": 7,
    "blackhole_pull_factor": 0.06,
    "blackhole_dps": 1,          # 1秒あたりの継続ダメージ

    # 必殺技：The World
    "the_world_duration_sec": 4,

    # 必殺技：毒へびー！（トカゲ）
    "poison_duration_sec": 20,            # 毒状態の継続時間
    "poison_tick_interval_sec": 2,        # 何秒ごとにダメージが入るか
    "poison_tick_dmg": 1,                 # 1ティックのダメージ

    # 必殺技：隕石！！（石）
    "meteor_duration_sec": 5,             # 相手を埋めて拘束する時間
    "meteor_dmg": 20,                     # 爆発ダメージ

    # 必殺技：マッチョパワー！！！（マッチョ）
    "dumbbell_duration_sec": 10,          # ダンベル投擲時間
    "dumbbell_per_sec": 3,                # 1秒あたりの投擲数
    "dumbbell_dmg": 5,                    # ダンベル1個のダメージ
    "dumbbell_speed": 7,                  # ダンベルの飛翔速度（px/frame）

    # キャラ固有のパッシブ特性
    "lizard_contact_dmg_per_sec": 1,      # トカゲ：接触1秒ごとに与えるダメージ
    "lizard_speed_factor": 1.25,          # トカゲ：移動・ジャンプ・攻撃速度の倍率
    "rock_dmg_resist": 0.5,               # 石：受ける通常ダメージの倍率（0.5=半減）
    "rock_move_factor": 0.75,             # 石：移動速度の倍率
}

# =====================================================================
# キャラ定義。キャラ追加手順は CHARACTERS.md を参照。
#   name : 表示名（クライアントの CHAR_NAMES と一致させること）
#   ult  : 必殺技の種類（"blackhole" / "the_world"）
# =====================================================================
CHARACTERS = {
    "slime":  {"name": "血まみれスライム", "ult": "blackhole"},
    "frog":   {"name": "かえる＆人間＆とけい", "ult": "the_world"},
    "lizard": {"name": "トカゲ", "ult": "poison"},
    "rock":   {"name": "石", "ult": "meteor"},
    "macho":  {"name": "マッチョなおじさん", "ult": "dumbbell"},
}
DEFAULT_CHAR = "slime"

def char_name(char):
    return CHARACTERS.get(char, {}).get("name", "不明")

# ===== ステージ =====
STAGE_W = CONFIG["stage_w"]
STAGE_H = CONFIG["stage_h"]
GRAVITY = CONFIG["gravity"]
GROUND_Y = CONFIG["ground_y"]
PLATFORMS = [
    {"x": 80, "y": 190, "w": 150, "h": 14},
    {"x": 325, "y": 130, "w": 150, "h": 14},
    {"x": 570, "y": 190, "w": 150, "h": 14},
]

# ===== ルーム管理 =====
rooms = {}  # room_id -> {p1_sid, p2_sid, p1_char, p2_char, state, spectators}

def make_game_state(p1_char=DEFAULT_CHAR, p2_char="frog"):
    return {
        "running": False,
        "start_time": None,
        "p1": make_player(CONFIG["p1_spawn_x"], False, p1_char),
        "p2": make_player(CONFIG["p2_spawn_x"], True, p2_char),
        "bh": None,
        "world": None,
        "meteor": None,        # {"target": "p1"|"p2", "t_start": time, "duration": sec}
        "projectiles": [],     # [{x,y,vx,owner:"p1"|"p2",dmg,type:"dumbbell"}]
    }

def make_player(x, is_p2, char=DEFAULT_CHAR):
    return {
        "x": x, "y": 190, "vx": 0, "vy": 0,
        "hp": CONFIG["max_hp"], "sp": 0,
        "onGround": False,
        "facing": -1 if is_p2 else 1,
        "isP2": is_p2,
        "char": char,
        "atkCd": 0, "atkAnim": 0, "hitAnim": 0,
        "frozen": 0, "isGuarding": False,
        "ult_active": False,
        "pending_kb_vx": 0, "pending_kb_vy": 0,  # 停止中に受けたノックバック（解除時に反映）
        "poisoned": 0,                          # 毒状態の残りフレーム数（0で毒なし）
        "buried": 0,                            # 隕石で埋まっている残りフレーム数（描画用）
        "contact_acc": 0,                       # トカゲの接触ダメージ用カウンタ（フレーム）
        "keys": {}
    }

# ===== HTTP Routes =====
@app.route('/')
def index():
    return render_template('index.html')

# ===== SocketIO Events =====
def other_char(taken):
    for c in CHARACTERS:
        if c != taken:
            return c
    return taken

@socketio.on('join')
def on_join(data):
    room_id = data.get('room', 'default')
    chosen = data.get('char', DEFAULT_CHAR)
    if chosen not in CHARACTERS:
        chosen = DEFAULT_CHAR
    join_room(room_id)

    if room_id not in rooms:
        rooms[room_id] = {
            "p1_sid": None, "p2_sid": None,
            "p1_char": DEFAULT_CHAR, "p2_char": "frog",
            "state": make_game_state(),
            "spectators": [],
            "rematch": set()
        }

    room = rooms[room_id]
    sid = request.sid

    if room["p1_sid"] is None:
        # 早い者勝ち：最初の入室者は選んだキャラを確定
        room["p1_sid"] = sid
        room["p1_char"] = chosen
        emit('assigned', {'player': 1, 'room': room_id, 'char': chosen})
        print(f"[Room {room_id}] P1 joined: {sid} as {chosen}")
    elif room["p2_sid"] is None:
        # 相手が先に取っていたら残りのキャラになる
        p2_char = chosen if chosen != room["p1_char"] else other_char(room["p1_char"])
        room["p2_sid"] = sid
        room["p2_char"] = p2_char
        emit('assigned', {'player': 2, 'room': room_id, 'char': p2_char})
        print(f"[Room {room_id}] P2 joined: {sid} as {p2_char}")
        # 両プレイヤー揃ったのでゲーム開始
        room["state"] = make_game_state(room["p1_char"], p2_char)
        room["state"]["running"] = True
        room["state"]["start_time"] = time.time()
        socketio.emit('game_start', {}, room=room_id)
        print(f"[Room {room_id}] Game started!")
    else:
        room["spectators"].append(sid)
        emit('assigned', {'player': 0, 'room': room_id})  # 観戦
        # 既に試合中なら観戦者にもゲーム画面を表示させる
        if room["state"]["running"]:
            emit('game_start', {})

@socketio.on('input')
def on_input(data):
    room_id = data.get('room', 'default')
    player = data.get('player')
    keys = data.get('keys', {})

    if room_id not in rooms:
        return
    state = rooms[room_id]["state"]

    if player == 1:
        state["p1"]["keys"] = keys
    elif player == 2:
        state["p2"]["keys"] = keys

@socketio.on('rematch')
def on_rematch(data):
    room_id = data.get('room', 'default')
    room = rooms.get(room_id)
    if not room:
        return
    sid = request.sid
    # 実プレイヤー（P1/P2）のみ再戦をリクエストできる
    if sid not in (room["p1_sid"], room["p2_sid"]):
        return
    room.setdefault("rematch", set()).add(sid)

    # 両者が「もう一度」を押したらリセットして再開
    if room["p1_sid"] in room["rematch"] and room["p2_sid"] in room["rematch"]:
        room["rematch"] = set()
        room["state"] = make_game_state(room["p1_char"], room["p2_char"])
        room["state"]["running"] = True
        room["state"]["start_time"] = time.time()
        socketio.emit('game_start', {}, room=room_id)
        print(f"[Room {room_id}] Rematch started!")
    else:
        # まだ片方だけ → 相手を待っている状態を全員に通知
        which = 1 if sid == room["p1_sid"] else 2
        socketio.emit('rematch_waiting', {'player': which}, room=room_id)

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for room_id, room in list(rooms.items()):
        if room["p1_sid"] == sid or room["p2_sid"] == sid:
            socketio.emit('player_disconnected', {}, room=room_id)
            rooms.pop(room_id, None)
            print(f"[Room {room_id}] Player disconnected, room closed.")
            break

# ===== ゲームループ（サーバー側物理） =====
def tick_room(room_id):
    room = rooms.get(room_id)
    if not room:
        return
    state = room["state"]
    if not state["running"]:
        return

    p1 = state["p1"]
    p2 = state["p2"]

    for pl, opp in [(p1, p2), (p2, p1)]:
        k = pl["keys"]
        is_frozen = pl["frozen"] > 0
        # ブラックホールに吸われている側か（移動・台への着地を無効化する）
        bh_target = bool(state["bh"]) and (pl["isP2"] == (state["bh"].get("caster") == "p1"))
        if is_frozen:
            # The World：完全停止（空中でもその瞬間の位置で止まる）
            pl["frozen"] -= 1
            pl["vx"] = 0
            pl["vy"] = 0
            pl["isGuarding"] = False
        else:
            # ブラックホールに吸われている側は左右移動で抜け出せない
            # キャラパッシブ：石は移動0.75倍／トカゲは移動1.25倍
            if pl["char"] == "rock":
                move_speed = CONFIG["move_speed"] * CONFIG["rock_move_factor"]
            elif pl["char"] == "lizard":
                move_speed = CONFIG["move_speed"] * CONFIG["lizard_speed_factor"]
            else:
                move_speed = CONFIG["move_speed"]
            if bh_target:
                pl["vx"] *= 0.7
            elif k.get("left"):
                pl["vx"] = -move_speed; pl["facing"] = -1
            elif k.get("right"):
                pl["vx"] = move_speed; pl["facing"] = 1
            else:
                pl["vx"] *= 0.7

            # ブラックホールに吸われている側はジャンプもできない
            # トカゲはジャンプ初速も1.25倍（より高く飛ぶ）
            jump_vy = CONFIG["jump_vy"] * (CONFIG["lizard_speed_factor"] if pl["char"] == "lizard" else 1.0)
            if k.get("jump") and pl["onGround"] and not bh_target:
                pl["vy"] = jump_vy

            pl["isGuarding"] = bool(k.get("guard"))

            # 攻撃クールダウン倍率（トカゲは1/1.25で早く撃てる）
            cd_factor = (1.0 / CONFIG["lizard_speed_factor"]) if pl["char"] == "lizard" else 1.0

            # 石の必殺技（隕石！！）発動中は攻撃を使えない
            can_attack = not (pl["char"] == "rock" and pl["ult_active"])

            # 弱攻撃
            if can_attack and k.get("weak") and pl["atkCd"] == 0:
                do_attack(pl, opp, CONFIG["weak_dmg"], max(1, int(CONFIG["weak_cd"] * cd_factor)), state, room_id)

            # 強攻撃
            if can_attack and k.get("strong") and pl["atkCd"] == 0:
                do_attack(pl, opp, CONFIG["strong_dmg"], max(1, int(CONFIG["strong_cd"] * cd_factor)), state, room_id)

            # 必殺技
            if k.get("ult") and pl["atkCd"] == 0 and pl["sp"] >= CONFIG["ult_cost"] and not pl["ult_active"]:
                do_ult(pl, opp, state, room_id)

        # 物理（停止中は計算をスキップして完全に静止させる）
        if not is_frozen:
            # 停止解除直後：停止中に溜まったノックバックをまとめて反映
            if pl["pending_kb_vx"] or pl["pending_kb_vy"]:
                pl["vx"] += pl["pending_kb_vx"]
                pl["vy"] += pl["pending_kb_vy"]
                pl["pending_kb_vx"] = 0
                pl["pending_kb_vy"] = 0
                pl["onGround"] = False

            pl["vy"] += GRAVITY
            pl["x"] += pl["vx"]
            pl["y"] += pl["vy"]
            pl["onGround"] = False

            # ブラックホールに吸われている側は台に着地しない（勝手に台へ上がるのを防止）
            if not bh_target:
                for pf in PLATFORMS:
                    if (pl["x"] + 42 > pf["x"] and pl["x"] < pf["x"] + pf["w"] and
                            pl["y"] + 50 > pf["y"] and pl["y"] + 50 < pf["y"] + pf["h"] + 12 and pl["vy"] >= 0):
                        pl["y"] = pf["y"] - 50
                        pl["vy"] = 0
                        pl["onGround"] = True

            if pl["y"] + 50 >= GROUND_Y:
                pl["y"] = GROUND_Y - 50; pl["vy"] = 0; pl["onGround"] = True

            pl["x"] = max(0, min(STAGE_W - 42, pl["x"]))

            for cd in ["atkCd", "atkAnim", "hitAnim"]:
                if pl[cd] > 0:
                    pl[cd] -= 1

        # 状態ティック（毒・埋まり：停止/拘束に関係なく時間経過）
        if pl["poisoned"] > 0:
            pl["poisoned"] -= 1
        if pl["buried"] > 0:
            pl["buried"] -= 1

    # トカゲのパッシブ：体が毒なので、接触中は1秒ごとに相手へ1ダメージ
    for src, dst in [(p1, p2), (p2, p1)]:
        if src["char"] != "lizard":
            continue
        overlap = (abs((src["x"] + 21) - (dst["x"] + 21)) < 36 and
                   abs((src["y"] + 25) - (dst["y"] + 25)) < 40)
        if overlap and dst["hp"] > 0:
            src["contact_acc"] += 1
            if src["contact_acc"] >= 60:
                src["contact_acc"] = 0
                d = CONFIG["lizard_contact_dmg_per_sec"]
                dst["hp"] = max(0, dst["hp"] - d)
                socketio.emit('hit', {"dmg": d, "target": 2 if dst["isP2"] else 1, "guarded": False}, room=room_id)
                if dst["hp"] <= 0:
                    end_game(src, state, room_id)
                    return
        else:
            src["contact_acc"] = 0

    # ブラックホール引き寄せ（発動者ではなく相手だけを引き寄せる。停止中は効かない）
    if state["bh"]:
        cx = STAGE_W / 2
        target = p2 if state["bh"].get("caster") == "p1" else p1
        if target["frozen"] <= 0:
            target["vx"] += (cx - (target["x"] + 21)) * CONFIG["blackhole_pull_factor"]

    # 投擲物（ダンベル等）の更新：移動＋衝突判定
    projs = state.get("projectiles") or []
    if projs:
        new_projs = []
        for p in projs:
            p["x"] += p["vx"]
            # 画面外で消滅
            if p["x"] < -30 or p["x"] > STAGE_W + 30:
                continue
            target = p2 if p["owner"] == "p1" else p1
            # 中心同士の距離で当たり判定（ダンベルは横長20×縦12を想定）
            if (abs(p["x"] - (target["x"] + 21)) < 28 and
                    abs(p["y"] - (target["y"] + 25)) < 28):
                d = p["dmg"]
                if target["isGuarding"]:
                    d = max(1, d // CONFIG["guard_divisor"])
                # 石キャラのパッシブ：通常ダメージ（投擲含む）を半減
                if target["char"] == "rock":
                    d = max(1, int(d * CONFIG["rock_dmg_resist"]))
                target["hp"] = max(0, target["hp"] - d)
                target["hitAnim"] = 8
                direction = 1 if p["vx"] > 0 else -1
                kb_vx = direction * d * 0.6
                kb_vy = -d * 0.3
                if target["frozen"] > 0:
                    target["pending_kb_vx"] += kb_vx
                    target["pending_kb_vy"] += kb_vy
                else:
                    target["vx"] = kb_vx
                    target["vy"] = kb_vy
                    target["onGround"] = False
                socketio.emit('hit', {"dmg": d, "target": 2 if target["isP2"] else 1, "guarded": target["isGuarding"]}, room=room_id)
                if target["hp"] <= 0:
                    caster = p1 if p["owner"] == "p1" else p2
                    end_game(caster, state, room_id)
                    return
                continue  # 命中したダンベルは消える
            new_projs.append(p)
        state["projectiles"] = new_projs

    # 状態送信
    socketio.emit('state', {
        "p1": {k: v for k, v in p1.items() if k != "keys"},
        "p2": {k: v for k, v in p2.items() if k != "keys"},
        "bh": state["bh"],
        "world": state["world"],
        "meteor": state.get("meteor"),
        "projectiles": state.get("projectiles", []),
        "elapsed": int(time.time() - state["start_time"]) if state["start_time"] else 0
    }, room=room_id)

def do_attack(atk, def_, dmg, cd, state, room_id):
    atk["atkCd"] = cd; atk["atkAnim"] = cd
    dist = abs((atk["x"] + 21) - (def_["x"] + 21))
    v_dist = abs((atk["y"] + 25) - (def_["y"] + 25))
    if dist > CONFIG["attack_range"] or v_dist > CONFIG["attack_v_range"]:
        return  # 空振り：横が遠い／高低差が大きいとゲージも溜まらない
    d = dmg
    if def_["isGuarding"]:
        d = max(1, d // CONFIG["guard_divisor"])
    # 石キャラのパッシブ：通常攻撃のダメージを半減
    if def_["char"] == "rock":
        d = max(1, int(d * CONFIG["rock_dmg_resist"]))
    def_["hp"] = max(0, def_["hp"] - d)
    # ゲージは相手にダメージを与えたときだけ溜まる（必殺発動中の本人は溜まらない＝多重発動防止）
    if not atk["ult_active"]:
        atk["sp"] = min(CONFIG["ult_cost"], atk["sp"] + CONFIG["sp_gain_on_attack"])
    if not def_["ult_active"]:
        def_["sp"] = min(CONFIG["ult_cost"], def_["sp"] + CONFIG["sp_gain_on_hit"])
    def_["hitAnim"] = 8

    # ダメージ量に応じたノックバック（吹っ飛び）
    direction = 1 if (def_["x"] + 21) >= (atk["x"] + 21) else -1
    kb_vx = direction * d * CONFIG["knockback_vx_factor"]
    kb_vy = -d * CONFIG["knockback_vy_factor"]
    if def_["frozen"] > 0:
        # The World停止中：ダメージは入るが、ノックバックは解除時にまとめて反映
        def_["pending_kb_vx"] += kb_vx
        def_["pending_kb_vy"] += kb_vy
    else:
        def_["vx"] = kb_vx
        def_["vy"] = kb_vy
        def_["onGround"] = False

    # ダメージイベント
    socketio.emit('hit', {"dmg": d, "target": 2 if def_["isP2"] else 1, "guarded": def_["isGuarding"]}, room=room_id)

    if def_["hp"] <= 0:
        end_game(atk, state, room_id)

def do_ult(atk, opp, state, room_id):
    atk["sp"] = 0
    atk["ult_active"] = True   # 必殺中は発動者のゲージは溜まらない（多重発動防止）
    atk["atkCd"] = 10
    atk_num = 2 if atk["isP2"] else 1
    opp_num = 1 if atk["isP2"] else 2
    caster_key = "p2" if atk["isP2"] else "p1"
    opp_key = "p1" if atk["isP2"] else "p2"
    socketio.emit('ult_start', {"player": atk_num}, room=room_id)

    ult = CHARACTERS.get(atk["char"], {}).get("ult")

    if ult == "blackhole":
        # ブラックホール：一定時間、相手だけを引き寄せ＋継続ダメージ
        state["bh"] = {"caster": caster_key}
        def bh_tick():
            for _ in range(CONFIG["blackhole_duration_sec"]):
                time.sleep(1)
                if room_id not in rooms:
                    return
                st = rooms[room_id]["state"]
                if not st["running"]:
                    return
                target = st[opp_key]
                target["hp"] = max(0, target["hp"] - CONFIG["blackhole_dps"])
                socketio.emit('hit', {"dmg": CONFIG["blackhole_dps"], "target": opp_num, "guarded": False}, room=room_id)
                if target["hp"] <= 0:
                    end_game(st[caster_key], st, room_id)
                    return
            if room_id in rooms:
                rooms[room_id]["state"]["bh"] = None
                rooms[room_id]["state"][caster_key]["ult_active"] = False
                socketio.emit('bh_end', {}, room=room_id)
        threading.Thread(target=bh_tick, daemon=True).start()
    elif ult == "the_world":
        # The World：一定時間、相手を停止
        opp["frozen"] = CONFIG["the_world_duration_sec"] * 60
        state["world"] = True
        def world_end():
            time.sleep(CONFIG["the_world_duration_sec"])
            if room_id in rooms:
                rooms[room_id]["state"][opp_key]["frozen"] = 0
                rooms[room_id]["state"][caster_key]["ult_active"] = False
                rooms[room_id]["state"]["world"] = None
                socketio.emit('world_end', {}, room=room_id)
        threading.Thread(target=world_end, daemon=True).start()

    elif ult == "poison":
        # 毒へびー！：相手を毒状態にし、一定間隔でダメージ
        opp["poisoned"] = CONFIG["poison_duration_sec"] * 60
        def poison_tick():
            ticks = CONFIG["poison_duration_sec"] // CONFIG["poison_tick_interval_sec"]
            for _ in range(ticks):
                time.sleep(CONFIG["poison_tick_interval_sec"])
                if room_id not in rooms:
                    return
                st = rooms[room_id]["state"]
                if not st["running"]:
                    return
                target = st[opp_key]
                target["hp"] = max(0, target["hp"] - CONFIG["poison_tick_dmg"])
                socketio.emit('hit', {"dmg": CONFIG["poison_tick_dmg"], "target": opp_num, "guarded": False}, room=room_id)
                if target["hp"] <= 0:
                    end_game(st[caster_key], st, room_id)
                    return
            if room_id in rooms:
                rooms[room_id]["state"][caster_key]["ult_active"] = False
                rooms[room_id]["state"][opp_key]["poisoned"] = 0
        threading.Thread(target=poison_tick, daemon=True).start()

    elif ult == "meteor":
        # 隕石！！：相手を5秒間埋めて拘束→爆発で20ダメージ
        dur = CONFIG["meteor_duration_sec"]
        opp["frozen"] = dur * 60
        opp["buried"] = dur * 60
        state["meteor"] = {"target": opp_key, "t_start": time.time(), "duration": dur}
        def meteor_end():
            time.sleep(dur)
            if room_id not in rooms:
                return
            st = rooms[room_id]["state"]
            if not st["running"]:
                return
            target = st[opp_key]
            d = CONFIG["meteor_dmg"]
            target["hp"] = max(0, target["hp"] - d)
            target["hitAnim"] = 12
            target["frozen"] = 0
            target["buried"] = 0
            target["pending_kb_vx"] = 0
            target["pending_kb_vy"] = 0
            target["vx"] = 0
            target["vy"] = -d * CONFIG["knockback_vy_factor"] * 0.5
            target["onGround"] = False
            socketio.emit('hit', {"dmg": d, "target": opp_num, "guarded": False}, room=room_id)
            st["meteor"] = None
            st[caster_key]["ult_active"] = False
            if target["hp"] <= 0:
                end_game(st[caster_key], st, room_id)
        threading.Thread(target=meteor_end, daemon=True).start()

    elif ult == "dumbbell":
        # マッチョパワー！！！：10秒間、毎秒3個のダンベルを前方に投げ続ける
        def dumbbell_throw():
            interval = 1.0 / CONFIG["dumbbell_per_sec"]
            total = int(CONFIG["dumbbell_per_sec"] * CONFIG["dumbbell_duration_sec"])
            for _ in range(total):
                if room_id not in rooms:
                    return
                st = rooms[room_id]["state"]
                if not st["running"]:
                    if room_id in rooms:
                        rooms[room_id]["state"][caster_key]["ult_active"] = False
                    return
                caster_pl = st[caster_key]
                facing = caster_pl["facing"]
                st.setdefault("projectiles", []).append({
                    "x": caster_pl["x"] + (42 if facing > 0 else 0),
                    "y": caster_pl["y"] + 24,
                    "vx": facing * CONFIG["dumbbell_speed"],
                    "owner": caster_key,
                    "dmg": CONFIG["dumbbell_dmg"],
                    "type": "dumbbell",
                })
                time.sleep(interval)
            if room_id in rooms:
                rooms[room_id]["state"][caster_key]["ult_active"] = False
        threading.Thread(target=dumbbell_throw, daemon=True).start()

def end_game(winner, state, room_id):
    state["running"] = False
    if room_id in rooms:
        rooms[room_id]["rematch"] = set()
    winner_name = char_name(winner.get("char", DEFAULT_CHAR))
    duration = int(time.time() - state["start_time"]) if state["start_time"] else 0
    st = rooms.get(room_id, {}).get("state", {})
    p1_total_dmg = CONFIG["max_hp"] - st.get("p2", {}).get("hp", CONFIG["max_hp"])
    p2_total_dmg = CONFIG["max_hp"] - st.get("p1", {}).get("hp", CONFIG["max_hp"])
    socketio.emit('game_over', {
        "winner": winner_name,
        "duration": duration,
        "p1_dmg": p1_total_dmg,
        "p2_dmg": p2_total_dmg,
    }, room=room_id)

# ===== ゲームループスレッド =====
def game_loop():
    while True:
        for room_id in list(rooms.keys()):
            try:
                tick_room(room_id)
            except Exception as e:
                print(f"[Loop] Error in room {room_id}: {e}")
        time.sleep(1/60)

loop_thread = threading.Thread(target=game_loop, daemon=True)
loop_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("============================")
    print(" バトルアリーナ v2 起動中...")
    print(f" http://localhost:{port}")
    print("============================")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
