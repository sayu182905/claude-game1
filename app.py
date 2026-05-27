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
    "sp_gain_on_attack": 10,     # 攻撃を出した側の増加量
    "sp_gain_on_hit": 20,        # 被弾した側の増加量

    # 必殺技：ブラックホール
    "blackhole_duration_sec": 7,
    "blackhole_pull_factor": 0.06,
    "blackhole_dps": 1,          # 1秒あたりの継続ダメージ

    # 必殺技：The World
    "the_world_duration_sec": 4,
}

# =====================================================================
# キャラ定義。キャラ追加手順は CHARACTERS.md を参照。
#   name : 表示名（クライアントの CHAR_NAMES と一致させること）
#   ult  : 必殺技の種類（"blackhole" / "the_world"）
# =====================================================================
CHARACTERS = {
    "slime": {"name": "血まみれスライム", "ult": "blackhole"},
    "frog":  {"name": "かえる＆人間＆とけい", "ult": "the_world"},
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
            "spectators": []
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
        if pl["frozen"] > 0:
            pl["frozen"] -= 1
            pl["vx"] *= 0.8
            pl["isGuarding"] = False
        else:
            if k.get("left"):
                pl["vx"] = -CONFIG["move_speed"]; pl["facing"] = -1
            elif k.get("right"):
                pl["vx"] = CONFIG["move_speed"]; pl["facing"] = 1
            else:
                pl["vx"] *= 0.7

            if k.get("jump") and pl["onGround"]:
                pl["vy"] = CONFIG["jump_vy"]

            pl["isGuarding"] = bool(k.get("guard"))

            # 弱攻撃
            if k.get("weak") and pl["atkCd"] == 0:
                do_attack(pl, opp, CONFIG["weak_dmg"], CONFIG["weak_cd"], state, room_id)

            # 強攻撃
            if k.get("strong") and pl["atkCd"] == 0:
                do_attack(pl, opp, CONFIG["strong_dmg"], CONFIG["strong_cd"], state, room_id)

            # 必殺技
            if k.get("ult") and pl["atkCd"] == 0 and pl["sp"] >= CONFIG["ult_cost"]:
                do_ult(pl, opp, state, room_id)

        # 物理
        pl["vy"] += GRAVITY
        pl["x"] += pl["vx"]
        pl["y"] += pl["vy"]
        pl["onGround"] = False

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

    # ブラックホール引き寄せ（発動者ではなく相手だけを引き寄せる）
    if state["bh"]:
        cx = STAGE_W / 2
        target = p2 if state["bh"].get("caster") == "p1" else p1
        target["vx"] += (cx - (target["x"] + 21)) * CONFIG["blackhole_pull_factor"]

    # 状態送信
    socketio.emit('state', {
        "p1": {k: v for k, v in p1.items() if k != "keys"},
        "p2": {k: v for k, v in p2.items() if k != "keys"},
        "bh": state["bh"],
        "world": state["world"],
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
    def_["hp"] = max(0, def_["hp"] - d)
    # ゲージは相手にダメージを与えたときだけ溜まる
    atk["sp"] = min(CONFIG["ult_cost"], atk["sp"] + CONFIG["sp_gain_on_attack"])
    def_["sp"] = min(CONFIG["ult_cost"], def_["sp"] + CONFIG["sp_gain_on_hit"])
    def_["hitAnim"] = 8

    # ダメージ量に応じたノックバック（吹っ飛び）
    direction = 1 if (def_["x"] + 21) >= (atk["x"] + 21) else -1
    def_["vx"] = direction * d * CONFIG["knockback_vx_factor"]
    def_["vy"] = -d * CONFIG["knockback_vy_factor"]
    def_["onGround"] = False

    # ダメージイベント
    socketio.emit('hit', {"dmg": d, "target": 2 if def_["isP2"] else 1, "guarded": def_["isGuarding"]}, room=room_id)

    if def_["hp"] <= 0:
        end_game(atk, state, room_id)

def do_ult(atk, opp, state, room_id):
    atk["sp"] = 0
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
                rooms[room_id]["state"]["world"] = None
                socketio.emit('world_end', {}, room=room_id)
        threading.Thread(target=world_end, daemon=True).start()

def end_game(winner, state, room_id):
    state["running"] = False
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
