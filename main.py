import math
import random
import sys
import os
import json
import time
import socket
import atexit
import colorsys
import threading
import queue
import itertools

# --- Plataforma: Android (ou MOBILE_SIM=1 para testar no PC) ---------------
IS_ANDROID = ("ANDROID_ARGUMENT" in os.environ) or ("ANDROID_PRIVATE" in os.environ)
MOBILE = IS_ANDROID or bool(os.environ.get("BLUE_ORB_MOBILE"))
if IS_ANDROID:
    os.environ.setdefault("SDL_TOUCH_MOUSE_EVENTS", "0")   # nós mesmos convertemos toque -> mouse (multitoque)
    os.environ.setdefault("SDL_ANDROID_TRAP_BACK_BUTTON", "1")
import pygame

_UID_ENEMY = itertools.count(1)
_UID_ORB = itertools.count(1)

# ============================================================================
# BLUE ORB SURVIVAL ARENA — v2.4 polido (hierarquia, táticos, sinergias, biomas 12)
# Python 3.10+ | pygame 2.5+
# ============================================================================

def get_writable_save_dir():
    """Encontra uma pasta com permissão de escrita e guarda TODOS os arquivos dentro da subpasta 'SAVES'."""
    base_candidates = []
    if os.environ.get("ANDROID_PRIVATE"):
        base_candidates.append(os.environ["ANDROID_PRIVATE"])   # sobrevive a atualizações do app
    try:
        base_candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    base_candidates.append(os.getcwd())
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            base_candidates.append(os.path.join(appdata, "BlueOrbSurvivalArena"))
    base_candidates.append(os.path.join(os.path.expanduser("~"), "BlueOrbSurvivalArena"))

    chosen_saves_dir = None
    chosen_base_dir = None
    for base in base_candidates:
        if not base:
            continue
        saves_path = os.path.join(base, "SAVES")
        try:
            os.makedirs(saves_path, exist_ok=True)
            test_file = os.path.join(saves_path, ".write_test.tmp")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
                f.flush()
                os.fsync(f.fileno())
            os.remove(test_file)
            chosen_saves_dir = saves_path
            chosen_base_dir = base
            break
        except Exception:
            continue

    if not chosen_saves_dir:
        chosen_base_dir = os.getcwd()
        chosen_saves_dir = os.path.join(chosen_base_dir, "SAVES")
        os.makedirs(chosen_saves_dir, exist_ok=True)

    # Migra automaticamente arquivos antigos soltos na pasta do jogo para dentro de "SAVES"
    legacy_files = [
        "profile.json",
        "highscores.json",
        "cloud_sync_backup.json",
        "save_slot_1.json",
        "save_slot_2.json",
        "save_slot_3.json",
        ".lvl30_restored.flag",
        ".slot1_lvl30_purged.flag",
    ]
    for fname in legacy_files:
        old_fp = os.path.join(chosen_base_dir, fname)
        new_fp = os.path.join(chosen_saves_dir, fname)
        if os.path.exists(old_fp) and os.path.isfile(old_fp):
            try:
                if not os.path.exists(new_fp):
                    os.replace(old_fp, new_fp)
                else:
                    os.remove(old_fp)
            except Exception:
                pass

    return chosen_saves_dir

SAVE_DIR = get_writable_save_dir()

_SAVE_Q = queue.Queue()
_SAVE_PENDING = {}
_SAVE_LOCK = threading.Lock()
_SAVE_THREAD = None

def _write_atomic(filepath, text):
    try:
        temp_path = filepath + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
    except Exception as e:
        print(f"[ERRO AO SALVAR {filepath}]: {e}")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

def _save_worker():
    while True:
        filepath, text = _SAVE_Q.get()
        try:
            _write_atomic(filepath, text)
        finally:
            with _SAVE_LOCK:
                _SAVE_PENDING[filepath] = max(0, _SAVE_PENDING.get(filepath, 1) - 1)
            _SAVE_Q.task_done()

def flush_saves():
    """Espera todas as gravacoes pendentes terminarem (usado ao sair do jogo)."""
    _SAVE_Q.join()

def safe_write_json(filepath, data):
    """Serializa na thread principal (barato) e grava em disco numa thread separada:
    escrita atomica (.tmp + fsync + replace) sem travar o jogo."""
    global _SAVE_THREAD
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERRO AO SERIALIZAR {filepath}]: {e}")
        return False
    if _SAVE_THREAD is None:
        _SAVE_THREAD = threading.Thread(target=_save_worker, daemon=True)
        _SAVE_THREAD.start()
    with _SAVE_LOCK:
        _SAVE_PENDING[filepath] = _SAVE_PENDING.get(filepath, 0) + 1
    _SAVE_Q.put((filepath, text))
    return True

def safe_read_json(filepath):
    """Lê um ficheiro JSON com segurança (espera gravações pendentes desse arquivo)."""
    if _SAVE_PENDING.get(filepath, 0) > 0:
        _SAVE_Q.join()
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERRO AO LER {filepath}]: {e}")
        return None

atexit.register(flush_saves)


pygame.init()
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=(2048 if MOBILE else 512))
    has_sound = True
except pygame.error:
    has_sound = False

W, H = 1280, 800
FPS = 60
TITLE = "BLUE ORB SURVIVAL ARENA"

BG = (6, 9, 20)
BG_GRID = (14, 24, 48)
WHITE = (240, 245, 255)
CYAN = (0, 230, 255)
BLUE = (20, 140, 255)
GREEN = (50, 245, 130)
RED = (255, 75, 95)
GOLD = (255, 210, 60)
PURPLE = (190, 90, 255)
ORANGE = (255, 150, 40)
MYTHIC = (255, 55, 145)
DIVINE = (0, 255, 215)
SUPREME = (255, 45, 75)

RARITY_COLORS = {
    "Comum": (150, 165, 185),
    "Incomum": GREEN,
    "Rara": BLUE,
    "Épica": PURPLE,
    "Lendária": GOLD,
    "Mítica": MYTHIC,
    "Divina": DIVINE,
    "Suprema": SUPREME,
    "Primordial": (255, 120, 35),
    "Transcendente": (245, 245, 255)
}

# ============================================================================
# CAMADA MOBILE (Android) — tela virtual escalada, MULTITOQUE real, joysticks
# flutuantes (mover à esquerda / mirar à direita), botões DASH, ULT, AUTO e PAUSA.
# Só é ativada quando MOBILE=True (Android, ou BLUE_ORB_MOBILE=1 no PC para teste).
# ============================================================================
MOBILE_VH = 720            # altura lógica; a largura segue a proporção da tela do aparelho
MOBILE_STICK_R = 72        # raio do joystick virtual (px lógicos)
_mob = {"vw": 1280, "vh": 720, "fingers": {}, "roles": {}, "origin": {}, "primary": None,
        "mouse_pos": (0, 0), "mouse_down": False, "swipe": 0.0, "flash": {}, "text_on": False}


def mobile_init_display():
    if IS_ANDROID:
        real = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        real = pygame.display.set_mode((1600, 720))      # simulação no PC
    rw, rh = real.get_size()
    vh = MOBILE_VH
    vw = int(round(vh * rw / max(1, rh) / 2.0)) * 2
    vw = max(1000, min(1800, vw))
    _mob["vw"], _mob["vh"] = vw, vh
    return pygame.Surface((vw, vh)).convert()


def mobile_present():
    real = pygame.display.get_surface()
    if real is not None:
        if real.get_size() == screen.get_size():
            real.blit(screen, (0, 0))
        else:
            pygame.transform.scale(screen, real.get_size(), real)
    pygame.display.flip()


def _mob_state():
    g = globals().get("game")
    return getattr(g, "state", "menu")


def _mob_layout():
    """Posições dos botões em coordenadas lógicas (dependem da largura da tela)."""
    vw, vh = _mob["vw"], _mob["vh"]
    return {
        "pause": pygame.Rect(vw - 72, 70, 56, 56),
        "auto": pygame.Rect(vw - 176, vh - 364, 130, 44),
        "ult": pygame.Rect(vw - 172, vh - 312, 108, 108),
        "dash": pygame.Rect(vw - 168, vh - 196, 100, 100),
    }


def _mob_stick_home(role):
    vw, vh = _mob["vw"], _mob["vh"]
    return (150, vh - 150) if role == "move" else (vw - 330, vh - 150)


def _mob_do_dash():
    g = globals()["game"]
    p = g.player
    if not (p.dash and p.dash_cd <= 0) or p.downed:
        return
    lx, ly = g.touch_left_vec
    if abs(lx) > 0.05 or abs(ly) > 0.05:
        ax, ay = vec_norm(lx, ly)
    elif math.hypot(p.vx, p.vy) > 20:
        ax, ay = vec_norm(p.vx, p.vy)
    else:
        rx, ry = g.touch_right_vec
        ax, ay = vec_norm(rx, ry) if (abs(rx) > 0.1 or abs(ry) > 0.1) else (1.0, 0.0)
    sc = g.get_skin_colors()
    p.dash_time = 0.16
    p.dash_cd = 2.8
    p.dash_vx = ax * 920
    p.dash_vy = ay * 920
    g.shockwaves.append(Shockwave(p.x, p.y, 48, sc["bullet"], 0.22, 2))
    g.particles.extend(Particle(p.x, p.y, sc["bullet"]) for _ in range(18))
    play_sound("dash")


def _mob_press_button(name):
    g = globals()["game"]
    _mob["flash"][name] = 0.18
    if name == "dash":
        _mob_do_dash()
    elif name == "ult":
        g.player.trigger_ultimate(g)
    elif name == "auto":
        g.auto_fire = not g.auto_fire
        play_sound("select")
    elif name == "pause":
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="\x1b"))


def _mob_finger_down_playing(fid, x, y):
    for name, rect in _mob_layout().items():
        if rect.inflate(18, 18).collidepoint(x, y):
            _mob["roles"][fid] = "btn"
            _mob_press_button(name)
            return
    vw, vh = _mob["vw"], _mob["vh"]
    role = "move" if x < vw * 0.5 else "aim"
    if role in _mob["roles"].values():
        return                                   # já existe um dedo nesse joystick
    R = MOBILE_STICK_R
    _mob["roles"][fid] = role
    _mob["origin"][fid] = (min(max(x, R + 16), vw - R - 16), min(max(y, R + 16), vh - R - 16))


def _mob_hook_events(evs):
    vw, vh = _mob["vw"], _mob["vh"]
    out = []
    st = _mob_state()
    playing = (st == "playing")
    if not playing:
        _mob["roles"].clear()
        _mob["origin"].clear()
    # teclado virtual do Android só no menu multiplayer (código da sala / servidor)
    want_text = (st == "multiplayer_view")
    if want_text != _mob["text_on"]:
        try:
            (pygame.key.start_text_input if want_text else pygame.key.stop_text_input)()
        except Exception:
            pass
        _mob["text_on"] = want_text
    real = pygame.display.get_surface()
    kx = vw / max(1, real.get_width()) if real else 1.0
    ky = vh / max(1, real.get_height()) if real else 1.0
    for ev in evs:
        t = ev.type
        if t == pygame.FINGERDOWN:
            x, y = ev.x * vw, ev.y * vh
            _mob["fingers"][ev.finger_id] = (x, y)
            if playing:
                _mob_finger_down_playing(ev.finger_id, x, y)
            elif _mob["primary"] is None:
                _mob["primary"] = ev.finger_id
                _mob["mouse_pos"] = (int(x), int(y))
                _mob["mouse_down"] = True
                _mob["swipe"] = 0.0
                out.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(int(x), int(y)), button=1))
        elif t == pygame.FINGERMOTION:
            x, y = ev.x * vw, ev.y * vh
            _mob["fingers"][ev.finger_id] = (x, y)
            if ev.finger_id == _mob["primary"] and not playing:
                _mob["mouse_pos"] = (int(x), int(y))
                _mob["swipe"] += ev.dy * vh
                if abs(_mob["swipe"]) > 70:         # arrastar para rolar listas (ex.: cartas)
                    out.append(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=(-1 if _mob["swipe"] < 0 else 1), flipped=False))
                    _mob["swipe"] = 0.0
        elif t == pygame.FINGERUP:
            _mob["fingers"].pop(ev.finger_id, None)
            _mob["roles"].pop(ev.finger_id, None)
            _mob["origin"].pop(ev.finger_id, None)
            if ev.finger_id == _mob["primary"]:
                _mob["primary"] = None
                _mob["mouse_down"] = False
                out.append(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=_mob["mouse_pos"], button=1))
        elif t == pygame.TEXTINPUT:
            for ch in ev.text:
                out.append(pygame.event.Event(pygame.KEYDOWN, key=(ord(ch.lower()) if ord(ch) < 128 else 0), mod=0, unicode=ch))
        elif t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            # mouse físico / simulação no PC: converte para coordenadas lógicas
            px, py = ev.pos
            lp = (int(px * kx), int(py * ky))
            _mob["mouse_pos"] = lp
            if t == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                _mob["mouse_down"] = True
            elif t == pygame.MOUSEBUTTONUP and ev.button == 1:
                _mob["mouse_down"] = False
            d = dict(ev.__dict__)
            d["pos"] = lp
            out.append(pygame.event.Event(t, **d))
        else:
            out.append(ev)
    return out


if MOBILE:
    _real_event_get = pygame.event.get

    def _mobile_event_get(*a, **k):
        return _mob_hook_events(_real_event_get(*a, **k))

    pygame.event.get = _mobile_event_get
    pygame.mouse.get_pos = lambda: _mob["mouse_pos"]
    pygame.mouse.get_pressed = lambda *a, **k: (bool(_mob["mouse_down"]) and _mob_state() != "playing", False, False)
    pygame.mouse.set_visible = lambda *a, **k: None


def mobile_draw_touch_controls(s, game):
    """Joysticks flutuantes (multitoque) + botões. Substitui draw_touch_controls no celular."""
    game.touch_mode = True
    game.touch_ui_captured = True            # nunca atira "por clique" no celular
    R = MOBILE_STICK_R
    dt_ = 1 / 60
    lay = _mob_layout()
    vec = {"move": (0.0, 0.0), "aim": (0.0, 0.0)}
    active = {}
    for fid, role in _mob["roles"].items():
        if role in vec and fid in _mob["fingers"]:
            ox, oy = _mob["origin"][fid]
            fx, fy = _mob["fingers"][fid]
            dx, dy = (fx - ox) / R, (fy - oy) / R
            m = math.hypot(dx, dy)
            if m > 1.0:
                dx, dy, m = dx / m, dy / m, 1.0
            vec[role] = (dx, dy)
            active[role] = ((ox, oy), (fx, fy), m)
    game.touch_left_vec = vec["move"]
    game.touch_right_vec = vec["aim"]

    for role, col, fill, label in (("move", CYAN, (12, 26, 52), "MOVER"), ("aim", GOLD, (18, 22, 48), "MIRAR")):
        if role in active:
            (ox, oy), (fx, fy), m = active[role]
            pygame.draw.circle(s, fill, (int(ox), int(oy)), R)
            pygame.draw.circle(s, col, (int(ox), int(oy)), R, 3)
            kx_ = int(ox + vec[role][0] * (R - 18))
            ky_ = int(oy + vec[role][1] * (R - 18))
            glow_circle(s, col, (kx_, ky_), 24, 2)
        else:
            hx, hy = _mob_stick_home(role)
            pygame.draw.circle(s, fill, (hx, hy), R)
            pygame.draw.circle(s, tuple(c // 2 for c in col), (hx, hy), R, 2)
            draw_text(s, label, TINY, tuple(int(c * .7) for c in col), (hx, hy), True)

    # --- botões -----------------------------------------------------------
    for k in list(_mob["flash"]):
        _mob["flash"][k] -= dt_
        if _mob["flash"][k] <= 0:
            del _mob["flash"][k]
    pressed = _mob["flash"]

    p = game.player
    r = lay["dash"]
    ready = bool(p.dash and p.dash_cd <= 0)
    c = CYAN if ready else (75, 95, 125)
    pygame.draw.ellipse(s, (40, 70, 110) if "dash" in pressed else (16, 32, 60), r)
    pygame.draw.ellipse(s, c, r, 3)
    draw_text(s, "DASH", SMALL, WHITE, r.center, True)
    if p.dash and p.dash_cd > 0:
        draw_text(s, f"{p.dash_cd:.1f}", TINY, (170, 190, 220), (r.centerx, r.bottom - 14), True)

    r = lay["ult"]
    u_ready = p.ult_charge >= 100.0
    c = GOLD if u_ready else PURPLE
    pygame.draw.ellipse(s, (70, 50, 120) if "ult" in pressed else (28, 20, 58), r)
    pygame.draw.ellipse(s, c, r, 4 if u_ready else 3)
    draw_text(s, "ULT!" if u_ready else f"{int(p.ult_charge)}%", MED if u_ready else SMALL, c, r.center, True)

    r = lay["auto"]
    c = GREEN if game.auto_fire else (100, 120, 150)
    pygame.draw.rect(s, (16, 36, 52), r, border_radius=12)
    pygame.draw.rect(s, c, r, 2, border_radius=12)
    draw_text(s, "AUTO: ON" if game.auto_fire else "AUTO: OFF", TINY, c, r.center, True)

    r = lay["pause"]
    pygame.draw.rect(s, (16, 28, 48), r, border_radius=14)
    pygame.draw.rect(s, WHITE, r, 2, border_radius=14)
    pygame.draw.rect(s, WHITE, (r.x + 17, r.y + 15, 7, 26), border_radius=2)
    pygame.draw.rect(s, WHITE, (r.x + 32, r.y + 15, 7, 26), border_radius=2)
    return lay["dash"], lay["ult"], lay["auto"]


ARENA_BIOMES = [
    {
        "name": "Nexus Cibernético",
        "boss_name": "O Quadrado Colossal",
        "bg": (6, 9, 20),
        "grid": (14, 26, 52),
        "sub_grid": (10, 18, 36),
        "border_outer": (95, 20, 40),
        "border_inner": (0, 230, 255),
        "nebula": [((12, 34, 72), 220), ((38, 16, 68), 190), ((10, 48, 64), 170)],
        "star_col": (90, 175, 255),
        "weather": "sparks"
    },
    {
        "name": "Inferno Vulcânico",
        "boss_name": "O Devorador Carmesim",
        "bg": (22, 7, 8),
        "grid": (58, 18, 16),
        "sub_grid": (38, 12, 10),
        "border_outer": (140, 40, 10),
        "border_inner": (255, 130, 20),
        "nebula": [((82, 22, 10), 220), ((68, 34, 8), 190), ((90, 14, 18), 170)],
        "star_col": (255, 155, 50),
        "weather": "embers"
    },
    {
        "name": "Abismo Tóxico",
        "boss_name": "O Núcleo Corrompido",
        "bg": (5, 18, 11),
        "grid": (14, 48, 28),
        "sub_grid": (8, 30, 18),
        "border_outer": (20, 110, 45),
        "border_inner": (50, 255, 120),
        "nebula": [((12, 65, 32), 220), ((28, 72, 18), 190), ((10, 52, 42), 170)],
        "star_col": (90, 255, 140),
        "weather": "spores"
    },
    {
        "name": "Tundra Sub-Zero",
        "boss_name": "O Senhor da Velocidade",
        "bg": (7, 16, 28),
        "grid": (22, 52, 82),
        "sub_grid": (14, 34, 56),
        "border_outer": (40, 110, 170),
        "border_inner": (185, 240, 255),
        "nebula": [((20, 58, 92), 220), ((30, 72, 105), 190), ((18, 48, 84), 170)],
        "star_col": (210, 245, 255),
        "weather": "snow"
    },
    {
        "name": "Dimensão do Vazio",
        "boss_name": "O Colosso Blindado",
        "bg": (13, 5, 24),
        "grid": (44, 16, 76),
        "sub_grid": (26, 9, 48),
        "border_outer": (95, 20, 140),
        "border_inner": (205, 85, 255),
        "nebula": [((58, 14, 88), 220), ((42, 10, 72), 190), ((75, 18, 95), 170)],
        "star_col": (215, 130, 255),
        "weather": "void_rifts"
    },
    {
        "name": "Santuário Celestial",
        "boss_name": "O Rei dos Quadrados",
        "bg": (18, 15, 6),
        "grid": (62, 50, 18),
        "sub_grid": (40, 32, 10),
        "border_outer": (140, 105, 20),
        "border_inner": (255, 215, 60),
        "nebula": [((78, 62, 14), 220), ((64, 45, 12), 190), ((88, 70, 22), 170)],
        "star_col": (255, 230, 120),
        "weather": "divine_light"
    },
    {
        "name": "Caldeira de Magma",
        "boss_name": "O Titã de Magma",
        "bg": (26, 9, 5),
        "grid": (72, 26, 12),
        "sub_grid": (46, 16, 8),
        "border_outer": (165, 50, 12),
        "border_inner": (255, 95, 20),
        "nebula": [((95, 28, 8), 220), ((85, 42, 10), 190), ((105, 18, 12), 170)],
        "star_col": (255, 130, 40),
        "weather": "embers"
    },
    {
        "name": "Cidadela Abissal",
        "boss_name": "O Arquiteto do Vazio",
        "bg": (8, 6, 22),
        "grid": (32, 22, 68),
        "sub_grid": (18, 12, 42),
        "border_outer": (75, 30, 150),
        "border_inner": (160, 110, 255),
        "nebula": [((45, 18, 85), 220), ((32, 14, 68), 190), ((62, 22, 96), 170)],
        "star_col": (185, 145, 255),
        "weather": "void_rifts"
    },
    {
        "name": "Oceano de Neon",
        "boss_name": "O Leviatã Cibernético",
        "bg": (4, 16, 24),
        "grid": (12, 54, 68),
        "sub_grid": (8, 34, 46),
        "border_outer": (15, 120, 135),
        "border_inner": (0, 255, 220),
        "nebula": [((10, 68, 78), 220), ((16, 82, 92), 190), ((8, 52, 68), 170)],
        "star_col": (110, 255, 235),
        "weather": "sparks"
    },
    {
        "name": "Trono Ômega",
        "boss_name": "O Imperador Ômega",
        "bg": (22, 5, 12),
        "grid": (68, 14, 34),
        "sub_grid": (44, 8, 22),
        "border_outer": (155, 18, 55),
        "border_inner": (255, 45, 95),
        "nebula": [((88, 12, 38), 220), ((72, 16, 48), 190), ((98, 18, 32), 170)],
        "star_col": (255, 95, 135),
        "weather": "embers"
    },
    {
        "name": "Jardim Prismático",
        "boss_name": "A Matriarca Prismática",
        "bg": (16, 8, 22),
        "grid": (62, 24, 72),
        "sub_grid": (38, 14, 46),
        "border_outer": (145, 35, 130),
        "border_inner": (255, 110, 230),
        "nebula": [((78, 22, 85), 220), ((24, 68, 88), 190), ((85, 62, 20), 170)],
        "star_col": (255, 175, 245),
        "weather": "divine_light"
    },
    {
        "name": "Horizonte de Eventos",
        "boss_name": "O Devorador de Estrelas",
        "bg": (4, 5, 14),
        "grid": (24, 30, 58),
        "sub_grid": (14, 18, 36),
        "border_outer": (90, 110, 165),
        "border_inner": (225, 245, 255),
        "nebula": [((28, 38, 82), 220), ((52, 24, 88), 190), ((18, 54, 78), 170)],
        "star_col": (240, 250, 255),
        "weather": "void_rifts"
    }
]

ZONE_VARIANTS = [
    {"tag": "Cibernético", "tint": (0, 230, 255), "ability": "cyber_pulse",
     "desc": "Sobrecarga: +10% vel., lasers rápidos e descarga elétrica ao morrer."},
    {"tag": "Ígneo", "tint": (255, 120, 30), "ability": "flame_dash",
     "desc": "Combustão: substitui marcha por Investida Vulcânica e aplica queimadura."},
    {"tag": "Bio-Tóxico", "tint": (55, 255, 120), "ability": "acid_split",
     "desc": "Mutação Ácida: regenera 2% HP/s e substitui tiro simples por Tiro Duplo Ácido."},
    {"tag": "Glacial", "tint": (175, 240, 255), "ability": "cryo_surge",
     "desc": "Crio-Armadura: +12% resistência e surtos de patinação rápida a cada 3,5s."},
    {"tag": "Abissal", "tint": (195, 85, 255), "ability": "void_blink",
     "desc": "Salto de Fase: inimigos ganham Micro-Teleporte dimensional a cada 4s."},
    {"tag": "Celestial", "tint": (255, 215, 65), "ability": "holy_cross",
     "desc": "Égide Solar: +20% HP, cura aliados e substitui tiro por Feixe em Cruz."},
    {"tag": "Magmático", "tint": (255, 85, 20), "ability": "magma_burst",
     "desc": "Núcleo Eruptivo: explode em 3 projéteis de lava ao ser derrotado."},
    {"tag": "Espectral", "tint": (150, 115, 255), "ability": "wraith_phase",
     "desc": "Manto Etéreo: fica intangível por 0,7s a cada 4,5s e avança mais rápido."},
    {"tag": "Hidro-Neon", "tint": (0, 250, 215), "ability": "tidal_wave",
     "desc": "Maré Neon: substitui movimento reto por avanço senoidal e rajada dupla."},
    {"tag": "Ômega", "tint": (255, 45, 95), "ability": "omega_frenzy",
     "desc": "Protocolo Ômega: abaixo de 60% HP entra em frenesi (+50% vel. e tiro)."},
    {"tag": "Prismático", "tint": (255, 120, 235), "ability": "prism_refract",
     "desc": "Refração RGB: reflete projéteis periódicos e dispara leque cromático triplo."},
    {"tag": "Cósmico", "tint": (225, 245, 255), "ability": "cosmic_homing",
     "desc": "Gravidade Estelar: puxa o jogador de perto e dispara orbes perseguidores."}
]

# ----------------------------------------------------------------------------
# SISTEMA DE SKINS (COM ATAQUES ESPECIAIS ÚNICOS POR COR), LOJA E CONQUISTAS
# ----------------------------------------------------------------------------
SKINS = [
    {
        "id": "classic",
        "name": "Azul Clássico",
        "desc": "O núcleo original de energia ciano puro.",
        "ult_name": "CATACLISMO DE PLASMA",
        "ult_style": "plasma",
        "req_text": "Desbloqueado desde o início",
        "coin_cost": 0,
        "body": (0, 180, 255),
        "glow": (0, 110, 215),
        "shoe": (30, 110, 190),
        "bullet": (0, 230, 255),
        "trail": (20, 100, 200)
    },
    {
        "id": "emerald",
        "name": "Esmeralda Tóxica",
        "desc": "Supremo: Tempestade Radioativa de esporos ácidos.",
        "ult_name": "TEMPESTADE RADIOATIVA",
        "ult_style": "toxic",
        "req_text": "50 Abates ou 150 Moedas",
        "req_ach": "kills_50",
        "coin_cost": 150,
        "body": (30, 235, 110),
        "glow": (15, 160, 70),
        "shoe": (20, 130, 65),
        "bullet": (95, 255, 150),
        "trail": (20, 160, 80)
    },
    {
        "id": "crimson",
        "name": "Fúria Carmesim",
        "desc": "Supremo: Erupção Sanguinária de lâminas escarlates.",
        "ult_name": "ERUPÇÃO SANGUINÁRIA",
        "ult_style": "blood",
        "req_text": "Combo 25x ou 250 Moedas",
        "req_ach": "combo_25",
        "coin_cost": 250,
        "body": (255, 50, 75),
        "glow": (195, 20, 45),
        "shoe": (155, 25, 40),
        "bullet": (255, 105, 125),
        "trail": (190, 30, 55)
    },
    {
        "id": "gold",
        "name": "Soberano Dourado",
        "desc": "Supremo: Julgamento Imperial com pilares de luz celeste.",
        "ult_name": "JULGAMENTO IMPERIAL",
        "ult_style": "divine",
        "req_text": "1 Chefe ou 350 Moedas",
        "req_ach": "boss_1",
        "coin_cost": 350,
        "body": (255, 205, 45),
        "glow": (210, 145, 15),
        "shoe": (180, 120, 20),
        "bullet": (255, 235, 110),
        "trail": (205, 155, 30)
    },
    {
        "id": "void",
        "name": "Névoa do Vazio",
        "desc": "Supremo: Colapso Dimensional com fendas gravitacionais.",
        "ult_name": "COLAPSO DIMENSIONAL",
        "ult_style": "void",
        "req_text": "Nível 15 ou 450 Moedas",
        "req_ach": "lvl_15",
        "coin_cost": 450,
        "body": (185, 75, 255),
        "glow": (125, 35, 200),
        "shoe": (110, 40, 165),
        "bullet": (220, 135, 255),
        "trail": (140, 50, 205)
    },
    {
        "id": "solar",
        "name": "Chama Solar",
        "desc": "Supremo: Supernova Incandescente de meteoros solares.",
        "ult_name": "SUPERNOVA INCANDESCENTE",
        "ult_style": "solar",
        "req_text": "200 Abates ou 550 Moedas",
        "req_ach": "kills_200",
        "coin_cost": 550,
        "body": (255, 130, 25),
        "glow": (210, 80, 10),
        "shoe": (175, 65, 15),
        "bullet": (255, 185, 70),
        "trail": (215, 95, 20)
    },
    {
        "id": "frost",
        "name": "Zero Absoluto",
        "desc": "Supremo: Nevasca Sub-Zero de lanças de gelo ártico.",
        "ult_name": "NEVASCA SUB-ZERO",
        "ult_style": "frost",
        "req_text": "5 min vivo ou 650 Moedas",
        "req_ach": "time_300",
        "coin_cost": 650,
        "body": (210, 245, 255),
        "glow": (110, 205, 255),
        "shoe": (100, 175, 220),
        "bullet": (235, 250, 255),
        "trail": (145, 215, 245)
    },
    {
        "id": "prism",
        "name": "Prisma Cósmico (RGB)",
        "desc": "Supremo: Hipernova Prismática de raios arco-íris!",
        "ult_name": "HIPERNOVA PRISMÁTICA",
        "ult_style": "prism",
        "req_text": "Nível 30 ou 900 Moedas",
        "req_ach": "lvl_30",
        "coin_cost": 900,
        "rainbow": True,
        "body": (255, 75, 185),
        "glow": (180, 40, 220),
        "shoe": (140, 50, 200),
        "bullet": (255, 120, 220),
        "trail": (200, 60, 210)
    },
    {
        "id": "archangel",
        "name": "Arcanjo Celestial",
        "desc": "Supremo: Cólera Divina com lanças de luz turquesa.",
        "ult_name": "CÓLERA DO ARCANJO",
        "ult_style": "divine",
        "req_text": "3 Chefes ou 1100 Moedas",
        "coin_cost": 1100,
        "body": (0, 250, 215),
        "glow": (0, 175, 160),
        "shoe": (20, 145, 135),
        "bullet": (160, 255, 240),
        "trail": (0, 200, 180)
    },
    {
        "id": "omega",
        "name": "Soberano Absoluto",
        "desc": "Supremo: Apocalipse Ômega que rasga o espaço-tempo!",
        "ult_name": "APOCALIPSE ÔMEGA",
        "ult_style": "prism",
        "req_text": "1500 Moedas",
        "coin_cost": 1500,
        "body": (255, 40, 85),
        "glow": (220, 20, 60),
        "shoe": (180, 15, 45),
        "bullet": (255, 195, 60),
        "trail": (255, 70, 110)
    }
]

SHOP_UPGRADES = [
    {"id": "dmg", "name": "Núcleo de Ataque", "desc": "+5% Dano Base permanente por nível", "base_cost": 60, "max_lvl": 10},
    {"id": "hp", "name": "Titânio Vital", "desc": "+12 Vida Máxima inicial por nível", "base_cost": 50, "max_lvl": 10},
    {"id": "spd", "name": "Propulsor Leve", "desc": "+4% Velocidade de Movimento por nível", "base_cost": 55, "max_lvl": 8},
    {"id": "mag", "name": "Bobina Magnética", "desc": "+25 Raio de Coleta de Orbes/Moedas", "base_cost": 45, "max_lvl": 8},
    {"id": "greed", "name": "Fortuna Dourada", "desc": "+15% Valor de todas as Moedas apanhadas", "base_cost": 80, "max_lvl": 10}
]

ACHIEVEMENTS = [
    {"id": "kills_50", "name": "Caçador Inicial", "desc": "Elimine 50 inimigos numa partida.", "reward": "Cor: Esmeralda Tóxica"},
    {"id": "combo_25", "name": "Mestre do Combo", "desc": "Alcance um Combo de 25x.", "reward": "Cor: Fúria Carmesim"},
    {"id": "boss_1", "name": "Matador de Gigantes", "desc": "Derrote o seu primeiro Chefe.", "reward": "Cor: Soberano Dourado"},
    {"id": "lvl_15", "name": "Veterano da Arena", "desc": "Alcance o Nível 15.", "reward": "Cor: Névoa do Vazio"},
    {"id": "kills_200", "name": "Exterminador", "desc": "Elimine 200 inimigos numa partida.", "reward": "Cor: Chama Solar"},
    {"id": "time_300", "name": "Imortal do Tempo", "desc": "Sobreviva durante 5 minutos (05:00).", "reward": "Cor: Zero Absoluto"},
    {"id": "lvl_30", "name": "Lenda Suprema", "desc": "Alcance o Nível 30.", "reward": "Cor: Prisma Cósmico (RGB)"},
    {"id": "coins_500", "name": "Barão do Ouro", "desc": "Acumule 500 Moedas na sua conta.", "reward": "+100 Moedas de Bónus"}
]

if MOBILE:
    screen = mobile_init_display()
    W, H = screen.get_size()
else:
    screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
pygame.display.set_caption(TITLE)
clock = pygame.time.Clock()

def _make_font(size, bold=False):
    """Fonte com cadeia de fallback (segoeui só existe no Windows)."""
    _bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts",
                            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    if os.path.exists(_bundled):
        try:
            return pygame.font.Font(_bundled, size)
        except Exception:
            pass
    for name in ("segoeui", "arial", "dejavusans", "liberationsans", "helvetica", "freesans"):
        try:
            path = pygame.font.match_font(name, bold=bold)
        except Exception:
            path = None
        if path:
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    return pygame.font.Font(None, int(size * 1.3))

FONT = _make_font(18)
SMALL = _make_font(14)
TINY = _make_font(12, True)
MED = _make_font(24, True)
BIG = _make_font(42, True)
HUGE = _make_font(58, True)

# Cartas de melhoria (formato: losango com o nome + corpo alongado com a descrição)
CARD_NAME_FONT = _make_font(19, True)
CARD_NAME_FONT_S = _make_font(15, True)
CARD_DESC_FONT = _make_font(23, True)
CARD_DESC_FONT_S = _make_font(19, True)
CARD_W, CARD_H, CARD_GAP, CARD_Y = 250, 480, 56, 160

# ----------------------------------------------------------------------------
# SINTETIZADOR DE ÁUDIO
# ----------------------------------------------------------------------------
def generate_sound(freq_start, freq_end, duration, volume=0.15, wave_type="sine"):
    if not has_sound:
        return None
    sample_rate = 44100
    n_samples = int(round(duration * sample_rate))
    buf = bytearray(n_samples * 4)
    max_amp = int(32767 * volume)
    phase = 0.0
    for s in range(n_samples):
        prog = s / max(1, n_samples)
        env = (1.0 - prog) ** 1.4
        freq = freq_start + (freq_end - freq_start) * prog
        phase += 2.0 * math.pi * freq / sample_rate
        if wave_type == "sine":
            raw = math.sin(phase)
        elif wave_type == "square":
            raw = 1.0 if math.sin(phase) >= 0 else -1.0
        elif wave_type == "saw":
            raw = 2.0 * ((phase / (2 * math.pi)) - math.floor(0.5 + phase / (2 * math.pi)))
        elif wave_type == "noise":
            raw = random.uniform(-1.0, 1.0) * math.sin(phase * 0.25)
        else:
            raw = math.sin(phase)
        val = int(max_amp * env * raw)
        lo = val & 0xff
        hi = (val >> 8) & 0xff
        idx = s * 4
        buf[idx] = lo
        buf[idx + 1] = hi
        buf[idx + 2] = lo
        buf[idx + 3] = hi
    try:
        return pygame.mixer.Sound(buffer=buf)
    except Exception:
        return None

SOUNDS = {}
if has_sound:
    SOUNDS["shoot"] = generate_sound(680, 260, 0.05, 0.07, "sine")
    SOUNDS["hit"] = generate_sound(220, 75, 0.11, 0.14, "square")
    SOUNDS["crit"] = generate_sound(880, 440, 0.08, 0.11, "saw")
    SOUNDS["kill"] = generate_sound(180, 65, 0.13, 0.11, "saw")
    SOUNDS["boom"] = generate_sound(140, 32, 0.28, 0.18, "noise")
    SOUNDS["xp"] = generate_sound(820, 1240, 0.045, 0.05, "sine")
    SOUNDS["coin"] = generate_sound(980, 1560, 0.07, 0.09, "sine")
    SOUNDS["levelup"] = generate_sound(380, 920, 0.42, 0.16, "sine")
    SOUNDS["boss"] = generate_sound(160, 55, 0.85, 0.20, "saw")
    SOUNDS["dash"] = generate_sound(320, 880, 0.16, 0.11, "sine")
    SOUNDS["select"] = generate_sound(480, 720, 0.08, 0.13, "sine")
    SOUNDS["hover"] = generate_sound(360, 400, 0.02, 0.04, "sine")
    SOUNDS["heal"] = generate_sound(420, 780, 0.18, 0.09, "sine")
    SOUNDS["ultimate"] = generate_sound(120, 960, 0.65, 0.22, "saw")
    SOUNDS["chest"] = generate_sound(520, 1180, 0.35, 0.16, "sine")
    SOUNDS["zap"] = generate_sound(950, 310, 0.07, 0.09, "square")
    SOUNDS["achievement"] = generate_sound(440, 1320, 0.55, 0.19, "sine")

def play_sound(name):
    if has_sound and name in SOUNDS and SOUNDS[name] and game.settings["volume"] > 0:
        SOUNDS[name].set_volume(game.settings["volume"])
        SOUNDS[name].play()

# ----------------------------------------------------------------------------
# FUNÇÕES UTILITÁRIAS E CACHES DE ALTO DESEMPENHO
# ----------------------------------------------------------------------------
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def vec_norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d else (0.0, 0.0)

TEXT_CACHE = {}

_GLYPH_OK = {}
def _sanitize_text(text, font):
    """Remove caracteres que a fonte nao possui (emoji etc.), em vez de mostrar quadradinhos."""
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ord(ch) < 0x250:
            out.append(ch)
            continue
        k = (id(font), ch)
        ok = _GLYPH_OK.get(k)
        if ok is None:
            try:
                m = font.metrics(ch)
                ok = bool(m) and m[0] is not None
            except Exception:
                ok = True
            _GLYPH_OK[k] = ok
        if ok:
            out.append(ch)
    return "".join(out)


# ----------------------------------------------------------------------------
# SISTEMA MULTILÍNGUE (PORTUGUÊS BR, ENGLISH, ESPAÑOL)
# ----------------------------------------------------------------------------
LANG_CUR = "pt"
TR_CACHE = {}

I18N_EXACT = {
    "en": {
        # Menu Principal & Navegação
        "JOGAR": "PLAY",
        "PERSONAGENS": "CHARACTERS",
        "MASCOTES": "PETS",
        "MASCOTES (PETS)": "COMPANION PETS",
        "CARTAS": "CARDS",
        "CARTAS DE MELHORIA": "UPGRADE CARDS",
        "INIMIGOS": "ENEMIES",
        "INIMIGOS E CHEFES": "ENEMIES & BOSSES",
        "BIOMAS": "BIOMES",
        "BIOMAS DA ARENA": "ARENA BIOMES",
        "CONQUISTAS": "ACHIEVEMENTS",
        "SALA DE CONQUISTAS": "ACHIEVEMENTS HALL",
        "MULTIJOGADOR": "MULTIPLAYER",
        "LOBBY MULTIJOGADOR EM TEMPO REAL": "REAL-TIME MULTIPLAYER LOBBY",
        "LOJA": "SHOP",
        "MERCADO DE MOEDAS": "COIN MARKET",
        "COMO JOGAR": "HOW TO PLAY",
        "COMO JOGAR & COMANDOS TÁTICOS": "HOW TO PLAY & TACTICAL CONTROLS",
        "CONFIGURAÇÕES": "SETTINGS",
        "SAIR": "EXIT",
        "VOLTAR": "BACK",
        "VOLTAR AO MENU": "BACK TO MENU",
        "ANTERIOR": "PREVIOUS",
        "PRÓXIMA": "NEXT",
        "CONTINUAR": "CONTINUE",
        "CONTINUAR JOGO": "CONTINUE GAME",
        "NOVO JOGO": "NEW GAME",
        "SLOT VAZIO": "EMPTY SLOT",
        "Clique para iniciar uma": "Click to start a",
        "nova partida neste slot.": "new match in this slot.",
        "Nenhuma carta ainda": "No cards acquired yet",
        "Nenhuma carta coletada ainda nesta partida.": "No cards collected yet in this match.",
        "ESCOLHA UM SLOT DE SALVAMENTO": "CHOOSE A SAVE SLOT",
        "O seu progresso, nível e habilidades das cartas são gravados automaticamente no slot escolhido": "Your progress, level and card abilities are automatically saved in the chosen slot",
        "Nova partida solo • escolha um slot": "New solo match • choose a slot",
        "Co-op e PvP 1v1": "Co-op & 1v1 PvP",
        "MELHOR NÍVEL": "BEST LEVEL",
        "MAIS ABATES": "MOST KILLS",
        "MAIOR TEMPO": "BEST TIME",
        "COMBO MÁX": "MAX COMBO",
        "MOEDAS": "COINS",
        "MOEDAS GANHAS": "COINS EARNED",
        "TEMPO": "TIME",
        "NÍVEL": "LEVEL",
        "ABATES": "KILLS",
        "CHEFES": "BOSSES",
        "RECORDE!": "NEW RECORD!",
        "SETAS/TAB: navegar    ENTER: selecionar    F11: tela cheia    ESC: sair": "ARROWS/TAB: navigate    ENTER: select    F11: fullscreen    ESC: exit",
        # Configurações
        "IDIOMA / LANGUAGE:": "LANGUAGE / IDIOMA:",
        "Tremor de Câmara (Trauma)": "Camera Shake (Trauma)",
        "Efeitos Visuais & Clima": "Visual Effects & Weather",
        "Números de Dano Flutuantes": "Floating Damage Numbers",
        "Auto-Mira Inteligente": "Smart Auto-Aim",
        "Mostrar Hitboxes (F3)": "Show Hitboxes (F3)",
        "Qualidade Gráfica": "Graphics Quality",
        "Reduzir Flashes (Fotossensível)": "Reduce Flashes (Photosensitive)",
        "HUD Compacta": "Compact HUD",
        "Tela Cheia (F11)": "Fullscreen (F11)",
        "LIGADO": "ON",
        "DESLIGADO": "OFF",
        "BAIXA": "LOW",
        "MÉDIA": "MEDIUM",
        "ALTA": "HIGH",
        # Pausa & Fim de Jogo
        "PAUSADO": "PAUSED",
        "PERSONAGEM / ATAQUE ESPECIAL": "CHARACTER / SPECIAL ATTACK",
        "SALVAR E VOLTAR AOS SLOTS": "SAVE & RETURN TO SLOTS",
        "SALVAR E IR AO MENU": "SAVE & RETURN TO MENU",
        "REINICIAR SLOT DO ZERO": "RESTART SLOT FROM ZERO",
        "VOCÊ CAIU EM COMBATE": "YOU FELL IN COMBAT",
        "RECOMEÇAR DO NÍVEL 1": "RESTART FROM LEVEL 1",
        "ESCOLHER OUTRO SLOT": "CHOOSE ANOTHER SLOT",
        "SUBIU DE NÍVEL!": "LEVEL UP!",
        "SORTEAR NOVAS [R] (Custo: 25 Moedas $)": "REROLL CARDS [R] (Cost: 25 Coins $)",
        # HUD & Combate
        "CHEFE EM COMBATE": "BOSS IN COMBAT",
        "ALERTA DE CHEFE COLOSSAL!": "COLOSSAL BOSS WARNING!",
        "ATAQUE ESPECIAL: INVESTIDA!": "SPECIAL ATTACK: CHARGE!",
        "INVENTÁRIO & TELEMETRIA TÁTICA [TAB]": "INVENTORY & TACTICAL TELEMETRY [TAB]",
        "F5: Salvar Rápido  |  ESC: Pausa  |  TAB: Inventário": "F5: Quick Save  |  ESC: Pause  |  TAB: Inventory",
        "SUPREMO": "ULTIMATE",
        "IMPULSO": "DASH",
        "AUTO-TIRO": "AUTO-FIRE",
        "MASCOTE": "PET",
        "PRONTO": "READY",
        "BLOQ.": "LOCKED",
        "ATIVO": "ACTIVE",
        "NENHUM": "NONE",
        "INVULNERÁVEL": "INVULNERABLE",
        "FRENESI": "FRENZY",
        "ÚLTIMA CHANCE": "LAST CHANCE",
        "ÚLTIMA CHANCE!": "LAST CHANCE!",
        "QUEIMANDO": "BURNING",
        "ENVENENADO": "POISONED",
        "NO GELO": "ON ICE",
        "IMPULSO DE ENERGIA": "ENERGY BOOST",
        "ESQUIVA!": "DODGE!",
        "ESCUDO!": "SHIELD!",
        "+8 ESCUDO": "+8 SHIELD",
        "VAPOR!": "STEAM!",
        "+BÓNUS SOBREVIVÊNCIA & MOEDAS!": "+SURVIVAL & COINS BONUS!",
        "MOVER": "MOVE",
        "MIRA 360°": "360° AIM",
        "Dano": "Damage",
        "Cadência": "Fire Rate",
        "Velocidade": "Speed",
        "Crítico": "Critical",
        "Armadura": "Armor",
        "BAÚ": "CHEST",
        # Multijogador
        "SALA ATIVA:": "ACTIVE ROOM:",
        "DIGITE O CÓDIGO NO TECLADO...": "TYPE ROOM CODE ON KEYBOARD...",
        "CRIAR SALA": "CREATE ROOM",
        "CONECTAR": "CONNECT",
        "SINCRONIZAR NUVEM AGORA": "SYNC CLOUD NOW",
        "JOGADOR 1 (VOCÊ)": "PLAYER 1 (YOU)",
        "JOGADOR 2 (PARCEIRO / RIVAL)": "PLAYER 2 (PARTNER / RIVAL)",
        "JOGADOR 2 (REDE ATIVA)": "PLAYER 2 (NETWORK ACTIVE)",
        "SKIN P2": "P2 SKIN",
        "MASCOTE P2": "P2 PET",
        "INICIAR CO-OP SOBREVIVÊNCIA": "START CO-OP SURVIVAL",
        "INICIAR DUELO PVP 1V1": "START 1V1 PVP DUEL",
        "Co-op: Lutem juntos contra as hordas e Chefes com Reanimação!  |  PvP: Duelo direto 1v1 na arena (Melhor de 3)!": "Co-op: Fight together against hordes & Bosses with Revive!  |  PvP: Direct 1v1 arena duel (Best of 3)!",
        "PARCEIRO ORB": "PARTNER ORB",
        "RIVAL ORB": "RIVAL ORB",
        "CAÍDO! APROXIME-SE!": "DOWNED! GET CLOSE!",
        "CAÍDO! AGUARDANDO REANIMAÇÃO...": "DOWNED! WAITING FOR REVIVE...",
        "PARCEIRO CAÍDO! APROXIME-SE PARA REANIMAR!": "PARTNER DOWN! GET CLOSE TO REVIVE!",
        "PARCEIRO REANIMADO!": "PARTNER REVIVED!",
        "REANIMADO PELO PARCEIRO!": "REVIVED BY PARTNER!",
        "ALIADO REANIMADO PELO SUPREMO!": "ALLY REVIVED BY ULTIMATE!",
        "REANIMADO PELO SUPREMO ALIADO!": "REVIVED BY ALLY ULTIMATE!",
        "DUELO PVP 1V1 — RODADA 1!": "1V1 PVP DUEL — ROUND 1!",
        "FASE 2: ENFURECIDO!": "PHASE 2: ENRAGED!",
        "FASE 3: APOCALIPSE!": "PHASE 3: APOCALYPSE!",
        # Botões de Loja, Skins e Pets
        "NÍVEL MÁXIMO": "MAX LEVEL",
        "EQUIPADO": "EQUIPPED",
        "EQUIPAR COR": "EQUIP SKIN",
        "EQUIPAR PET": "EQUIP PET",
        # Biomas & Clima
        "O cenário muda a cada chefe derrotado.": "The arena biome changes after each defeated boss.",
        "Bioma inicial": "Starting biome",
        "Nexus Cibernético": "Cybernetic Nexus",
        "Inferno Vulcânico": "Volcanic Inferno",
        "Abismo Tóxico": "Toxic Abyss",
        "Tundra Sub-Zero": "Sub-Zero Tundra",
        "Dimensão do Vazio": "Void Dimension",
        "Santuário Celestial": "Celestial Sanctuary",
        "Caldeira de Magma": "Magma Caldera",
        "Cidadela Abissal": "Abyssal Citadel",
        "Oceano de Neon": "Neon Ocean",
        "Trono Ômega": "Omega Throne",
        "Jardim Prismático": "Prismatic Garden",
        "Horizonte de Eventos": "Event Horizon",
        "Faíscas": "Sparks",
        "Brasas": "Embers",
        "Esporos": "Spores",
        "Neve": "Snow",
        "Fendas do vazio": "Void rifts",
        "Luz divina": "Divine light",
        # Raridades
        "Comum": "Common",
        "Incomum": "Uncommon",
        "Rara": "Rare",
        "Épica": "Epic",
        "Lendária": "Legendary",
        "Mítica": "Mythic",
        "Divina": "Divine",
        "Suprema": "Supreme",
        "Primordial": "Primordial",
        "Transcendente": "Transcendent",
        # Como Jogar
        "WASD / SETAS": "WASD / ARROWS",
        "Mova a sua personagem pela arena desviando de cercos e perigos de terreno.": "Move your character across the arena dodging swarms and terrain hazards.",
        "RATO / TECLA E": "MOUSE / E KEY",
        "Aponte com o Rato. Botão Esquerdo dispara; Tecla E ou Botão Direito ativa Auto-Tiro.": "Aim with Mouse. Left Click shoots; E Key or Right Click toggles Auto-Fire.",
        "TECLA Q (100%)": "Q KEY (100%)",
        "Dispara o ATAQUE ESPECIAL SUPREMO exclusivo da Cor (Skin) equipada!": "Unleashes the exclusive ULTIMATE SPECIAL ATTACK of your equipped Skin!",
        "MOEDAS DE OURO": "GOLD COINS",
        "Colete moedas para comprar Upgrades Permanentes, Skins e Mascotes na Loja.": "Collect coins to buy Permanent Upgrades, Skins and Pets in the Shop.",
        "BAÚS DOURADOS": "GOLDEN CHESTS",
        "Elites e Chefes largam Baús de Relíquia com moedas, cura, escudo e bónus permanentes.": "Elites and Bosses drop Relic Chests with coins, healing, shield and permanent bonuses.",
        "TECLAS 1, 2, 3, R": "KEYS 1, 2, 3, R",
        "Ao subir de nível, escolha 1 entre 3 cartas holográficas ou pressione R para sortear novas.": "On level up, choose 1 of 3 holographic cards or press R to reroll new options.",
        "TECLA F5": "F5 KEY",
        "Gravação Rápida instantânea na subpasta SAVES/ (além do Auto-Save automático).": "Instant Quick Save into the SAVES/ subfolder (in addition to automatic Auto-Save).",
        "ESC / F3 / TAB": "ESC / F3 / TAB",
        "ESC pausa a partida, F3 exibe Hitboxes e TAB abre o Inventário Tático em tempo real.": "ESC pauses the match, F3 shows Hitboxes and TAB opens the real-time Tactical Inventory.",
        # Skins & Supremos
        "Azul Clássico": "Classic Blue",
        "O núcleo original de energia ciano puro.": "The original core of pure cyan energy.",
        "CATACLISMO DE PLASMA": "PLASMA CATACLYSM",
        "Desbloqueado desde o início": "Unlocked from the start",
        "Esmeralda Tóxica": "Toxic Emerald",
        "Supremo: Tempestade Radioativa de esporos ácidos.": "Ultimate: Radioactive Storm of acid spores.",
        "TEMPESTADE RADIOATIVA": "RADIOACTIVE STORM",
        "50 Abates ou 150 Moedas": "50 Kills or 150 Coins",
        "Fúria Carmesim": "Crimson Fury",
        "Supremo: Erupção Sanguinária de lâminas escarlates.": "Ultimate: Bloodthirsty Eruption of scarlet blades.",
        "ERUPÇÃO SANGUINÁRIA": "BLOOD ERUPTION",
        "Combo 25x ou 250 Moedas": "25x Combo or 250 Coins",
        "Soberano Dourado": "Golden Sovereign",
        "Supremo: Julgamento Imperial com pilares de luz celeste.": "Ultimate: Imperial Judgment with celestial light pillars.",
        "JULGAMENTO IMPERIAL": "IMPERIAL JUDGMENT",
        "1 Chefe ou 350 Moedas": "1 Boss or 350 Coins",
        "Névoa do Vazio": "Void Mist",
        "Supremo: Colapso Dimensional com fendas gravitacionais.": "Ultimate: Dimensional Collapse with gravity rifts.",
        "COLAPSO DIMENSIONAL": "DIMENSIONAL COLLAPSE",
        "Nível 15 ou 450 Moedas": "Level 15 or 450 Coins",
        "Chama Solar": "Solar Flame",
        "Supremo: Supernova Incandescente de meteoros solares.": "Ultimate: Incandescent Supernova of solar meteors.",
        "SUPERNOVA INCANDESCENTE": "BLAZING SUPERNOVA",
        "200 Abates ou 550 Moedas": "200 Kills or 550 Coins",
        "Zero Absoluto": "Absolute Zero",
        "Supremo: Nevasca Sub-Zero de lanças de gelo ártico.": "Ultimate: Sub-Zero Blizzard of arctic ice spears.",
        "NEVASCA SUB-ZERO": "SUB-ZERO BLIZZARD",
        "5 min vivo ou 650 Moedas": "Survive 5 min or 650 Coins",
        "Prisma Cósmico (RGB)": "Cosmic Prism (RGB)",
        "Supremo: Hipernova Prismática de raios arco-íris!": "Ultimate: Prismatic Hypernova of rainbow rays!",
        "HIPERNOVA PRISMÁTICA": "PRISMATIC HYPERNOVA",
        "Nível 30 ou 900 Moedas": "Level 30 or 900 Coins",
        "Arcanjo Celestial": "Celestial Archangel",
        "Supremo: Cólera Divina com lanças de luz turquesa.": "Ultimate: Divine Wrath with turquoise light spears.",
        "CÓLERA DO ARCANJO": "ARCHANGEL'S WRATH",
        "3 Chefes ou 1100 Moedas": "3 Bosses or 1100 Coins",
        "Soberano Absoluto": "Absolute Sovereign",
        "Supremo: Apocalipse Ômega que rasga o espaço-tempo!": "Ultimate: Omega Apocalypse that tears spacetime!",
        "APOCALIPSE ÔMEGA": "OMEGA APOCALYPSE",
        "1500 Moedas": "1500 Coins",
        # Loja
        "Núcleo de Ataque": "Attack Core",
        "+5% Dano Base permanente por nível": "+5% permanent Base Damage per level",
        "Titânio Vital": "Vital Titanium",
        "+12 Vida Máxima inicial por nível": "+12 starting Max Health per level",
        "Propulsor Leve": "Light Thruster",
        "+4% Velocidade de Movimento por nível": "+4% Movement Speed per level",
        "Bobina Magnética": "Magnetic Coil",
        "+25 Raio de Coleta de Orbes/Moedas": "+25 Orb/Coin Pickup Radius per level",
        "Fortuna Dourada": "Golden Fortune",
        "+15% Valor de todas as Moedas apanhadas": "+15% Value of all collected Coins",
        # Conquistas
        "Caçador Inicial": "Rookie Hunter",
        "Elimine 50 inimigos numa partida.": "Eliminate 50 enemies in a single match.",
        "Cor: Esmeralda Tóxica": "Skin: Toxic Emerald",
        "Mestre do Combo": "Combo Master",
        "Alcance um Combo de 25x.": "Reach a 25x Combo.",
        "Cor: Fúria Carmesim": "Skin: Crimson Fury",
        "Matador de Gigantes": "Giant Slayer",
        "Derrote o seu primeiro Chefe.": "Defeat your first Boss.",
        "Cor: Soberano Dourado": "Skin: Golden Sovereign",
        "Veterano da Arena": "Arena Veteran",
        "Alcance o Nível 15.": "Reach Level 15.",
        "Cor: Névoa do Vazio": "Skin: Void Mist",
        "Exterminador": "Exterminator",
        "Elimine 200 inimigos numa partida.": "Eliminate 200 enemies in a single match.",
        "Cor: Chama Solar": "Skin: Solar Flame",
        "Imortal do Tempo": "Time Immortal",
        "Sobreviva durante 5 minutos (05:00).": "Survive for 5 minutes (05:00).",
        "Cor: Zero Absoluto": "Skin: Absolute Zero",
        "Lenda Suprema": "Supreme Legend",
        "Alcance o Nível 30.": "Reach Level 30.",
        "Cor: Prisma Cósmico (RGB)": "Skin: Cosmic Prism (RGB)",
        "Barão do Ouro": "Gold Baron",
        "Acumule 500 Moedas na sua conta.": "Accumulate 500 Coins in your account.",
        "+100 Moedas de Bónus": "+100 Bonus Coins",
        # Mascotes
        "Gelatina Azul": "Blue Slime",
        "Atira mini-projéteis no inimigo mais próximo.": "Fires mini-projectiles at the nearest enemy.",
        "Gatinho Relâmpago": "Lightning Kitty",
        "Solta raios que atingem até 3 inimigos a cada 3s.": "Unleashes lightning hitting up to 3 enemies every 3s.",
        "Coruja Sábia": "Wise Owl",
        "+15% de XP e +60 de raio de coleta de orbes.": "+15% XP and +60 orb pickup radius.",
        "Cão Guardião": "Guardian Dog",
        "+8 de escudo a cada 6s e morde quem chega perto.": "+8 shield every 6s and bites nearby enemies.",
        "Dragãozinho de Plasma": "Plasma Dragonet",
        "Lança bolas de fogo explosivas em área a cada 4s.": "Launches explosive area fireballs every 4s.",
        "Fênix Neon": "Neon Phoenix",
        "Cura 6% da vida máxima a cada 8s.": "Heals 6% of max health every 8s.",
        "Drone Cyber-Sniper": "Cyber-Sniper Drone",
        "Dispara lasers de alta precisão e velocidade.": "Fires high-precision, high-velocity lasers.",
        "Serafim Astral": "Astral Seraph",
        "Invoca relâmpagos divinos em cadeia contra os inimigos.": "Summons chained divine lightning against enemies.",
        "Cometa Guardião": "Guardian Comet",
        "Gera escudo periodicamente e protege quando inimigos se aproximam.": "Periodically generates shield and protects when enemies approach.",
        "Filhote do Vazio": "Voidling",
        "Dispara explosões roxas contra grupos de inimigos.": "Fires purple blasts against enemy groups.",
        # Inimigos & Chefes
        "Básico": "Basic",
        "Veloz": "Swift",
        "Tanque": "Tank",
        "Atirador": "Shooter",
        "Regenerador": "Regenerator",
        "Explosivo": "Explosive",
        "Teletransportador": "Teleporter",
        "Blindado": "Armored",
        "Invocador": "Summoner",
        "Ceifador": "Reaper",
        "Piromante": "Pyromancer",
        "Sentinela Laser": "Laser Sentry",
        "Berserker": "Berserker",
        "Elite": "Elite",
        "Aracnídeo": "Arachnid",
        "Anomalia": "Anomaly",
        "Espelho": "Mirror",
        "Parasita": "Parasite",
        "Vórtice": "Vortex",
        "Escudeiro": "Shieldbearer",
        "Bombardeiro": "Bomber",
        "Fantasma": "Ghost",
        "Regenerante": "Regenerating",
        "Gigante": "Giant",
        "Persegue o jogador em linha reta.": "Chases the player in a straight line.",
        "Rápido e frágil: corre para cima de você.": "Fast and fragile: rushes straight at you.",
        "Lento e muito resistente.": "Slow and very tough.",
        "Mantém distância e atira.": "Keeps distance and shoots.",
        "Recupera vida com o tempo.": "Regenerates health over time.",
        "Explode ao morrer, ferindo quem estiver perto.": "Explodes on death, damaging nearby units.",
        "Teleporta para perto de você.": "Teleports close to you.",
        "Recebe 25% menos dano dos seus tiros.": "Takes 25% less damage from your shots.",
        "Invoca inimigos menores.": "Summons smaller enemies.",
        "Perseguidor rápido, resistente e de dano alto.": "Fast, tough chaser with high damage.",
        "Mantém distância e lança 3 projéteis em leque.": "Keeps distance and fires a 3-shot spread.",
        "Mantém distância e dispara tiros rápidos.": "Keeps distance and fires rapid lasers.",
        "Acelera 65% quando abaixo de 50% da vida.": "Speeds up by 65% when below 50% health.",
        "Versão perigosa. A partir do nível 8 pode ter afixo.": "Dangerous elite. From level 8 can gain an affix.",
        "Avança em zigue-zague para flanquear.": "Advances in a zig-zag pattern to flank you.",
        "Persegue e dispara 4 projéteis em leque.": "Chases and fires a 4-projectile spread.",
        "O Quadrado Colossal": "The Colossal Square",
        "O Devorador Carmesim": "The Crimson Devourer",
        "O Núcleo Corrompido": "The Corrupted Core",
        "O Senhor da Velocidade": "The Speed Lord",
        "O Colosso Blindado": "The Armored Colossus",
        "O Rei dos Quadrados": "The King of Squares",
        "O Titã de Magma": "The Magma Titan",
        "O Arquiteto do Vazio": "The Void Architect",
        "O Leviatã Cibernético": "The Cyber Leviathan",
        "O Imperador Ômega": "The Omega Emperor",
        "A Matriarca Prismática": "The Prismatic Matriarch",
        "O Devorador de Estrelas": "The Star Devourer",
        # Cartas de Melhoria
        "Vitalidade": "Vitality",
        "Vida máxima +20.": "Max Health +20.",
        "Coração Extra": "Extra Heart",
        "Vida máxima +35.": "Max Health +35.",
        "Regeneração": "Regeneration",
        "Recupera 1,2 de vida por segundo.": "Regenerates 1.2 health per second.",
        "Cura Emergencial": "Emergency Heal",
        "Recupera 40% da vida máxima imediatamente.": "Restores 40% of max health immediately.",
        "Pele Resistente": "Tough Skin",
        "Reduz dano recebido em 10%.": "Reduces damage taken by 10%.",
        "Armadura Reforçada": "Reinforced Armor",
        "Reduz dano recebido em 15%.": "Reduces damage taken by 15%.",
        "Escudo de Energia": "Energy Shield",
        "Concede 35 pontos de escudo recarregável.": "Grants 35 points of rechargeable shield.",
        "Muralha de Plasma": "Plasma Wall",
        "O teu escudo regenera automaticamente 1,5/s.": "Your shield automatically regenerates 1.5/s.",
        "Última Chance": "Last Chance",
        "Uma vez, evita a morte, explode a tela e deixa 20% HP.": "Once, prevents death, blasts the screen and leaves 20% HP.",
        "Recuperação": "Recovery",
        "Aumenta toda cura recebida em 25%.": "Increases all healing received by 25%.",
        "Barreira Temporal": "Temporal Barrier",
        "Invulnerabilidade após dano +0,35 s.": "Invulnerability after taking damage +0.35 s.",
        "Triângulos Poderosos": "Mighty Triangles",
        "Dano dos projéteis +20%.": "Projectile damage +20%.",
        "Disparo Rápido": "Rapid Fire",
        "Velocidade de disparo +16%.": "Fire rate +16%.",
        "Projétil Veloz": "Swift Projectile",
        "Velocidade dos projéteis +25%.": "Projectile speed +25%.",
        "Tiro Duplo": "Double Shot",
        "Adiciona +1 projétil por disparo.": "Adds +1 projectile per shot.",
        "Tiro Triplo": "Triple Shot",
        "Garante pelo menos 3 projéteis em leque.": "Guarantees at least 3 projectiles in a spread.",
        "Perfuração": "Piercing",
        "Projéteis atravessam +1 inimigo extra.": "Projectiles pierce +1 extra enemy.",
        "Ricochete": "Ricochet",
        "Projéteis saltam para outro inimigo (+1 salto).": "Projectiles bounce to another enemy (+1 bounce).",
        "Dano Crítico": "Critical Hit",
        "Chance crítica +8 pontos percentuais.": "Critical chance +8 percentage points.",
        "Impacto Brutal": "Brutal Impact",
        "Multiplicador de dano crítico +50%.": "Critical damage multiplier +50%.",
        "Caçador de Elites": "Elite Hunter",
        "Dano contra inimigos especiais +25%.": "Damage against elite enemies +25%.",
        "Matador de Chefes": "Boss Slayer",
        "Dano contra chefes +20%.": "Damage against bosses +20%.",
        "Explosão Triangular": "Triangular Blast",
        "Impactos causam explosão em área.": "Impacts cause an area explosion.",
        "Passos Rápidos": "Quick Steps",
        "Velocidade de movimento +12%.": "Movement speed +12%.",
        "Impulso Azul": "Blue Dash",
        "Espaço ativa avanço invulnerável com recarga.": "Spacebar activates an invulnerable dash with cooldown.",
        "Corpo Leve": "Light Body",
        "Movimento mais ágil (+8% velocidade).": "More agile movement (+8% speed).",
        "Esquiva Energética": "Energy Dodge",
        "Chance de evitar dano +8%.": "Chance to dodge damage +8%.",
        "Aceleração": "Acceleration",
        "Abates concedem +30% velocidade por 2 s.": "Kills grant +30% movement speed for 2 s.",
        "Campo Repulsor": "Repulsor Field",
        "Onda de choque empurra inimigos próximos.": "Shockwave pushes nearby enemies back.",
        "Aprendizado Rápido": "Fast Learner",
        "XP recebido +15%.": "XP gained +15%.",
        "Conhecimento Avançado": "Advanced Knowledge",
        "XP recebido +25%.": "XP gained +25%.",
        "Ímã de Experiência": "Experience Magnet",
        "Raio de coleta de orbes e moedas +100.": "Orb and coin pickup radius +100.",
        "Orbes Valiosos": "Valuable Orbs",
        "Valor dos orbes de XP +20%.": "XP orb value +20%.",
        "Cobiça Dourada": "Golden Greed",
        "Inimigos largam +35% mais Moedas.": "Enemies drop +35% more Coins.",
        "Execução Premiada": "Bounty Execution",
        "Elites concedem +35% XP e +1 sorteio de carta.": "Elites grant +35% XP and +1 card reroll.",
        "Bônus de Sobrevivência": "Survival Bonus",
        "Recebe pacote de XP, cura e moedas a cada 45s.": "Receive an XP, heal and coin care package every 45s.",
        "Caçador Experiente": "Seasoned Hunter",
        "XP de chefes aumentado em +50%.": "Boss XP increased by +50%.",
        "Núcleo Energético": "Energy Core",
        "Dano +20%, mas movimento -8%.": "Damage +20%, but movement speed -8%.",
        "Canhão Azul": "Blue Cannon",
        "Projéteis maiores, +15% dano e empurrão.": "Larger projectiles, +15% damage and knockback.",
        "Sobrecarga": "Overload",
        "A cada 10 s, entra em frenesi de disparo por 2,5 s.": "Every 10 s, enter a firing frenzy for 2.5 s.",
        "Aura Destrutiva": "Destructive Aura",
        "Campo elétrico causa dano contínuo ao redor.": "Electric field deals continuous damage around you.",
        "Dreno Vital": "Life Drain",
        "Recupera vida ao derrotar inimigos.": "Restores health when defeating enemies.",
        "Duplicação Energética": "Energy Duplication",
        "Chance de +25% de disparar projétil extra.": "+25% chance to fire an extra projectile.",
        "Campo de Lentidão": "Slow Field",
        "Congela parcialmente inimigos próximos (-40% vel.).": "Partially freezes nearby enemies (-40% speed).",
        "Explosão ao Morrer": "Death Explosion",
        "Inimigos abatidos têm 22% de chance de explodir.": "Defeated enemies have a 22% chance to explode.",
        "Proteção de Elite": "Elite Protection",
        "Elites derrotados concedem +18 de escudo.": "Defeated elites grant +18 shield.",
        "Fúria Azul": "Blue Fury",
        "Dano +25% quando a vida está abaixo de 40%.": "Damage +25% when health is below 40%.",
        "Evolução Suprema": "Supreme Evolution",
        "Dano +12%, Vida Máx +15 e +1 Sorteio de Carta.": "Damage +12%, Max Health +15 and +1 Card Reroll.",
        "Orbes Orbitais": "Orbital Orbs",
        "Invoca 1 satélite de plasma que gira ao seu redor.": "Summons 1 plasma satellite that orbits around you.",
        "Relâmpago em Cadeia": "Chain Lightning",
        "Impactos têm 22% de chance de eletrocutar 1 inimigo próximo.": "Hits have a 22% chance to electrocute 1 nearby enemy.",
        "Catalisador Supremo": "Ultimate Catalyst",
        "O Ataque Especial [Q] carrega 25% mais rápido.": "Your Special Attack [Q] charges 25% faster.",
        "Ascensão Mítica": "Mythic Ascension",
        "Dano +15%, +1 Projétil, +15 Vida Máx e +15 Escudo.": "Damage +15%, +1 Projectile, +15 Max HP and +15 Shield.",
        "Lâminas Fantasmas": "Phantom Blades",
        "Projéteis ganham +1 Perfuração e +1 Ricochete.": "Projectiles gain +1 Piercing and +1 Ricochet.",
        "Fúria Relâmpago": "Lightning Fury",
        "Cadência de tiro +18% e Velocidade +10%.": "Fire rate +18% and Movement Speed +10%.",
        "Couraça de Titânio": "Titanium Cuirass",
        "Vida Máxima +40, Armadura +8% e +20 Escudo.": "Max Health +40, Armor +8% and +20 Shield.",
        "Chuva de Meteoros": "Meteor Shower",
        "A cada 7 s, invoca explosões solares em até 3 inimigos.": "Every 7 s, calls down solar blasts on up to 3 enemies.",
        "Bênção do Arcanjo": "Archangel's Grace",
        "Regenera 2,5 HP/s, +1,5/s Escudo e +20% Dano Crítico.": "Regenerates 2.5 HP/s, +1.5/s Shield and +20% Crit Damage.",
        "Decreto Supremo": "Supreme Decree",
        "Dano +28%, +1 Projétil, +30 HP Máx e +1 Orbital.": "Damage +28%, +1 Projectile, +30 Max HP and +1 Orbital.",
        "Coração Primordial": "Primordial Heart",
        "Vida máxima +55 e recupera 15% da vida.": "Max Health +55 and restores 15% health.",
        "Marca do Caçador": "Hunter's Mark",
        "30% de chance de marcar o alvo: ele recebe +25% de dano.": "30% chance to mark the target: it takes +25% damage.",
        "Balas Incendiárias": "Incendiary Rounds",
        "35% de chance de queimar o alvo por 3 s (dano contínuo).": "35% chance to burn the target for 3 s (damage over time).",
        "Veneno Neurotóxico": "Neurotoxic Venom",
        "40% de chance de envenenar. O veneno acumula até 5 vezes.": "40% chance to poison. Poison stacks up to 5 times.",
        "Toque Gélido": "Frost Touch",
        "25% de chance de congelar: o inimigo fica 55% mais lento.": "25% chance to freeze: slows the enemy by 55%.",
        "Catalisador Elemental": "Elemental Catalyst",
        "+15% chance de status. Queimar + congelar causa VAPOR (dano em área x2).": "+15% status chance. Burn + Freeze triggers STEAM (2x area damage).",
        "Tempestade Elemental": "Elemental Storm",
        "+12% chance de status e dano contínuo +50%.": "+12% status chance and +50% damage over time.",
    },
    "es": {
        # Menu Principal & Navegación
        "JOGAR": "JUGAR",
        "PERSONAGENS": "PERSONAJES",
        "MASCOTES": "MASCOTAS",
        "MASCOTES (PETS)": "MASCOTAS (PETS)",
        "CARTAS": "CARTAS",
        "CARTAS DE MELHORIA": "CARTAS DE MEJORA",
        "INIMIGOS": "ENEMIGOS",
        "INIMIGOS E CHEFES": "ENEMIGOS Y JEFES",
        "BIOMAS": "BIOMAS",
        "BIOMAS DA ARENA": "BIOMAS DE LA ARENA",
        "CONQUISTAS": "LOGROS",
        "SALA DE CONQUISTAS": "SALA DE LOGROS",
        "MULTIJOGADOR": "MULTIJUGADOR",
        "LOBBY MULTIJOGADOR EM TEMPO REAL": "LOBBY MULTIJUGADOR EN TIEMPO REAL",
        "LOJA": "TIENDA",
        "MERCADO DE MOEDAS": "MERCADO DE MONEDAS",
        "COMO JOGAR": "CÓMO JUGAR",
        "COMO JOGAR & COMANDOS TÁTICOS": "CÓMO JUGAR Y COMANDOS TÁCTICOS",
        "CONFIGURAÇÕES": "CONFIGURACIÓN",
        "SAIR": "SALIR",
        "VOLTAR": "VOLVER",
        "VOLTAR AO MENU": "VOLVER AL MENÚ",
        "ANTERIOR": "ANTERIOR",
        "PRÓXIMA": "SIGUIENTE",
        "CONTINUAR": "CONTINUAR",
        "CONTINUAR JOGO": "CONTINUAR JUEGO",
        "NOVO JOGO": "NUEVO JUEGO",
        "SLOT VAZIO": "RANURA VACÍA",
        "Clique para iniciar uma": "Haz clic para iniciar una",
        "nova partida neste slot.": "nueva partida en esta ranura.",
        "Nenhuma carta ainda": "Ninguna carta todavía",
        "Nenhuma carta coletada ainda nesta partida.": "Aún no has recolectado cartas en esta partida.",
        "ESCOLHA UM SLOT DE SALVAMENTO": "ELIGE UNA RANURA DE GUARDADO",
        "O seu progresso, nível e habilidades das cartas são gravados automaticamente no slot escolhido": "Tu progreso, nivel y habilidades de cartas se guardan automáticamente en la ranura elegida",
        "Nova partida solo • escolha um slot": "Nueva partida solo • elige una ranura",
        "Co-op e PvP 1v1": "Co-op y PvP 1v1",
        "MELHOR NÍVEL": "MEJOR NIVEL",
        "MAIS ABATES": "MÁS BAJAS",
        "MAIOR TEMPO": "MAYOR TIEMPO",
        "COMBO MÁX": "COMBO MÁX",
        "MOEDAS": "MONEDAS",
        "MOEDAS GANHAS": "MONEDAS GANADAS",
        "TEMPO": "TIEMPO",
        "NÍVEL": "NIVEL",
        "ABATES": "BAJAS",
        "CHEFES": "JEFES",
        "RECORDE!": "¡RÉCORD!",
        "SETAS/TAB: navegar    ENTER: selecionar    F11: tela cheia    ESC: sair": "FLECHAS/TAB: navegar    ENTER: seleccionar    F11: pantalla completa    ESC: salir",
        # Configuración
        "IDIOMA / LANGUAGE:": "IDIOMA / LANGUAGE:",
        "Tremor de Câmara (Trauma)": "Temblor de Cámara (Trauma)",
        "Efeitos Visuais & Clima": "Efectos Visuales y Clima",
        "Números de Dano Flutuantes": "Números de Daño Flotantes",
        "Auto-Mira Inteligente": "Auto-Apuntado Inteligente",
        "Mostrar Hitboxes (F3)": "Mostrar Hitboxes (F3)",
        "Qualidade Gráfica": "Calidad Gráfica",
        "Reduzir Flashes (Fotossensível)": "Reducir Destellos (Fotosensible)",
        "HUD Compacta": "HUD Compacta",
        "Tela Cheia (F11)": "Pantalla Completa (F11)",
        "LIGADO": "ACTIVADO",
        "DESLIGADO": "DESACTIVADO",
        "BAIXA": "BAJA",
        "MÉDIA": "MEDIA",
        "ALTA": "ALTA",
        # Pausa & Fin de Partida
        "PAUSADO": "PAUSADO",
        "PERSONAGEM / ATAQUE ESPECIAL": "PERSONAJE / ATAQUE ESPECIAL",
        "SALVAR E VOLTAR AOS SLOTS": "GUARDAR Y VOLVER A RANURAS",
        "SALVAR E IR AO MENU": "GUARDAR E IR AL MENÚ",
        "REINICIAR SLOT DO ZERO": "REINICIAR RANURA DESDE CERO",
        "VOCÊ CAIU EM COMBATE": "HAS CAÍDO EN COMBATE",
        "RECOMEÇAR DO NÍVEL 1": "REINICIAR DESDE NIVEL 1",
        "ESCOLHER OUTRO SLOT": "ELEGIR OTRA RANURA",
        "SUBIU DE NÍVEL!": "¡SUBISTE DE NIVEL!",
        "SORTEAR NOVAS [R] (Custo: 25 Moedas $)": "SORTEAR NUEVAS [R] (Costo: 25 Monedas $)",
        # HUD & Combate
        "CHEFE EM COMBATE": "JEFE EN COMBATE",
        "ALERTA DE CHEFE COLOSSAL!": "¡ALERTA DE JEFE COLOSAL!",
        "ATAQUE ESPECIAL: INVESTIDA!": "¡ATAQUE ESPECIAL: EMBESTIDA!",
        "INVENTÁRIO & TELEMETRIA TÁTICA [TAB]": "INVENTARIO Y TELEMETRÍA TÁCTICA [TAB]",
        "F5: Salvar Rápido  |  ESC: Pausa  |  TAB: Inventário": "F5: Guardado Rápido  |  ESC: Pausa  |  TAB: Inventario",
        "SUPREMO": "SUPREMO",
        "IMPULSO": "IMPULSO",
        "AUTO-TIRO": "AUTO-DISPARO",
        "MASCOTE": "MASCOTA",
        "PRONTO": "LISTO",
        "BLOQ.": "BLOQ.",
        "ATIVO": "ACTIVO",
        "NENHUM": "NINGUNO",
        "INVULNERÁVEL": "INVULNERABLE",
        "FRENESI": "FRENESÍ",
        "ÚLTIMA CHANCE": "ÚLTIMA OPORTUNIDAD",
        "ÚLTIMA CHANCE!": "¡ÚLTIMA OPORTUNIDAD!",
        "QUEIMANDO": "QUEMÁNDOSE",
        "ENVENENADO": "ENVENENADO",
        "NO GELO": "EN HIELO",
        "IMPULSO DE ENERGIA": "IMPULSO DE ENERGÍA",
        "ESQUIVA!": "¡ESQUIVA!",
        "ESCUDO!": "¡ESCUDO!",
        "+8 ESCUDO": "+8 ESCUDO",
        "VAPOR!": "¡VAPOR!",
        "+BÓNUS SOBREVIVÊNCIA & MOEDAS!": "¡BONO DE SUPERVIVENCIA Y MONEDAS!",
        "MOVER": "MOVER",
        "MIRA 360°": "MIRA 360°",
        "Dano": "Daño",
        "Cadência": "Cadencia",
        "Velocidade": "Velocidad",
        "Crítico": "Crítico",
        "Armadura": "Armadura",
        "BAÚ": "COFRE",
        # Multijugador
        "SALA ATIVA:": "SALA ACTIVA:",
        "DIGITE O CÓDIGO NO TECLADO...": "ESCRIBE EL CÓDIGO EN EL TECLADO...",
        "CRIAR SALA": "CREAR SALA",
        "CONECTAR": "CONECTAR",
        "SINCRONIZAR NUVEM AGORA": "SINCRONIZAR NUBE AHORA",
        "JOGADOR 1 (VOCÊ)": "JUGADOR 1 (TÚ)",
        "JOGADOR 2 (PARCEIRO / RIVAL)": "JUGADOR 2 (COMPAÑERO / RIVAL)",
        "JOGADOR 2 (REDE ATIVA)": "JUGADOR 2 (RED ACTIVA)",
        "SKIN P2": "SKIN J2",
        "MASCOTE P2": "MASCOTA J2",
        "INICIAR CO-OP SOBREVIVÊNCIA": "INICIAR CO-OP SUPERVIVENCIA",
        "INICIAR DUELO PVP 1V1": "INICIAR DUELO PVP 1V1",
        "Co-op: Lutem juntos contra as hordas e Chefes com Reanimação!  |  PvP: Duelo direto 1v1 na arena (Melhor de 3)!": "Co-op: ¡Luchen juntos contra hordas y Jefes con Reanimación!  |  PvP: ¡Duelo directo 1v1 en la arena (Mejor de 3)!",
        "PARCEIRO ORB": "ORBE COMPAÑERO",
        "RIVAL ORB": "ORBE RIVAL",
        "CAÍDO! APROXIME-SE!": "¡CAÍDO! ¡ACÉRCATE!",
        "CAÍDO! AGUARDANDO REANIMAÇÃO...": "¡CAÍDO! ESPERANDO REANIMACIÓN...",
        "PARCEIRO CAÍDO! APROXIME-SE PARA REANIMAR!": "¡COMPAÑERO CAÍDO! ¡ACÉRCATE PARA REANIMAR!",
        "PARCEIRO REANIMADO!": "¡COMPAÑERO REANIMADO!",
        "REANIMADO PELO PARCEIRO!": "¡REANIMADO POR EL COMPAÑERO!",
        "ALIADO REANIMADO PELO SUPREMO!": "¡ALIADO REANIMADO POR EL SUPREMO!",
        "REANIMADO PELO SUPREMO ALIADO!": "¡REANIMADO POR EL SUPREMO ALIADO!",
        "DUELO PVP 1V1 — RODADA 1!": "¡DUELO PVP 1V1 — RONDA 1!",
        "FASE 2: ENFURECIDO!": "¡FASE 2: ENFURECIDO!",
        "FASE 3: APOCALIPSE!": "¡FASE 3: APOCALIPSIS!",
        # Botones Tienda, Skins y Mascotas
        "NÍVEL MÁXIMO": "NIVEL MÁXIMO",
        "EQUIPADO": "EQUIPADO",
        "EQUIPAR COR": "EQUIPAR COLOR",
        "EQUIPAR PET": "EQUIPAR MASCOTA",
        # Biomas & Clima
        "O cenário muda a cada chefe derrotado.": "El escenario cambia con cada jefe derrotado.",
        "Bioma inicial": "Bioma inicial",
        "Nexus Cibernético": "Nexo Cibernético",
        "Inferno Vulcânico": "Infierno Volcánico",
        "Abismo Tóxico": "Abismo Tóxico",
        "Tundra Sub-Zero": "Tundra Sub-Cero",
        "Dimensão do Vazio": "Dimensión del Vacío",
        "Santuário Celestial": "Santuario Celestial",
        "Caldeira de Magma": "Caldera de Magma",
        "Cidadela Abissal": "Ciudadela Abisal",
        "Oceano de Neon": "Océano de Neón",
        "Trono Ômega": "Trono Omega",
        "Jardim Prismático": "Jardín Prismático",
        "Horizonte de Eventos": "Horizonte de Eventos",
        "Faíscas": "Chispas",
        "Brasas": "Brasas",
        "Esporos": "Esporas",
        "Neve": "Nieve",
        "Fendas do vazio": "Grietas del vacío",
        "Luz divina": "Luz divina",
        # Rarezas
        "Comum": "Común",
        "Incomum": "Poco Común",
        "Rara": "Rara",
        "Épica": "Épica",
        "Lendária": "Legendaria",
        "Mítica": "Mítica",
        "Divina": "Divina",
        "Suprema": "Suprema",
        "Primordial": "Primordial",
        "Transcendente": "Trascendente",
        # Cómo Jugar
        "WASD / SETAS": "WASD / FLECHAS",
        "Mova a sua personagem pela arena desviando de cercos e perigos de terreno.": "Mueve a tu personaje por la arena esquivando hordas y peligros del terreno.",
        "RATO / TECLA E": "RATÓN / TECLA E",
        "Aponte com o Rato. Botão Esquerdo dispara; Tecla E ou Botão Direito ativa Auto-Tiro.": "Apunta con el Ratón. Clic Izquierdo dispara; Tecla E o Clic Derecho activa Auto-Disparo.",
        "TECLA Q (100%)": "TECLA Q (100%)",
        "Dispara o ATAQUE ESPECIAL SUPREMO exclusivo da Cor (Skin) equipada!": "¡Dispara el ATAQUE ESPECIAL SUPREMO exclusivo del Color (Skin) equipado!",
        "MOEDAS DE OURO": "MONEDAS DE ORO",
        "Colete moedas para comprar Upgrades Permanentes, Skins e Mascotes na Loja.": "Recoge monedas para comprar Mejoras Permanentes, Skins y Mascotas en la Tienda.",
        "BAÚS DOURADOS": "COFRES DORADOS",
        "Elites e Chefes largam Baús de Relíquia com moedas, cura, escudo e bónus permanentes.": "Élites y Jefes sueltan Cofres de Reliquia con monedas, curación, escudo y bonos permanentes.",
        "TECLAS 1, 2, 3, R": "TECLAS 1, 2, 3, R",
        "Ao subir de nível, escolha 1 entre 3 cartas holográficas ou pressione R para sortear novas.": "Al subir de nivel, elige 1 de 3 cartas holográficas o presiona R para sortear nuevas.",
        "TECLA F5": "TECLA F5",
        "Gravação Rápida instantânea na subpasta SAVES/ (além do Auto-Save automático).": "Guardado Rápido instantáneo en la subcarpeta SAVES/ (además del Auto-Guardado).",
        "ESC / F3 / TAB": "ESC / F3 / TAB",
        "ESC pausa a partida, F3 exibe Hitboxes e TAB abre o Inventário Tático em tempo real.": "ESC pausa la partida, F3 muestra Hitboxes y TAB abre el Inventario Táctico en tiempo real.",
        # Skins & Supremos
        "Azul Clássico": "Azul Clásico",
        "O núcleo original de energia ciano puro.": "El núcleo original de energía cian pura.",
        "CATACLISMO DE PLASMA": "CATACLISMO DE PLASMA",
        "Desbloqueado desde o início": "Desbloqueado desde el inicio",
        "Esmeralda Tóxica": "Esmeralda Tóxica",
        "Supremo: Tempestade Radioativa de esporos ácidos.": "Supremo: Tormenta Radiactiva de esporas ácidas.",
        "TEMPESTADE RADIOATIVA": "TORMENTA RADIACTIVA",
        "50 Abates ou 150 Moedas": "50 Bajas o 150 Monedas",
        "Fúria Carmesim": "Furia Carmesí",
        "Supremo: Erupção Sanguinária de lâminas escarlates.": "Supremo: Erupción Sanguinaria de cuchillas escarlatas.",
        "ERUPÇÃO SANGUINÁRIA": "ERUPCIÓN SANGUINARIA",
        "Combo 25x ou 250 Moedas": "Combo 25x o 250 Monedas",
        "Soberano Dourado": "Soberano Dorado",
        "Supremo: Julgamento Imperial com pilares de luz celeste.": "Supremo: Juicio Imperial con pilares de luz celestial.",
        "JULGAMENTO IMPERIAL": "JUICIO IMPERIAL",
        "1 Chefe ou 350 Moedas": "1 Jefe o 350 Monedas",
        "Névoa do Vazio": "Niebla del Vacío",
        "Supremo: Colapso Dimensional com fendas gravitacionais.": "Supremo: Colapso Dimensional con grietas gravitacionales.",
        "COLAPSO DIMENSIONAL": "COLAPSO DIMENSIONAL",
        "Nível 15 ou 450 Moedas": "Nivel 15 o 450 Monedas",
        "Chama Solar": "Llama Solar",
        "Supremo: Supernova Incandescente de meteoros solares.": "Supremo: Supernova Incandescente de meteoros solares.",
        "SUPERNOVA INCANDESCENTE": "SUPERNOVA INCANDESCENTE",
        "200 Abates ou 550 Moedas": "200 Bajas o 550 Monedas",
        "Zero Absoluto": "Cero Absoluto",
        "Supremo: Nevasca Sub-Zero de lanças de gelo ártico.": "Supremo: Ventisca Sub-Cero de lanzas de hielo ártico.",
        "NEVASCA SUB-ZERO": "VENTISCA SUB-CERO",
        "5 min vivo ou 650 Moedas": "5 min vivo o 650 Monedas",
        "Prisma Cósmico (RGB)": "Prisma Cósmico (RGB)",
        "Supremo: Hipernova Prismática de raios arco-íris!": "¡Supremo: Hipernova Prismática de rayos arcoíris!",
        "HIPERNOVA PRISMÁTICA": "HIPERNOVA PRISMÁTICA",
        "Nível 30 ou 900 Moedas": "Nivel 30 o 900 Monedas",
        "Arcanjo Celestial": "Arcángel Celestial",
        "Supremo: Cólera Divina com lanças de luz turquesa.": "Supremo: Cólera Divina con lanzas de luz turquesa.",
        "CÓLERA DO ARCANJO": "CÓLERA DEL ARCÁNGEL",
        "3 Chefes ou 1100 Moedas": "3 Jefes o 1100 Monedas",
        "Soberano Absoluto": "Soberano Absoluto",
        "Supremo: Apocalipse Ômega que rasga o espaço-tempo!": "¡Supremo: Apocalipsis Omega que desgarra el espacio-tiempo!",
        "APOCALIPSE ÔMEGA": "APOCALIPSIS OMEGA",
        "1500 Moedas": "1500 Monedas",
        # Tienda
        "Núcleo de Ataque": "Núcleo de Ataque",
        "+5% Dano Base permanente por nível": "+5% Daño Base permanente por nivel",
        "Titânio Vital": "Titanio Vital",
        "+12 Vida Máxima inicial por nível": "+12 Vida Máxima inicial por nivel",
        "Propulsor Leve": "Propulsor Ligero",
        "+4% Velocidade de Movimento por nível": "+4% Velocidad de Movimiento por nivel",
        "Bobina Magnética": "Bobina Magnética",
        "+25 Raio de Coleta de Orbes/Moedas": "+25 Radio de Recolección de Orbes/Monedas",
        "Fortuna Dourada": "Fortuna Dorada",
        "+15% Valor de todas as Moedas apanhadas": "+15% Valor de todas las Monedas recogidas",
        # Logros
        "Caçador Inicial": "Cazador Inicial",
        "Elimine 50 inimigos numa partida.": "Elimina 50 enemigos en una partida.",
        "Cor: Esmeralda Tóxica": "Color: Esmeralda Tóxica",
        "Mestre do Combo": "Maestro del Combo",
        "Alcance um Combo de 25x.": "Alcanza un Combo de 25x.",
        "Cor: Fúria Carmesim": "Color: Furia Carmesí",
        "Matador de Gigantes": "Matagigantes",
        "Derrote o seu primeiro Chefe.": "Derrota a tu primer Jefe.",
        "Cor: Soberano Dourado": "Color: Soberano Dorado",
        "Veterano da Arena": "Veterano de la Arena",
        "Alcance o Nível 15.": "Alcanza el Nivel 15.",
        "Cor: Névoa do Vazio": "Color: Niebla del Vacío",
        "Exterminador": "Exterminador",
        "Elimine 200 inimigos numa partida.": "Elimina 200 enemigos en una partida.",
        "Cor: Chama Solar": "Color: Llama Solar",
        "Imortal do Tempo": "Inmortal del Tiempo",
        "Sobreviva durante 5 minutos (05:00).": "Sobrevive durante 5 minutos (05:00).",
        "Cor: Zero Absoluto": "Color: Cero Absoluto",
        "Lenda Suprema": "Leyenda Suprema",
        "Alcance o Nível 30.": "Alcanza el Nivel 30.",
        "Cor: Prisma Cósmico (RGB)": "Color: Prisma Cósmico (RGB)",
        "Barão do Ouro": "Barón del Oro",
        "Acumule 500 Moedas na sua conta.": "Acumula 500 Monedas en tu cuenta.",
        "+100 Moedas de Bónus": "+100 Monedas de Bono",
        # Mascotas
        "Gelatina Azul": "Gelatina Azul",
        "Atira mini-projéteis no inimigo mais próximo.": "Dispara mini-proyectiles al enemigo más cercano.",
        "Gatinho Relâmpago": "Gatito Relámpago",
        "Solta raios que atingem até 3 inimigos a cada 3s.": "Lanza rayos que golpean hasta 3 enemigos cada 3s.",
        "Coruja Sábia": "Búho Sabio",
        "+15% de XP e +60 de raio de coleta de orbes.": "+15% de XP y +60 de radio de recolección de orbes.",
        "Cão Guardião": "Perro Guardián",
        "+8 de escudo a cada 6s e morde quem chega perto.": "+8 de escudo cada 6s y muerde a quien se acerque.",
        "Dragãozinho de Plasma": "Dragoncito de Plasma",
        "Lança bolas de fogo explosivas em área a cada 4s.": "Lanza bolas de fuego explosivas en área cada 4s.",
        "Fênix Neon": "Fénix Neón",
        "Cura 6% da vida máxima a cada 8s.": "Cura 6% de la vida máxima cada 8s.",
        "Drone Cyber-Sniper": "Dron Cyber-Francotirador",
        "Dispara lasers de alta precisão e velocidade.": "Dispara láseres de alta precisión y velocidad.",
        "Serafim Astral": "Serafín Astral",
        "Invoca relâmpagos divinos em cadeia contra os inimigos.": "Invoca relámpagos divinos en cadena contra los enemigos.",
        "Cometa Guardião": "Cometa Guardián",
        "Gera escudo periodicamente e protege quando inimigos se aproximam.": "Genera escudo periódicamente y protege cuando se acercan enemigos.",
        "Filhote do Vazio": "Cría del Vacío",
        "Dispara explosões roxas contra grupos de inimigos.": "Dispara explosiones púrpuras contra grupos de enemigos.",
        # Enemigos y Jefes
        "Básico": "Básico",
        "Veloz": "Veloz",
        "Tanque": "Tanque",
        "Atirador": "Tirador",
        "Regenerador": "Regenerador",
        "Explosivo": "Explosivo",
        "Teletransportador": "Teletransportador",
        "Blindado": "Blindado",
        "Invocador": "Invocador",
        "Ceifador": "Segador",
        "Piromante": "Piromante",
        "Sentinela Laser": "Centinela Láser",
        "Berserker": "Berserker",
        "Elite": "Élite",
        "Aracnídeo": "Arácnido",
        "Anomalia": "Anomalía",
        "Espelho": "Espejo",
        "Parasita": "Parásito",
        "Vórtice": "Vórtice",
        "Escudeiro": "Escudero",
        "Bombardeiro": "Bombardero",
        "Fantasma": "Fantasma",
        "Regenerante": "Regenerante",
        "Gigante": "Gigante",
        "Persegue o jogador em linha reta.": "Persigue al jugador en línea recta.",
        "Rápido e frágil: corre para cima de você.": "Rápido y frágil: corre directo hacia ti.",
        "Lento e muito resistente.": "Lento y muy resistente.",
        "Mantém distância e atira.": "Mantiene la distancia y dispara.",
        "Recupera vida com o tempo.": "Recupera vida con el tiempo.",
        "Explode ao morrer, ferindo quem estiver perto.": "Explota al morir, hiriendo a quien esté cerca.",
        "Teleporta para perto de você.": "Se teletransporta cerca de ti.",
        "Recebe 25% menos dano dos seus tiros.": "Recibe 25% menos daño de tus disparos.",
        "Invoca inimigos menores.": "Invoca enemigos menores.",
        "Perseguidor rápido, resistente e de dano alto.": "Perseguidor rápido, resistente y de alto daño.",
        "Mantém distância e lança 3 projéteis em leque.": "Mantiene distancia y lanza 3 proyectiles en abanico.",
        "Mantém distância e dispara tiros rápidos.": "Mantiene distancia y dispara tiros rápidos.",
        "Acelera 65% quando abaixo de 50% da vida.": "Acelera 65% cuando está por debajo del 50% de vida.",
        "Versão perigosa. A partir do nível 8 pode ter afixo.": "Versión peligrosa. Desde el nivel 8 puede tener afijo.",
        "Avança em zigue-zague para flanquear.": "Avanza en zigzag para flanquearte.",
        "Persegue e dispara 4 projéteis em leque.": "Persigue y dispara 4 proyectiles en abanico.",
        "O Quadrado Colossal": "El Cuadrado Colosal",
        "O Devorador Carmesim": "El Devorador Carmesí",
        "O Núcleo Corrompido": "El Núcleo Corrupto",
        "O Senhor da Velocidade": "El Señor de la Velocidad",
        "O Colosso Blindado": "El Coloso Blindado",
        "O Rei dos Quadrados": "El Rey de los Cuadrados",
        "O Titã de Magma": "El Titán de Magma",
        "O Arquiteto do Vazio": "El Arquitecto del Vacío",
        "O Leviatã Cibernético": "El Leviatán Cibernético",
        "O Imperador Ômega": "El Emperador Omega",
        "A Matriarca Prismática": "La Matriarca Prismática",
        "O Devorador de Estrelas": "El Devorador de Estrellas",
        # Cartas de Mejora
        "Vitalidade": "Vitalidad",
        "Vida máxima +20.": "Vida máxima +20.",
        "Coração Extra": "Corazón Extra",
        "Vida máxima +35.": "Vida máxima +35.",
        "Regeneração": "Regeneración",
        "Recupera 1,2 de vida por segundo.": "Recupera 1,2 de vida por segundo.",
        "Cura Emergencial": "Curación de Emergencia",
        "Recupera 40% da vida máxima imediatamente.": "Recupera 40% de la vida máxima inmediatamente.",
        "Pele Resistente": "Piel Resistente",
        "Reduz dano recebido em 10%.": "Reduce el daño recibido en 10%.",
        "Armadura Reforçada": "Armadura Reforzada",
        "Reduz dano recebido em 15%.": "Reduce el daño recibido en 15%.",
        "Escudo de Energia": "Escudo de Energía",
        "Concede 35 pontos de escudo recarregável.": "Otorga 35 puntos de escudo recargable.",
        "Muralha de Plasma": "Muralla de Plasma",
        "O teu escudo regenera automaticamente 1,5/s.": "Tu escudo se regenera automáticamente 1,5/s.",
        "Última Chance": "Última Oportunidad",
        "Uma vez, evita a morte, explode a tela e deixa 20% HP.": "Una vez, evita la muerte, explota la pantalla y deja 20% HP.",
        "Recuperação": "Recuperación",
        "Aumenta toda cura recebida em 25%.": "Aumenta toda curación recibida en 25%.",
        "Barreira Temporal": "Barrera Temporal",
        "Invulnerabilidade após dano +0,35 s.": "Invulnerabilidad tras recibir daño +0,35 s.",
        "Triângulos Poderosos": "Triángulos Poderosos",
        "Dano dos projéteis +20%.": "Daño de los proyectiles +20%.",
        "Disparo Rápido": "Disparo Rápido",
        "Velocidade de disparo +16%.": "Velocidad de disparo +16%.",
        "Projétil Veloz": "Proyectil Veloz",
        "Velocidade dos projéteis +25%.": "Velocidad de los proyectiles +25%.",
        "Tiro Duplo": "Tiro Doble",
        "Adiciona +1 projétil por disparo.": "Añade +1 proyectil por disparo.",
        "Tiro Triplo": "Tiro Triple",
        "Garante pelo menos 3 projéteis em leque.": "Garantiza al menos 3 proyectiles en abanico.",
        "Perfuração": "Perforación",
        "Projéteis atravessam +1 inimigo extra.": "Los proyectiles atraviesan +1 enemigo extra.",
        "Ricochete": "Rebote",
        "Projéteis saltam para outro inimigo (+1 salto).": "Los proyectiles rebotan a otro enemigo (+1 salto).",
        "Dano Crítico": "Daño Crítico",
        "Chance crítica +8 pontos percentuais.": "Probabilidad crítica +8 puntos porcentuales.",
        "Impacto Brutal": "Impacto Brutal",
        "Multiplicador de dano crítico +50%.": "Multiplicador de daño crítico +50%.",
        "Caçador de Elites": "Cazador de Élites",
        "Dano contra inimigos especiais +25%.": "Daño contra enemigos especiales +25%.",
        "Matador de Chefes": "Matador de Jefes",
        "Dano contra chefes +20%.": "Daño contra jefes +20%.",
        "Explosão Triangular": "Explosión Triangular",
        "Impactos causam explosão em área.": "Los impactos causan explosión en área.",
        "Passos Rápidos": "Pasos Rápidos",
        "Velocidade de movimento +12%.": "Velocidad de movimiento +12%.",
        "Impulso Azul": "Impulso Azul",
        "Espaço ativa avanço invulnerável com recarga.": "Espacio activa un avance invulnerable con recarga.",
        "Corpo Leve": "Cuerpo Ligero",
        "Movimento mais ágil (+8% velocidade).": "Movimiento más ágil (+8% velocidad).",
        "Esquiva Energética": "Esquiva Energética",
        "Chance de evitar dano +8%.": "Probabilidad de evitar daño +8%.",
        "Aceleração": "Aceleración",
        "Abates concedem +30% velocidade por 2 s.": "Las bajas otorgan +30% de velocidad por 2 s.",
        "Campo Repulsor": "Campo Repulsor",
        "Onda de choque empurra inimigos próximos.": "Onda de choque que empuja a los enemigos cercanos.",
        "Aprendizado Rápido": "Aprendizaje Rápido",
        "XP recebido +15%.": "XP recibido +15%.",
        "Conhecimento Avançado": "Conocimiento Avanzado",
        "XP recebido +25%.": "XP recibido +25%.",
        "Ímã de Experiência": "Imán de Experiencia",
        "Raio de coleta de orbes e moedas +100.": "Radio de recolección de orbes y monedas +100.",
        "Orbes Valiosos": "Orbes Valiosos",
        "Valor dos orbes de XP +20%.": "Valor de los orbes de XP +20%.",
        "Cobiça Dourada": "Codicia Dorada",
        "Inimigos largam +35% mais Moedas.": "Los enemigos sueltan +35% más Monedas.",
        "Execução Premiada": "Ejecución Premiada",
        "Elites concedem +35% XP e +1 sorteio de carta.": "Los élites otorgan +35% XP y +1 sorteo de carta.",
        "Bônus de Sobrevivência": "Bono de Supervivencia",
        "Recebe pacote de XP, cura e moedas a cada 45s.": "Recibe un paquete de XP, curación y monedas cada 45s.",
        "Caçador Experiente": "Cazador Experto",
        "XP de chefes aumentado em +50%.": "XP de jefes aumentado en +50%.",
        "Núcleo Energético": "Núcleo Energético",
        "Dano +20%, mas movimento -8%.": "Daño +20%, pero movimiento -8%.",
        "Canhão Azul": "Cañón Azul",
        "Projéteis maiores, +15% dano e empurrão.": "Proyectiles más grandes, +15% daño y empuje.",
        "Sobrecarga": "Sobrecarga",
        "A cada 10 s, entra em frenesi de disparo por 2,5 s.": "Cada 10 s, entra en frenesí de disparo por 2,5 s.",
        "Aura Destrutiva": "Aura Destructiva",
        "Campo elétrico causa dano contínuo ao redor.": "Campo eléctrico que causa daño continuo alrededor.",
        "Dreno Vital": "Drenaje Vital",
        "Recupera vida ao derrotar inimigos.": "Recupera vida al derrotar enemigos.",
        "Duplicação Energética": "Duplicación Energética",
        "Chance de +25% de disparar projétil extra.": "+25% de probabilidad de disparar un proyectil extra.",
        "Campo de Lentidão": "Campo de Lentitud",
        "Congela parcialmente inimigos próximos (-40% vel.).": "Congela parcialmente a enemigos cercanos (-40% vel.).",
        "Explosão ao Morrer": "Explosión al Morir",
        "Inimigos abatidos têm 22% de chance de explodir.": "Los enemigos abatidos tienen 22% de probabilidad de explotar.",
        "Proteção de Elite": "Protección de Élite",
        "Elites derrotados concedem +18 de escudo.": "Los élites derrotados otorgan +18 de escudo.",
        "Fúria Azul": "Furia Azul",
        "Dano +25% quando a vida está abaixo de 40%.": "Daño +25% cuando la vida está por debajo del 40%.",
        "Evolução Suprema": "Evolución Suprema",
        "Dano +12%, Vida Máx +15 e +1 Sorteio de Carta.": "Daño +12%, Vida Máx +15 y +1 Sorteo de Carta.",
        "Orbes Orbitais": "Orbes Orbitales",
        "Invoca 1 satélite de plasma que gira ao seu redor.": "Invoca 1 satélite de plasma que gira a tu alrededor.",
        "Relâmpago em Cadeia": "Relámpago en Cadena",
        "Impactos têm 22% de chance de eletrocutar 1 inimigo próximo.": "Los impactos tienen 22% de probabilidad de electrocutar a 1 enemigo cercano.",
        "Catalisador Supremo": "Catalizador Supremo",
        "O Ataque Especial [Q] carrega 25% mais rápido.": "El Ataque Especial [Q] carga 25% más rápido.",
        "Ascensão Mítica": "Ascensión Mítica",
        "Dano +15%, +1 Projétil, +15 Vida Máx e +15 Escudo.": "Daño +15%, +1 Proyectil, +15 Vida Máx y +15 Escudo.",
        "Lâminas Fantasmas": "Cuchillas Fantasma",
        "Projéteis ganham +1 Perfuração e +1 Ricochete.": "Los proyectiles ganan +1 Perforación y +1 Rebote.",
        "Fúria Relâmpago": "Furia Relámpago",
        "Cadência de tiro +18% e Velocidade +10%.": "Cadencia de tiro +18% y Velocidad +10%.",
        "Couraça de Titânio": "Coraza de Titanio",
        "Vida Máxima +40, Armadura +8% e +20 Escudo.": "Vida Máxima +40, Armadura +8% y +20 Escudo.",
        "Chuva de Meteoros": "Lluvia de Meteoros",
        "A cada 7 s, invoca explosões solares em até 3 inimigos.": "Cada 7 s, invoca explosiones solares en hasta 3 enemigos.",
        "Bênção do Arcanjo": "Bendición del Arcángel",
        "Regenera 2,5 HP/s, +1,5/s Escudo e +20% Dano Crítico.": "Regenera 2,5 HP/s, +1,5/s Escudo y +20% Daño Crítico.",
        "Decreto Supremo": "Decreto Supremo",
        "Dano +28%, +1 Projétil, +30 HP Máx e +1 Orbital.": "Daño +28%, +1 Proyectil, +30 HP Máx y +1 Orbital.",
        "Coração Primordial": "Corazón Primordial",
        "Vida máxima +55 e recupera 15% da vida.": "Vida máxima +55 y recupera 15% de la vida.",
        "Marca do Caçador": "Marca del Cazador",
        "30% de chance de marcar o alvo: ele recebe +25% de dano.": "30% de probabilidad de marcar al objetivo: recibe +25% de daño.",
        "Balas Incendiárias": "Balas Incendiarias",
        "35% de chance de queimar o alvo por 3 s (dano contínuo).": "35% de probabilidad de quemar al objetivo por 3 s (daño continuo).",
        "Veneno Neurotóxico": "Veneno Neurotóxico",
        "40% de chance de envenenar. O veneno acumula até 5 vezes.": "40% de probabilidad de envenenar. El veneno se acumula hasta 5 veces.",
        "Toque Gélido": "Toque Gélido",
        "25% de chance de congelar: o inimigo fica 55% mais lento.": "25% de probabilidad de congelar: el enemigo es 55% más lento.",
        "Catalisador Elemental": "Catalizador Elemental",
        "+15% chance de status. Queimar + congelar causa VAPOR (dano em área x2).": "+15% prob. de estado. Quemar + congelar causa VAPOR (daño en área x2).",
        "Tempestade Elemental": "Tormenta Elemental",
        "+12% chance de status e dano contínuo +50%.": "+12% prob. de estado y daño continuo +50%.",
    }
}

# Adiciona versões em maiúsculas de todas as chaves exatas (para títulos de chefes, biomas e raridades)
for _lg in ("en", "es"):
    for _k, _v in list(I18N_EXACT[_lg].items()):
        if _k.upper() not in I18N_EXACT[_lg]:
            I18N_EXACT[_lg][_k.upper()] = _v.upper()

I18N_FRAGMENTS = {
    "en": [
        ("Cada cor muda o visual do seu Ataque Especial [Q]   •   Moedas:", "Each color changes your Special Attack [Q] visual   •   Coins:"),
        ("Um mascote te acompanha e ajuda na batalha   •   Moedas:", "A companion pet follows and helps you in battle   •   Coins:"),
        ("Escolha uma melhoria (1, 2 ou 3)   •   Suas Moedas:", "Choose an upgrade (1, 2 or 3)   •   Your Coins:"),
        ("(Use a roda do rato)", "(Use mouse wheel)"),
        ("Conquistas Desbloqueadas:", "Unlocked Achievements:"),
        ("Terreno: Pads de energia: aceleram você (+35%)", "Terrain: Energy pads: speed you up (+35%)"),
        ("Terreno: Poças de lava: queimam você por alguns segundos", "Terrain: Lava pools: burn you for a few seconds"),
        ("Terreno: Poças tóxicas: envenenam e deixam você mais lento", "Terrain: Toxic pools: poison and slow you down"),
        ("Terreno: Gelo liso: você escorrega e demora a frear", "Terrain: Slick ice: you slide and brake slower"),
        ("Terreno: Fendas do vazio: puxam você para o centro", "Terrain: Void rifts: pull you toward the center"),
        ("Terreno: Círculos de luz: curam devagar quem fica dentro", "Terrain: Light circles: slowly heal whoever stands inside"),
        ("Após derrotar o chefe nº", "After defeating boss #"),
        ("Aparece no nível", "Spawns at level"),
        (". Ao cair, o cenário vira", ". On defeat, biome shifts to"),
        ("cores e ataques supremos", "skins & ultimate attacks"),
        ("habilidades em 10 raridades", "skills across 10 rarities"),
        ("cenários de arena", "arena biomes"),
        ("desbloqueados", "unlocked"),
        ("concluídas", "completed"),
        ("tipos •", "types •"),
        ("chefes", "bosses"),
        ("moedas", "coins"),
        ("PERFIL LOCAL", "LOCAL PROFILE"),
        ("SINCRONIZADO", "SYNCED"),
        ("OFFLINE & NUVEM OK", "OFFLINE & CLOUD OK"),
        ("NUVEM + CACHE LOCAL", "CLOUD + LOCAL CACHE"),
        ("Pronto (IA Tática + Rede LAN Ativa)", "Ready (Tactical AI + Active LAN)"),
        ("aberta (Porta 45890) • Aguardando ou Jogue c/ IA", "open (Port 45890) • Waiting or Play w/ AI"),
        ("pronta (Modo Local / IA Tática)", "ready (Local Mode / Tactical AI)"),
        ("vinculada (Modo Simulado / IA)", "linked (Simulated Mode / AI)"),
        ("Conectado à sala", "Connected to room"),
        ("Entrar noutra sala:", "Join another room:"),
        ("SALDO ATUAL:", "CURRENT BALANCE:"),
        ("VOLUME GERAL:", "MASTER VOLUME:"),
        ("GRAVADO EM SAVES/SLOT", "SAVED TO SAVES/SLOT"),
        ("PROGRESSO SALVO", "PROGRESS SAVED"),
        ("CONTINUAR DO NÍVEL", "CONTINUE FROM LEVEL"),
        ("Progresso no Nível", "Progress at Level"),
        ("gravado no Slot", "saved in Slot"),
        ("Últimas cartas:", "Latest cards:"),
        ("Cartas Adquiridas", "Acquired Cards"),
        ("Cartas Coletadas:", "Collected Cards:"),
        ("Chefes Derrotados:", "Bosses Defeated:"),
        ("outras melhorias...", "other upgrades..."),
        ("Pasta de gravação ativa:", "Active save folder:"),
        ("EXPERIÊNCIA (XP):", "EXPERIENCE (XP):"),
        ("NÍVEL ATUAL:", "CURRENT LEVEL:"),
        ("[TAB] INVENTÁRIO TÁTICO", "[TAB] TACTICAL INVENTORY"),
        ("DPS ESTIMADO:", "ESTIMATED DPS:"),
        ("Recorde de combo:", "Best combo:"),
        ("Cenário Atual:", "Current Biome:"),
        ("NOVO CENÁRIO:", "NEW BIOME:"),
        ("CHEFE NV", "BOSS LV"),
        ("em ", "in "),
        (" níveis", " levels"),
        ("ALVOS", "TARGETS"),
        ("MAPA:", "MAP:"),
        ("FASE ", "PHASE "),
        ("PRONTO!", "READY!"),
        ("ESCUDO", "SHIELD"),
        ("SORTEAR NOVAS [R]", "REROLL CARDS [R]"),
        ("Grátis", "Free"),
        ("COMPRAR", "BUY"),
        ("CONCLUÍDA —", "COMPLETED —"),
        ("Recompensa:", "Reward:"),
        ("Faltam ", "Need "),
        ("Página ", "Page "),
        (" de ", " of "),
        ("Continuar: Slot", "Continue: Slot"),
        ("Nível ", "Level "),
        ("Tempo:", "Time:"),
        ("Abates:", "Kills:"),
        ("Vida:", "Health:"),
        ("Escudo:", "Shield:"),
        ("Clima:", "Weather:"),
        ("Mascote:", "Pet:"),
        ("Sinergia:", "Synergy:"),
        ("Cartas (", "Cards ("),
        ("TECLA ", "KEY "),
        ("VIDA ", "HP "),
        ("VEL ", "SPD "),
        ("DANO ", "DMG "),
        ("MOEDAS", "COINS"),
        ("Moedas", "Coins"),
        ("Nenhuma", "None"),
    ],
    "es": [
        ("Cada cor muda o visual do seu Ataque Especial [Q]   •   Moedas:", "Cada color cambia el visual de tu Ataque Especial [Q]   •   Monedas:"),
        ("Um mascote te acompanha e ajuda na batalha   •   Moedas:", "Una mascota te acompaña y ayuda en la batalla   •   Monedas:"),
        ("Escolha uma melhoria (1, 2 ou 3)   •   Suas Moedas:", "Elige una mejora (1, 2 o 3)   •   Tus Monedas:"),
        ("(Use a roda do rato)", "(Usa la rueda del ratón)"),
        ("Conquistas Desbloqueadas:", "Logros Desbloqueados:"),
        ("Terreno: Pads de energia: aceleram você (+35%)", "Terreno: Paneles de energía: te aceleran (+35%)"),
        ("Terreno: Poças de lava: queimam você por alguns segundos", "Terreno: Charcos de lava: te queman por unos segundos"),
        ("Terreno: Poças tóxicas: envenenam e deixam você mais lento", "Terreno: Charcos tóxicos: envenenan y te ralentizan"),
        ("Terreno: Gelo liso: você escorrega e demora a frear", "Terreno: Hielo liso: resbalas y tardas en frenar"),
        ("Terreno: Fendas do vazio: puxam você para o centro", "Terreno: Grietas del vacío: te atraen hacia el centro"),
        ("Terreno: Círculos de luz: curam devagar quem fica dentro", "Terreno: Círculos de luz: curan lentamente a quien esté dentro"),
        ("Após derrotar o chefe nº", "Tras derrotar al jefe nº"),
        ("Aparece no nível", "Aparece en el nivel"),
        (". Ao cair, o cenário vira", ". Al caer, el escenario cambia a"),
        ("cores e ataques supremos", "colores y ataques supremos"),
        ("habilidades em 10 raridades", "habilidades en 10 rarezas"),
        ("cenários de arena", "escenarios de arena"),
        ("desbloqueados", "desbloqueados"),
        ("concluídas", "completados"),
        ("tipos •", "tipos •"),
        ("chefes", "jefes"),
        ("moedas", "monedas"),
        ("PERFIL LOCAL", "PERFIL LOCAL"),
        ("SINCRONIZADO", "SINCRONIZADO"),
        ("OFFLINE & NUVEM OK", "OFFLINE Y NUBE OK"),
        ("NUVEM + CACHE LOCAL", "NUBE + CACHÉ LOCAL"),
        ("Pronto (IA Tática + Rede LAN Ativa)", "Listo (IA Táctica + Red LAN Activa)"),
        ("aberta (Porta 45890) • Aguardando ou Jogue c/ IA", "abierta (Puerto 45890) • Esperando o Juega c/ IA"),
        ("pronta (Modo Local / IA Tática)", "lista (Modo Local / IA Táctica)"),
        ("vinculada (Modo Simulado / IA)", "vinculada (Modo Simulado / IA)"),
        ("Conectado à sala", "Conectado a la sala"),
        ("Entrar noutra sala:", "Entrar en otra sala:"),
        ("SALDO ATUAL:", "SALDO ACTUAL:"),
        ("VOLUME GERAL:", "VOLUMEN GENERAL:"),
        ("GRAVADO EM SAVES/SLOT", "GUARDADO EN SAVES/RANURA"),
        ("PROGRESSO SALVO", "PROGRESO GUARDADO"),
        ("CONTINUAR DO NÍVEL", "CONTINUAR DESDE NIVEL"),
        ("Progresso no Nível", "Progreso en el Nivel"),
        ("gravado no Slot", "guardado en la Ranura"),
        ("Últimas cartas:", "Últimas cartas:"),
        ("Cartas Adquiridas", "Cartas Adquiridas"),
        ("Cartas Coletadas:", "Cartas Recolectadas:"),
        ("Chefes Derrotados:", "Jefes Derrotados:"),
        ("outras melhorias...", "otras mejoras..."),
        ("Pasta de gravação ativa:", "Carpeta de guardado activa:"),
        ("EXPERIÊNCIA (XP):", "EXPERIENCIA (XP):"),
        ("NÍVEL ATUAL:", "NIVEL ACTUAL:"),
        ("[TAB] INVENTÁRIO TÁTICO", "[TAB] INVENTARIO TÁCTICO"),
        ("DPS ESTIMADO:", "DPS ESTIMADO:"),
        ("Recorde de combo:", "Récord de combo:"),
        ("Cenário Atual:", "Escenario Actual:"),
        ("NOVO CENÁRIO:", "NUEVO ESCENARIO:"),
        ("CHEFE NV", "JEFE NV"),
        ("em ", "en "),
        (" níveis", " niveles"),
        ("ALVOS", "OBJETIVOS"),
        ("MAPA:", "MAPA:"),
        ("FASE ", "FASE "),
        ("PRONTO!", "¡LISTO!"),
        ("ESCUDO", "ESCUDO"),
        ("SORTEAR NOVAS [R]", "SORTEAR NUEVAS [R]"),
        ("Grátis", "Gratis"),
        ("COMPRAR", "COMPRAR"),
        ("CONCLUÍDA —", "COMPLETADO —"),
        ("Recompensa:", "Recompensa:"),
        ("Faltam ", "Faltan "),
        ("Página ", "Página "),
        (" de ", " de "),
        ("Continuar: Slot", "Continuar: Ranura"),
        ("Nível ", "Nivel "),
        ("Tempo:", "Tiempo:"),
        ("Abates:", "Bajas:"),
        ("Vida:", "Vida:"),
        ("Escudo:", "Escudo:"),
        ("Clima:", "Clima:"),
        ("Mascote:", "Mascota:"),
        ("Sinergia:", "Sinergia:"),
        ("Cartas (", "Cartas ("),
        ("TECLA ", "TECLA "),
        ("VIDA ", "VIDA "),
        ("VEL ", "VEL "),
        ("DANO ", "DAÑO "),
        ("MOEDAS", "MONEDAS"),
        ("Moedas", "Monedas"),
        ("Nenhuma", "Ninguna"),
    ]
}

for _lg in ("en", "es"):
    _existing = {k for k, _ in I18N_FRAGMENTS[_lg]}
    for _k, _v in sorted(I18N_EXACT[_lg].items(), key=lambda it: -len(it[0])):
        if len(_k) >= 5 and _k not in _existing and _k != _v:
            I18N_FRAGMENTS[_lg].append((_k, _v))
            _existing.add(_k)
    I18N_FRAGMENTS[_lg].sort(key=lambda it: -len(it[0]))

def tr_text(text):
    s = str(text)
    if LANG_CUR == "pt" or not s:
        return s
    key = (LANG_CUR, s)
    cached = TR_CACHE.get(key)
    if cached is not None:
        return cached
    if len(TR_CACHE) > 4000:
        TR_CACHE.clear()
    exact_map = I18N_EXACT.get(LANG_CUR, {})
    if s in exact_map:
        res = exact_map[s]
    elif s.strip() in exact_map:
        st = s.strip()
        res = s.replace(st, exact_map[st])
    else:
        res = s
        for k, v in I18N_FRAGMENTS.get(LANG_CUR, ()):
            if k in res:
                res = res.replace(k, v)
    TR_CACHE[key] = res
    TR_CACHE[(LANG_CUR, res)] = res
    return res

def get_cached_text(text, font, color):
    t_str = tr_text(text)
    key = (id(font), LANG_CUR, t_str, color)
    if key not in TEXT_CACHE:
        if len(TEXT_CACHE) > 1500:
            TEXT_CACHE.clear()
        TEXT_CACHE[key] = font.render(_sanitize_text(t_str, font), True, color)
    return TEXT_CACHE[key]

def draw_text(surf, text, font, color, pos, center=False, shadow=True):
    if shadow:
        sh_img = get_cached_text(text, font, (4, 8, 18))
        sh_rect = sh_img.get_rect()
        if center:
            sh_rect.center = (pos[0] + 1, pos[1] + 2)
        else:
            sh_rect.topleft = (pos[0] + 1, pos[1] + 2)
        surf.blit(sh_img, sh_rect)
    img = get_cached_text(text, font, color)
    rect = img.get_rect()
    if center:
        rect.center = pos
    else:
        rect.topleft = pos
    surf.blit(img, rect)
    return rect

PANEL_CACHE = {}
VIGNETTE_CACHE = {}
GRADIENT_CACHE = {}
NEBULA_CACHE = {}

def get_vertical_gradient(w, h, top_col, bot_col, radius=12):
    """Gera uma superfície com gradiente vertical suave e cantos arredondados em cache."""
    key = (w, h, top_col, bot_col, radius)
    if key not in GRADIENT_CACHE:
        if len(GRADIENT_CACHE) > 200:
            GRADIENT_CACHE.clear()
        grad = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(h):
            t = y / max(1, h - 1)
            c = tuple(int(top_col[i] + (bot_col[i] - top_col[i]) * t) for i in range(len(top_col)))
            pygame.draw.line(grad, c, (0, y), (w - 1, y))
        if radius > 0:
            mask = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
            grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        GRADIENT_CACHE[key] = grad
    return GRADIENT_CACHE[key]

def draw_panel(surf, rect, color, border_color=None, radius=12, shadow_offset=8):
    """Painel Cyber-Glassmorphism com gradiente profundo, sombra suave e reflexo superior 3D."""
    x, y, w, h = rect
    key = (w, h, color, border_color, radius, shadow_offset)
    if key not in PANEL_CACHE:
        if len(PANEL_CACHE) > 250:
            PANEL_CACHE.clear()
        panel_surf = pygame.Surface((w + shadow_offset * 2, h + shadow_offset * 2), pygame.SRCALPHA)
        for i in range(4):
            pygame.draw.rect(
                panel_surf, (0, 0, 0, 44 - i * 10),
                (shadow_offset - i + 2, shadow_offset - i + 4, w + i * 2, h + i * 2),
                border_radius=radius + i
            )
        alpha = color[3] if len(color) > 3 else 230
        top_c = (min(255, color[0] + 14), min(255, color[1] + 20), min(255, color[2] + 32), alpha)
        bot_c = (max(0, color[0] - 6), max(0, color[1] - 8), max(0, color[2] - 12), alpha)
        grad = get_vertical_gradient(w, h, top_c, bot_c, radius)
        panel_surf.blit(grad, (shadow_offset, shadow_offset))
        pygame.draw.rect(
            panel_surf, (255, 255, 255, 18),
            (shadow_offset + 2, shadow_offset + 2, w - 4, max(6, h // 3)),
            border_top_left_radius=max(1, radius - 2), border_top_right_radius=max(1, radius - 2)
        )
        if border_color:
            pygame.draw.rect(panel_surf, (*border_color[:3], 70), (shadow_offset - 1, shadow_offset - 1, w + 2, h + 2), 3, border_radius=radius + 1)
            pygame.draw.rect(panel_surf, border_color, (shadow_offset, shadow_offset, w, h), 2, border_radius=radius)
            pygame.draw.line(
                panel_surf, (255, 255, 255, 120),
                (shadow_offset + radius, shadow_offset + 1),
                (shadow_offset + w - radius, shadow_offset + 1), 1
            )
        PANEL_CACHE[key] = panel_surf
    surf.blit(PANEL_CACHE[key], (x - shadow_offset, y - shadow_offset))

def draw_glossy_bar(surf, rect, frac, fill_col, bg_col=(18, 28, 48), ghost_frac=0.0, ghost_col=(235, 145, 40), segments=0, border_col=None):
    """Barra de progresso estilo vidro líquido com brilho superior e divisórias."""
    x, y, w, h = rect
    r = max(3, h // 2)
    pygame.draw.rect(surf, bg_col, rect, border_radius=r)
    frac = clamp(frac, 0.0, 1.0)
    ghost_frac = clamp(ghost_frac, 0.0, 1.0)
    if ghost_frac > frac and int(w * ghost_frac) > 2:
        pygame.draw.rect(surf, ghost_col, (x, y, int(w * ghost_frac), h), border_radius=r)
    fill_w = int(w * frac)
    if fill_w > 2:
        pygame.draw.rect(surf, fill_col, (x, y, fill_w, h), border_radius=r)
        shine_h = max(2, h // 2 - 1)
        shine_col = tuple(min(255, c + 65) for c in fill_col[:3])
        pygame.draw.rect(surf, shine_col, (x + 2, y + 1, max(2, fill_w - 4), shine_h), border_radius=max(1, r - 1))
    if segments > 1:
        for i in range(1, segments):
            sx = x + int(w * (i / segments))
            pygame.draw.line(surf, (8, 14, 28), (sx, y + 1), (sx, y + h - 2), 1)
    pygame.draw.rect(surf, border_col if border_col else (55, 95, 150), rect, 1, border_radius=r)

def draw_cyber_button(surf, rect, text, font, border_col, hover=False, text_col=WHITE, icon=None):
    """Botão futurista Cyber-Glassmorphism com chanfros neon, brilho aditivo no hover e marcadores táticos."""
    r = pygame.Rect(rect)
    if hover:
        r = r.move(0, -2)
    x, y, w, h = r
    base_c = (32, 76, 142, 248) if hover else (14, 30, 58, 238)
    draw_panel(surf, r, base_c, (240, 250, 255) if hover else border_col, radius=10, shadow_offset=6 if hover else 4)
    # Barra lateral de acento neon
    pygame.draw.rect(surf, border_col, (x + 5, y + 6, 4, h - 12), border_radius=2)
    pygame.draw.rect(surf, border_col, (x + w - 9, y + 6, 4, h - 12), border_radius=2)
    if hover:
        glow = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*border_col[:3], 48), (0, 0, w, h), border_radius=10)
        surf.blit(glow, (x, y), special_flags=pygame.BLEND_ADD)
        pygame.draw.polygon(surf, border_col, [(x + 14, y + h // 2 - 5), (x + 22, y + h // 2), (x + 14, y + h // 2 + 5)])
        pygame.draw.polygon(surf, border_col, [(x + w - 14, y + h // 2 - 5), (x + w - 22, y + h // 2), (x + w - 14, y + h // 2 + 5)])
    if icon:
        draw_icon(surf, icon, (x + 28, y + h // 2), 8, border_col if not hover else WHITE)
        draw_text(surf, text, font, text_col, (r.centerx + 10, r.centery), True)
    else:
        draw_text(surf, text, font, text_col, r.center, True)

def draw_rotated_panel_or_text(surf, text, font, color, center_pos, angle, bg_color=None, border_color=None):
    txt_img = get_cached_text(text, font, color)
    w, h = txt_img.get_size()
    pad = 12
    surf_size = (w + pad * 2, h + pad * 2)
    temp_surf = pygame.Surface(surf_size, pygame.SRCALPHA)
    if bg_color:
        pygame.draw.rect(temp_surf, bg_color, (0, 0, surf_size[0], surf_size[1]), border_radius=8)
    if border_color:
        pygame.draw.rect(temp_surf, border_color, (0, 0, surf_size[0], surf_size[1]), 2, border_radius=8)
    temp_surf.blit(txt_img, (pad, pad))
    rotated_surf = pygame.transform.rotate(temp_surf, angle)
    rot_rect = rotated_surf.get_rect(center=center_pos)
    surf.blit(rotated_surf, rot_rect.topleft)

GLOW_CACHE = {}

def glow_circle(surf, color, pos, radius, strength=3):
    """Brilho neon aditivo com transição radial suave (Bloom)."""
    x, y = int(pos[0]), int(pos[1])
    radius = max(1, int(radius))
    q_col = (color[0] & 252, color[1] & 252, color[2] & 252)
    key = (q_col, radius, strength)
    if key not in GLOW_CACHE:
        if len(GLOW_CACHE) > 450:
            GLOW_CACHE.clear()
        max_r = int(radius + strength * 4) + 2
        size = max_r * 2 + 2
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        center = (max_r + 1, max_r + 1)
        steps = max(2, strength * 2)
        for i in range(steps, 0, -1):
            rr = int(radius + i * 1.6)
            alpha = max(3, int(48 * ((1.0 - (i / (steps + 1))) ** 1.6)))
            pygame.draw.circle(layer, (*q_col, alpha), center, rr)
        GLOW_CACHE[key] = (layer, max_r + 1)
    layer, offset = GLOW_CACHE[key]
    surf.blit(layer, (x - offset, y - offset), special_flags=pygame.BLEND_ADD)
    pygame.draw.circle(surf, color, (x, y), radius)
    pygame.draw.circle(surf, WHITE, (x, y), radius, 1)
    pygame.draw.circle(surf, (235, 250, 255), (x - int(radius * 0.3), y - int(radius * 0.3)), max(2, int(radius * 0.28)))

def glow_bloom(surf, color, pos, radius, strength=3):
    """Só o halo aditivo (bloom), sem preencher o núcleo — preserva a iluminação neon."""
    x, y = int(pos[0]), int(pos[1])
    radius = max(1, int(radius))
    q_col = (color[0] & 252, color[1] & 252, color[2] & 252)
    key = ("bloom", q_col, radius, strength)
    if key not in GLOW_CACHE:
        if len(GLOW_CACHE) > 450:
            GLOW_CACHE.clear()
        max_r = int(radius + strength * 5) + 3
        size = max_r * 2 + 2
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        center = (max_r + 1, max_r + 1)
        steps = max(3, strength * 3)
        for i in range(steps, 0, -1):
            rr = int(radius + i * 1.8)
            # bloom um pouco mais forte que o original
            alpha = max(4, int(62 * ((1.0 - (i / (steps + 1))) ** 1.45)))
            pygame.draw.circle(layer, (*q_col, alpha), center, rr)
        GLOW_CACHE[key] = (layer, max_r + 1)
    layer, offset = GLOW_CACHE[key]
    surf.blit(layer, (x - offset, y - offset), special_flags=pygame.BLEND_ADD)

# ----------------------------------------------------------------------------
# ORBE 3D (esfera luminosa: volume + neon + specular)
# ----------------------------------------------------------------------------
SPHERE_CACHE = {}

def _mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))

def draw_soft_shadow(surf, x, y, w, h, alpha=90):
    """Sombra elíptica suave sob entidades (sensação de volume/altura)."""
    w, h = max(4, int(w)), max(3, int(h))
    key = (w, h, min(255, int(alpha)))
    if key not in SPHERE_CACHE:
        if len(SPHERE_CACHE) > 200:
            SPHERE_CACHE.clear()
        spr = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        cx, cy = (w + 4) // 2, (h + 4) // 2
        for i in range(6, 0, -1):
            a = int(alpha * (i / 6) ** 1.8)
            rw = int(w * (0.55 + 0.45 * i / 6) / 2)
            rh = int(h * (0.55 + 0.45 * i / 6) / 2)
            pygame.draw.ellipse(spr, (0, 0, 0, a), (cx - rw, cy - rh, rw * 2, rh * 2))
        SPHERE_CACHE[key] = spr
    spr = SPHERE_CACHE[key]
    surf.blit(spr, (int(x) - spr.get_width() // 2, int(y) - spr.get_height() // 2))

def draw_sphere_3d(surf, pos, radius, color, outline=True, flash=False, rim=True, glow=True):
    """Esfera 2.5D luminosa: bloom neon + volume + specular (não apaga a iluminação)."""
    x, y = int(pos[0]), int(pos[1])
    r = max(4, int(radius))
    if flash:
        color = (255, 90, 100)
    # halo bem leve (não vira “bola de luz” azul em volta)
    if glow:
        glow_bloom(surf, color, (x, y), r, strength=2)
    # sombreamento suave (não tão escuro quanto antes — mantém saturação)
    dark = _mix(color, (20, 28, 45), 0.28)
    mid = color
    light = _mix(color, (255, 255, 255), 0.48)
    # corpo
    pygame.draw.circle(surf, dark, (x, y), r)
    pygame.draw.circle(surf, mid, (x - int(r * 0.10), y - int(r * 0.12)), max(3, int(r * 0.88)))
    pygame.draw.circle(surf, light, (x - int(r * 0.22), y - int(r * 0.26)), max(2, int(r * 0.52)))
    # specular forte (sensação de luz)
    pygame.draw.circle(surf, (245, 252, 255), (x - int(r * 0.30), y - int(r * 0.36)), max(2, int(r * 0.24)))
    pygame.draw.circle(surf, (255, 255, 255), (x - int(r * 0.34), y - int(r * 0.40)), max(1, int(r * 0.11)))
    # anel luminoso na borda (rim / neon edge)
    if rim:
        rim_col = _mix(color, (220, 245, 255), 0.55)
        pygame.draw.circle(surf, rim_col, (x, y), r, max(1, r // 7))
        # segundo anel mais fino e claro
        pygame.draw.circle(surf, (255, 255, 255), (x, y), r, 1)
    elif outline:
        pygame.draw.circle(surf, (12, 16, 28), (x, y), r, max(1, r // 10))
    return (x, y)

def draw_orb_character(surf, pos, r, body_col, shoe_col, glow_col, elapsed, moving, flash=False, legs=True, face=True, scale=1.0, shadow=True):
    """Personagem orbe completo com sombra 3D, pernas e cara."""
    px, py = int(pos[0]), int(pos[1])
    r = max(4, int(r * scale))
    bob = math.sin(elapsed * 18) * 2.5 * scale if moving else 0
    leg_swing = math.sin(elapsed * 18) * 6 * scale if moving else 0
    py_anim = py + int(bob)
    outline_col = (10, 15, 30)

    # soft ground shadow (more 3D)
    if shadow:
        draw_soft_shadow(surf, px, py + int(20 * scale), int(36 * scale), int(12 * scale), 100)

    if glow_col:
        # halo bem sutil (como o original) — só um pouco de luz, sem aura grande
        glow_bloom(surf, glow_col if not flash else (200, 0, 0), (px, py_anim), r + 1, strength=2)

    if legs:
        # legs + shoes with slight thickness
        pygame.draw.line(surf, outline_col, (px - int(5 * scale), py_anim + int(10 * scale)),
                         (px - int(5 * scale) - int(leg_swing), py_anim + int(23 * scale)), max(2, int(4 * scale)))
        pygame.draw.rect(surf, outline_col, (px - int(10 * scale) - int(leg_swing), py_anim + int(21 * scale),
                                            int(11 * scale), int(7 * scale)), border_radius=2)
        pygame.draw.rect(surf, shoe_col, (px - int(9 * scale) - int(leg_swing), py_anim + int(22 * scale),
                                         int(9 * scale), int(5 * scale)), border_radius=2)

        pygame.draw.line(surf, outline_col, (px + int(5 * scale), py_anim + int(10 * scale)),
                         (px + int(5 * scale) + int(leg_swing), py_anim + int(23 * scale)), max(2, int(4 * scale)))
        pygame.draw.rect(surf, outline_col, (px + int(1 * scale) + int(leg_swing), py_anim + int(21 * scale),
                                            int(11 * scale), int(7 * scale)), border_radius=2)
        pygame.draw.rect(surf, shoe_col, (px + int(2 * scale) + int(leg_swing), py_anim + int(22 * scale),
                                         int(9 * scale), int(5 * scale)), border_radius=2)

        # arms
        pygame.draw.line(surf, outline_col, (px - int(14 * scale), py_anim + int(2 * scale)),
                         (px - int(19 * scale), py_anim + int(12 * scale)), max(2, int(4 * scale)))
        pygame.draw.circle(surf, outline_col, (px - int(19 * scale), py_anim + int(14 * scale)), max(2, int(4 * scale)))
        pygame.draw.line(surf, outline_col, (px + int(14 * scale), py_anim + int(2 * scale)),
                         (px + int(19 * scale), py_anim + int(12 * scale)), max(2, int(4 * scale)))
        pygame.draw.circle(surf, outline_col, (px + int(19 * scale), py_anim + int(14 * scale)), max(2, int(4 * scale)))

    draw_sphere_3d(surf, (px, py_anim), r, body_col, outline=True, flash=flash, rim=False, glow=False)

    if face and not flash:
        # eyes with slight depth (dark sockets + white)
        pygame.draw.rect(surf, (18, 22, 35), (px - int(8 * scale), py_anim - int(9 * scale), int(7 * scale), int(7 * scale)))
        pygame.draw.rect(surf, WHITE, (px - int(7 * scale), py_anim - int(8 * scale), int(6 * scale), int(6 * scale)))
        pygame.draw.rect(surf, outline_col, (px - int(5 * scale), py_anim - int(2 * scale), int(3 * scale), int(4 * scale)))
        pygame.draw.rect(surf, outline_col, (px + int(3 * scale), py_anim - int(2 * scale), int(3 * scale), int(4 * scale)))
        pygame.draw.lines(surf, outline_col, False,
                          [(px - int(3 * scale), py_anim + int(4 * scale)),
                           (px, py_anim + int(6 * scale)),
                           (px + int(3 * scale), py_anim + int(4 * scale))], max(1, int(2 * scale)))
    return py_anim

# ----------------------------------------------------------------------------
# ILUMINACAO 2D (light map), VIGNETTE DINAMICA E FLASH DE IMPACTO
# ----------------------------------------------------------------------------
LIGHT_SPR = {}
_LM = {"size": None, "half": None, "full": None}
VIG_CACHE = {}
FLASH_CACHE = {}

def get_light_sprite(r, col):
    q = (min(255, col[0]) >> 4 << 4, min(255, col[1]) >> 4 << 4, min(255, col[2]) >> 4 << 4)
    key = (r, q)
    spr = LIGHT_SPR.get(key)
    if spr is None:
        if len(LIGHT_SPR) > 320:
            LIGHT_SPR.clear()
        spr = pygame.Surface((r * 2, r * 2)).convert()
        spr.fill((0, 0, 0))
        steps = 16
        for i in range(steps):
            rad = max(1, int(r * (1.0 - i / steps)))
            k = ((i + 1) / steps) ** 1.8
            pygame.draw.circle(spr, (int(q[0] * k), int(q[1] * k), int(q[2] * k)), (r, r), rad)
        LIGHT_SPR[key] = spr
    return spr

def render_lighting(s, game, cx, cy):
    """Light map em meia resolução multiplicado sobre a cena (so qualidade Alta)."""
    if game.settings.get("quality", 2) < 2 or not game.settings.get("effects", True):
        return
    hw, hh = max(2, W // 2), max(2, H // 2)
    if _LM["size"] != (W, H):
        _LM["half"] = pygame.Surface((hw, hh)).convert()
        _LM["full"] = pygame.Surface((W, H)).convert()
        _LM["size"] = (W, H)
    lm = _LM["half"]
    lm.fill((118, 124, 148))
    sc = game.get_skin_colors()

    def L(x, y, r, col):
        sx, sy, rr = int((x - cx) / 2), int((y - cy) / 2), max(4, int(r / 2))
        if -rr < sx < hw + rr and -rr < sy < hh + rr:
            lm.blit(get_light_sprite(rr, col), (sx - rr, sy - rr), special_flags=pygame.BLEND_ADD)

    bc = sc["bullet"]
    L(game.player.x, game.player.y, 430, (150 + bc[0] // 10, 150 + bc[1] // 10, 150 + bc[2] // 10))
    for b in game.bullets:
        c = b.color if not b.enemy else (200, 40, 60)
        L(b.x, b.y, 70, (c[0] * 6 // 10, c[1] * 6 // 10, c[2] * 6 // 10))
    for e in game.enemies:
        c = e.color
        if e.boss:
            L(e.x, e.y, 260, (c[0] * 6 // 10, c[1] * 6 // 10, c[2] * 6 // 10))
        else:
            L(e.x, e.y, e.r * 3.6, (c[0] * 5 // 10, c[1] * 5 // 10, c[2] * 5 // 10))
    for o in game.orbs:
        L(o.x, o.y, 52, (120, 110, 40) if o.kind == "coin" else ((40, 120, 50) if o.kind == "heal" else (35, 85, 130)))
    for sw in game.shockwaves:
        if sw.life > 0:
            k = sw.life / sw.duration
            L(sw.x, sw.y, sw.max_r * (1.7 - k * 0.5), (int(sw.color[0] * .55 * k) + 20, int(sw.color[1] * .55 * k) + 20, int(sw.color[2] * .55 * k) + 20))
    for pl in getattr(game, "pools", ()):
        pc_ = {"lava": (150, 70, 20), "toxic": (30, 110, 50), "void": (80, 30, 130), "heal": (130, 110, 50), "pad": (0, 90, 120)}.get(pl["kind"])
        if pc_:
            L(pl["x"], pl["y"], pl["r"] * 2.4, pc_)
    pygame.transform.scale(lm, (W, H), _LM["full"])
    s.blit(_LM["full"], (0, 0), special_flags=pygame.BLEND_RGB_MULT)

def _build_vignette(w, h, color, max_a):
    small = pygame.Surface((64, 40), pygame.SRCALPHA)
    for y in range(40):
        for x in range(64):
            u, v = (x / 63 - 0.5) * 2, (y / 39 - 0.5) * 2
            r = math.sqrt(u * u + v * v) / 1.414
            a = max(0.0, min(1.0, (r - 0.42) / 0.58)) ** 1.7
            small.set_at((x, y), (*color, int(a * max_a)))
    return pygame.transform.smoothscale(small, (w, h))

def draw_vignette(s, game):
    if len(VIG_CACHE) > 6:
        VIG_CACHE.clear()
    dark = VIG_CACHE.get(("d", W, H))
    if dark is None:
        dark = VIG_CACHE[("d", W, H)] = _build_vignette(W, H, (0, 0, 6), 190)
    s.blit(dark, (0, 0))
    p = game.player
    frac = p.hp / max(1.0, p.maxhp)
    if frac < 0.40 and game.state == "playing":
        red = VIG_CACHE.get(("r", W, H))
        if red is None:
            red = VIG_CACHE[("r", W, H)] = _build_vignette(W, H, (190, 0, 25), 235)
        strength = (0.40 - frac) / 0.40
        if game.settings.get("reduce_flash", False):
            pulse = 0.7
        else:
            pulse = 0.65 + 0.35 * math.sin(game.elapsed * (5 + 8 * strength))
        red.set_alpha(int(255 * min(1.0, strength) * pulse))
        s.blit(red, (0, 0))

def flash_disc(s, pos, r, k):
    r = max(3, int(r))
    ab = max(1, min(4, int(k * 4 + 0.5)))
    key = (r, ab)
    spr = FLASH_CACHE.get(key)
    if spr is None:
        if len(FLASH_CACHE) > 200:
            FLASH_CACHE.clear()
        spr = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(spr, (255, 255, 255, 60 + ab * 30), (r + 2, r + 2), r)
        pygame.draw.circle(spr, (255, 255, 255, 255), (r + 2, r + 2), r, 2)
        FLASH_CACHE[key] = spr
    s.blit(spr, (int(pos[0]) - r - 2, int(pos[1]) - r - 2))

# ----------------------------------------------------------------------------
# UI PREMIUM: ICONES DESENHADOS, FUNDO DO MENU, CARTOES, HALOS
# ----------------------------------------------------------------------------
GAME_VERSION = "2.4"
BOSS_COUNT = 12
LOGO_FONT = _make_font(96, True)
SUB_FONT = _make_font(20, True)
CARD_T = _make_font(15, True)
BTN_BIG = _make_font(40, True)
STAT_V = _make_font(21, True)

def draw_icon(s, name, c, sz, col):
    """Icones vetoriais simples desenhados com pygame.draw (sem depender de glifos de fonte)."""
    x, y = int(c[0]), int(c[1])
    r = int(sz)
    D = pygame.draw
    dk = (6, 12, 26)
    f = lambda k: int(r * k)
    if name == "clock":
        D.circle(s, col, (x, y), r, 2)
        D.line(s, col, (x, y), (x, y - f(.62)), 2)
        D.line(s, col, (x, y), (x + f(.46), y + f(.12)), 2)
    elif name == "skull":
        D.circle(s, col, (x, y - f(.2)), f(.78))
        D.rect(s, col, (x - f(.42), y + f(.25), f(.84), f(.62)), border_radius=2)
        D.circle(s, dk, (x - f(.3), y - f(.2)), max(1, f(.22)))
        D.circle(s, dk, (x + f(.3), y - f(.2)), max(1, f(.22)))
    elif name == "crown":
        D.polygon(s, col, [(x - r, y + f(.65)), (x - r, y - f(.45)), (x - f(.45), y + f(.1)), (x, y - f(.7)),
                           (x + f(.45), y + f(.1)), (x + r, y - f(.45)), (x + r, y + f(.65))])
    elif name == "coin":
        D.circle(s, col, (x, y), r)
        D.circle(s, dk, (x, y), r, 1)
        D.circle(s, tuple(max(0, v - 80) for v in col[:3]), (x, y), max(2, f(.55)), 2)
    elif name == "bolt":
        D.polygon(s, col, [(x + f(.15), y - r), (x - f(.6), y + f(.15)), (x - f(.05), y + f(.15)),
                           (x - f(.2), y + r), (x + f(.6), y - f(.2)), (x + f(.05), y - f(.2))])
    elif name == "shield":
        D.polygon(s, col, [(x - f(.8), y - f(.7)), (x, y - r), (x + f(.8), y - f(.7)), (x + f(.8), y + f(.1)), (x, y + r), (x - f(.8), y + f(.1))])
        D.line(s, dk, (x, y - f(.6)), (x, y + f(.6)), 1)
    elif name == "sword":
        D.line(s, col, (x - f(.8), y + f(.8)), (x + f(.8), y - f(.8)), 3)
        D.line(s, col, (x - f(.7), y + f(.1)), (x - f(.1), y + f(.7)), 3)
    elif name == "heart":
        D.circle(s, col, (x - f(.45), y - f(.25)), f(.55))
        D.circle(s, col, (x + f(.45), y - f(.25)), f(.55))
        D.polygon(s, col, [(x - r, y - f(.05)), (x + r, y - f(.05)), (x, y + r)])
    elif name == "star":
        pts = []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5
            rr = r if k % 2 == 0 else r * .45
            pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
        D.polygon(s, col, pts)
    elif name == "play":
        D.polygon(s, col, [(x - f(.6), y - r), (x + r, y), (x - f(.6), y + r)])
    elif name == "cards":
        D.rect(s, tuple(v // 2 for v in col[:3]), (x - r, y - f(.6), f(1.2), f(1.5)), border_radius=3)
        D.rect(s, col, (x - f(.2), y - r, f(1.2), f(1.5)), 2, border_radius=3)
    elif name == "paw":
        D.circle(s, col, (x, y + f(.3)), f(.55))
        for ox, oy in ((-.65, -.2), (0, -.55), (.65, -.2)):
            D.circle(s, col, (x + f(ox), y + f(oy)), max(2, f(.28)))
    elif name == "orb":
        D.circle(s, col, (x, y), r)
        D.circle(s, dk, (x - f(.3), y - f(.1)), max(1, f(.15)))
        D.circle(s, dk, (x + f(.3), y - f(.1)), max(1, f(.15)))
        D.circle(s, (230, 250, 255), (x - f(.35), y - f(.42)), max(1, f(.18)))
    elif name == "trophy":
        D.polygon(s, col, [(x - f(.7), y - f(.8)), (x + f(.7), y - f(.8)), (x + f(.5), y + f(.1)), (x - f(.5), y + f(.1))])
        D.rect(s, col, (x - f(.12), y + f(.1), max(2, f(.24)), f(.5)))
        D.rect(s, col, (x - f(.5), y + f(.6), r, max(2, f(.25))))
        D.circle(s, col, (x - f(.8), y - f(.4)), f(.35), 2)
        D.circle(s, col, (x + f(.8), y - f(.4)), f(.35), 2)
    elif name == "gear":
        D.circle(s, col, (x, y), f(.62), 3)
        for k in range(8):
            a = k * math.pi / 4
            D.line(s, col, (x + math.cos(a) * r * .62, y + math.sin(a) * r * .62), (x + math.cos(a) * r, y + math.sin(a) * r), 3)
    elif name == "book":
        D.rect(s, col, (x - f(.8), y - r, f(1.6), r * 2), 2, border_radius=2)
        D.line(s, col, (x - f(.4), y - r), (x - f(.4), y + r), 2)
        D.line(s, col, (x - f(.1), y - f(.4)), (x + f(.5), y - f(.4)), 1)
        D.line(s, col, (x - f(.1), y), (x + f(.5), y), 1)
    elif name == "exit":
        D.rect(s, col, (x - f(.8), y - r, f(1.1), r * 2), 2)
        D.line(s, col, (x - f(.1), y), (x + r, y), 2)
        D.polygon(s, col, [(x + r, y), (x + f(.55), y - f(.4)), (x + f(.55), y + f(.4))])
    elif name == "globe":
        D.circle(s, col, (x, y), r, 2)
        D.ellipse(s, col, (x - f(.4), y - r, f(.8), r * 2), 1)
        D.line(s, col, (x - r, y), (x + r, y), 1)
    elif name == "users":
        D.circle(s, col, (x - f(.42), y - f(.1)), f(.55))
        D.circle(s, tuple(v * 3 // 4 for v in col[:3]), (x + f(.45), y + f(.1)), f(.55))
    elif name == "biome":
        D.polygon(s, col, [(x - r, y + f(.8)), (x - f(.3), y - f(.6)), (x + f(.1), y + f(.1)), (x + f(.4), y - f(.3)), (x + r, y + f(.8))])
        D.circle(s, tuple(min(255, v + 60) for v in col[:3]), (x + f(.5), y - f(.65)), max(2, f(.25)))
    elif name == "diamond":
        D.polygon(s, col, [(x, y - r), (x + f(.7), y), (x, y + r), (x - f(.7), y)])
    elif name == "warn":
        D.polygon(s, col, [(x, y - r), (x + r, y + f(.85)), (x - r, y + f(.85))], 2)
        D.line(s, col, (x, y - f(.35)), (x, y + f(.25)), 2)
        D.circle(s, col, (x, y + f(.6)), max(1, f(.1)))
    elif name == "back":
        D.polygon(s, col, [(x - r, y), (x, y - f(.8)), (x, y + f(.8))])
        D.line(s, col, (x, y), (x + r, y), 3)
    elif name == "check":
        D.lines(s, col, False, [(x - f(.75), y + f(.05)), (x - f(.2), y + f(.65)), (x + f(.85), y - f(.65))], max(2, f(.32)))
    elif name == "cloud":
        D.circle(s, col, (x - f(.35), y + f(.1)), f(.48))
        D.circle(s, col, (x + f(.05), y - f(.15)), f(.58))
        D.circle(s, col, (x + f(.45), y + f(.15)), f(.42))
        D.rect(s, col, (x - f(.45), y + f(.1), f(.95), f(.45)))

def draw_spaced(s, text, font, col, center, track=6):
    imgs = [get_cached_text(ch, font, col) for ch in text]
    total = sum(i.get_width() for i in imgs) + track * (len(imgs) - 1)
    x = center[0] - total // 2
    for im in imgs:
        s.blit(im, (x, center[1] - im.get_height() // 2))
        x += im.get_width() + track

HALO_CACHE = {}
def soft_glow(s, color, pos, radius, alpha=60):
    """Halo radial aditivo (sem disco solido), em cache. Usa superficie opaca preta + BLEND_ADD."""
    radius = max(4, int(radius))
    q = (color[0] & 248, color[1] & 248, color[2] & 248)
    key = (q, radius >> 2, alpha >> 3)
    spr = HALO_CACHE.get(key)
    if spr is None:
        if len(HALO_CACHE) > 120:
            HALO_CACHE.clear()
        rr = max(2, (radius >> 2) << 2)
        spr = pygame.Surface((rr * 2, rr * 2))
        spr.fill((0, 0, 0))
        steps = 16
        peak = alpha / 255.0
        for i in range(steps):
            k = (i + 1) / steps
            f = peak * (k ** 2.2)
            pygame.draw.circle(spr, (int(q[0] * f), int(q[1] * f), int(q[2] * f)), (rr, rr), max(1, int(rr * (1 - i / steps))))
        spr = spr.convert()
        HALO_CACHE[key] = spr
    s.blit(spr, (int(pos[0]) - spr.get_width() // 2, int(pos[1]) - spr.get_height() // 2), special_flags=pygame.BLEND_ADD)

_MENU = {"size": None, "bg": None, "stars": None}
def get_menu_bg(w, h):
    if _MENU["size"] != (w, h):
        small = pygame.Surface((64, 40))
        blobs = [(0.22, 0.55, 0.38, (28, 80, 170)), (0.82, 0.22, 0.32, (110, 40, 175)), (0.62, 0.92, 0.34, (18, 105, 140)), (0.5, 0.0, 0.4, (20, 50, 120))]
        for yy in range(40):
            for xx in range(64):
                ty = yy / 39
                r_, g_, b_ = 3 + 7 * ty, 6 + 10 * ty, 16 + 26 * ty
                for bx, by, rad, col in blobs:
                    d = math.hypot((xx / 63 - bx) * 1.6, yy / 39 - by)
                    k = max(0.0, 1.0 - d / rad) ** 2 * 0.55
                    r_ += col[0] * k
                    g_ += col[1] * k
                    b_ += col[2] * k
                small.set_at((xx, yy), (min(255, int(r_)), min(255, int(g_)), min(255, int(b_))))
        _MENU["bg"] = pygame.transform.smoothscale(small, (w, h)).convert()
        rnd = random.Random(7)
        _MENU["stars"] = [(rnd.random(), rnd.random(), rnd.choice((0, 0, 1, 2)), rnd.random() * 6.28) for _ in range(150)]
        _MENU["size"] = (w, h)
    return _MENU["bg"], _MENU["stars"]

def draw_menu_backdrop(s, t, accent, hero=None):
    bg, stars = get_menu_bg(W, H)
    s.blit(bg, (0, 0))
    for xf, yf, layer, ph in stars:
        sp = (5, 12, 26)[layer]
        x = int((xf * W + t * sp) % W)
        y = int(yf * H)
        v = 90 + int(70 * (0.5 + 0.5 * math.sin(t * 1.5 + ph)))
        col = (v // 2, v * 3 // 4, min(255, v + 40))
        if layer == 2:
            pygame.draw.rect(s, col, (x, y, 2, 2))
        else:
            s.set_at((x, y), col)
    # silhuetas geometricas flutuando (inimigos distantes)
    for i in range(9):
        a = t * (0.05 + i * 0.011) + i * 1.9
        cx = int(W * (0.12 + 0.76 * ((i * 0.37) % 1.0)) + math.cos(a) * 26)
        cy = int(H * (0.12 + 0.76 * ((i * 0.53 + 0.2) % 1.0)) + math.sin(a * 1.3) * 22)
        sz = 14 + (i % 4) * 8
        ang = t * (0.3 + 0.07 * i) * (1 if i % 2 else -1)
        pts = [(cx + math.cos(ang + k * math.pi / 2 + math.pi / 4) * sz * 1.41, cy + math.sin(ang + k * math.pi / 2 + math.pi / 4) * sz * 1.41) for k in range(4)]
        pygame.draw.polygon(s, (14, 26, 54), pts, 2)
    if hero:
        hx, hy = hero
        for i, (R, sp_, n) in enumerate(((150, 0.35, 6), (205, -0.22, 8), (265, 0.14, 10))):
            span = math.tau / n * 0.55
            for k in range(n):
                a0 = t * sp_ + k * math.tau / n
                rect = pygame.Rect(hx - R, hy - R, R * 2, R * 2)
                col = tuple(int(c * (0.55 - i * 0.12)) for c in accent)
                pygame.draw.arc(s, col, rect, a0, a0 + span, 2)

def draw_menu_card(s, rect, title, sub, icon, accent, hover, off=0):
    r = rect.move(0, off - (4 if hover else 0))
    draw_panel(s, r, (22, 50, 96, 247) if hover else (11, 22, 44, 238), (235, 245, 255) if hover else accent, 12, 6)
    if hover:
        soft_glow(s, accent, r.center, max(r.w, r.h) * 0.9, 38)
    pygame.draw.circle(s, (6, 12, 26), (r.x + 34, r.y + 34), 21)
    pygame.draw.circle(s, accent, (r.x + 34, r.y + 34), 21, 2)
    draw_icon(s, icon, (r.x + 34, r.y + 34), 11, accent)
    draw_text(s, title, CARD_T, WHITE, (r.x + 14, r.y + int(r.h * 0.56)))
    for li, ln in enumerate(wrap_text_px(TINY, sub, r.w - 24)[:2]):
        draw_text(s, ln, TINY, (150, 185, 225) if not hover else (205, 230, 255), (r.x + 14, r.y + int(r.h * 0.56) + 22 + li * 14))

def draw_stat_box(s, rect, icon, label, value, col, tag=None):
    draw_panel(s, rect, (10, 20, 42, 238), (40, 85, 150), 10, 4)
    draw_icon(s, icon, (rect.x + 20, rect.centery - 2), 9, col)
    draw_text(s, label, TINY, (130, 165, 205), (rect.x + 38, rect.y + 8))
    draw_text(s, str(value), STAT_V, WHITE, (rect.x + 38, rect.y + 24))
    if tag:
        img = get_cached_text(tag, TINY, (20, 14, 0))
        tr = pygame.Rect(rect.right - img.get_width() - 14, rect.y + 6, img.get_width() + 8, 16)
        pygame.draw.rect(s, GOLD, tr, border_radius=7)
        s.blit(img, (tr.x + 4, tr.y + 2))

_VEIL = {}
def draw_veil(s, alpha):
    key = (W, H)
    v = _VEIL.get(key)
    if v is None:
        if len(_VEIL) > 4:
            _VEIL.clear()
        v = pygame.Surface((W, H))
        v.fill((2, 4, 12))
        _VEIL[key] = v
    v.set_alpha(alpha)
    s.blit(v, (0, 0))

_CARD_IDX = {}
def card_rarity_color(name):
    if not _CARD_IDX:
        for c in CARDS:
            _CARD_IDX[c["name"]] = c
    c = _CARD_IDX.get(name)
    return (RARITY_COLORS.get(c["rarity"], WHITE) if c else WHITE), c

ENEMY_ROLES = {
    "Básico": "Persegue o jogador em linha reta.",
    "Veloz": "Rápido e frágil: corre para cima de você.",
    "Tanque": "Lento e muito resistente.",
    "Atirador": "Mantém distância e atira.",
    "Regenerador": "Recupera vida com o tempo.",
    "Explosivo": "Explode ao morrer, ferindo quem estiver perto.",
    "Teletransportador": "Teleporta para perto de você.",
    "Blindado": "Recebe 25% menos dano dos seus tiros.",
    "Invocador": "Invoca inimigos menores.",
    "Ceifador": "Perseguidor rápido, resistente e de dano alto.",
    "Piromante": "Mantém distância e lança 3 projéteis em leque.",
    "Sentinela Laser": "Mantém distância e dispara tiros rápidos.",
    "Berserker": "Acelera 65% quando abaixo de 50% da vida.",
    "Elite": "Versão perigosa. A partir do nível 8 pode ter afixo.",
    "Aracnídeo": "Avança em zigue-zague para flanquear.",
    "Anomalia": "Persegue e dispara 4 projéteis em leque.",
    "Espelho": "Mantém distância e reflete projéteis frontais.",
    "Parasita": "Veloz; gruda no jogador (lentidão e dano periódico).",
    "Vórtice": "Campo gravitacional puxa o jogador e curva projéteis.",
    "Escudeiro": "Escudo frontal 110°; vulnerável pelas costas.",
    "Bombardeiro": "Telegrafa área vermelha que explode em 0,7 s.",
    "Fantasma": "Alterna entre físico e manto intangível.",
}
WEATHER_PT = {"sparks": "Faíscas", "embers": "Brasas", "spores": "Esporos", "snow": "Neve", "void_rifts": "Fendas do vazio", "divine_light": "Luz divina"}

# ----------------------------------------------------------------------------
# TERRENOS E PERIGOS POR BIOMA (paisagem propria + zonas interativas)
# ----------------------------------------------------------------------------
BIOME_HAZARD = {
    0: ("pad", "Pads de energia (+35% vel) • Variante: Cibernética (Lasers)"),
    1: ("lava", "Poças de lava • Variante: Ígnea (Investida Vulcânica)"),
    2: ("toxic", "Poças tóxicas • Variante: Bio-Tóxica (Tiro Duplo Ácido)"),
    3: ("ice", "Gelo liso • Variante: Glacial (Armadura + Crio-Impulso)"),
    4: ("void", "Fendas do vazio • Variante: Abissal (Salto de Teleporte)"),
    5: ("heal", "Círculos de luz • Variante: Celestial (Feixe em Cruz)"),
    6: ("lava", "Caldeira eruptiva • Variante: Magmática (Erupção ao Morrer)"),
    7: ("void", "Poço abissal • Variante: Espectral (Manto Intangível)"),
    8: ("pad", "Corrente de neon • Variante: Hidro-Neon (Maré Senoidal)"),
    9: ("lava", "Fornalha Ômega • Variante: Ômega (Frenesi abaixo de 60% HP)"),
    10: ("heal", "Cristal prismático • Variante: Prismática (Leque RGB)"),
    11: ("void", "Singularidade • Variante: Cósmica (Gravidade + Perseguidor)"),
}
POOL_SPEC = {"lava": (9, 95, 170), "toxic": (8, 90, 150), "ice": (8, 120, 200), "void": (5, 80, 120), "heal": (5, 90, 120), "pad": (7, 65, 80)}
TERRAIN = {"idx": None, "surf": None}

def build_pools(idx, ww, wh):
    kind = BIOME_HAZARD[idx % len(BIOME_HAZARD)][0]
    n, rmin, rmax = POOL_SPEC[kind]
    rng = random.Random(7000 + idx * 31)
    pools, tries = [], 0
    while len(pools) < n and tries < 800:
        tries += 1
        r = rng.uniform(rmin, rmax)
        x, y = rng.uniform(r + 90, ww - r - 90), rng.uniform(r + 90, wh - r - 90)
        if math.hypot(x - ww / 2, y - wh / 2) < r + 260:
            continue
        if any(math.hypot(x - p["x"], y - p["y"]) < r + p["r"] + 140 for p in pools):
            continue
        pools.append({"kind": kind, "x": x, "y": y, "r": r, "ph": rng.random() * 6.283,
                      "pts": [0.88 + rng.random() * 0.24 for _ in range(16)]})
    return pools

def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

def _rpoly(rng, cx, cy, rad, n=None, j=0.4):
    n = n or rng.randint(5, 8)
    angs = sorted(rng.random() * math.tau for _ in range(n))
    return [(cx + math.cos(a) * rad * (1 - j + rng.random() * j * 2), cy + math.sin(a) * rad * (1 - j + rng.random() * j * 2)) for a in angs]

def _walk(rng, x, y, steps, seg):
    a = rng.random() * math.tau
    pts = [(x, y)]
    for _ in range(steps):
        a += rng.uniform(-0.7, 0.7)
        x += math.cos(a) * rng.uniform(seg * 0.6, seg)
        y += math.sin(a) * rng.uniform(seg * 0.6, seg)
        pts.append((x, y))
    return pts

def build_terrain(idx, ww, wh, pools):
    """Pre-renderiza uma vez a paisagem do bioma (superficie do tamanho do mundo)."""
    rng = random.Random(4200 + idx)
    idx = idx % 12
    surf = pygame.Surface((ww, wh))
    D = pygame.draw
    RX = lambda: rng.uniform(0, ww)
    RY = lambda: rng.uniform(0, wh)
    if idx == 1:      # planeta rochoso vulcanico
        surf.fill((26, 14, 13))
        for _ in range(430):
            pts = _rpoly(rng, RX(), RY(), rng.uniform(55, 150))
            D.polygon(surf, _shade((40, 23, 20), rng.uniform(0.8, 1.25)), pts)
            D.polygon(surf, (15, 8, 8), pts, 2)
        for pl in pools:
            D.circle(surf, (14, 7, 6), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.6))
            D.circle(surf, (30, 15, 11), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.3))
        for _ in range(85):
            pts = _walk(rng, RX(), RY(), rng.randint(6, 14), 55)
            D.lines(surf, (110, 36, 12), False, pts, 6)
            D.lines(surf, (255, 120, 32), False, pts, 2)
            if rng.random() < 0.4:
                D.lines(surf, (255, 210, 90), False, pts, 1)
        for _ in range(300):
            x, y = RX(), RY()
            pts = _rpoly(rng, x, y, rng.uniform(8, 26))
            D.polygon(surf, (22, 13, 12), pts)
            D.line(surf, (96, 56, 44), pts[0], pts[1], 2)
        for _ in range(20):
            x, y, r = RX(), RY(), rng.randint(40, 90)
            D.circle(surf, (18, 10, 9), (int(x), int(y)), r)
            D.circle(surf, (64, 36, 30), (int(x), int(y)), r, 4)
        for _ in range(900):
            surf.set_at((int(RX()), int(RY())), (70, 46, 40))
    elif idx == 2:    # pantano toxico
        surf.fill((9, 24, 15))
        for _ in range(520):
            D.circle(surf, (rng.randint(12, 24), rng.randint(36, 66), rng.randint(20, 34)), (int(RX()), int(RY())), rng.randint(30, 100))
        for pl in pools:
            D.circle(surf, (6, 16, 10), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.5))
            D.circle(surf, (22, 56, 32), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.25))
        for _ in range(70):
            D.lines(surf, (5, 14, 9), False, _walk(rng, RX(), RY(), rng.randint(5, 10), 50), 3)
        for _ in range(22):
            x, y = RX(), RY()
            D.line(surf, (22, 38, 26), (x, y), (x + rng.uniform(-15, 15), y - 90), 5)
            for b in range(3):
                by = y - 30 - b * 25
                D.line(surf, (22, 38, 26), (x, by), (x + rng.choice((-1, 1)) * rng.uniform(25, 50), by - 25), 3)
        for _ in range(80):
            x, y = RX(), RY()
            col = rng.choice(((70, 255, 160), (180, 90, 255), (255, 120, 200)))
            D.circle(surf, _shade(col, 0.18), (int(x), int(y)), 26)
            D.rect(surf, (170, 190, 165), (int(x) - 3, int(y), 6, 14))
            D.ellipse(surf, _shade(col, 0.75), (int(x) - 15, int(y) - 10, 30, 18))
            D.circle(surf, (235, 255, 240), (int(x) - 4, int(y) - 5), 2)
        for _ in range(220):
            x, y = int(RX()), int(RY())
            D.circle(surf, (20, 70, 40), (x, y), 5)
            D.circle(surf, (90, 255, 140), (x, y), 2)
    elif idx == 3:    # tundra congelada
        surf.fill((54, 76, 104))
        for _ in range(260):
            x, y, w, h = RX(), RY(), rng.uniform(120, 320), rng.uniform(50, 130)
            D.ellipse(surf, (92, 122, 156), (x, y, w, h))
            D.ellipse(surf, (128, 158, 190), (x + w * 0.1, y + h * 0.05, w * 0.7, h * 0.55))
        for pl in pools:
            D.circle(surf, (150, 185, 215), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.22))
        for _ in range(60):
            D.lines(surf, (196, 224, 246), False, _walk(rng, RX(), RY(), rng.randint(5, 10), 45), rng.choice((1, 2)))
        for _ in range(160):
            x, y = RX(), RY()
            D.polygon(surf, (40, 52, 72), _rpoly(rng, x, y, rng.uniform(14, 40)))
            D.ellipse(surf, (214, 232, 246), (x - 10, y - 18, 22, 9))
        for _ in range(70):
            x, y = RX(), RY()
            h = rng.uniform(26, 70)
            D.polygon(surf, (160, 215, 245), [(x - 9, y), (x, y - h), (x + 9, y)])
            D.polygon(surf, (232, 248, 255), [(x - 3, y), (x, y - h), (x + 2, y - h * 0.4)])
        for _ in range(500):
            surf.set_at((int(RX()), int(RY())), (225, 242, 255))
    elif idx == 4:    # vazio cosmico
        surf.fill((10, 5, 22))
        for _ in range(120):
            D.circle(surf, (rng.randint(20, 34), rng.randint(8, 16), rng.randint(40, 62)), (int(RX()), int(RY())), rng.randint(80, 220))
        for _ in range(12):
            D.circle(surf, (70, 30, 120), (int(RX()), int(RY())), rng.randint(100, 260), 2)
        for pl in pools:
            D.circle(surf, (4, 0, 10), (int(pl["x"]), int(pl["y"])), int(pl["r"] * 1.35))
        for _ in range(120):
            x, y = RX(), RY()
            pts = _rpoly(rng, x, y, rng.uniform(25, 120), j=0.5)
            D.polygon(surf, (26, 14, 46), pts)
            D.polygon(surf, (96, 46, 150), pts, 2)
        for _ in range(40):
            pts = _walk(rng, RX(), RY(), rng.randint(5, 11), 55)
            D.lines(surf, (90, 20, 150), False, pts, 6)
            D.lines(surf, (230, 110, 255), False, pts, 2)
        for _ in range(700):
            surf.set_at((int(RX()), int(RY())), (rng.randint(120, 200), rng.randint(90, 150), 255))
    elif idx == 5:    # santuario celestial (marmore e ouro)
        tile = 150
        for ty in range(0, wh, tile):
            for tx in range(0, ww, tile):
                D.rect(surf, _shade((58, 48, 30), rng.uniform(0.88, 1.12)), (tx, ty, tile, tile))
                D.rect(surf, (170, 135, 55), (tx, ty, tile, tile), 2)
                D.rect(surf, (96, 78, 40), (tx + 8, ty + 8, tile - 16, tile - 16), 1)
        for _ in range(90):
            D.circle(surf, (74, 62, 38), (int(RX()), int(RY())), rng.randint(60, 140))
        for _ in range(8):
            x, y, r = int(RX()), int(RY()), rng.randint(120, 200)
            D.circle(surf, (150, 120, 50), (x, y), r, 3)
            D.circle(surf, (150, 120, 50), (x, y), int(r * 0.7), 1)
            D.polygon(surf, (150, 120, 50), [(x + math.cos(k * math.pi / 4 * 3) * r * 0.7, y + math.sin(k * math.pi / 4 * 3) * r * 0.7) for k in range(8)], 1)
        for _ in range(30):
            x, y = int(RX()), int(RY())
            D.circle(surf, (20, 15, 8), (x + 5, y + 7), 26)
            D.circle(surf, (66, 54, 32), (x, y), 26)
            D.circle(surf, (190, 155, 70), (x, y), 26, 3)
            D.circle(surf, (90, 74, 44), (x, y), 14)
        for _ in range(400):
            surf.set_at((int(RX()), int(RY())), (230, 195, 100))
    elif idx == 6:  # Caldeira de Magma
        surf.fill((26, 9, 5))
        for _ in range(280):
            pts = _rpoly(rng, RX(), RY(), rng.uniform(40, 120))
            D.polygon(surf, _shade((35, 18, 12), rng.uniform(0.7, 1.2)), pts)
        for _ in range(55):
            pts = _walk(rng, RX(), RY(), rng.randint(8, 16), 70)
            D.lines(surf, (90, 25, 8), False, pts, 24)
            D.lines(surf, (200, 55, 12), False, pts, 14)
            D.lines(surf, (255, 110, 25), False, pts, 8)
            D.lines(surf, (255, 215, 80), False, pts, 2)
        for _ in range(40):
            x, y = RX(), RY()
            D.circle(surf, (18, 8, 6), (int(x), int(y)), int(rng.uniform(18, 42)))
            D.circle(surf, (255, 70, 15), (int(x), int(y)), int(rng.uniform(6, 14)), 2)
            for k in range(3):   # fumaça das crateras
                D.circle(surf, (58, 44, 40), (int(x + rng.uniform(-10, 10)), int(y - 10 - k * 9)), 5 + k * 2, 1)
        for _ in range(200):
            surf.set_at((int(RX()), int(RY())), (255, 120, 40))
    elif idx == 7:  # Cidadela Abissal
        surf.fill((8, 6, 22))
        for _ in range(220):
            x, y = int(RX()), int(RY())
            w, h = int(rng.uniform(40, 100)), int(rng.uniform(40, 100))
            D.rect(surf, (22, 14, 48), (x, y, w, h))
            D.rect(surf, (55, 30, 110), (x, y, w, h), 2)
        for _ in range(90):
            x, y = int(RX()), int(RY())
            D.line(surf, (160, 70, 255), (x, y), (x + rng.randint(-30, 30), y + rng.randint(-40, 40)), 2)
            D.circle(surf, (200, 120, 255), (x, y), 3)
        for _ in range(70):      # runas roxas brilhantes
            x, y = int(RX()), int(RY())
            D.circle(surf, (120, 55, 210), (x, y), 10, 1)
            D.line(surf, (190, 120, 255), (x - 5, y - 5), (x + 5, y + 5), 2)
            D.line(surf, (190, 120, 255), (x + 5, y - 5), (x - 5, y + 5), 2)
            D.line(surf, (190, 120, 255), (x, y - 8), (x, y + 8), 1)
        for _ in range(35):
            x, y = int(RX()), int(RY())
            D.polygon(surf, (30, 18, 55), [(x, y - 50), (x - 18, y + 10), (x + 18, y + 10)])
            D.polygon(surf, (120, 60, 200), [(x, y - 50), (x - 18, y + 10), (x + 18, y + 10)], 2)
        for _ in range(150):
            surf.set_at((int(RX()), int(RY())), (180, 100, 255))
    elif idx == 8:  # Oceano de Neon
        surf.fill((4, 16, 24))
        for gx in range(0, ww, 48):
            D.line(surf, (12, 54, 68), (gx, 0), (gx, wh), 1)
        for gy in range(0, wh, 48):
            D.line(surf, (12, 54, 68), (0, gy), (ww, gy), 1)
        for _ in range(70):
            x, y = RX(), RY()
            for k in range(5):
                D.circle(surf, (0, max(0, 180 - k * 25), max(0, 200 - k * 20)), (int(x), int(y)), 20 + k * 18, 1)
        for _ in range(100):
            x, y = int(RX()), int(RY())
            D.line(surf, (0, 255, 220), (x, y), (x + rng.randint(20, 60), y), 2)
        for _ in range(220):
            surf.set_at((int(RX()), int(RY())), (80, 255, 230))
    elif idx == 9:  # Trono Omega
        surf.fill((22, 5, 12))
        for _ in range(180):
            x, y = int(RX()), int(RY())
            r = int(rng.uniform(20, 55))
            pts = [(x + int(math.cos(a) * r), y + int(math.sin(a) * r)) for a in [k * math.pi / 3 for k in range(6)]]
            D.polygon(surf, (45, 12, 22), pts)
            D.polygon(surf, (155, 30, 60), pts, 2)
        for _ in range(80):
            x, y = int(RX()), int(RY())
            D.line(surf, (255, 40, 80), (x, y), (x + rng.randint(-50, 50), y + rng.randint(-50, 50)), 3)
        for _ in range(40):
            x, y = int(RX()), int(RY())
            D.circle(surf, (255, 45, 95), (x, y), 12, 2)
        for _ in range(180):
            surf.set_at((int(RX()), int(RY())), (255, 80, 120))
    elif idx == 10:  # Jardim Prismatico
        surf.fill((16, 8, 22))
        cols = [(255, 110, 230), (120, 200, 255), (255, 220, 80), (160, 255, 140)]
        for _ in range(250):
            x, y = int(RX()), int(RY())
            c = cols[rng.randint(0, 3)]
            s = int(rng.uniform(12, 36))
            D.polygon(surf, c, [(x, y - s), (x + s, y), (x, y + s), (x - s, y)], 1)
            D.circle(surf, c, (x, y), 4)
        for _ in range(60):
            x, y = int(RX()), int(RY())
            c = cols[rng.randint(0, 3)]
            for a in range(0, 360, 45):
                rad = math.radians(a)
                D.line(surf, c, (x, y), (x + int(math.cos(rad) * 40), y + int(math.sin(rad) * 40)), 1)
        for _ in range(200):
            surf.set_at((int(RX()), int(RY())), cols[rng.randint(0, 3)])
    elif idx == 11:  # Horizonte de Eventos
        surf.fill((4, 5, 14))
        for _ in range(50):
            x, y = RX(), RY()
            for k in range(8):
                D.circle(surf, (40 + k * 8, 50 + k * 10, 90 + k * 12), (int(x), int(y)), 30 + k * 22, 1)
        for _ in range(30):
            x, y = int(RX()), int(RY())
            D.circle(surf, (10, 12, 28), (x, y), int(rng.uniform(25, 70)))
            D.circle(surf, (120, 140, 200), (x, y), int(rng.uniform(25, 70)), 1)
        for _ in range(500):
            surf.set_at((int(RX()), int(RY())), (220, 230, 255))
        for _ in range(40):
            x, y = int(RX()), int(RY())
            D.line(surf, (180, 200, 255), (x, y), (x + rng.randint(-80, 80), y + rng.randint(-20, 20)), 1)
    else:
        surf.fill((6, 9, 20))
    return surf.convert()

def get_terrain_surface(idx, ww, wh, pools):
    if TERRAIN["idx"] != idx:
        TERRAIN["surf"] = build_terrain(idx, ww, wh, pools)
        TERRAIN["idx"] = idx
    return TERRAIN["surf"]

def draw_coin_icon(surf, pos, radius=8, phase=0.0):
    x, y = int(pos[0]), int(pos[1])
    w = max(3, int(radius * abs(math.cos(phase))))
    pygame.draw.ellipse(surf, GOLD, (x - w, y - radius, w * 2, radius * 2))
    pygame.draw.ellipse(surf, WHITE, (x - w, y - radius, w * 2, radius * 2), 1)
    if w >= 5:
        pygame.draw.line(surf, (180, 120, 10), (x, y - radius // 2), (x, y + radius // 2), 2)


def mix_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def wrap_text_px(font, text, max_w):
    """Quebra o texto traduzido em linhas respeitando a largura em pixels."""
    lines, cur = [], ""
    for word in tr_text(text).split():
        test = (cur + " " + word).strip()
        if font.size(test)[0] <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines

def render_upgrade_card(card, index, w, h, hover=False):
    """Carta Holográfica de melhoria com losango superior iluminado, faixas de energia e halo neon."""
    col = RARITY_COLORS[card["rarity"]]
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    lcx = w // 2
    hw = w // 2 - 4
    hh = 76
    cy = hh + 4
    taper = 64
    bot = h - 4
    edge = (255, 255, 255) if hover else mix_color(col, (255, 255, 255), 0.78)
    body_fill = (34, 44, 86, 252) if hover else (18, 24, 50, 246)

    body = [(lcx - hw, cy), (lcx + hw, cy), (lcx + hw, bot - taper), (lcx, bot), (lcx - hw, bot - taper)]
    pygame.draw.polygon(surf, body_fill, body)

    for k in range(3):
        yy = cy + 60 + k * 75
        pygame.draw.line(surf, (*col, 26 if not hover else 52), (lcx - hw + 14, yy), (lcx + hw - 14, yy - 28), 6)

    if hover:
        halo = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(halo, (*col, 48), body)
        surf.blit(halo, (0, 0), special_flags=pygame.BLEND_ADD)

    side = [(lcx - hw, cy), (lcx - hw, bot - taper), (lcx, bot), (lcx + hw, bot - taper), (lcx + hw, cy)]
    pygame.draw.lines(surf, edge, False, side, 4)
    for pt in side[1:-1]:
        pygame.draw.circle(surf, edge, pt, 2)
    inner = [(lcx - hw + 10, cy + 24), (lcx - hw + 10, bot - taper - 3), (lcx, bot - 17),
             (lcx + hw - 10, bot - taper - 3), (lcx + hw - 10, cy + 24)]
    pygame.draw.lines(surf, col, False, inner, 1)

    dia = [(lcx, 4), (lcx + hw, cy), (lcx, cy + hh), (lcx - hw, cy)]
    pygame.draw.polygon(surf, mix_color(col, (0, 0, 0), 0.06 if hover else 0.24), dia)
    pygame.draw.polygon(surf, edge, dia, 4)

    nm = card["name"]
    font = CARD_NAME_FONT
    lines = wrap_text_px(font, nm, 160)
    if len(lines) > 2:
        font = CARD_NAME_FONT_S
        lines = wrap_text_px(font, nm, 170)
    lh = font.get_linesize() + 1
    y0 = cy - (len(lines) - 1) * lh / 2
    for j, ln in enumerate(lines):
        pos = (lcx, int(y0 + j * lh))
        sh = get_cached_text(ln, font, (8, 10, 22))
        surf.blit(sh, sh.get_rect(center=(pos[0] + 1, pos[1] + 2)))
        im = get_cached_text(ln, font, WHITE)
        surf.blit(im, im.get_rect(center=pos))

    img_rar = get_cached_text(card["rarity"].upper(), SMALL, mix_color(col, (255, 255, 255), 0.30))
    surf.blit(img_rar, img_rar.get_rect(center=(lcx, cy + hh + 20)))
    tags = card.get("tags") or CARD_TAGS.get(card["name"], [])
    if tags:
        tag_txt = " · ".join(tags)
        img_tag = get_cached_text(tag_txt, TINY, mix_color(col, (200, 230, 255), 0.5))
        surf.blit(img_tag, img_tag.get_rect(center=(lcx, cy + hh + 38)))
    pygame.draw.line(surf, col, (lcx - 52, cy + hh + 36), (lcx + 52, cy + hh + 36), 2)
    pygame.draw.circle(surf, WHITE, (lcx, cy + hh + 36), 3)

    area_top = cy + hh + 50
    area_bot = bot - taper - 40
    font = CARD_DESC_FONT
    lines = wrap_text_px(font, card["desc"], w - 62)
    if len(lines) * (font.get_linesize()) > area_bot - area_top:
        font = CARD_DESC_FONT_S
        lines = wrap_text_px(font, card["desc"], w - 58)
    lh = font.get_linesize() + 1
    y0 = area_top + max(0, (area_bot - area_top - len(lines) * lh) // 2) + lh // 2
    for j, ln in enumerate(lines):
        pos = (lcx, int(y0 + j * lh))
        sh = get_cached_text(ln, font, (8, 10, 22))
        surf.blit(sh, sh.get_rect(center=(pos[0] + 1, pos[1] + 2)))
        im = get_cached_text(ln, font, WHITE)
        surf.blit(im, im.get_rect(center=pos))

    btn_rect = pygame.Rect(lcx - 58, bot - taper - 32, 116, 26)
    pygame.draw.rect(surf, col if hover else (26, 38, 68), btn_rect, border_radius=7)
    pygame.draw.rect(surf, edge, btn_rect, 1, border_radius=7)
    img_btn = get_cached_text(f"TECLA {index + 1}", SMALL, WHITE)
    surf.blit(img_btn, img_btn.get_rect(center=btn_rect.center))
    return surf

def xp_required(level):
    """Curva suave: 1.20 até o nv.25, depois o expoente desacelera gradualmente."""
    lv = max(1, int(level))
    if lv <= 25:
        base = 110 * (1.20 ** (lv - 1))
    else:
        # após 25: exp diminui de 1.20 para ~1.12
        exp = 1.20 - min(0.08, (lv - 25) * 0.004)
        base = 110 * (1.20 ** 24) * (exp ** (lv - 25))
    return max(1, math.ceil(base))

# ----------------------------------------------------------------------------
# DADOS DE CARTAS E INIMIGOS
# ----------------------------------------------------------------------------
CARD_DATA = [    ("Vitalidade", "Vida máxima +20.", "max_hp", 20, "Comum"),
    ("Coração Extra", "Vida máxima +35.", "max_hp", 35, "Incomum"),
    ("Regeneração", "Recupera 1,2 de vida por segundo.", "regen", 1.2, "Rara"),
    ("Cura Emergencial", "Recupera 40% da vida máxima imediatamente.", "heal", .40, "Incomum"),
    ("Pele Resistente", "Reduz dano recebido em 10%.", "armor", .10, "Incomum"),
    ("Armadura Reforçada", "Reduz dano recebido em 15%.", "armor", .15, "Rara"),
    ("Escudo de Energia", "Concede 35 pontos de escudo recarregável.", "shield", 35, "Rara"),
    ("Muralha de Plasma", "O teu escudo regenera automaticamente 1,5/s.", "shield_regen", 1.5, "Épica"),
    ("Última Chance", "Uma vez, evita a morte, explode a tela e deixa 20% HP.", "lastchance", 1, "Lendária"),
    ("Recuperação", "Aumenta toda cura recebida em 25%.", "healing", .25, "Rara"),
    ("Barreira Temporal", "Invulnerabilidade após dano +0,35 s.", "invuln", .35, "Incomum"),
    ("Triângulos Poderosos", "Dano dos projéteis +20%.", "damage", .20, "Comum"),
    ("Disparo Rápido", "Velocidade de disparo +16%.", "firerate", .16, "Comum"),
    ("Projétil Veloz", "Velocidade dos projéteis +25%.", "bulletspeed", .25, "Comum"),
    ("Tiro Duplo", "Adiciona +1 projétil por disparo.", "multishot", 1, "Rara"),
    ("Tiro Triplo", "Garante pelo menos 3 projéteis em leque.", "triple", 1, "Épica"),
    ("Perfuração", "Projéteis atravessam +1 inimigo extra.", "pierce", 1, "Rara"),
    ("Ricochete", "Projéteis saltam para outro inimigo (+1 salto).", "ricochet", 1, "Épica"),
    ("Dano Crítico", "Chance crítica +8 pontos percentuais.", "crit", .08, "Incomum"),
    ("Impacto Brutal", "Multiplicador de dano crítico +50%.", "critdamage", .5, "Rara"),
    ("Caçador de Elites", "Dano contra inimigos especiais +25%.", "elite", .25, "Rara"),
    ("Matador de Chefes", "Dano contra chefes +20%.", "bossdamage", .20, "Épica"),
    ("Explosão Triangular", "Impactos causam explosão em área.", "explosive", 1, "Épica"),
    ("Passos Rápidos", "Velocidade de movimento +12%.", "speed", .12, "Comum"),
    ("Impulso Azul", "Espaço ativa avanço invulnerável com recarga.", "dash", 1, "Rara"),
    ("Corpo Leve", "Movimento mais ágil (+8% velocidade).", "speed", .08, "Incomum"),
    ("Esquiva Energética", "Chance de evitar dano +8%.", "dodge", .08, "Rara"),
    ("Aceleração", "Abates concedem +30% velocidade por 2 s.", "killboost", 1, "Incomum"),
    ("Campo Repulsor", "Onda de choque empurra inimigos próximos.", "repulse", 1, "Épica"),
    ("Aprendizado Rápido", "XP recebido +15%.", "xp", .15, "Comum"),
    ("Conhecimento Avançado", "XP recebido +25%.", "xp", .25, "Rara"),
    ("Ímã de Experiência", "Raio de coleta de orbes e moedas +100.", "magnet", 100, "Comum"),
    ("Orbes Valiosos", "Valor dos orbes de XP +20%.", "orbxp", .20, "Incomum"),
    ("Cobiça Dourada", "Inimigos largam +35% mais Moedas.", "coin_bonus", .35, "Incomum"),
    ("Execução Premiada", "Elites concedem +35% XP e +1 sorteio de carta.", "elite_xp", .35, "Rara"),
    ("Bônus de Sobrevivência", "Recebe pacote de XP, cura e moedas a cada 45s.", "survivalxp", 1, "Épica"),
    ("Caçador Experiente", "XP de chefes aumentado em +50%.", "bossxp", .5, "Épica"),
    ("Núcleo Energético", "Dano +20%, mas movimento -8%.", "core", 1, "Épica"),
    ("Canhão Azul", "Projéteis maiores, +15% dano e empurrão.", "cannon", 1, "Rara"),
    ("Sobrecarga", "A cada 10 s, entra em frenesi de disparo por 2,5 s.", "overload", 1, "Lendária"),
    ("Aura Destrutiva", "Campo elétrico causa dano contínuo ao redor.", "aura", 1, "Épica"),
    ("Dreno Vital", "Recupera vida ao derrotar inimigos.", "lifesteal", 1, "Rara"),
    ("Duplicação Energética", "Chance de +25% de disparar projétil extra.", "duplicate", .25, "Rara"),
    ("Campo de Lentidão", "Congela parcialmente inimigos próximos (-40% vel.).", "slowfield", 1, "Épica"),
    ("Explosão ao Morrer", "Inimigos abatidos têm 22% de chance de explodir.", "deathboom", .22, "Rara"),
    ("Proteção de Elite", "Elites derrotados concedem +18 de escudo.", "eliteshield", 1, "Épica"),
    ("Fúria Azul", "Dano +25% quando a vida está abaixo de 40%.", "fury", .25, "Lendária"),
    ("Evolução Suprema", "Dano +12%, Vida Máx +15 e +1 Sorteio de Carta.", "supreme", 1, "Lendária"),
    ("Orbes Orbitais", "Invoca 1 satélite de plasma que gira ao seu redor.", "orbitals", 1, "Lendária"),
    ("Relâmpago em Cadeia", "Impactos têm 22% de chance de eletrocutar 1 inimigo próximo.", "chain_lightning", 1, "Lendária"),
    ("Catalisador Supremo", "O Ataque Especial [Q] carrega 25% mais rápido.", "ult_charge", .25, "Épica"),
    ("Ascensão Mítica", "Dano +15%, +1 Projétil, +15 Vida Máx e +15 Escudo.", "mythic_ascension", 1, "Mítica"),
    ("Lâminas Fantasmas", "Projéteis ganham +1 Perfuração e +1 Ricochete.", "phantom_blades", 1, "Mítica"),
    ("Fúria Relâmpago", "Cadência de tiro +18% e Velocidade +10%.", "storm_fury", 1, "Lendária"),
    ("Couraça de Titânio", "Vida Máxima +40, Armadura +8% e +20 Escudo.", "titan_plate", 1, "Lendária"),
    ("Chuva de Meteoros", "A cada 7 s, invoca explosões solares em até 3 inimigos.", "meteor_shower", 1, "Divina"),
    ("Bênção do Arcanjo", "Regenera 2,5 HP/s, +1,5/s Escudo e +20% Dano Crítico.", "archangel_grace", 1, "Divina"),
    ("Decreto Supremo", "Dano +28%, +1 Projétil, +30 HP Máx e +1 Orbital.", "supreme_decree", 1, "Suprema"),
    ("Coração Primordial", "Vida máxima +55 e recupera 15% da vida.", "max_hp", 55, "Primordial"),
    ("Marca do Caçador", "30% de chance de marcar o alvo: ele recebe +25% de dano.", "mark", 1, "Incomum"),
    ("Balas Incendiárias", "35% de chance de queimar o alvo por 3 s (dano contínuo).", "burn", 1, "Rara"),
    ("Veneno Neurotóxico", "40% de chance de envenenar. O veneno acumula até 5 vezes.", "poison", 1, "Rara"),
    ("Toque Gélido", "25% de chance de congelar: o inimigo fica 55% mais lento.", "freeze", 1, "Épica"),
    ("Catalisador Elemental", "+15% chance de status. Queimar + congelar causa VAPOR (dano em área x2).", "catalyst", 1, "Lendária"),
    ("Tempestade Elemental", "+12% chance de status e dano contínuo +50%.", "elemental_storm", 1, "Mítica"),
    ("Mísseis Teleguiados", "Projéteis curvam suavemente na direção dos inimigos.", "homing", 1, "Épica"),
    ("Chuva de Triângulos", "A cada 3,5 s dispara uma salva de 14 projéteis em 360°.", "rain", 1, "Lendária"),
    ("Singularidade Azul", "A cada 7 s cria um buraco negro que suga e causa dano contínuo.", "blackhole", 1, "Mítica"),
    ("Arsenal Infinito", "+2 Projéteis por disparo e +20% Velocidade de Disparo.", "infinite_arsenal", 1, "Divina"),
    ("Onipotência Azul", "Dano e Cadência +25%, Velocidade +15%, Crítico +12% e Última Chance.", "omnipotence", 1, "Suprema"),
    ("Núcleo da Eternidade", "Dano +35%, +2 Orbitais, +40 Escudo e recarga do Supremo +35%.", "eternity_core", 1, "Transcendente"),
]


# Tags por carta (sinergias: 3+ da mesma tag = bônus)
CARD_TAGS = {
    "Vitalidade": ["Escudo"], "Coração Extra": ["Escudo"], "Regeneração": ["Escudo"],
    "Cura Emergencial": ["Escudo"], "Pele Resistente": ["Escudo"], "Armadura Reforçada": ["Escudo"],
    "Escudo de Energia": ["Escudo"], "Muralha de Plasma": ["Escudo"], "Última Chance": ["Escudo"],
    "Recuperação": ["Escudo"], "Barreira Temporal": ["Escudo"], "Couraça de Titânio": ["Escudo"],
    "Bênção do Arcanjo": ["Escudo"], "Coração Primordial": ["Escudo"],
    "Triângulos Poderosos": ["Crítico"], "Disparo Rápido": ["Crítico"], "Projétil Veloz": ["Crítico"],
    "Tiro Duplo": ["Crítico"], "Tiro Triplo": ["Crítico"], "Perfuração": ["Crítico"],
    "Ricochete": ["Crítico"], "Dano Crítico": ["Crítico"], "Impacto Brutal": ["Crítico"],
    "Explosão Triangular": ["Fogo"], "Balas Incendiárias": ["Fogo"], "Canhão Azul": ["Crítico"],
    "Sobrecarga": ["Raio"], "Aura Destrutiva": ["Raio"], "Relâmpago em Cadeia": ["Raio"],
    "Fúria Relâmpago": ["Raio"], "Toque Gélido": ["Gelo"], "Campo de Lentidão": ["Gelo"],
    "Veneno Neurotóxico": ["Veneno"], "Marca do Caçador": ["Crítico"],
    "Catalisador Elemental": ["Fogo", "Gelo"], "Tempestade Elemental": ["Fogo", "Veneno"],
    "Orbes Orbitais": ["Orbital"], "Ascensão Mítica": ["Orbital", "Crítico"],
    "Lâminas Fantasmas": ["Crítico"], "Decreto Supremo": ["Orbital", "Crítico"],
    "Chuva de Meteoros": ["Fogo"], "Cobiça Dourada": ["Economia"], "Orbes Valiosos": ["Economia"],
    "Aprendizado Rápido": ["Economia"], "Conhecimento Avançado": ["Economia"],
    "Ímã de Experiência": ["Economia"], "Fúria Azul": ["Crítico"], "Núcleo Energético": ["Crítico"],
    "Mísseis Teleguiados": ["Crítico"], "Chuva de Triângulos": ["Crítico"],
    "Singularidade Azul": ["Orbital"], "Arsenal Infinito": ["Crítico"],
    "Onipotência Azul": ["Crítico", "Escudo"], "Núcleo da Eternidade": ["Orbital", "Escudo"],
}

SYNERGY_BONUS = {
    "Fogo": "Queimaduras +25% de duração e dano",
    "Gelo": "Congelamento +15% de lentidão",
    "Raio": "Cadeia elétrica +10% chance",
    "Veneno": "Veneno acumula até 6 stacks",
    "Escudo": "Escudo máximo efetivo +15%",
    "Crítico": "Chance crítica +6%",
    "Orbital": "Orbitais causam +20% dano",
    "Economia": "Moedas e XP +12%",
}

CARDS = [dict(name=n, desc=d, effect=e, value=v, rarity=r) for n, d, e, v, r in CARD_DATA]
for _c in CARDS:
    _c["tags"] = CARD_TAGS.get(_c["name"], [])

ENEMY_TYPES = {
    "Básico": ((230, 50, 60), 22, 72, 9, 12, 1.0),
    "Veloz": ((245, 140, 40), 14, 130, 6, 14, 1.15),
    "Tanque": ((150, 50, 220), 65, 44, 16, 25, .85),
    "Atirador": ((245, 200, 45), 24, 52, 8, 20, 1.0),
    "Regenerador": ((100, 230, 140), 32, 48, 7, 22, 1.0),
    "Explosivo": ((70, 200, 220), 19, 88, 18, 19, 1.1),
    "Teletransportador": ((235, 240, 255), 28, 80, 10, 22, 1.0),
    "Blindado": ((70, 75, 85), 58, 48, 12, 24, .65),
    "Invocador": ((240, 100, 180), 40, 42, 8, 28, 1.0),
    "Ceifador": ((170, 30, 240), 46, 112, 15, 32, 1.1),
    "Piromante": ((255, 95, 25), 36, 58, 12, 30, 1.0),
    "Sentinela Laser": ((0, 235, 210), 44, 50, 13, 34, 1.0),
    "Berserker": ((200, 20, 45), 54, 86, 17, 35, 1.05),
    "Elite": ((240, 180, 30), 105, 62, 20, 48, 1.2),
    "Aracnídeo": ((255, 70, 180), 34, 105, 11, 29, 1.1),
    "Anomalia": ((160, 100, 255), 72, 38, 18, 42, .9),
    "Espelho": ((200, 225, 255), 42, 56, 12, 30, 1.0),
    "Parasita": ((135, 255, 70), 20, 134, 9, 24, 1.1),
    "Vórtice": ((130, 60, 235), 58, 46, 14, 34, 0.9),
    "Escudeiro": ((145, 165, 195), 70, 50, 15, 32, 0.75),
    "Bombardeiro": ((255, 115, 45), 38, 52, 16, 30, 1.0),
    "Fantasma": ((175, 210, 255), 32, 92, 13, 28, 1.05),
}

# ----------------------------------------------------------------------------
# EFEITOS VISUAIS E EFEITOS ESPECIAIS DO SUPREMO DE CADA COR
# ----------------------------------------------------------------------------
class FloatingText:
    def __init__(self, x, y, text, color=WHITE, crit=False):
        self.x = x + random.uniform(-10, 10)
        self.y = y - 10
        self.vy = -55 if not crit else -75
        self.text = str(text)
        self.color = color
        self.crit = crit
        self.life = 0.65 if not crit else 0.85
        self.maxlife = self.life

    def update(self, dt):
        self.y += self.vy * dt
        self.vy *= max(0.0, 1.0 - 3.5 * dt)
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        sx, sy = int(self.x - cx), int(self.y - cy)
        if not (-50 < sx < W + 50 and -50 < sy < H + 50):
            return
        font = MED if self.crit else SMALL
        draw_text(s, self.text, font, self.color, (sx, sy), center=True)

class Shockwave:
    def __init__(self, x, y, max_r, color=CYAN, duration=0.35, width=3):
        self.x = x
        self.y = y
        self.max_r = max_r
        self.color = color
        self.duration = duration
        self.life = duration
        self.width = width

    def update(self, dt):
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        prog = 1.0 - (self.life / self.duration)
        r = int(max(3, self.max_r * math.sin(prog * (math.pi / 2))))
        w = max(1, int(self.width * (1.0 - prog * 0.75)))
        sx, sy = int(self.x - cx), int(self.y - cy)
        if not (-r < sx < W + r and -r < sy < H + r):
            return
        k = max(0.12, 1.0 - prog * 0.85)
        col = (int(self.color[0] * k), int(self.color[1] * k), int(self.color[2] * k))
        pygame.draw.circle(s, col, (sx, sy), r, w + 1)
        if r > 10:
            pygame.draw.circle(s, (int(235 * k), int(240 * k), int(255 * k)), (sx, sy), max(1, r - 3), 1)

class UltimateEffectVisual:
    """Desenha efeitos visuais exclusivos para o Ataque Especial [Q] consoante a cor equipada."""
    def __init__(self, x, y, style, color, targets=None):
        self.x = x
        self.y = y
        self.style = style
        self.color = color
        self.targets = targets or []
        self.duration = 0.75
        self.life = self.duration

    def update(self, dt):
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        prog = 1.0 - (self.life / self.duration)
        sx, sy = int(self.x - cx), int(self.y - cy)

        if self.style == "toxic":
            # Nuvens bioquímicas e símbolos radioativos em expansão
            for i in range(8):
                ang = prog * 3.0 + i * (math.tau / 8)
                dist = prog * 420
                bx = sx + int(math.cos(ang) * dist)
                by = sy + int(math.sin(ang) * dist)
                rad = max(4, int(34 * (1.0 - prog)))
                glow_circle(s, (40, 245, 95), (bx, by), rad, 2)
        elif self.style == "blood":
            # Lâminas e espinhos carmesim a rasgar a arena
            for i in range(12):
                ang = i * (math.tau / 12)
                r_in = prog * 180
                r_out = prog * 460
                p1 = (sx + math.cos(ang) * r_out, sy + math.sin(ang) * r_out)
                p2 = (sx + math.cos(ang + 0.12) * r_in, sy + math.sin(ang + 0.12) * r_in)
                p3 = (sx + math.cos(ang - 0.12) * r_in, sy + math.sin(ang - 0.12) * r_in)
                pygame.draw.polygon(s, (255, 35, 65), [p1, p2, p3])
                pygame.draw.polygon(s, WHITE, [p1, p2, p3], 1)
        elif self.style == "divine":
            # Pilares celestiais dourados a cair do céu sobre os inimigos
            w_beam = max(2, int(28 * (1.0 - prog)))
            for tx, ty in self.targets[:18]:
                tsx, tsy = int(tx - cx), int(ty - cy)
                pygame.draw.line(s, GOLD, (tsx, tsy - 500), (tsx, tsy), w_beam)
                pygame.draw.line(s, WHITE, (tsx, tsy - 500), (tsx, tsy), max(1, w_beam // 3))
                pygame.draw.circle(s, GOLD, (tsx, tsy), int(35 * prog), 2)
        elif self.style == "void":
            # Fendas gravitacionais negras e roxas que implodem
            r_void = int(440 * (1.0 - prog * 0.6))
            pygame.draw.circle(s, (35, 10, 65), (sx, sy), max(10, int(95 * (1.0 - prog))))
            pygame.draw.circle(s, PURPLE, (sx, sy), r_void, 3)
            for tx, ty in self.targets[:16]:
                tsx, tsy = int(tx - cx), int(ty - cy)
                pygame.draw.circle(s, (20, 5, 40), (tsx, tsy), max(4, int(26 * (1.0 - prog))))
                pygame.draw.circle(s, (210, 120, 255), (tsx, tsy), max(6, int(30 * (1.0 - prog))), 2)
        elif self.style == "solar":
            # Explosão de chamas solares e anéis de magma
            for i in range(10):
                ang = -prog * 2.5 + i * (math.tau / 10)
                dist = prog * 440
                bx = sx + int(math.cos(ang) * dist)
                by = sy + int(math.sin(ang) * dist)
                glow_circle(s, (255, 140, 20), (bx, by), max(5, int(38 * (1.0 - prog))), 3)
        elif self.style == "frost":
            # Estilhaços e flocos gigantes de gelo sub-zero
            for i in range(8):
                ang = i * (math.tau / 8)
                dist = prog * 450
                ex = sx + int(math.cos(ang) * dist)
                ey = sy + int(math.sin(ang) * dist)
                pygame.draw.line(s, (200, 245, 255), (sx, sy), (ex, ey), 4)
                pygame.draw.circle(s, WHITE, (ex, ey), max(4, int(18 * (1.0 - prog))), 2)
        elif self.style == "prism":
            # Feixes arco-íris em rotação cromática
            for i in range(16):
                hue = (prog + i / 16.0) % 1.0
                rc, gc, bc = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.85, 1.0)]
                ang = prog * 2.0 + i * (math.tau / 16)
                ex = sx + int(math.cos(ang) * (prog * 480))
                ey = sy + int(math.sin(ang) * (prog * 480))
                pygame.draw.line(s, (rc, gc, bc), (sx, sy), (ex, ey), 4)

class LightningBolt:
    """Efeito de raio elétrico entre dois pontos."""
    def __init__(self, x1, y1, x2, y2, color=CYAN):
        self.pts = [(x1, y1)]
        steps = 5
        for i in range(1, steps):
            t = i / steps
            px = x1 + (x2 - x1) * t + random.uniform(-14, 14)
            py = y1 + (y2 - y1) * t + random.uniform(-14, 14)
            self.pts.append((px, py))
        self.pts.append((x2, y2))
        self.color = color
        self.life = 0.16

    def update(self, dt):
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0 or len(self.pts) < 2:
            return
        screen_pts = [(int(px - cx), int(py - cy)) for px, py in self.pts]
        pygame.draw.lines(s, self.color, False, screen_pts, 3)
        pygame.draw.lines(s, WHITE, False, screen_pts, 1)

class BlackHoleEffect:
    """Singularidade que atrai inimigos e causa dano contínuo."""
    def __init__(self, x, y, damage):
        self.x = x
        self.y = y
        self.damage = damage
        self.life = 3.2
        self.maxlife = 3.2
        self.radius = 165
        self.angle = 0.0

    def update(self, dt, g):
        self.life -= dt
        self.angle += dt * 7.5
        for en in g.enemies:
            if not en.alive:
                continue
            dx = self.x - en.x
            dy = self.y - en.y
            dist = math.hypot(dx, dy)
            if 0 < dist < self.radius:
                nx, ny = dx / dist, dy / dist
                pull = (145 if not en.boss else 35) * dt
                en.x = clamp(en.x + nx * pull, 30, g.world_w - 30)
                en.y = clamp(en.y + ny * pull, 30, g.world_h - 30)
                en.hp -= self.damage * 1.35 * dt
                en.hitflash = 0.05

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        sx, sy = int(self.x - cx), int(self.y - cy)
        if not (-200 < sx < W + 200 and -200 < sy < H + 200):
            return
        pulse = int(24 + math.sin(self.angle * 2) * 4)
        glow_circle(s, MYTHIC, (sx, sy), pulse, 4)
        pygame.draw.circle(s, (15, 5, 30), (sx, sy), max(6, pulse - 8))
        pygame.draw.circle(s, PURPLE, (sx, sy), int(self.radius * 0.65), 1)
        for i in range(4):
            a = self.angle + i * (math.tau / 4)
            ox = sx + int(math.cos(a) * 42)
            oy = sy + int(math.sin(a) * 42)
            pygame.draw.circle(s, CYAN, (ox, oy), 4)

class RelicChest:
    """Baú de relíquia largado por Elites e Chefes (inclui Moedas de Ouro)."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.phase = random.random() * math.tau

    def update(self, dt, g):
        self.phase += dt * 4.5
        dist = math.hypot(g.player.x - self.x, g.player.y - self.y)
        if dist < 170:
            nx, ny = vec_norm(g.player.x - self.x, g.player.y - self.y)
            self.x += nx * 160 * dt
            self.y += ny * 160 * dt
        if dist < g.player.r + 18:
            g.player.rerolls += 1
            g.player.hp = min(g.player.maxhp, g.player.hp + g.player.maxhp * 0.25)
            g.player.shield += 20
            coin_reward = int((25 + g.level * 2) * (1.0 + g.player.coin_bonus))
            g.gain_coins(coin_reward)
            g.gain_xp(65 + g.level * 12)
            bonus_type = random.choice(["dano", "crit", "vel", "hp"])
            if bonus_type == "dano":
                g.player.damage *= 1.08
                msg = f"BAÚ: +8% DANO & +{coin_reward} MOEDAS!"
            elif bonus_type == "crit":
                g.player.crit = min(0.85, g.player.crit + 0.04)
                msg = f"BAÚ: +4% CRÍTICO & +{coin_reward} MOEDAS!"
            elif bonus_type == "vel":
                g.player.fire_rate = min(15, g.player.fire_rate * 1.07)
                msg = f"BAÚ: +7% CADÊNCIA & +{coin_reward} MOEDAS!"
            else:
                g.player.maxhp += 15
                g.player.hp = min(g.player.maxhp, g.player.hp + 15)
                msg = f"BAÚ: +15 VIDA MÁX & +{coin_reward} MOEDAS!"
            g.floating_texts.append(FloatingText(self.x, self.y - 18, msg, GOLD, crit=True))
            g.shockwaves.append(Shockwave(self.x, self.y, 110, GOLD, 0.35, 3))
            g.particles.extend(Particle(self.x, self.y, GOLD, size=5) for _ in range(22))
            play_sound("chest")
            return False
        return True

    def draw(self, s, cx, cy):
        sx = int(self.x - cx)
        sy = int(self.y - cy + math.sin(self.phase) * 4)
        if not (-40 < sx < W + 40 and -40 < sy < H + 40):
            return
        glow_circle(s, GOLD, (sx, sy), 12, 3)
        pygame.draw.rect(s, (160, 95, 20), (sx - 12, sy - 9, 24, 18), border_radius=4)
        pygame.draw.rect(s, GOLD, (sx - 12, sy - 9, 24, 18), 2, border_radius=4)
        pygame.draw.line(s, GOLD, (sx - 12, sy), (sx + 12, sy), 2)
        pygame.draw.rect(s, CYAN, (sx - 3, sy - 3, 6, 6), border_radius=1)

PARTICLE_CAPS = (140, 320, 650)
SMOKE_CACHE = {}

def _fade(color, k):
    return (int(color[0] * k), int(color[1] * k), int(color[2] * k))

class Particle:
    """Particula multiuso. kind: 'spark' (faisca alongada), 'smoke', 'ember', 'ring'."""
    def __init__(self, x, y, color, vel=None, life=None, size=None, kind="spark"):
        self.x, self.y = x, y
        a = random.random() * math.tau
        speed = random.uniform(45, 220)
        self.vx, self.vy = vel if vel else (math.cos(a) * speed, math.sin(a) * speed)
        self.color = color
        self.kind = kind
        self.life = life or random.uniform(0.28, 0.65)
        if kind == "smoke" and not life:
            self.life = random.uniform(0.5, 0.9)
        self.maxlife = self.life
        self.size = size or random.uniform(2.2, 5.5)

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.kind == "smoke":
            drag = max(0.0, 1.0 - 1.4 * dt)
            self.vy -= 28 * dt
        elif self.kind == "ember":
            drag = max(0.0, 1.0 - 1.8 * dt)
            self.vy -= 70 * dt
            self.vx += math.sin(self.life * 18 + self.x) * 40 * dt
        elif self.kind == "ring":
            drag = 1.0
        else:
            drag = max(0.0, 1.0 - 2.4 * dt)
        self.vx *= drag
        self.vy *= drag
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        sx, sy = int(self.x - cx), int(self.y - cy)
        if not (-30 < sx < W + 30 and -30 < sy < H + 30):
            return
        prog = self.life / self.maxlife
        if self.kind == "ring":
            r = int(self.size * (1.0 - prog) + 3)
            pygame.draw.circle(s, _fade(self.color, 0.25 + 0.75 * prog), (sx, sy), max(2, r), 2)
            return
        if self.kind == "smoke":
            r = max(2, int(self.size * (1.6 - prog * 0.6)))
            ab = max(1, int(prog * 5))
            key = (r >> 1, ab, self.color)
            spr = SMOKE_CACHE.get(key)
            if spr is None:
                if len(SMOKE_CACHE) > 300:
                    SMOKE_CACHE.clear()
                rr = max(2, (r >> 1) << 1)
                spr = pygame.Surface((rr * 2, rr * 2), pygame.SRCALPHA)
                pygame.draw.circle(spr, (*self.color, ab * 11), (rr, rr), rr)
                SMOKE_CACHE[key] = spr
            s.blit(spr, (sx - spr.get_width() // 2, sy - spr.get_height() // 2))
            return
        r = max(1, int(self.size * prog))
        col = _fade(self.color, 0.30 + 0.70 * prog)
        spd2 = self.vx * self.vx + self.vy * self.vy
        if self.kind == "spark" and spd2 > 900:
            pygame.draw.line(s, col, (sx, sy), (int(sx - self.vx * 0.035), int(sy - self.vy * 0.035)), max(1, r))
        else:
            pygame.draw.circle(s, col, (sx, sy), r)
        if r >= 3:
            pygame.draw.circle(s, WHITE, (sx, sy), max(1, int(r * 0.45)))

class Shard:
    """Estilhaco poligonal que gira: usado na morte dos inimigos."""
    def __init__(self, x, y, color, size):
        a = random.random() * math.tau
        sp = random.uniform(70, 280)
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(a) * sp, math.sin(a) * sp
        self.color = color
        self.life = self.maxlife = random.uniform(0.45, 0.95)
        self.rot = random.random() * math.tau
        self.vr = random.uniform(-10, 10)
        n = random.choice((3, 4, 4))
        base = sorted(random.random() * math.tau for _ in range(n))
        self.pts = [(math.cos(t) * size * random.uniform(0.6, 1.2), math.sin(t) * size * random.uniform(0.6, 1.2)) for t in base]

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        d = max(0.0, 1.0 - 2.1 * dt)
        self.vx *= d
        self.vy *= d
        self.rot += self.vr * dt
        self.life -= dt

    def draw(self, s, cx, cy):
        if self.life <= 0:
            return
        sx, sy = self.x - cx, self.y - cy
        if not (-30 < sx < W + 30 and -30 < sy < H + 30):
            return
        prog = self.life / self.maxlife
        k = 0.45 + 0.55 * prog
        sc_ = 0.45 + 0.55 * prog
        ca, sa = math.cos(self.rot), math.sin(self.rot)
        pts = [(sx + (px * ca - py * sa) * sc_, sy + (px * sa + py * ca) * sc_) for px, py in self.pts]
        pygame.draw.polygon(s, _fade(self.color, k), pts)
        pygame.draw.polygon(s, _fade(WHITE, k * 0.8), pts, 1)

def spawn_death_fx(game, e):
    """Morte com estilhacos da propria cor do inimigo, faiscas, anel e fumaca."""
    q = game.settings.get("quality", 2)
    f = (0.5, 0.8, 1.0)[q]
    boss = e.boss
    n_sh = int((9 if not boss else 38) * f)
    size = e.r * (0.28 if not boss else 0.2)
    for _ in range(max(3, n_sh)):
        game.particles.append(Shard(e.x, e.y, e.color, max(3.0, size) * random.uniform(0.8, 1.3)))
    for _ in range(int((7 if not boss else 30) * f) + 1):
        game.particles.append(Particle(e.x, e.y, mix_color(e.color, WHITE, 0.5), size=random.uniform(2, 4)))
    game.particles.append(Particle(e.x, e.y, mix_color(e.color, WHITE, 0.35), vel=(0, 0), life=0.26, size=e.r * 2.2, kind="ring"))
    if q >= 1:
        for _ in range(2 if not boss else 7):
            game.particles.append(Particle(e.x + random.uniform(-6, 6), e.y + random.uniform(-6, 6), (70, 80, 100), vel=(random.uniform(-30, 30), random.uniform(-30, 10)), size=random.uniform(6, 11), kind="smoke"))

# ----------------------------------------------------------------------------
# ENTIDADES DE JOGO: PROJÉTEIS, ORBES/MOEDAS, JOGADOR E INIMIGOS
# ----------------------------------------------------------------------------
def seg_hit(x0, y0, x1, y1, cx, cy, r):
    """Colisao varrida: o segmento da bala (frame anterior -> atual) toca o circulo?"""
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((cx - x0) * dx + (cy - y0) * dy) / l2))
    qx, qy = x0 + dx * t - cx, y0 + dy * t - cy
    return qx * qx + qy * qy < r * r

class Bullet:
    def __init__(self, x, y, vx, vy, damage, enemy=False, pierce=0, ricochet=0, size=7, homing=False, knockback=0, color=None, owner="p1"):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.damage = damage
        self.enemy = enemy
        self.owner = owner
        self.life = 3.2
        self.pierce = pierce
        self.ricochet = ricochet
        self.size = size
        self.homing = homing
        self.knockback = knockback
        self.hit = set()
        self.color = RED if enemy else (color if color else CYAN)
        self.target = None
        self.retarget = 0.0
        self.px, self.py = x, y

    def update(self, dt, game):
        self.px, self.py = self.x, self.y
        if self.homing and not self.enemy:
            # alvo em cache, reavaliado a cada ~0,15 s via spatial hash (antes: lista nova por bala por frame)
            self.retarget -= dt
            t = self.target
            if self.retarget <= 0 or t is None or not t.alive or t in self.hit:
                self.retarget = 0.12 + random.random() * 0.06
                best, bd = None, 420 ** 2
                for en in game.enemies_near(self.x, self.y, 420):
                    if en.alive and en not in self.hit:
                        d2 = (en.x - self.x) ** 2 + (en.y - self.y) ** 2
                        if d2 < bd:
                            best, bd = en, d2
                self.target = best
            t = self.target
            if t is not None:
                dist_sq = (t.x - self.x) ** 2 + (t.y - self.y) ** 2
                if dist_sq < 420 ** 2:
                    nx, ny = vec_norm(t.x - self.x, t.y - self.y)
                    speed = math.hypot(self.vx, self.vy)
                    self.vx, self.vy = vec_norm(self.vx * 0.90 + nx * speed * 0.10, self.vy * 0.90 + ny * speed * 0.10)
                    self.vx *= speed
                    self.vy *= speed
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt

    def draw(self, s, cx, cy):
        bx, by = self.x - cx, self.y - cy
        if not (-60 < bx < W + 60 and -60 < by < H + 60):
            return
        if self.enemy:
            _draw_enemy_bullet(s, bx, by, self)
            return
        angle = math.atan2(self.vy, self.vx)
        r = self.size
        ca, sa = math.cos(angle), math.sin(angle)
        # soft motion trail (3 segments fading)
        for i, fade in enumerate((0.18, 0.38, 0.62)):
            tx = bx - ca * r * (1.4 + i * 1.1)
            ty = by - sa * r * (1.4 + i * 1.1)
            tr = max(1, int(r * (0.85 - i * 0.18)))
            col = (int(self.color[0] * fade), int(self.color[1] * fade), int(self.color[2] * fade))
            pygame.draw.circle(s, col, (int(tx), int(ty)), tr)
        pts = [
            (bx + ca * r * 2.15, by + sa * r * 2.15),
            (bx + math.cos(angle + 2.35) * r * 1.1, by + math.sin(angle + 2.35) * r * 1.1),
            (bx - ca * r * 0.7, by - sa * r * 0.7),
            (bx + math.cos(angle - 2.35) * r * 1.1, by + math.sin(angle - 2.35) * r * 1.1)
        ]
        dark = (max(0, self.color[0] // 3), max(0, self.color[1] // 3), max(0, self.color[2] // 3))
        pygame.draw.polygon(s, dark, pts)
        # raised mid body for volume
        mid = [
            (bx + ca * r * 1.55, by + sa * r * 1.55),
            (bx + math.cos(angle + 2.1) * r * 0.75, by + math.sin(angle + 2.1) * r * 0.75),
            (bx - ca * r * 0.25, by - sa * r * 0.25),
            (bx + math.cos(angle - 2.1) * r * 0.75, by + math.sin(angle - 2.1) * r * 0.75)
        ]
        pygame.draw.polygon(s, self.color, mid)
        pygame.draw.polygon(s, WHITE, pts, 1)
        # specular tip
        pygame.draw.circle(s, (255, 255, 255), (int(bx + ca * r * 0.55), int(by + sa * r * 0.55)), max(1, r // 3))

class Orb:
    """Pode ser Orbe de XP ('xp'), Orbe de Cura ('heal') ou Moeda de Ouro ('coin')."""
    def __init__(self, x, y, value, kind="xp"):
        self.x, self.y = x, y
        self.value = value
        self.kind = kind
        self.phase = random.random() * 6.28
        self.oid = next(_UID_ORB)

    def update(self, dt, game):
        self.phase += dt * (6.5 if self.kind == "coin" else 4.0)
        dx, dy = game.player.x - self.x, game.player.y - self.y
        dist = math.hypot(dx, dy)
        mag_r = game.player.magnet * (1.25 if self.kind in ("heal", "coin") else 1.0)
        if dist < mag_r:
            nx, ny = vec_norm(dx, dy)
            sp = 280 + max(0, mag_r - dist) * 3.1
            self.x += nx * sp * dt
            self.y += ny * sp * dt
        if dist < game.player.r + 14:
            if self.kind == "heal":
                heal_amt = self.value * (1 + game.player.healing)
                game.player.hp = min(game.player.maxhp, game.player.hp + heal_amt)
                game.floating_texts.append(FloatingText(self.x, self.y, f"+{int(heal_amt)} HP", GREEN))
                game.particles.extend(Particle(self.x, self.y, GREEN) for _ in range(8))
                play_sound("heal")
            elif self.kind == "coin":
                amt = max(1, int(round(self.value * (1.0 + game.player.coin_bonus + getattr(game.player, "syn_coin", 0.0)))))
                game.gain_coins(amt)
                game.floating_texts.append(FloatingText(self.x, self.y, f"+{amt} $", GOLD))
                game.particles.extend(Particle(self.x, self.y, GOLD) for _ in range(7))
                play_sound("coin")
            else:
                game.gain_xp(self.value)
                game.particles.extend(Particle(self.x, self.y, game.get_skin_colors()["bullet"]) for _ in range(5))
                play_sound("xp")
            return False
        return True

    def draw(self, s, cx, cy):
        ox, oy = self.x - cx, self.y - cy + math.sin(self.phase) * 3.5
        if -40 < ox < W + 40 and -40 < oy < H + 40:
            # sombra suave no chão
            draw_soft_shadow(s, ox, oy + 10, 18, 7, 70)
            if self.kind == "heal":
                draw_sphere_3d(s, (ox, oy), 7, GREEN, outline=False, rim=True, glow=True)
            elif self.kind == "coin":
                draw_coin_icon(s, (ox, oy), 8, self.phase)
            else:
                col = GOLD if self.value >= 40 else (40, 165, 255)
                r = 7 if self.value >= 40 else 5
                draw_sphere_3d(s, (ox, oy), r, col, outline=False, rim=True, glow=True)

class Player:
    def __init__(self, perm_upgrades=None):
        up = perm_upgrades or {}
        dmg_lvl = up.get("dmg", 0)
        hp_lvl = up.get("hp", 0)
        spd_lvl = up.get("spd", 0)
        mag_lvl = up.get("mag", 0)
        greed_lvl = up.get("greed", 0)

        self.x = 1200.0
        self.y = 900.0
        self.vx = 0.0
        self.vy = 0.0
        self.r = 15
        self.maxhp = 90 + hp_lvl * 10
        self.hp = self.maxhp
        self.ghost_hp = float(self.maxhp)
        self.damage = 16 * (1.0 + dmg_lvl * 0.05)
        self.fire_rate = 3.1
        self.bullet_speed = 540
        self.move_speed = 248 * (1.0 + spd_lvl * 0.04)
        self.crit = .05
        self.crit_mult = 2.0
        self.shots = 1
        self.pierce = 0
        self.ricochet = 0
        self.armor = 0
        self.shield = 0
        self.shield_regen = 0.0
        self.magnet = 120 + mag_lvl * 25
        self.xp_bonus = 0
        self.orb_bonus = 0
        self.coin_bonus = greed_lvl * 0.15
        self.healing = 0
        self.regen = 0
        self.invuln = 0
        self.invuln_bonus = 0
        self.last_chance = False
        self.dodge = 0
        self.homing = False
        self.explosive = False
        self.aura = False
        self.slowfield = False
        self.repulse = False
        self.lifesteal = False
        self.deathboom = False
        self.eliteshield = False
        self.fury = 0
        self.elite_bonus = 0
        self.boss_bonus = 0
        self.elite_xp = 0
        self.boss_xp = 0
        self.duplicate = 0
        self.killboost = 0
        self.killboost_timer = 0
        self.dash = False
        self.dash_cd = 0
        self.dash_time = 0
        self.dash_vx = 0
        self.dash_vy = 0
        self.overload = False
        self.rain = False
        self.rain_timer = 0
        self.orbitals = 0
        self.orbital_angle = 0.0
        self.chain_lightning = False
        self.burn = False
        self.poison = False
        self.freeze = False
        self.mark = False
        self.catalyst = False
        self.status_chance = 0.0
        self.dot_mult = 1.0
        self.blackhole = False
        self.blackhole_timer = 0.0
        self.meteor_shower = False
        self.active_synergies = set()
        self.synergy_counts = {}
        self.syn_crit = 0.0
        self.syn_xp = 0.0
        self.syn_coin = 0.0
        self.syn_dot = 1.0
        self.syn_poison_cap = 5
        self.syn_freeze = 0.0
        self.syn_chain = 0.0
        self.syn_orbital = 1.0
        self.syn_shield = 1.0
        self.meteor_timer = 0.0
        self.ult_charge = 0.0
        self.ult_rate = 1.0
        self.knockback = 18
        self.bullet_size = 7
        self.last_shot = 0
        self.since_survival = 0
        self.flash = 0
        self.recoil_x = 0.0
        self.recoil_y = 0.0
        self.trail = []
        self.acquired = []
        self.rerolls = 1
        self.downed = False
        self.revive_progress = 0.0
        self.smart_target_pos = None

    def trigger_ultimate(self, game):
        """Ataque Especial [Q]: Mesma função e poder em todas as cores, mas com visual e nome exclusivos da Skin!"""
        if self.ult_charge < 100.0:
            return
        sc = game.get_skin_colors()
        skin_meta = game.get_selected_skin_meta()
        ult_name = skin_meta.get("ult_name", "CATACLISMO SUPREMO")
        ult_style = skin_meta.get("ult_style", "plasma")

        self.ult_charge = 0.0
        self.invuln = max(self.invuln, 1.8)
        game.camera_shake = 1.15
        game.hit_stop = 0.09

        # Limpa todos os projéteis inimigos e de rivais PvP
        game.bullets = [b for b in game.bullets if not b.enemy and b.owner != "p2"]

        # Calcula alvos e aplica exatamente a mesma função de dano em área (raio 480)
        ult_dmg = 160 + self.damage * 4.5 + game.level * 12
        hit_positions = []
        for en in game.enemies:
            if en.alive and math.hypot(en.x - self.x, en.y - self.y) < 480:
                en.hp -= ult_dmg * (0.45 if en.boss else 1.0)
                en.hitflash = 0.25
                hit_positions.append((en.x, en.y))
                if ult_style in ("plasma", "prism", "frost"):
                    game.lightnings.append(LightningBolt(self.x, self.y, en.x, en.y, sc["bullet"]))
                if game.settings["damage_numbers"]:
                    game.floating_texts.append(FloatingText(en.x, en.y - en.r, f"{int(ult_dmg)}!", sc["bullet"], crit=True))
                game.particles.extend(Particle(en.x, en.y, sc["bullet"], size=6) for _ in range(10))

        # No Modo PvP, o Supremo também atinge o Orbe Rival se estiver no raio!
        if game.game_mode == "pvp" and game.partner and game.partner.alive and not game.partner.downed:
            if math.hypot(game.partner.x - self.x, game.partner.y - self.y) < 480:
                pvp_ult_dmg = ult_dmg * 0.32
                game.partner.take_damage(pvp_ult_dmg, game)
                hit_positions.append((game.partner.x, game.partner.y))
                game.lightnings.append(LightningBolt(self.x, self.y, game.partner.x, game.partner.y, sc["bullet"]))
        elif game.game_mode == "coop" and game.partner and game.partner.downed:
            # No Co-op, usar o Supremo perto do aliado caído reanima-o instantaneamente!
            if math.hypot(game.partner.x - self.x, game.partner.y - self.y) < 480:
                game.partner.downed = False
                game.partner.revive_progress = 0.0
                game.partner.hp = game.partner.maxhp * 0.60
                game.floating_texts.append(FloatingText(game.partner.x, game.partner.y - 28, "ALIADO REANIMADO PELO SUPREMO!", GREEN, crit=True))

        # Efeitos visuais personalizados conforme a cor equipada
        game.shockwaves.append(Shockwave(self.x, self.y, 470, sc["bullet"], 0.65, 6))
        game.shockwaves.append(Shockwave(self.x, self.y, 330, sc["body"], 0.50, 4))
        game.ult_visuals.append(UltimateEffectVisual(self.x, self.y, ult_style, sc["bullet"], hit_positions))
        game.floating_texts.append(FloatingText(self.x, self.y - 32, f"{ult_name}!", sc["bullet"], crit=True))
        play_sound("ultimate")

    def take_damage(self, amount, game):
        if self.invuln > 0 or self.dash_time > 0:
            return
        if random.random() < self.dodge:
            game.floating_texts.append(FloatingText(self.x, self.y - 10, "ESQUIVA!", game.get_skin_colors()["bullet"]))
            return
        amount = max(1, amount * (1 - self.armor))
        absorbed = min(self.shield, amount)
        self.shield -= absorbed
        amount -= absorbed
        if amount > 0:
            self.hp -= amount
            game.floating_texts.append(FloatingText(self.x, self.y - 12, f"-{int(amount)}", RED))
        else:
            game.floating_texts.append(FloatingText(self.x, self.y - 12, "ESCUDO!", (90, 210, 255)))
        self.invuln = .72 + self.invuln_bonus
        self.flash = .35
        game.combo = 0
        game.camera_shake = max(game.camera_shake, 0.35)
        game.particles.extend(Particle(self.x, self.y, RED) for _ in range(16))
        play_sound("hit")
        if self.hp <= 0:
            if self.last_chance:
                self.hp = self.maxhp * 0.20
                self.last_chance = False
                self.invuln = 2.5
                game.shockwaves.append(Shockwave(self.x, self.y, 260, GOLD, 0.55, 5))
                game.floating_texts.append(FloatingText(self.x, self.y - 25, "ÚLTIMA CHANCE!", GOLD, crit=True))
                game.slowmo = 0.6
                for en in game.enemies:
                    if en.alive and not en.boss and math.hypot(en.x - self.x, en.y - self.y) < 260:
                        en.hp -= 120
                play_sound("levelup")
            elif game.game_mode == "coop" and game.partner and not game.partner.downed:
                self.hp = 1
                self.downed = True
                self.revive_progress = 0.0
                self.invuln = 1.5
                game.shockwaves.append(Shockwave(self.x, self.y, 140, RED, 0.4, 3))
                game.floating_texts.append(FloatingText(self.x, self.y - 28, "CAÍDO! AGUARDANDO REANIMAÇÃO...", ORANGE, crit=True))
            elif game.game_mode == "pvp":
                game.handle_pvp_round_end(winner="p2")
            else:
                game.record_highscore()
                self.hp = self.maxhp
                game.save_game(game.current_slot)
                game.state = "gameover"

    def apply(self, c):
        e, v = c["effect"], c["value"]
        self.acquired.append(c["name"])
        if e == "max_hp":
            self.maxhp += v
            self.hp += v
        elif e == "regen":
            self.regen += v
        elif e == "heal":
            self.hp = min(self.maxhp, self.hp + self.maxhp * v * (1 + self.healing))
        elif e == "armor":
            self.armor = min(.72, self.armor + v)
        elif e == "shield":
            self.shield += v
        elif e == "shield_regen":
            self.shield_regen += v
        elif e == "lastchance":
            self.last_chance = True
        elif e == "healing":
            self.healing = min(1.5, self.healing + v)
        elif e == "invuln":
            self.invuln_bonus = min(1.2, self.invuln_bonus + v)
        elif e == "damage":
            self.damage *= 1 + v
        elif e == "firerate":
            self.fire_rate = min(14, self.fire_rate * (1 + v))
        elif e == "bulletspeed":
            self.bullet_speed *= 1 + v
        elif e == "multishot":
            self.shots = min(8, self.shots + v)
        elif e == "triple":
            self.shots = min(8, max(self.shots, 3))
        elif e == "pierce":
            self.pierce = min(6, self.pierce + v)
        elif e == "ricochet":
            self.ricochet = min(4, self.ricochet + int(v))
        elif e == "crit":
            self.crit = min(.80, self.crit + v)
        elif e == "critdamage":
            self.crit_mult += v
        elif e == "elite":
            self.elite_bonus += v
        elif e == "bossdamage":
            self.boss_bonus += v
        elif e == "explosive":
            self.explosive = True
        elif e == "homing":
            self.homing = True
        elif e == "rain":
            self.rain = True
        elif e == "speed":
            self.move_speed = min(460, self.move_speed * (1 + v))
        elif e == "dash":
            self.dash = True
        elif e == "dodge":
            self.dodge = min(.45, self.dodge + v)
        elif e == "killboost":
            self.killboost = 1
        elif e == "repulse":
            self.repulse = True
        elif e == "xp":
            self.xp_bonus += v
        elif e == "magnet":
            self.magnet += v
        elif e == "orbxp":
            self.orb_bonus += v
        elif e == "coin_bonus":
            self.coin_bonus += v
        elif e == "elite_xp":
            self.elite_xp += v
            self.rerolls += 1
        elif e == "survivalxp":
            self.since_survival = 0
        elif e == "bossxp":
            self.boss_xp += v
        elif e == "core":
            self.damage *= 1.20
            self.move_speed *= .92
        elif e == "cannon":
            self.damage *= 1.15
            self.bullet_size = 10
            self.knockback = 42
        elif e == "overload":
            self.overload = True
        elif e == "aura":
            self.aura = True
        elif e == "lifesteal":
            self.lifesteal = True
        elif e == "duplicate":
            self.duplicate = min(.85, self.duplicate + v)
        elif e == "slowfield":
            self.slowfield = True
        elif e == "deathboom":
            self.deathboom = True
        elif e == "eliteshield":
            self.eliteshield = True
        elif e == "fury":
            self.fury += v
        elif e == "supreme":
            self.damage *= 1.12
            self.maxhp += 15
            self.hp = min(self.maxhp, self.hp + 15)
            self.rerolls += 1
        elif e == "orbitals":
            self.orbitals = min(4, self.orbitals + 1)
        elif e == "chain_lightning":
            self.chain_lightning = True
        elif e == "ult_charge":
            self.ult_rate += v
        elif e == "blackhole":
            self.blackhole = True
        elif e == "mythic_ascension":
            self.damage *= 1.15
            self.shots = min(10, self.shots + 1)
            self.maxhp += 15
            self.hp = min(self.maxhp, self.hp + 15)
            self.shield += 15
        elif e == "phantom_blades":
            self.pierce = min(8, self.pierce + 1)
            self.ricochet = min(6, self.ricochet + 1)
        elif e == "storm_fury":
            self.fire_rate = min(16, self.fire_rate * 1.18)
            self.move_speed = min(480, self.move_speed * 1.10)
        elif e == "titan_plate":
            self.maxhp += 40
            self.hp += 40
            self.armor = min(0.75, self.armor + 0.08)
            self.shield += 20
        elif e == "meteor_shower":
            self.meteor_shower = True
        elif e == "archangel_grace":
            self.regen += 2.5
            self.shield_regen += 1.5
            self.crit_mult += 0.20
        elif e == "infinite_arsenal":
            self.shots = min(10, self.shots + 2)
            self.fire_rate = min(16, self.fire_rate * 1.20)
        elif e == "supreme_decree":
            self.damage *= 1.28
            self.shots = min(10, self.shots + 1)
            self.maxhp += 30
            self.hp += 30
            self.orbitals = min(6, self.orbitals + 1)
        elif e == "omnipotence":
            self.damage *= 1.25
            self.fire_rate = min(16, self.fire_rate * 1.25)
            self.move_speed = min(480, self.move_speed * 1.15)
            self.crit = min(0.90, self.crit + 0.12)
            self.last_chance = True
        elif e == "burn":
            self.burn = True
        elif e == "poison":
            self.poison = True
        elif e == "freeze":
            self.freeze = True
        elif e == "mark":
            self.mark = True
        elif e == "catalyst":
            self.catalyst = True
            self.status_chance += 0.15
        elif e == "elemental_storm":
            self.status_chance += 0.12
            self.dot_mult = 1.5
        if e in ("max_hp", "supreme", "mythic_ascension", "titan_plate", "supreme_decree", "omnipotence"):
            self.maxhp = min(3000, self.maxhp)
            self.hp = min(self.hp, self.maxhp)
        # Sinergias de tags (3+ cartas)
        self._recompute_synergies()

    def _recompute_synergies(self):
        """Conta tags das cartas adquiridas e ativa bônus com 3+ da mesma tag."""
        counts = {}
        for name in self.acquired:
            for t in CARD_TAGS.get(name, []):
                counts[t] = counts.get(t, 0) + 1
        prev = getattr(self, "active_synergies", set())
        self.active_synergies = {t for t, n in counts.items() if n >= 3}
        self.synergy_counts = counts
        # aplicar modificadores derivados
        self.syn_crit = 0.06 if "Crítico" in self.active_synergies else 0.0
        self.syn_xp = 0.12 if "Economia" in self.active_synergies else 0.0
        self.syn_coin = 0.12 if "Economia" in self.active_synergies else 0.0
        self.syn_dot = 1.25 if "Fogo" in self.active_synergies else 1.0
        self.syn_poison_cap = 6 if "Veneno" in self.active_synergies else 5
        self.syn_freeze = 0.15 if "Gelo" in self.active_synergies else 0.0
        self.syn_chain = 0.10 if "Raio" in self.active_synergies else 0.0
        self.syn_orbital = 1.20 if "Orbital" in self.active_synergies else 1.0
        self.syn_shield = 1.15 if "Escudo" in self.active_synergies else 1.0

    def update(self, dt, game, keys, mouse_down):
        sc = game.get_skin_colors()
        self.invuln = max(0, self.invuln - dt)
        self.flash = max(0, self.flash - dt)
        self.dash_cd = max(0, self.dash_cd - dt)
        self.killboost_timer = max(0, self.killboost_timer - dt)
        self.recoil_x *= max(0.0, 1.0 - 12 * dt)
        self.recoil_y *= max(0.0, 1.0 - 12 * dt)
        self.hp = min(self.maxhp, self.hp + self.regen * dt)
        if self.ghost_hp > self.hp:
            self.ghost_hp = max(self.hp, self.ghost_hp - (self.ghost_hp - self.hp) * 4.5 * dt - 8.0 * dt)
        else:
            self.ghost_hp = float(self.hp)
        if self.shield_regen > 0:
            self.shield = min(self.maxhp * 0.65 * getattr(self, "syn_shield", 1.0), self.shield + self.shield_regen * dt)
        self.ult_charge = min(100.0, self.ult_charge + dt * 1.4 * self.ult_rate)

        self.since_survival += dt
        if self.since_survival >= 45:
            self.since_survival = 0
            if any(c["effect"] == "survivalxp" for c in CARDS if c["name"] in self.acquired):
                game.gain_xp(45 + game.level * 5)
                game.gain_coins(12 + game.level)
                self.hp = min(self.maxhp, self.hp + 15)
                game.floating_texts.append(FloatingText(self.x, self.y - 20, "+BÓNUS SOBREVIVÊNCIA & MOEDAS!", sc["bullet"]))

        if self.blackhole:
            self.blackhole_timer += dt
            if self.blackhole_timer >= 7.0:
                self.blackhole_timer = 0.0
                camx, camy = game.camera()
                mx, my = pygame.mouse.get_pos()
                bx = clamp(mx + camx, 80, game.world_w - 80)
                by = clamp(my + camy, 80, game.world_h - 80)
                game.blackholes.append(BlackHoleEffect(bx, by, self.damage))
                play_sound("dash")

        if self.meteor_shower:
            self.meteor_timer += dt
            if self.meteor_timer >= 7.0:
                self.meteor_timer = 0.0
                targets = [en for en in game.enemies if en.alive]
                random.shuffle(targets)
                for en in targets[:3]:
                    m_dmg = self.damage * 1.8 + game.level * 4
                    en.hp -= m_dmg * (0.5 if en.boss else 1.0)
                    en.hitflash = 0.2
                    game.shockwaves.append(Shockwave(en.x, en.y, 115, ORANGE, 0.38, 4))
                    game.particles.extend(Particle(en.x, en.y, GOLD, size=6) for _ in range(12))
                    if game.settings["damage_numbers"]:
                        game.floating_texts.append(FloatingText(en.x, en.y - en.r, f"☄ {int(m_dmg)}!", ORANGE, crit=True))
                if targets:
                    play_sound("boom")

        if self.rain:
            self.rain_timer += dt
            if self.rain_timer >= 3.5:
                self.rain_timer = 0
                for i in range(14):
                    ang = math.tau * i / 14
                    game.bullets.append(Bullet(
                        self.x, self.y,
                        math.cos(ang) * self.bullet_speed,
                        math.sin(ang) * self.bullet_speed,
                        self.damage * 0.85,
                        pierce=self.pierce, ricochet=self.ricochet,
                        size=7, homing=self.homing, knockback=self.knockback,
                        color=sc["bullet"]
                    ))
                game.shockwaves.append(Shockwave(self.x, self.y, 85, sc["bullet"], 0.25, 2))
                play_sound("shoot")

        if self.orbitals > 0:
            self.orbital_angle = (self.orbital_angle + dt * 3.8) % math.tau
            orb_r = 68
            for i in range(self.orbitals):
                ang = self.orbital_angle + i * (math.tau / self.orbitals)
                ox = self.x + math.cos(ang) * orb_r
                oy = self.y + math.sin(ang) * orb_r
                for en in game.enemies:
                    if en.alive and math.hypot(en.x - ox, en.y - oy) < en.r + 10:
                        en.hp -= self.damage * 1.15 * getattr(self, "syn_orbital", 1.0) * dt
                        en.hitflash = 0.06

        if self.downed:
            self.vx *= max(0.0, 1.0 - 10.0 * dt)
            self.vy *= max(0.0, 1.0 - 10.0 * dt)
            if game.partner and not game.partner.downed:
                d_ally = math.hypot(game.partner.x - self.x, game.partner.y - self.y)
                if d_ally < 110:
                    self.revive_progress += dt / 2.4
                    if self.revive_progress >= 1.0:
                        self.downed = False
                        self.revive_progress = 0.0
                        self.hp = self.maxhp * 0.55
                        self.invuln = 2.2
                        game.shockwaves.append(Shockwave(self.x, self.y, 190, GREEN, 0.45, 4))
                        game.floating_texts.append(FloatingText(self.x, self.y - 26, "REANIMADO PELO PARCEIRO!", GREEN, crit=True))
                        play_sound("heal")
            return

        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        nx, ny = vec_norm(dx, dy)
        if getattr(game, "touch_mode", False) and (abs(game.touch_left_vec[0]) > 0.05 or abs(game.touch_left_vec[1]) > 0.05):
            nx, ny = game.touch_left_vec[0], game.touch_left_vec[1]

        spd = self.move_speed * (1.30 if self.killboost_timer > 0 else 1.0) * getattr(self, "terrain_speed", 1.0)

        if self.dash_time > 0:
            self.dash_time -= dt
            self.x += self.dash_vx * dt
            self.y += self.dash_vy * dt
            if random.random() < 0.8:
                game.particles.append(Particle(self.x, self.y, sc["bullet"], life=0.22, size=5))
        else:
            target_vx = nx * spd
            target_vy = ny * spd
            accel = (14.0 if (nx or ny) else 10.0) * getattr(self, "terrain_accel", 1.0)
            self.vx += (target_vx - self.vx) * min(1.0, accel * dt)
            self.vy += (target_vy - self.vy) * min(1.0, accel * dt)
            self.x += self.vx * dt
            self.y += self.vy * dt

        self.x = clamp(self.x, 26, game.world_w - 26)
        self.y = clamp(self.y, 26, game.world_h - 26)
        self.trail.append((self.x, self.y, .28, self.dash_time > 0))
        self.trail = [(x, y, t - dt, d) for x, y, t, d in self.trail if t > dt]

        right_stick_active = getattr(game, "touch_mode", False) and (abs(game.touch_right_vec[0]) > 0.12 or abs(game.touch_right_vec[1]) > 0.12)
        firing = ((mouse_down and not getattr(game, "touch_ui_captured", False)) or right_stick_active or game.auto_fire) and game.state == "playing"
        self.smart_target_pos = None
        if firing:
            aim_screen_pos = pygame.mouse.get_pos()
            camx, camy = game.camera()
            if right_stick_active:
                aim_screen_pos = (
                    int(self.x - camx + game.touch_right_vec[0] * 260),
                    int(self.y - camy + game.touch_right_vec[1] * 260)
                )
            elif game.auto_fire and game.settings.get("smart_auto_aim", True) and not mouse_down:
                best_t = None
                if game.game_mode == "pvp" and game.partner and game.partner.alive and not game.partner.downed:
                    best_t = (game.partner.x, game.partner.y)
                else:
                    alive_e = [e for e in game.enemies if e.alive and math.hypot(e.x - self.x, e.y - self.y) < 680]
                    if alive_e:
                        target_e = min(alive_e, key=lambda e: (math.hypot(e.x - self.x, e.y - self.y) * (0.65 if e.boss else 1.0)))
                        best_t = (target_e.x, target_e.y)
                if best_t:
                    self.smart_target_pos = best_t
                    aim_screen_pos = (int(best_t[0] - camx), int(best_t[1] - camy))

            is_overload = self.overload and ((game.elapsed % 10.0) < 2.5)
            rate = self.fire_rate * (1.75 if is_overload else 1.0)
            if game.elapsed - self.last_shot >= 1.0 / rate:
                self.last_shot = game.elapsed
                self.shoot(game, aim_screen_pos)

        if self.aura:
            for en in game.enemies:
                if en.alive and math.hypot(en.x - self.x, en.y - self.y) < 105:
                    en.hp -= (18 + game.level * 1.2) * dt

        if self.repulse and int((game.elapsed - dt) / 1.8) != int(game.elapsed / 1.8):
            game.shockwaves.append(Shockwave(self.x, self.y, 135, sc["bullet"], 0.30, 3))
            for en in game.enemies:
                dx2, dy2 = en.x - self.x, en.y - self.y
                dist = math.hypot(dx2, dy2)
                if 0 < dist < 135:
                    nx2, ny2 = vec_norm(dx2, dy2)
                    push = 65 if not en.boss else 20
                    en.x = clamp(en.x + nx2 * push, 30, game.world_w - 30)
                    en.y = clamp(en.y + ny2 * push, 30, game.world_h - 30)

        if self.dash and self.dash_cd <= 0 and keys[pygame.K_SPACE]:
            camx, camy = game.camera()
            aimx, aimy = pygame.mouse.get_pos()
            ax, ay = vec_norm(nx, ny)
            if ax == ay == 0:
                ax, ay = vec_norm((aimx + camx) - self.x, (aimy + camy) - self.y)
            self.dash_time = .16
            self.dash_cd = 2.8
            self.dash_vx = ax * 920
            self.dash_vy = ay * 920
            game.shockwaves.append(Shockwave(self.x, self.y, 48, sc["bullet"], 0.22, 2))
            game.particles.extend(Particle(self.x, self.y, sc["bullet"]) for _ in range(18))
            play_sound("dash")

    def shoot(self, game, mouse):
        sc = game.get_skin_colors()
        camx, camy = game.camera()
        tx, ty = mouse[0] + camx, mouse[1] + camy
        nx, ny = vec_norm(tx - self.x, ty - self.y)
        if nx == ny == 0:
            return
        shots = self.shots
        if random.random() < self.duplicate:
            shots += 1
        spread = .15
        self.recoil_x = -nx * 4.5
        self.recoil_y = -ny * 4.5
        for i in range(shots):
            off = (i - (shots - 1) / 2) * spread
            ang = math.atan2(ny, nx) + off
            d = self.damage
            if self.hp < self.maxhp * .40:
                d *= 1 + self.fury
            game.bullets.append(Bullet(
                self.x, self.y,
                math.cos(ang) * self.bullet_speed,
                math.sin(ang) * self.bullet_speed,
                d,
                pierce=self.pierce, ricochet=self.ricochet,
                size=self.bullet_size, homing=self.homing,
                knockback=self.knockback,
                color=sc["bullet"]
            ))
            game.particles.append(Particle(self.x + nx * 14, self.y + ny * 14, sc["bullet"], life=.14, size=3))
        play_sound("shoot")


STATUS_COL = {"burn": (255, 130, 35), "poison": (110, 255, 90), "freeze": (150, 225, 255), "mark": (255, 230, 90)}
AFFIX_COL = {"Veloz": (255, 240, 90), "Regenerante": (90, 255, 150), "Explosivo": (255, 120, 60), "Gigante": (200, 140, 255)}

class Enemy:
    def __init__(self, x, y, kind, level, boss=False, boss_index=1):
        self.x, self.y = x, y
        self.kind = kind
        self.boss = boss
        self.alive = True
        self.status = {}
        self.affix = None
        self.react_cd = 0.0
        if boss:
            self.name = [
                "O Quadrado Colossal", "O Devorador Carmesim", "O Núcleo Corrompido",
                "O Senhor da Velocidade", "O Colosso Blindado", "O Rei dos Quadrados",
                "O Titã de Magma", "O Arquiteto do Vazio", "O Leviatã Cibernético", "O Imperador Ômega",
                "A Matriarca Prismática", "O Devorador de Estrelas"
            ][(boss_index - 1) % 12]
            self.color = [
                (180, 30, 50), (220, 40, 90), (150, 70, 255),
                (255, 90, 130), (100, 120, 155), (255, 200, 40),
                (255, 95, 20), (120, 35, 210), (0, 215, 220), (255, 45, 95),
                (255, 80, 210), (220, 245, 255)
            ][(boss_index - 1) % 12]
            self.r = 48 + min(20, boss_index * 2)
            # Chefes: HP progressivo 920 * (4 + i*0.85) * (1 + i*0.55) -> 1º ≈ 6.9k, 10º ≈ 100k+
            self.maxhp = 920 * (4.0 + boss_index * 0.85) * (1 + boss_index * 0.55)
            self.hp = self.maxhp
            self.speed = 58 + boss_index * 4
            self.damage = 42 + boss_index * 7
            self.xp = 220 + boss_index * 55
            self.fire_timer = 1.2
            self.phase = 1
            self.attack_timer = 2.0
            self.charge = 0
        else:
            col, hp, sp, dmg, xp, scale = ENEMY_TYPES[kind]
            cycle = max(0, (level - 1) // 10)
            self.color = col
            self.r = 12 if kind not in ("Tanque", "Blindado", "Elite") else 16
            # VERSÃO DIFÍCIL: inimigos mais tanky e letais
            self.maxhp = hp * (1.35 + level * .11) * (1 + cycle * .28)
            self.hp = self.maxhp
            self.speed = sp * (1.08 + level * .018)
            self.damage = dmg * (1.25 + level * .055)
            self.xp = xp * (1 + level * .03)
            if kind == "Elite":
                self.maxhp *= 1.3
                self.hp = self.maxhp
                if level >= 6 and random.random() < 0.85:
                    self.affix = random.choice(("Veloz", "Regenerante", "Explosivo", "Gigante"))
                    if self.affix == "Veloz":
                        self.speed *= 1.45
                    elif self.affix == "Regenerante":
                        pass
                    elif self.affix == "Explosivo":
                        self.damage *= 1.15
                    elif self.affix == "Gigante":
                        self.maxhp *= 1.85
                        self.hp = self.maxhp
                        self.r += 5
                        self.damage *= 1.2
            self.fire_timer = random.uniform(.9, 1.9)
            self.summon_timer = random.uniform(2.5, 4.2)
            self.phase = 1
            self.attack_timer = 2.0
        self.hitflash = 0
        self.uid = next(_UID_ENEMY)
        self.charge = getattr(self, "charge", 0)
        self.spawn_t = 0.0
        self.spawn_total = 0.55
        self.drop_fx = False
        self.bi = boss_index if boss else 0
        self.guard = 0.0
        self.hold = 0.0
        self.pend = None
        self.cur_attack = ""
        self.cur_attack_t = 0.0
        self.chain = 0
        self.last_atk = ""
        self.tx, self.ty = x, y
        self.teleport = 0
        self.telegraph = 0.0
        self.telegraph_x = 0.0
        self.telegraph_y = 0.0
        self.intangible = 0.0
        self.ghost_cd = random.uniform(2.0, 4.0)
        self.bomb_cd = random.uniform(2.5, 4.0)
        self.attached = False
        self.shield_dir = 0.0
        self.reflect_cd = 0.0
        self.zone_cd = random.uniform(1.8, 3.6)
        self.zone_idx = 0
        self.zone_variant = ZONE_VARIANTS[0]
        if not self.boss:
            try:
                z_i = (game.bosses % len(ARENA_BIOMES)) if ("game" in globals() and game is not None) else 0
            except Exception:
                z_i = 0
            self.apply_zone_variant(z_i)

    def apply_zone_variant(self, z_idx):
        self.zone_idx = z_idx % len(ZONE_VARIANTS)
        zv = ZONE_VARIANTS[self.zone_idx]
        self.zone_variant = zv
        self.color = mix_color(self.color, zv["tint"], 0.38)
        ab = zv["ability"]
        if ab == "cyber_pulse":
            self.speed *= 1.10
        elif ab == "cryo_surge":
            self.maxhp *= 1.12
            self.hp = self.maxhp
        elif ab == "holy_cross":
            self.maxhp *= 1.20
            self.hp = self.maxhp

    def status_slow(self, extra_slow=0.0):
        if "freeze" in self.status:
            base = 0.75 if self.boss else 0.45
            return max(0.18, base - float(extra_slow or 0.0))
        return 1.0

    def tick_status(self, dt, g):
        self.react_cd = max(0.0, self.react_cd - dt)
        if self.affix == "Regenerante":
            self.hp = min(self.maxhp, self.hp + self.maxhp * 0.03 * dt)
        st = self.status
        if not st:
            return
        mult = g.player.dot_mult * getattr(g.player, "syn_dot", 1.0)
        for k in list(st):
            st[k][0] -= dt
            if st[k][0] <= 0:
                del st[k]
        if "burn" in st:
            self.hp -= (6 + g.level * 0.9) * mult * dt
            if random.random() < dt * 9:
                g.particles.append(Particle(self.x + random.uniform(-self.r, self.r), self.y, (255, 140, 40), vel=(random.uniform(-15, 15), -60), life=.4, size=3, kind="ember"))
        if "poison" in st:
            self.hp -= st["poison"][1] * (2.5 + g.level * 0.35) * mult * dt
            if random.random() < dt * 5:
                g.particles.append(Particle(self.x + random.uniform(-self.r, self.r), self.y - 4, (110, 255, 90), vel=(0, -35), life=.5, size=4, kind="smoke"))
        if "freeze" in st and random.random() < dt * 4:
            g.particles.append(Particle(self.x + random.uniform(-self.r, self.r), self.y + random.uniform(-self.r, self.r), (170, 235, 255), life=.3, size=3))

    def update(self, dt, g):
        if not self.alive:
            return
        self.hitflash = max(0, self.hitflash - dt)
        if self.spawn_t > 0:
            self.spawn_t -= dt
            if self.spawn_t <= 0 and self.drop_fx:
                self.drop_fx = False
                g.shockwaves.append(Shockwave(self.x, self.y, 80, (255, 90, 60), 0.3, 3))
                g.camera_shake = max(g.camera_shake, 0.12)
            return
        if self.status or self.affix:
            self.tick_status(dt, g)
        p = g.pick_target(self)
        dx, dy = p.x - self.x, p.y - self.y
        dist = math.hypot(dx, dy)
        nx, ny = vec_norm(dx, dy)
        slow = .60 if p.slowfield and dist < 160 else 1.0
        if self.status:
            slow *= self.status_slow(getattr(g.player, "syn_freeze", 0.0))

        if self.boss:
            if self.hp < self.maxhp * .65 and self.phase == 1:
                self.phase = 2
                self.speed *= 1.18
                g.shockwaves.append(Shockwave(self.x, self.y, 190, ORANGE, 0.45, 5))
                g.floating_texts.append(FloatingText(self.x, self.y - self.r, "FASE 2: ENFURECIDO!", ORANGE, crit=True))
            elif self.hp < self.maxhp * .30 and self.phase == 2:
                self.phase = 3
                self.speed *= 1.22
                g.shockwaves.append(Shockwave(self.x, self.y, 260, RED, 0.55, 6))
                g.floating_texts.append(FloatingText(self.x, self.y - self.r, "FASE 3: APOCALIPSE!", RED, crit=True))
            boss_ai(self, dt, g, p, nx, ny, dist, slow)

        elif self.kind in ("Atirador", "Piromante", "Sentinela Laser"):
            if dist > 260:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt
            elif dist < 185:
                self.x -= nx * self.speed * slow * dt
                self.y -= ny * self.speed * slow * dt
            self.fire_timer -= dt
            if self.fire_timer <= 0 and dist < 680:
                if self.kind == "Piromante":
                    self.fire_timer = 1.95
                    base_a = math.atan2(ny, nx)
                    for off_a in (-0.22, 0.0, 0.22):
                        g.bullets.append(Bullet(self.x, self.y, math.cos(base_a + off_a) * 215, math.sin(base_a + off_a) * 215, 9 + self.damage * .32, enemy=True, size=6))
                elif self.kind == "Sentinela Laser":
                    self.fire_timer = 1.45
                    g.bullets.append(Bullet(self.x, self.y, nx * 340, ny * 340, 10 + self.damage * .38, enemy=True, size=5))
                else:
                    self.fire_timer = 1.65
                    g.bullets.append(Bullet(self.x, self.y, nx * 225, ny * 225, 8 + self.damage * .35, enemy=True, size=5))
        elif self.kind == "Berserker":
            rage_mult = 1.65 if self.hp < self.maxhp * 0.5 else 1.0
            self.x += nx * self.speed * rage_mult * slow * dt
            self.y += ny * self.speed * rage_mult * slow * dt
        elif self.kind == "Aracnídeo":
            zig = math.sin(g.elapsed * 11 + self.x * 0.02) * 0.55
            zx, zy = -ny * zig, nx * zig
            self.x += (nx + zx) * self.speed * slow * dt
            self.y += (ny + zy) * self.speed * slow * dt
        elif self.kind == "Anomalia":
            self.x += nx * self.speed * slow * dt
            self.y += ny * self.speed * slow * dt
            self.fire_timer -= dt
            if self.fire_timer <= 0 and dist < 620:
                self.fire_timer = 2.2
                for k in range(4):
                    ang_a = math.atan2(ny, nx) + (k - 1.5) * 0.35
                    g.bullets.append(Bullet(self.x, self.y, math.cos(ang_a) * 210, math.sin(ang_a) * 210, 11 + self.damage * .35, enemy=True, size=6))

        elif self.kind == "Espelho":
            # Mantém distância e reflete projéteis do jogador
            if dist < 220:
                self.x -= nx * self.speed * 1.1 * slow * dt
                self.y -= ny * self.speed * 1.1 * slow * dt
            else:
                self.x += nx * self.speed * 0.7 * slow * dt
                self.y += ny * self.speed * 0.7 * slow * dt
            self.reflect_cd = max(0, self.reflect_cd - dt)
            if self.reflect_cd <= 0:
                for b in g.bullets:
                    if (not b.enemy) and b.life > 0:
                        if math.hypot(b.x - self.x, b.y - self.y) < self.r + b.size + 8:
                            # reflete: vira bala inimiga
                            b.vx, b.vy = -b.vx * 0.9, -b.vy * 0.9
                            b.enemy = True
                            b.color = (200, 220, 255)
                            self.reflect_cd = 0.35
                            g.particles.extend(Particle(self.x, self.y, (200, 220, 255)) for _ in range(6))
                            break

        elif self.kind == "Parasita":
            if not self.attached:
                self.x += nx * self.speed * 1.25 * slow * dt
                self.y += ny * self.speed * 1.25 * slow * dt
                if dist < p.r + self.r + 6:
                    self.attached = True
            else:
                # Gruda e reduz velocidade do jogador
                self.x, self.y = p.x + math.cos(g.elapsed * 4) * 18, p.y + math.sin(g.elapsed * 4) * 18
                p.move_speed = getattr(p, '_parasite_base_speed', p.move_speed)
                if not hasattr(p, '_parasite_slow'):
                    p._parasite_base_speed = p.move_speed
                    p._parasite_slow = True
                    p.move_speed *= 0.72
                self.fire_timer -= dt
                if self.fire_timer <= 0:
                    self.fire_timer = 0.8
                    p.take_damage(max(1, self.damage * 0.35), g)

        elif self.kind == "Vórtice":
            if dist > 180:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt
            # Puxa jogador e projéteis
            if dist < 280 and dist > 1:
                pull = 95 * dt
                p.x -= nx * pull * 0.55
                p.y -= ny * pull * 0.55
            for b in g.bullets:
                if not getattr(b, 'enemy', False):
                    dx, dy = self.x - b.x, self.y - b.y
                    d2 = math.hypot(dx, dy)
                    if 10 < d2 < 220:
                        b.vx += dx / d2 * 420 * dt
                        b.vy += dy / d2 * 420 * dt

        elif self.kind == "Escudeiro":
            self.shield_dir = math.atan2(ny, nx)
            # Aproxima de frente; lado vulnerável atrás
            self.x += nx * self.speed * slow * dt
            self.y += ny * self.speed * slow * dt

        elif self.kind == "Bombardeiro":
            if dist > 260:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt
            self.bomb_cd -= dt
            if self.bomb_cd <= 0:
                if self.telegraph <= 0:
                    self.telegraph = 0.7
                    self.telegraph_x, self.telegraph_y = p.x, p.y
                else:
                    self.telegraph -= dt
                    if self.telegraph <= 0:
                        self.bomb_cd = 3.2
                        # explosão na área marcada
                        if math.hypot(p.x - self.telegraph_x, p.y - self.telegraph_y) < 70:
                            p.take_damage(self.damage * 1.4, g)
                        g.shockwaves.append(Shockwave(self.telegraph_x, self.telegraph_y, 80, ORANGE, 0.35, 3))
                        g.particles.extend(Particle(self.telegraph_x, self.telegraph_y, ORANGE, size=5) for _ in range(14))
                        play_sound("boom")

        elif self.kind == "Fantasma":
            self.ghost_cd -= dt
            if self.ghost_cd <= 0:
                if self.intangible <= 0:
                    self.intangible = 1.4
                    self.ghost_cd = 3.5
                else:
                    pass
            if self.intangible > 0:
                self.intangible -= dt
                # move mais rápido enquanto intangível
                self.x += nx * self.speed * 1.4 * slow * dt
                self.y += ny * self.speed * 1.4 * slow * dt
            else:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt

        elif self.kind == "Invocador":
            if dist > 300:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt
            elif dist < 200:
                self.x -= nx * self.speed * slow * dt
                self.y -= ny * self.speed * slow * dt
            self.summon_timer -= dt
            if self.summon_timer <= 0 and len(g.enemies) < 110:
                self.summon_timer = 4.2
                sx = clamp(self.x + random.uniform(-45, 45), 35, g.world_w - 35)
                sy = clamp(self.y + random.uniform(-45, 45), 35, g.world_h - 35)
                minion = Enemy(sx, sy, "Veloz" if random.random() < 0.4 else "Básico", g.level)
                minion.xp *= 0.4
                g.enemies.append(minion)
                g.shockwaves.append(Shockwave(sx, sy, 32, PURPLE, 0.25, 2))

        elif self.kind == "Teletransportador":
            self.teleport -= dt
            if self.teleport <= 0 and dist < 310:
                self.teleport = 2.8
                g.particles.extend(Particle(self.x, self.y, self.color) for _ in range(8))
                ang = random.random() * math.tau
                self.x = clamp(p.x + math.cos(ang) * 165, 40, g.world_w - 40)
                self.y = clamp(p.y + math.sin(ang) * 165, 40, g.world_h - 40)
                g.shockwaves.append(Shockwave(self.x, self.y, 28, WHITE, 0.20, 2))
            else:
                self.x += nx * self.speed * slow * dt
                self.y += ny * self.speed * slow * dt
        else:
            self.x += nx * self.speed * slow * dt
            self.y += ny * self.speed * slow * dt

        # --- HABILIDADES DE VARIANTE DA ZONA ATUAL (12 ÁREAS DE CHEFES) ---
        if not self.boss:
            zv = getattr(self, "zone_variant", ZONE_VARIANTS[0])
            z_ab = zv["ability"]
            z_tint = zv["tint"]
            self.zone_cd -= dt

            if z_ab == "cyber_pulse":
                # Zona 1 (Nexus Cibernético): Pulso laser extra rápido nos atiradores
                if self.zone_cd <= 0 and dist < 540 and self.kind in ("Atirador", "Sentinela Laser", "Elite"):
                    self.zone_cd = 2.8
                    g.bullets.append(Bullet(self.x, self.y, nx * 360, ny * 360, 8 + self.damage * 0.30, enemy=True, size=5, color=z_tint))

            elif z_ab == "flame_dash":
                # Zona 2 (Inferno Vulcânico): Substitui marcha comum por Investida Vulcânica periódica
                if self.zone_cd <= 0 and 70 < dist < 350:
                    self.zone_cd = 3.2
                    self.x = clamp(self.x + nx * 68, 30, g.world_w - 30)
                    self.y = clamp(self.y + ny * 68, 30, g.world_h - 30)
                    g.particles.extend(Particle(self.x, self.y, ORANGE, size=4, kind="ember") for _ in range(5))

            elif z_ab == "acid_split":
                # Zona 3 (Abismo Tóxico): Regeneração bio-ácida + Tiro Duplo Ácido
                self.hp = min(self.maxhp, self.hp + self.maxhp * 0.02 * dt)
                if self.zone_cd <= 0 and dist < 520 and self.kind in ("Atirador", "Piromante", "Anomalia", "Invocador"):
                    self.zone_cd = 2.6
                    base_a = math.atan2(ny, nx)
                    for off_a in (-0.18, 0.18):
                        g.bullets.append(Bullet(self.x, self.y, math.cos(base_a + off_a) * 240, math.sin(base_a + off_a) * 240, 8 + self.damage * 0.3, enemy=True, size=5, color=z_tint))

            elif z_ab == "cryo_surge":
                # Zona 4 (Tundra Sub-Zero): Patinação Crio-Cinética (+45% vel em surtos)
                if (g.elapsed + self.x * 0.01) % 3.5 < 0.75:
                    self.x += nx * self.speed * 0.45 * dt
                    self.y += ny * self.speed * 0.45 * dt

            elif z_ab == "void_blink":
                # Zona 5 (Dimensão do Vazio): Salto de Fase (Micro-Teleporte dimensional)
                if self.zone_cd <= 0 and 120 < dist < 420:
                    self.zone_cd = 4.0
                    g.particles.extend(Particle(self.x, self.y, PURPLE, size=4) for _ in range(6))
                    ang_v = math.atan2(ny, nx) + random.uniform(-0.55, 0.55)
                    self.x = clamp(self.x + math.cos(ang_v) * 92, 35, g.world_w - 35)
                    self.y = clamp(self.y + math.sin(ang_v) * 92, 35, g.world_h - 35)

            elif z_ab == "holy_cross":
                # Zona 6 (Santuário Celestial): Cura aliados + Feixe Solar em Cruz (4 direções)
                if self.zone_cd <= 0 and dist < 540:
                    self.zone_cd = 3.8
                    for o_en in g.enemies_near(self.x, self.y, 110):
                        if o_en.alive and not o_en.boss:
                            o_en.hp = min(o_en.maxhp, o_en.hp + o_en.maxhp * 0.08)
                    if self.kind in ("Atirador", "Sentinela Laser", "Elite", "Anomalia"):
                        for k_c in range(4):
                            ac = k_c * (math.pi / 2) + 0.78
                            g.bullets.append(Bullet(self.x, self.y, math.cos(ac) * 230, math.sin(ac) * 230, 9 + self.damage * 0.3, enemy=True, size=5, color=GOLD))

            elif z_ab == "wraith_phase":
                # Zona 8 (Cidadela Abissal): Manto Etéreo intangível por 0.7s
                if self.zone_cd <= 0:
                    self.zone_cd = 4.5
                    self.intangible = 0.70
                if self.intangible > 0:
                    self.intangible -= dt
                    self.x += nx * self.speed * 0.30 * dt
                    self.y += ny * self.speed * 0.30 * dt

            elif z_ab == "tidal_wave":
                # Zona 9 (Oceano de Neon): Substitui caminhada reta por Maré Senoidal
                sway = math.sin(g.elapsed * 9.0 + self.y * 0.02) * 0.55
                self.x += (-ny * sway) * self.speed * dt
                self.y += (nx * sway) * self.speed * dt

            elif z_ab == "omega_frenzy":
                # Zona 10 (Trono Ômega): Frenesi Ômega abaixo de 60% HP
                if self.hp < self.maxhp * 0.60:
                    self.x += nx * self.speed * 0.50 * dt
                    self.y += ny * self.speed * 0.50 * dt

            elif z_ab == "prism_refract":
                # Zona 11 (Jardim Prismático): Leque Cromático Triplo
                if self.zone_cd <= 0 and dist < 520 and self.kind in ("Atirador", "Piromante", "Sentinela Laser", "Elite"):
                    self.zone_cd = 3.1
                    base_a = math.atan2(ny, nx)
                    for off_a in (-0.25, 0.0, 0.25):
                        g.bullets.append(Bullet(self.x, self.y, math.cos(base_a + off_a) * 245, math.sin(base_a + off_a) * 245, 9 + self.damage * 0.3, enemy=True, size=5, color=z_tint))

            elif z_ab == "cosmic_homing":
                # Zona 12 (Horizonte de Eventos): Gravidade Estelar + Orbes Perseguidores
                if dist < 185 and dist > 5:
                    p.x -= nx * 38 * dt
                    p.y -= ny * 38 * dt
                if self.zone_cd <= 0 and dist < 560 and self.kind in ("Atirador", "Anomalia", "Elite", "Invocador"):
                    self.zone_cd = 3.4
                    g.bullets.append(Bullet(self.x, self.y, nx * 215, ny * 215, 10 + self.damage * 0.32, enemy=True, size=6, color=WHITE))

        if self.kind == "Regenerador":
            for other in g.enemies:
                if other is not self and other.alive and math.hypot(other.x - self.x, other.y - self.y) < 110:
                    other.hp = min(other.maxhp, other.hp + 6 * dt)

        if dist < self.r + p.r - 1:
            if self.kind == "Explosivo":
                p.take_damage(self.damage * 1.35, g)
                self.hp = 0
            else:
                p.take_damage(self.damage * 0.85, g)

    def draw(self, s, cx, cy):
        x, y = int(self.x - cx), int(self.y - cy)
        if not (-130 < x < W + 130 and -130 < y < H + 130):
            return
        col = self.color
        if self.spawn_t > 0:
            k_sp = clamp(self.spawn_t / max(0.1, self.spawn_total), 0.0, 1.0)
            if self.drop_fx:
                # sombra de impacto no chão + inimigo "caindo" do alto
                gr = int(self.r * (1.7 + 1.3 * k_sp))
                draw_soft_shadow(s, x, y + 4, gr * 2, max(8, gr), int(70 + 90 * (1 - k_sp)))
                _alpha_disc(s, (255, 70, 50), (x, y), gr, int(35 + 55 * (1 - k_sp)))
                pygame.draw.circle(s, (255, 90, 60), (x, y), gr, 2)
                pygame.draw.circle(s, _fade(col, 0.5 + 0.4 * (1 - k_sp)), (x, y - int(k_sp * 150)), self.r, 2)
            pygame.draw.circle(s, _fade(col, 0.4 + 0.5 * (1 - k_sp)), (x, y), int(self.r * (1.0 + 1.6 * k_sp)), 2)
            pygame.draw.circle(s, _fade(col, 0.8), (x, y), max(2, int(self.r * (1 - k_sp) * 0.6)))
            return
        # Telegraph do Bombardeiro (área vermelha avisando)
        if self.kind == "Bombardeiro" and self.telegraph > 0:
            tx, ty = int(self.telegraph_x - cx), int(self.telegraph_y - cy)
            alpha_pulse = int(80 + 80 * abs(math.sin(self.telegraph * 12)))
            rad = 70
            _alpha_disc(s, (255, 40, 40), (tx, ty), rad, alpha_pulse // 3)
            pygame.draw.circle(s, (255, 40, 40), (tx, ty), rad, 2)
            pygame.draw.circle(s, (255, 80, 40), (tx, ty), int(rad * (1.0 - self.telegraph / 0.7)), 1)
        # Fantasma intangível: contorno tracejado claro
        if self.kind == "Fantasma" and self.intangible > 0:
            col = (min(255, col[0] + 60), min(255, col[1] + 60), min(255, col[2] + 80))
        # Escudeiro: arco de escudo frontal
        if self.kind == "Escudeiro":
            sh_r = self.r + 10
            for a in (-0.9, -0.45, 0, 0.45, 0.9):
                ang = self.shield_dir + a
                pygame.draw.circle(s, (160, 180, 210), (x + int(math.cos(ang) * sh_r), y + int(math.sin(ang) * sh_r)), 4)

        time_s = pygame.time.get_ticks() / 1000.0
        is_moving = self.speed > 0
        bob = math.sin(time_s * 18 + self.x * 0.01) * 2.5 if is_moving else 0
        leg_swing = math.sin(time_s * 18 + self.x * 0.01) * 5 if is_moving else 0
        y_anim = y + int(bob)
        outline_col = (10, 15, 30)
        sh_w = int(self.r * 2.2)
        sh_h = max(6, int(self.r * 0.6))
        draw_soft_shadow(s, x, y + self.r + 4, sh_w, sh_h, 95)

        if self.boss:
            r = self.r
            pygame.draw.rect(s, (col[0] // 3, col[1] // 3, col[2] // 3), (x - r - 6, y_anim - r - 6, (r + 6) * 2, (r + 6) * 2), border_radius=10)

            if self.name == "O Rei dos Quadrados":
                pygame.draw.polygon(s, (180, 20, 30), [(x - r - 20, y_anim + r), (x - r + 10, y_anim - r + 10), (x + r - 10, y_anim - r + 10), (x + r + 20, y_anim + r)])
                pygame.draw.polygon(s, WHITE, [(x - r - 25, y_anim + r), (x - r - 20, y_anim + r - 10), (x + r + 20, y_anim + r - 10), (x + r + 25, y_anim + r)])
            elif self.name == "O Senhor da Velocidade":
                jet_y = y_anim + math.sin(time_s * 20) * 5
                pygame.draw.polygon(s, (255, 50, 50), [(x - r - 10, jet_y - 10), (x - r - 40, jet_y), (x - r - 10, jet_y + 10)])
                pygame.draw.polygon(s, (255, 150, 0), [(x - r - 10, jet_y + 20), (x - r - 35, jet_y + 30), (x - r - 10, jet_y + 40)])
                pygame.draw.rect(s, (80, 80, 80), (x - r - 15, y_anim - 20, 15, 25), border_radius=4)
                pygame.draw.rect(s, (80, 80, 80), (x - r - 15, y_anim + 10, 15, 25), border_radius=4)
                pygame.draw.rect(s, outline_col, (x - r - 15, y_anim - 20, 15, 25), 2, border_radius=4)
                pygame.draw.rect(s, outline_col, (x - r - 15, y_anim + 10, 15, 25), 2, border_radius=4)

            if self.name == "O Quadrado Colossal":
                pygame.draw.rect(s, col, (x - r // 2 - 15, y_anim + r - 10, 20, 35), border_radius=5)
                pygame.draw.rect(s, outline_col, (x - r // 2 - 15, y_anim + r - 10, 20, 35), 3, border_radius=5)
                pygame.draw.rect(s, col, (x + r // 2 - 5, y_anim + r - 10, 20, 35), border_radius=5)
                pygame.draw.rect(s, outline_col, (x + r // 2 - 5, y_anim + r - 10, 20, 35), 3, border_radius=5)
                pygame.draw.circle(s, col, (x - r - 15, y_anim - 5), 20)
                pygame.draw.circle(s, outline_col, (x - r - 15, y_anim - 5), 20, 3)
                pygame.draw.circle(s, col, (x - r - 25, y_anim + 20), 16)
                pygame.draw.circle(s, outline_col, (x - r - 25, y_anim + 20), 16, 3)
                pygame.draw.circle(s, col, (x + r + 15, y_anim - 5), 20)
                pygame.draw.circle(s, outline_col, (x + r + 15, y_anim - 5), 20, 3)
                pygame.draw.circle(s, col, (x + r + 25, y_anim + 20), 16)
                pygame.draw.circle(s, outline_col, (x + r + 25, y_anim + 20), 16, 3)
            elif self.name == "O Devorador Carmesim":
                pygame.draw.line(s, outline_col, (x - r // 2 + 10, y_anim + r), (x - r // 2 - leg_swing * 2, y_anim + r + 25), 6)
                pygame.draw.line(s, outline_col, (x + r // 2 - 10, y_anim + r), (x + r // 2 + leg_swing * 2, y_anim + r + 25), 6)
                pygame.draw.rect(s, (180, 0, 0), (x - r // 2 - leg_swing * 2 - 10, y_anim + r + 20, 16, 10))
                pygame.draw.rect(s, (180, 0, 0), (x + r // 2 + leg_swing * 2 - 6, y_anim + r + 20, 16, 10))
                pygame.draw.line(s, outline_col, (x - r, y_anim + 15), (x - r - 25, y_anim + 35 - bob * 2), 6)
                pygame.draw.line(s, outline_col, (x + r, y_anim + 15), (x + r + 25, y_anim + 35 - bob * 2), 6)
            elif self.name == "O Colosso Blindado":
                pygame.draw.rect(s, (70, 80, 90), (x - r // 2 - 10, y_anim + r, 16, 25))
                pygame.draw.rect(s, outline_col, (x - r // 2 - 10, y_anim + r, 16, 25), 3)
                pygame.draw.rect(s, (70, 80, 90), (x + r // 2 - 6, y_anim + r, 16, 25))
                pygame.draw.rect(s, outline_col, (x + r // 2 - 6, y_anim + r, 16, 25), 3)
                pygame.draw.circle(s, (80, 90, 100), (x - r - 10, y_anim + 10), 14)
                pygame.draw.circle(s, outline_col, (x - r - 10, y_anim + 10), 14, 3)
                pygame.draw.circle(s, (60, 70, 80), (x - r - 25, y_anim + 25), 16)
                pygame.draw.circle(s, outline_col, (x - r - 25, y_anim + 25), 16, 3)
            elif self.name in ["O Senhor da Velocidade", "O Rei dos Quadrados"]:
                pygame.draw.line(s, outline_col, (x - 15, y_anim + r), (x - 15 - leg_swing * 1.5, y_anim + r + 20), 6)
                pygame.draw.line(s, outline_col, (x + 15, y_anim + r), (x + 15 + leg_swing * 1.5, y_anim + r + 20), 6)
                shoe_c = (255, 80, 120) if self.name == "O Senhor da Velocidade" else (220, 160, 0)
                pygame.draw.rect(s, shoe_c, (x - 22 - leg_swing * 1.5, y_anim + r + 15, 14, 8))
                pygame.draw.rect(s, shoe_c, (x + 8 + leg_swing * 1.5, y_anim + r + 15, 14, 8))
                if self.name != "O Rei dos Quadrados":
                    pygame.draw.line(s, outline_col, (x - r, y_anim + 5), (x - r - 20, y_anim + 20 - bob), 6)
                    pygame.draw.line(s, outline_col, (x + r, y_anim + 5), (x + r + 20, y_anim + 20 - bob), 6)

            pygame.draw.rect(s, col, (x - r, y_anim - r, r * 2, r * 2), border_radius=6)
            pygame.draw.rect(s, outline_col, (x - r, y_anim - r, r * 2, r * 2), 4, border_radius=6)

            if self.name == "O Quadrado Colossal":
                pygame.draw.line(s, outline_col, (x + r - 20, y_anim - r), (x + r - 5, y_anim - r + 15), 3)
                pygame.draw.line(s, outline_col, (x + r - 5, y_anim - r + 15), (x + r, y_anim - r + 25), 3)
                eye_y = y_anim - 15
                pygame.draw.polygon(s, outline_col, [(x - 35, eye_y - 5), (x + 35, eye_y - 5), (x, eye_y + 8)])
                pygame.draw.circle(s, outline_col, (x - 18, eye_y + 12), 7)
                pygame.draw.circle(s, WHITE, (x - 18, eye_y + 12), 3)
                pygame.draw.circle(s, outline_col, (x + 18, eye_y + 12), 7)
                pygame.draw.circle(s, WHITE, (x + 18, eye_y + 12), 3)
                pygame.draw.line(s, outline_col, (x - 20, y_anim + 20), (x + 20, y_anim + 20), 4)

            elif self.name == "O Devorador Carmesim":
                eye_y = y_anim - 30
                pygame.draw.line(s, outline_col, (x - 25, eye_y - 12), (x - 8, eye_y), 5)
                pygame.draw.line(s, outline_col, (x + 25, eye_y - 12), (x + 8, eye_y), 5)
                pygame.draw.circle(s, WHITE, (x - 15, eye_y + 8), 6)
                pygame.draw.circle(s, outline_col, (x - 15, eye_y + 8), 3)
                pygame.draw.circle(s, WHITE, (x + 15, eye_y + 8), 6)
                pygame.draw.circle(s, outline_col, (x + 15, eye_y + 8), 3)
                mouth_rect = pygame.Rect(x - 35, y_anim - 5, 70, 50)
                pygame.draw.ellipse(s, outline_col, mouth_rect)
                for i in range(6):
                    tx = x - 28 + i * 10
                    pygame.draw.polygon(s, (255, 240, 220), [(tx, y_anim - 2), (tx + 10, y_anim - 2), (tx + 5, y_anim + 12)])
                    pygame.draw.polygon(s, (255, 240, 220), [(tx, y_anim + 42), (tx + 10, y_anim + 42), (tx + 5, y_anim + 28)])

            elif self.name == "O Núcleo Corrompido":
                pygame.draw.rect(s, (120, 50, 200), (x - r // 2, y_anim - r // 2, r, r), border_radius=4)
                eye_y = y_anim
                pygame.draw.circle(s, outline_col, (x, eye_y), 26)
                pygame.draw.circle(s, (255, 120, 255), (x, eye_y), 22)
                pygame.draw.circle(s, outline_col, (x, eye_y), 10)
                pygame.draw.circle(s, WHITE, (x - 4, eye_y - 4), 3)
                for i in range(8):
                    ang = time_s * 2 + i * (math.tau / 8)
                    rx = x + math.cos(ang) * (r + 18)
                    ry = y_anim + math.sin(ang) * (r + 18)
                    pygame.draw.polygon(s, col, [(rx, ry - 10), (rx - 10, ry), (rx, ry + 10), (rx + 10, ry)])
                    pygame.draw.polygon(s, outline_col, [(rx, ry - 10), (rx - 10, ry), (rx, ry + 10), (rx + 10, ry)], 3)

            elif self.name == "O Senhor da Velocidade":
                pygame.draw.rect(s, outline_col, (x - 30, y_anim - 10, 25, 14), border_radius=3)
                pygame.draw.rect(s, outline_col, (x + 5, y_anim - 10, 25, 14), border_radius=3)
                pygame.draw.line(s, outline_col, (x - 5, y_anim - 3), (x + 5, y_anim - 3), 4)
                pygame.draw.line(s, WHITE, (x - 25, y_anim - 6), (x - 12, y_anim - 6), 2)
                pygame.draw.line(s, WHITE, (x + 10, y_anim - 6), (x + 23, y_anim - 6), 2)
                pygame.draw.line(s, outline_col, (x - 8, y_anim + 15), (x + 15, y_anim + 15), 3)

            elif self.name == "O Colosso Blindado":
                for i in range(4):
                    sx = x - 25 + i * 16
                    pygame.draw.polygon(s, (200, 200, 200), [(sx - 6, y_anim - r), (sx + 6, y_anim - r), (sx, y_anim - r - 12)])
                    pygame.draw.polygon(s, outline_col, [(sx - 6, y_anim - r), (sx + 6, y_anim - r), (sx, y_anim - r - 12)], 2)
                for ix in [-20, 0, 20]:
                    for iy in [-20, 0, 20]:
                        pygame.draw.circle(s, (50, 60, 70), (x + ix, y_anim + iy), 4)
                pygame.draw.line(s, outline_col, (x - 20, y_anim - 5), (x - 5, y_anim + 2), 5)
                pygame.draw.line(s, outline_col, (x + 20, y_anim - 5), (x + 5, y_anim + 2), 5)
                pygame.draw.line(s, outline_col, (x - 12, y_anim + 20), (x + 12, y_anim + 20), 4)
                pygame.draw.rect(s, (90, 100, 110), (x + r - 5, y_anim - 30, 25, 80), border_radius=5)
                pygame.draw.rect(s, outline_col, (x + r - 5, y_anim - 30, 25, 80), 4, border_radius=5)
                pygame.draw.rect(s, outline_col, (x + r + 2, y_anim - 15, 10, 50), 2)

            elif self.name == "O Rei dos Quadrados":
                pygame.draw.polygon(s, (255, 220, 50), [(x - r + 5, y_anim - r), (x - r, y_anim - r - 35), (x - r // 2, y_anim - r - 15), (x, y_anim - r - 40), (x + r // 2, y_anim - r - 15), (x + r, y_anim - r - 35), (x + r - 5, y_anim - r)])
                pygame.draw.polygon(s, outline_col, [(x - r + 5, y_anim - r), (x - r, y_anim - r - 35), (x - r // 2, y_anim - r - 15), (x, y_anim - r - 40), (x + r // 2, y_anim - r - 15), (x + r, y_anim - r - 35), (x + r - 5, y_anim - r)], 3)
                pygame.draw.circle(s, RED, (x, y_anim - r - 20), 6)
                pygame.draw.line(s, outline_col, (x - 20, y_anim - 5), (x - 8, y_anim - 5), 5)
                pygame.draw.line(s, outline_col, (x + 8, y_anim - 5), (x + 20, y_anim - 5), 5)
                pygame.draw.line(s, outline_col, (x - 15, y_anim + 15), (x + 15, y_anim + 15), 4)
                pygame.draw.line(s, outline_col, (x - r, y_anim + 10), (x - r - 15, y_anim + 25 - bob), 6)
                pygame.draw.line(s, outline_col, (x + r, y_anim + 10), (x + r + 15, y_anim + 25 - bob), 6)
                pygame.draw.line(s, (150, 100, 20), (x + r + 20, y_anim - 40), (x + r + 10, y_anim + 40), 6)
                pygame.draw.circle(s, GOLD, (x + r + 22, y_anim - 42), 14)
                pygame.draw.circle(s, outline_col, (x + r + 22, y_anim - 42), 14, 3)
            elif self.name in ("O Titã de Magma", "O Arquiteto do Vazio", "O Leviatã Cibernético", "O Imperador Ômega", "A Matriarca Prismática", "O Devorador de Estrelas"):
                orb_count = 8 if self.name in ("A Matriarca Prismática", "O Devorador de Estrelas") else 6
                for i in range(orb_count):
                    ang = time_s * 2.8 + i * (math.tau / orb_count)
                    ox = x + int(math.cos(ang) * (r + 18))
                    oy = y_anim + int(math.sin(ang) * (r + 18))
                    orb_c = CYAN if (self.name == "A Matriarca Prismática" and i % 2 == 0) else (GOLD if self.name == "O Devorador de Estrelas" else col)
                    glow_circle(s, orb_c, (ox, oy), 8, 2)
                if self.name == "A Matriarca Prismática":
                    for sx in (-1, 1):
                        wing_pts = [(x + sx * r, y_anim - 10), (x + sx * (r + 34), y_anim - 32), (x + sx * (r + 26), y_anim + 18), (x + sx * r, y_anim + 12)]
                        pygame.draw.polygon(s, (255, 130, 235), wing_pts)
                        pygame.draw.polygon(s, WHITE, wing_pts, 2)
                elif self.name == "O Devorador de Estrelas":
                    pygame.draw.circle(s, (30, 10, 55), (x, y_anim), r - 8)
                    pygame.draw.circle(s, CYAN, (x, y_anim), r - 8, 2)
                pygame.draw.polygon(s, GOLD, [(x - 26, y_anim - r), (x - 14, y_anim - r - 24), (x, y_anim - r - 8), (x + 14, y_anim - r - 24), (x + 26, y_anim - r)])
                pygame.draw.circle(s, WHITE, (x - 16, y_anim - 8), 8)
                pygame.draw.circle(s, outline_col, (x - 16, y_anim - 8), 4)
                pygame.draw.circle(s, WHITE, (x + 16, y_anim - 8), 8)
                pygame.draw.circle(s, outline_col, (x + 16, y_anim - 8), 4)
                pygame.draw.rect(s, outline_col, (x - 22, y_anim + 12, 44, 12), border_radius=4)
            if self.phase >= 2:
                aura_col = RED if self.phase == 3 else ORANGE
                pygame.draw.circle(s, aura_col, (x, y_anim), r + 8 + int(math.sin(time_s * 10) * 4), 2)
        else:
            r = self.r
            if self.kind != "Teletransportador":
                if self.kind == "Tanque":
                    pygame.draw.circle(s, col, (x - r - 6, y_anim), 8)
                    pygame.draw.circle(s, col, (x + r + 6, y_anim), 8)
                    pygame.draw.circle(s, outline_col, (x - r - 6, y_anim), 8, 2)
                    pygame.draw.circle(s, outline_col, (x + r + 6, y_anim), 8, 2)
                else:
                    pygame.draw.line(s, outline_col, (x - r + 2, y_anim), (x - r - 8, y_anim + 6), 3)
                    pygame.draw.circle(s, outline_col, (x - r - 8, y_anim + 6), 3)
                    pygame.draw.line(s, outline_col, (x + r - 2, y_anim), (x + r + 8, y_anim + 6), 3)
                    pygame.draw.circle(s, outline_col, (x + r + 8, y_anim + 6), 3)

                pygame.draw.line(s, outline_col, (x - 4, y_anim + r - 2), (x - 4 - leg_swing * .8, y_anim + r + 8), 3)
                pygame.draw.line(s, outline_col, (x + 4, y_anim + r - 2), (x + 4 + leg_swing * .8, y_anim + r + 8), 3)
                shoe_c = col
                pygame.draw.rect(s, outline_col, (x - 8 - leg_swing * .8, y_anim + r + 6, 8, 5), border_radius=1)
                pygame.draw.rect(s, shoe_c, (x - 7 - leg_swing * .8, y_anim + r + 7, 6, 3), border_radius=1)
                pygame.draw.rect(s, outline_col, (x + 0 + leg_swing * .8, y_anim + r + 6, 8, 5), border_radius=1)
                pygame.draw.rect(s, shoe_c, (x + 1 + leg_swing * .8, y_anim + r + 7, 6, 3), border_radius=1)

            if self.kind == "Veloz":
                pygame.draw.polygon(s, RED, [(x - r, y_anim - r + 4), (x - r - 12, y_anim - r), (x - r - 8, y_anim - r + 6)])
                pygame.draw.polygon(s, RED, [(x - r, y_anim - r + 8), (x - r - 14, y_anim - r + 10), (x - r - 8, y_anim - r + 12)])

            if self.kind == "Teletransportador":
                body_surf = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                pygame.draw.rect(body_surf, (col[0], col[1], col[2], 180), (2, 2, r * 2, r * 2), border_radius=3)
                s.blit(body_surf, (x - r - 2, y_anim - r - 2))
            else:
                pygame.draw.rect(s, (col[0] // 4, col[1] // 4, col[2] // 4), (x - r - 2, y_anim - r - 2, r * 2 + 4, r * 2 + 4), border_radius=3)
                pygame.draw.rect(s, col, (x - r, y_anim - r, r * 2, r * 2), border_radius=2)

            if self.kind in ("Elite", "Blindado"):
                pygame.draw.rect(s, outline_col, (x - r, y_anim - r, r * 2, r * 2), 2, border_radius=2)

            if self.kind == "Básico":
                pygame.draw.line(s, outline_col, (x - 8, y_anim - 6), (x - 2, y_anim - 3), 2)
                pygame.draw.line(s, outline_col, (x + 8, y_anim - 6), (x + 2, y_anim - 3), 2)
                pygame.draw.rect(s, outline_col, (x - 6, y_anim - 3, 2, 3))
                pygame.draw.rect(s, outline_col, (x + 4, y_anim - 3, 2, 3))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 4), (x + 3, y_anim + 4), 2)

            elif self.kind == "Veloz":
                pygame.draw.rect(s, RED, (x - r, y_anim - r + 3, r * 2, 6))
                pygame.draw.rect(s, outline_col, (x - 6, y_anim, 3, 4))
                pygame.draw.rect(s, outline_col, (x + 3, y_anim, 3, 4))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 6), (x + 3, y_anim + 6), 2)

            elif self.kind == "Tanque":
                pygame.draw.rect(s, outline_col, (x - 7, y_anim - 6, 5, 2))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim - 6, 5, 2))
                pygame.draw.rect(s, outline_col, (x - 5, y_anim - 4, 3, 3))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim - 4, 3, 3))
                pygame.draw.line(s, outline_col, (x - 4, y_anim + 5), (x + 4, y_anim + 5), 2)

            elif self.kind == "Atirador":
                pygame.draw.rect(s, outline_col, (x - 10, y_anim - 6, 20, 8))
                pygame.draw.rect(s, WHITE, (x - 8, y_anim - 4, 4, 2))
                pygame.draw.rect(s, WHITE, (x + 2, y_anim - 4, 4, 2))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 5), (x + 3, y_anim + 5), 2)
                pygame.draw.rect(s, (60, 60, 60), (x - 16, y_anim + 2, 10, 6), border_radius=1)

            elif self.kind == "Regenerador":
                pygame.draw.line(s, outline_col, (x - 6, y_anim - 2), (x - 2, y_anim - 2), 2)
                pygame.draw.line(s, outline_col, (x + 6, y_anim - 2), (x + 2, y_anim - 2), 2)
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 5), (x + 3, y_anim + 5), 2)
                leaf_ang = time_s * 3
                lx1, ly1 = x + math.cos(leaf_ang) * 22, y_anim + math.sin(leaf_ang) * 22
                lx2, ly2 = x + math.cos(leaf_ang + math.pi) * 22, y_anim + math.sin(leaf_ang + math.pi) * 22
                pygame.draw.polygon(s, GREEN, [(lx1, ly1 - 4), (lx1 - 4, ly1), (lx1, ly1 + 4), (lx1 + 4, ly1)])
                pygame.draw.polygon(s, outline_col, [(lx1, ly1 - 4), (lx1 - 4, ly1), (lx1, ly1 + 4), (lx1 + 4, ly1)], 1)
                pygame.draw.polygon(s, GREEN, [(lx2, ly2 - 4), (lx2 - 4, ly2), (lx2, ly2 + 4), (lx2 + 4, ly2)])
                pygame.draw.polygon(s, outline_col, [(lx2, ly2 - 4), (lx2 - 4, ly2), (lx2, ly2 + 4), (lx2 + 4, ly2)], 1)

            elif self.kind == "Explosivo":
                pygame.draw.line(s, outline_col, (x, y_anim - r), (x, y_anim - r - 8), 2)
                spark_y = y_anim - r - 8 + math.sin(time_s * 30) * 2
                pygame.draw.circle(s, (255, 150, 0), (x, int(spark_y)), 4)
                pygame.draw.circle(s, (255, 255, 0), (x, int(spark_y)), 2)
                pygame.draw.circle(s, WHITE, (x - 4, y_anim - 2), 4)
                pygame.draw.circle(s, WHITE, (x + 5, y_anim - 2), 5)
                pygame.draw.circle(s, outline_col, (x - 4, y_anim - 2), 1)
                pygame.draw.circle(s, outline_col, (x + 5, y_anim - 3), 1)
                pygame.draw.polygon(s, outline_col, [(x - 6, y_anim + 4), (x + 6, y_anim + 4), (x, y_anim + 10)])
                pygame.draw.polygon(s, WHITE, [(x - 4, y_anim + 4), (x + 4, y_anim + 4), (x, y_anim + 8)])

            elif self.kind == "Teletransportador":
                pygame.draw.rect(s, (150, 180, 255), (x - 7, y_anim - 2, 4, 3), 1)
                pygame.draw.rect(s, (150, 180, 255), (x + 3, y_anim - 2, 4, 3), 1)
                if random.random() < 0.2:
                    game.particles.append(Particle(self.x + random.randint(-r, r), self.y + random.randint(0, r), WHITE, (0, -20), 0.5, 2))

            elif self.kind == "Blindado":
                pygame.draw.polygon(s, (150, 150, 150), [(x - 6, y_anim - r), (x - 3, y_anim - r - 5), (x, y_anim - r)])
                pygame.draw.polygon(s, (150, 150, 150), [(x, y_anim - r), (x + 3, y_anim - r - 5), (x + 6, y_anim - r)])
                pygame.draw.circle(s, (100, 100, 100), (x - r + 4, y_anim - r + 4), 1)
                pygame.draw.circle(s, (100, 100, 100), (x + r - 4, y_anim - r + 4), 1)
                pygame.draw.circle(s, (100, 100, 100), (x - r + 4, y_anim + r - 4), 1)
                pygame.draw.circle(s, (100, 100, 100), (x + r - 4, y_anim + r - 4), 1)
                pygame.draw.rect(s, (120, 120, 130), (x + 10, y_anim - 4, 6, 16), border_radius=2)
                pygame.draw.rect(s, outline_col, (x + 10, y_anim - 4, 6, 16), 1, border_radius=2)
                pygame.draw.rect(s, outline_col, (x - 5, y_anim - 2, 2, 2))
                pygame.draw.rect(s, outline_col, (x + 3, y_anim - 2, 2, 2))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 5), (x + 3, y_anim + 5), 2)

            elif self.kind == "Invocador":
                pygame.draw.line(s, outline_col, (x - 6, y_anim - 2), (x - 2, y_anim), 2)
                pygame.draw.line(s, outline_col, (x + 6, y_anim - 2), (x + 2, y_anim), 2)
                pygame.draw.rect(s, outline_col, (x - 5, y_anim, 2, 2))
                pygame.draw.rect(s, outline_col, (x + 3, y_anim, 2, 2))
                pygame.draw.line(s, (100, 50, 30), (x + 14, y_anim + 10), (x + 18, y_anim - 10), 3)
                pygame.draw.circle(s, (255, 100, 255), (x + 18, y_anim - 12), 4)
                pygame.draw.circle(s, outline_col, (x + 18, y_anim - 12), 4, 1)
                pygame.draw.line(s, outline_col, (x, y_anim + 4), (x + 3, y_anim + 2), 2)

            elif self.kind == "Elite":
                pygame.draw.polygon(s, (255, 200, 0), [(x - 10, y_anim - r), (x - 12, y_anim - r - 10), (x - 4, y_anim - r - 4), (x, y_anim - r - 12), (x + 4, y_anim - r - 4), (x + 12, y_anim - r - 10), (x + 10, y_anim - r)])
                pygame.draw.polygon(s, outline_col, [(x - 10, y_anim - r), (x - 12, y_anim - r - 10), (x - 4, y_anim - r - 4), (x, y_anim - r - 12), (x + 4, y_anim - r - 4), (x + 12, y_anim - r - 10), (x + 10, y_anim - r)], 1)
                pygame.draw.circle(s, RED, (x, y_anim - r - 6), 2)
                pygame.draw.rect(s, outline_col, (x - 6, y_anim - 2, 4, 2))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim - 2, 4, 2))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 5), (x + 3, y_anim + 5), 2)
            elif self.kind in ("Ceifador", "Piromante", "Sentinela Laser", "Berserker"):
                pygame.draw.circle(s, WHITE, (x - 5, y_anim - 3), 3)
                pygame.draw.circle(s, WHITE, (x + 5, y_anim - 3), 3)
                pygame.draw.circle(s, outline_col, (x - 5, y_anim - 3), 1)
                pygame.draw.circle(s, outline_col, (x + 5, y_anim - 3), 1)
                if self.kind == "Ceifador":
                    pygame.draw.line(s, (190, 200, 220), (x + r + 4, y_anim - 14), (x + r - 2, y_anim + 14), 2)
                    pygame.draw.polygon(s, CYAN, [(x + r + 4, y_anim - 14), (x + r + 16, y_anim - 10), (x + r + 4, y_anim - 6)])
                elif self.kind == "Piromante":
                    glow_circle(s, ORANGE, (x, y_anim - r - 6), 5, 1)
                elif self.kind == "Sentinela Laser":
                    pygame.draw.rect(s, CYAN, (x - 8, y_anim - 5, 16, 4), border_radius=2)
                elif self.kind == "Berserker":
                    pygame.draw.polygon(s, WHITE, [(x - 9, y_anim - r), (x - 13, y_anim - r - 8), (x - 4, y_anim - r)])
                    pygame.draw.polygon(s, WHITE, [(x + 9, y_anim - r), (x + 13, y_anim - r - 8), (x + 4, y_anim - r)])
            elif self.kind == "Aracnídeo":
                for side_s in (-1, 1):
                    for leg_i in (-1, 0, 1):
                        ly = y_anim + leg_i * 5
                        knee_x = x + side_s * (r + 7)
                        knee_y = ly - 4 + int(math.sin(time_s * 20 + leg_i) * 3)
                        foot_x = x + side_s * (r + 13)
                        foot_y = ly + 5
                        pygame.draw.lines(s, outline_col, False, [(x + side_s * r, ly), (knee_x, knee_y), (foot_x, foot_y)], 2)
                for ex_o in (-6, -2, 2, 6):
                    pygame.draw.circle(s, RED, (x + ex_o, y_anim - 3), 2)
            elif self.kind == "Anomalia":
                ring_r = r + 5 + int(math.sin(time_s * 8) * 3)
                pygame.draw.circle(s, CYAN, (x, y_anim), ring_r, 1)
                glow_circle(s, PURPLE, (x, y_anim), 6, 2)
                pygame.draw.circle(s, WHITE, (x, y_anim), 3)

            elif self.kind == "Espelho":
                pygame.draw.polygon(s, (220, 240, 255), [(x, y_anim - r - 2), (x + r + 2, y_anim), (x, y_anim + r + 2), (x - r - 2, y_anim)], 2)
                pygame.draw.rect(s, WHITE, (x - 5, y_anim - 4, 3, 3))
                pygame.draw.rect(s, WHITE, (x + 2, y_anim - 4, 3, 3))
                pygame.draw.line(s, outline_col, (x - 4, y_anim + 5), (x + 4, y_anim + 5), 2)

            elif self.kind == "Parasita":
                pygame.draw.circle(s, (80, 200, 40), (x - 6, y_anim - 4), 4)
                pygame.draw.circle(s, (80, 200, 40), (x + 6, y_anim - 4), 4)
                pygame.draw.rect(s, outline_col, (x - 3, y_anim, 2, 3))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim, 2, 3))
                for k in range(3):
                    a = time_s * 6 + k * 2.1
                    pygame.draw.line(s, (135, 255, 70), (x, y_anim), (x + math.cos(a) * (r + 6), y_anim + math.sin(a) * (r + 6)), 2)

            elif self.kind == "Vórtice":
                for k in range(3):
                    rr = r + 4 + k * 5
                    pygame.draw.circle(s, (130, 60, 235), (x, y_anim), rr, 1)
                pygame.draw.circle(s, (200, 140, 255), (x, y_anim), 4)
                pygame.draw.rect(s, WHITE, (x - 5, y_anim - 3, 2, 2))
                pygame.draw.rect(s, WHITE, (x + 3, y_anim - 3, 2, 2))

            elif self.kind == "Escudeiro":
                pygame.draw.arc(s, (180, 200, 230), (x - r - 8, y_anim - r - 8, (r + 8) * 2, (r + 8) * 2), self.shield_dir - 0.95, self.shield_dir + 0.95, 3)
                pygame.draw.rect(s, outline_col, (x - 5, y_anim - 3, 3, 3))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim - 3, 3, 3))
                pygame.draw.line(s, outline_col, (x - 3, y_anim + 5), (x + 3, y_anim + 5), 2)

            elif self.kind == "Bombardeiro":
                pygame.draw.rect(s, (255, 150, 60), (x - 6, y_anim - r - 6, 12, 8), border_radius=2)
                pygame.draw.circle(s, RED, (x, y_anim - r - 8), 3)
                pygame.draw.rect(s, outline_col, (x - 5, y_anim - 2, 3, 3))
                pygame.draw.rect(s, outline_col, (x + 2, y_anim - 2, 3, 3))

            elif self.kind == "Fantasma":
                alpha_col = (200, 230, 255) if self.intangible > 0 else outline_col
                pygame.draw.circle(s, alpha_col, (x - 5, y_anim - 3), 3, 1)
                pygame.draw.circle(s, alpha_col, (x + 5, y_anim - 3), 3, 1)
                pygame.draw.arc(s, alpha_col, (x - 6, y_anim + 1, 12, 8), 0.2, math.pi - 0.2, 2)
                if self.intangible > 0:
                    pygame.draw.circle(s, (175, 210, 255), (x, y_anim), r + 4, 1)

            if self.hp < self.maxhp:
                bw = self.r * 2 + 8
                pygame.draw.rect(s, (25, 15, 20), (x - bw // 2, y_anim - self.r - 12, bw, 4), border_radius=2)
                pygame.draw.rect(s, GREEN, (x - bw // 2, y_anim - self.r - 12, int(bw * clamp(self.hp / self.maxhp, 0, 1)), 4), border_radius=2)

        if not self.boss and getattr(self, "zone_idx", 0) > 0:
            zt = self.zone_variant["tint"]
            pygame.draw.circle(s, zt, (x, y_anim - self.r - 4), 2)
        if self.affix:
            ac = AFFIX_COL[self.affix]
            pygame.draw.circle(s, ac, (x, y_anim), int(self.r) + 7 + int(math.sin(time_s * 6) * 2), 2)
            draw_text(s, self.affix.upper(), TINY, ac, (x, y_anim - self.r - 22), True)
        if self.status:
            ix = x - (len(self.status) - 1) * 5
            for k_st in self.status:
                pygame.draw.circle(s, STATUS_COL[k_st], (ix, y_anim - self.r - 8 if not self.affix else y_anim - self.r - 34), 3)
                ix += 10
        if self.hitflash > 0:
            flash_disc(s, (x, y_anim), self.r, min(1.0, self.hitflash / .12))
        if game.settings.get("show_hitboxes", False):
            pygame.draw.circle(s, (255, 255, 0), (x, y), int(self.r), 1)


# ============================================================================
# ===  GAMEPLAY 2.0: PERIGOS TELEGRAFADOS, CHEFES COM PADRÕES PRÓPRIOS,     ===
# ===  OBJETOS DE CENÁRIO INTERATIVOS, VISUAL DO JOGADOR / INIMIGOS / HUD    ===
# ============================================================================
_HZ_CACHE = {}


def _alpha_disc(s, col, pos, r, alpha, width=0):
    """Disco/anel translúcido em cache (usado nos avisos dos perigos)."""
    r = max(3, int(r))
    key = (col, r >> 1, alpha >> 4, width)
    spr = _HZ_CACHE.get(key)
    if spr is None:
        if len(_HZ_CACHE) > 60:
            _HZ_CACHE.clear()
        rr = (r >> 1) << 1
        spr = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(spr, (col[0], col[1], col[2], (alpha >> 4) << 4), (rr + 2, rr + 2), rr, width)
        _HZ_CACHE[key] = spr
    s.blit(spr, (int(pos[0]) - spr.get_width() // 2, int(pos[1]) - spr.get_height() // 2))


def _seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 <= 1e-6:
        return math.hypot(px - x0, py - y0)
    t = clamp(((px - x0) * dx + (py - y0) * dy) / L2, 0.0, 1.0)
    return math.hypot(px - (x0 + dx * t), py - (y0 + dy * t))


class Hazard:
    """Perigo com aviso (telegraph) e efeito: circle, ring, beam, cloud, pull, gust, warnline."""

    def __init__(self, kind, x, y, r=80.0, ang=0.0, length=900.0, width=28.0, warm=0.9, dur=0.0,
                 dmg=20.0, col=(255, 80, 60), spin=0.0, cloud=False, gap=0.0, speed=320.0, tick=0.18,
                 strength=240.0, blast=0.0, foe=False, visual=False):
        self.kind, self.x, self.y, self.r = kind, float(x), float(y), float(r)
        self.ang, self.length, self.width = float(ang), float(length), float(width)
        self.warm, self.dur, self.dmg = float(warm), float(dur), float(dmg)
        self.col = tuple(int(c) for c in col)
        self.spin, self.cloud, self.gap, self.speed = float(spin), bool(cloud), float(gap), float(speed)
        self.tick, self.strength, self.blast = float(tick), float(strength), float(blast)
        self.foe, self.visual = bool(foe), bool(visual)
        self.t = 0.0
        self.fired = False
        self.tick_t = 0.0
        self.cur_r = 0.0
        self.hit = set()
        if kind == "circle":
            self.life = self.warm + 0.4
        elif kind == "ring":
            self.life = self.warm + 1000.0 / max(60.0, self.speed)
        elif kind == "pull":
            self.life = self.warm + self.dur + 0.45
        elif kind == "warnline":
            self.life = self.warm + 0.05
        else:
            self.life = self.warm + self.dur + 0.25

    def spec(self):
        return {"k": self.kind, "x": round(self.x, 1), "y": round(self.y, 1), "r": self.r, "a": round(self.ang, 3),
                "l": self.length, "w": self.width, "wm": self.warm, "d": self.dur, "dm": self.dmg, "c": list(self.col),
                "sp": self.spin, "cl": self.cloud, "g": self.gap, "v": self.speed, "tk": self.tick,
                "st": self.strength, "b": self.blast, "f": self.foe}

    # ------------------------------------------------------------------
    def update(self, dt, g):
        self.t += dt
        k = self.kind
        host = not self.visual
        if k == "circle":
            if not self.fired and self.t >= self.warm:
                self.fired = True
                g.shockwaves.append(Shockwave(self.x, self.y, self.r, self.col, 0.38, 4))
                for _ in range(14):
                    g.particles.append(Particle(self.x + random.uniform(-self.r * .5, self.r * .5),
                                                self.y + random.uniform(-self.r * .5, self.r * .5), self.col, size=5))
                g.camera_shake = max(g.camera_shake, 0.22)
                play_sound("boom")
                if host:
                    g.hurt_in_circle(self.x, self.y, self.r, self.dmg, self.foe)
                    if self.cloud:
                        g.spawn_hazard("cloud", self.x, self.y, r=self.r * 0.9, warm=0.0, dur=4.5,
                                       dmg=max(2.0, self.dmg * 0.16), tick=0.45, col=self.col)
        elif k == "ring":
            if self.t >= self.warm:
                self.cur_r = (self.t - self.warm) * self.speed
                if host:
                    for tg in g.hz_targets():
                        if id(tg) in self.hit:
                            continue
                        d = math.hypot(tg.x - self.x, tg.y - self.y)
                        if abs(d - self.cur_r) < self.width * 0.5 + tg.r * 0.6:
                            a = math.atan2(tg.y - self.y, tg.x - self.x)
                            diff = (a - self.ang + math.pi) % math.tau - math.pi
                            if abs(diff) > self.gap:
                                self.hit.add(id(tg))
                                tg.take_damage(self.dmg, g)
        elif k == "beam":
            if self.t >= self.warm:
                self.ang += self.spin * dt
                if host:
                    self.tick_t -= dt
                    if self.tick_t <= 0:
                        self.tick_t = self.tick
                        x1, y1 = self.x + math.cos(self.ang) * self.length, self.y + math.sin(self.ang) * self.length
                        for tg in g.hz_targets():
                            if _seg_dist(tg.x, tg.y, self.x, self.y, x1, y1) < self.width * 0.5 + tg.r * 0.5:
                                tg.take_damage(self.dmg, g)
                if random.random() < dt * 40:
                    dd = random.uniform(40, self.length)
                    g.particles.append(Particle(self.x + math.cos(self.ang) * dd, self.y + math.sin(self.ang) * dd, self.col, size=3))
        elif k == "cloud":
            if self.t >= self.warm:
                if random.random() < dt * 14:
                    g.particles.append(Particle(self.x + random.uniform(-self.r, self.r) * .8, self.y + random.uniform(-self.r, self.r) * .8,
                                                self.col, vel=(0, -30), life=0.6, size=5, kind="smoke"))
                if host:
                    self.tick_t -= dt
                    if self.tick_t <= 0:
                        self.tick_t = self.tick
                        for tg in g.hz_targets():
                            if math.hypot(tg.x - self.x, tg.y - self.y) < self.r:
                                if tg is g.player:
                                    g.terrain_dot(self.dmg, self.col)
                                else:
                                    tg.take_damage(self.dmg, g)
        elif k == "pull":
            if self.warm <= self.t < self.warm + self.dur:
                for ent in g.pull_subjects(host):
                    d = math.hypot(self.x - ent.x, self.y - ent.y)
                    if 6 < d < self.r:
                        f = self.strength * (1.0 - d / self.r) * (0.35 if getattr(ent, "boss", False) else 1.0)
                        ent.x += (self.x - ent.x) / d * f * dt
                        ent.y += (self.y - ent.y) / d * f * dt
            if not self.fired and self.t >= self.warm + self.dur:
                self.fired = True
                if self.blast > 0:
                    g.shockwaves.append(Shockwave(self.x, self.y, self.blast, self.col, 0.4, 4))
                    g.camera_shake = max(g.camera_shake, 0.25)
                    play_sound("boom")
                    if host:
                        g.hurt_in_circle(self.x, self.y, self.blast, self.dmg, self.foe)
        elif k == "gust":
            if self.warm <= self.t < self.warm + self.dur:
                vx, vy = math.cos(self.ang) * self.strength, math.sin(self.ang) * self.strength
                for ent in g.pull_subjects(host):
                    f = 0.35 if getattr(ent, "boss", False) else 1.0
                    ent.x = clamp(ent.x + vx * f * dt, 26, g.world_w - 26)
                    ent.y = clamp(ent.y + vy * f * dt, 26, g.world_h - 26)

    # ------------------------------------------------------------------
    def draw(self, s, cx, cy, g):
        k = self.kind
        sx, sy = self.x - cx, self.y - cy
        col = self.col
        warming = self.t < self.warm
        pulse = 0.5 + 0.5 * math.sin(self.t * 15)
        if k == "gust":
            if self.t < self.warm + self.dur:
                a = self.ang
                ca, sa = math.cos(a), math.sin(a)
                active = self.t >= self.warm
                for i in range(16):
                    ph = (self.t * (900 if active else 150) * 0.002 + i * 0.37) % 1.0
                    off = (i * 97) % 1000 / 1000.0
                    bx = (off * (W + 400) + ph * 600 * ca) % (W + 400) - 200
                    by = ((i * 53) % 800 / 800.0 * (H + 200) + ph * 600 * sa) % (H + 200) - 100
                    ln = 70 if active else 25
                    pygame.draw.line(s, _fade(col, 0.75 if active else 0.35), (bx, by), (bx + ca * ln, by + sa * ln), 2)
            return
        vis_r = self.r if k != "beam" else self.length
        if sx < -vis_r - 60 or sx > W + vis_r + 60 or sy < -vis_r - 60 or sy > H + vis_r + 60:
            return
        if k == "circle":
            if warming:
                prog = self.t / max(0.01, self.warm)
                _alpha_disc(s, col, (sx, sy), self.r, int(30 + 55 * pulse))
                pygame.draw.circle(s, col, (int(sx), int(sy)), int(self.r), 3)
                pygame.draw.circle(s, mix_color(col, WHITE, 0.55), (int(sx), int(sy)), max(3, int(self.r * prog)), 2)
                pygame.draw.line(s, col, (sx - 9, sy), (sx + 9, sy), 2)
                pygame.draw.line(s, col, (sx, sy - 9), (sx, sy + 9), 2)
            else:
                f = clamp((self.t - self.warm) / 0.4, 0.0, 1.0)
                pygame.draw.circle(s, _fade(mix_color(col, WHITE, 0.5), 1.0 - f), (int(sx), int(sy)), int(self.r * (0.8 + 0.3 * f)), max(1, int(6 * (1 - f))))
        elif k == "warnline":
            x1, y1 = sx + math.cos(self.ang) * self.length, sy + math.sin(self.ang) * self.length
            nxp, nyp = -math.sin(self.ang) * self.width * 0.5, math.cos(self.ang) * self.width * 0.5
            c2 = _fade(col, 0.55 + 0.4 * pulse)
            pygame.draw.line(s, c2, (sx + nxp, sy + nyp), (x1 + nxp, y1 + nyp), 2)
            pygame.draw.line(s, c2, (sx - nxp, sy - nyp), (x1 - nxp, y1 - nyp), 2)
            pygame.draw.line(s, _fade(col, 0.35), (sx, sy), (x1, y1), 1)
        elif k == "beam":
            x1, y1 = sx + math.cos(self.ang) * self.length, sy + math.sin(self.ang) * self.length
            if warming:
                nxp, nyp = -math.sin(self.ang) * self.width * 0.5, math.cos(self.ang) * self.width * 0.5
                c2 = _fade(col, 0.45 + 0.45 * pulse)
                pygame.draw.line(s, c2, (sx + nxp, sy + nyp), (x1 + nxp, y1 + nyp), 2)
                pygame.draw.line(s, c2, (sx - nxp, sy - nyp), (x1 - nxp, y1 - nyp), 2)
                pygame.draw.circle(s, col, (int(sx), int(sy)), int(8 + 6 * pulse), 2)
            else:
                fade_out = clamp((self.warm + self.dur + 0.2 - self.t) / 0.2, 0.0, 1.0)
                w = max(3, int(self.width * fade_out))
                pygame.draw.line(s, _fade(col, 0.45), (sx, sy), (x1, y1), w + 12)
                pygame.draw.line(s, col, (sx, sy), (x1, y1), w)
                pygame.draw.line(s, (255, 255, 255), (sx, sy), (x1, y1), max(2, w // 3))
                soft_glow(s, col, (sx, sy), 46, 90)
        elif k == "ring":
            if warming:
                prog = self.t / max(0.01, self.warm)
                pygame.draw.circle(s, _fade(col, 0.5 + 0.4 * pulse), (int(sx), int(sy)), int(24 + 46 * prog), 3)
                ga, gw = self.ang, max(0.1, self.gap)
                for sgn in (-1, 1):
                    a = ga + sgn * gw
                    pygame.draw.line(s, (120, 255, 160), (sx + math.cos(a) * 70, sy + math.sin(a) * 70), (sx + math.cos(a) * 140, sy + math.sin(a) * 140), 3)
            elif self.cur_r > 8:
                rad = self.cur_r
                n = int(clamp(rad / 7, 28, 170))
                a0, a1 = self.ang + self.gap, self.ang + math.tau - self.gap
                prev = None
                wd = max(4, int(self.width * 0.5))
                for i in range(n + 1):
                    a = a0 + (a1 - a0) * i / n
                    p_ = (sx + math.cos(a) * rad, sy + math.sin(a) * rad)
                    if prev is not None and (-80 < p_[0] < W + 80 and -80 < p_[1] < H + 80):
                        pygame.draw.line(s, col, prev, p_, wd + 4)
                        pygame.draw.line(s, (255, 235, 235), prev, p_, max(2, wd // 2))
                    prev = p_
        elif k == "cloud":
            if warming:
                pygame.draw.circle(s, _fade(col, 0.4 + 0.4 * pulse), (int(sx), int(sy)), int(self.r), 2)
            else:
                fo = clamp((self.warm + self.dur + 0.25 - self.t) / 0.5, 0.0, 1.0)
                _alpha_disc(s, col, (sx, sy), self.r, int((40 + 25 * pulse) * fo))
                pygame.draw.circle(s, _fade(col, 0.6 * fo), (int(sx), int(sy)), int(self.r), 2)
        elif k == "pull":
            if warming:
                pygame.draw.circle(s, _fade(col, 0.4 + 0.4 * pulse), (int(sx), int(sy)), int(self.r), 2)
            elif self.t < self.warm + self.dur:
                for i in range(3):
                    a = self.t * 3 + i * 2.09
                    pts = [(sx + math.cos(a + j * 0.35) * self.r * (1 - j / 14), sy + math.sin(a + j * 0.35) * self.r * (1 - j / 14)) for j in range(14)]
                    pygame.draw.lines(s, col, False, pts, 3)
                pygame.draw.circle(s, (8, 4, 20), (int(sx), int(sy)), 18)
                pygame.draw.circle(s, col, (int(sx), int(sy)), int(self.r), 1)
                soft_glow(s, col, (sx, sy), self.r * 0.6, 60)
            if self.blast > 0 and warming is False and self.t < self.warm + self.dur:
                pygame.draw.circle(s, _fade(col, 0.35), (int(sx), int(sy)), int(self.blast), 1)


# ----------------------------------------------------------------------------
# OBJETOS DE CENÁRIO (props): pilares, barris explosivos e cristais
# ----------------------------------------------------------------------------
PROP_HP = {"pillar": 1, "barrel": 60, "crystal": 85}
BARREL_STYLE = {"fire": ((255, 120, 30), "Barril Incendiário"), "toxic": ((110, 255, 90), "Barril Tóxico"),
                "frost": ((150, 225, 255), "Barril Criogênico"), "energy": ((0, 230, 255), "Célula de Energia"),
                "void": ((120, 50, 200), "Barril do Vazio"), "holy": ((255, 220, 100), "Relíquia Solar")}


class Prop:
    def __init__(self, pid, kind, x, y, r, accent, style):
        self.id, self.kind, self.x, self.y, self.r = pid, kind, x, y, r
        self.accent, self.style = accent, style
        self.maxhp = PROP_HP[kind]
        self.hp = float(self.maxhp)
        self.alive = True
        self.respawn = 0.0
        self.flash = 0.0
        self.fuse = -1.0
        self.ph = random.random() * 6.28
        self.born = 1.0


def build_props(idx, ww, wh, pools):
    rng = random.Random(9100 + idx * 17)
    accent = ARENA_BIOMES[idx % len(ARENA_BIOMES)]["border_inner"]
    hz = BIOME_HAZARD[idx % len(BIOME_HAZARD)][0]
    style = {"lava": "fire", "toxic": "toxic", "ice": "frost"}.get(hz, "energy")
    biome_extra = {4: "void", 5: "holy", 7: "void", 10: "holy", 11: "void"}.get(idx % 12)
    props, pid = [], 0
    for kind, n in (("pillar", 9), ("barrel", 6), ("crystal", 7)):
        cnt, tries = 0, 0
        while cnt < n and tries < 700:
            tries += 1
            r = {"pillar": rng.uniform(26, 38), "barrel": 17.0, "crystal": rng.uniform(19, 26)}[kind]
            x, y = rng.uniform(r + 120, ww - r - 120), rng.uniform(r + 120, wh - r - 120)
            if math.hypot(x - ww / 2, y - wh / 2) < 320:
                continue
            if any(math.hypot(x - pl["x"], y - pl["y"]) < pl["r"] + r + 30 for pl in pools):
                continue
            if any(math.hypot(x - q.x, y - q.y) < q.r + r + 95 for q in props):
                continue
            st = style
            if kind == "barrel" and biome_extra and rng.random() < 0.45:
                st = biome_extra
            props.append(Prop(pid, kind, x, y, r, accent, st))
            pid += 1
            cnt += 1
    return props


def _draw_prop(s, pr, sx, sy, t):
    r = int(pr.r)
    acc = pr.accent
    sc_ = 1.0 - 0.6 * max(0.0, pr.born)
    if sc_ <= 0.05:
        return
    draw_soft_shadow(s, sx, sy + r * 0.9, int(r * 2.6 * sc_), max(6, int(r * 0.8)), 110)
    flash = pr.flash > 0
    if pr.kind == "pillar":
        dark, mid, lite = (22, 30, 52), (44, 58, 92), (78, 98, 140)
        top_y = sy - int(r * 1.15)
        pygame.draw.rect(s, dark, (sx - r, top_y, r * 2, int(r * 2.1)), border_radius=6)
        pygame.draw.rect(s, mid, (sx - r + 4, top_y, r * 2 - 8, int(r * 2.1)), border_radius=5)
        pygame.draw.rect(s, lite, (sx - r + 6, top_y + 4, max(3, r // 3), int(r * 2.1) - 8), border_radius=3)
        pygame.draw.ellipse(s, dark, (sx - r, top_y - r // 3, r * 2, int(r * 0.9)))
        pygame.draw.ellipse(s, mid, (sx - r + 3, top_y - r // 3 + 2, r * 2 - 6, int(r * 0.9) - 4))
        glow = 0.55 + 0.45 * math.sin(t * 2.2 + pr.ph)
        pygame.draw.ellipse(s, _fade(acc, glow), (sx - r + 6, top_y - r // 3 + 5, r * 2 - 12, max(4, int(r * 0.9) - 10)), 2)
        for k in range(3):
            yy = top_y + int(r * (0.55 + k * 0.5))
            pygame.draw.line(s, _fade(acc, 0.35 + 0.35 * glow), (sx - r + 6, yy), (sx + r - 6, yy), 1)
    elif pr.kind == "barrel":
        col, _nm = BARREL_STYLE[pr.style]
        danger = pr.fuse >= 0 or pr.hp < pr.maxhp * 0.45
        blink = (math.sin(t * 22) > 0) if danger else False
        body = mix_color((50, 56, 72), col, 0.25 if not blink else 0.7)
        pygame.draw.rect(s, (14, 18, 30), (sx - r, sy - int(r * 1.2), r * 2, int(r * 2.2)), border_radius=7)
        pygame.draw.rect(s, body, (sx - r + 2, sy - int(r * 1.2) + 2, r * 2 - 4, int(r * 2.2) - 4), border_radius=6)
        for k in range(3):
            yy = sy - int(r * 0.6) + k * int(r * 0.65)
            pygame.draw.line(s, col, (sx - r + 3, yy), (sx + r - 3, yy), 3)
        pygame.draw.circle(s, WHITE if blink else col, (sx, sy), max(3, r // 3))
        pygame.draw.circle(s, (14, 18, 30), (sx, sy), max(3, r // 3), 1)
        if pr.style == "void":      # espiral gravitacional
            for k in range(2):
                a = t * 3.0 + k * math.pi
                pts = [(sx + math.cos(a + j * 0.5) * (r * 0.9 - j * 1.4), sy + math.sin(a + j * 0.5) * (r * 0.9 - j * 1.4)) for j in range(6)]
                pygame.draw.lines(s, (200, 140, 255), False, pts, 2)
            pygame.draw.circle(s, _fade(col, 0.5 + 0.4 * math.sin(t * 4)), (sx, sy), int(r * 2.0 + 3 * math.sin(t * 5)), 1)
        elif pr.style == "holy":    # raios solares
            for k in range(8):
                a = t * 1.2 + k * math.tau / 8
                pygame.draw.line(s, _fade(GOLD, 0.8), (sx + math.cos(a) * r * 0.8, sy + math.sin(a) * r * 0.8),
                                 (sx + math.cos(a) * r * 1.5, sy + math.sin(a) * r * 1.5), 2)
        soft_glow(s, col, (sx, sy), r * 2.4, 40 + (50 if blink else 0))
    else:  # crystal
        acc2 = mix_color(acc, WHITE, 0.25)
        pul = 0.6 + 0.4 * math.sin(t * 2.6 + pr.ph)
        h = int(r * 1.9)
        pts = [(sx, sy - h), (sx + int(r * 0.9), sy - int(h * 0.25)), (sx + int(r * 0.6), sy + int(r * 0.8)),
               (sx - int(r * 0.6), sy + int(r * 0.8)), (sx - int(r * 0.9), sy - int(h * 0.25))]
        soft_glow(s, acc, (sx, sy - r // 2), r * 2.6, int(40 + 40 * pul))
        pygame.draw.polygon(s, (10, 16, 30), pts)
        pygame.draw.polygon(s, mix_color(acc, (10, 16, 30), 0.35), [(sx, sy - h + 4), (sx + int(r * 0.7), sy - int(h * 0.22)), (sx + int(r * 0.45), sy + int(r * 0.6)), (sx - int(r * 0.45), sy + int(r * 0.6)), (sx - int(r * 0.7), sy - int(h * 0.22))])
        pygame.draw.polygon(s, _fade(acc2, 0.5 + 0.4 * pul), [(sx, sy - h + 4), (sx + int(r * 0.7), sy - int(h * 0.22)), (sx, sy + int(r * 0.2))])
        pygame.draw.line(s, WHITE, (sx, sy - h + 4), (sx, sy + int(r * 0.6)), 1)
        pygame.draw.polygon(s, acc2, pts, 2)
    if flash:
        pygame.draw.circle(s, WHITE, (sx, sy), r + 3, 2)
    if pr.kind != "pillar" and pr.hp < pr.maxhp:
        bw = r * 2
        pygame.draw.rect(s, (20, 14, 24), (sx - bw // 2, sy - int(r * 1.5) - 10, bw, 4))
        pygame.draw.rect(s, GREEN if pr.hp > pr.maxhp * 0.45 else RED, (sx - bw // 2, sy - int(r * 1.5) - 10, int(bw * clamp(pr.hp / pr.maxhp, 0, 1)), 4))


# ----------------------------------------------------------------------------
# CHEFES: 12 ARQUÉTIPOS COM PADRÕES DE ATAQUE PRÓPRIOS
# ----------------------------------------------------------------------------
BOSS_ATK_NAME = {
    "radial": "CHUVA RADIAL", "fan": "LEQUE DE TIROS", "slam": "ESMAGAMENTO", "ring": "ONDA DE CHOQUE",
    "lunge": "INVESTIDA", "dashchain": "INVESTIDAS EM CADEIA", "toxic": "BOMBAS TÓXICAS", "meteors": "CHUVA DE METEOROS",
    "lasersweep": "LASER VARREDOR", "lasercross": "LASER EM CRUZ", "summon": "CONVOCAÇÃO", "rift": "POÇO GRAVITACIONAL",
    "blink": "SALTO DIMENSIONAL", "prism": "PRISMA RADIANTE", "starrain": "CHUVA ESTELAR", "guard": "GUARDA BLINDADA",
    "crown": "COROA REAL",
    "void": {"col": (120, 50, 200), "name": "Barril do Vazio", "pull": True},
    "holy": {"col": (255, 220, 100), "name": "Relíquia Solar", "heal": True},

}
BOSS_PATTERNS = {
    0: [("radial", 1), ("slam", 1), ("fan", 1), ("ring", 3)],
    1: [("lunge", 1), ("fan", 1), ("summon", 2), ("dashchain", 3)],
    2: [("toxic", 1), ("radial", 1), ("ring", 2), ("fan", 2)],
    3: [("dashchain", 1), ("fan", 1), ("radial", 2), ("lunge", 1)],
    4: [("guard", 1), ("fan", 1), ("slam", 1), ("meteors", 3)],
    5: [("summon", 1), ("crown", 1), ("slam", 2), ("ring", 3)],
    6: [("meteors", 1), ("slam", 1), ("fan", 2), ("ring", 2)],
    7: [("rift", 1), ("blink", 1), ("lasercross", 2), ("fan", 1)],
    8: [("lasersweep", 1), ("ring", 1), ("fan", 1), ("lasercross", 3)],
    9: [("lasercross", 1), ("meteors", 1), ("radial", 1), ("dashchain", 2), ("ring", 2), ("rift", 3)],
    10: [("prism", 1), ("summon", 2), ("ring", 1), ("lasersweep", 3)],
    11: [("starrain", 1), ("rift", 1), ("lasersweep", 2), ("prism", 3)],
}
BOSS_SUMMONS = {1: ["Veloz", "Veloz", "Berserker"], 5: ["Básico", "Tanque", "Escudeiro"], 10: ["Espelho", "Atirador"]}


def _b_radial(e, g, n, spd, off=0.0, col=None, size=6):
    bd = 8 + e.phase * 3.5 + e.bi * 1.2
    for i in range(n):
        a = off + math.tau * i / n
        g.bullets.append(Bullet(e.x, e.y, math.cos(a) * spd, math.sin(a) * spd, bd, enemy=True, size=size, color=col))


def _b_fan(e, g, ang, n, spread, spd, col=None, size=6):
    bd = 9 + e.phase * 3.5 + e.bi * 1.2
    for i in range(n):
        a = ang + (i - (n - 1) / 2) * spread
        g.bullets.append(Bullet(e.x, e.y, math.cos(a) * spd, math.sin(a) * spd, bd, enemy=True, size=size, color=col))


def _boss_attack(e, g, p, name, nx, ny, dist):
    ph = e.phase
    ang = math.atan2(ny, nx)
    hd = e.damage * 1.05
    col = e.color
    hot = mix_color(col, (255, 120, 60), 0.5)
    if name == "radial":
        _b_radial(e, g, 12 + ph * 5, 205 + ph * 12, off=g.elapsed)
        if ph >= 2:
            e.pend = [0.35, "radial", None]
    elif name == "fan":
        _b_fan(e, g, ang, 5 + ph * 2, 0.20, 250)
    elif name == "slam":
        g.spawn_hazard("circle", e.x, e.y, r=150 + ph * 25, warm=0.9, dmg=hd * 1.25, col=hot)
        e.pend = [0.92, "radial", None]
        e.hold = 1.2
    elif name == "ring":
        g.spawn_hazard("ring", e.x, e.y, ang=ang + random.uniform(-1.2, 1.2), gap=0.50, warm=0.8, speed=300 + ph * 25, width=26, dmg=hd * 0.95, col=(255, 70, 90))
    elif name == "lunge":
        e.pend = [0.01, "windup", None]
        e.chain = 0
    elif name == "dashchain":
        e.chain = 2
        e.pend = [0.01, "windup", None]
    elif name == "toxic":
        for i in range(3 + ph):
            ox, oy = (p.x if i == 0 else p.x + random.uniform(-280, 280)), (p.y if i == 0 else p.y + random.uniform(-280, 280))
            g.spawn_hazard("circle", clamp(ox, 60, g.world_w - 60), clamp(oy, 60, g.world_h - 60), r=76, warm=1.05 + i * 0.18, dmg=hd * 0.8, col=(110, 255, 90), cloud=True)
    elif name == "meteors":
        for i in range(4 + ph * 2):
            ox, oy = (p.x if i == 0 else p.x + random.uniform(-330, 330)), (p.y if i == 0 else p.y + random.uniform(-330, 330))
            g.spawn_hazard("circle", clamp(ox, 60, g.world_w - 60), clamp(oy, 60, g.world_h - 60), r=72, warm=1.1 + i * 0.12, dmg=hd * 0.9, col=(255, 130, 40), cloud=(e.bi - 1) % 12 in (6, 9))
    elif name == "lasersweep":
        sgn = random.choice((-1, 1))
        g.spawn_hazard("beam", e.x, e.y, ang=ang - sgn * 0.9, length=1100, width=30, warm=1.0, dur=2.4, dmg=hd * 0.7, spin=sgn * (0.75 + ph * 0.12), col=(255, 60, 80), tick=0.15)
        e.hold = 3.4
    elif name == "lasercross":
        base = random.uniform(0, math.tau)
        for k in range(4):
            g.spawn_hazard("beam", e.x, e.y, ang=base + k * math.pi / 2, length=1100, width=26, warm=1.1, dur=3.0, dmg=hd * 0.65, spin=0.55 + ph * 0.1, col=(190, 90, 255), tick=0.15)
        e.hold = 4.0
    elif name == "summon":
        pool = BOSS_SUMMONS.get((e.bi - 1) % 12, ["Básico", "Veloz"])
        for i in range(2 + ph):
            if len(g.enemies) < 100:
                a = random.random() * math.tau
                mx_, my_ = clamp(e.x + math.cos(a) * 110, 40, g.world_w - 40), clamp(e.y + math.sin(a) * 110, 40, g.world_h - 40)
                kind = random.choice(pool)
                if kind not in ENEMY_TYPES:
                    kind = "Básico"
                m = Enemy(mx_, my_, kind, g.level)
                m.xp *= 0.35
                m.spawn_t = 0.45
                g.enemies.append(m)
                g.shockwaves.append(Shockwave(mx_, my_, 36, PURPLE, 0.3, 2))
    elif name == "rift":
        g.spawn_hazard("pull", p.x + random.uniform(-90, 90), p.y + random.uniform(-90, 90), r=340, warm=0.7, dur=2.6, strength=250 + ph * 25, blast=130, dmg=hd * 1.1, col=(170, 80, 255))
    elif name == "blink":
        tx = clamp(p.x + math.cos(ang + math.pi + random.uniform(-0.8, 0.8)) * 150, 60, g.world_w - 60)
        ty = clamp(p.y + math.sin(ang + math.pi + random.uniform(-0.8, 0.8)) * 150, 60, g.world_h - 60)
        g.spawn_hazard("circle", tx, ty, r=100, warm=0.85, dmg=hd * 1.1, col=(180, 90, 255))
        e.pend = [0.85, "blink", (tx, ty)]
        e.hold = 1.0
    elif name == "prism":
        e.pend = [0.01, "prism", 3 + (1 if ph >= 3 else 0)]
    elif name == "starrain":
        for i in range(8 + ph * 2):
            ox, oy = p.x + random.uniform(-420, 420), p.y + random.uniform(-340, 340)
            g.spawn_hazard("circle", clamp(ox, 50, g.world_w - 50), clamp(oy, 50, g.world_h - 50), r=54, warm=0.8 + random.uniform(0, 0.9), dmg=hd * 0.75, col=(220, 235, 255))
    elif name == "guard":
        e.guard = 3.0
        g.shockwaves.append(Shockwave(e.x, e.y, 120, (150, 170, 210), 0.4, 4))
        _b_fan(e, g, ang, 7 + ph * 2, 0.17, 235, col=(170, 190, 230))
    elif name == "crown":
        _b_radial(e, g, 14 + ph * 4, 190, off=g.elapsed, col=GOLD, size=6)
        e.pend = [0.4, "crown2", None]


def _boss_pending(e, g, p, act):
    name, data = act[1], act[2]
    ph = e.phase
    ang = math.atan2(p.y - e.y, p.x - e.x)
    if name == "windup":
        g.spawn_hazard("warnline", e.x, e.y, ang=ang, length=780, width=46, warm=0.55, col=(255, 70, 70))
        e.pend = [0.55, "charge", None]
    elif name == "charge":
        e.charge = 0.42 if e.chain > 0 else 0.55
        if e.chain > 0:
            e.chain -= 1
            e.pend = [0.95, "windup", None]
    elif name == "radial":
        _b_radial(e, g, 12 + ph * 4, 215, off=g.elapsed * 0.7)
    elif name == "crown2":
        _b_radial(e, g, 14 + ph * 4, 160, off=g.elapsed + 0.2, col=(255, 235, 150), size=7)
    elif name == "blink":
        tx, ty = data
        g.particles.extend(Particle(e.x, e.y, e.color, size=6) for _ in range(12))
        e.x, e.y = tx, ty
        g.shockwaves.append(Shockwave(e.x, e.y, 90, e.color, 0.3, 3))
        _b_radial(e, g, 10 + ph * 2, 230, off=random.random())
    elif name == "prism":
        n = int(data)
        hue = (g.elapsed * 0.35 + n * 0.17) % 1.0
        r_, g_, b_ = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
        c = (int(r_ * 255), int(g_ * 255), int(b_ * 255))
        _b_fan(e, g, ang + random.uniform(-0.25, 0.25), 7 + ph, 0.22, 240, col=c, size=6)
        if n > 1:
            e.pend = [0.38, "prism", n - 1]


def boss_ai(e, dt, g, p, nx, ny, dist, slow):
    arche = (e.bi - 1) % 12
    ph = e.phase
    e.cur_attack_t = max(0.0, e.cur_attack_t - dt)
    e.guard = max(0.0, e.guard - dt)
    e.hold = max(0.0, e.hold - dt)
    if e.pend is not None:
        e.pend[0] -= dt
        if e.pend[0] <= 0:
            act, e.pend = e.pend, None
            _boss_pending(e, g, p, act)
    # ---- movimento ----
    if e.charge > 0:
        e.charge -= dt
        mult = 4.2 if ph == 3 else 3.8
        e.x += nx * e.speed * mult * dt
        e.y += ny * e.speed * mult * dt
    else:
        mm = (0.15 if e.pend is not None else 1.0) * (0.25 if e.hold > 0 else 1.0) * slow
        if arche in (7, 8, 11):
            if dist < 300:
                dv, st = -1.0, 0.0
            elif dist > 480:
                dv, st = 1.0, 0.0
            else:
                dv, st = 0.0, 0.5
        else:
            dv, st = 1.0, 0.0
        e.x += (nx * dv - ny * st) * e.speed * mm * dt
        e.y += (ny * dv + nx * st) * e.speed * mm * dt
    e.x, e.y = clamp(e.x, 60, g.world_w - 60), clamp(e.y, 60, g.world_h - 60)
    # ---- escolha de ataque ----
    e.attack_timer -= dt
    if e.attack_timer <= 0 and e.pend is None and e.charge <= 0:
        if not g.camera_visible(e.x, e.y):
            e.attack_timer = 0.8
        else:
            cands = [n for (n, mp) in BOSS_PATTERNS[arche] if mp <= ph and n != e.last_atk] or [BOSS_PATTERNS[arche][0][0]]
            name = random.choice(cands)
            e.last_atk = name
            e.attack_timer = max(1.1, 3.1 - ph * 0.55) + random.uniform(0.0, 0.5)
            e.cur_attack, e.cur_attack_t = BOSS_ATK_NAME.get(name, name.upper()), 1.9
            _boss_attack(e, g, p, name, nx, ny, dist)
    # ---- reforços espontâneos nas fases 2 e 3 ----
    if ph >= 2 and len(g.enemies) < 90 and random.random() < dt * (0.30 if ph == 3 else 0.16):
        g.spawn_enemy("Aracnídeo" if ph == 3 else "Veloz")


# ----------------------------------------------------------------------------
# VISUAIS: PROJÉTIL INIMIGO LEGÍVEL, OVERLAYS DE CHEFE, JOGADOR EVOLUTIVO
# ----------------------------------------------------------------------------
def _draw_enemy_bullet(s, bx, by, b):
    r = b.size
    col = b.color
    t = pygame.time.get_ticks() * 0.012 + b.x * 0.03
    cxp, cyp = int(bx), int(by)
    pr = r + 2 + int(math.sin(t) * 1.4)
    soft_glow(s, col, (cxp, cyp), r * 3.2, 70)
    pygame.draw.circle(s, (18, 6, 12), (cxp, cyp), pr + 2)
    pygame.draw.circle(s, col, (cxp, cyp), pr)
    pygame.draw.circle(s, mix_color(col, WHITE, 0.7), (cxp, cyp), max(2, pr - 3))
    for k in range(4):
        a = t * 0.8 + k * math.pi / 2
        pygame.draw.line(s, col, (cxp + math.cos(a) * pr, cyp + math.sin(a) * pr), (cxp + math.cos(a) * (pr + 4), cyp + math.sin(a) * (pr + 4)), 2)


def draw_enemy_overlays(s, cx, cy, g):
    """Escudo/aviso/nome do ataque dos Chefes + marcador de ameaça."""
    t = pygame.time.get_ticks() / 1000.0
    for e in g.enemies:
        if not e.alive or not e.boss:
            continue
        x, y = int(e.x - cx), int(e.y - cy)
        if not (-200 < x < W + 200 and -200 < y < H + 200):
            continue
        if e.guard > 0:
            rr = e.r + 22
            for k in range(8):
                a = t * 2.2 + k * math.tau / 8
                pygame.draw.circle(s, (170, 195, 235), (int(x + math.cos(a) * rr), int(y + math.sin(a) * rr)), 5)
            pygame.draw.circle(s, (150, 175, 220), (x, y), rr, 2)
        if e.pend is not None or e.charge > 0:
            pl = 0.5 + 0.5 * math.sin(t * 20)
            pygame.draw.circle(s, _fade((255, 70, 70), 0.4 + 0.5 * pl), (x, y), int(e.r + 12 + 5 * pl), 3)
        if e.cur_attack_t > 0:
            img = get_cached_text(e.cur_attack, TINY, (255, 220, 160))
            k = clamp(e.cur_attack_t / 0.3, 0.0, 1.0)
            tag = pygame.Rect(0, 0, img.get_width() + 16, 20)
            tag.center = (x, y - e.r - 34)
            pygame.draw.rect(s, (30, 8, 14), tag, border_radius=8)
            pygame.draw.rect(s, _fade((255, 120, 90), k), tag, 1, border_radius=8)
            s.blit(img, (tag.x + 8, tag.y + 3))


def draw_player_back(s, g, px, py, sc):
    """CAMADA 2: anéis de evolução, recarga do impulso, sombra elíptica e halo — tudo ATRÁS do corpo.
    Retorna py_anim (mesma oscilação vertical usada por draw_orb_character)."""
    p = g.player
    t = g.elapsed
    r = int(p.r)
    moving = math.hypot(p.vx, p.vy) > 18
    py_anim = py + int(math.sin(t * 18) * 2.5) if moving else py
    tier = min(4, g.level // 10)
    if tier >= 1:
        n = 5 + tier
        for k in range(n):
            a = t * 1.6 + k * math.tau / n
            pygame.draw.circle(s, sc["bullet"], (int(px + math.cos(a) * (r + 7)), int(py_anim + math.sin(a) * (r + 7))), 2)
    if tier >= 2:
        for k in range(3):
            a = -t * 0.9 + k * math.tau / 3
            pygame.draw.polygon(s, _fade(sc["bullet"], 0.8), [(px + math.cos(a) * (r + 13), py_anim + math.sin(a) * (r + 13)),
                                                              (px + math.cos(a + 0.12) * (r + 6), py_anim + math.sin(a + 0.12) * (r + 6)),
                                                              (px + math.cos(a - 0.12) * (r + 6), py_anim + math.sin(a - 0.12) * (r + 6))])
    if tier >= 3:
        pygame.draw.circle(s, _fade(GOLD, 0.55 + 0.25 * math.sin(t * 3)), (px, py_anim), r + 17, 1)
    if p.dash:
        if p.dash_cd > 0:
            rect2 = pygame.Rect(px - r - 10, py_anim - r - 10, (r + 10) * 2, (r + 10) * 2)
            pygame.draw.arc(s, (60, 130, 175), rect2, math.pi / 2, math.pi / 2 + clamp(1.0 - p.dash_cd / 2.8, 0, 1) * math.tau, 2)
        elif g.elapsed % 1.2 < 0.15:
            pygame.draw.circle(s, CYAN, (px, py_anim), r + 11, 1)
    draw_soft_shadow(s, px, py + 20, 36, 12, 100)
    if g.settings.get("effects", True):
        glow_bloom(s, (200, 0, 0) if p.flash > 0 else sc["glow"], (px, py_anim), r + 1, strength=2)
    return py_anim


def draw_player_extras(s, g, px, py, py_anim, sc):
    """CAMADA 4: coroa de nível, canhão de mira (somente fora da borda), anel de vida e Supremo pronto.
    Nada é desenhado por cima do interior do corpo (raio r)."""
    p = g.player
    t = g.elapsed
    r = int(p.r)
    tier = min(4, g.level // 10)
    if tier >= 4:
        for k in (-1, 0, 1):
            pygame.draw.polygon(s, GOLD, [(px + k * 7 - 3, py_anim - r - 8), (px + k * 7 + 3, py_anim - r - 8), (px + k * 7, py_anim - r - 17 - (4 if k == 0 else 0))])
    # --- canhão de mira ---
    try:
        mxs, mys = pygame.mouse.get_pos()
        aim = math.atan2(mys - py, mxs - px)
        if p.smart_target_pos and g.auto_fire:
            cxm, cym = g.camera()
            aim = math.atan2(p.smart_target_pos[1] - cym - py, p.smart_target_pos[0] - cxm - px)
    except Exception:
        aim = 0.0
    recoil = clamp((0.09 - (g.elapsed - p.last_shot)) / 0.09, 0.0, 1.0) * 4
    ca, sa = math.cos(aim), math.sin(aim)
    b0, b1 = r + 4 - recoil * 0.5, r + 13 - recoil
    nxp, nyp = -sa * 3.5, ca * 3.5
    pygame.draw.polygon(s, (14, 20, 36), [(px + ca * b0 + nxp, py_anim + sa * b0 + nyp), (px + ca * b1 + nxp * 0.8, py_anim + sa * b1 + nyp * 0.8),
                                          (px + ca * b1 - nxp * 0.8, py_anim + sa * b1 - nyp * 0.8), (px + ca * b0 - nxp, py_anim + sa * b0 - nyp)])
    pygame.draw.line(s, sc["bullet"], (px + ca * (b0 + 2), py_anim + sa * (b0 + 2)), (px + ca * b1, py_anim + sa * b1), 2)
    if g.elapsed - p.last_shot < 0.06:
        soft_glow(s, sc["bullet"], (px + ca * (b1 + 4), py_anim + sa * (b1 + 4)), 20, 160)
    # --- anel de vida ---
    frac = clamp(p.hp / max(1.0, p.maxhp), 0.0, 1.0)
    hcol = GREEN if frac > 0.5 else (GOLD if frac > 0.25 else RED)
    rect = pygame.Rect(px - r - 5, py_anim - r - 5, (r + 5) * 2, (r + 5) * 2)
    pygame.draw.arc(s, (20, 30, 50), rect, 0, math.tau, 2)
    if frac > 0.01:
        pygame.draw.arc(s, hcol, rect, math.pi / 2, math.pi / 2 + frac * math.tau, 3)
    if frac < 0.30 and not g.settings.get("reduce_flash", False):
        pygame.draw.circle(s, _fade(RED, 0.4 + 0.4 * math.sin(t * 10)), (px, py_anim), r + 20, 2)
    # --- Supremo pronto ---
    if p.ult_charge >= 100 and not p.downed:
        pr = r + 22 + int(3 * math.sin(t * 6))
        pygame.draw.circle(s, _fade(GOLD, 0.75), (px, py_anim), pr, 2)
        draw_icon(s, "bolt", (px, py_anim - r - 26 - int(2 * math.sin(t * 6))), 6, GOLD)


# ----------------------------------------------------------------------------
# MASCOTES (PETS)
# ----------------------------------------------------------------------------
PETS = [
    {"id": "slime", "name": "Gelatina Azul", "kind": "shooter", "cost": 0,
     "desc": "Atira mini-projéteis no inimigo mais próximo.",
     "color": (60, 170, 255), "accent": (190, 235, 255)},
    {"id": "cat", "name": "Gatinho Relâmpago", "kind": "lightning", "cost": 200,
     "desc": "Solta raios que atingem até 3 inimigos a cada 3s.",
     "color": (255, 215, 70), "accent": (255, 250, 190)},
    {"id": "owl", "name": "Coruja Sábia", "kind": "wisdom", "cost": 250,
     "desc": "+15% de XP e +60 de raio de coleta de orbes.",
     "color": (150, 110, 230), "accent": (225, 205, 255)},
    {"id": "dog", "name": "Cão Guardião", "kind": "guardian", "cost": 300,
     "desc": "+8 de escudo a cada 6s e morde quem chega perto.",
     "color": (80, 235, 150), "accent": (205, 255, 228)},
    {"id": "dragon", "name": "Dragãozinho de Plasma", "kind": "bomber", "cost": 450,
     "desc": "Lança bolas de fogo explosivas em área a cada 4s.",
     "color": (255, 90, 70), "accent": (255, 175, 125)},
    {"id": "phoenix", "name": "Fênix Neon", "kind": "healer", "cost": 600,
     "desc": "Cura 6% da vida máxima a cada 8s.",
     "color": (255, 125, 40), "accent": (255, 228, 115)},
    {"id": "drone", "name": "Drone Cyber-Sniper", "kind": "shooter", "cost": 750,
     "desc": "Dispara lasers de alta precisão e velocidade.",
     "color": (0, 240, 215), "accent": (180, 255, 245)},
    {"id": "seraph", "name": "Serafim Astral", "kind": "lightning", "cost": 950,
     "desc": "Invoca relâmpagos divinos em cadeia contra os inimigos.",
     "color": (255, 85, 195), "accent": (255, 215, 245)},
    {"id": "comet", "name": "Cometa Guardião", "kind": "guardian", "cost": 1250,
     "desc": "Gera escudo periodicamente e protege quando inimigos se aproximam.",
     "color": (100, 220, 255), "accent": (235, 250, 255)},
    {"id": "voidling", "name": "Filhote do Vazio", "kind": "bomber", "cost": 1600,
     "desc": "Dispara explosões roxas contra grupos de inimigos.",
     "color": (175, 90, 255), "accent": (235, 210, 255)},
]

PET_COOLDOWN = {"shooter": 0.70, "lightning": 3.0, "guardian": 6.0, "bomber": 4.0, "healer": 8.0, "wisdom": 99.0}


def draw_pet_sprite(s, pet, x, y, scale=1.0, t=0.0, facing=1):
    """Desenha o mascote (usado no jogo e nos menus)."""
    pid, col, acc = pet["id"], pet["color"], pet["accent"]
    ol = (10, 15, 30)
    fx = 1 if facing >= 0 else -1

    def Q(v):
        return int(round(v * scale))

    def Z(v):
        return max(1, int(round(v * scale)))

    if pid == "slime":
        sq = math.sin(t * 6)
        w, h = Z(14 + sq * 1.2), Z(11 - sq * 1.2)
        pygame.draw.ellipse(s, ol, (x - w - 2, y - h - 2, 2 * w + 4, 2 * h + 4))
        pygame.draw.ellipse(s, col, (x - w, y - h, 2 * w, 2 * h))
        pygame.draw.ellipse(s, acc, (x - w + Z(4), y - h + Z(3), Z(7), Z(4)))
        for ex in (-Q(5), Q(5)):
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(1)), Z(3.2))
            pygame.draw.circle(s, ol, (x + ex + fx * Q(1), y - Q(1)), Z(1.6))
        pygame.draw.arc(s, ol, (x - Q(3), y + Q(1), Q(6), Q(4)), math.pi, math.tau, 1)

    elif pid == "cat":
        tail = [(x - fx * Q(10), y + Q(5)), (x - fx * Q(18), y - Q(1) + int(math.sin(t * 7) * Q(3))), (x - fx * Q(16), y - Q(10))]
        pygame.draw.lines(s, ol, False, tail, max(2, Q(5)))
        pygame.draw.lines(s, col, False, tail, Z(3))
        for sx in (-1, 1):
            ear = [(x + sx * Q(11), y - Q(3)), (x + sx * Q(8), y - Q(17)), (x + sx * Q(1), y - Q(9))]
            pygame.draw.polygon(s, col, ear)
            pygame.draw.polygon(s, ol, ear, 2)
        pygame.draw.circle(s, col, (x, y), Z(12))
        pygame.draw.circle(s, ol, (x, y), Z(12), 2)
        bolt = [(x + Q(1), y - Q(10)), (x - Q(2), y - Q(5)), (x + Q(2), y - Q(5)), (x - Q(1), y)]
        pygame.draw.lines(s, (255, 150, 30), False, bolt, Z(1.6))
        for ex in (-Q(5), Q(5)):
            pygame.draw.ellipse(s, WHITE, (x + ex - Q(2.5), y + Q(1), Z(5), Z(6)))
            pygame.draw.circle(s, ol, (x + ex + fx, y + Q(4)), Z(1.5))
        for sy in (-1, 1):
            pygame.draw.line(s, ol, (x + Q(8), y + Q(6) + sy * Q(1)), (x + Q(15), y + Q(6) + sy * Q(3)), 1)
            pygame.draw.line(s, ol, (x - Q(8), y + Q(6) + sy * Q(1)), (x - Q(15), y + Q(6) + sy * Q(3)), 1)

    elif pid == "owl":
        flap = math.sin(t * 9) * Q(4)
        for sx in (-1, 1):
            wing = [(x + sx * Q(9), y - Q(2)), (x + sx * Q(21), y - Q(8) - flap), (x + sx * Q(17), y + Q(6)), (x + sx * Q(8), y + Q(7))]
            pygame.draw.polygon(s, acc, wing)
            pygame.draw.polygon(s, ol, wing, 2)
            tuft = [(x + sx * Q(10), y - Q(6)), (x + sx * Q(10), y - Q(17)), (x + sx * Q(3), y - Q(10))]
            pygame.draw.polygon(s, col, tuft)
            pygame.draw.polygon(s, ol, tuft, 2)
        pygame.draw.circle(s, col, (x, y), Z(12))
        pygame.draw.circle(s, ol, (x, y), Z(12), 2)
        pygame.draw.ellipse(s, acc, (x - Q(6), y + Q(1), Z(12), Z(10)))
        for ex in (-Q(5), Q(5)):
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(3)), Z(5))
            pygame.draw.circle(s, ol, (x + ex, y - Q(3)), Z(5), 2)
            pygame.draw.circle(s, ol, (x + ex + fx * Q(1), y - Q(2)), Z(2))
        beak = [(x - Q(2), y + Q(1)), (x + Q(2), y + Q(1)), (x, y + Q(6))]
        pygame.draw.polygon(s, ORANGE, beak)

    elif pid == "dog":
        wag = math.sin(t * 12) * Q(4)
        pygame.draw.line(s, ol, (x - fx * Q(9), y + Q(4)), (x - fx * Q(18), y - Q(3) + wag), max(2, Q(5)))
        pygame.draw.line(s, col, (x - fx * Q(9), y + Q(4)), (x - fx * Q(18), y - Q(3) + wag), Z(3))
        dark = mix_color(col, (0, 0, 0), 0.45)
        for sx in (-1, 1):
            pygame.draw.ellipse(s, dark, (x + sx * Q(11) - Q(4), y - Q(8), Z(8), Z(15)))
            pygame.draw.ellipse(s, ol, (x + sx * Q(11) - Q(4), y - Q(8), Z(8), Z(15)), 2)
        pygame.draw.circle(s, col, (x, y), Z(12))
        pygame.draw.circle(s, ol, (x, y), Z(12), 2)
        pygame.draw.ellipse(s, acc, (x - Q(6), y + Q(1), Z(12), Z(9)))
        pygame.draw.circle(s, ol, (x, y + Q(3)), Z(2.2))
        for ex in (-Q(5), Q(5)):
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(3)), Z(2.8))
            pygame.draw.circle(s, ol, (x + ex + fx, y - Q(3)), Z(1.5))
        badge = [(x, y + Q(11)), (x - Q(3), y + Q(14)), (x, y + Q(18)), (x + Q(3), y + Q(14))]
        pygame.draw.polygon(s, BLUE, badge)
        pygame.draw.polygon(s, ol, badge, 1)

    elif pid == "dragon":
        flap = math.sin(t * 10) * Q(5)
        for sx in (-1, 1):
            wing = [(x + sx * Q(6), y - Q(3)), (x + sx * Q(21), y - Q(14) - flap), (x + sx * Q(17), y + Q(2)), (x + sx * Q(8), y + Q(4))]
            pygame.draw.polygon(s, acc, wing)
            pygame.draw.polygon(s, ol, wing, 2)
            horn = [(x + sx * Q(5), y - Q(9)), (x + sx * Q(8), y - Q(18)), (x + sx * Q(1), y - Q(11))]
            pygame.draw.polygon(s, WHITE, horn)
            pygame.draw.polygon(s, ol, horn, 1)
        tail = [(x - fx * Q(9), y + Q(5)), (x - fx * Q(17), y + Q(9) + int(math.sin(t * 6) * Q(2))), (x - fx * Q(21), y + Q(3))]
        pygame.draw.lines(s, ol, False, tail, max(2, Q(5)))
        pygame.draw.lines(s, col, False, tail, Z(3))
        pygame.draw.circle(s, col, (x, y), Z(11))
        pygame.draw.circle(s, ol, (x, y), Z(11), 2)
        pygame.draw.ellipse(s, acc, (x - Q(6) + fx * Q(3), y + Q(1), Z(12), Z(8)))
        for ex in (-Q(4), Q(4)):
            pygame.draw.circle(s, (255, 235, 90), (x + ex, y - Q(3)), Z(2.8))
            pygame.draw.circle(s, ol, (x + ex + fx, y - Q(3)), Z(1.4))
        puff = Z(3 + abs(math.sin(t * 8)) * 2)
        pygame.draw.circle(s, ORANGE, (x + fx * Q(14), y + Q(4)), puff)
        pygame.draw.circle(s, GOLD, (x + fx * Q(14), y + Q(4)), max(1, puff // 2))

    elif pid == "phoenix":
        fl = math.sin(t * 12)
        flap = math.sin(t * 8) * Q(4)
        for sx in (-1, 1):
            wing = [(x + sx * Q(7), y), (x + sx * Q(22), y - Q(10) - flap), (x + sx * Q(19), y + Q(1)),
                    (x + sx * Q(22), y + Q(8)), (x + sx * Q(8), y + Q(7))]
            pygame.draw.polygon(s, col, wing)
            pygame.draw.polygon(s, ol, wing, 2)
        tailf = [(x - Q(5), y + Q(8)), (x, y + Q(22) + int(fl * Q(2))), (x + Q(5), y + Q(8))]
        pygame.draw.polygon(s, ORANGE, tailf)
        flame = [(x - Q(8), y - Q(4)), (x - Q(5), y - Q(16) - int(fl * Q(2))), (x - Q(1), y - Q(8)),
                 (x, y - Q(20) + int(fl * Q(2))), (x + Q(2), y - Q(8)), (x + Q(6), y - Q(15) + int(fl * Q(2))), (x + Q(8), y - Q(4))]
        pygame.draw.polygon(s, ORANGE, flame)
        pygame.draw.polygon(s, GOLD, [(x - Q(3), y - Q(4)), (x, y - Q(13)), (x + Q(3), y - Q(4))])
        pygame.draw.circle(s, col, (x, y), Z(10))
        pygame.draw.circle(s, ol, (x, y), Z(10), 2)
        pygame.draw.ellipse(s, acc, (x - Q(5), y + Q(1), Z(10), Z(8)))
        for ex in (-Q(4), Q(4)):
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(2)), Z(2.6))
            pygame.draw.circle(s, ol, (x + ex + fx, y - Q(2)), Z(1.4))
        pygame.draw.polygon(s, GOLD, [(x - Q(2), y + Q(2)), (x + Q(2), y + Q(2)), (x, y + Q(6))])
    elif pid in ("drone", "seraph"):
        ang = t * 6.0
        for i in range(4):
            a = ang + i * (math.tau / 4)
            rx = x + int(math.cos(a) * Q(16))
            ry = y + int(math.sin(a) * Q(16))
            pygame.draw.line(s, acc, (x, y), (rx, ry), 2)
            pygame.draw.circle(s, col, (rx, ry), Z(4))
        pygame.draw.circle(s, col, (x, y), Z(11))
        pygame.draw.circle(s, ol, (x, y), Z(11), 2)
        pygame.draw.circle(s, WHITE, (x + fx * Q(2), y), Z(5))
        pygame.draw.circle(s, CYAN if pid == "drone" else GOLD, (x + fx * Q(3), y), Z(2.5))
    elif pid == "comet":
        tail_pts = [(x - fx * Q(6), y - Q(5)), (x - fx * Q(22), y + int(math.sin(t * 10) * Q(3))), (x - fx * Q(6), y + Q(5))]
        pygame.draw.polygon(s, CYAN, tail_pts)
        pygame.draw.polygon(s, WHITE, [(x - fx * Q(6), y - Q(2)), (x - fx * Q(15), y), (x - fx * Q(6), y + Q(2))])
        for i in range(3):
            a = t * 4.5 + i * (math.tau / 3)
            ox, oy = x + int(math.cos(a) * Q(16)), y + int(math.sin(a) * Q(16))
            pygame.draw.circle(s, acc, (ox, oy), Z(3.5))
        pygame.draw.circle(s, col, (x, y), Z(11))
        pygame.draw.circle(s, WHITE, (x, y), Z(11), 2)
        for ex in (-Q(4), Q(4)):
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(2)), Z(2.8))
            pygame.draw.circle(s, ol, (x + ex + fx, y - Q(2)), Z(1.4))
    elif pid == "voidling":
        for i in range(5):
            tx = x + (i - 2) * Q(4)
            ty = y + Q(10) + int(math.sin(t * 8 + i) * Q(3))
            pygame.draw.line(s, ol, (x + (i - 2) * Q(3), y + Q(5)), (tx, ty + Q(5)), max(2, Z(2.5)))
            pygame.draw.line(s, col, (x + (i - 2) * Q(3), y + Q(5)), (tx, ty + Q(5)), max(1, Z(1.5)))
        pygame.draw.circle(s, (35, 12, 65), (x, y), Z(12))
        pygame.draw.circle(s, col, (x, y), Z(12), 2)
        for ex in (-Q(5), Q(5)):
            pygame.draw.circle(s, CYAN, (x + ex, y - Q(1)), Z(2.8))
            pygame.draw.circle(s, WHITE, (x + ex, y - Q(1)), Z(1.2))
        pygame.draw.polygon(s, GOLD, [(x, y - Q(9)), (x - Q(3), y - Q(5)), (x, y - Q(3)), (x + Q(3), y - Q(5))])


class Pet:
    """Mascote que segue o jogador e ajuda na batalha."""

    def __init__(self, meta, player):
        self.meta = meta
        self.kind = meta["kind"]
        self.x = player.x - 40
        self.y = player.y - 40
        self.phase = random.random() * 6.0
        self.facing = 1
        self.cd = 1.0
        if self.kind == "wisdom":
            player.xp_bonus += 0.15
            player.magnet += 60

    def _nearest(self, game, rng):
        best, bd = None, rng * rng
        for e in game.enemies:
            if e.alive:
                d = (e.x - self.x) ** 2 + (e.y - self.y) ** 2
                if d < bd:
                    best, bd = e, d
        return best

    def update(self, dt, game):
        p = game.player
        col = self.meta["color"]
        self.phase += dt
        tx = p.x - 34 + math.cos(self.phase * 1.4) * 16
        ty = p.y - 38 + math.sin(self.phase * 2.2) * 9
        if math.hypot(tx - self.x, ty - self.y) > 700:
            self.x, self.y = tx, ty
        k = min(1.0, 7.0 * dt)
        nx = self.x + (tx - self.x) * k
        if abs(nx - self.x) > 0.25:
            self.facing = 1 if nx > self.x else -1
        self.x = nx
        self.y += (ty - self.y) * k

        kind = self.kind
        if kind == "wisdom":
            return
        if kind == "guardian":
            for e in game.enemies:
                if e.alive and (e.x - self.x) ** 2 + (e.y - self.y) ** 2 < (58 + e.r) ** 2:
                    e.hp -= 22 * dt * (0.5 if e.boss else 1.0)

        self.cd -= dt
        if self.cd > 0:
            return

        if kind == "shooter":
            t = self._nearest(game, 540)
            if t:
                nx_, ny_ = vec_norm(t.x - self.x, t.y - self.y)
                dmg = 9 + p.damage * 0.40 + game.level * 0.6
                game.bullets.append(Bullet(self.x, self.y, nx_ * 520, ny_ * 520, dmg, size=5, color=col))
                self.facing = 1 if nx_ >= 0 else -1
                self.cd = PET_COOLDOWN["shooter"]
            else:
                self.cd = 0.15

        elif kind == "lightning":
            targets = [e for e in game.enemies if e.alive and (e.x - self.x) ** 2 + (e.y - self.y) ** 2 < 400 ** 2]
            targets.sort(key=lambda e: (e.x - self.x) ** 2 + (e.y - self.y) ** 2)
            if targets:
                dmg = 20 + p.damage * 0.9 + game.level * 2
                for e in targets[:3]:
                    e.hp -= dmg * (0.5 if e.boss else 1.0)
                    e.hitflash = 0.12
                    game.lightnings.append(LightningBolt(self.x, self.y, e.x, e.y, col))
                    if game.settings["damage_numbers"]:
                        game.floating_texts.append(FloatingText(e.x, e.y - e.r, f"{int(dmg)}", col))
                    game.particles.extend(Particle(e.x, e.y, col, size=5) for _ in range(5))
                play_sound("zap")
                self.cd = PET_COOLDOWN["lightning"]
            else:
                self.cd = 0.2

        elif kind == "bomber":
            t = self._nearest(game, 620)
            if t:
                dmg = 38 + p.damage * 1.6 + game.level * 3
                game.lightnings.append(LightningBolt(self.x, self.y, t.x, t.y, ORANGE))
                game.shockwaves.append(Shockwave(t.x, t.y, 100, ORANGE, 0.38, 5))
                for e in game.enemies:
                    if e.alive and (e.x - t.x) ** 2 + (e.y - t.y) ** 2 < 100 ** 2:
                        e.hp -= dmg * (0.5 if e.boss else 1.0)
                        e.hitflash = 0.12
                game.particles.extend(Particle(t.x, t.y, ORANGE, size=6) for _ in range(14))
                game.camera_shake = max(game.camera_shake, 0.12)
                self.facing = 1 if t.x >= self.x else -1
                play_sound("zap")
                self.cd = PET_COOLDOWN["bomber"]
            else:
                self.cd = 0.25

        elif kind == "guardian":
            if p.shield < 40:
                p.shield = min(40, p.shield + 8)
                game.floating_texts.append(FloatingText(p.x, p.y - 30, "+8 ESCUDO", (90, 210, 255)))
                game.shockwaves.append(Shockwave(p.x, p.y, 54, col, 0.30, 3))
            self.cd = PET_COOLDOWN["guardian"]

        elif kind == "healer":
            if p.hp < p.maxhp:
                heal = p.maxhp * 0.06
                p.hp = min(p.maxhp, p.hp + heal)
                game.floating_texts.append(FloatingText(p.x, p.y - 30, f"+{int(heal)}", GREEN))
                game.particles.extend(Particle(p.x, p.y, GREEN, size=5) for _ in range(8))
                self.cd = PET_COOLDOWN["healer"]
            else:
                self.cd = 0.0

    def draw(self, s, cx, cy):
        sx, sy = int(self.x - cx), int(self.y - cy)
        if not (-60 < sx < W + 60 and -60 < sy < H + 60):
            return
        bob = int(math.sin(self.phase * 5) * 3)
        pygame.draw.ellipse(s, (4, 8, 18), (sx - 9, sy + 22, 18, 6))
        glow_circle(s, self.meta["color"], (sx, sy + bob), 12, 1)
        draw_pet_sprite(s, self.meta, sx, sy + bob, 1.0, self.phase, self.facing)


# ----------------------------------------------------------------------------
# CONTROLADOR PRINCIPAL DO JOGO, MOEDAS, LOJA E 3 SLOTS DE SAVE
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# REDE MULTIJOGADOR EM TEMPO REAL (SOCKET UDP) & ORBE PARCEIRO / RIVAL (CO-OP & PVP)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# REDE ONLINE (NUVEM): CLIENTE DO SERVIDOR RELAY  (veja blue_orb_relay_server.py)
# Dois jogadores se conectam ao MESMO servidor (TCP, saída), informam o código
# da sala e o servidor repassa os pacotes. Funciona pela Internet sem abrir porta.
# ----------------------------------------------------------------------------
import zlib
import struct

DEFAULT_RELAY = "127.0.0.1:45890"


def _pack_frame(b):
    return struct.pack(">I", len(b)) + b


class RelayLink:
    """Conexão TCP com o servidor relay. Duas threads (leitura/escrita) — o jogo nunca trava."""

    def __init__(self):
        self.state = "idle"       # idle | connecting | waiting | paired | error | closed
        self.err = ""
        self.role = None
        self.code = ""
        self.peer_present = False
        self.peer_name = ""
        self.host_gone = False
        self.rx = queue.Queue()
        self.tx = queue.Queue()
        self.bytes_tx = 0
        self.bytes_rx = 0
        self._gen = 0

    # ---- ciclo de vida ----
    def open(self, host, port, op, code, name):
        self.close()
        self._gen += 1
        gen = self._gen
        self.state, self.err = "connecting", ""
        self.peer_present, self.host_gone, self.peer_name = False, False, ""
        self.rx, self.tx = queue.Queue(), queue.Queue()
        threading.Thread(target=self._run, args=(gen, host, port, op, code, name, self.rx, self.tx), daemon=True).start()

    def close(self):
        if self.state in ("waiting", "paired", "connecting"):
            try:
                self.tx.put(_pack_frame(b"C" + json.dumps({"op": "bye"}).encode()))
                self.tx.put(None)
            except Exception:
                pass
        self._gen += 1
        self.state = "idle"
        self.peer_present = False
        self.role = None

    # ---- threads ----
    def _writer(self, gen, s, txq):
        while True:
            item = txq.get()
            if item is None or gen != self._gen:
                break
            try:
                s.sendall(item)
            except Exception as e:
                if gen == self._gen:
                    self.state, self.err = "error", f"envio falhou ({e})"
                break

    def _run(self, gen, host, port, op, code, name, rxq, txq):
        s = None
        try:
            s = socket.create_connection((host, port), timeout=6.0)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.sendall(_pack_frame(b"C" + json.dumps({"op": op, "code": code, "name": name, "v": 1}).encode()))
            s.settimeout(0.4)
            threading.Thread(target=self._writer, args=(gen, s, txq), daemon=True).start()
            buf = b""
            last_ka = time.time()
            while gen == self._gen:
                try:
                    chunk = s.recv(65536)
                    if not chunk:
                        raise ConnectionError("servidor encerrou a conexão")
                    buf += chunk
                    self.bytes_rx += len(chunk)
                except socket.timeout:
                    pass
                while len(buf) >= 4:
                    n = struct.unpack(">I", buf[:4])[0]
                    if n > (1 << 20):
                        raise ValueError("pacote inválido")
                    if len(buf) < 4 + n:
                        break
                    frame, buf = buf[4:4 + n], buf[4 + n:]
                    self._on_frame(gen, frame, rxq)
                if time.time() - last_ka > 3.0:
                    last_ka = time.time()
                    txq.put(_pack_frame(b"C" + json.dumps({"op": "ka"}).encode()))
        except Exception as e:
            if gen == self._gen and self.state not in ("idle", "closed"):
                self.state, self.err = "error", str(e) or e.__class__.__name__
        finally:
            try:
                txq.put(None)
            except Exception:
                pass
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    def _on_frame(self, gen, frame, rxq):
        if gen != self._gen or not frame:
            return
        kind = frame[:1]
        if kind == b"C":
            try:
                m = json.loads(frame[1:].decode("utf-8"))
            except Exception:
                return
            op = m.get("op")
            if op == "ok":
                self.role = m.get("role")
                self.code = m.get("code", self.code)
                self.peer_name = m.get("peer", "") or ""
                if self.role == "client":
                    self.peer_present, self.state = True, "paired"
                else:
                    self.state = "waiting"
            elif op == "err":
                self.state, self.err = "error", m.get("msg", "erro do servidor")
            elif op == "peer":
                if m.get("state") == "joined":
                    self.peer_present, self.state = True, "paired"
                    self.peer_name = m.get("name", "") or ""
                else:
                    self.peer_present = False
                    if m.get("host_gone"):
                        self.host_gone = True
                        self.state, self.err = "error", "o anfitrião encerrou a sala"
                    else:
                        self.state = "waiting"
        elif kind == b"G":
            try:
                obj = json.loads(zlib.decompress(frame[1:]).decode("utf-8"))
                rxq.put(obj)
            except Exception:
                pass

    # ---- envio ----
    def send(self, obj, droppable=False):
        if self.state not in ("waiting", "paired"):
            return False
        if droppable and self.tx.qsize() > 40:
            return False
        try:
            data = zlib.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"), 1)
        except Exception:
            return False
        self.bytes_tx += len(data) + 5
        self.tx.put(_pack_frame(b"G" + data))
        return True


class MultiplayerNetManager:
    """Salas por código via servidor relay (nuvem/LAN). Mantém a mesma interface usada pelo jogo."""

    def __init__(self):
        self.room_code = "ARENA-????"
        self.input_code = ""
        self.role = "host"
        self.connected_peer = False
        self.peer_addr = None
        self.sock = None
        self.status_msg = "Offline • Parceiro IA ativo (crie ou entre numa sala para jogar online)"
        self.last_packet_time = 0.0
        self.remote_state = {}
        self.link = RelayLink()
        self.server_text = os.environ.get("BLUE_ORB_SERVER", DEFAULT_RELAY)
        self.edit_server = False
        self.rtt_ms = 0.0
        self.player_name = "Orb"
        self._ping_t = 0.0
        self._rate_t = time.time()
        self._rate_prev = (0, 0)
        self.kbps_up = 0.0
        self.kbps_down = 0.0

    def parse_server(self):
        txt = (self.server_text or DEFAULT_RELAY).strip()
        if ":" in txt:
            host, port_s = txt.rsplit(":", 1)
        else:
            host, port_s = txt, "45890"
        try:
            port = int(port_s)
        except ValueError:
            port = 45890
        return (host.strip() or "127.0.0.1"), port

    def create_room(self):
        self.close()
        self.role = "host"
        host, port = self.parse_server()
        self.status_msg = f"Conectando a {host}:{port}…"
        self.link.open(host, port, "create", "", self.player_name)

    def join_room(self, code_str):
        clean = (code_str or "").strip().upper()
        if not clean:
            self.status_msg = "Digite o código da sala (ex.: ARENA-K7QZ) e clique em CONECTAR"
            return
        self.close()
        self.role = "client"
        self.room_code = clean
        host, port = self.parse_server()
        self.status_msg = f"Conectando a {host}:{port}…"
        self.link.open(host, port, "join", clean, self.player_name)

    def send(self, obj, droppable=False):
        return self.link.send(obj, droppable)

    def poll(self):
        """Chamado 1x por frame. Devolve as mensagens de jogo recebidas (já sem ping/pong)."""
        lk = self.link
        out = []
        try:
            while True:
                out.append(lk.rx.get_nowait())
        except queue.Empty:
            pass
        self.connected_peer = (lk.state == "paired" and lk.peer_present)
        if lk.code and lk.state in ("waiting", "paired"):
            self.room_code = lk.code
        now = time.perf_counter()
        if self.connected_peer and now - self._ping_t > 1.5:
            self._ping_t = now
            lk.send({"t": "ping", "ts": now}, droppable=True)
        msgs = []
        for m in out:
            t = m.get("t")
            self.last_packet_time = time.time()
            if t == "ping":
                lk.send({"t": "pong", "ts": m.get("ts", 0)}, droppable=True)
            elif t == "pong":
                rtt = (now - float(m.get("ts", now))) * 1000.0
                self.rtt_ms = rtt if self.rtt_ms <= 0 else self.rtt_ms * 0.7 + rtt * 0.3
            else:
                msgs.append(m)
        wall = time.time()
        if wall - self._rate_t >= 1.0:
            dt_r = wall - self._rate_t
            self.kbps_up = (lk.bytes_tx - self._rate_prev[0]) / dt_r / 1024.0
            self.kbps_down = (lk.bytes_rx - self._rate_prev[1]) / dt_r / 1024.0
            self._rate_prev = (lk.bytes_tx, lk.bytes_rx)
            self._rate_t = wall
        self._refresh_status()
        return msgs

    def _refresh_status(self):
        lk = self.link
        host, port = self.parse_server()
        if lk.state == "connecting":
            self.status_msg = f"Conectando a {host}:{port}…"
        elif lk.state == "waiting":
            self.status_msg = f"Sala {lk.code} aberta • compartilhe o código • aguardando parceiro"
        elif lk.state == "paired":
            self.status_msg = f"ONLINE • sala {lk.code} • ping {int(self.rtt_ms)} ms"
        elif lk.state == "error":
            self.status_msg = f"Falha: {lk.err} — jogando offline com IA"
        elif lk.state == "idle":
            self.status_msg = "Offline • Parceiro IA ativo (crie ou entre numa sala para jogar online)"

    def sync_step(self, game):
        """Compatibilidade: a rede agora roda em Game.net_tick (1x por frame)."""
        return

    def close(self):
        self.link.close()
        self.connected_peer = False
        self.remote_state = {}
        self.rtt_ms = 0.0
        self._refresh_status()


class PartnerOrb:
    """Segundo Orbe na Arena: atua como Parceiro Co-op (com reanimação) ou Rival no Duelo PvP 1v1."""
    def __init__(self, x, y, skin_id="emerald", pet_id="cat", mode="coop", level=1):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.r = 15
        self.skin_id = skin_id
        self.pet_id = pet_id
        self.mode = mode
        self.alive = True
        self.downed = False
        self.revive_progress = 0.0
        self.maxhp = 140.0 if mode == "coop" else 220.0
        self.hp = self.maxhp
        self.ghost_hp = self.maxhp
        self.shield = 25.0
        self.damage = 19.0 + level * 2.2
        self.fire_rate = 3.4 if mode == "coop" else 3.1
        self.bullet_speed = 540.0
        self.move_speed = 248.0
        self.shots = 2 if level >= 5 else 1
        self.last_shot = 0.0
        self.dash_cd = 0.0
        self.dash_time = 0.0
        self.dash_vx = 0.0
        self.dash_vy = 0.0
        self.ult_charge = 0.0
        self.invuln = 0.0
        self.flash = 0.0
        self.trail = []
        self.strafe_dir = 1
        self.strafe_timer = 1.5
        self.name = "PARCEIRO ORB" if mode == "coop" else "RIVAL ORB"
        self.pet_phase = random.random() * math.tau
        self.remote = False
        self.slowfield = False

    def trigger_ultimate(self, game):
        if self.ult_charge < 100.0 or self.downed:
            return
        sc = game.get_skin_colors(self.skin_id)
        skin_meta = game.get_selected_skin_meta(self.skin_id)
        ult_name = skin_meta.get("ult_name", "SUPREMO")
        ult_style = skin_meta.get("ult_style", "plasma")
        self.ult_charge = 0.0
        self.invuln = 1.5
        game.camera_shake = max(game.camera_shake, 0.85)
        ult_dmg = 135 + self.damage * 3.8 + game.level * 10
        hit_positions = []

        if self.mode == "coop":
            game.bullets = [b for b in game.bullets if not b.enemy]
            for en in game.enemies:
                if en.alive and math.hypot(en.x - self.x, en.y - self.y) < 460:
                    en.hp -= ult_dmg * (0.45 if en.boss else 1.0)
                    en.hitflash = 0.22
                    hit_positions.append((en.x, en.y))
                    game.lightnings.append(LightningBolt(self.x, self.y, en.x, en.y, sc["bullet"]))
            if game.player.downed and math.hypot(game.player.x - self.x, game.player.y - self.y) < 460:
                game.player.downed = False
                game.player.revive_progress = 0.0
                game.player.hp = game.player.maxhp * 0.55
                game.floating_texts.append(FloatingText(game.player.x, game.player.y - 28, "REANIMADO PELO SUPREMO ALIADO!", GREEN, crit=True))
        else:
            game.bullets = [b for b in game.bullets if b.owner != "p1"]
            if math.hypot(game.player.x - self.x, game.player.y - self.y) < 430:
                game.player.take_damage(ult_dmg * 0.26, game)
                hit_positions.append((game.player.x, game.player.y))
                game.lightnings.append(LightningBolt(self.x, self.y, game.player.x, game.player.y, sc["bullet"]))

        game.shockwaves.append(Shockwave(self.x, self.y, 440, sc["bullet"], 0.60, 5))
        game.ult_visuals.append(UltimateEffectVisual(self.x, self.y, ult_style, sc["bullet"], hit_positions))
        game.floating_texts.append(FloatingText(self.x, self.y - 30, f"{ult_name}!", sc["bullet"], crit=True))
        play_sound("ultimate")

    def take_damage(self, amount, game):
        if self.remote:
            return self.remote_damage(amount, game)
        if self.invuln > 0 or self.dash_time > 0 or self.downed:
            return
        absorbed = min(self.shield, amount)
        self.shield -= absorbed
        rem = amount - absorbed
        if rem > 0:
            self.hp -= rem
            game.floating_texts.append(FloatingText(self.x, self.y - 14, f"-{int(rem)}", ORANGE if self.mode == "coop" else GOLD))
        self.invuln = 0.42
        self.flash = 0.25
        game.particles.extend(Particle(self.x, self.y, RED) for _ in range(10))
        play_sound("hit")
        if self.hp <= 0:
            if self.mode == "coop":
                if game.player.downed:
                    game.record_highscore()
                    game.player.downed = False
                    game.player.hp = game.player.maxhp
                    game.save_game(game.current_slot)
                    game.state = "gameover"
                else:
                    self.hp = 1.0
                    self.downed = True
                    self.revive_progress = 0.0
                    game.shockwaves.append(Shockwave(self.x, self.y, 130, ORANGE, 0.4, 3))
                    game.floating_texts.append(FloatingText(self.x, self.y - 26, "PARCEIRO CAÍDO! APROXIME-SE PARA REANIMAR!", ORANGE, crit=True))
            else:
                game.handle_pvp_round_end(winner="p1")

    def update(self, dt, game):
        sc = game.get_skin_colors(self.skin_id)
        self.invuln = max(0.0, self.invuln - dt)
        self.flash = max(0.0, self.flash - dt)
        self.dash_cd = max(0.0, self.dash_cd - dt)
        self.pet_phase += dt * 4.2
        if self.ghost_hp > self.hp:
            self.ghost_hp = max(self.hp, self.ghost_hp - (self.ghost_hp - self.hp) * 4.2 * dt - 6.0 * dt)
        else:
            self.ghost_hp = float(self.hp)

        if self.remote:
            self.remote_update(dt, game)
            return

        if self.downed:
            self.vx *= max(0.0, 1.0 - 10.0 * dt)
            self.vy *= max(0.0, 1.0 - 10.0 * dt)
            if not game.player.downed:
                d_p1 = math.hypot(game.player.x - self.x, game.player.y - self.y)
                if d_p1 < 110:
                    self.revive_progress += dt / 2.4
                    if self.revive_progress >= 1.0:
                        self.downed = False
                        self.revive_progress = 0.0
                        self.hp = self.maxhp * 0.60
                        self.shield = 20.0
                        self.invuln = 2.0
                        game.shockwaves.append(Shockwave(self.x, self.y, 180, GREEN, 0.45, 4))
                        game.floating_texts.append(FloatingText(self.x, self.y - 26, "PARCEIRO REANIMADO!", GREEN, crit=True))
                        play_sound("heal")
            return

        self.hp = min(self.maxhp, self.hp + (1.4 if self.mode == "coop" else 0.6) * dt)
        self.ult_charge = min(100.0, self.ult_charge + dt * (4.2 if self.mode == "coop" else 5.5))
        if self.ult_charge >= 100.0:
            if self.mode == "coop" and len(game.enemies) >= 4:
                self.trigger_ultimate(game)
            elif self.mode == "pvp" and math.hypot(game.player.x - self.x, game.player.y - self.y) < 400:
                self.trigger_ultimate(game)

        self.strafe_timer -= dt
        if self.strafe_timer <= 0:
            self.strafe_timer = random.uniform(1.0, 2.2)
            self.strafe_dir = -self.strafe_dir

        nx, ny = 0.0, 0.0
        target_shoot = None

        if self.mode == "coop":
            if game.player.downed:
                dx_p, dy_p = game.player.x - self.x, game.player.y - self.y
                dist_p = math.hypot(dx_p, dy_p)
                if dist_p > 45:
                    nx, ny = vec_norm(dx_p, dy_p)
            else:
                dx_p, dy_p = game.player.x - self.x, game.player.y - self.y
                dist_p = math.hypot(dx_p, dy_p)
                alive_e = [e for e in game.enemies if e.alive]
                nearest_e = min(alive_e, key=lambda e: (e.x - self.x) ** 2 + (e.y - self.y) ** 2) if alive_e else None

                if dist_p > 340:
                    nx, ny = vec_norm(dx_p, dy_p)
                elif nearest_e:
                    de = math.hypot(nearest_e.x - self.x, nearest_e.y - self.y)
                    ex_n, ey_n = vec_norm(nearest_e.x - self.x, nearest_e.y - self.y)
                    if de < 165:
                        nx, ny = -ex_n, -ey_n
                    elif de > 280:
                        nx, ny = ex_n, ey_n
                    else:
                        nx, ny = -ey_n * self.strafe_dir, ex_n * self.strafe_dir
                    if de < 650:
                        target_shoot = (nearest_e.x, nearest_e.y)
                elif dist_p > 120:
                    nx, ny = vec_norm(dx_p, dy_p)

                for o in game.orbs[:]:
                    if math.hypot(o.x - self.x, o.y - self.y) < self.r + 18:
                        if o.kind == "heal":
                            self.hp = min(self.maxhp, self.hp + o.value)
                        elif o.kind == "coin":
                            game.gain_coins(max(1, int(o.value)))
                        else:
                            game.gain_xp(o.value)
                        if o in game.orbs:
                            game.orbs.remove(o)
        else:
            dx_p, dy_p = game.player.x - self.x, game.player.y - self.y
            dist_p = math.hypot(dx_p, dy_p)
            px_n, py_n = vec_norm(dx_p, dy_p)

            heal_orbs = [o for o in game.orbs if o.kind == "heal"]
            if self.hp < self.maxhp * 0.65 and heal_orbs:
                ho = min(heal_orbs, key=lambda o: (o.x - self.x) ** 2 + (o.y - self.y) ** 2)
                nx, ny = vec_norm(ho.x - self.x, ho.y - self.y)
            else:
                if dist_p > 320:
                    nx, ny = px_n * 0.8 - py_n * 0.5 * self.strafe_dir, py_n * 0.8 + px_n * 0.5 * self.strafe_dir
                elif dist_p < 190:
                    nx, ny = -px_n * 0.85 - py_n * 0.5 * self.strafe_dir, -py_n * 0.85 + px_n * 0.5 * self.strafe_dir
                else:
                    nx, ny = -py_n * self.strafe_dir, px_n * self.strafe_dir
                nx, ny = vec_norm(nx, ny)

            if self.dash_cd <= 0:
                for b in game.bullets:
                    if b.owner == "p1" and math.hypot(b.x - self.x, b.y - self.y) < 135:
                        bnx, bny = vec_norm(b.vx, b.vy)
                        self.dash_time = 0.16
                        self.dash_cd = 3.0
                        self.dash_vx = -bny * self.strafe_dir * 860
                        self.dash_vy = bnx * self.strafe_dir * 860
                        game.shockwaves.append(Shockwave(self.x, self.y, 44, sc["bullet"], 0.20, 2))
                        play_sound("dash")
                        break

            for o in game.orbs[:]:
                if math.hypot(o.x - self.x, o.y - self.y) < self.r + 18:
                    if o.kind == "heal":
                        self.hp = min(self.maxhp, self.hp + o.value)
                        game.floating_texts.append(FloatingText(self.x, self.y, f"+{int(o.value)} HP", GREEN))
                    else:
                        self.ult_charge = min(100.0, self.ult_charge + 18.0)
                    game.orbs.remove(o)

            lead_t = min(0.45, dist_p / max(1.0, self.bullet_speed))
            target_shoot = (game.player.x + game.player.vx * lead_t, game.player.y + game.player.vy * lead_t)

        if self.dash_time > 0:
            self.dash_time -= dt
            self.x += self.dash_vx * dt
            self.y += self.dash_vy * dt
        else:
            self.vx += (nx * self.move_speed - self.vx) * min(1.0, 11.0 * dt)
            self.vy += (ny * self.move_speed - self.vy) * min(1.0, 11.0 * dt)
            self.x += self.vx * dt
            self.y += self.vy * dt

        self.x = clamp(self.x, 36, game.world_w - 36)
        self.y = clamp(self.y, 36, game.world_h - 36)
        self.trail.append((self.x, self.y, 0.25, self.dash_time > 0))
        self.trail = [(x, y, t - dt, d) for x, y, t, d in self.trail if t > dt]

        if target_shoot and (game.elapsed - self.last_shot >= 1.0 / self.fire_rate):
            self.last_shot = game.elapsed
            snx, sny = vec_norm(target_shoot[0] - self.x, target_shoot[1] - self.y)
            if snx != 0 or sny != 0:
                shots = self.shots if self.mode == "coop" else 1
                spread = 0.14
                b_owner = "p2_coop" if self.mode == "coop" else "p2"
                for i in range(shots):
                    off = (i - (shots - 1) / 2) * spread
                    ang = math.atan2(sny, snx) + off
                    game.bullets.append(Bullet(
                        self.x, self.y,
                        math.cos(ang) * self.bullet_speed,
                        math.sin(ang) * self.bullet_speed,
                        self.damage * (0.75 if self.mode == "pvp" else 0.90),
                        enemy=False,
                        size=7,
                        color=sc["bullet"],
                        owner=b_owner
                    ))

    def draw(self, s, cx, cy, game):
        px, py = int(self.x - cx), int(self.y - cy)
        if not (-80 < px < W + 80 and -80 < py < H + 80):
            return
        sc = game.get_skin_colors(self.skin_id)

        trail_pts = [(int(x - cx), int(y - cy), t, is_d) for x, y, t, is_d in self.trail]
        for idx_t in range(len(trail_pts)):
            tx_p, ty_p, t_p, is_d = trail_pts[idx_t]
            col = sc["bullet"] if is_d else sc["trail"]
            rad = max(2, int((12 if is_d else 7) * t_p / 0.25))
            if idx_t > 0:
                px_prev, py_prev, _, _ = trail_pts[idx_t - 1]
                pygame.draw.line(s, col, (px_prev, py_prev), (tx_p, ty_p), max(2, rad * 2))
            pygame.draw.circle(s, col, (tx_p, ty_p), rad)

        is_moving = math.hypot(self.vx, self.vy) > 15
        glow_c = (ORANGE if self.downed else sc["glow"])
        py_anim = draw_orb_character(
            s, (px, py), self.r, sc["body"], sc["shoe"], glow_c,
            game.elapsed + 1.5, is_moving, flash=self.flash > 0, legs=True, face=True, scale=1.0
        )

        if self.shield > 0 and not self.downed:
            sh_r = self.r + 12
            hex_pts = [(px + math.cos(game.elapsed * 2.2 + k * math.tau / 6) * sh_r,
                        py_anim + math.sin(game.elapsed * 2.2 + k * math.tau / 6) * sh_r) for k in range(6)]
            pygame.draw.polygon(s, sc["bullet"], hex_pts, 2)

        pet_meta = next((pt for pt in PETS if pt["id"] == self.pet_id), PETS[0])
        pet_x = px + int(math.cos(self.pet_phase * 0.5) * 32)
        pet_y = py_anim - 28 + int(math.sin(self.pet_phase) * 4)
        draw_pet_sprite(s, pet_meta, pet_x, pet_y, 0.85, self.pet_phase, 1)

        tag_col = GREEN if self.mode == "coop" else RED
        draw_text(s, self.name, TINY, tag_col, (px, py_anim - 34), True)
        bw = 42
        pygame.draw.rect(s, (18, 24, 42), (px - bw // 2, py_anim - 24, bw, 5), border_radius=2)
        pygame.draw.rect(s, tag_col, (px - bw // 2, py_anim - 24, int(bw * clamp(self.hp / self.maxhp, 0.0, 1.0)), 5), border_radius=2)

        if self.downed:
            pygame.draw.circle(s, ORANGE, (px, py), 110, 2)
            if self.revive_progress > 0:
                arc_r = pygame.Rect(px - 34, py - 34, 68, 68)
                pygame.draw.arc(s, GREEN, arc_r, -math.pi / 2, -math.pi / 2 + self.revive_progress * math.tau, 5)
            draw_text(s, f"REANIMAR PARCEIRO ({int(self.revive_progress * 100)}%)", SMALL, GREEN, (px, py - 48), True)


class Game:
    kb_idx = -1
    settings_back = None
    bestiary_tab = "enemies"

    def __init__(self):
        self.world_w = 2400
        self.world_h = 1800
        self.settings = {
            "shake": True,
            "flashes": True,
            "effects": True,
            "damage_numbers": True,
            "volume": 0.5,
            "show_hitboxes": False,
            "smart_auto_aim": True,
            "quality": (1 if MOBILE else 2),
            "reduce_flash": False,
            "compact_hud": bool(MOBILE),
            "language": "pt"
        }
        self.cards_page = 0
        self.auto_fire = bool(MOBILE)
        self.touch_mode = bool(MOBILE)
        self.touch_left_vec = (0.0, 0.0)
        self.touch_right_vec = (0.0, 0.0)
        self.touch_ui_captured = False
        self.current_slot = 1
        self.game_mode = "solo"
        self.partner_skin_idx = 1
        self.partner_pet_idx = 1
        self.partner = None
        self.pvp_round = 1
        self.pvp_p1_wins = 0
        self.pvp_p2_wins = 0
        self.pvp_orb_timer = 0.0
        self.pvp_banner_text = ""
        self.pvp_banner_timer = 0.0
        self.net = MultiplayerNetManager()
        self.cloud_sync_timer = 0.0
        self.cloud_status_text = "SINCRONIZADO (NUVEM + CACHE LOCAL)"
        self.autosave_timer = 0.0
        self.save_indicator_timer = 0.0
        self.hit_stop = 0.0
        self.slowmo = 0.0
        self._eg = {}
        self._emr = 30
        self._last_side = -1
        self.achievement_banners = []
        self.highscores = self.load_highscores()
        self.profile = self.load_profile()
        self.net.server_text = self.profile.get("relay_server", self.net.server_text)
        self.net.player_name = str(self.profile.get("player_name", "Orb"))[:12]
        global LANG_CUR
        LANG_CUR = self.profile.get("language", "pt")
        self.settings["language"] = LANG_CUR
        self.purge_slot1_level30()
        self.sync_unlocks_from_progress()
        self.sync_cloud_backup(silent=True)
        self.reset()
        self.state = "menu"

    def get_slot_filename(self, slot=None):
        s = slot if slot is not None else self.current_slot
        return os.path.join(SAVE_DIR, f"save_slot_{s}.json")

    def get_highscores_filename(self):
        return os.path.join(SAVE_DIR, "highscores.json")

    def get_profile_filename(self):
        return os.path.join(SAVE_DIR, "profile.json")

    def get_recovery_marker_filename(self):
        return os.path.join(SAVE_DIR, ".lvl30_restored.flag")

    def load_profile(self):
        data = safe_read_json(self.get_profile_filename())
        if isinstance(data, dict):
            data.setdefault("selected_skin", "classic")
            data.setdefault("unlocked_skins", ["classic"])
            data.setdefault("achievements", [])
            data.setdefault("coins", 250)
            data.setdefault("upgrades", {"dmg": 0, "hp": 0, "spd": 0, "mag": 0, "greed": 0})
            data.setdefault("unlocked_pets", ["slime"])
            data.setdefault("selected_pet", "slime")
            data.setdefault("language", "pt")
            return data
        return {
            "selected_skin": "classic",
            "unlocked_pets": ["slime"],
            "selected_pet": "slime",
            "language": "pt",
            "unlocked_skins": ["classic"],
            "achievements": [],
            "coins": 250,
            "upgrades": {"dmg": 0, "hp": 0, "spd": 0, "mag": 0, "greed": 0}
        }

    def save_profile(self):
        safe_write_json(self.get_profile_filename(), self.profile)
        self.sync_cloud_backup(silent=True)

    def sync_cloud_backup(self, silent=False):
        """Sincroniza Perfil, Moedas, Skins, Pets e Recordes com o Cofre de Nuvem/Backup Híbrido."""
        cloud_fp = os.path.join(SAVE_DIR, "cloud_sync_backup.json")
        existing = safe_read_json(cloud_fp)
        if isinstance(existing, dict):
            for sk_id in existing.get("unlocked_skins", []):
                if sk_id not in self.profile["unlocked_skins"]:
                    self.profile["unlocked_skins"].append(sk_id)
            for pt_id in existing.get("unlocked_pets", []):
                if pt_id not in self.profile["unlocked_pets"]:
                    self.profile["unlocked_pets"].append(pt_id)
            for ach_id in existing.get("achievements", []):
                if ach_id not in self.profile["achievements"]:
                    self.profile["achievements"].append(ach_id)
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "room_code": self.net.room_code if hasattr(self, "net") else "ORB-01",
            "coins": self.profile.get("coins", 0),
            "selected_skin": self.profile.get("selected_skin", "classic"),
            "selected_pet": self.profile.get("selected_pet", "slime"),
            "unlocked_skins": self.profile.get("unlocked_skins", ["classic"]),
            "unlocked_pets": self.profile.get("unlocked_pets", ["slime"]),
            "achievements": self.profile.get("achievements", []),
            "upgrades": self.profile.get("upgrades", {}),
            "highscores": self.highscores,
        }
        safe_write_json(cloud_fp, payload)
        self.cloud_status_text = f"SINCRONIZADO ({time.strftime('%H:%M')}) • OFFLINE & NUVEM OK"
        if not silent:
            self.save_indicator_timer = 2.2
            play_sound("select")

    def gain_coins(self, amount):
        if amount <= 0:
            return
        self.run_coins += amount
        self.profile["coins"] = self.profile.get("coins", 0) + amount
        self.save_profile()
        if self.profile["coins"] >= 500:
            self.unlock_achievement("coins_500")

    def get_selected_skin_meta(self, skin_id=None):
        sid = skin_id or self.profile.get("selected_skin", "classic")
        return next((sk for sk in SKINS if sk["id"] == sid), SKINS[0])

    def get_skin_colors(self, skin_id=None):
        skin = self.get_selected_skin_meta(skin_id)
        if skin.get("rainbow"):
            t = pygame.time.get_ticks() * 0.00045
            r1, g1, b1 = [int(c * 255) for c in colorsys.hsv_to_rgb(t % 1.0, 0.85, 1.0)]
            r2, g2, b2 = [int(c * 255) for c in colorsys.hsv_to_rgb((t + 0.12) % 1.0, 0.90, 0.85)]
            r3, g3, b3 = [int(c * 255) for c in colorsys.hsv_to_rgb((t + 0.25) % 1.0, 0.75, 1.0)]
            return {
                "body": (r1, g1, b1),
                "glow": (r2, g2, b2),
                "shoe": (max(20, r2 - 30), max(20, g2 - 30), max(20, b2 - 30)),
                "bullet": (r3, g3, b3),
                "trail": (r2, g2, b2)
            }
        return skin

    def unlock_achievement(self, ach_id, silent=False):
        if ach_id in self.profile["achievements"]:
            return
        self.profile["achievements"].append(ach_id)
        ach_obj = next((a for a in ACHIEVEMENTS if a["id"] == ach_id), None)
        if ach_id == "coins_500":
            self.profile["coins"] = self.profile.get("coins", 0) + 100
        for sk in SKINS:
            if sk.get("req_ach") == ach_id and sk["id"] not in self.profile["unlocked_skins"]:
                self.profile["unlocked_skins"].append(sk["id"])
        self.save_profile()
        if ach_obj and not silent:
            self.achievement_banners.append({
                "title": f"CONQUISTA: {ach_obj['name'].upper()}",
                "sub": f"Recompensa: {ach_obj['reward']}",
                "timer": 4.2
            })
            play_sound("achievement")

    def sync_unlocks_from_progress(self):
        """Desbloqueia retroativamente conquistas e cores com base nos recordes e slots salvos."""
        max_lvl = self.highscores.get("max_level", 1)
        max_kills = self.highscores.get("max_kills", 0)
        max_combo = self.highscores.get("max_combo", 0)
        max_time = self.highscores.get("max_time", 0)
        max_bosses = 0
        for sl in (1, 2, 3):
            inf = self.get_slot_info(sl)
            if inf:
                max_lvl = max(max_lvl, inf.get("level", 1))
                max_kills = max(max_kills, inf.get("kills", 0))
                max_combo = max(max_combo, inf.get("max_combo", 0))
                max_time = max(max_time, int(inf.get("elapsed", 0)))
                max_bosses = max(max_bosses, inf.get("bosses", 0))

        if max_kills >= 50:
            self.unlock_achievement("kills_50", silent=True)
        if max_combo >= 25:
            self.unlock_achievement("combo_25", silent=True)
        if max_bosses >= 1:
            self.unlock_achievement("boss_1", silent=True)
        if max_lvl >= 15:
            self.unlock_achievement("lvl_15", silent=True)
        if max_kills >= 200:
            self.unlock_achievement("kills_200", silent=True)
        if max_time >= 300:
            self.unlock_achievement("time_300", silent=True)
        if max_lvl >= 30:
            self.unlock_achievement("lvl_30", silent=True)
        if self.profile.get("coins", 0) >= 500:
            self.unlock_achievement("coins_500", silent=True)

    def check_live_achievements(self):
        if self.kills >= 50:
            self.unlock_achievement("kills_50")
        if self.kills >= 200:
            self.unlock_achievement("kills_200")
        if self.combo >= 25 or self.max_combo >= 25:
            self.unlock_achievement("combo_25")
        if self.bosses >= 1:
            self.unlock_achievement("boss_1")
        if self.level >= 15:
            self.unlock_achievement("lvl_15")
        if self.level >= 30:
            self.unlock_achievement("lvl_30")
        if self.elapsed >= 300:
            self.unlock_achievement("time_300")
        if self.profile.get("coins", 0) >= 500:
            self.unlock_achievement("coins_500")

    def purge_slot1_level30(self):
        """Apaga (uma única vez) o save do Slot 1 de Nível 30+ e desativa a antiga restauração automática do Nível 30."""
        purge_flag = os.path.join(SAVE_DIR, ".slot1_lvl30_purged.flag")
        if os.path.exists(purge_flag):
            return
        try:
            data = safe_read_json(self.get_slot_filename(1))
            if isinstance(data, dict) and data.get("level", 0) >= 30:
                self.delete_save(1)
                print("[SAVE] Slot 1 (Nível 30) apagado.")
            old_marker = self.get_recovery_marker_filename()
            if os.path.exists(old_marker):
                os.remove(old_marker)
        except Exception as e:
            print(f"[ERRO AO APAGAR SLOT 1]: {e}")
        try:
            with open(purge_flag, "w", encoding="utf-8") as pf:
                pf.write("done")
        except Exception:
            pass

    def get_slot_info(self, slot):
        return safe_read_json(self.get_slot_filename(slot))

    def reset(self):
        self.player = Player(self.profile.get("upgrades", {}))
        self.pet = None
        pet_meta = next((pt for pt in PETS if pt["id"] == self.profile.get("selected_pet")), None)
        if pet_meta and pet_meta["id"] in self.profile.get("unlocked_pets", []):
            self.pet = Pet(pet_meta, self.player)
        self.enemies = []
        self.bullets = []
        self.orbs = []
        self.chests = []
        self.particles = []
        self.floating_texts = []
        self.shockwaves = []
        self.ult_visuals = []
        self.lightnings = []
        self.blackholes = []
        self.level = 1
        self.xp = 0
        self.xp_need = xp_required(1)
        self.elapsed = 0
        self.kills = 0
        self.bosses = 0
        self.run_coins = 0
        self.combo = 0
        self.max_combo = 0
        self.combo_timer = 0.0
        self.spawn_timer = 0
        self.phase_event_timer = random.uniform(28.0, 38.0)
        self.phase_event_active = None  # None | "xp_rain" | "enemy_rain" | "mixed_storm"
        self.phase_event_ttl = 0.0
        self.phase_event_cd_xp = 0.0
        self.phase_event_cd_en = 0.0
        self.phase_event_banner = 0.0
        self.phase_event_label = ""
        self.phase_event_total = 0.0
        self.boss_active = False
        self.cards = []
        self.camera_shake = 0
        self.cam_x = self.player.x - W / 2
        self.cam_y = self.player.y - H / 2
        self.boss_index = 0
        self.boss_queued = False
        self.last_level_boss = 0
        self.boss_banner_timer = 0.0
        self.autosave_timer = 0.0
        self.hit_stop = 0.0
        self.slowmo = 0.0
        self._eg = {}
        self._emr = 30
        self.pvp_orb_timer = 0.0
        if getattr(self, "game_mode", "solo") in ("coop", "pvp"):
            sk_id = SKINS[self.partner_skin_idx % len(SKINS)]["id"]
            pt_id = PETS[self.partner_pet_idx % len(PETS)]["id"]
            px_start = self.player.x + (110 if self.game_mode == "coop" else 420)
            py_start = self.player.y
            self.partner = PartnerOrb(px_start, py_start, sk_id, pt_id, self.game_mode, self.level)
            if self.game_mode == "pvp":
                self.player.x = self.world_w / 2 - 260
                self.player.y = self.world_h / 2
                self.partner.x = self.world_w / 2 + 260
                self.partner.y = self.world_h / 2
        else:
            self.partner = None
        self.state = "playing"

    def start_multiplayer_match(self, mode, online=None, role=None):
        if online is None:
            online = bool(self.net.connected_peer)
        if online and self.net.role == "client":
            self.net_toast("Aguarde: o ANFITRIÃO inicia a partida", 3.0)
            return
        self.game_mode = mode
        self.online = bool(online)
        self.online_role = "host"
        self.pvp_round = 1
        self.pvp_p1_wins = 0
        self.pvp_p2_wins = 0
        self._net_start_flag = True
        self.reset()
        self._net_start_flag = False
        if self.online:
            self.net_send_start()
        tag = "ONLINE " if self.online else ""
        if mode == "pvp":
            self.pvp_banner_text = f"DUELO PVP 1V1 {tag}— RODADA 1!"
        else:
            self.pvp_banner_text = f"MODO CO-OP {tag}ATIVO — SALA {self.net.room_code}"
        self.pvp_banner_timer = 2.8
        play_sound("levelup")

    def handle_pvp_round_end(self, winner="p1"):
        if winner == "p1":
            self.pvp_p1_wins += 1
            reward_c = 45
            self.gain_coins(reward_c)
            self.pvp_banner_text = f"VOCÊ VENCEU A RODADA {self.pvp_round}! (+{reward_c} $)"
            play_sound("achievement")
        else:
            self.pvp_p2_wins += 1
            self.pvp_banner_text = f"RIVAL VENCEU A RODADA {self.pvp_round}!"
            play_sound("boss")

        self.pvp_banner_timer = 3.2
        if self.pvp_p1_wins >= 2 or self.pvp_p2_wins >= 2:
            if self.pvp_p1_wins > self.pvp_p2_wins:
                self.gain_coins(80)
                self.pvp_banner_text = f"CAMPEÃO DO DUELO PVP ({self.pvp_p1_wins}x{self.pvp_p2_wins})! +80 MOEDAS!"
            else:
                self.pvp_banner_text = f"FIM DO DUELO PVP ({self.pvp_p1_wins}x{self.pvp_p2_wins}) — NOVA SÉRIE!"
            self.pvp_p1_wins = 0
            self.pvp_p2_wins = 0
            self.pvp_round = 1
        else:
            self.pvp_round += 1

        self.bullets.clear()
        self.orbs.clear()
        self.player.hp = self.player.maxhp
        self.player.shield = 25
        self.player.invuln = 1.8
        self.player.x = self.world_w / 2 - 260
        self.player.y = self.world_h / 2
        if self.partner:
            self.partner.hp = self.partner.maxhp
            self.partner.shield = 25
            self.partner.invuln = 1.8
            self.partner.x = self.world_w / 2 + 260
            self.partner.y = self.world_h / 2
        self.shockwaves.append(Shockwave(self.world_w / 2, self.world_h / 2, 320, GOLD, 0.55, 5))

    def load_highscores(self):
        data = safe_read_json(self.get_highscores_filename())
        if isinstance(data, dict):
            return data
        return {"max_level": 1, "max_kills": 0, "max_time": 0, "max_combo": 0}

    def record_highscore(self):
        changed = False
        if self.level > self.highscores.get("max_level", 1):
            self.highscores["max_level"] = self.level
            changed = True
        if self.kills > self.highscores.get("max_kills", 0):
            self.highscores["max_kills"] = self.kills
            changed = True
        if int(self.elapsed) > self.highscores.get("max_time", 0):
            self.highscores["max_time"] = int(self.elapsed)
            changed = True
        if self.max_combo > self.highscores.get("max_combo", 0):
            self.highscores["max_combo"] = self.max_combo
            changed = True
        if changed:
            safe_write_json(self.get_highscores_filename(), self.highscores)
        self.check_live_achievements()

    def save_game(self, slot=None):
        target_slot = slot if slot is not None else self.current_slot
        self.record_highscore()
        self.save_profile()
        data = {
            "slot": target_slot,
            "level": self.level,
            "xp": self.xp,
            "pending_levelup": (self.state == "levelup"),
            "elapsed": self.elapsed,
            "kills": self.kills,
            "bosses": self.bosses,
            "run_coins": self.run_coins,
            "combo": self.combo,
            "max_combo": self.max_combo,
            "last_level_boss": self.last_level_boss,
            "boss_queued": self.boss_queued,
            "player_x": self.player.x,
            "player_y": self.player.y,
            "hp": max(1, self.player.hp),
            "maxhp": self.player.maxhp,
            "shield": self.player.shield,
            "rerolls": self.player.rerolls,
            "last_chance": self.player.last_chance,
            "dash_cd": self.player.dash_cd,
            "since_survival": self.player.since_survival,
            "ult_charge": self.player.ult_charge,
            "acquired": self.player.acquired
        }
        if safe_write_json(self.get_slot_filename(target_slot), data):
            self.save_indicator_timer = 1.8

    def load_game(self, slot=None):
        target_slot = slot if slot is not None else self.current_slot
        self.current_slot = target_slot
        data = safe_read_json(self.get_slot_filename(target_slot))
        if not data:
            return False
        try:
            self.reset()
            self.current_slot = target_slot
            self.level = data.get("level", 1)
            self.xp = data.get("xp", 0)
            self.xp_need = xp_required(self.level)
            self.elapsed = data.get("elapsed", 0)
            self.kills = data.get("kills", 0)
            self.bosses = data.get("bosses", 0)
            self.run_coins = data.get("run_coins", 0)
            self.combo = data.get("combo", 0)
            self.max_combo = data.get("max_combo", 0)
            self.last_level_boss = data.get("last_level_boss", 0)
            self.boss_queued = data.get("boss_queued", False)

            for name in data.get("acquired", []):
                for c in CARDS:
                    if c["name"] == name:
                        self.player.apply(c)
                        break

            self.player.x = clamp(data.get("player_x", self.world_w / 2), 40, self.world_w - 40)
            self.player.y = clamp(data.get("player_y", self.world_h / 2), 40, self.world_h - 40)
            self.cam_x = self.player.x - W / 2
            self.cam_y = self.player.y - H / 2
            self.player.hp = clamp(data.get("hp", self.player.maxhp), 1, self.player.maxhp)
            self.player.shield = data.get("shield", 0)
            self.player.rerolls = data.get("rerolls", 1)
            if "last_chance" in data:
                self.player.last_chance = data["last_chance"]
            self.player.dash_cd = data.get("dash_cd", 0)
            self.player.since_survival = data.get("since_survival", 0)
            self.player.ult_charge = data.get("ult_charge", 0.0)

            self.record_highscore()

            if data.get("pending_levelup", False) or self.xp >= self.xp_need:
                if self.xp >= self.xp_need:
                    self.xp -= self.xp_need
                    self.level += 1
                    self.xp_need = xp_required(self.level)
                self.cards = self.choose_cards()
                self.state = "levelup"
            return True
        except Exception as e:
            print(f"[ERRO AO CARREGAR SLOT {target_slot}]: {e}")
            return False

    def delete_save(self, slot=None):
        target_slot = slot if slot is not None else self.current_slot
        try:
            flush_saves()
            fname = self.get_slot_filename(target_slot)
            if os.path.exists(fname):
                os.remove(fname)
        except Exception:
            pass

    def camera(self):
        cx = clamp(self.cam_x, 0, max(0, self.world_w - W))
        cy = clamp(self.cam_y, 0, max(0, self.world_h - H))
        if self.camera_shake > 0 and self.settings["shake"]:
            # trauma^2 com ruido suave (soma de senoides), em vez de aleatorio puro
            tr = min(1.0, self.camera_shake)
            amp = tr * tr * 15.0
            t = time.perf_counter() * 34.0
            cx += amp * (math.sin(t * 1.31) + math.sin(t * 2.73 + 1.7)) * 0.5
            cy += amp * (math.sin(t * 1.17 + 0.6) + math.sin(t * 3.11 + 2.3)) * 0.5
        return cx, cy

    def camera_visible(self, x, y):
        cx, cy = self.camera()
        return cx - 80 < x < cx + W + 80 and cy - 80 < y < cy + H + 80

    def spawn_enemy(self, kind=None):
        if len(self.enemies) > 145:
            return
        side = random.choice([sd for sd in range(4) if sd != self._last_side])
        self._last_side = side
        margin = 35
        cx, cy = self.player.x, self.player.y
        if side == 0:
            x, y = random.uniform(cx - W * .7, cx + W * .7), cy - H * .65
        elif side == 1:
            x, y = random.uniform(cx - W * .7, cx + W * .7), cy + H * .65
        elif side == 2:
            x, y = cx - W * .7, random.uniform(cy - H * .6, cy + H * .6)
        else:
            x, y = cx + W * .7, random.uniform(cy - H * .6, cy + H * .6)
        x = clamp(x, margin, self.world_w - margin)
        y = clamp(y, margin, self.world_h - margin)
        if math.hypot(x - cx, y - cy) < 260:
            x = clamp(x + 320, margin, self.world_w - margin)
        if kind is None:
            lvl = self.level
            choices = ["Básico"] * 6
            # (táticos adicionados abaixo conforme nível)
            if lvl >= 2:
                choices += ["Veloz"] * 3 + ["Tanque"]
            if lvl >= 4:
                choices += ["Atirador"] * 2 + ["Regenerador"]
            if lvl >= 6:
                choices += ["Explosivo", "Blindado"]
            if lvl >= 5:
                choices += ["Piromante", "Berserker"]
            if lvl >= 7:
                choices += ["Sentinela Laser", "Ceifador"]
            if lvl >= 8:
                choices += ["Teletransportador", "Invocador"]
            if lvl >= 9:
                choices += ["Aracnídeo"] * 2
            if lvl >= 13:
                choices += ["Anomalia"]
            if lvl >= 11:
                choices += ["Elite"]
            if lvl >= 6:
                choices += ["Parasita", "Bombardeiro"]
            if lvl >= 8:
                choices += ["Espelho", "Escudeiro", "Fantasma"]
            if lvl >= 10:
                choices += ["Vórtice"]
            kind = random.choice(choices)
        e0 = Enemy(x, y, kind, self.level)
        e0.spawn_t = 0.55
        self.enemies.append(e0)
        if kind in ("Básico", "Veloz", "Aracnídeo") and self.level >= 3 and random.random() < 0.16 and len(self.enemies) < 100:
            for _ in range(random.randint(2, 4)):
                ex = clamp(x + random.uniform(-60, 60), margin, self.world_w - margin)
                ey = clamp(y + random.uniform(-60, 60), margin, self.world_h - margin)
                e1 = Enemy(ex, ey, kind, self.level)
                e1.spawn_t = 0.55
                e1.xp *= 0.8
                self.enemies.append(e1)

    def spawn_boss(self):
        if self.boss_active:
            return
        self.boss_index = max(1, self.level // 10)
        x = clamp(self.player.x + random.choice([-560, 560]), 90, self.world_w - 90)
        y = clamp(self.player.y + random.choice([-380, 380]), 90, self.world_h - 90)
        self.enemies.append(Enemy(x, y, "Boss", self.level, True, self.boss_index))
        self.boss_active = True
        self.boss_queued = False
        self.camera_shake = .9
        self.boss_banner_timer = 3.5
        self.shockwaves.append(Shockwave(x, y, 220, PURPLE, 0.55, 4))
        self.particles.extend(Particle(x, y, PURPLE, size=7) for _ in range(45))
        play_sound("boss")

    def gain_xp(self, amount):
        sc = self.get_skin_colors()
        combo_mult = 1.0 + min(0.50, self.combo * 0.01)
        syn_xp = getattr(self.player, "syn_xp", 0.0)
        self.xp += amount * (1 + self.player.xp_bonus) * (1 + self.player.orb_bonus) * combo_mult * (1.0 + syn_xp)
        if self.xp >= self.xp_need and self.state == "playing":
            self.xp -= self.xp_need
            self.level += 1
            self.xp_need = xp_required(self.level)
            self.cards = self.choose_cards()
            self.state = "levelup"
            self.shockwaves.append(Shockwave(self.player.x, self.player.y, 160, sc["bullet"], 0.45, 3))
            self.particles.extend(Particle(self.player.x, self.player.y, sc["bullet"], size=6) for _ in range(40))
            play_sound("levelup")
            if self.level % 10 == 0 and self.level > self.last_level_boss:
                self.boss_queued = True
                self.last_level_boss = self.level
            self.save_game(self.current_slot)

    def choose_cards(self):
        pool = CARDS[:]
        if "Última Chance" in self.player.acquired:
            pool = [c for c in pool if c["effect"] != "lastchance"]
        if self.player.dash:
            pool = [c for c in pool if c["effect"] != "dash"]
        if self.player.orbitals >= 4:
            pool = [c for c in pool if c["effect"] != "orbitals"]
        if self.player.blackhole:
            pool = [c for c in pool if c["effect"] != "blackhole"]
        weights = [
            5.0 if c["rarity"] == "Comum" else
            3.0 if c["rarity"] == "Incomum" else
            1.75 if c["rarity"] == "Rara" else
            1.0 if c["rarity"] == "Épica" else
            0.52 if c["rarity"] == "Lendária" else
            0.28 if c["rarity"] == "Mítica" else
            0.18 if c["rarity"] == "Divina" else
            0.12 if c["rarity"] == "Suprema" else
            0.07 if c["rarity"] == "Primordial" else 0.035
            for c in pool
        ]
        chosen = []
        for _ in range(3):
            if not pool:
                break
            c = random.choices(pool, weights=weights, k=1)[0]
            chosen.append(c)
            idx = pool.index(c)
            pool.pop(idx)
            weights.pop(idx)
        return chosen

    def enemy_killed(self, e):
        sc = self.get_skin_colors()
        # Parasita morto: restaura velocidade do jogador
        if e.kind == "Parasita" and getattr(e, "attached", False):
            if hasattr(self.player, "_parasite_base_speed"):
                self.player.move_speed = self.player._parasite_base_speed
                delattr(self.player, "_parasite_base_speed")
            if hasattr(self.player, "_parasite_slow"):
                delattr(self.player, "_parasite_slow")
        self.kills += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.combo_timer = 3.2
        self.player.ult_charge = min(100.0, self.player.ult_charge + (1.8 if not e.boss else 25.0) * self.player.ult_rate)
        self.record_highscore()
        if self.player.killboost:
            self.player.killboost_timer = 2.0

        orb_val = int(e.xp * (1 + self.player.elite_xp if e.kind == "Elite" else 1) * (1 + self.player.boss_xp if e.boss else 1))
        self.orbs.append(Orb(e.x, e.y, orb_val, "xp"))

        # Drop de Moedas Douradas!
        if e.boss:
            for _ in range(8):
                self.orbs.append(Orb(e.x + random.uniform(-35, 35), e.y + random.uniform(-35, 35), 10 + self.level, "coin"))
        elif e.kind == "Elite":
            for _ in range(3):
                self.orbs.append(Orb(e.x + random.uniform(-18, 18), e.y + random.uniform(-18, 18), 5 + self.level // 3, "coin"))
        elif random.random() < 0.45:
            coin_val = 2 if e.kind in ("Tanque", "Blindado", "Invocador") else 1
            self.orbs.append(Orb(e.x + random.uniform(-12, 12), e.y + random.uniform(-12, 12), coin_val, "coin"))

        if random.random() < (0.06 if not e.boss else 1.0):
            self.orbs.append(Orb(e.x + random.uniform(-15, 15), e.y + random.uniform(-15, 15), 18 if not e.boss else 45, "heal"))

        if e.boss or (e.kind == "Elite" and random.random() < 0.35):
            self.chests.append(RelicChest(e.x, e.y))
            self.hit_stop = 0.05 if not e.boss else 0.12

        spawn_death_fx(self, e)
        play_sound("kill")

        if self.player.lifesteal:
            self.player.hp = min(self.player.maxhp, self.player.hp + 2.2 * (1 + self.player.healing))
        if self.player.eliteshield and e.kind == "Elite":
            self.player.shield += 18

        if not e.boss:
            z_ab_dead = getattr(e, "zone_variant", ZONE_VARIANTS[0])["ability"]
            if z_ab_dead == "magma_burst" and random.random() < 0.45:
                base_ang = math.atan2(self.player.y - e.y, self.player.x - e.x)
                for off_m in (-0.35, 0.0, 0.35):
                    self.bullets.append(Bullet(e.x, e.y, math.cos(base_ang + off_m) * 210, math.sin(base_ang + off_m) * 210, 9 + self.level * 0.4, enemy=True, size=5, color=ORANGE))
        should_explode = (e.kind == "Explosivo") or (e.affix == "Explosivo") or (self.player.deathboom and random.random() < .22)
        if should_explode:
            boom_r = 115 if e.kind == "Explosivo" else 130
            self.shockwaves.append(Shockwave(e.x, e.y, boom_r, ORANGE if e.kind == "Explosivo" else sc["bullet"], 0.32, 3))
            play_sound("boom")
            for other in self.enemies:
                if other is not e and other.alive and math.hypot(other.x - e.x, other.y - e.y) < boom_r:
                    other.hp -= 48 + self.level * 2

        if e.boss:
            self.bosses += 1
            self.boss_active = False
            new_z_idx = self.bosses % len(ARENA_BIOMES)
            new_biome = ARENA_BIOMES[new_z_idx]
            new_var = ZONE_VARIANTS[new_z_idx]
            for rem_e in self.enemies:
                if rem_e.alive and not rem_e.boss:
                    rem_e.apply_zone_variant(new_z_idx)
            self.floating_texts.append(FloatingText(self.player.x, self.player.y - 48, f"ZONA {new_z_idx + 1}: {new_biome['name'].upper()} ({new_var['tag'].upper()})!", GOLD, crit=True))
            self.player.rerolls += 1
            self.gain_xp(140 + self.boss_index * 55)
            self.player.shield += 35
            self.player.hp = min(self.player.maxhp, self.player.hp + 30)
            self.shockwaves.append(Shockwave(e.x, e.y, 260, GOLD, 0.65, 5))
            self.cards = self.choose_cards()
            self.state = "levelup"
            self.camera_shake = 1.2
            self.save_game(self.current_slot)
            play_sound("levelup")

    # ----- spatial hash de inimigos (balas, homing, status em área) -----
    def build_enemy_grid(self):
        g = {}
        mr = 0
        for e in self.enemies:
            if e.alive:
                g.setdefault((int(e.x // 96), int(e.y // 96)), []).append(e)
                if e.r > mr:
                    mr = e.r
        self._eg = g
        self._emr = mr

    def enemies_near(self, x, y, r):
        r2 = r + self._emr
        out = []
        g = self._eg
        for gx in range(int((x - r2) // 96), int((x + r2) // 96) + 1):
            for gy in range(int((y - r2) // 96), int((y + r2) // 96) + 1):
                c = g.get((gx, gy))
                if c:
                    out.extend(c)
        return out

    def enemies_near_seg(self, x0, y0, x1, y1, pad):
        r2 = pad + self._emr
        out = []
        g = self._eg
        for gx in range(int((min(x0, x1) - r2) // 96), int((max(x0, x1) + r2) // 96) + 1):
            for gy in range(int((min(y0, y1) - r2) // 96), int((max(y0, y1) + r2) // 96) + 1):
                c = g.get((gx, gy))
                if c:
                    out.extend(c)
        return out

    # ----- status elementais e reacoes -----
    def apply_status(self, e, name, dur, stacks=1):
        st = e.status
        if e.boss:
            dur *= 0.6
        if name == "poison":
            cur = st.get("poison", [0.0, 0])
            cap = int(getattr(self.player, "syn_poison_cap", 5))
            st["poison"] = [max(cur[0], dur), min(cap, cur[1] + stacks)]
        elif name == "burn":
            dur = dur * getattr(self.player, "syn_dot", 1.0)
            prev = st.get("burn", [0.0])[0]
            st["burn"] = [max(prev, dur)]
        else:
            st[name] = [dur, 1]
        if e.react_cd <= 0 and "burn" in st and "freeze" in st:
            e.react_cd = 1.2
            del st["burn"]
            del st["freeze"]
            self.steam_burst(e)

    def steam_burst(self, e):
        dmg = (36 + self.level * 3) * (2.0 if self.player.catalyst else 1.0)
        for o in self.enemies_near(e.x, e.y, 95):
            if o.alive and math.hypot(o.x - e.x, o.y - e.y) < 95 + o.r:
                o.hp -= dmg * (1.4 if o is e else 1.0)
                o.hitflash = 0.1
        self.shockwaves.append(Shockwave(e.x, e.y, 95, (215, 238, 255), 0.32, 3))
        for _ in range(5):
            self.particles.append(Particle(e.x + random.uniform(-10, 10), e.y + random.uniform(-10, 10), (210, 225, 240), vel=(random.uniform(-50, 50), random.uniform(-70, -10)), size=random.uniform(8, 14), kind="smoke"))
        self.floating_texts.append(FloatingText(e.x, e.y - e.r, "VAPOR!", (200, 235, 255), crit=True))
        play_sound("zap")

    def apply_status_on_hit(self, e):
        p = self.player
        if not (p.burn or p.poison or p.freeze or p.mark):
            return
        sc_ = p.status_chance
        if p.mark and "mark" not in e.status and random.random() < 0.30 + sc_:
            self.apply_status(e, "mark", 4.0)
        if p.burn and random.random() < 0.35 + sc_:
            self.apply_status(e, "burn", 3.0)
        if p.poison and random.random() < 0.40 + sc_:
            self.apply_status(e, "poison", 4.0)
        if p.freeze and random.random() < 0.25 + sc_:
            self.apply_status(e, "freeze", 2.0)

    def trigger_phase_event(self):
        """Evento no meio da fase: chuva de XP, inimigos ou tempestade mista."""
        if self.boss_active or self.game_mode == "pvp":
            self.phase_event_timer = random.uniform(20.0, 30.0)
            return
        roll = random.random()
        if roll < 0.38:
            kind, label = "xp_rain", "CHUVA DE XP!"
        elif roll < 0.72:
            kind, label = "enemy_rain", "CHUVA DE INIMIGOS!"
        else:
            kind, label = "mixed_storm", "TEMPESTADE: XP + INIMIGOS!"
        self.phase_event_active = kind
        self.phase_event_ttl = 7.5 + min(4.0, self.level * 0.15)
        self.phase_event_total = self.phase_event_ttl
        self.phase_event_cd_xp = 0.0
        self.phase_event_cd_en = 0.0
        self.phase_event_banner = 3.2
        self.phase_event_label = label
        self.camera_shake = max(self.camera_shake, 0.35)
        self.achievement_banners.append({
            "title": label,
            "sub": "Colete orbes • Sobreviva à horda do céu",
            "timer": 3.5
        })
        try:
            play_sound("achievement")
        except Exception:
            try:
                play_sound("select")
            except Exception:
                pass
        self.phase_event_timer = random.uniform(40.0, 55.0)

    def update_phase_events(self, dt):
        """Atualiza timer e executa chuva de XP / inimigos durante a fase."""
        if self.game_mode == "pvp":
            return
        if self.phase_event_banner > 0:
            self.phase_event_banner = max(0.0, self.phase_event_banner - dt)
        if self.phase_event_active is None:
            self.phase_event_timer -= dt
            if self.phase_event_timer <= 0 and self.state == "playing" and not self.boss_active:
                self.trigger_phase_event()
            return
        self.phase_event_ttl -= dt
        self.phase_event_cd_xp = max(0.0, self.phase_event_cd_xp - dt)
        self.phase_event_cd_en = max(0.0, self.phase_event_cd_en - dt)
        if self.phase_event_ttl <= 0:
            self.phase_event_active = None
            self.phase_event_label = ""
            return
        px, py = self.player.x, self.player.y
        kind = self.phase_event_active
        if kind in ("xp_rain", "mixed_storm") and self.phase_event_cd_xp <= 0:
            n = 4 if kind == "xp_rain" else 2
            for _ in range(n):
                ox = clamp(px + random.uniform(-420, 420), 40, self.world_w - 40)
                oy = clamp(py - random.uniform(280, 520), 40, self.world_h - 40)
                val = 12 + self.level * 2 + random.randint(0, 18)
                self.orbs.append(Orb(ox, oy, val, "xp"))
                if random.random() < 0.12:
                    self.orbs.append(Orb(ox + random.uniform(-20, 20), oy + 12, 8 + self.level, "coin"))
            self.phase_event_cd_xp = 0.26 if kind == "xp_rain" else 0.38
            if self.settings.get("effects", True):
                for _ in range(4):
                    self.particles.append(Particle(
                        px + random.uniform(-300, 300),
                        py - random.uniform(100, 400),
                        (40, 165, 255), size=3
                    ))
        if kind in ("enemy_rain", "mixed_storm") and self.phase_event_cd_en <= 0 and len(self.enemies) < 130:
            n_spawn = 2 if kind == "enemy_rain" else 1
            choices = ["Básico"] * 4 + ["Veloz"] * 3
            if self.level >= 4:
                choices += ["Atirador", "Tanque"]
            if self.level >= 7:
                choices += ["Explosivo"]
            if self.level >= 8:
                choices += ["Parasita", "Bombardeiro", "Escudeiro"]
            if self.level >= 10:
                choices += ["Ceifador", "Fantasma"]
            for _ in range(n_spawn):
                if len(self.enemies) >= 130:
                    break
                sx = clamp(px + random.uniform(-380, 380), 50, self.world_w - 50)
                sy = clamp(py - random.uniform(260, 480), 50, self.world_h - 50)
                kind_e = random.choice(choices)
                try:
                    en = Enemy(sx, sy, kind_e, self.level)
                    en.spawn_t = 0.65
                    en.spawn_total = 0.65
                    en.drop_fx = True
                    self.enemies.append(en)
                    self.shockwaves.append(Shockwave(sx, sy, 70, (255, 90, 60), 0.5, 2))
                except Exception:
                    try:
                        self.spawn_enemy(kind_e)
                    except Exception:
                        pass
            self.phase_event_cd_en = 0.48 if kind == "enemy_rain" else 0.55

    def spawn_pressure(self):
        """VERSÃO DIFÍCIL: pressão agressiva, ciclos de 32 s."""
        ph = (self.elapsed % 32.0) / 32.0
        lvl_boost = min(0.55, self.level * 0.025)
        if ph < 0.82:
            return 1.05 + lvl_boost + 0.85 * (ph / 0.82)
        return 0.55 + lvl_boost * 0.5

    def resolve_enemy_collisions(self, dt):
        """Particionamento espacial rápido O(N) para evitar lentidão com centenas de inimigos."""
        cell_size = 44
        grid = {}
        alive_enemies = [e for e in self.enemies if e.alive and not e.boss]
        for e in alive_enemies:
            key = (int(e.x // cell_size), int(e.y // cell_size))
            grid.setdefault(key, []).append(e)

        for (gx, gy), cell in grid.items():
            for dx_c in (0, 1):
                for dy_c in (-1, 0, 1):
                    if dx_c == 0 and dy_c < 0:
                        continue
                    other_cell = grid.get((gx + dx_c, gy + dy_c))
                    if not other_cell:
                        continue
                    for e1 in cell:
                        for e2 in other_cell:
                            if e1 is e2:
                                continue
                            dx = e2.x - e1.x
                            dy = e2.y - e1.y
                            min_d = e1.r + e2.r + 2
                            if abs(dx) < min_d and abs(dy) < min_d:
                                d = math.hypot(dx, dy)
                                if 0 < d < min_d:
                                    overlap = (min_d - d) * 0.35
                                    nx, ny = dx / d, dy / d
                                    e1.x -= nx * overlap
                                    e1.y -= ny * overlap
                                    e2.x += nx * overlap
                                    e2.y += ny * overlap

    def update(self, dt):
        self.save_indicator_timer = max(0.0, self.save_indicator_timer - dt)
        for b_ach in self.achievement_banners:
            b_ach["timer"] -= dt
        self.achievement_banners = [b_ach for b_ach in self.achievement_banners if b_ach["timer"] > 0]

        if self.state != "playing":
            return
        if self.hit_stop > 0:
            # hit-stop vira "quase parado" (6% da velocidade) em vez de congelar todo o update
            self.hit_stop -= dt
            dt *= 0.06
        elif self.slowmo > 0:
            self.slowmo -= dt
            dt *= 0.35

        sc = self.get_skin_colors()
        self.elapsed += dt
        self.camera_shake = max(0, self.camera_shake - dt)
        self.boss_banner_timer = max(0, self.boss_banner_timer - dt)
        self.update_phase_events(dt)

        # Auto-Save a cada 3 segundos durante a partida
        self.autosave_timer += dt
        if self.autosave_timer >= 6.0:
            self.autosave_timer = 0.0
            self.save_game(self.current_slot)

        if self.combo > 0:
            self.combo_timer -= dt
            if self.combo_timer <= 0:
                self.combo = 0

        self.pvp_banner_timer = max(0.0, self.pvp_banner_timer - dt)
        keys = pygame.key.get_pressed()
        mouse = pygame.mouse.get_pressed()[0]
        self.update_terrain(dt)
        self.update_world_extras(dt)
        self.player.update(dt, self, keys, mouse)
        if self.pet:
            self.pet.update(dt, self)
        if self.partner:
            self.partner.damage = max(self.partner.damage, self.player.damage * 0.85)
            self.partner.update(dt, self)
        if self.game_mode in ("coop", "pvp"):
            self.net.sync_step(self)

        for bh in self.blackholes:
            bh.update(dt, self)
        self.blackholes = [bh for bh in self.blackholes if bh.life > 0]

        mx, my = pygame.mouse.get_pos()
        lead_x = (mx - W / 2) * 0.12
        lead_y = (my - H / 2) * 0.12
        target_cx = clamp(self.player.x + lead_x - W / 2, 0, max(0, self.world_w - W))
        target_cy = clamp(self.player.y + lead_y - H / 2, 0, max(0, self.world_h - H))
        self.cam_x += (target_cx - self.cam_x) * min(1.0, 9.0 * dt)
        self.cam_y += (target_cy - self.cam_y) * min(1.0, 9.0 * dt)

        if self.game_mode == "pvp":
            self.pvp_orb_timer += dt
            if self.pvp_orb_timer >= 4.0 and len(self.orbs) < 8:
                self.pvp_orb_timer = 0.0
                ox = self.world_w / 2 + random.uniform(-340, 340)
                oy = self.world_h / 2 + random.uniform(-240, 240)
                kind_o = "heal" if random.random() < 0.5 else "xp"
                self.orbs.append(Orb(ox, oy, 28 if kind_o == "heal" else 40, kind_o))
        else:
            self.spawn_timer -= dt
            pressure = self.spawn_pressure()
            # VERSÃO DIFÍCIL: hordas mais densas
            interval = max(.10, (0.78 - self.level * .022) / max(1.0, pressure))
            cap = int(min(140, 22 + self.level * 4.2) * (0.65 + 0.55 * pressure))
            if self.spawn_timer <= 0 and len(self.enemies) < cap:
                self.spawn_timer = interval
                self.spawn_enemy()
                if self.level >= 8 and random.random() < 0.28 and len(self.enemies) < cap:
                    self.spawn_enemy()
            if self.boss_queued and not self.boss_active and not any(e.boss and e.alive for e in self.enemies):
                self.spawn_boss()

        for e in self.enemies:
            e.update(dt, self)
        self.props_resolve()
        self.build_enemy_grid()

        for b in self.bullets:
            b.update(dt, self)
            if b.enemy:
                if math.hypot(b.x - self.player.x, b.y - self.player.y) < self.player.r + b.size - 1:
                    self.player.take_damage(b.damage, self)
                    b.life = 0
                elif self.game_mode == "coop" and self.partner and not self.partner.downed:
                    if math.hypot(b.x - self.partner.x, b.y - self.partner.y) < self.partner.r + b.size - 1:
                        self.partner.take_damage(b.damage, self)
                        b.life = 0
            elif b.owner == "p2":
                if math.hypot(b.x - self.player.x, b.y - self.player.y) < self.player.r + b.size - 1:
                    self.player.take_damage(b.damage, self)
                    b.life = 0
            else:
                if self.game_mode == "pvp" and b.owner == "p1" and self.partner and not self.partner.downed:
                    if math.hypot(b.x - self.partner.x, b.y - self.partner.y) < self.partner.r + b.size + 1:
                        is_crit = random.random() < (self.player.crit + getattr(self.player, "syn_crit", 0))
                        dmg_pvp = b.damage * (1.35 if is_crit else 0.85)
                        self.partner.take_damage(dmg_pvp, self)
                        self.player.ult_charge = min(100.0, self.player.ult_charge + 4.5)
                        b.life = 0
                        continue
                for e in self.enemies_near_seg(b.px, b.py, b.x, b.y, b.size + 2):
                    if e.alive and e not in b.hit and seg_hit(b.px, b.py, b.x, b.y, e.x, e.y, e.r + b.size + 2):
                        # Fantasma intangível ignora dano
                        if getattr(e, "intangible", 0) > 0:
                            continue
                        # Escudeiro: bloqueia ataques frontais (arco de 110°)
                        if e.kind == "Escudeiro":
                            ang_to_b = math.atan2(b.y - e.y, b.x - e.x)
                            diff = (ang_to_b - e.shield_dir + math.pi) % math.tau - math.pi
                            if abs(diff) < 0.95:
                                b.hit.add(e)
                                if b.pierce > 0:
                                    b.pierce -= 1
                                else:
                                    b.life = 0
                                self.particles.extend(Particle(b.x, b.y, (140, 160, 190)) for _ in range(3))
                                continue
                        dmg = b.damage * (1 + self.player.boss_bonus if e.boss else 1) * (1 + self.player.elite_bonus if e.kind == "Elite" else 1)
                        is_crit = random.random() < (self.player.crit + getattr(self.player, "syn_crit", 0))
                        if is_crit:
                            dmg *= self.player.crit_mult
                            play_sound("crit")
                        if e.kind == "Blindado":
                            dmg *= 0.75
                        if e.guard > 0:
                            dmg *= 0.4
                        if e.status and "mark" in e.status:
                            dmg *= 1.25
                        e.hp -= dmg
                        e.hitflash = .12
                        b.hit.add(e)
                        self.apply_status_on_hit(e)

                        if b.knockback > 0 and not e.boss:
                            knx, kny = vec_norm(b.vx, b.vy)
                            e.x = clamp(e.x + knx * b.knockback * 0.25, 25, self.world_w - 25)
                            e.y = clamp(e.y + kny * b.knockback * 0.25, 25, self.world_h - 25)

                        if self.settings["damage_numbers"]:
                            txt = f"{int(dmg)}!" if is_crit else f"{int(dmg)}"
                            col = GOLD if is_crit else WHITE
                            self.floating_texts.append(FloatingText(e.x, e.y - e.r, txt, col, crit=is_crit))

                        self.particles.extend(Particle(b.x, b.y, e.color) for _ in range(4))
                        if self.player.explosive:
                            self.shockwaves.append(Shockwave(b.x, b.y, 55, sc["bullet"], 0.18, 2))
                            for other in self.enemies:
                                if other is not e and other.alive and math.hypot(other.x - e.x, other.y - e.y) < 55:
                                    other.hp -= dmg * .28

                        if self.player.chain_lightning and random.random() < (0.22 + getattr(self.player, "syn_chain", 0)):
                            chain_targets = [o for o in self.enemies if o is not e and o.alive and math.hypot(o.x - e.x, o.y - e.y) < 180]
                            for ct in chain_targets[:1]:
                                zap_dmg = dmg * 0.40
                                ct.hp -= zap_dmg
                                ct.hitflash = 0.10
                                self.lightnings.append(LightningBolt(e.x, e.y, ct.x, ct.y, sc["bullet"]))
                            if chain_targets:
                                play_sound("zap")

                        if b.ricochet > 0:
                            b.ricochet -= 1
                            candidates = [o for o in self.enemies if o.alive and o not in b.hit and math.hypot(o.x - e.x, o.y - e.y) < 280]
                            if candidates:
                                target = min(candidates, key=lambda o: (o.x - e.x) ** 2 + (o.y - e.y) ** 2)
                                rnx, rny = vec_norm(target.x - b.x, target.y - b.y)
                                spd = math.hypot(b.vx, b.vy)
                                b.vx, b.vy = rnx * spd, rny * spd
                                break

                        if b.pierce > 0:
                            b.pierce -= 1
                        else:
                            b.life = 0
                        break

        for e in self.enemies[:]:
            if e.hp <= 0 and e.alive:
                e.alive = False
                self.enemy_killed(e)
        self.enemies = [e for e in self.enemies if e.alive]
        self.resolve_enemy_collisions(dt)

        for b in self.bullets:
            if not b.enemy and b.ricochet > 0:
                bounced = False
                if b.x < 0 or b.x > self.world_w:
                    b.vx = -b.vx
                    b.x = clamp(b.x, 1, self.world_w - 1)
                    bounced = True
                if b.y < 0 or b.y > self.world_h:
                    b.vy = -b.vy
                    b.y = clamp(b.y, 1, self.world_h - 1)
                    bounced = True
                if bounced:
                    b.ricochet -= 1
                    self.particles.extend(Particle(b.x, b.y, b.color, size=3) for _ in range(5))
        self.props_bullets()
        self.bullets = [b for b in self.bullets if b.life > 0 and 0 < b.x < self.world_w and 0 < b.y < self.world_h]
        self.orbs = [o for o in self.orbs if o.update(dt, self)]
        self.chests = [ch for ch in self.chests if ch.update(dt, self)]
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        cap_p = PARTICLE_CAPS[self.settings.get("quality", 2)]
        if len(self.particles) > cap_p:
            del self.particles[:len(self.particles) - cap_p]
        for ft in self.floating_texts:
            ft.update(dt)
        self.floating_texts = [ft for ft in self.floating_texts if ft.life > 0]
        for sw in self.shockwaves:
            sw.update(dt)
        self.shockwaves = [sw for sw in self.shockwaves if sw.life > 0]
        for uv in self.ult_visuals:
            uv.update(dt)
        self.ult_visuals = [uv for uv in self.ult_visuals if uv.life > 0]
        for lb in self.lightnings:
            lb.update(dt)
        self.lightnings = [lb for lb in self.lightnings if lb.life > 0]

    def draw_background(self, s, cx, cy):
        biome_idx = self.bosses % len(ARENA_BIOMES)
        biome = ARENA_BIOMES[biome_idx]
        s.fill(biome["bg"])
        sc = self.get_skin_colors()

        self.ensure_terrain()
        terr = get_terrain_surface(biome_idx, self.world_w, self.world_h, self.pools) if biome_idx != 0 else None
        if terr is not None:
            s.blit(terr, (int(-cx), int(-cy)))
        else:
            if biome_idx not in NEBULA_CACHE:
                blobs = []
                for col_n, rad_n in biome["nebula"]:
                    bs = pygame.Surface((rad_n * 2, rad_n * 2), pygame.SRCALPHA)
                    for step in range(8, 0, -1):
                        rr = int(rad_n * (step / 8))
                        pygame.draw.circle(bs, (*col_n, 8), (rad_n, rad_n), rr)
                    blobs.append((bs, rad_n))
                NEBULA_CACHE[biome_idx] = blobs
            for idx_b, (bs, rad_n) in enumerate(NEBULA_CACHE[biome_idx]):
                nx = ((idx_b * 430 + 250) - int(cx * 0.15)) % (W + rad_n * 2) - rad_n
                ny = ((idx_b * 310 + 180) - int(cy * 0.15)) % (H + rad_n * 2) - rad_n
                s.blit(bs, (nx - rad_n, ny - rad_n), special_flags=pygame.BLEND_ADD)

            # Camadas de grade com paralaxe (sensação de profundidade 2.5D)
            sub_grid = 140
            sox, soy = int(-cx * 0.18) % sub_grid, int(-cy * 0.18) % sub_grid
            for x in range(sox, W, sub_grid):
                pygame.draw.line(s, biome["sub_grid"], (x, 0), (x, H), 1)
            for y in range(soy, H, sub_grid):
                pygame.draw.line(s, biome["sub_grid"], (0, y), (W, y), 1)

            grid = 68
            ox, oy = int(-cx * 0.5) % grid, int(-cy * 0.5) % grid
            for x in range(ox, W, grid):
                pygame.draw.line(s, biome["grid"], (x, 0), (x, H), 1)
            for y in range(oy, H, grid):
                # linhas horizontais um pouco mais densas na base (chão virtual)
                pygame.draw.line(s, biome["grid"], (0, y), (W, y), 1)

            # nós próximos ao jogador com brilho (ancoragem espacial)
            px_s, py_s = int(self.player.x - cx), int(self.player.y - cy)
            for x in range(ox, W, grid):
                if abs(x - px_s) < 220:
                    for y in range(oy, H, grid):
                        d_node = math.hypot(x - px_s, y - py_s)
                        if d_node < 220:
                            k = 1.0 - d_node / 220
                            col = (int(sc["trail"][0] * k), int(sc["trail"][1] * k), int(sc["trail"][2] * k))
                            pygame.draw.circle(s, col, (x, y), 2 if d_node > 80 else 3)

            st_r, st_g, st_b = biome["star_col"]
            weather_kind = biome.get("weather", "sparks")
            for i in range(65):
                x = (i * 187 - int(cx * 0.25)) % W
                y = (i * 93 - int(cy * 0.25 + self.elapsed * (12 if biome_idx in (1, 3) else 2))) % H
                pulse = 0.45 + abs(math.sin(self.elapsed * 2.2 + i)) * 0.55
                col_star = (int(st_r * pulse), int(st_g * pulse), int(st_b * pulse))
                pygame.draw.circle(s, col_star, (x, y), 1 + (i % 2))

        weather_kind = biome.get("weather", "sparks")
        self.draw_pools(s, cx, cy)

        if self.settings.get("effects", True):
            for w_i in range(18):
                wx = (w_i * 233 + int(self.elapsed * (28 if weather_kind == "snow" else 14)) - int(cx * 0.4)) % W
                wy = (w_i * 139 + int(self.elapsed * (-42 if weather_kind in ("embers", "divine_light") else 36)) - int(cy * 0.4)) % H
                if weather_kind == "embers":
                    pygame.draw.circle(s, (255, 140, 35), (wx, wy), 2 + (w_i % 2))
                elif weather_kind == "spores":
                    sway = int(math.sin(self.elapsed * 3.0 + w_i) * 8)
                    pygame.draw.circle(s, (75, 255, 130), (wx + sway, wy), 2)
                elif weather_kind == "snow":
                    pygame.draw.circle(s, (220, 245, 255), (wx, wy), 2 + (w_i % 2))
                elif weather_kind == "void_rifts":
                    r_v = 3 + int(abs(math.sin(self.elapsed * 2.5 + w_i)) * 4)
                    pygame.draw.circle(s, (195, 95, 255), (wx, wy), r_v, 1)
                elif weather_kind == "divine_light":
                    pygame.draw.line(s, (255, 225, 95), (wx, wy - 5), (wx, wy + 5), 1)
                    pygame.draw.line(s, (255, 225, 95), (wx - 5, wy), (wx + 5, wy), 1)
                else:
                    pygame.draw.circle(s, (0, 220, 255), (wx, wy), 1 + (w_i % 2))

        pygame.draw.rect(s, biome["border_outer"], (int(-cx) - 3, int(-cy) - 3, self.world_w + 6, self.world_h + 6), 8, border_radius=12)
        pygame.draw.rect(s, biome["border_inner"], (int(-cx), int(-cy), self.world_w, self.world_h), 3, border_radius=10)


    # ----------------------------------------------------------------------------
    # TERRENO INTERATIVO POR BIOMA
    # ----------------------------------------------------------------------------
    def ensure_terrain(self):
        idx = self.bosses % len(ARENA_BIOMES)
        if getattr(self, "_terr_idx", None) != idx:
            first = getattr(self, "_terr_idx", None) is None
            self._terr_idx = idx
            self.pools = build_pools(idx, self.world_w, self.world_h)
            if not first and self.state == "playing":
                self.floating_texts.append(FloatingText(self.player.x, self.player.y - 70, BIOME_HAZARD[idx][1].split(":")[0].upper() + "!", ORANGE, crit=True))

    def terrain_dot(self, amount, col):
        p = self.player
        if p.invuln > 1.0 or p.downed:
            return
        amount = max(1.0, amount * (1 - p.armor * 0.5))
        absorbed = min(p.shield, amount)
        p.shield -= absorbed
        amount -= absorbed
        if amount > 0:
            p.hp -= amount
            self.floating_texts.append(FloatingText(p.x + random.uniform(-10, 10), p.y - 14, f"-{int(amount)}", col))
        if p.hp <= 0:
            p.hp = 0.5
            p.invuln = 0.0
            p.dash_time = 0.0
            dg = p.dodge
            p.dodge = 0.0
            p.take_damage(1, self)
            p.dodge = dg

    def update_terrain(self, dt):
        self.ensure_terrain()
        p = self.player
        p.terrain_speed = 1.0
        p.terrain_accel = 1.0
        for pl in self.pools:
            dx, dy = p.x - pl["x"], p.y - pl["y"]
            d = math.hypot(dx, dy)
            k = pl["kind"]
            if k == "void":
                reach = pl["r"] * 1.7
                if 4 < d < reach:
                    pull = 150 * (1 - d / reach)
                    p.x -= dx / d * pull * dt
                    p.y -= dy / d * pull * dt
            elif d < pl["r"] * 0.88:
                if k == "lava":
                    p.burn_t = 3.0
                elif k == "toxic":
                    p.poison_t = 2.5
                    p.terrain_speed = 0.78
                elif k == "ice":
                    p.terrain_accel = 0.2
                    if random.random() < dt * 8:
                        self.particles.append(Particle(p.x, p.y + 8, (210, 240, 255), life=0.4, size=3))
                elif k == "heal":
                    p.hp = min(p.maxhp, p.hp + p.maxhp * 0.012 * dt)
                    if random.random() < dt * 10:
                        self.particles.append(Particle(p.x + random.uniform(-14, 14), p.y + 8, (255, 225, 120), vel=(0, -60), life=0.6, size=3, kind="ember"))
                elif k == "pad":
                    p.terrain_speed = 1.35
        self._dot_acc = getattr(self, "_dot_acc", 0.0) + dt
        tick = self._dot_acc >= 0.4
        if tick:
            self._dot_acc -= 0.4
        lvl = min(self.level, 50)
        bt = getattr(p, "burn_t", 0.0)
        if bt > 0:
            p.burn_t = bt - dt
            if random.random() < 0.6:
                self.particles.append(Particle(p.x + random.uniform(-10, 10), p.y + random.uniform(-6, 8), (255, random.randint(90, 170), 30), vel=(random.uniform(-20, 20), -random.uniform(40, 90)), life=0.45, size=4, kind="ember"))
            if tick:
                self.terrain_dot((5 + 0.45 * lvl) * 0.4, ORANGE)
        pt = getattr(p, "poison_t", 0.0)
        if pt > 0:
            p.poison_t = pt - dt
            if random.random() < 0.3:
                self.particles.append(Particle(p.x + random.uniform(-10, 10), p.y - 4, (110, 255, 90), vel=(0, -35), life=0.5, size=5, kind="smoke"))
            if tick:
                self.terrain_dot((3.5 + 0.3 * lvl) * 0.4, (120, 255, 100))
        self._terr_en = getattr(self, "_terr_en", 0.0) - dt
        if self._terr_en <= 0 and self.pools and self.pools[0]["kind"] in ("lava", "toxic"):
            self._terr_en = 0.25
            nm = "burn" if self.pools[0]["kind"] == "lava" else "poison"
            for pl in self.pools:
                for e in self.enemies_near(pl["x"], pl["y"], pl["r"]):
                    if e.alive and not e.boss and e.kind != "Piromante" and math.hypot(e.x - pl["x"], e.y - pl["y"]) < pl["r"] * 0.88:
                        self.apply_status(e, nm, 2.0)

    def draw_pools(self, s, cx, cy):
        t = self.elapsed
        fx = self.settings.get("effects", True)
        for pl in self.pools:
            sx, sy, r = pl["x"] - cx, pl["y"] - cy, pl["r"]
            if sx < -r * 2 or sx > W + r * 2 or sy < -r * 2 or sy > H + r * 2:
                continue
            kind, ph, pts = pl["kind"], pl["ph"], pl["pts"]

            def poly(k, wob=0.0, rot=0.0):
                return [(sx + math.cos(i * math.tau / 16 + rot) * r * f * k * (1 + wob * math.sin(t * 2 + i + ph)),
                         sy + math.sin(i * math.tau / 16 + rot) * r * f * k * (1 + wob * math.sin(t * 2 + i + ph))) for i, f in enumerate(pts)]
            pulse = 0.5 + 0.5 * math.sin(t * 2.2 + ph)
            if kind == "lava":
                if fx:
                    soft_glow(s, (255, 110, 30), (sx, sy), r * 1.9, 60)
                pygame.draw.polygon(s, (58, 20, 10), poly(1.16))
                pygame.draw.polygon(s, (120, 36, 10), poly(1.07))
                pygame.draw.polygon(s, (235, 80, 18), poly(1.0, 0.03))
                pygame.draw.polygon(s, (255, 140 + int(60 * pulse), 30), poly(0.72, 0.05))
                pygame.draw.polygon(s, (255, 225, 110), poly(0.34 + 0.08 * pulse, 0.08))
                for b in range(4):
                    f = (t * 0.6 + b * 0.25 + ph) % 1.0
                    if f < 0.85:
                        pygame.draw.circle(s, (255, 200, 90), (int(sx + math.cos(b * 2.1 + ph) * r * 0.5), int(sy + math.sin(b * 2.1 + ph) * r * 0.5)), int(3 + f * 9), 2)
            elif kind == "toxic":
                if fx:
                    soft_glow(s, (70, 255, 110), (sx, sy), r * 1.7, 42)
                pygame.draw.polygon(s, (12, 40, 22), poly(1.14))
                pygame.draw.polygon(s, (40, 150, 60), poly(1.0, 0.03))
                pygame.draw.polygon(s, (90, 220, 90), poly(0.7, 0.05))
                pygame.draw.polygon(s, (170, 255, 150), poly(0.3 + 0.06 * pulse, 0.08))
                for b in range(5):
                    f = (t * 0.5 + b * 0.2 + ph) % 1.0
                    pygame.draw.circle(s, (190, 255, 170), (int(sx + math.cos(b * 1.7 + ph) * r * 0.55), int(sy + math.sin(b * 1.7 + ph) * r * 0.5 - f * 18)), int(2 + f * 6), 1)
            elif kind == "ice":
                pygame.draw.polygon(s, (110, 160, 200), poly(1.08))
                pygame.draw.polygon(s, (170, 220, 245), poly(1.0))
                pygame.draw.polygon(s, (215, 242, 255), poly(0.62, 0.0, 0.2))
                for k_ in range(5):
                    a = ph + k_ * 1.3
                    pygame.draw.line(s, (255, 255, 255), (sx + math.cos(a) * r * 0.1, sy + math.sin(a) * r * 0.1), (sx + math.cos(a) * r * 0.8, sy + math.sin(a) * r * 0.8), 1)
                pygame.draw.line(s, (255, 255, 255), (sx - r * 0.5, sy - r * 0.55), (sx - r * 0.2, sy - r * 0.7), 3)
            elif kind == "void":
                if fx:
                    soft_glow(s, (160, 60, 255), (sx, sy), r * 2.2, 55)
                pygame.draw.polygon(s, (60, 10, 100), poly(1.1))
                pygame.draw.polygon(s, (6, 0, 14), poly(0.92, 0.04))
                for k_ in range(3):
                    rect = pygame.Rect(sx - r * 0.8, sy - r * 0.8, r * 1.6, r * 1.6)
                    pygame.draw.arc(s, (200, 110, 255), rect, t * (1.2 + k_ * 0.4) + k_ * 2.1, t * (1.2 + k_ * 0.4) + k_ * 2.1 + 1.6, 3)
                pygame.draw.circle(s, (0, 0, 0), (int(sx), int(sy)), int(r * 0.25))
                pygame.draw.circle(s, (150, 70, 230), (int(sx), int(sy)), int(r * 1.7), 1)
            elif kind == "heal":
                if fx:
                    soft_glow(s, (255, 225, 120), (sx, sy), r * 1.9, 55)
                pygame.draw.circle(s, (255, 225, 120), (int(sx), int(sy)), int(r * 0.9), 3)
                pygame.draw.circle(s, (255, 245, 200), (int(sx), int(sy)), int(r * 0.55), 1)
                for k_ in range(8):
                    a = t * 0.5 + k_ * math.pi / 4
                    pygame.draw.line(s, (255, 235, 150), (sx + math.cos(a) * r * 0.2, sy + math.sin(a) * r * 0.2), (sx + math.cos(a) * r * 0.85, sy + math.sin(a) * r * 0.85), 1)
                draw_icon(s, "star", (sx, sy), int(14 + 3 * pulse), (255, 240, 170))
            elif kind == "pad":
                if fx:
                    soft_glow(s, (0, 220, 255), (sx, sy), r * 1.6, 45)
                pygame.draw.circle(s, (0, 200, 255), (int(sx), int(sy)), int(r), 2)
                pygame.draw.circle(s, (0, 120, 180), (int(sx), int(sy)), int(r * 0.65), 1)
                for k_ in range(3):
                    off = ((t * 1.6 + k_ * 0.33) % 1.0)
                    yy = sy + r * 0.5 - off * r
                    pygame.draw.lines(s, (0, 230, 255), False, [(sx - 16, yy + 8), (sx, yy - 6), (sx + 16, yy + 8)], 3)

    def draw_minimap(self, s):
        sc = self.get_skin_colors()
        mw, mh = 168, 126
        mx, my = 18, 152
        draw_panel(s, (mx, my, mw, mh), (6, 13, 28, 228), (45, 110, 190), 10)

        cx_m, cy_m = mx + mw // 2, my + mh // 2
        for gx in range(1, 4):
            lx = mx + int(mw * gx / 4)
            pygame.draw.line(s, (14, 28, 54), (lx, my + 2), (lx, my + mh - 2), 1)
        for gy in range(1, 3):
            ly = my + int(mh * gy / 3)
            pygame.draw.line(s, (14, 28, 54), (mx + 2, ly), (mx + mw - 2, ly), 1)
        pygame.draw.circle(s, (20, 44, 82), (cx_m, cy_m), 34, 1)
        pygame.draw.circle(s, (16, 34, 64), (cx_m, cy_m), 54, 1)

        sweep_ang = (self.elapsed * 2.4) % math.tau
        end_x = cx_m + int(math.cos(sweep_ang) * 58)
        end_y = cy_m + int(math.sin(sweep_ang) * 52)
        pygame.draw.line(s, (*sc["bullet"][:3],), (cx_m, cy_m), (end_x, end_y), 1)

        sx = mw / self.world_w
        sy = mh / self.world_h

        cam_x, cam_y = self.camera()
        vx = mx + int(cam_x * sx)
        vy = my + int(cam_y * sy)
        vw = max(10, int(W * sx))
        vh = max(8, int(H * sy))
        pygame.draw.rect(s, (55, 115, 185), (vx, vy, min(mw - (vx - mx), vw), min(mh - (vy - my), vh)), 1, border_radius=2)

        for ch in self.chests:
            pygame.draw.circle(s, GOLD, (int(mx + ch.x * sx), int(my + ch.y * sy)), 3)
        for o in self.orbs:
            if o.kind == "heal":
                pygame.draw.circle(s, GREEN, (int(mx + o.x * sx), int(my + o.y * sy)), 2)
            elif o.kind == "coin":
                pygame.draw.circle(s, GOLD, (int(mx + o.x * sx), int(my + o.y * sy)), 1)
        for e in self.enemies:
            if not e.alive:
                continue
            ex = int(mx + e.x * sx)
            ey = int(my + e.y * sy)
            if e.boss:
                pygame.draw.circle(s, GOLD, (ex, ey), 4)
                pygame.draw.circle(s, RED, (ex, ey), 6, 1)
            elif e.kind == "Elite":
                pygame.draw.circle(s, ORANGE, (ex, ey), 3)
            else:
                pygame.draw.circle(s, RED, (ex, ey), 2)

        if self.partner:
            p2x = int(mx + self.partner.x * sx)
            p2y = int(my + self.partner.y * sy)
            p2_col = GREEN if self.game_mode == "coop" else ORANGE
            pygame.draw.circle(s, WHITE, (p2x, p2y), 4)
            pygame.draw.circle(s, p2_col, (p2x, p2y), 3)

        px = int(mx + self.player.x * sx)
        py = int(my + self.player.y * sy)
        pygame.draw.circle(s, WHITE, (px, py), 4)
        pygame.draw.circle(s, sc["bullet"], (px, py), 3)
        biome_name = ARENA_BIOMES[self.bosses % len(ARENA_BIOMES)]["name"]
        draw_text(s, f"MAPA: {biome_name[:14].upper()}", TINY, (130, 175, 225), (mx + 6, my + 4))
        draw_text(s, f"{len(self.enemies)} ALVOS", TINY, RED if len(self.enemies) > 50 else (150, 185, 220), (mx + mw - 64, my + 4))

    def draw_hud(self, s):
        p = self.player
        sc = self.get_skin_colors()
        skin_meta = self.get_selected_skin_meta()
        mx, my = pygame.mouse.get_pos()

        if p.hp < p.maxhp * 0.30 and not self.settings.get("reduce_flash", False):
            pulse = int(75 + math.sin(self.elapsed * 9) * 45)
            pygame.draw.rect(s, (235, 25, 45), (0, 0, W, H), max(3, pulse // 16))

        cam_x, cam_y = self.camera()
        important_targets = [(e.x, e.y, GOLD if e.boss else ORANGE, "BOSS" if e.boss else "ELITE") for e in self.enemies if e.alive and (e.boss or e.kind == "Elite")]
        important_targets += [(ch.x, ch.y, GOLD, "BAÚ") for ch in self.chests]
        for tx, ty, tcol, tlabel in important_targets[:6]:
            sx_t, sy_t = tx - cam_x, ty - cam_y
            if not (25 <= sx_t <= W - 25 and 25 <= sy_t <= H - 25):
                ang = math.atan2(sy_t - H / 2, sx_t - W / 2)
                ix = int(clamp(W / 2 + math.cos(ang) * (W / 2 - 42), 36, W - 36))
                iy = int(clamp(H / 2 + math.sin(ang) * (H / 2 - 58), 46, H - 72))
                p1 = (ix + math.cos(ang) * 12, iy + math.sin(ang) * 12)
                p2 = (ix + math.cos(ang + 2.4) * 9, iy + math.sin(ang + 2.4) * 9)
                p3 = (ix + math.cos(ang - 2.4) * 9, iy + math.sin(ang - 2.4) * 9)
                pygame.draw.polygon(s, tcol, [p1, p2, p3])
                pygame.draw.polygon(s, WHITE, [p1, p2, p3], 1)
                draw_text(s, tlabel, TINY, tcol, (ix, iy - 14), True)

        rect_left = pygame.Rect(18, 16, 386, 126)
        hover_left = rect_left.collidepoint(mx, my)
        draw_panel(s, rect_left, (14, 26, 52, 238) if hover_left else (10, 18, 38, 228), sc["bullet"] if hover_left else (40, 90, 155), 14)

        port_cx, port_cy = 58, 66
        pygame.draw.circle(s, (6, 12, 26), (port_cx, port_cy), 30)
        pygame.draw.circle(s, sc["bullet"], (port_cx, port_cy), 30, 2)
        self.draw_orb_preview(s, port_cx, port_cy - 3, self.profile["selected_skin"], scale=0.95)

        hex_pts = [(port_cx + math.cos(k * math.tau / 6) * 16, port_cy + 42 + math.sin(k * math.tau / 6) * 11) for k in range(6)]
        pygame.draw.polygon(s, (18, 38, 74), hex_pts)
        pygame.draw.polygon(s, GOLD, hex_pts, 2)
        draw_text(s, f"NV {self.level}", TINY, GOLD, (port_cx, port_cy + 42), True)

        bar_x, bar_w = 100, 288
        ghost_frac = clamp(getattr(p, "ghost_hp", p.hp) / p.maxhp, 0, 1)
        hp_frac = clamp(p.hp / p.maxhp, 0, 1)
        hp_col = GREEN if hp_frac > 0.5 else (GOLD if hp_frac > 0.25 else RED)
        draw_glossy_bar(s, pygame.Rect(bar_x, 26, bar_w, 22), hp_frac, hp_col, (18, 28, 48), ghost_frac, (240, 140, 35), segments=6, border_col=(65, 115, 180))
        if p.shield > 0:
            sh_w = min(bar_w, int(bar_w * clamp(p.shield / p.maxhp, 0.0, 1.0)))
            pygame.draw.rect(s, (0, 225, 255), (bar_x, 26, sh_w, 22), 2, border_radius=10)
        draw_text(s, f"HP {int(max(0, p.hp))}/{int(p.maxhp)}" + (f"  (+{int(p.shield)} ESCUDO)" if p.shield > 0 else ""), TINY, WHITE, (bar_x + bar_w // 2, 37), True)

        ult_frac = clamp(p.ult_charge / 100.0, 0.0, 1.0)
        ult_col = GOLD if ult_frac >= 1.0 else sc["body"]
        draw_glossy_bar(s, pygame.Rect(bar_x, 56, bar_w, 14), ult_frac, ult_col, (16, 24, 44), segments=4, border_col=GOLD if ult_frac >= 1.0 else (45, 80, 135))
        short_ult = skin_meta.get("ult_name", "SUPREMO")
        ult_label = f"{short_ult} [Q]: PRONTO!" if ult_frac >= 1.0 else f"{short_ult} [Q]: {int(p.ult_charge)}%"
        draw_icon(s, "bolt", (bar_x + 8, 80), 6, GOLD if ult_frac >= 1.0 else (195, 215, 245))
        draw_text(s, ult_label, TINY, GOLD if ult_frac >= 1.0 else (195, 215, 245), (bar_x + 20, 74))

        regen_txt = f"+{p.regen:.1f}/s" if p.regen > 0 else "0.0/s"
        draw_text(s, f"SLOT {self.current_slot}  •  REGEN {regen_txt}  •  AUTO [E]: {'ON' if self.auto_fire else 'OFF'}", TINY, GREEN if self.auto_fire else (145, 175, 210), (bar_x + 4, 94))
        chips = []
        if p.invuln > 0:
            chips.append(("INVULNERÁVEL", (255, 235, 130)))
        if p.dash_time > 0:
            chips.append(("IMPULSO", CYAN))
        if getattr(p, "killboost_timer", 0) > 0:
            chips.append(("FRENESI", ORANGE))
        if p.shield > 0:
            chips.append((f"ESCUDO {int(p.shield)}", (90, 210, 255)))
        if p.last_chance:
            chips.append(("ÚLTIMA CHANCE", GOLD))
        if getattr(p, "burn_t", 0) > 0:
            chips.insert(0, ("QUEIMANDO", (255, 120, 40)))
        if getattr(p, "poison_t", 0) > 0:
            chips.insert(0, ("ENVENENADO", (120, 255, 100)))
        if getattr(p, "terrain_accel", 1.0) < 1.0:
            chips.insert(0, ("NO GELO", (170, 225, 255)))
        if getattr(p, "terrain_speed", 1.0) > 1.0:
            chips.insert(0, ("IMPULSO DE ENERGIA", (0, 220, 255)))
        chip_x = bar_x
        for label_c, col_c in chips:
            img_c = get_cached_text(label_c, TINY, col_c)
            w_c = img_c.get_width() + 14
            if chip_x + w_c > rect_left.right - 8:
                break
            r_c = pygame.Rect(chip_x, 112, w_c, 18)
            pygame.draw.rect(s, (8, 16, 34), r_c, border_radius=8)
            pygame.draw.rect(s, col_c, r_c, 1, border_radius=8)
            s.blit(img_c, (r_c.x + 7, r_c.y + 2))
            chip_x += w_c + 6

        self.draw_minimap(s)
        if self.save_indicator_timer > 0:
            draw_icon(s, "check", (28, 291), 6, GREEN)
            draw_text(s, f"GRAVADO EM SAVES/SLOT {self.current_slot} [F5]", TINY, GREEN, (38, 284))
        else:
            draw_text(s, "F5: Salvar Rápido  |  ESC: Pausa  |  TAB: Inventário", TINY, (125, 160, 200), (22, 284))

        rect_right = pygame.Rect(W - 292, 16, 274, 118)
        hover_right = rect_right.collidepoint(mx, my)
        draw_panel(s, rect_right, (14, 26, 52, 238) if hover_right else (10, 18, 38, 228), sc["bullet"] if hover_right else (40, 90, 155), 14)

        mins, secs = int(self.elapsed // 60), int(self.elapsed % 60)
        draw_icon(s, "clock", (W - 266, 34), 9, CYAN)
        draw_text(s, f"{mins:02d}:{secs:02d}", MED, CYAN, (W - 250, 21))
        next_boss_lvl = ((self.level // 10) + 1) * 10
        boss_alive = any(e.boss and e.alive for e in self.enemies)
        if boss_alive:
            img_b = get_cached_text("CHEFE EM COMBATE", TINY, RED)
            s.blit(img_b, (W - 38 - img_b.get_width(), 22))
        else:
            tag_b = f"CHEFE NV {next_boss_lvl}"
            img_b = get_cached_text(tag_b, TINY, ORANGE)
            s.blit(img_b, (W - 38 - img_b.get_width(), 22))
            img_b2 = get_cached_text(f"em {next_boss_lvl - self.level} níveis", TINY, (200, 150, 90))
            s.blit(img_b2, (W - 38 - img_b2.get_width(), 36))
        biome_now = ARENA_BIOMES[self.bosses % len(ARENA_BIOMES)]
        draw_icon(s, "diamond", (W - 266, 54), 5, biome_now["border_inner"])
        draw_text(s, biome_now["name"].upper(), TINY, biome_now["border_inner"], (W - 254, 48))
        draw_icon(s, "skull", (W - 266, 71), 6, (205, 220, 245))
        draw_text(s, f"{self.kills}", SMALL, (205, 225, 250), (W - 254, 63))
        draw_icon(s, "crown", (W - 176, 71), 6, GOLD)
        draw_text(s, f"{self.bosses}", SMALL, (205, 225, 250), (W - 163, 63))
        draw_coin_icon(s, (W - 266, 89), 6, self.elapsed * 5.0)
        draw_text(s, f"{self.profile.get('coins', 0)}  (+{self.run_coins})", SMALL, GOLD, (W - 254, 81))

        if self.combo > 1:
            combo_frac = clamp(self.combo_timer / 3.2, 0.0, 1.0)
            draw_glossy_bar(s, pygame.Rect(W - 274, 104, 238, 14), combo_frac, GOLD if self.combo >= 15 else ORANGE, (20, 26, 46), border_col=GOLD)
            draw_text(s, f"COMBO {self.combo}x (+{min(50, self.combo)}% XP)", TINY, WHITE, (W - 155, 111), True)
        else:
            draw_text(s, f"Recorde de combo: {self.max_combo}x", TINY, (120, 150, 185), (W - 274, 106))

        if not self.settings.get("compact_hud", False):
            self.draw_status_panel(s)

        if self.game_mode == "pvp" and self.partner:
            pvp_panel = pygame.Rect(W // 2 - 270, 14, 540, 66)
            draw_panel(s, pvp_panel, (24, 12, 34, 242), GOLD, 12)
            draw_icon(s, "sword", (pvp_panel.x + 22, 27), 7, GOLD)
            draw_text(s, f"DUELO PVP 1V1 (SALA {self.net.room_code}) • RODADA {self.pvp_round} • VOCÊ {self.pvp_p1_wins} x {self.pvp_p2_wins} RIVAL", TINY, GOLD, (W // 2 + 8, 27), True)
            r_frac = clamp(self.partner.hp / self.partner.maxhp, 0.0, 1.0)
            r_ghost = clamp(self.partner.ghost_hp / self.partner.maxhp, 0.0, 1.0)
            draw_glossy_bar(s, pygame.Rect(W // 2 - 246, 44, 492, 20), r_frac, RED, (28, 14, 24), r_ghost, ORANGE, segments=8, border_col=GOLD)
            draw_text(s, f"RIVAL ORB: {int(max(0, self.partner.hp))}/{int(self.partner.maxhp)} HP  (+{int(self.partner.shield)} ESCUDO)", TINY, WHITE, (W // 2, 54), True)
        elif self.game_mode == "coop" and self.partner and not any(e.boss for e in self.enemies):
            coop_panel = pygame.Rect(W // 2 - 210, 14, 420, 44)
            c_border = ORANGE if self.partner.downed else GREEN
            draw_panel(s, coop_panel, (10, 26, 38, 230), c_border, 10)
            p2_st = "CAÍDO! APROXIME-SE!" if self.partner.downed else f"{int(self.partner.hp)}/{int(self.partner.maxhp)} HP"
            draw_icon(s, "users", (coop_panel.x + 22, 26), 7, c_border)
            draw_text(s, f"CO-OP SALA {self.net.room_code}  •  PARCEIRO: {p2_st}", TINY, c_border, (W // 2 + 8, 26), True)
            draw_glossy_bar(s, pygame.Rect(W // 2 - 190, 38, 380, 10), clamp(self.partner.hp / self.partner.maxhp, 0.0, 1.0), c_border, (14, 24, 38))

        if self.pvp_banner_timer > 0 and self.pvp_banner_text:
            draw_text(s, self.pvp_banner_text, MED, GOLD, (W // 2, 102), True)

        if getattr(self, "phase_event_active", None):
            rem = max(0.0, getattr(self, "phase_event_ttl", 0))
            total = getattr(self, "phase_event_total", 0.0) or (7.5 + min(4.0, self.level * 0.15))
            frac = clamp(rem / max(0.01, total), 0.0, 1.0)
            label = self.phase_event_label or {"xp_rain": "CHUVA DE XP", "enemy_rain": "CHUVA DE INIMIGOS", "mixed_storm": "TEMPESTADE"}.get(self.phase_event_active, "EVENTO")
            col = GOLD if "XP" in label else RED if "INIMIGOS" in label else ORANGE
            panel = pygame.Rect(W // 2 - 180, 108, 360, 42)
            draw_panel(s, panel, (12, 18, 36, 230), col, 10)
            draw_text(s, label, SMALL, col, (W // 2, 118), True)
            bar = pygame.Rect(W // 2 - 150, 132, 300, 10)
            pygame.draw.rect(s, (30, 40, 60), bar, border_radius=4)
            pygame.draw.rect(s, col, (bar.x, bar.y, int(bar.w * frac), bar.h), border_radius=4)
            draw_text(s, f"{rem:.1f}s", TINY, WHITE, (W // 2, 137), True)

        if any(e.boss for e in self.enemies):
            boss = next(e for e in self.enemies if e.boss)
            bc = boss.color
            ease_b = clamp((3.5 - self.boss_banner_timer) / 0.45, 0.0, 1.0) if self.boss_banner_timer > 0 else 1.0
            by0 = 14 - int((1.0 - ease_b) * 110)
            boss_panel = pygame.Rect(W // 2 - 300, by0, 600, 80)
            b_light = tuple(min(255, c + 70) for c in bc)
            draw_panel(s, boss_panel, (int(14 + bc[0] * 0.10), int(8 + bc[1] * 0.06), int(18 + bc[2] * 0.10), 244), b_light, 12)
            draw_icon(s, "skull", (boss_panel.x + 24, by0 + 24), 9, b_light)
            draw_text(s, boss.name.upper(), SMALL, b_light, (boss_panel.x + 42, by0 + 12))
            draw_text(s, "AMEAÇA COLOSSAL", TINY, RED, (boss_panel.x + 42, by0 + 28))
            for ph_i in range(3):
                draw_icon(s, "diamond", (boss_panel.right - 28 - ph_i * 20, by0 + 23), 6, b_light if ph_i < boss.phase else (50, 60, 85))
            draw_text(s, f"FASE {boss.phase}", TINY, (210, 220, 240), (boss_panel.right - 112, by0 + 16), False)
            b_frac = clamp(boss.hp / boss.maxhp, 0.0, 1.0)
            bx_bar, bw_bar = boss_panel.x + 20, boss_panel.w - 40
            draw_glossy_bar(s, pygame.Rect(bx_bar, by0 + 40, bw_bar, 22), b_frac, bc, (26, 12, 22), segments=10, border_col=b_light)
            for p_mark in (0.30, 0.65):
                mx_line = bx_bar + int(bw_bar * p_mark)
                pygame.draw.line(s, WHITE, (mx_line, by0 + 38), (mx_line, by0 + 64), 2)
            draw_text(s, f"{int(max(0, boss.hp))} / {int(boss.maxhp)}  ({int(b_frac * 100)}%)", TINY, WHITE, (W // 2, by0 + 51), True)
            if boss.charge > 0 and ease_b >= 1.0:
                warn_r = pygame.Rect(W // 2 - 130, by0 + 86, 260, 22)
                blink = 0.6 + 0.4 * math.sin(self.elapsed * 18)
                pygame.draw.rect(s, (int(70 * blink), 8, 14), warn_r, border_radius=10)
                pygame.draw.rect(s, RED, warn_r, 1, border_radius=10)
                draw_icon(s, "warn", (warn_r.x + 16, warn_r.centery), 7, (255, 200, 90))
                draw_text(s, "ATAQUE ESPECIAL: INVESTIDA!", TINY, WHITE, (warn_r.centerx + 8, warn_r.centery), True)

        if self.boss_banner_timer > 0:
            draw_icon(s, "warn", (W // 2 - 270, 150), 16, RED)
            draw_icon(s, "warn", (W // 2 + 270, 150), 16, RED)
            draw_text(s, "ALERTA DE CHEFE COLOSSAL!", BIG, RED, (W // 2, 150), True)

        if self.achievement_banners:
            b_ach = self.achievement_banners[0]
            ab_y = 120 if any(e.boss for e in self.enemies) else 88
            banner_rect = pygame.Rect(W // 2 - 220, ab_y, 440, 58)
            draw_panel(s, banner_rect, (18, 32, 62, 245), GOLD, 12)
            draw_text(s, b_ach["title"], FONT, GOLD, (W // 2, ab_y + 18), True)
            draw_text(s, b_ach["sub"], SMALL, WHITE, (W // 2, ab_y + 42), True)

        dock_w, dock_h = 396, 54
        dock_x, dock_y = W // 2 - dock_w // 2, H - 98
        draw_panel(s, (dock_x, dock_y, dock_w, dock_h), (10, 22, 46, 238), sc["bullet"], 13)

        if p.acquired:
            counts_h, order_h = {}, []
            for cname in p.acquired:
                if cname not in counts_h:
                    order_h.append(cname)
                counts_h[cname] = counts_h.get(cname, 0) + 1
            shown_h = order_h[-18:]
            step_h = 22
            hx0 = W // 2 - (len(shown_h) * step_h) // 2 + step_h // 2
            hy0 = dock_y - 16
            hover_card = None
            for i_h, cname in enumerate(shown_h):
                col_h, cmeta = card_rarity_color(cname)
                hxc = hx0 + i_h * step_h
                draw_icon(s, "diamond", (hxc, hy0), 8, col_h)
                if counts_h[cname] > 1:
                    draw_text(s, str(counts_h[cname]), TINY, WHITE, (hxc + 5, hy0 + 2))
                if abs(mx - hxc) <= 10 and abs(my - hy0) <= 10:
                    hover_card = (cname, cmeta, col_h)
            if hover_card:
                tip_w = 300
                tip = pygame.Rect(clamp(mx - tip_w // 2, 10, W - tip_w - 10), hy0 - 70, tip_w, 54)
                draw_panel(s, tip, (8, 16, 36, 248), hover_card[2], 10, 4)
                draw_text(s, hover_card[0], SMALL, hover_card[2], (tip.x + 10, tip.y + 6))
                for li_t, ln_t in enumerate(wrap_text_px(TINY, hover_card[1]["desc"] if hover_card[1] else "", tip_w - 20)[:2]):
                    draw_text(s, ln_t, TINY, (200, 220, 245), (tip.x + 10, tip.y + 26 + li_t * 13))

        dash_frac = 1.0 if (p.dash and p.dash_cd <= 0) else (clamp(1.0 - p.dash_cd / 2.8, 0.0, 1.0) if p.dash else 0.0)
        dash_txt = "PRONTO" if (p.dash and p.dash_cd <= 0) else (f"{p.dash_cd:.1f}s" if p.dash else "BLOQ.")
        pet_name = self.pet.meta["name"].split()[0] if self.pet else "NENHUM"

        slots_info = [
            ("Q", "SUPREMO", f"{int(p.ult_charge)}%", ult_frac, GOLD if ult_frac >= 1.0 else sc["bullet"]),
            ("ESP", "IMPULSO", dash_txt, dash_frac, CYAN if dash_frac >= 1.0 else (110, 140, 175)),
            ("E", "AUTO-TIRO", "ATIVO" if self.auto_fire else "OFF", 1.0 if self.auto_fire else 0.0, GREEN if self.auto_fire else (110, 140, 175)),
            ("PET", "MASCOTE", pet_name.upper(), 1.0 if self.pet else 0.0, self.pet.meta["color"] if self.pet else (110, 140, 175)),
        ]
        for idx_s, (key_lbl, title_lbl, val_lbl, s_frac, s_col) in enumerate(slots_info):
            sx_slot = dock_x + 12 + idx_s * 90
            sy_slot = dock_y + 6
            rc_x, rc_y = sx_slot + 18, sy_slot + 20
            pygame.draw.circle(s, (18, 32, 58), (rc_x, rc_y), 16)
            if s_frac > 0.02:
                arc_rect = pygame.Rect(rc_x - 16, rc_y - 16, 32, 32)
                pygame.draw.arc(s, s_col, arc_rect, math.pi / 2 - s_frac * math.tau, math.pi / 2, 3)
            pygame.draw.circle(s, s_col if s_frac >= 1.0 else (50, 80, 125), (rc_x, rc_y), 16, 1)
            draw_text(s, key_lbl, TINY, WHITE, (rc_x, rc_y), True)
            draw_text(s, title_lbl, TINY, (150, 185, 220), (sx_slot + 38, sy_slot + 4))
            draw_text(s, val_lbl, TINY, s_col, (sx_slot + 38, sy_slot + 20))

        frac = clamp(self.xp / self.xp_need, 0, 1)
        draw_glossy_bar(s, pygame.Rect(18, H - 34, W - 36, 20), frac, sc["body"], (8, 15, 30), segments=10, border_col=sc["bullet"])
        draw_text(s, f"EXPERIÊNCIA (XP): {int(self.xp)} / {self.xp_need} ({int(frac * 100)}%)   •   NÍVEL ATUAL: {self.level}   •   [TAB] INVENTÁRIO TÁTICO", TINY, WHITE, (W // 2, H - 24), True)

        if pygame.key.get_pressed()[pygame.K_TAB]:
            tab_rect = pygame.Rect(W // 2 - 330, H // 2 - 210, 660, 390)
            draw_panel(s, tab_rect, (8, 16, 36, 245), GOLD, 16)
            biome_now = ARENA_BIOMES[self.bosses % len(ARENA_BIOMES)]["name"]
            draw_text(s, "INVENTÁRIO & TELEMETRIA TÁTICA [TAB]", MED, GOLD, (W // 2, tab_rect.y + 28), True)
            draw_text(s, f"Cenário Atual: {biome_now}   •   Skin: {skin_meta['name']}   •   Cartas Coletadas: {len(p.acquired)}", SMALL, CYAN, (W // 2, tab_rect.y + 58), True)
            pygame.draw.line(s, (45, 95, 165), (tab_rect.x + 24, tab_rect.y + 78), (tab_rect.right - 24, tab_rect.y + 78), 1)
            if p.acquired:
                counts = {}
                for cname in p.acquired:
                    counts[cname] = counts.get(cname, 0) + 1
                unique_cards = list(counts.items())[-18:]
                for idx_c, (cname, cnt) in enumerate(unique_cards):
                    cx_col = tab_rect.x + 36 + (idx_c % 2) * 305
                    cy_row = tab_rect.y + 94 + (idx_c // 2) * 28
                    c_meta = next((cd for cd in CARDS if cd["name"] == cname), None)
                    c_col = RARITY_COLORS.get(c_meta["rarity"], WHITE) if c_meta else WHITE
                    draw_icon(s, "diamond", (cx_col + 6, cy_row + 10), 6, c_col)
                    draw_text(s, f"{cname}" + (f" (x{cnt})" if cnt > 1 else ""), SMALL, c_col, (cx_col + 18, cy_row))
            else:
                draw_text(s, "Nenhuma carta coletada ainda nesta partida.", SMALL, (150, 175, 210), (W // 2, tab_rect.centery), True)

    def draw_status_panel(self, s):
        p = self.player
        sc = self.get_skin_colors()
        mx, my = pygame.mouse.get_pos()
        rect_status = pygame.Rect(W - 232, 144, 214, 206)
        hover_status = rect_status.collidepoint(mx, my)
        draw_panel(s, rect_status, (14, 26, 52, 230) if hover_status else (10, 18, 38, 218), (50, 115, 195) if hover_status else (35, 75, 130), 12)

        dps_est = p.damage * p.shots * p.fire_rate * (1.0 + p.crit * (p.crit_mult - 1.0))
        draw_icon(s, "bolt", (W - 205, 160), 7, GOLD)
        draw_text(s, f"DPS ESTIMADO: {int(dps_est)}", SMALL, GOLD, (W - 110, 160), True)
        pygame.draw.line(s, (35, 75, 130), (W - 218, 174), (W - 32, 174), 1)

        stats_rows = [
            ("sword", "Dano", f"{p.damage:.0f} ({p.shots}x)", clamp(p.damage / 120.0, 0.08, 1.0), RED),
            ("bolt", "Cadência", f"{p.fire_rate:.1f}/s", clamp(p.fire_rate / 12.0, 0.08, 1.0), CYAN),
            ("play", "Velocidade", f"{p.move_speed:.0f}", clamp(p.move_speed / 440.0, 0.08, 1.0), GREEN),
            ("star", "Crítico", f"{int(p.crit * 100)}% ({p.crit_mult:.1f}x)", clamp(p.crit / 0.80, 0.08, 1.0), GOLD),
            ("shield", "Armadura", f"{int(p.armor * 100)}%", clamp(p.armor / 0.72, 0.05, 1.0), PURPLE),
        ]
        for i, (ic_s, lbl_s, val_s, frac_s, col_s) in enumerate(stats_rows):
            ry = 182 + i * 27
            draw_icon(s, ic_s, (W - 210, ry + 6), 5, col_s)
            draw_text(s, lbl_s, TINY, (175, 205, 235), (W - 200, ry))
            draw_text(s, val_s, TINY, WHITE, (W - 110, ry))
            draw_glossy_bar(s, pygame.Rect(W - 218, ry + 16, 186, 5), frac_s, col_s, (16, 24, 42))

        if p.acquired:
            draw_text(s, f"Cartas ({len(p.acquired)}): " + " • ".join(p.acquired[-2:]), TINY, (145, 185, 225), (W - 125, 332), True)
        syns = getattr(p, "active_synergies", None)
        if syns:
            draw_text(s, "Sinergia: " + " · ".join(sorted(syns)), TINY, GOLD, (W - 125, 348), True)

    def draw_cards(self, s):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((5, 10, 25, 235))
        s.blit(overlay, (0, 0))
        draw_text(s, "SUBIU DE NÍVEL!", HUGE, CYAN, (W // 2, 65), True)
        draw_text(s, f"Escolha uma melhoria (1, 2 ou 3)   •   Suas Moedas: {self.profile.get('coins', 0)} $", FONT, WHITE, (W // 2, 120), True)

        cardw, cardh, gap = CARD_W, CARD_H, CARD_GAP
        start = (W - (3 * cardw + 2 * gap)) // 2
        mx, my = pygame.mouse.get_pos()

        for i, c in enumerate(self.cards):
            base_x = start + i * (cardw + gap)
            float_offset = math.sin(pygame.time.get_ticks() * 0.003 + i * 1.2) * 6
            y = CARD_Y + int(float_offset)
            card_angle = math.sin(pygame.time.get_ticks() * 0.002 + i * 1.0) * 2.5

            r_card = pygame.Rect(base_x, y, cardw, cardh)
            is_hover = r_card.collidepoint(mx, my)
            card_surf = render_upgrade_card(c, i, cardw, cardh, is_hover)

            rot_card = pygame.transform.rotozoom(card_surf, card_angle if not is_hover else 0, 1.0)
            rot_rect = rot_card.get_rect(center=(base_x + cardw // 2, y + cardh // 2))
            s.blit(rot_card, rot_rect.topleft)

        reroll_rect = pygame.Rect(W // 2 - 190, H - 78, 380, 44)
        can_free = self.player.rerolls > 0
        can_coin = self.profile.get("coins", 0) >= 25
        can_reroll = can_free or can_coin
        r_hover = reroll_rect.collidepoint(mx, my) and can_reroll
        pygame.draw.rect(s, (24, 58, 105) if r_hover else (14, 28, 52), reroll_rect, border_radius=10)
        pygame.draw.rect(s, GOLD if can_reroll else (70, 80, 100), reroll_rect, 2, border_radius=10)
        if can_free:
            lbl = f"SORTEAR NOVAS [R] ({self.player.rerolls} Grátis)"
        else:
            lbl = "SORTEAR NOVAS [R] (Custo: 25 Moedas $)"
        draw_text(s, lbl, FONT, GOLD if can_reroll else (110, 120, 140), reroll_rect.center, True)
        return reroll_rect

    def draw_orb_preview(self, s, cx, cy, skin_id, scale=1.0):
        sc = self.get_skin_colors(skin_id)
        t = pygame.time.get_ticks() / 1000.0
        r = int(16 * scale)
        draw_orb_character(
            s, (cx, cy), r, sc["body"], sc["shoe"], sc["glow"],
            t, True, flash=False, legs=True, face=True, scale=1.0
        )

    def ui_button(self, s, rect, text, accent, hover, icon=None, big=False):
        r = rect.move(0, -2) if hover else pygame.Rect(rect)
        draw_panel(s, r, (32, 78, 146, 250) if hover else (12, 26, 52, 242), (240, 250, 255) if hover else accent, 11, 6 if hover else 4)
        pygame.draw.rect(s, accent, (r.x + 5, r.y + 7, 4, r.h - 14), border_radius=2)
        pygame.draw.rect(s, accent, (r.right - 9, r.y + 7, 4, r.h - 14), border_radius=2)
        if hover:
            soft_glow(s, accent, r.center, r.w * 0.45, 42)
            pygame.draw.polygon(s, WHITE, [(r.right - 22, r.centery - 5), (r.right - 14, r.centery), (r.right - 22, r.centery + 5)])
        if icon:
            pygame.draw.circle(s, (8, 16, 34), (r.x + 28, r.centery), 13)
            pygame.draw.circle(s, accent, (r.x + 28, r.centery), 13, 1)
            draw_icon(s, icon, (r.x + 28, r.centery), 8, WHITE if hover else accent)
        draw_text(s, text, BTN_BIG if big else FONT, WHITE, (r.centerx + (10 if icon else 0), r.centery), True)

    def draw_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        now = time.perf_counter()
        if now - getattr(self, "_menu_seen", 0.0) > 0.3:
            self._menu_t0 = now
        self._menu_seen = now
        et = now - self._menu_t0
        ease = lambda i: clamp((et - i * 0.05) / 0.35, 0.0, 1.0)
        sc = self.get_skin_colors()
        accent = sc["bullet"]
        mx, my = pygame.mouse.get_pos()
        wide = W >= 1000
        k = clamp(H / 800.0, 0.72, 1.15)
        hero = (int(W * 0.255), int(H * 0.52)) if wide else None
        draw_menu_backdrop(s, t, accent, hero)

        # ---- logotipo
        logo_cy = int(76 * k)
        lg = ease(0)
        lo = int((1 - lg) * -30)
        for ox, oy in ((-4, 0), (4, 0), (0, -4), (0, 4), (-3, 3), (3, 3)):
            g_img = get_cached_text("BLUE ORB", LOGO_FONT, tuple(int(c * 0.30) for c in accent))
            s.blit(g_img, g_img.get_rect(center=(W // 2 + ox, logo_cy + lo + oy)))
        main_img = get_cached_text("BLUE ORB", LOGO_FONT, (225, 248, 255))
        s.blit(main_img, main_img.get_rect(center=(W // 2, logo_cy + lo)))
        sub_y = logo_cy + int(60 * k) + lo
        draw_spaced(s, "S U R V I V A L   A R E N A", SUB_FONT, accent, (W // 2, sub_y), 5)
        wline = int(220 + 40 * math.sin(t * 2))
        pygame.draw.line(s, accent, (W // 2 - wline // 2, sub_y + 16), (W // 2 + wline // 2, sub_y + 16), 2)

        # ---- heroi (bolinha azul protagonista)
        if hero:
            hx, hy = hero
            pulse = 1.0 + 0.06 * math.sin(t * 2.2)
            soft_glow(s, sc["glow"], (hx, hy), 190 * pulse, 70)
            soft_glow(s, accent, (hx, hy), 120 * pulse, 60)
            for i in range(16):
                a = t * (0.9 + (i % 3) * 0.25) + i * math.tau / 16
                rr = 105 + (i % 4) * 16 + math.sin(t * 1.7 + i) * 8
                px_, py_ = hx + math.cos(a) * rr, hy + math.sin(a) * rr * 0.62
                pygame.draw.circle(s, accent if i % 2 else sc["glow"], (int(px_), int(py_)), 2 + (i % 3))
            bob = int(math.sin(t * 2.0) * 7)
            pygame.draw.ellipse(s, (3, 7, 18), (hx - 52, hy + 92, 104, 22))
            self.draw_orb_preview(s, hx, hy + bob, self.profile["selected_skin"], scale=3.0)
            meta = self.get_selected_skin_meta()
            draw_text(s, meta["name"].upper(), MED, WHITE, (hx, hy + 138), True)
            draw_text(s, f"SUPREMO: {meta.get('ult_name', '')}", TINY, GOLD, (hx, hy + 164), True)

        # ---- dados reais do perfil
        max_lvl = self.highscores.get("max_level", 1)
        max_kills = self.highscores.get("max_kills", 0)
        best_slot = None
        for sl in (1, 2, 3):
            inf = self.get_slot_info(sl)
            if inf:
                max_lvl = max(max_lvl, inf.get("level", 1))
                max_kills = max(max_kills, inf.get("kills", 0))
                if best_slot is None or inf.get("level", 1) > best_slot[1]:
                    best_slot = (sl, inf.get("level", 1))
        coins = self.profile.get("coins", 0)
        n_ach = len(self.profile.get("achievements", []))

        # ---- coluna de acoes
        aw = min(int(W * 0.5), 680) if wide else W - 48
        x0 = W - aw - 56 if wide else 24
        play_top = sub_y + int(34 * k)
        play_h = int(92 * k)
        play = pygame.Rect(x0, play_top, aw, play_h)
        rects = []
        i_sel = 0
        e0 = ease(1)
        off0 = int((1 - e0) * 40)
        hov = play.collidepoint(mx, my) or self.kb_idx == i_sel
        pr = play.move(0, off0)
        for gi in range(3):
            gw = int((6 + 5 * math.sin(t * 3 - gi * 0.9)) + gi * 5)
            pygame.draw.rect(s, tuple(int(c * (0.7 - gi * 0.2)) for c in accent), pr.inflate(gw, gw), 2, border_radius=18)
        draw_panel(s, pr, (26, 108, 196, 250) if hov else (16, 78, 152, 246), (235, 250, 255) if hov else accent, 16, 8)
        soft_glow(s, accent, pr.center, pr.w * 0.5, 40 if hov else 24)
        draw_icon(s, "play", (pr.x + 60, pr.centery), int(26 * k), WHITE)
        draw_text(s, "JOGAR", BTN_BIG, WHITE, (pr.x + 110, pr.centery - int(34 * k)))
        sub_txt = f"Continuar: Slot {best_slot[0]} • Nível {best_slot[1]}" if best_slot else "Nova partida solo • escolha um slot"
        draw_text(s, sub_txt, SMALL, (190, 225, 250), (pr.x + 112, pr.centery + int(14 * k)))
        rects.append((play, "open_slots"))

        n_sk = len(self.profile.get("unlocked_skins", []))
        n_pt = len(self.profile.get("unlocked_pets", []))
        cards = [
            ("skins", "PERSONAGENS", "orb", f"{n_sk}/{len(SKINS)} cores e ataques supremos", CYAN),
            ("pets", "MASCOTES", "paw", f"{n_pt}/{len(PETS)} desbloqueados", GREEN),
            ("cards", "CARTAS", "cards", f"{len(CARDS)} habilidades em 10 raridades", PURPLE),
            ("bestiary", "INIMIGOS", "skull", f"{len(ENEMY_TYPES)} tipos • {BOSS_COUNT} chefes", RED),
            ("biomes", "BIOMAS", "biome", f"{len(ARENA_BIOMES)} cenários de arena", (80, 200, 255)),
            ("achievements", "CONQUISTAS", "trophy", f"{n_ach}/{len(ACHIEVEMENTS)} concluídas", GOLD),
            ("multiplayer", "MULTIJOGADOR", "users", "Co-op e PvP 1v1", DIVINE),
            ("shop", "LOJA", "coin", f"{coins} moedas", GOLD),
        ]
        gap = 12
        cw = (aw - 3 * gap) // 4
        ch = int(clamp(H * 0.15, 92, 124))
        gy = play.bottom + int(20 * k)
        for idx, (act, title, icon, sub, col) in enumerate(cards):
            r = pygame.Rect(x0 + (idx % 4) * (cw + gap), gy + (idx // 4) * (ch + gap), cw, ch)
            rects.append((r, act))
            e = ease(2 + idx)
            if e <= 0:
                continue
            draw_menu_card(s, r, title, sub, icon, col, r.collidepoint(mx, my) or self.kb_idx == len(rects) - 1, int((1 - e) * 30))
        small_y = gy + 2 * ch + gap + int(14 * k)
        small = [("how", "COMO JOGAR", "book", CYAN), ("settings", "CONFIGURAÇÕES", "gear", CYAN), ("quit", "SAIR", "exit", RED)]
        sw_ = (aw - 2 * gap) // 3
        sh_ = int(40 * k)
        for idx, (act, title, icon, col) in enumerate(small):
            r = pygame.Rect(x0 + idx * (sw_ + gap), small_y, sw_, sh_)
            rects.append((r, act))
            h = r.collidepoint(mx, my) or self.kb_idx == len(rects) - 1
            draw_panel(s, r, (22, 50, 96, 245) if h else (9, 18, 38, 232), (235, 245, 255) if h else (50, 95, 160), 10, 4)
            draw_icon(s, icon, (r.x + 22, r.centery), 8, col)
            draw_text(s, title, FONT if len(title) < 12 else SMALL, WHITE, (r.centerx + 8, r.centery), True)

        # ---- barra de progresso real
        bar_h = int(60 * k)
        bar = pygame.Rect(56, max(small_y + sh_ + 16, H - bar_h - 34), W - 112, bar_h)
        draw_panel(s, bar, (8, 16, 34, 232), (35, 75, 130), 12, 6)
        mm, ss = divmod(int(self.highscores.get("max_time", 0)), 60)
        stats = [("trophy", "MELHOR NÍVEL", f"Nv {max_lvl}", GOLD), ("skull", "MAIS ABATES", max_kills, RED),
                 ("clock", "MAIOR TEMPO", f"{mm:02d}:{ss:02d}", CYAN), ("bolt", "COMBO MÁX", f"{self.highscores.get('max_combo', 0)}x", ORANGE),
                 ("coin", "MOEDAS", coins, GOLD), ("star", "CONQUISTAS", f"{n_ach}/{len(ACHIEVEMENTS)}", GREEN)]
        sw2 = bar.w // len(stats)
        for idx, (icon, label, val, col) in enumerate(stats):
            bx = bar.x + idx * sw2
            draw_icon(s, icon, (bx + 26, bar.centery), 10, col)
            draw_text(s, label, TINY, (125, 160, 200), (bx + 46, bar.y + int(bar.h * 0.2)))
            draw_text(s, str(val), STAT_V, WHITE, (bx + 46, bar.y + int(bar.h * 0.45)))
        draw_text(s, f"v{GAME_VERSION}  •  PERFIL LOCAL  •  {self.cloud_status_text}", TINY, (90, 130, 170), (56, H - 24))
        hint = "SETAS/TAB: navegar    ENTER: selecionar    F11: tela cheia    ESC: sair"
        himg = get_cached_text(hint, TINY, (90, 130, 170))
        s.blit(himg, (W - 56 - himg.get_width(), H - 24))
        return rects

    # ------------------------------------------------------------------ BESTIARIO
    def _render_enemy_icon(self, key, boss_idx, size):
        """Desenha o inimigo REAL (mesmo Enemy.draw do jogo) numa superficie e reduz."""
        cache = getattr(self, "_best_en", None)
        if cache is None:
            cache = self._best_en = {}
        e = cache.get(key)
        if e is None:
            e = Enemy(100, 100, "Básico" if boss_idx else key, 1, bool(boss_idx), boss_idx or 1)
            cache[key] = e
        e.x, e.y = 100, 100
        surf = pygame.Surface((200, 200), pygame.SRCALPHA)
        try:
            e.draw(surf, 0, 0)
        except Exception:
            pygame.draw.circle(surf, e.color, (100, 100), int(e.r))
        crop = surf.get_bounding_rect()
        if crop.w < 2:
            return None
        icon = surf.subsurface(crop)
        sc_ = min(size / max(crop.w, crop.h), 1.6)
        return pygame.transform.smoothscale(icon, (max(2, int(crop.w * sc_)), max(2, int(crop.h * sc_))))

    def draw_bestiary(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, (90, 150, 230))
        tab = getattr(self, "bestiary_tab", "enemies")
        rects = []
        draw_text(s, "INIMIGOS E CHEFES", BIG, WHITE, (W // 2, 54), True)
        tw = 210
        for i, (act, label) in enumerate((("tab_enemies", f"INIMIGOS ({len(ENEMY_TYPES)})"), ("tab_bosses", f"CHEFES ({BOSS_COUNT})"))):
            r = pygame.Rect(W // 2 - tw - 8 + i * (tw + 16), 96, tw, 40)
            rects.append((r, act))
            on = (tab == "enemies") == (i == 0)
            h = r.collidepoint(mx, my) or self.kb_idx == len(rects) - 1
            self.ui_button(s, r, label, GOLD if on else (90, 150, 230), h or on)
        items = list(ENEMY_TYPES.keys()) if tab == "enemies" else list(range(1, BOSS_COUNT + 1))
        cols = 4
        rows = math.ceil(len(items) / cols)
        top = 156
        gap = 12
        avail_h = H - top - 96
        cw = (W - 2 * 60 - (cols - 1) * gap) // cols
        ch = int(clamp((avail_h - (rows - 1) * gap) / rows, 84, 132))
        for idx, it in enumerate(items):
            r = pygame.Rect(60 + (idx % cols) * (cw + gap), top + (idx // cols) * (ch + gap), cw, ch)
            hov = r.collidepoint(mx, my)
            if tab == "enemies":
                col, hp, sp, dmg, xp, _sc = ENEMY_TYPES[it]
                title, role = it, ENEMY_ROLES.get(it, "")
                stat = f"VIDA {hp}  VEL {sp}  DANO {dmg}"
                icon = self._render_enemy_icon(it, 0, min(ch - 30, 84))
            else:
                be = getattr(self, "_best_en", {}).get(("b", it)) or Enemy(100, 100, "Básico", 1, True, it)
                col, title = be.color, be.name
                nb = ARENA_BIOMES[it % len(ARENA_BIOMES)]["name"]
                role = f"Aparece no nível {it * 10}. Ao cair, o cenário vira {nb}."
                stat = f"VIDA {int(be.maxhp)}  DANO {int(be.damage)}"
                icon = self._render_enemy_icon(("b", it), it, min(ch - 26, 90))
            draw_panel(s, r, (22, 46, 90, 247) if hov else (10, 20, 42, 238), (235, 245, 255) if hov else col, 12, 5)
            if icon:
                s.blit(icon, icon.get_rect(center=(r.x + 52, r.centery)))
            tx = r.x + 104
            tcol = mix_color(col, WHITE, 0.45)
            ty = r.y + 10
            for ln in wrap_text_px(CARD_T, title, r.right - tx - 8)[:2]:
                draw_text(s, ln, CARD_T, tcol, (tx, ty))
                ty += 18
            draw_text(s, stat, TINY, GOLD, (tx, ty + 2))
            ty += 22
            for li, ln in enumerate(wrap_text_px(TINY, role, r.right - tx - 8)[:3]):
                draw_text(s, ln, TINY, (170, 200, 235), (tx, ty + li * 14))
        back = pygame.Rect(W // 2 - 110, H - 70, 220, 46)
        rects.append((back, "back"))
        self.ui_button(s, back, "VOLTAR", CYAN, back.collidepoint(mx, my) or self.kb_idx == len(rects) - 1, "back")
        return rects

    # ------------------------------------------------------------------ BIOMAS
    def draw_biomes(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, (90, 150, 230))
        rects = []
        draw_text(s, "12 ZONAS DOS CHEFES & VARIANTES", BIG, WHITE, (W // 2, 42), True)
        draw_text(s, "Cada Chefe possui a sua própria Zona. Os inimigos mudam de variante e ganham novas habilidades em cada área!", SMALL, (150, 185, 225), (W // 2, 76), True)
        cols = 4
        gap = 12
        top = 100
        rows = math.ceil(len(ARENA_BIOMES) / cols)
        cw = (W - 2 * 48 - (cols - 1) * gap) // cols
        ch = int(clamp((H - top - 82 - (rows - 1) * gap) / rows, 165, 200))
        rnd = random.Random(3)
        for idx, bm in enumerate(ARENA_BIOMES):
            zv = ZONE_VARIANTS[idx % len(ZONE_VARIANTS)]
            r = pygame.Rect(48 + (idx % cols) * (cw + gap), top + (idx // cols) * (ch + gap), cw, ch)
            hov = r.collidepoint(mx, my)
            draw_panel(s, r, (10, 20, 42, 242), (235, 245, 255) if hov else bm["border_inner"], 11, 4)
            pv = pygame.Rect(r.x + 8, r.y + 8, r.w - 16, int(ch * 0.40))
            pygame.draw.rect(s, bm["bg"], pv, border_radius=7)
            old_clip = s.get_clip()
            s.set_clip(pv)
            for (ncol, nal), (fx, fy, fr) in zip(bm["nebula"], ((.2, .6, .5), (.75, .35, .45), (.5, .85, .4))):
                nc = tuple(min(255, int(bm["bg"][c] + (ncol[c] - bm["bg"][c]) * 0.9)) for c in range(3))
                pygame.draw.circle(s, nc, (pv.x + int(pv.w * fx), pv.y + int(pv.h * fy)), int(pv.w * fr * 0.45))
            for gx in range(pv.x, pv.right, 22):
                pygame.draw.line(s, bm["grid"], (gx, pv.y), (gx, pv.bottom), 1)
            for gy_ in range(pv.y, pv.bottom, 22):
                pygame.draw.line(s, bm["grid"], (pv.x, gy_), (pv.right, gy_), 1)
            for k_ in range(18):
                sx_ = pv.x + int((rnd.random() * pv.w + t * 6 * (1 + k_ % 3)) % pv.w)
                sy_ = pv.y + int(rnd.random() * pv.h)
                pygame.draw.circle(s, bm["star_col"], (sx_, sy_), 1)
            s.set_clip(old_clip)
            pygame.draw.rect(s, bm["border_inner"], pv, 2, border_radius=7)
            draw_text(s, f"Z{idx + 1}: {bm['name'].upper()}", TINY, bm["border_inner"], (r.x + 10, pv.bottom + 6))
            draw_text(s, f"Chefe: {bm.get('boss_name', '')}", TINY, GOLD, (r.x + 10, pv.bottom + 22))
            draw_text(s, f"Variante: {zv['tag']}", TINY, zv["tint"], (r.x + 10, pv.bottom + 38))
            for li_h, ln_h in enumerate(wrap_text_px(TINY, zv["desc"], r.w - 20)[:2]):
                draw_text(s, ln_h, TINY, (190, 215, 240), (r.x + 10, pv.bottom + 54 + li_h * 14))
        back = pygame.Rect(W // 2 - 110, H - 62, 220, 44)
        rects.append((back, "back"))
        self.ui_button(s, back, "VOLTAR", CYAN, back.collidepoint(mx, my) or self.kb_idx == 0, "back")
        return rects

    # ------------------------------------------------------------------ PAUSA / DERROTA
    def draw_pause_screen(self, s):
        mx, my = pygame.mouse.get_pos()
        sc = self.get_skin_colors()
        accent = sc["bullet"]
        draw_veil(s, 205)
        pw = 580
        ph = int(min(H - 30, 560))
        panel = pygame.Rect(W // 2 - pw // 2, (H - ph) // 2, pw, ph)
        draw_panel(s, panel, (8, 16, 36, 246), accent, 18, 10)
        draw_text(s, "PAUSADO", BIG, accent, (W // 2, panel.y + 44), True)
        biome = ARENA_BIOMES[self.bosses % len(ARENA_BIOMES)]["name"].upper()
        draw_text(s, f"SLOT {self.current_slot}  •  {biome}  •  PROGRESSO SALVO", TINY, GREEN, (W // 2, panel.y + 80), True)
        mm, ss = divmod(int(self.elapsed), 60)
        boxes = [("clock", "TEMPO", f"{mm:02d}:{ss:02d}", CYAN), ("star", "NÍVEL", self.level, GOLD),
                 ("skull", "ABATES", self.kills, (255, 110, 110)), ("crown", "CHEFES", self.bosses, ORANGE)]
        bw = (pw - 48 - 3 * 10) // 4
        for i, (ic, lb, vl, cl) in enumerate(boxes):
            draw_stat_box(s, pygame.Rect(panel.x + 24 + i * (bw + 10), panel.y + 104, bw, 56), ic, lb, vl, cl)
        btns = [("CONTINUAR", "continue", GOLD, "play", True), ("CONFIGURAÇÕES", "settings", CYAN, "gear", False),
                ("PERSONAGEM / ATAQUE ESPECIAL", "skins", CYAN, "orb", False), ("SALVAR E VOLTAR AOS SLOTS", "slots", CYAN, "book", False),
                ("SALVAR E IR AO MENU", "menu", CYAN, "exit", False), ("REINICIAR SLOT DO ZERO", "restart", RED, "warn", False)]
        y0 = panel.y + 182
        bh = int(clamp((panel.bottom - 22 - y0) / len(btns) - 8, 32, 46))
        rects = []
        for i, (label, act, col, icon, big) in enumerate(btns):
            r = pygame.Rect(panel.x + 40, y0 + i * (bh + 8), pw - 80, bh)
            rects.append((r, act))
            self.ui_button(s, r, label, col, r.collidepoint(mx, my) or self.kb_idx == i, icon)
        return rects

    def draw_gameover_screen(self, s):
        mx, my = pygame.mouse.get_pos()
        draw_veil(s, 225)
        pw = 700
        ph = int(min(H - 30, 600))
        panel = pygame.Rect(W // 2 - pw // 2, (H - ph) // 2, pw, ph)
        draw_panel(s, panel, (16, 8, 22, 248), RED, 18, 10)
        draw_text(s, "VOCÊ CAIU EM COMBATE", BIG, RED, (W // 2, panel.y + 46), True)
        draw_text(s, f"Progresso no Nível {self.level} gravado no Slot {self.current_slot}", SMALL, GREEN, (W // 2, panel.y + 84), True)
        hs = self.highscores
        mm, ss = divmod(int(self.elapsed), 60)
        rec = lambda v, k: "RECORDE!" if v > 0 and v >= hs.get(k, 0) and v > 1 else None
        boxes = [("clock", "TEMPO", f"{mm:02d}:{ss:02d}", CYAN, rec(int(self.elapsed), "max_time")),
                 ("star", "NÍVEL", self.level, GOLD, rec(self.level, "max_level")),
                 ("skull", "ABATES", self.kills, (255, 110, 110), rec(self.kills, "max_kills")),
                 ("crown", "CHEFES", self.bosses, ORANGE, None),
                 ("bolt", "COMBO MÁX", f"{self.max_combo}x", ORANGE, rec(self.max_combo, "max_combo")),
                 ("coin", "MOEDAS GANHAS", f"+{self.run_coins}", GOLD, None)]
        bw = (pw - 48 - 2 * 12) // 3
        for i, (ic, lb, vl, cl, tg) in enumerate(boxes):
            draw_stat_box(s, pygame.Rect(panel.x + 24 + (i % 3) * (bw + 12), panel.y + 112 + (i // 3) * 68, bw, 58), ic, lb, vl, cl, tg)
        last = ", ".join(self.player.acquired[-4:]) if self.player.acquired else "Nenhuma"
        for li, ln in enumerate(wrap_text_px(SMALL, "Últimas cartas: " + last, pw - 60)[:2]):
            draw_text(s, ln, SMALL, (170, 200, 230), (W // 2, panel.y + 262 + li * 18), True)
        btns = [(f"CONTINUAR DO NÍVEL {self.level}", "continue_lvl", GOLD, "play"), ("RECOMEÇAR DO NÍVEL 1", "restart_zero", CYAN, "back"),
                ("ESCOLHER OUTRO SLOT", "slots", CYAN, "book"), ("VOLTAR AO MENU", "menu", CYAN, "exit")]
        y0 = panel.y + 312
        bh = int(clamp((panel.bottom - 24 - y0) / len(btns) - 10, 34, 50))
        rects = []
        for i, (label, act, col, icon) in enumerate(btns):
            r = pygame.Rect(panel.x + 70, y0 + i * (bh + 10), pw - 140, bh)
            rects.append((r, act))
            self.ui_button(s, r, label, col, r.collidepoint(mx, my) or self.kb_idx == i, icon)
        return rects

    def draw_multiplayer_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, DIVINE)

        draw_text(s, "LOBBY MULTIJOGADOR EM TEMPO REAL", BIG, DIVINE, (W // 2, 46), True)
        draw_icon(s, "cloud", (W // 2 - 255, 84), 8, GREEN)
        draw_text(s, f"{self.cloud_status_text}   •   {self.net.status_msg}", SMALL, GREEN, (W // 2 + 10, 84), True)

        rects = []

        # Painel de Sala com layout dividido (Esquerda: Código & Input | Direita: Botões sem sobreposição!)
        room_panel = pygame.Rect(W // 2 - 470, 108, 940, 114)
        draw_panel(s, room_panel, (12, 26, 52, 242), CYAN, 14, 6)

        badge_r = pygame.Rect(room_panel.x + 22, room_panel.y + 16, 420, 50)
        pygame.draw.rect(s, (8, 16, 34), badge_r, border_radius=10)
        pygame.draw.rect(s, GOLD, badge_r, 2, border_radius=10)
        draw_icon(s, "globe", (badge_r.x + 24, badge_r.centery), 10, GOLD)
        draw_text(s, "SALA ATIVA:", TINY, (175, 205, 235), (badge_r.x + 46, badge_r.y + 8))
        draw_text(s, self.net.room_code, MED, GOLD, (badge_r.x + 46, badge_r.y + 21))

        inp_txt = self.net.input_code if self.net.input_code else "DIGITE O CÓDIGO NO TECLADO..."
        draw_icon(s, "play", (room_panel.x + 32, room_panel.y + 88), 6, CYAN)
        draw_text(s, f"Entrar noutra sala:  [ {inp_txt} ]", SMALL, WHITE if self.net.input_code and not self.net.edit_server else (155, 190, 225), (room_panel.x + 48, room_panel.y + 70))
        srv_r = pygame.Rect(room_panel.x + 20, room_panel.y + 90, 520, 20)
        ed = self.net.edit_server
        pygame.draw.rect(s, (8, 16, 34), srv_r, border_radius=6)
        pygame.draw.rect(s, GOLD if ed else (60, 100, 150), srv_r, 1, border_radius=6)
        draw_text(s, "SERVIDOR: " + self.net.server_text + ("_" if ed and int(t * 2) % 2 == 0 else "") + ("   (ENTER confirma)" if ed else "   (clique para editar)"), TINY, GOLD if ed else (150, 185, 220), (srv_r.x + 8, srv_r.y + 4))
        rects.append((srv_r, "mp_server"))

        btn_create = pygame.Rect(room_panel.right - 380, room_panel.y + 16, 176, 40)
        btn_join = pygame.Rect(room_panel.right - 192, room_panel.y + 16, 172, 40)
        btn_sync = pygame.Rect(room_panel.right - 380, room_panel.y + 64, 360, 38)
        self.ui_button(s, btn_create, "CRIAR SALA", CYAN, btn_create.collidepoint(mx, my), "globe")
        self.ui_button(s, btn_join, "CONECTAR", GOLD, btn_join.collidepoint(mx, my), "play")
        self.ui_button(s, btn_sync, "SINCRONIZAR NUVEM AGORA", GREEN, btn_sync.collidepoint(mx, my), "cloud")
        rects.extend([(btn_create, "mp_create"), (btn_join, "mp_join"), (btn_sync, "mp_sync")])

        p1_panel = pygame.Rect(W // 2 - 470, 238, 452, 262)
        p2_panel = pygame.Rect(W // 2 + 18, 238, 452, 262)
        draw_panel(s, p1_panel, (14, 30, 58, 240), CYAN, 14, 6)
        draw_panel(s, p2_panel, (18, 24, 52, 240), GOLD, 14, 6)

        p1_skin = self.get_selected_skin_meta()
        p1_pet = next((pt for pt in PETS if pt["id"] == self.profile.get("selected_pet")), PETS[0])
        draw_icon(s, "orb", (p1_panel.x + 30, 266), 9, CYAN)
        draw_text(s, "JOGADOR 1 (VOCÊ)", MED, CYAN, (p1_panel.centerx + 8, 266), True)
        self.draw_orb_preview(s, p1_panel.centerx - 48, 340, p1_skin["id"], scale=1.55)
        draw_pet_sprite(s, p1_pet, p1_panel.centerx + 52, 340, 1.8, t, 1)
        draw_text(s, f"Skin: {p1_skin['name']}", FONT, WHITE, (p1_panel.centerx, 410), True)
        draw_text(s, f"Supremo [Q]: {p1_skin['ult_name']}", TINY, GOLD, (p1_panel.centerx, 438), True)
        draw_text(s, f"Mascote: {p1_pet['name']}", SMALL, p1_pet["color"], (p1_panel.centerx, 464), True)

        p2_skin = SKINS[self.partner_skin_idx % len(SKINS)]
        p2_pet = PETS[self.partner_pet_idx % len(PETS)]
        p2_title = "JOGADOR 2 (REDE ATIVA)" if self.net.connected_peer else "JOGADOR 2 (PARCEIRO / RIVAL)"
        draw_icon(s, "users", (p2_panel.x + 30, 266), 9, GOLD)
        draw_text(s, p2_title, MED, GOLD, (p2_panel.centerx + 10, 266), True)
        self.draw_orb_preview(s, p2_panel.centerx - 48, 340, p2_skin["id"], scale=1.55)
        draw_pet_sprite(s, p2_pet, p2_panel.centerx + 52, 340, 1.8, t + 1.2, -1)
        draw_text(s, f"Skin: {p2_skin['name']}", FONT, WHITE, (p2_panel.centerx, 404), True)
        draw_text(s, f"Mascote: {p2_pet['name']}", SMALL, p2_pet["color"], (p2_panel.centerx, 430), True)

        btn_p2_skin = pygame.Rect(p2_panel.x + 24, 452, 194, 36)
        btn_p2_pet = pygame.Rect(p2_panel.right - 218, 452, 194, 36)
        self.ui_button(s, btn_p2_skin, "SKIN P2", CYAN, btn_p2_skin.collidepoint(mx, my), "orb")
        self.ui_button(s, btn_p2_pet, "MASCOTE P2", GOLD, btn_p2_pet.collidepoint(mx, my), "paw")
        rects.extend([(btn_p2_skin, "mp_p2_skin"), (btn_p2_pet, "mp_p2_pet")])

        btn_coop = pygame.Rect(W // 2 - 470, 518, 452, 60)
        btn_pvp = pygame.Rect(W // 2 + 18, 518, 452, 60)
        _cl = self.net.connected_peer and self.net.role == "client"
        _on = self.net.connected_peer
        self.ui_button(s, btn_coop, "AGUARDANDO O ANFITRIÃO..." if _cl else ("INICIAR CO-OP ONLINE" if _on else "INICIAR CO-OP (PARCEIRO IA)"), GREEN, btn_coop.collidepoint(mx, my), "users")
        self.ui_button(s, btn_pvp, "AGUARDANDO O ANFITRIÃO..." if _cl else ("INICIAR DUELO PVP ONLINE" if _on else "INICIAR DUELO PVP (RIVAL IA)"), RED, btn_pvp.collidepoint(mx, my), "sword")
        rects.extend([(btn_coop, "mp_start_coop"), (btn_pvp, "mp_start_pvp")])

        draw_text(s, "Co-op: Lutem juntos contra as hordas e Chefes com Reanimação!  |  PvP: Duelo direto 1v1 na arena (Melhor de 3)!", SMALL, (180, 210, 240), (W // 2, 600), True)

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR AO MENU", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_shop_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, GOLD)

        draw_text(s, "MERCADO DE MOEDAS", BIG, GOLD, (W // 2, 48), True)
        wallet_r = pygame.Rect(W // 2 - 170, 82, 340, 38)
        draw_panel(s, wallet_r, (20, 32, 58, 240), GOLD, 10, 4)
        draw_coin_icon(s, (wallet_r.x + 28, wallet_r.centery), 9, t * 5.0)
        draw_text(s, f"SALDO ATUAL: {self.profile.get('coins', 0)} MOEDAS", FONT, GOLD, (wallet_r.centerx + 12, wallet_r.centery), True)

        rects = []
        upgrades = self.profile.setdefault("upgrades", {"dmg": 0, "hp": 0, "spd": 0, "mag": 0, "greed": 0})
        up_icons = {"dmg": ("sword", RED), "hp": ("heart", GREEN), "spd": ("bolt", CYAN), "mag": ("orb", PURPLE), "greed": ("coin", GOLD)}

        start_y = 136
        for i, up in enumerate(SHOP_UPGRADES):
            uid = up["id"]
            lvl = upgrades.get(uid, 0)
            max_l = up["max_lvl"]
            cost = int(up["base_cost"] * (1.35 ** lvl))
            by = start_y + i * 98
            panel_r = pygame.Rect(W // 2 - 450, by, 900, 86)
            hov_row = panel_r.collidepoint(mx, my)
            ic_name, ic_col = up_icons.get(uid, ("star", CYAN))
            draw_panel(s, panel_r, (18, 36, 68, 244) if hov_row else (12, 24, 46, 236), ic_col if hov_row else (50, 105, 180), 14, 5)

            # Emblema circular do Upgrade
            pygame.draw.circle(s, (8, 16, 32), (panel_r.x + 42, panel_r.centery), 26)
            pygame.draw.circle(s, ic_col, (panel_r.x + 42, panel_r.centery), 26, 2)
            draw_icon(s, ic_name, (panel_r.x + 42, panel_r.centery), 12, ic_col)

            draw_text(s, f"{up['name']}   •   Nível {lvl}/{max_l}", MED, WHITE, (panel_r.x + 84, by + 12))
            draw_text(s, up["desc"], SMALL, (180, 210, 240), (panel_r.x + 84, by + 42))
            draw_glossy_bar(s, pygame.Rect(panel_r.x + 84, by + 64, 510, 10), lvl / max(1, max_l), ic_col, (14, 22, 38), segments=max_l, border_col=ic_col)

            btn_r = pygame.Rect(panel_r.right - 228, by + 20, 208, 46)
            if lvl >= max_l:
                draw_panel(s, btn_r, (20, 68, 48, 245), GREEN, 10, 3)
                draw_icon(s, "check", (btn_r.x + 32, btn_r.centery), 8, GREEN)
                draw_text(s, "NÍVEL MÁXIMO", SMALL, GREEN, (btn_r.centerx + 10, btn_r.centery), True)
            else:
                can_buy = self.profile.get("coins", 0) >= cost
                hov = btn_r.collidepoint(mx, my) and can_buy
                if can_buy:
                    self.ui_button(s, btn_r, f"COMPRAR ({cost} $)", GOLD, hov, "coin")
                    rects.append((btn_r, f"buy_up_{uid}"))
                else:
                    draw_panel(s, btn_r, (18, 26, 44, 225), (75, 90, 115), 10, 3)
                    draw_icon(s, "coin", (btn_r.x + 26, btn_r.centery), 8, (120, 135, 160))
                    draw_text(s, f"COMPRAR ({cost} $)", SMALL, (130, 145, 170), (btn_r.centerx + 10, btn_r.centery), True)

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR AO MENU", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_skins_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, CYAN)
        self.sync_unlocks_from_progress()

        draw_text(s, "SKINS & ATAQUES ESPECIAIS [Q]", BIG, CYAN, (W // 2, 44), True)
        draw_text(s, f"Cada cor muda o visual do seu Ataque Especial [Q]   •   Moedas: {self.profile.get('coins', 0)} $", FONT, GOLD, (W // 2, 86), True)

        cols = 5
        card_w, card_h = 224, 260
        gap_x, gap_y = 16, 16
        start_x = (W - (cols * card_w + (cols - 1) * gap_x)) // 2
        start_y = 118
        rects = []

        for idx, sk in enumerate(SKINS):
            row = idx // cols
            col_i = idx % cols
            bx = start_x + col_i * (card_w + gap_x)
            by = start_y + row * (card_h + gap_y)
            r_card = pygame.Rect(bx, by, card_w, card_h)

            unlocked = sk["id"] in self.profile["unlocked_skins"]
            selected = self.profile["selected_skin"] == sk["id"]
            is_hover = r_card.collidepoint(mx, my)
            sc = self.get_skin_colors(sk["id"])

            border_c = GOLD if selected else (sc["bullet"] if unlocked else (65, 78, 102))
            bg_c = (24, 50, 92, 248) if (is_hover and unlocked) else (12, 24, 46, 238)
            draw_panel(s, r_card.move(0, -3 if is_hover else 0), bg_c, border_c, 14, 6)

            self.draw_orb_preview(s, bx + card_w // 2, by + 48, sk["id"], scale=1.25)

            name_f = SMALL if len(sk["name"]) > 16 else FONT
            draw_text(s, sk["name"], name_f, sc["bullet"] if unlocked else (145, 160, 185), (bx + card_w // 2, by + 104), True)
            draw_text(s, f"Q: {sk['ult_name']}", TINY, GOLD, (bx + card_w // 2, by + 126), True)

            # Quebra de linha automática para nunca vazar fora do cartão!
            for li_d, ln_d in enumerate(wrap_text_px(TINY, sk["desc"], card_w - 24)[:3]):
                draw_text(s, ln_d, TINY, (185, 210, 235), (bx + card_w // 2, by + 146 + li_d * 15), True)

            btn_rect = pygame.Rect(bx + 14, by + card_h - 48, card_w - 28, 36)
            if selected:
                draw_panel(s, btn_rect, (22, 78, 52, 248), GREEN, 9, 3)
                draw_icon(s, "check", (btn_rect.x + 28, btn_rect.centery), 7, GREEN)
                draw_text(s, "EQUIPADO", SMALL, GREEN, (btn_rect.centerx + 10, btn_rect.centery), True)
            elif unlocked:
                draw_cyber_button(s, btn_rect, "EQUIPAR COR", SMALL, sc["bullet"], is_hover, icon="orb")
                rects.append((r_card, f"skin_{sk['id']}"))
            else:
                cost = sk.get("coin_cost", 300)
                can_afford = self.profile.get("coins", 0) >= cost
                if can_afford:
                    draw_cyber_button(s, btn_rect, f"COMPRAR ({cost} $)", TINY, GOLD, is_hover, text_col=GOLD, icon="coin")
                    rects.append((r_card, f"buyskin_{sk['id']}"))
                else:
                    draw_panel(s, btn_rect, (18, 24, 38, 228), (75, 88, 112), 9, 2)
                    draw_text(s, sk["req_text"], TINY, GOLD, btn_rect.center, True)

        back_btn = pygame.Rect(W // 2 - 120, H - 64, 240, 44)
        self.ui_button(s, back_btn, "VOLTAR", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_pets_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, GREEN)

        draw_text(s, "MASCOTES (PETS)", BIG, CYAN, (W // 2, 44), True)
        draw_text(s, f"Um mascote te acompanha e ajuda na batalha   •   Moedas: {self.profile.get('coins', 0)} $", FONT, GOLD, (W // 2, 86), True)

        cols = 5
        card_w, card_h = 224, 260
        gap_x, gap_y = 16, 16
        start_x = (W - (cols * card_w + (cols - 1) * gap_x)) // 2
        start_y = 118
        rects = []

        for idx, pt in enumerate(PETS):
            row, col_i = idx // cols, idx % cols
            bx = start_x + col_i * (card_w + gap_x)
            by = start_y + row * (card_h + gap_y)
            r_card = pygame.Rect(bx, by, card_w, card_h)
            unlocked = pt["id"] in self.profile.get("unlocked_pets", [])
            selected = self.profile.get("selected_pet") == pt["id"]
            is_hover = r_card.collidepoint(mx, my)

            border_c = GOLD if selected else (pt["color"] if unlocked else (65, 78, 102))
            bg_c = (24, 50, 92, 248) if (is_hover and unlocked) else (12, 24, 46, 238)
            draw_panel(s, r_card.move(0, -3 if is_hover else 0), bg_c, border_c, 14, 6)

            bob = int(math.sin(t * 4 + idx) * 4)
            glow_circle(s, pt["color"], (bx + card_w // 2, by + 50 + bob), 28, 2)
            draw_pet_sprite(s, pt, bx + card_w // 2, by + 50 + bob, 2.1, t + idx, 1)

            draw_text(s, pt["name"], SMALL, pt["color"] if unlocked else (145, 160, 185), (bx + card_w // 2, by + 110), True)
            for j, ln in enumerate(wrap_text_px(TINY, pt["desc"], card_w - 24)[:3]):
                draw_text(s, ln, TINY, (185, 210, 235), (bx + card_w // 2, by + 136 + j * 16), True)

            btn_rect = pygame.Rect(bx + 14, by + card_h - 48, card_w - 28, 36)
            if selected:
                draw_panel(s, btn_rect, (22, 78, 52, 248), GREEN, 9, 3)
                draw_icon(s, "check", (btn_rect.x + 28, btn_rect.centery), 7, GREEN)
                draw_text(s, "EQUIPADO", SMALL, GREEN, (btn_rect.centerx + 10, btn_rect.centery), True)
            elif unlocked:
                draw_cyber_button(s, btn_rect, "EQUIPAR PET", SMALL, pt["color"], is_hover, icon="paw")
                rects.append((r_card, f"pet_{pt['id']}"))
            else:
                cost = pt["cost"]
                can_afford = self.profile.get("coins", 0) >= cost
                if can_afford:
                    draw_cyber_button(s, btn_rect, f"COMPRAR ({cost} $)", TINY, GOLD, is_hover, text_col=GOLD, icon="coin")
                    rects.append((r_card, f"buypet_{pt['id']}"))
                else:
                    draw_panel(s, btn_rect, (18, 24, 38, 228), (75, 88, 112), 9, 2)
                    draw_text(s, f"Faltam {cost - self.profile.get('coins', 0)} $ ({cost} $)", TINY, (155, 170, 195), btn_rect.center, True)

        back_btn = pygame.Rect(W // 2 - 120, H - 64, 240, 44)
        self.ui_button(s, back_btn, "VOLTAR", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_achievements_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, GOLD)
        self.sync_unlocks_from_progress()

        draw_text(s, "SALA DE CONQUISTAS", BIG, GOLD, (W // 2, 48), True)
        unlocked_count = len(self.profile["achievements"])
        total_ach = max(1, len(ACHIEVEMENTS))
        prog_f = unlocked_count / total_ach
        draw_glossy_bar(s, pygame.Rect(W // 2 - 230, 84, 460, 18), prog_f, GOLD, (14, 24, 44), segments=8, border_col=GOLD)
        draw_text(s, f"Conquistas Desbloqueadas: {unlocked_count} / {len(ACHIEVEMENTS)} ({int(prog_f * 100)}%)", TINY, WHITE, (W // 2, 93), True)

        cols = 2
        card_w, card_h = 530, 110
        gap_x, gap_y = 28, 18
        start_x = (W - (cols * card_w + gap_x)) // 2
        start_y = 122

        for idx, ach in enumerate(ACHIEVEMENTS[:8]):
            row = idx // cols
            col_i = idx % cols
            bx = start_x + col_i * (card_w + gap_x)
            by = start_y + row * (card_h + gap_y)
            done = ach["id"] in self.profile["achievements"]
            hov = pygame.Rect(bx, by, card_w, card_h).collidepoint(mx, my)

            border_c = GOLD if done else (55, 78, 115)
            bg_c = (22, 44, 80, 244) if done else (12, 20, 38, 228)
            draw_panel(s, (bx, by - (2 if hov else 0), card_w, card_h), bg_c, border_c, 12, 5)

            badge_pos = (bx + 44, by + card_h // 2)
            badge_col = GOLD if done else (55, 70, 95)
            glow_circle(s, badge_col, badge_pos, 20, 2 if done else 1)
            if done:
                draw_icon(s, "trophy", badge_pos, 10, (25, 18, 5))
            else:
                draw_icon(s, "star", badge_pos, 9, (180, 195, 220))

            draw_text(s, ach["name"], MED, GOLD if done else (165, 180, 205), (bx + 84, by + 14))
            draw_text(s, ach["desc"], SMALL, WHITE if done else (130, 150, 175), (bx + 84, by + 46))
            if done:
                draw_icon(s, "check", (bx + 92, by + 84), 6, GREEN)
                draw_text(s, f"CONCLUÍDA — {ach['reward']}", TINY, GREEN, (bx + 104, by + 76))
            else:
                draw_icon(s, "diamond", (bx + 92, by + 84), 5, CYAN)
                draw_text(s, f"Recompensa: {ach['reward']}", TINY, CYAN, (bx + 104, by + 76))

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR AO MENU", CYAN, back_btn.collidepoint(mx, my), "back")
        return [(back_btn, "back")]

    def draw_slots_menu(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, CYAN)

        draw_text(s, "ESCOLHA UM SLOT DE SALVAMENTO", BIG, CYAN, (W // 2, 54), True)
        draw_text(s, "O seu progresso, nível e habilidades das cartas são gravados automaticamente no slot escolhido", FONT, (185, 215, 245), (W // 2, 100), True)

        card_w, card_h = 336, 446
        gap = 34
        start_x = (W - (3 * card_w + 2 * gap)) // 2
        y = 144
        rects = []

        for slot in (1, 2, 3):
            bx = start_x + (slot - 1) * (card_w + gap)
            info = self.get_slot_info(slot)
            card_rect = pygame.Rect(bx, y, card_w, card_h)
            del_rect = pygame.Rect(bx + card_w - 44, y + 14, 30, 30)

            hover_del = info is not None and del_rect.collidepoint(mx, my)
            hover_card = card_rect.collidepoint(mx, my) and not hover_del

            border_c = GOLD if (info and hover_card) else (CYAN if hover_card else (48, 100, 170))
            bg_c = (22, 46, 86, 246) if hover_card else (12, 24, 48, 236)
            draw_panel(s, card_rect.move(0, -3 if hover_card else 0), bg_c, border_c, 16, 6)

            draw_text(s, f"SLOT {slot}", BIG, CYAN if not info else GOLD, (bx + card_w // 2, y + 40), True)
            pygame.draw.line(s, border_c, (bx + 25, y + 76), (bx + card_w - 25, y + 76), 2)

            if info:
                lvl = info.get("level", 1)
                el = int(info.get("elapsed", 0))
                kills = info.get("kills", 0)
                bosses = info.get("bosses", 0)
                hp = int(info.get("hp", 100))
                maxhp = int(info.get("maxhp", 100))
                shield = int(info.get("shield", 0))
                acq = info.get("acquired", [])

                draw_text(s, f"Nível {lvl}", MED, WHITE, (bx + card_w // 2, y + 106), True)
                draw_text(s, f"Tempo: {el // 60:02d}:{el % 60:02d}   •   Abates: {kills}", FONT, (190, 220, 245), (bx + card_w // 2, y + 140), True)
                draw_text(s, f"Vida: {hp}/{maxhp}   •   Escudo: {shield}", SMALL, GREEN, (bx + card_w // 2, y + 172), True)
                draw_text(s, f"Chefes Derrotados: {bosses}", SMALL, (170, 200, 230), (bx + card_w // 2, y + 198), True)

                pygame.draw.line(s, (30, 60, 105), (bx + 30, y + 222), (bx + card_w - 30, y + 222), 1)
                draw_text(s, f"Cartas Adquiridas ({len(acq)}):", SMALL, GOLD, (bx + card_w // 2, y + 242), True)

                if acq:
                    last_cards = acq[-4:]
                    for idx_c, c_name in enumerate(last_cards):
                        draw_text(s, f"• {c_name}", SMALL, WHITE, (bx + card_w // 2, y + 268 + idx_c * 22), True)
                    if len(acq) > 4:
                        draw_text(s, f"+ {len(acq) - 4} outras melhorias...", TINY, (150, 180, 215), (bx + card_w // 2, y + 358), True)
                else:
                    draw_text(s, "Nenhuma carta ainda", SMALL, (130, 155, 185), (bx + card_w // 2, y + 282), True)

                play_btn = pygame.Rect(bx + 24, y + card_h - 60, card_w - 48, 44)
                self.ui_button(s, play_btn, "CONTINUAR JOGO", GOLD, hover_card, "play")

                pygame.draw.rect(s, (175, 38, 55) if hover_del else (85, 22, 35), del_rect, border_radius=7)
                pygame.draw.rect(s, RED, del_rect, 1, border_radius=7)
                draw_text(s, "X", FONT, WHITE, del_rect.center, True)
                rects.append((del_rect, f"del_{slot}"))
                rects.append((card_rect, f"slot_{slot}"))
            else:
                self.draw_orb_preview(s, bx + card_w // 2, y + 185, self.profile["selected_skin"], scale=1.45)
                draw_text(s, "SLOT VAZIO", MED, (130, 160, 200), (bx + card_w // 2, y + 245), True)
                draw_text(s, "Clique para iniciar uma", SMALL, (110, 140, 175), (bx + card_w // 2, y + 280), True)
                draw_text(s, "nova partida neste slot.", SMALL, (110, 140, 175), (bx + card_w // 2, y + 302), True)

                play_btn = pygame.Rect(bx + 24, y + card_h - 60, card_w - 48, 44)
                self.ui_button(s, play_btn, "NOVO JOGO", CYAN, hover_card, "play")
                rects.append((card_rect, f"slot_{slot}"))

        draw_text(s, f"Pasta de gravação ativa: {SAVE_DIR}", TINY, (120, 155, 190), (W // 2, H - 100), True)

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR AO MENU", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_settings(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, CYAN)
        draw_text(s, "CONFIGURAÇÕES", BIG, CYAN, (W // 2, 38), True)
        rects = []

        # Seletor de Idiomas (Português BR, Inglês e Espanhol)
        lang_panel = pygame.Rect(W // 2 - 360, 72, 720, 50)
        draw_panel(s, lang_panel, (14, 28, 56, 242), GOLD, 12, 5)
        draw_icon(s, "globe", (lang_panel.x + 26, lang_panel.centery), 9, GOLD)
        draw_text(s, "IDIOMA / LANGUAGE:", FONT, WHITE, (lang_panel.x + 48, lang_panel.centery - 11))

        cur_lang = self.settings.get("language", "pt")
        lang_opts = [("pt", "PORTUGUÊS (BR)"), ("en", "ENGLISH"), ("es", "ESPAÑOL")]
        for i_l, (l_code, l_name) in enumerate(lang_opts):
            lb_r = pygame.Rect(lang_panel.x + 258 + i_l * 150, lang_panel.y + 7, 142, 36)
            is_sel = (cur_lang == l_code)
            is_hov = lb_r.collidepoint(mx, my) or self.kb_idx == len(rects)
            b_col = GOLD if is_sel else (CYAN if is_hov else (60, 100, 160))
            bg_c = (24, 72, 52, 248) if is_sel else ((28, 62, 112, 245) if is_hov else (10, 20, 40, 235))
            draw_panel(s, lb_r, bg_c, b_col, 9, 3)
            if is_sel:
                draw_icon(s, "check", (lb_r.x + 16, lb_r.centery), 6, GREEN)
                draw_text(s, l_name, TINY, GOLD, (lb_r.centerx + 7, lb_r.centery), True)
            else:
                draw_text(s, l_name, TINY, WHITE if is_hov else (180, 205, 235), lb_r.center, True)
            rects.append((lb_r, f"lang_{l_code}"))

        # Painel de Volume com Barra Gráfica Líquida e Botões Estilizados
        vol_panel = pygame.Rect(W // 2 - 360, 130, 720, 52)
        draw_panel(s, vol_panel, (12, 26, 52, 240), CYAN, 12, 5)
        draw_icon(s, "bolt", (vol_panel.x + 28, vol_panel.centery), 9, GOLD)
        draw_text(s, f"VOLUME GERAL: {int(self.settings['volume'] * 100)}%", FONT, WHITE, (vol_panel.x + 48, vol_panel.centery - 12))
        vol_minus = pygame.Rect(vol_panel.x + 290, vol_panel.centery - 16, 50, 32)
        vol_plus = pygame.Rect(vol_panel.right - 70, vol_panel.centery - 16, 50, 32)
        draw_glossy_bar(s, pygame.Rect(vol_minus.right + 14, vol_panel.centery - 8, vol_plus.x - vol_minus.right - 28, 16), self.settings["volume"], CYAN, (16, 28, 48), segments=10, border_col=CYAN)
        draw_cyber_button(s, vol_minus, "-", MED, CYAN, vol_minus.collidepoint(mx, my))
        draw_cyber_button(s, vol_plus, "+", MED, CYAN, vol_plus.collidepoint(mx, my))
        rects.append((vol_minus, "vol-"))
        rects.append((vol_plus, "vol+"))

        options = [
            ("Tremor de Câmara (Trauma)", "shake", "bolt"),
            ("Efeitos Visuais & Clima", "effects", "star"),
            ("Números de Dano Flutuantes", "damage_numbers", "sword"),
            ("Auto-Mira Inteligente", "smart_auto_aim", "orb"),
            ("Mostrar Hitboxes (F3)", "show_hitboxes", "shield"),
            ("Qualidade Gráfica", "quality", "diamond"),
            ("Reduzir Flashes (Fotossensível)", "reduce_flash", "heart"),
            ("HUD Compacta", "compact_hud", "cards"),
            ("Tela Cheia (F11)", "fullscreen", "globe")
        ]
        start_y = 190
        row_h = 42
        gap_y = 6
        for idx, (label, key, ic_name) in enumerate(options):
            y_pos = start_y + idx * (row_h + gap_y)
            row_r = pygame.Rect(W // 2 - 360, y_pos, 720, row_h)
            btn = pygame.Rect(row_r.right - 196, y_pos + 4, 184, row_h - 8)
            hov = row_r.collidepoint(mx, my) or self.kb_idx == len(rects)

            if key == "quality":
                q_val = self.settings.get("quality", 2)
                val_txt = ("BAIXA", "MÉDIA", "ALTA")[q_val]
                is_on = q_val > 0
                st_col = GOLD if q_val == 2 else (CYAN if q_val == 1 else (150, 165, 190))
            elif key == "fullscreen":
                is_on = bool(pygame.display.get_surface().get_flags() & pygame.FULLSCREEN)
                val_txt = "LIGADO" if is_on else "DESLIGADO"
                st_col = GREEN if is_on else (255, 85, 105)
            else:
                is_on = bool(self.settings.get(key, False))
                val_txt = "LIGADO" if is_on else "DESLIGADO"
                st_col = GREEN if is_on else (255, 85, 105)

            draw_panel(s, row_r, (20, 42, 78, 242) if hov else (11, 22, 44, 232), st_col if hov else (40, 82, 145), 11, 4)
            draw_icon(s, ic_name, (row_r.x + 26, row_r.centery), 8, st_col)
            draw_text(s, label, FONT, WHITE, (row_r.x + 48, row_r.centery - 11))

            sw_bg = (20, 68, 48) if is_on else (52, 20, 30)
            if key == "quality":
                sw_bg = (26, 56, 98)
            pygame.draw.rect(s, sw_bg, btn, border_radius=9)
            pygame.draw.rect(s, WHITE if hov else st_col, btn, 2, border_radius=9)
            knob_x = btn.right - 20 if is_on else btn.x + 20
            pygame.draw.circle(s, st_col, (knob_x, btn.centery), 8)
            pygame.draw.circle(s, WHITE, (knob_x, btn.centery), 4)
            draw_text(s, val_txt, SMALL, WHITE if hov else st_col, (btn.centerx - (8 if is_on else -8), btn.centery), True)
            rects.append((row_r, key))

        back_btn = pygame.Rect(W // 2 - 120, H - 56, 240, 42)
        self.ui_button(s, back_btn, "VOLTAR", CYAN, back_btn.collidepoint(mx, my) or self.kb_idx == len(rects), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_cards_view(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, PURPLE)
        draw_text(s, "CARTAS DE MELHORIA", BIG, CYAN, (W // 2, 48), True)

        items_per_page = 12
        total_pages = math.ceil(len(CARDS) / items_per_page)
        start_idx = self.cards_page * items_per_page
        end_idx = min(start_idx + items_per_page, len(CARDS))

        for i in range(start_idx, end_idx):
            c = CARDS[i]
            y_pos = 104 + (i - start_idx) * 41
            col = RARITY_COLORS[c["rarity"]]
            row_r = pygame.Rect(W // 2 - 470, y_pos, 940, 36)
            hov = row_r.collidepoint(mx, my)
            draw_panel(s, row_r, (24, 46, 86, 245) if hov else (12, 24, 46, 232), WHITE if hov else col, 8, 3)
            draw_icon(s, "diamond", (row_r.x + 20, row_r.centery), 6, col)
            draw_text(s, f"{c['name']}  [{c['rarity']}]", FONT, col, (row_r.x + 36, row_r.y + 6))
            draw_text(s, c["desc"], SMALL, WHITE, (W // 2 + 10, row_r.y + 8))

        draw_text(s, f"Página {self.cards_page + 1} de {total_pages} (Use a roda do rato)", SMALL, (175, 205, 235), (W // 2, H - 116), True)

        rects = []
        prev_btn = pygame.Rect(W // 2 - 260, H - 134, 130, 38)
        next_btn = pygame.Rect(W // 2 + 130, H - 134, 130, 38)

        if self.cards_page > 0:
            self.ui_button(s, prev_btn, "ANTERIOR", CYAN, prev_btn.collidepoint(mx, my), "back")
            rects.append((prev_btn, "prev_page"))

        if self.cards_page < total_pages - 1:
            self.ui_button(s, next_btn, "PRÓXIMA", CYAN, next_btn.collidepoint(mx, my), "play")
            rects.append((next_btn, "next_page"))

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR", CYAN, back_btn.collidepoint(mx, my), "back")
        rects.append((back_btn, "back"))
        return rects

    def draw_how_to_play(self, s):
        t = pygame.time.get_ticks() / 1000.0
        mx, my = pygame.mouse.get_pos()
        draw_menu_backdrop(s, t, CYAN)
        draw_text(s, "COMO JOGAR & COMANDOS TÁTICOS", BIG, CYAN, (W // 2, 52), True)
        lines = [
            ("play", "WASD / SETAS", "Mova a sua personagem pela arena desviando de cercos e perigos de terreno.", CYAN),
            ("sword", "RATO / TECLA E", "Aponte com o Rato. Botão Esquerdo dispara; Tecla E ou Botão Direito ativa Auto-Tiro.", GOLD),
            ("bolt", "TECLA Q (100%)", "Dispara o ATAQUE ESPECIAL SUPREMO exclusivo da Cor (Skin) equipada!", MYTHIC),
            ("coin", "MOEDAS DE OURO", "Colete moedas para comprar Upgrades Permanentes, Skins e Mascotes na Loja.", GOLD),
            ("trophy", "BAÚS DOURADOS", "Elites e Chefes largam Baús de Relíquia com moedas, cura, escudo e bónus permanentes.", ORANGE),
            ("cards", "TECLAS 1, 2, 3, R", "Ao subir de nível, escolha 1 entre 3 cartas holográficas ou pressione R para sortear novas.", PURPLE),
            ("check", "TECLA F5", "Gravação Rápida instantânea na subpasta SAVES/ (além do Auto-Save automático).", GREEN),
            ("gear", "ESC / F3 / TAB", "ESC pausa a partida, F3 exibe Hitboxes e TAB abre o Inventário Tático em tempo real.", DIVINE),
        ]
        for i, (ic_n, badge_t, desc_t, col_i) in enumerate(lines):
            ry = 112 + i * 62
            row_r = pygame.Rect(W // 2 - 480, ry, 960, 50)
            hov = row_r.collidepoint(mx, my)
            draw_panel(s, row_r, (20, 42, 78, 244) if hov else (12, 24, 46, 234), col_i if hov else (45, 90, 155), 11, 4)
            draw_icon(s, ic_n, (row_r.x + 28, row_r.centery), 9, col_i)
            badge_r = pygame.Rect(row_r.x + 52, ry + 10, 155, 30)
            pygame.draw.rect(s, (8, 16, 32), badge_r, border_radius=7)
            pygame.draw.rect(s, col_i, badge_r, 1, border_radius=7)
            draw_text(s, badge_t, TINY, col_i, badge_r.center, True)
            draw_text(s, desc_t, FONT, WHITE, (badge_r.right + 18, ry + 13))

        back_btn = pygame.Rect(W // 2 - 120, H - 68, 240, 46)
        self.ui_button(s, back_btn, "VOLTAR", CYAN, back_btn.collidepoint(mx, my), "back")
        return [(back_btn, "back")]


def draw_custom_crosshair(s, pos, firing=False, color=CYAN):
    mx, my = pos
    r = 11 if firing else 8
    col = GOLD if firing else color
    pygame.draw.circle(s, col, (mx, my), r, 1)
    pygame.draw.line(s, col, (mx - r - 4, my), (mx - 3, my), 2)
    pygame.draw.line(s, col, (mx + 3, my), (mx + r + 4, my), 2)
    pygame.draw.line(s, col, (mx, my - r - 4), (mx, my - 3), 2)
    pygame.draw.line(s, col, (mx, my + 3), (mx, my + r + 4), 2)


def draw_touch_controls(s, game):
    """Analógico Duplo Virtual (Dual-Stick Touch: Movimento à esquerda + Mira 360° à direita) + Botões Ergonômicos."""
    if not getattr(game, "touch_mode", False):
        game.touch_left_vec = (0.0, 0.0)
        game.touch_right_vec = (0.0, 0.0)
        game.touch_ui_captured = False
        return None, None, None

    left_center = (130, H - 145)
    right_center = (W - 140, H - 145)
    joy_r = 62

    dash_rect = pygame.Rect(W - 285, H - 135, 76, 76)
    ult_rect = pygame.Rect(W - 245, H - 235, 84, 84)
    auto_rect = pygame.Rect(W - 135, H - 265, 76, 42)

    mx, my = pygame.mouse.get_pos()
    mouse_down = pygame.mouse.get_pressed()[0]
    game.touch_ui_captured = False

    if mouse_down:
        dl = math.hypot(mx - left_center[0], my - left_center[1])
        dr = math.hypot(mx - right_center[0], my - right_center[1])
        if dl <= joy_r * 1.45:
            mag = min(1.0, dl / joy_r)
            nx, ny = vec_norm(mx - left_center[0], my - left_center[1])
            game.touch_left_vec = (nx * mag, ny * mag)
            game.touch_ui_captured = True
        elif dr <= joy_r * 1.45:
            mag = min(1.0, dr / joy_r)
            nx, ny = vec_norm(mx - right_center[0], my - right_center[1])
            game.touch_right_vec = (nx * mag, ny * mag)
            game.touch_ui_captured = True
        elif dash_rect.collidepoint(mx, my) or ult_rect.collidepoint(mx, my) or auto_rect.collidepoint(mx, my):
            game.touch_ui_captured = True
    else:
        game.touch_left_vec = (0.0, 0.0)
        game.touch_right_vec = (0.0, 0.0)

    # Analógico Esquerdo (Movimento)
    pygame.draw.circle(s, (12, 26, 52), left_center, joy_r)
    pygame.draw.circle(s, CYAN, left_center, joy_r, 3)
    lk_x = int(left_center[0] + game.touch_left_vec[0] * (joy_r - 18))
    lk_y = int(left_center[1] + game.touch_left_vec[1] * (joy_r - 18))
    glow_circle(s, CYAN, (lk_x, lk_y), 20, 2)
    draw_text(s, "MOVER", TINY, (165, 205, 240), (left_center[0], left_center[1] - joy_r - 12), True)

    # Analógico Direito (Mira 360° & Disparo)
    pygame.draw.circle(s, (18, 22, 48), right_center, joy_r)
    pygame.draw.circle(s, GOLD, right_center, joy_r, 3)
    rk_x = int(right_center[0] + game.touch_right_vec[0] * (joy_r - 18))
    rk_y = int(right_center[1] + game.touch_right_vec[1] * (joy_r - 18))
    glow_circle(s, GOLD, (rk_x, rk_y), 20, 2)
    draw_text(s, "MIRA 360°", TINY, GOLD, (right_center[0], right_center[1] - joy_r - 12), True)

    # Botão DASH
    d_col = CYAN if (game.player.dash and game.player.dash_cd <= 0) else (75, 95, 125)
    pygame.draw.ellipse(s, (16, 32, 60), dash_rect)
    pygame.draw.ellipse(s, d_col, dash_rect, 3)
    draw_text(s, "DASH", SMALL, WHITE, dash_rect.center, True)

    # Botão SUPREMO [Q]
    u_ready = game.player.ult_charge >= 100.0
    u_col = GOLD if u_ready else PURPLE
    pygame.draw.ellipse(s, (28, 20, 58), ult_rect)
    pygame.draw.ellipse(s, u_col, ult_rect, 3)
    draw_text(s, "ULT!" if u_ready else f"{int(game.player.ult_charge)}%", MED if u_ready else SMALL, u_col, ult_rect.center, True)

    # Botão AUTO-DISPARO INTELIGENTE
    a_col = GREEN if game.auto_fire else (100, 120, 150)
    pygame.draw.rect(s, (16, 36, 52), auto_rect, border_radius=10)
    pygame.draw.rect(s, a_col, auto_rect, 2, border_radius=10)
    draw_text(s, "AUTO: ON" if game.auto_fire else "AUTO: OFF", TINY, a_col, auto_rect.center, True)

    return dash_rect, ult_rect, auto_rect


if MOBILE:
    draw_touch_controls = mobile_draw_touch_controls

# ----------------------------------------------------------------------------
# LOOP PRINCIPAL COM AUTO-SAVE BLINDADO
# ----------------------------------------------------------------------------
# ============================================================================
# ===  EXTENSÕES DO GAME: PERIGOS, PROPS, EVENTOS DE CENÁRIO, REDE, HUD+     ===
# ============================================================================
BIOME_EVENT = {0: "strike", 1: "meteor", 2: "gas", 3: "gust", 4: "rift", 5: "beam",
               6: "meteor", 7: "rift", 8: "strike", 9: "meteor", 10: "beam", 11: "rift"}
EVENT_WARN = {"strike": ("TEMPESTADE ELÉTRICA!", (0, 230, 255)), "meteor": ("CHUVA DE METEOROS!", (255, 140, 50)),
              "gas": ("NUVENS TÓXICAS!", (120, 255, 100)), "gust": ("VENTANIA GÉLIDA!", (170, 225, 255)),
              "rift": ("FENDA GRAVITACIONAL!", (190, 110, 255)), "beam": ("FEIXES CELESTIAIS!", (255, 235, 150))}

Game.online = False
Game.online_role = "host"
Game._net_start_flag = False


def _skin_idx(sid):
    for i, sk in enumerate(SKINS):
        if sk["id"] == sid:
            return i
    return 0


def _pet_idx(pid):
    for i, pt in enumerate(PETS):
        if pt["id"] == pid:
            return i
    return 0


# ---------------------------------------------------------------- perigos
def _g_is_client(self):
    return self.online and self.online_role == "client"


def _g_spawn_hazard(self, kind, x, y, **kw):
    hz = Hazard(kind, x, y, **kw)
    self.hazards.append(hz)
    if self.online and self.online_role == "host":
        self.net.send({"t": "hz", "h": hz.spec()})
    return hz


def _g_hz_targets(self):
    out = []
    if not self.player.downed:
        out.append(self.player)
    pt = self.partner
    if pt is not None and self.game_mode == "coop" and not pt.downed:
        out.append(pt)
    return out


def _g_pull_subjects(self, host):
    out = [self.player]
    pt = self.partner
    if pt is not None and self.game_mode == "coop" and not pt.downed and not pt.remote:
        out.append(pt)
    if host:
        out.extend(e for e in self.enemies if e.alive)
    return out


def _g_hurt_in_circle(self, x, y, r, dmg, foe=False):
    for tg in self.hz_targets():
        if math.hypot(tg.x - x, tg.y - y) < r + tg.r * 0.5:
            tg.take_damage(dmg, self)
    for pr in self.props:
        if pr.alive and pr.kind != "pillar" and math.hypot(pr.x - x, pr.y - y) < r + pr.r:
            self.prop_damage(pr, 70)
    if foe:
        for en in self.enemies_near(x, y, r):
            if en.alive and math.hypot(en.x - x, en.y - y) < r + en.r:
                en.hp -= dmg * 2.2 * (0.3 if en.boss else 1.0)
                en.hitflash = 0.15


def _g_fx_blast(self, x, y, r, col):
    self.shockwaves.append(Shockwave(x, y, r, col, 0.4, 4))
    for _ in range(16):
        self.particles.append(Particle(x, y, col, size=5))
    self.camera_shake = max(self.camera_shake, 0.3)
    if self.online and self.online_role == "host":
        self.net.send({"t": "fx", "x": round(x), "y": round(y), "r": r, "c": list(col)})


def _g_warn(self, text, col, t=2.6):
    self.warns.append([text, tuple(col), t])
    self.warns = self.warns[-3:]
    if self.online and self.online_role == "host":
        self.net.send({"t": "warn", "x": text, "c": list(col)})


def _g_hz_update(self, dt):
    for hz in self.hazards:
        hz.update(dt, self)
    self.hazards = [hz for hz in self.hazards if hz.t < hz.life]
    for m in self.dmg_marks:
        m[1] -= dt
    self.dmg_marks = [m for m in self.dmg_marks if m[1] > 0]
    for w in self.warns:
        w[2] -= dt
    self.warns = [w for w in self.warns if w[2] > 0]


# ---------------------------------------------------------------- props
def _g_build_props(self):
    idx = self.bosses % len(ARENA_BIOMES)
    self.props = build_props(idx, self.world_w, self.world_h, getattr(self, "pools", []))
    self._props_idx = idx
    cells = {}
    for pr in self.props:
        for gx in range(int((pr.x - pr.r - 24) // 200), int((pr.x + pr.r + 24) // 200) + 1):
            for gy in range(int((pr.y - pr.r - 24) // 200), int((pr.y + pr.r + 24) // 200) + 1):
                cells.setdefault((gx, gy), []).append(pr)
    self.prop_cells = cells


_orig_ensure_terrain = Game.ensure_terrain


def _g_ensure_terrain(self):
    _orig_ensure_terrain(self)
    if getattr(self, "_props_idx", None) != self.bosses % len(ARENA_BIOMES):
        self.build_props()


def _g_prop_damage(self, pr, dmg):
    if self.is_client() or not pr.alive or pr.kind == "pillar":
        return
    pr.hp -= dmg
    pr.flash = 0.12
    if pr.hp <= 0:
        self.prop_destroy(pr)


def _g_prop_destroy(self, pr):
    pr.alive = False
    pr.respawn = 28.0 if pr.kind == "barrel" else 42.0
    if self.online and self.online_role == "host":
        self.net.send({"t": "prop", "i": pr.id, "s": 0})
    self.prop_destroy_fx(pr)
    lvl = self.level
    if pr.kind == "barrel":
        col, _nm = BARREL_STYLE[pr.style]
        if pr.style != "void":   # o Barril do Vazio puxa primeiro e só explode depois
            for en in self.enemies_near(pr.x, pr.y, 140):
                if en.alive and math.hypot(en.x - pr.x, en.y - pr.y) < 140 + en.r:
                    en.hp -= (45 + lvl * 3) * (0.3 if en.boss else 1.0)
                    en.hitflash = 0.15
                    nm = {"fire": "burn", "toxic": "poison", "frost": "freeze"}.get(pr.style)
                    if nm:
                        self.apply_status(en, nm, 3.0)
            if pr.style != "holy":   # a Relíquia Solar não fere quem está perto: ela cura
                for tg in self.hz_targets():
                    if math.hypot(tg.x - pr.x, tg.y - pr.y) < 140:
                        tg.take_damage(14 + lvl * 1.1, self)
        if pr.style in ("toxic", "fire"):
            self.spawn_hazard("cloud", pr.x, pr.y, r=95, warm=0.0, dur=4.0, dmg=3 + lvl * 0.25, tick=0.45, col=col)
        if pr.style == "void":
            self.spawn_hazard("pull", pr.x, pr.y, r=190, warm=0.0, dur=0.6, strength=460, blast=140, dmg=14 + lvl * 1.1, col=col, foe=True)
        if pr.style == "holy":
            self.shockwaves.append(Shockwave(pr.x, pr.y, 160, GOLD, 0.45, 3))
            for en in self.enemies_near(pr.x, pr.y, 150):
                if en.alive:
                    self.apply_status(en, "mark", 4.0)
            for tg in self.hz_targets():
                if math.hypot(tg.x - pr.x, tg.y - pr.y) < 150:
                    heal = getattr(tg, "maxhp", 100) * 0.08
                    tg.hp = min(tg.maxhp, tg.hp + heal)
                    self.floating_texts.append(FloatingText(tg.x, tg.y - 20, f"+{int(heal)} HP", GOLD))
        for q in self.props:
            if q is not pr and q.alive and math.hypot(q.x - pr.x, q.y - pr.y) < 180:
                if q.kind == "barrel" and q.fuse < 0:
                    q.fuse = 0.16
                elif q.kind == "crystal":
                    self.prop_damage(q, 45)
    elif pr.kind == "crystal":
        for k in range(8):
            a = math.tau * k / 8
            self.bullets.append(Bullet(pr.x, pr.y, math.cos(a) * 330, math.sin(a) * 330, 14 + lvl * 2.2, size=6, color=pr.accent))
        self.orbs.append(Orb(pr.x, pr.y, 16 + lvl * 2, "xp"))
        if random.random() < 0.4:
            self.orbs.append(Orb(pr.x + 10, pr.y, 16, "heal"))


def _g_prop_destroy_fx(self, pr):
    """Visual local (também usado pelo cliente ao receber o evento da rede)."""
    if pr.kind == "barrel":
        col, _nm = BARREL_STYLE[pr.style]
        if pr.style == "void":   # implosão: o estouro vem do puxão (Hazard "pull")
            self.shockwaves.append(Shockwave(pr.x, pr.y, 60, col, 0.3, 3))
            for _ in range(12):
                self.particles.append(Particle(pr.x, pr.y, col, size=4))
            return
        self.shockwaves.append(Shockwave(pr.x, pr.y, 140, col, 0.4, 4))
        for _ in range(18):
            self.particles.append(Particle(pr.x, pr.y, col, size=5))
        if pr.style == "holy":
            self.shockwaves.append(Shockwave(pr.x, pr.y, 190, GOLD, 0.6, 2))
        self.camera_shake = max(self.camera_shake, 0.3)
        play_sound("boom")
    elif pr.kind == "crystal":
        for _ in range(14):
            self.particles.append(Shard(pr.x, pr.y, pr.accent, 6))
        play_sound("crit")


def _g_props_update(self, dt):
    host = not self.is_client()
    for pr in self.props:
        pr.flash = max(0.0, pr.flash - dt)
        pr.born = max(0.0, pr.born - dt * 2.5)
        if not host:
            continue
        if pr.alive:
            if pr.fuse >= 0:
                pr.fuse -= dt
                if pr.fuse <= 0:
                    pr.fuse = -1.0
                    self.prop_destroy(pr)
        else:
            pr.respawn -= dt
            if pr.respawn <= 0:
                if math.hypot(self.player.x - pr.x, self.player.y - pr.y) < 90:
                    pr.respawn = 2.0
                else:
                    pr.alive, pr.hp, pr.born, pr.fuse = True, float(pr.maxhp), 1.0, -1.0
                    if self.online and self.online_role == "host":
                        self.net.send({"t": "prop", "i": pr.id, "s": 1})


def _g_props_bullets(self):
    cells = self.prop_cells
    if not cells:
        return
    client = self.is_client()
    for b in self.bullets:
        pcs = cells.get((int(b.x // 200), int(b.y // 200)))
        if not pcs:
            continue
        for pr in pcs:
            if not pr.alive or pr in b.hit:
                continue
            if math.hypot(b.x - pr.x, b.y - pr.y) < pr.r + b.size:
                b.hit.add(pr)
                if b.enemy:
                    if pr.kind == "barrel" and not client:
                        self.prop_damage(pr, b.damage * 1.2)
                    b.life = 0
                else:
                    if pr.kind != "pillar" and not client:
                        self.prop_damage(pr, b.damage)
                    if b.pierce > 0 and pr.kind != "pillar":
                        b.pierce -= 1
                    else:
                        b.life = 0
                for _ in range(3):
                    self.particles.append(Particle(b.x, b.y, pr.accent, size=3))
                break


def _push_out(ent, pr, er):
    dx, dy = ent.x - pr.x, ent.y - pr.y
    mind = pr.r + er * 0.85
    d2 = dx * dx + dy * dy
    if d2 < mind * mind:
        d = math.sqrt(d2) or 0.01
        if d2 == 0:
            dx, dy = 1.0, 0.0
        ent.x += dx / d * (mind - d)
        ent.y += dy / d * (mind - d)


def _g_props_resolve(self):
    pt = self.partner
    for pr in self.props:
        if not pr.alive:
            continue
        _push_out(self.player, pr, self.player.r)
        if pt is not None and not pt.remote:
            _push_out(pt, pr, pt.r)
        if not self.is_client():
            for en in self.enemies_near(pr.x, pr.y, pr.r + 70):
                if en.alive:
                    _push_out(en, pr, en.r)


def _g_draw_props(self, s, cx, cy):
    t = self.elapsed
    vis = []
    for pr in self.props:
        sx, sy = int(pr.x - cx), int(pr.y - cy)
        if -80 < sx < W + 80 and -100 < sy < H + 80:
            vis.append((sy, sx, pr))
    vis.sort(key=lambda v: v[0])
    for sy, sx, pr in vis:
        if pr.alive:
            _draw_prop(s, pr, sx, sy, t)
        elif pr.kind == "barrel":
            pygame.draw.ellipse(s, (8, 8, 14), (sx - 20, sy - 7, 40, 16))


def _g_draw_hazards(self, s, cx, cy):
    for hz in self.hazards:
        hz.draw(s, cx, cy, self)


# ---------------------------------------------------------------- eventos de cenário
def _g_env_update(self, dt):
    if self.game_mode == "pvp" or self.is_client() or self.level < 3:
        return
    self.env_t -= dt
    if self.env_t > 0:
        return
    boss_on = any(e.boss and e.alive for e in self.enemies)
    self.env_t = random.uniform(10, 16) * (1.4 if boss_on else 1.0)
    self.env_fire(BIOME_EVENT[(self.bosses % len(ARENA_BIOMES)) % 12])


def _g_env_fire(self, kind):
    lvl = self.level
    d = 12 + lvl * 0.9
    txt, col = EVENT_WARN[kind]
    self.warn(txt, col)

    def tg():
        return random.choice(self.hz_targets() or [self.player])

    def cl(v, hi):
        return clamp(v, 50, hi - 50)
    if kind == "strike":
        for i in range(4 + min(6, lvl // 6)):
            t_ = tg()
            self.spawn_hazard("circle", cl(t_.x + random.uniform(-260, 260), self.world_w), cl(t_.y + random.uniform(-260, 260), self.world_h),
                              r=62, warm=0.85 + i * 0.08, dmg=d, col=(0, 230, 255), foe=True)
    elif kind == "meteor":
        for i in range(3 + min(5, lvl // 7)):
            t_ = tg()
            self.spawn_hazard("circle", cl(t_.x + random.uniform(-300, 300), self.world_w), cl(t_.y + random.uniform(-300, 300), self.world_h),
                              r=78, warm=1.15 + i * 0.15, dmg=d * 1.4, col=(255, 140, 50), cloud=True, foe=True)
    elif kind == "gas":
        for _ in range(3):
            t_ = tg()
            a = random.random() * math.tau
            dd = random.uniform(160, 380)
            self.spawn_hazard("cloud", cl(t_.x + math.cos(a) * dd, self.world_w), cl(t_.y + math.sin(a) * dd, self.world_h),
                              r=115, warm=0.9, dur=7.0, tick=0.5, dmg=4 + lvl * 0.3, col=(110, 255, 90))
    elif kind == "gust":
        self.spawn_hazard("gust", self.player.x, self.player.y, ang=random.random() * math.tau, warm=1.3, dur=4.0, strength=190, col=(190, 230, 255))
    elif kind == "rift":
        t_ = tg()
        a = random.random() * math.tau
        self.spawn_hazard("pull", cl(t_.x + math.cos(a) * 300, self.world_w), cl(t_.y + math.sin(a) * 300, self.world_h),
                          r=300, warm=1.0, dur=3.2, strength=210, blast=100, dmg=d * 1.5, col=(190, 110, 255), foe=True)
    elif kind == "beam":
        for i in range(3):
            t_ = tg()
            a = random.uniform(0, math.pi)
            off = random.uniform(-150, 150)
            ox = t_.x - math.cos(a) * 650 - math.sin(a) * off
            oy = t_.y - math.sin(a) * 650 + math.cos(a) * off
            self.spawn_hazard("beam", ox, oy, ang=a, length=1300, width=38, warm=1.3 + i * 0.25, dur=0.55, dmg=d * 1.6, col=(255, 235, 150), tick=0.1)


def _g_rain_update(self, dt):
    """Evento global: CHUVA DE XP E INIMIGOS no meio da fase (só o anfitrião/solo simula)."""
    if self.game_mode == "pvp" or self.is_client() or self.level < 2:
        return
    boss_on = any(e.boss and e.alive for e in self.enemies)
    if self.rain_t <= 0:
        self.rain_next -= dt
        if self.rain_next <= 0:
            if boss_on:
                self.rain_next = 8.0
                return
            self.rain_t = 9.0
            self.rain_acc = self.rain_enemy_acc = 0.0
            self.warn("CHUVA DE XP E INIMIGOS!", GOLD, 3.2)
            play_sound("levelup")
        return
    self.rain_t -= dt
    if self.rain_t <= 0:
        self.rain_next = random.uniform(45, 70)
        return
    tgs = self.hz_targets() or [self.player]
    lvl = self.level
    self.rain_acc += dt
    while self.rain_acc >= 0.14:
        self.rain_acc -= 0.14
        t_ = random.choice(tgs)
        x = clamp(t_.x + random.uniform(-460, 460), 40, self.world_w - 40)
        y = clamp(t_.y + random.uniform(-340, 340), 40, self.world_h - 40)
        r = random.random()
        if r < 0.10:
            self.orbs.append(Orb(x, y, 14 + lvl * 2.2, "xp"))
        elif r < 0.18:
            self.orbs.append(Orb(x, y, 3 + lvl // 4, "coin"))
        elif r < 0.22:
            self.orbs.append(Orb(x, y, 16, "heal"))
        else:
            self.orbs.append(Orb(x, y, 6 + lvl * 1.1, "xp"))
        self.particles.append(Particle(x, y, GOLD, vel=(0, 0), life=0.35, size=20, kind="ring"))
        for _ in range(3):
            self.particles.append(Particle(x, y - random.uniform(10, 60), (255, 235, 150), vel=(0, 160), life=0.3, size=3))
    self.rain_enemy_acc += dt
    if self.rain_enemy_acc >= 0.85 and len(self.enemies) < 105:
        self.rain_enemy_acc = 0.0
        t_ = random.choice(tgs)
        kinds = ["Básico", "Veloz"]
        if lvl >= 4:
            kinds += ["Atirador", "Tanque"]
        if lvl >= 7:
            kinds += ["Berserker", "Aracnídeo"]
        a = random.random() * math.tau
        d = random.uniform(240, 420)
        x = clamp(t_.x + math.cos(a) * d, 40, self.world_w - 40)
        y = clamp(t_.y + math.sin(a) * d, 40, self.world_h - 40)
        e = Enemy(x, y, random.choice(kinds), lvl)
        e.spawn_t = 0.75
        e.xp *= 1.3
        self.enemies.append(e)
        self.shockwaves.append(Shockwave(x, y, 46, GOLD, 0.35, 2))


def _g_pick_target(self, e):
    p = self.player
    pt = self.partner
    if e.kind == "Parasita" or pt is None or self.game_mode != "coop" or pt.downed:
        return p
    if p.downed:
        return pt
    d_p = (p.x - e.x) ** 2 + (p.y - e.y) ** 2
    d_t = ((pt.x - e.x) ** 2 + (pt.y - e.y) ** 2) * 1.15
    return pt if d_t < d_p else p


def _g_update_world_extras(self, dt):
    self.hz_update(dt)
    self.props_update(dt)
    self.env_update(dt)
    if self.is_client():
        return
    self.rain_update(dt)
    # cenário x inimigos: gelo congela, vazio puxa, círculos de luz curam
    self._pool_t = getattr(self, "_pool_t", 0.0) - dt
    if self.pools and self.pools[0]["kind"] in ("ice", "void", "heal") and self.enemies:
        kind = self.pools[0]["kind"]
        tick = self._pool_t <= 0
        if tick:
            self._pool_t = 0.25
        for pl in self.pools:
            reach = pl["r"] * (1.7 if kind == "void" else 0.88)
            for en in self.enemies_near(pl["x"], pl["y"], reach):
                if not en.alive or en.boss:
                    continue
                dx, dy = pl["x"] - en.x, pl["y"] - en.y
                d = math.hypot(dx, dy)
                if d > reach:
                    continue
                if kind == "void" and d > 4:
                    pull = 110 * (1 - d / reach) * dt
                    en.x += dx / d * pull
                    en.y += dy / d * pull
                elif tick and kind == "ice":
                    self.apply_status(en, "freeze", 0.5)
                elif tick and kind == "heal":
                    en.hp = min(en.maxhp, en.hp + en.maxhp * 0.012)
    pt = self.partner
    if pt is not None and pt.remote and self.online:
        rs = self.net.remote_state or {}
        mag = float(rs.get("mg", 120))
        for o in self.orbs[:]:
            d = math.hypot(o.x - pt.x, o.y - pt.y)
            mr = mag * (1.25 if o.kind in ("heal", "coin") else 1.0)
            if d < mr and d > 1:
                sp = 280 + (mr - d) * 3.1
                o.x += (pt.x - o.x) / d * sp * dt
                o.y += (pt.y - o.y) / d * sp * dt
            if d < pt.r + 14:
                self.orbs.remove(o)
                self.net.send({"t": "orbgive", "k": o.kind, "v": o.value})


# ---------------------------------------------------------------- HUD+
def _g_draw_hud_plus(self, s):
    p = self.player
    cxm, cym = self.camera()
    px, py = p.x - cxm, p.y - cym
    t = pygame.time.get_ticks() / 1000.0
    # indicadores de direção do dano
    for ang, life in self.dmg_marks:
        k = clamp(life / 0.9, 0.0, 1.0)
        c = _fade((255, 60, 70), k)
        pts = [(px + math.cos(ang - 0.32) * 74, py + math.sin(ang - 0.32) * 74), (px + math.cos(ang + 0.32) * 74, py + math.sin(ang + 0.32) * 74),
               (px + math.cos(ang + 0.2) * 96, py + math.sin(ang + 0.2) * 96), (px + math.cos(ang - 0.2) * 96, py + math.sin(ang - 0.2) * 96)]
        pygame.draw.polygon(s, c, pts)
    # avisos de cenário
    if self.warns:
        txt, col, tm = self.warns[-1]
        img = get_cached_text(txt, MED, col)
        r = pygame.Rect(0, 0, img.get_width() + 56, 40)
        r.center = (W // 2, H - 150)
        pygame.draw.rect(s, (14, 10, 22), r, border_radius=12)
        pygame.draw.rect(s, _fade(col, 0.55 + 0.4 * math.sin(t * 12)), r, 2, border_radius=12)
        draw_icon(s, "warn", (r.x + 22, r.centery), 9, col)
        s.blit(img, (r.x + 40, r.y + 7))
    # seta do aliado / rival fora da tela
    pt = self.partner
    if pt is not None and self.game_mode in ("coop", "pvp"):
        sx_t, sy_t = pt.x - cxm, pt.y - cym
        if not (30 <= sx_t <= W - 30 and 30 <= sy_t <= H - 30):
            ang = math.atan2(sy_t - H / 2, sx_t - W / 2)
            ix = int(clamp(W / 2 + math.cos(ang) * (W / 2 - 40), 40, W - 40))
            iy = int(clamp(H / 2 + math.sin(ang) * (H / 2 - 60), 50, H - 80))
            col = GREEN if self.game_mode == "coop" else RED
            pts = [(ix + math.cos(ang) * 14, iy + math.sin(ang) * 14), (ix + math.cos(ang + 2.4) * 10, iy + math.sin(ang + 2.4) * 10),
                   (ix + math.cos(ang - 2.4) * 10, iy + math.sin(ang - 2.4) * 10)]
            pygame.draw.polygon(s, col, pts)
            pygame.draw.polygon(s, WHITE, pts, 1)
            dist = int(math.hypot(pt.x - p.x, pt.y - p.y) / 10)
            draw_text(s, f"{'ALIADO' if self.game_mode == 'coop' else 'RIVAL'} {dist}m {int(100 * pt.hp / max(1, pt.maxhp))}%", TINY, col, (ix, iy - 16), True)
    # medidor de ameaça
    cap = max(1, int(min(115, 14 + self.level * 3)))
    frac = clamp(len(self.enemies) / cap, 0.0, 1.0)
    if self.game_mode != "pvp":
        col = CYAN if frac < 0.5 else (ORANGE if frac < 0.85 else RED)
        draw_text(s, "AMEAÇA", TINY, (160, 190, 225), (22, H - 66))
        draw_glossy_bar(s, pygame.Rect(78, H - 66, 150, 12), frac, col, (16, 24, 42), border_col=(45, 80, 135))
    # selo de rede
    if self.online:
        rtt = int(self.net.rtt_ms)
        col = GREEN if rtt < 80 else (GOLD if rtt < 160 else RED)
        r = pygame.Rect(W - 330, H - 66, 312, 22)
        pygame.draw.rect(s, (8, 16, 34), r, border_radius=9)
        pygame.draw.rect(s, col, r, 1, border_radius=9)
        role = "ANFITRIÃO" if self.online_role == "host" else "CONVIDADO"
        draw_text(s, f"ONLINE {role} • {rtt} ms • UP {self.net.kbps_up:.0f} DN {self.net.kbps_down:.0f} KB/s", TINY, col, (r.centerx, r.centery), True)


def _g_net_toast(self, text, t=3.0):
    self.net_toast_text, self.net_toast_t = text, t


def _g_draw_toast(self, s):
    if self.net_toast_t > 0 and self.net_toast_text:
        img = get_cached_text(self.net_toast_text, SMALL, WHITE)
        r = pygame.Rect(0, 0, img.get_width() + 36, 34)
        r.center = (W // 2, 118)
        pygame.draw.rect(s, (12, 22, 44), r, border_radius=12)
        pygame.draw.rect(s, CYAN, r, 2, border_radius=12)
        s.blit(img, (r.x + 18, r.y + 8))


# ---------------------------------------------------------------- rede: sessão
def _g_net_send_start(self):
    self.net.send({"t": "start", "m": self.game_mode, "sk": self.profile.get("selected_skin", "classic"),
                   "pt": self.profile.get("selected_pet", "slime")})


def _g_net_leave_match(self, notify=True):
    if notify and self.net.connected_peer:
        self.net.send({"t": "left"})
    self.online = False
    if self.partner is not None:
        self.partner.remote = False


def _g_net_peer_lost(self):
    if self.online_role == "host":
        self.net_leave_match(notify=False)
        self.net_toast("Parceiro desconectou — a IA assumiu o controle", 4.0)
    else:
        self.net_leave_match(notify=False)
        self.game_mode = "solo"
        self.state = "menu"
        self.net_toast("Conexão com o anfitrião perdida", 4.0)


def _g_net_send_state(self):
    p = self.player
    self.net.send({"t": "st", "x": round(p.x, 1), "y": round(p.y, 1), "vx": round(p.vx), "vy": round(p.vy),
                   "hp": round(p.hp, 1), "mh": round(p.maxhp), "sh": round(p.shield), "sk": self.profile.get("selected_skin", "classic"),
                   "pt": self.profile.get("selected_pet", "slime"), "dn": bool(p.downed), "ul": int(p.ult_charge),
                   "mg": int(p.magnet), "nm": self.net.player_name, "lv": self.level}, droppable=True)


def _g_build_snapshot(self):
    pt = self.partner
    ref = [(self.player.x, self.player.y)] + ([(pt.x, pt.y)] if pt else [])

    def near(x, y):
        return any((x - rx) ** 2 + (y - ry) ** 2 < 1250 ** 2 for rx, ry in ref)
    en = []
    for e in self.enemies:
        if not e.alive:
            continue
        fl = (1 if e.charge > 0 else 0) | (2 if e.intangible > 0 else 0) | (4 if e.attached else 0) | (8 if e.pend is not None else 0)
        en.append([e.uid, e.kind, round(e.x, 1), round(e.y, 1), int(e.hp), int(e.maxhp), 1 if e.boss else 0, e.bi, e.phase, fl,
                   e.affix or 0, int(e.shield_dir * 100), e.r, int(e.guard * 10), e.cur_attack if e.cur_attack_t > 0 else 0])
        if len(en) >= 150:
            break
    eb, pb = [], []
    for b in self.bullets:
        if b.enemy:
            if len(eb) < 230 and near(b.x, b.y):
                eb.append([round(b.x), round(b.y), round(b.vx), round(b.vy), b.size, *b.color])
        elif b.owner != "p2_coop" and len(pb) < 100:
            pb.append([round(b.x), round(b.y), round(b.vx), round(b.vy), b.size, *b.color])
    orbs = [[o.oid, round(o.x), round(o.y), {"xp": 0, "heal": 1, "coin": 2}.get(o.kind, 0), o.value] for o in self.orbs[:130]]
    return {"t": "snap", "e": en, "eb": eb, "pb": pb, "o": orbs, "k": self.kills, "z": self.bosses, "lv": self.level,
            "el": round(self.elapsed, 1), "cm": self.combo}


def _g_apply_snapshot(self, m):
    live = self.state == "playing"
    seen = set()
    for row in m.get("e", []):
        uid, kind, x, y, hp, mhp, boss, bi, ph, fl, affix, sd, r, guard, atk = row
        seen.add(uid)
        e = self.puppets.get(uid)
        if e is None:
            if not boss and kind not in ENEMY_TYPES:
                kind = "Básico"
            e = Enemy(x, y, kind, max(1, m.get("lv", 1)), bool(boss), max(1, bi))
            e.uid, e.spawn_t, e.tx, e.ty = uid, 0.0, x, y
            self.puppets[uid] = e
            self.enemies.append(e)
            if boss:
                self.boss_banner_timer, self.camera_shake = 3.5, 0.9
                play_sound("boss")
        else:
            if hp < e.hp - 0.5 and self.settings.get("damage_numbers", True) and abs(e.x - self.player.x) < W:
                self.floating_texts.append(FloatingText(e.x, e.y - e.r, str(int(e.hp - hp)), WHITE))
            if hp < e.hp - 0.5:
                e.hitflash = 0.1
        e.tx, e.ty = x, y
        if not live:
            e.x, e.y = x, y
        e.hp, e.maxhp, e.phase, e.r = hp, mhp, ph, r
        e.charge = 0.3 if fl & 1 else 0.0
        e.intangible = 0.5 if fl & 2 else 0.0
        e.attached = bool(fl & 4)
        e.pend = [1.0, "x", None] if fl & 8 else None
        e.affix = affix or None
        e.shield_dir = sd / 100.0
        e.guard = guard / 10.0
        e.cur_attack, e.cur_attack_t = (atk, 1.0) if atk else ("", 0.0)
    for uid in [u for u in self.puppets if u not in seen]:
        e = self.puppets.pop(uid)
        e.alive = False
        if self.camera_visible(e.x, e.y):
            spawn_death_fx(self, e)
    self.enemies = [e for e in self.enemies if e.alive]
    # projéteis
    keep = [b for b in self.bullets if not b.enemy and b.owner != "remote_vis"]
    for x, y, vx, vy, sz, cr, cg, cb in m.get("eb", []):
        keep.append(Bullet(x, y, vx, vy, 0, enemy=True, size=sz, color=(cr, cg, cb), owner="remote_enemy"))
    for x, y, vx, vy, sz, cr, cg, cb in m.get("pb", []):
        keep.append(Bullet(x, y, vx, vy, 0, enemy=False, size=sz, color=(cr, cg, cb), owner="remote_vis"))
    self.bullets = keep
    # orbes
    cur = {o.oid: o for o in self.orbs}
    new = []
    for oid, x, y, kc, v in m.get("o", []):
        o = cur.get(oid)
        if o is None:
            o = Orb(x, y, v, ("xp", "heal", "coin")[kc])
            o.oid = oid
        o.x, o.y = x, y
        new.append(o)
    self.orbs = new
    # progresso compartilhado
    k = m.get("k", self.kills)
    if k > self.kills:
        dk = k - self.kills
        self.player.ult_charge = min(100.0, self.player.ult_charge + 1.8 * dk * self.player.ult_rate)
        self.combo += dk
        self.combo_timer = 3.2
    self.kills = k
    z = m.get("z", self.bosses)
    if z > self.bosses:
        self.bosses = z
        self.boss_active = False
        self.player.rerolls += 1
        self.player.shield += 35
        self.player.hp = min(self.player.maxhp, self.player.hp + 30)
        self.gain_xp(140 + max(1, z) * 55)
        if self.state == "playing":
            self.cards = self.choose_cards()
            self.state = "levelup"
        self.floating_texts.append(FloatingText(self.player.x, self.player.y - 48, "CHEFE DERROTADO!", GOLD, crit=True))
    elif z < self.bosses:
        self.bosses = z
    el = m.get("el", self.elapsed)
    if abs(el - self.elapsed) > 0.5:
        self.elapsed = el


def _g_net_dispatch(self, m):
    t = m.get("t")
    cl = self.is_client()
    if t == "st":
        self.net.remote_state = m
        m["_rx"] = time.time()
    elif t == "start":
        self.online, self.online_role = True, "client"
        self.game_mode = m.get("m", "coop")
        self.partner_skin_idx = _skin_idx(m.get("sk", "classic"))
        self.partner_pet_idx = _pet_idx(m.get("pt", "slime"))
        self._net_start_flag = True
        self.pvp_round = self.pvp_p1_wins = self.pvp_p2_wins = 0
        self.pvp_round = 1
        self.reset()
        self._net_start_flag = False
        self.pvp_banner_text = f"{'DUELO PVP 1V1' if self.game_mode == 'pvp' else 'CO-OP ONLINE'} — SALA {self.net.room_code}"
        self.pvp_banner_timer = 2.8
        self.state = "playing"
        play_sound("levelup")
    elif t == "snap":
        if cl and self.game_mode == "coop":
            self.apply_snapshot(m)
        elif cl and self.game_mode == "pvp":
            self.apply_pvp_orbs(m)
    elif t == "shot":
        if self.online and (self.game_mode == "pvp" or not cl):
            lat = min(0.18, self.net.rtt_ms / 2000.0)
            owner = "p2" if self.game_mode == "pvp" else "p2_coop"
            for x, y, vx, vy, d, sz, pi, ri, ho, kb, cr, cg, cb in m.get("b", []):
                self.bullets.append(Bullet(x + vx * lat, y + vy * lat, vx, vy, d, enemy=False, pierce=pi, ricochet=ri, size=sz,
                                           homing=bool(ho), knockback=kb, color=(cr, cg, cb), owner=owner))
    elif t == "hz":
        if cl:
            h = m["h"]
            self.hazards.append(Hazard(h["k"], h["x"], h["y"], r=h["r"], ang=h["a"], length=h["l"], width=h["w"], warm=h["wm"], dur=h["d"],
                                       dmg=h["dm"], col=h["c"], spin=h["sp"], cloud=h["cl"], gap=h["g"], speed=h["v"], tick=h["tk"],
                                       strength=h["st"], blast=h["b"], foe=h["f"], visual=True))
    elif t == "fx":
        self.shockwaves.append(Shockwave(m["x"], m["y"], m["r"], tuple(m["c"]), 0.4, 4))
        for _ in range(14):
            self.particles.append(Particle(m["x"], m["y"], tuple(m["c"]), size=5))
        self.camera_shake = max(self.camera_shake, 0.3)
    elif t == "prop":
        for pr in self.props:
            if pr.id == m["i"]:
                if m["s"] == 0 and pr.alive:
                    pr.alive = False
                    self.prop_destroy_fx(pr)
                elif m["s"] == 1:
                    pr.alive, pr.hp, pr.born = True, float(pr.maxhp), 1.0
    elif t == "warn":
        self.warns.append([m["x"], tuple(m["c"]), 2.6])
    elif t == "ult":
        if self.partner is not None and self.state in ("playing", "levelup"):
            self.partner.ult_charge = 100.0
            self.partner.downed = False
            self.partner.trigger_ultimate(self)
    elif t == "dmg":
        if self.state == "playing" and not self.player.downed and self.game_mode == "coop":
            self.player.take_damage(float(m.get("a", 5)), self)
    elif t == "orbgive":
        self.net_orb_give(m.get("k", "xp"), m.get("v", 0))
    elif t == "xp":
        if self.state in ("playing", "levelup"):
            self.gain_xp(float(m.get("v", 0)))
    elif t == "pvp_end":
        if self.game_mode == "pvp" and time.time() - getattr(self, "_pvp_end_t", 0) > 1.0:
            self._pvp_end_t = time.time()
            Game.handle_pvp_round_end(self, "p1" if m.get("w") == "p2" else "p2", _remote=True)
    elif t == "gameover":
        if self.online and self.state in ("playing", "levelup", "paused"):
            self._net_go_sent = True
            self.record_highscore()
            self.state = "gameover"
    elif t == "left":
        if self.online:
            self.net_peer_lost()


def _g_apply_pvp_orbs(self, m):
    cur = {o.oid: o for o in self.orbs}
    new = []
    for oid, x, y, kc, v in m.get("o", []):
        o = cur.get(oid)
        if o is None:
            o = Orb(x, y, v, ("xp", "heal", "coin")[kc])
            o.oid = oid
        o.x, o.y = x, y
        new.append(o)
    self.orbs = new


def _g_net_orb_give(self, k, v):
    p = self.player
    if self.game_mode == "pvp":
        if k == "heal":
            p.hp = min(p.maxhp, p.hp + v)
        else:
            p.ult_charge = min(100.0, p.ult_charge + 18.0)
        return
    if k == "heal":
        amt = v * (1 + p.healing)
        p.hp = min(p.maxhp, p.hp + amt)
        self.floating_texts.append(FloatingText(p.x, p.y - 10, f"+{int(amt)} HP", GREEN))
        play_sound("heal")
    elif k == "coin":
        amt = max(1, int(round(v * (1.0 + p.coin_bonus))))
        self.gain_coins(amt)
        self.floating_texts.append(FloatingText(p.x, p.y - 10, f"+{amt} $", GOLD))
        play_sound("coin")
    else:
        self.gain_xp(v)
        play_sound("xp")


def _g_net_tick(self, dt):
    net = self.net
    for m in net.poll():
        try:
            self.net_dispatch(m)
        except Exception as ex:
            print("[NET] erro ao processar", m.get("t"), repr(ex))
    self.net_toast_t = max(0.0, self.net_toast_t - dt)
    prev, cur = self._peer_prev, net.connected_peer
    self._peer_prev = cur
    if cur and not prev and self.state == "multiplayer_view":
        play_sound("achievement")
        self.net_toast("Parceiro conectado! O anfitrião inicia a partida.", 4.0)
    if not self.online:
        return
    if self.state in ("menu", "multiplayer_view", "slots_view"):
        self.net_leave_match(notify=True)
        return
    if not cur:
        self.net_peer_lost()
        return
    now = time.perf_counter()
    if now - self._st_t >= 0.05:
        self._st_t = now
        self.net_send_state()
    if self.online_role == "host" and now - self._snap_t >= 0.066:
        self._snap_t = now
        if self.game_mode == "coop":
            self.net.send(self.build_snapshot(), droppable=True)
        elif self.game_mode == "pvp":
            self.net.send({"t": "snap", "o": [[o.oid, round(o.x), round(o.y), {"xp": 0, "heal": 1, "coin": 2}.get(o.kind, 0), o.value] for o in self.orbs[:20]]}, droppable=True)
    if self.state == "gameover" and not self._net_go_sent:
        self._net_go_sent = True
        self.net.send({"t": "gameover"})


# ---------------------------------------------------------------- cliente online (coop/pvp)
def _g_update_client(self, dt):
    for b_ach in self.achievement_banners:
        b_ach["timer"] -= dt
    self.achievement_banners = [b for b in self.achievement_banners if b["timer"] > 0]
    self.save_indicator_timer = max(0.0, self.save_indicator_timer - dt)
    self.elapsed += dt
    self.camera_shake = max(0, self.camera_shake - dt)
    self.boss_banner_timer = max(0, self.boss_banner_timer - dt)
    self.pvp_banner_timer = max(0.0, self.pvp_banner_timer - dt)
    if self.combo > 0:
        self.combo_timer -= dt
        if self.combo_timer <= 0:
            self.combo = 0
    keys = pygame.key.get_pressed()
    mouse = pygame.mouse.get_pressed()[0]
    self.update_terrain(dt)
    self.update_world_extras(dt)
    self.player.update(dt, self, keys, mouse)
    if self.pet:
        self.pet.update(dt, self)
    if self.partner:
        self.partner.update(dt, self)
    for bh in self.blackholes:
        bh.update(dt, self)
    self.blackholes = [bh for bh in self.blackholes if bh.life > 0]
    mx, my = pygame.mouse.get_pos()
    tcx = clamp(self.player.x + (mx - W / 2) * 0.12 - W / 2, 0, max(0, self.world_w - W))
    tcy = clamp(self.player.y + (my - H / 2) * 0.12 - H / 2, 0, max(0, self.world_h - H))
    self.cam_x += (tcx - self.cam_x) * min(1.0, 9.0 * dt)
    self.cam_y += (tcy - self.cam_y) * min(1.0, 9.0 * dt)
    for e in self.enemies:
        e.puppet_update(dt)
    self.build_enemy_grid()
    pvp = self.game_mode == "pvp"
    for b in self.bullets:
        b.update(dt, self)
        if b.enemy or b.owner == "remote_vis":
            continue
        if b.owner == "p2":
            if math.hypot(b.x - self.player.x, b.y - self.player.y) < self.player.r + b.size - 1:
                self.player.take_damage(b.damage, self)
                b.life = 0
            continue
        if pvp and self.partner and not self.partner.downed and math.hypot(b.x - self.partner.x, b.y - self.partner.y) < self.partner.r + b.size + 1:
            self.player.ult_charge = min(100.0, self.player.ult_charge + 4.5)
            b.life = 0
            continue
        for e in self.enemies_near_seg(b.px, b.py, b.x, b.y, b.size + 2):
            if e.alive and e not in b.hit and seg_hit(b.px, b.py, b.x, b.y, e.x, e.y, e.r + b.size + 2):
                b.hit.add(e)
                self.particles.extend(Particle(b.x, b.y, e.color) for _ in range(3))
                if b.pierce > 0:
                    b.pierce -= 1
                else:
                    b.life = 0
                break
    self.props_bullets()
    self.bullets = [b for b in self.bullets if b.life > 0 and 0 < b.x < self.world_w and 0 < b.y < self.world_h]
    for o in self.orbs:
        o.phase += dt * 4.0
    for p_ in self.particles:
        p_.update(dt)
    self.particles = [p_ for p_ in self.particles if p_.life > 0]
    cap_p = PARTICLE_CAPS[self.settings.get("quality", 2)]
    if len(self.particles) > cap_p:
        del self.particles[:len(self.particles) - cap_p]
    for ft in self.floating_texts:
        ft.update(dt)
    self.floating_texts = [ft for ft in self.floating_texts if ft.life > 0]
    for sw in self.shockwaves:
        sw.update(dt)
    self.shockwaves = [sw for sw in self.shockwaves if sw.life > 0]
    for uv in self.ult_visuals:
        uv.update(dt)
    self.ult_visuals = [uv for uv in self.ult_visuals if uv.life > 0]
    for lb in self.lightnings:
        lb.update(dt)
    self.lightnings = [lb for lb in self.lightnings if lb.life > 0]
    self.props_resolve()


_orig_update = Game.update


def _g_update(self, dt):
    if self.online and self.online_role == "client" and self.state == "playing":
        self.update_client(dt)
        return
    _orig_update(self, dt)


# ---------------------------------------------------------------- PartnerOrb remoto
def _po_remote_update(self, dt, game):
    rs = game.net.remote_state or {}
    self.x += (rs.get("x", self.x) - self.x) * min(1.0, 14.0 * dt)
    self.y += (rs.get("y", self.y) - self.y) * min(1.0, 14.0 * dt)
    self.vx, self.vy = rs.get("vx", 0.0), rs.get("vy", 0.0)
    self.skin_id = rs.get("sk", self.skin_id)
    self.pet_id = rs.get("pt", self.pet_id)
    self.maxhp = max(1.0, float(rs.get("mh", self.maxhp)))
    self.hp = float(rs.get("hp", self.hp))
    self.shield = float(rs.get("sh", self.shield))
    self.downed = bool(rs.get("dn", False))
    self.ult_charge = float(rs.get("ul", self.ult_charge))
    self.name = str(rs.get("nm", "ORB"))[:12].upper() if game.game_mode == "coop" else "RIVAL"
    if game.game_mode == "pvp" and game.online_role == "host" and False:
        pass
    self.pet_phase += dt * 4.2
    self.ghost_hp = self.hp if self.ghost_hp < self.hp else max(self.hp, self.ghost_hp - 40 * dt)
    self.invuln = max(0.0, self.invuln - dt)
    self.flash = max(0.0, self.flash - dt)
    self.trail.append((self.x, self.y, 0.26, False))
    self.trail = [(x, y, t - dt, d) for x, y, t, d in self.trail if t > dt]


def _po_remote_damage(self, amount, game):
    """Dano no parceiro remoto: o ANFITRIÃO decide e avisa; o dono do orbe aplica (armadura, esquiva...)."""
    if game.game_mode != "coop" or self.invuln > 0 or self.downed or not game.online:
        return
    self.invuln = 0.42
    game.net.send({"t": "dmg", "a": round(amount, 1)})


_orig_shoot = Player.shoot


def _shoot_wrap(self, game, mouse):
    n0 = len(game.bullets)
    _orig_shoot(self, game, mouse)
    if game.online and (game.game_mode == "pvp" or game.online_role == "client"):
        new = [b for b in game.bullets[n0:] if not b.enemy]
        if new:
            game.net.send({"t": "shot", "b": [[round(b.x, 1), round(b.y, 1), round(b.vx, 1), round(b.vy, 1), round(b.damage, 1), b.size,
                                                 b.pierce, b.ricochet, int(bool(b.homing)), b.knockback, *b.color] for b in new]})


_orig_ult = Player.trigger_ultimate


def _ult_wrap(self, game):
    ready = self.ult_charge >= 100.0 and not self.downed
    _orig_ult(self, game)
    if ready and game.online:
        game.net.send({"t": "ult"})


_orig_ptd = Player.take_damage


def _ptd_wrap(self, amount, game):
    h0 = self.hp + self.shield
    _orig_ptd(self, amount, game)
    if self.hp + self.shield < h0 - 0.01:
        best, bd = None, 240 * 240
        for b in game.bullets:
            if b.enemy:
                d2 = (b.x - self.x) ** 2 + (b.y - self.y) ** 2
                if d2 < bd:
                    best, bd = (b.x, b.y), d2
        for e in game.enemies_near(self.x, self.y, 170):
            d2 = (e.x - self.x) ** 2 + (e.y - self.y) ** 2
            if e.alive and d2 < bd:
                best, bd = (e.x, e.y), d2
        if best:
            game.dmg_marks.append([math.atan2(best[1] - self.y, best[0] - self.x), 0.9])


_orig_enemy_killed = Game.enemy_killed


def _g_enemy_killed(self, e):
    _orig_enemy_killed(self, e)
    if self.online and self.online_role == "host" and self.game_mode == "coop":
        self.net.send({"t": "xp", "v": round(e.xp * 0.35, 1)})


_orig_pvp_end = Game.handle_pvp_round_end


def _g_pvp_end(self, winner="p1", _remote=False):
    if self.online and not _remote:
        self._pvp_end_t = time.time()
        self.net.send({"t": "pvp_end", "w": winner})
    _orig_pvp_end(self, winner)
    if self.online and self.online_role == "client" and self.game_mode == "pvp":
        self.player.x = self.world_w / 2 + 260
        if self.partner:
            self.partner.x = self.world_w / 2 - 260


_orig_reset = Game.reset


def _g_reset(self):
    if self.online and self.online_role == "client" and not self._net_start_flag:
        self.net_leave_match(notify=True)
        self.game_mode = "solo"
    _orig_reset(self)
    self.hazards, self.props, self.prop_cells, self._props_idx = [], [], {}, None
    self.dmg_marks, self.warns, self.env_t = [], [], 14.0
    self.rain_t, self.rain_next, self.rain_acc, self.rain_enemy_acc = 0.0, 30.0, 0.0, 0.0
    self.puppets = {}
    self._net_go_sent = False
    self._snap_t = self._st_t = 0.0
    self.net_toast_text, self.net_toast_t = "", 0.0
    if not hasattr(self, "_peer_prev"):
        self._peer_prev = False
    if self.online and self.partner is not None:
        self.partner.remote = True
        if self.online_role == "client" and self.game_mode == "pvp":
            self.player.x, self.partner.x = self.world_w / 2 + 260, self.world_w / 2 - 260
    if self.online and self.online_role == "host" and not self._net_start_flag:
        self.net_send_start()


def _puppet_update(self, dt):
    self.hitflash = max(0.0, self.hitflash - dt)
    k = min(1.0, 16.0 * dt)
    self.x += (self.tx - self.x) * k
    self.y += (self.ty - self.y) * k


Enemy.puppet_update = _puppet_update
PartnerOrb.remote_update = _po_remote_update
PartnerOrb.remote_damage = _po_remote_damage
Player.shoot = _shoot_wrap
Player.trigger_ultimate = _ult_wrap
Player.take_damage = _ptd_wrap
Game.enemy_killed = _g_enemy_killed
Game.handle_pvp_round_end = _g_pvp_end
Game.reset = _g_reset
Game.update = _g_update
Game.ensure_terrain = _g_ensure_terrain
for _nm_, _fn_ in (("is_client", _g_is_client), ("spawn_hazard", _g_spawn_hazard), ("hz_targets", _g_hz_targets),
                   ("pull_subjects", _g_pull_subjects), ("hurt_in_circle", _g_hurt_in_circle), ("fx_blast", _g_fx_blast),
                   ("warn", _g_warn), ("hz_update", _g_hz_update), ("build_props", _g_build_props), ("prop_damage", _g_prop_damage),
                   ("prop_destroy", _g_prop_destroy), ("prop_destroy_fx", _g_prop_destroy_fx), ("props_update", _g_props_update),
                   ("props_bullets", _g_props_bullets), ("props_resolve", _g_props_resolve), ("draw_props", _g_draw_props),
                   ("draw_hazards", _g_draw_hazards), ("env_update", _g_env_update), ("env_fire", _g_env_fire),
                   ("pick_target", _g_pick_target), ("rain_update", _g_rain_update), ("update_world_extras", _g_update_world_extras), ("draw_hud_plus", _g_draw_hud_plus),
                   ("net_toast", _g_net_toast), ("draw_toast", _g_draw_toast), ("net_send_start", _g_net_send_start),
                   ("net_leave_match", _g_net_leave_match), ("net_peer_lost", _g_net_peer_lost), ("net_send_state", _g_net_send_state),
                   ("build_snapshot", _g_build_snapshot), ("apply_snapshot", _g_apply_snapshot), ("apply_pvp_orbs", _g_apply_pvp_orbs),
                   ("net_dispatch", _g_net_dispatch), ("net_orb_give", _g_net_orb_give), ("net_tick", _g_net_tick),
                   ("update_client", _g_update_client)):
    setattr(Game, _nm_, _fn_)


game = Game()

def _emergency_exit_save():
    if game.state in ("playing", "paused", "levelup", "gameover"):
        game.save_game(game.current_slot)

atexit.register(_emergency_exit_save)

menu_rects = []
mp_rects = []
slots_rects = []
touch_btns = (None, None, None)
shop_rects = []
skins_rects = []
pets_rects = []
ach_rects = []
settings_rects = []
cards_rects = []
how_rects = []
pause_rects = []
gameover_rects = []
reroll_btn_rect = None
bestiary_rects = []
biomes_rects = []
running = True
last_hovered = None
game.kb_idx = -1
_prev_state = game.state
_fade_t = 0.0
FADE_STATES = ("menu", "slots_view", "skins_view", "pets_view", "achievements_view", "shop_view", "cards_view", "how", "settings_view", "bestiary_view", "biomes_view", "multiplayer_view")
KB_STATES = ("menu", "paused", "gameover", "settings_view", "bestiary_view", "biomes_view")
_windowed_size = (W, H)

def get_active_rects():
    return {"menu": menu_rects, "paused": pause_rects, "gameover": gameover_rects, "settings_view": settings_rects,
            "bestiary_view": bestiary_rects, "biomes_view": biomes_rects}.get(game.state, [])

def kb_move(rl, idx, dx, dy):
    """Navegacao por teclado: escolhe o cartao mais proximo na direcao pedida."""
    if idx < 0 or idx >= len(rl):
        return 0
    cx0, cy0 = rl[idx][0].center
    best, bd = idx, 1e18
    for i, (r, _a) in enumerate(rl):
        if i == idx:
            continue
        ox, oy = r.centerx - cx0, r.centery - cy0
        if dx:
            if ox * dx <= 0 or abs(oy) > abs(ox) * 1.3 + 40:
                continue
            d = abs(ox) + abs(oy) * 2
        else:
            if oy * dy <= 0 or abs(ox) > abs(oy) * 1.3 + 40:
                continue
            d = abs(oy) + abs(ox) * 2
        if d < bd:
            best, bd = i, d
    return best

def toggle_fullscreen():
    global screen, _windowed_size
    if MOBILE:
        return
    if screen.get_flags() & pygame.FULLSCREEN:
        screen = pygame.display.set_mode(_windowed_size, pygame.RESIZABLE)
    else:
        _windowed_size = screen.get_size()
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

def menu_action(act):
    """Executa uma acao do menu inicial. Retorna True para sair do jogo."""
    if act == "open_slots":
        game.game_mode = "solo"
        game.state = "slots_view"
    elif act == "multiplayer":
        game.state = "multiplayer_view"
    elif act == "shop":
        game.state = "shop_view"
    elif act == "skins":
        game.state = "skins_view"
    elif act == "pets":
        game.state = "pets_view"
    elif act == "achievements":
        game.state = "achievements_view"
    elif act == "how":
        game.state = "how"
    elif act == "cards":
        game.state = "cards_view"
        game.cards_page = 0
    elif act == "bestiary":
        game.state = "bestiary_view"
        game.bestiary_tab = "enemies"
    elif act == "biomes":
        game.state = "biomes_view"
    elif act == "settings":
        game.settings_back = None
        game.state = "settings_view"
    elif act == "quit":
        return True
    return False

# --- MODO DE TESTE AUTOMATICO (sem interacao): BLUE_ORB_SMOKE=<n_frames> ---
SMOKE_FRAMES = int(os.environ.get("BLUE_ORB_SMOKE", "0") or 0)
SMOKE_SHOTS = os.environ.get("BLUE_ORB_SHOTS", "")
_smoke = {"n": 0, "upd": [], "frame": [], "maxent": 0, "maxpart": 0}
if SMOKE_FRAMES:
    game.reset()
    game.current_slot = 1
    game.state = "playing"
    game.auto_fire = True
    _NETTEST = os.environ.get("BLUE_ORB_NETTEST", "")
    if _NETTEST:
        game.state = "multiplayer_view"
        game.net.player_name = _NETTEST.split(":")[0].upper()[:8]
    for _nm in ("Balas Incendiárias", "Veneno Neurotóxico", "Toque Gélido", "Marca do Caçador", "Catalisador Elemental"):
        for _c in CARDS:
            if _c["name"] == _nm:
                game.player.apply(_c)

FIXED_DT = (1.0 / 60.0) if MOBILE else (1.0 / 120.0)
_dt_acc = 0.0
while running:
    _t_frame = time.perf_counter()
    frame_dt = min(clock.tick(0 if SMOKE_FRAMES else FPS) / 1000.0, .05)
    dt = frame_dt  # usado por UI / animações de menu
    if SMOKE_FRAMES:
        dt = frame_dt = 1 / 60
        _smoke["n"] += 1
        _n = _smoke["n"]
        game.player.hp = game.player.maxhp
        game.player.invuln = max(game.player.invuln, 0.0)
        if _NETTEST:
            if _n == 1:
                if _NETTEST.startswith("host"):
                    game.net.create_room()
                else:
                    game.net.input_code = os.environ.get("BLUE_ORB_CODE", "")
                    game.net.join_room(game.net.input_code)
            if _NETTEST.startswith("host") and game.net.connected_peer and not game.online and _n > 30:
                game.start_multiplayer_match(os.environ.get("BLUE_ORB_MODE", "coop"))
            if _NETTEST.startswith("host") and _n % 60 == 0 and game.net.link.state == "waiting":
                print("CODE", game.net.room_code, flush=True)
        if game.state == "levelup":
            game.player.apply(random.choice(game.cards))
            game.state = "playing"
        if game.state == "playing":
            game.player.x = 1200 + math.cos(_n / 90) * 420
            game.player.y = 900 + math.sin(_n / 70) * 300
            if _n % 25 == 0:
                game.gain_xp(35 + game.level * 6)
            if os.environ.get("BLUE_ORB_STRESS") and _n % 5 == 0:
                for _ in range(3):
                    game.spawn_enemy()
    W, H = screen.get_size()
    pygame.mouse.set_visible(game.state != "playing")

    for event in pygame.event.get():
        if event.type == pygame.WINDOWFOCUSLOST and game.state == "playing" and game.game_mode == "solo" and not SMOKE_FRAMES:
            game.save_game(game.current_slot)
            game.state = "paused"
        if event.type == pygame.MOUSEMOTION:
            game.kb_idx = -1
        if event.type == pygame.QUIT:
            if game.state in ("playing", "paused", "levelup", "gameover"):
                game.save_game(game.current_slot)
            running = False
        if event.type == pygame.VIDEORESIZE and not MOBILE:
            screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
        if event.type == pygame.KEYDOWN and MOBILE and event.key == getattr(pygame, "K_AC_BACK", -1):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="\x1b"))
            continue
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F11:
                toggle_fullscreen()
            if game.state in KB_STATES and event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB):
                rl_ = get_active_rects()
                if rl_:
                    ddx, ddy = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_UP: (0, -1)}.get(event.key, (0, 1))
                    if event.key == pygame.K_TAB and (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                        ddx, ddy = 0, -1
                    game.kb_idx = kb_move(rl_, game.kb_idx, ddx, ddy)
                    play_sound("hover")
            elif game.state in KB_STATES and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and (game.kb_idx >= 0 or game.state == "menu"):
                rl_ = get_active_rects()
                if game.kb_idx < 0:
                    game.kb_idx = 0
                if 0 <= game.kb_idx < len(rl_):
                    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rl_[game.kb_idx][0].center, button=1))
            if event.key == pygame.K_F3:
                game.settings["show_hitboxes"] = not game.settings["show_hitboxes"]
            if event.key == pygame.K_F5 and game.state in ("playing", "paused", "levelup"):
                game.save_game(game.current_slot)
                play_sound("select")
            if event.key == pygame.K_e and game.state == "playing":
                game.auto_fire = not game.auto_fire
                play_sound("select")
            if event.key == pygame.K_q and game.state == "playing":
                game.player.trigger_ultimate(game)
            if event.key == pygame.K_t and game.state == "playing" and not MOBILE:
                game.touch_mode = not getattr(game, "touch_mode", False)
                play_sound("select")
            if event.key == pygame.K_ESCAPE:
                if game.state == "playing":
                    game.save_game(game.current_slot)
                    game.state = "paused"
                elif game.state == "paused":
                    game.save_game(game.current_slot)
                    game.state = "playing"
                elif game.state == "settings_view":
                    game.state = game.settings_back or "menu"
                    game.settings_back = None
                elif game.state in ("how", "cards_view", "slots_view", "skins_view", "pets_view", "achievements_view", "shop_view", "multiplayer_view", "bestiary_view", "biomes_view"):
                    game.state = "menu"
                elif game.state == "menu":
                    running = False
            if game.state == "multiplayer_view":
                if game.net.edit_server:
                    if event.key == pygame.K_BACKSPACE:
                        game.net.server_text = game.net.server_text[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
                        game.net.edit_server = False
                        game.profile["relay_server"] = game.net.server_text
                        game.save_profile()
                        play_sound("select")
                    else:
                        ch = event.unicode
                        if ch and (ch.isalnum() or ch in ".:-_") and len(game.net.server_text) < 60:
                            game.net.server_text += ch
                elif event.key == pygame.K_BACKSPACE:
                    game.net.input_code = game.net.input_code[:-1]
                    play_sound("hover")
                elif event.key == pygame.K_RETURN and game.net.input_code:
                    game.net.join_room(game.net.input_code)
                    play_sound("select")
                else:
                    ch = event.unicode.upper()
                    if ch and ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" and len(game.net.input_code) < 12:
                        game.net.input_code += ch
                        play_sound("hover")
            if game.state == "levelup":
                if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    idx = event.key - pygame.K_1
                    if idx < len(game.cards):
                        play_sound("select")
                        game.player.apply(game.cards[idx])
                        game.state = "playing"
                        game.save_game(game.current_slot)
                        if game.boss_queued and not game.boss_active:
                            game.spawn_boss()
                elif event.key == pygame.K_r:
                    if game.player.rerolls > 0:
                        game.player.rerolls -= 1
                        game.cards = game.choose_cards()
                        game.save_game(game.current_slot)
                        play_sound("select")
                    elif game.profile.get("coins", 0) >= 25:
                        game.profile["coins"] -= 25
                        game.save_profile()
                        game.cards = game.choose_cards()
                        game.save_game(game.current_slot)
                        play_sound("coin")
            if game.state == "gameover" and event.key == pygame.K_RETURN and game.kb_idx < 0:
                play_sound("select")
                game.load_game(game.current_slot)
            if game.state == "paused" and event.key == pygame.K_RETURN and game.kb_idx < 0:
                play_sound("select")
                game.state = "playing"

        if event.type == pygame.MOUSEWHEEL:
            if game.state == "cards_view":
                max_p = math.ceil(len(CARDS) / 12) - 1
                if event.y < 0 and game.cards_page < max_p:
                    game.cards_page += 1
                    play_sound("hover")
                elif event.y > 0 and game.cards_page > 0:
                    game.cards_page -= 1
                    play_sound("hover")

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 3 and game.state == "playing":
                game.auto_fire = not game.auto_fire
                play_sound("select")
            elif event.button == 1:
                mx, my = event.pos
                if game.state == "menu":
                    for r, act in menu_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if menu_action(act):
                                running = False
                elif game.state == "playing" and getattr(game, "touch_mode", False):
                    d_r, u_r, a_r = touch_btns
                    if d_r and d_r.collidepoint(mx, my):
                        if game.player.dash and game.player.dash_cd <= 0:
                            game.player.dash_time = 0.16
                            game.player.dash_cd = 2.8
                            ax, ay = game.touch_left_vec if (abs(game.touch_left_vec[0]) > 0.05 or abs(game.touch_left_vec[1]) > 0.05) else (1.0, 0.0)
                            ax, ay = vec_norm(ax, ay)
                            game.player.dash_vx = ax * 920
                            game.player.dash_vy = ay * 920
                            play_sound("dash")
                    elif u_r and u_r.collidepoint(mx, my):
                        game.player.trigger_ultimate(game)
                    elif a_r and a_r.collidepoint(mx, my):
                        game.auto_fire = not game.auto_fire
                        play_sound("select")
                elif game.state == "bestiary_view":
                    for r, act in bestiary_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                            elif act in ("tab_enemies", "tab_bosses"):
                                game.bestiary_tab = act[4:]
                            break
                elif game.state == "biomes_view":
                    for r, act in biomes_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                            break
                elif game.state == "multiplayer_view":
                    for r, act in mp_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                            elif act == "mp_server":
                                game.net.edit_server = not game.net.edit_server
                                if not game.net.edit_server:
                                    game.profile["relay_server"] = game.net.server_text
                                    game.save_profile()
                            elif act == "mp_create":
                                game.net.create_room()
                            elif act == "mp_join":
                                game.net.join_room(game.net.input_code)
                            elif act == "mp_sync":
                                game.sync_cloud_backup(silent=False)
                            elif act == "mp_p2_skin":
                                game.partner_skin_idx = (game.partner_skin_idx + 1) % len(SKINS)
                            elif act == "mp_p2_pet":
                                game.partner_pet_idx = (game.partner_pet_idx + 1) % len(PETS)
                            elif act == "mp_start_coop":
                                game.start_multiplayer_match("coop")
                            elif act == "mp_start_pvp":
                                game.start_multiplayer_match("pvp")
                            break
                elif game.state == "shop_view":
                    for r, act in shop_rects:
                        if r.collidepoint(mx, my):
                            if act == "back":
                                play_sound("select")
                                game.state = "menu"
                            elif act.startswith("buy_up_"):
                                uid = act.split("buy_up_")[1]
                                up_meta = next((u for u in SHOP_UPGRADES if u["id"] == uid), None)
                                if up_meta:
                                    cur_l = game.profile["upgrades"].get(uid, 0)
                                    cost = int(up_meta["base_cost"] * (1.35 ** cur_l))
                                    if cur_l < up_meta["max_lvl"] and game.profile.get("coins", 0) >= cost:
                                        game.profile["coins"] -= cost
                                        game.profile["upgrades"][uid] = cur_l + 1
                                        game.save_profile()
                                        play_sound("coin")
                            break
                elif game.state == "skins_view":
                    for r, act in skins_rects:
                        if r.collidepoint(mx, my):
                            if act == "back":
                                play_sound("select")
                                game.state = "menu"
                            elif act.startswith("skin_"):
                                sk_id = act.split("_", 1)[1]
                                if sk_id in game.profile["unlocked_skins"]:
                                    game.profile["selected_skin"] = sk_id
                                    game.save_profile()
                                    play_sound("select")
                            elif act.startswith("buyskin_"):
                                sk_id = act.split("_", 1)[1]
                                sk_meta = next((sk for sk in SKINS if sk["id"] == sk_id), None)
                                if sk_meta and game.profile.get("coins", 0) >= sk_meta.get("coin_cost", 300):
                                    game.profile["coins"] -= sk_meta.get("coin_cost", 300)
                                    if sk_id not in game.profile["unlocked_skins"]:
                                        game.profile["unlocked_skins"].append(sk_id)
                                    game.profile["selected_skin"] = sk_id
                                    game.save_profile()
                                    play_sound("coin")
                            break
                elif game.state == "pets_view":
                    for r, act in pets_rects:
                        if r.collidepoint(mx, my):
                            if act == "back":
                                play_sound("select")
                                game.state = "menu"
                            elif act.startswith("pet_"):
                                pid = act.split("_", 1)[1]
                                if pid in game.profile["unlocked_pets"]:
                                    game.profile["selected_pet"] = pid
                                    game.save_profile()
                                    play_sound("select")
                            elif act.startswith("buypet_"):
                                pid = act.split("_", 1)[1]
                                pm = next((pt for pt in PETS if pt["id"] == pid), None)
                                if pm and game.profile.get("coins", 0) >= pm["cost"]:
                                    game.profile["coins"] -= pm["cost"]
                                    if pid not in game.profile["unlocked_pets"]:
                                        game.profile["unlocked_pets"].append(pid)
                                    game.profile["selected_pet"] = pid
                                    game.save_profile()
                                    play_sound("coin")
                            break
                elif game.state == "achievements_view":
                    for r, act in ach_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                elif game.state == "slots_view":
                    for r, act in slots_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                            elif act.startswith("del_"):
                                slot_num = int(act.split("_")[1])
                                game.delete_save(slot_num)
                            elif act.startswith("slot_"):
                                slot_num = int(act.split("_")[1])
                                game.current_slot = slot_num
                                if not game.load_game(slot_num):
                                    game.reset()
                                    game.current_slot = slot_num
                                    game.save_game(slot_num)
                            break
                elif game.state == "settings_view":
                    for r, act in settings_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act in ("lang_pt", "lang_en", "lang_es"):
                                LANG_CUR = act.split("_")[1]
                                game.settings["language"] = LANG_CUR
                                game.profile["language"] = LANG_CUR
                                TEXT_CACHE.clear()
                                game.save_profile()
                            elif act == "vol-":
                                game.settings["volume"] = round(max(0.0, game.settings["volume"] - 0.1), 1)
                            elif act == "vol+":
                                game.settings["volume"] = round(min(1.0, game.settings["volume"] + 0.1), 1)
                            elif act == "quality":
                                game.settings["quality"] = (game.settings.get("quality", 2) + 1) % 3
                            elif act == "fullscreen":
                                toggle_fullscreen()
                            elif act in ("shake", "effects", "damage_numbers", "show_hitboxes", "smart_auto_aim", "reduce_flash", "compact_hud"):
                                game.settings[act] = not game.settings.get(act, False)
                            elif act == "back":
                                game.state = game.settings_back or "menu"
                                game.settings_back = None
                elif game.state == "cards_view":
                    for r, act in cards_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "prev_page":
                                game.cards_page -= 1
                            elif act == "next_page":
                                game.cards_page += 1
                            elif act == "back":
                                game.state = "menu"
                elif game.state == "how":
                    for r, act in how_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "back":
                                game.state = "menu"
                elif game.state == "levelup":
                    cardw, cardh = CARD_W, CARD_H
                    gap = CARD_GAP
                    start = (W - (3 * cardw + 2 * gap)) // 2
                    for i in range(len(game.cards)):
                        float_offset = math.sin(pygame.time.get_ticks() * 0.003 + i * 1.2) * 6
                        y_pos = CARD_Y + int(float_offset)
                        r = pygame.Rect(start + i * (cardw + gap), y_pos, cardw, cardh)
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            game.player.apply(game.cards[i])
                            game.state = "playing"
                            game.save_game(game.current_slot)
                            if game.boss_queued and not game.boss_active:
                                game.spawn_boss()
                            break
                    if reroll_btn_rect and reroll_btn_rect.collidepoint(mx, my):
                        if game.player.rerolls > 0:
                            game.player.rerolls -= 1
                            game.cards = game.choose_cards()
                            game.save_game(game.current_slot)
                            play_sound("select")
                        elif game.profile.get("coins", 0) >= 25:
                            game.profile["coins"] -= 25
                            game.save_profile()
                            game.cards = game.choose_cards()
                            game.save_game(game.current_slot)
                            play_sound("coin")
                elif game.state == "paused":
                    for r, act in pause_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "continue":
                                game.save_game(game.current_slot)
                                game.state = "playing"
                            elif act == "skins":
                                game.save_game(game.current_slot)
                                game.state = "skins_view"
                            elif act == "settings":
                                game.save_game(game.current_slot)
                                game.settings_back = "paused"
                                game.state = "settings_view"
                            elif act == "restart":
                                game.delete_save(game.current_slot)
                                game.reset()
                                game.save_game(game.current_slot)
                                game.state = "playing"
                            elif act == "slots":
                                game.save_game(game.current_slot)
                                game.state = "slots_view"
                            elif act == "menu":
                                game.save_game(game.current_slot)
                                game.state = "menu"
                            break
                elif game.state == "gameover":
                    for r, act in gameover_rects:
                        if r.collidepoint(mx, my):
                            play_sound("select")
                            if act == "continue_lvl":
                                game.load_game(game.current_slot)
                            elif act == "restart_zero":
                                game.delete_save(game.current_slot)
                                game.reset()
                                game.save_game(game.current_slot)
                            elif act == "slots":
                                game.state = "slots_view"
                            elif act == "menu":
                                game.state = "menu"
                            break

    # Deteção de Hover para efeitos sonoros
    mx, my = pygame.mouse.get_pos()
    hovering_now = None
    active_list = []
    if game.state == "menu":
        active_list = menu_rects
    elif game.state == "multiplayer_view":
        active_list = mp_rects
    elif game.state == "shop_view":
        active_list = shop_rects
    elif game.state == "slots_view":
        active_list = slots_rects
    elif game.state == "skins_view":
        active_list = skins_rects
    elif game.state == "pets_view":
        active_list = pets_rects
    elif game.state == "achievements_view":
        active_list = ach_rects
    elif game.state == "how":
        active_list = how_rects
    elif game.state == "bestiary_view":
        active_list = bestiary_rects
    elif game.state == "biomes_view":
        active_list = biomes_rects
    elif game.state == "cards_view":
        active_list = cards_rects
    elif game.state == "settings_view":
        active_list = settings_rects
    elif game.state == "paused":
        active_list = pause_rects
    elif game.state == "gameover":
        active_list = gameover_rects

    for r, act in active_list:
        if r.collidepoint(mx, my):
            hovering_now = act
            break

    if game.state == "levelup":
        cardw, cardh = CARD_W, CARD_H
        gap = CARD_GAP
        start = (W - (3 * cardw + 2 * gap)) // 2
        for i in range(len(game.cards)):
            float_offset = math.sin(pygame.time.get_ticks() * 0.003 + i * 1.2) * 6
            y_pos = CARD_Y + int(float_offset)
            if pygame.Rect(start + i * (cardw + gap), y_pos, cardw, cardh).collidepoint(mx, my):
                hovering_now = f"card_{i}"

    if hovering_now != last_hovered:
        if hovering_now is not None:
            play_sound("hover")
        last_hovered = hovering_now

    if game.state != _prev_state:
        if game.state in FADE_STATES or _prev_state in FADE_STATES:
            _fade_t = 0.28
        game.kb_idx = -1
        _prev_state = game.state

    game.net_tick(frame_dt)
    _t_u = time.perf_counter()
    if game.state == "playing":
        # Timestep fixo 120 Hz com acumulador (física determinística)
        _dt_acc += frame_dt
        steps = 0
        while _dt_acc >= FIXED_DT and steps < 8:
            game.update(FIXED_DT)
            _dt_acc -= FIXED_DT
            steps += 1
        if steps == 0 and frame_dt > 0:
            # frame muito curto: ainda avança um pouco
            game.update(min(frame_dt, FIXED_DT))
            _dt_acc = 0.0
    _t_upd = time.perf_counter() - _t_u

    if game.state == "menu":
        menu_rects = game.draw_menu(screen)
    elif game.state == "multiplayer_view":
        mp_rects = game.draw_multiplayer_menu(screen)
    elif game.state == "shop_view":
        shop_rects = game.draw_shop_menu(screen)
    elif game.state == "slots_view":
        slots_rects = game.draw_slots_menu(screen)
    elif game.state == "skins_view":
        skins_rects = game.draw_skins_menu(screen)
    elif game.state == "pets_view":
        pets_rects = game.draw_pets_menu(screen)
    elif game.state == "achievements_view":
        ach_rects = game.draw_achievements_menu(screen)
    elif game.state == "how":
        how_rects = game.draw_how_to_play(screen)
    elif game.state == "bestiary_view":
        bestiary_rects = game.draw_bestiary(screen)
    elif game.state == "biomes_view":
        biomes_rects = game.draw_biomes(screen)
    elif game.state == "cards_view":
        cards_rects = game.draw_cards_view(screen)
    elif game.state == "settings_view":
        settings_rects = game.draw_settings(screen)
    else:
        cx, cy = game.camera()
        sc = game.get_skin_colors()
        game.draw_background(screen, cx, cy)

        # CAMADA 1: cenário, props, perigos, buracos negros, orbes, baús, inimigos, lightmap (antes do jogador)
        game.draw_props(screen, cx, cy)
        game.draw_hazards(screen, cx, cy)
        for bh in game.blackholes:
            bh.draw(screen, cx, cy)
        for o in game.orbs:
            o.draw(screen, cx, cy)
        for ch in game.chests:
            ch.draw(screen, cx, cy)
        for e in game.enemies:
            e.draw(screen, cx, cy)
        draw_enemy_overlays(screen, cx, cy, game)
        for lb in game.lightnings:
            lb.draw(screen, cx, cy)
        for p in game.particles:
            p.draw(screen, cx, cy)
        render_lighting(screen, game, cx, cy)

        px, py = int(game.player.x - cx + game.player.recoil_x), int(game.player.y - cy + game.player.recoil_y)
        # CAMADA 2: efeitos atrás do jogador
        if game.player.slowfield:
            pygame.draw.circle(screen, sc["trail"], (px, py), 160, 1)
        if game.player.aura:
            aura_r = int(102 + math.sin(game.elapsed * 8) * 4)
            pygame.draw.circle(screen, sc["bullet"], (px, py), aura_r, 2)
        for uv in game.ult_visuals:
            uv.draw(screen, cx, cy)

        # CAMADA 2 cont.: rastro do jogador (atrás do corpo)
        trail_pts = [(int(x - cx), int(y - cy), t, is_dash) for x, y, t, is_dash in game.player.trail]
        for idx_t in range(len(trail_pts)):
            tx_p, ty_p, t_p, is_d = trail_pts[idx_t]
            col = sc["bullet"] if is_d else sc["trail"]
            rad = max(2, int((14 if is_d else 8) * t_p / .28))
            if idx_t > 0:
                px_prev, py_prev, _, _ = trail_pts[idx_t - 1]
                pygame.draw.line(screen, col, (px_prev, py_prev), (tx_p, ty_p), max(2, rad * 2))
            pygame.draw.circle(screen, col, (tx_p, ty_p), rad)

        # CAMADA 2 cont.: anéis de evolução, recarga do dash, sombra elíptica e halo (glow_bloom)
        draw_player_back(screen, game, px, py, sc)

        # --- CAMADA 3: JOGADOR (sprite original, sem lightmap por cima) ---
        is_moving = math.hypot(game.player.vx, game.player.vy) > 18
        body_col = sc["body"]
        shoe_col = sc["shoe"]
        py_anim = draw_orb_character(
            screen, (px, py), game.player.r, body_col, shoe_col, None,
            game.elapsed, is_moving, flash=game.player.flash > 0, legs=True, face=True, scale=1.0,
            shadow=False
        )
        # Contraste de segurança: mantém a silhueta do jogador legível mesmo
        # sobre bloom, partículas, iluminação e efeitos de ultimate.
        _player_outline_r = max(6, int(game.player.r) + 2)
        pygame.draw.circle(screen, (5, 12, 28), (px, py_anim), _player_outline_r, 3)
        pygame.draw.circle(screen, (220, 250, 255), (px, py_anim), max(4, int(game.player.r) - 1), 1)

        if not game.player.downed:
            draw_player_extras(screen, game, px, py, py_anim, sc)

        if game.player.shield > 0:
            sh_r = game.player.r + 13
            hex_pts = [
                (px + math.cos(game.elapsed * 2.2 + k * math.tau / 6) * sh_r,
                 py_anim + math.sin(game.elapsed * 2.2 + k * math.tau / 6) * sh_r)
                for k in range(6)
            ]
            pygame.draw.polygon(screen, sc["bullet"], hex_pts, 2)

        # CAMADA 4: satélites, projéteis (sobre o cenário, sem cobrir o corpo do orbe)
        if game.player.orbitals > 0:
            for i in range(game.player.orbitals):
                ang = game.player.orbital_angle + i * (math.tau / game.player.orbitals)
                ox = px + int(math.cos(ang) * 68)
                oy = py_anim + int(math.sin(ang) * 68)
                glow_circle(screen, sc["bullet"], (ox, oy), 8, 2)
        for b in game.bullets:
            bx_, by_ = int(b.x - cx), int(b.y - cy)
            if not (-70 < bx_ < W + 70 and -70 < by_ < H + 70):
                continue
            tc = sc["trail"] if not b.enemy else (150, 35, 60)
            p1 = (int(bx_ - b.vx * .020), int(by_ - b.vy * .020))
            p2 = (int(bx_ - b.vx * .042), int(by_ - b.vy * .042))
            p3 = (int(bx_ - b.vx * .068), int(by_ - b.vy * .068))
            pygame.draw.line(screen, tc, (bx_, by_), p1, 5)
            pygame.draw.line(screen, _fade(tc, 0.6), p1, p2, 3)
            pygame.draw.line(screen, _fade(tc, 0.3), p2, p3, 2)
            b.draw(screen, cx, cy)
        for sw in game.shockwaves:
            sw.draw(screen, cx, cy)

        if game.settings.get("show_hitboxes", False):
            pygame.draw.circle(screen, (0, 255, 0), (px, py), int(game.player.r), 1)

        if game.player.downed:
            pygame.draw.circle(screen, ORANGE, (px, py), 110, 2)
            if game.player.revive_progress > 0:
                arc_r = pygame.Rect(px - 34, py - 34, 68, 68)
                pygame.draw.arc(screen, GREEN, arc_r, -math.pi / 2, -math.pi / 2 + game.player.revive_progress * math.tau, 5)
            draw_text(screen, f"REANIMANDO ({int(game.player.revive_progress * 100)}%)", SMALL, GREEN, (px, py - 46), True)

        if game.pet:
            game.pet.draw(screen, cx, cy)
        if game.partner:
            game.partner.draw(screen, cx, cy, game)

        if game.player.smart_target_pos and game.auto_fire:
            stx = int(game.player.smart_target_pos[0] - cx)
            sty = int(game.player.smart_target_pos[1] - cy)
            pygame.draw.circle(screen, GOLD, (stx, sty), 22, 1)
            pygame.draw.line(screen, GOLD, (stx - 26, sty), (stx - 14, sty), 2)
            pygame.draw.line(screen, GOLD, (stx + 14, sty), (stx + 26, sty), 2)

        draw_vignette(screen, game)

        for ft in game.floating_texts:
            ft.draw(screen, cx, cy)

        game.draw_hud(screen)
        game.draw_hud_plus(screen)

        if game.state == "playing":
            touch_btns = draw_touch_controls(screen, game)
            if not MOBILE:
                draw_custom_crosshair(screen, (mx, my), pygame.mouse.get_pressed()[0] or game.auto_fire, sc["bullet"])
        elif game.state == "levelup":
            reroll_btn_rect = game.draw_cards(screen)
        elif game.state == "paused":
            pause_rects = game.draw_pause_screen(screen)
        elif game.state == "gameover":
            gameover_rects = game.draw_gameover_screen(screen)

    game.draw_toast(screen)
    if _fade_t > 0:
        _fade_t = max(0.0, _fade_t - dt)
        draw_veil(screen, int(215 * _fade_t / 0.28))

    mobile_present() if MOBILE else pygame.display.flip()
    if SMOKE_FRAMES:
        _smoke["upd"].append(_t_upd)
        _smoke["frame"].append(time.perf_counter() - _t_frame)
        _smoke["maxent"] = max(_smoke["maxent"], len(game.enemies))
        _smoke["maxpart"] = max(_smoke["maxpart"], len(game.particles))
        if SMOKE_SHOTS and _smoke["n"] in (500, 1100, 1700):
            pygame.image.save(screen, os.path.join(SMOKE_SHOTS, f"shot_{_smoke['n']}.png"))
        if _smoke["n"] >= SMOKE_FRAMES:
            _f = sorted(_smoke["frame"]); _u = sorted(_smoke["upd"])
            _avg = sum(_f) / len(_f)
            print(f"FRAMES={len(_f)} frame_ms avg={_avg*1000:.2f} p95={_f[int(len(_f)*.95)]*1000:.2f} max={_f[-1]*1000:.2f} | update_ms avg={sum(_u)/len(_u)*1000:.2f} p95={_u[int(len(_u)*.95)]*1000:.2f} | draw_ms avg={(_avg - sum(_u)/len(_u))*1000:.2f}")
            print(f"nivel={game.level} kills={game.kills} bosses={game.bosses} max_inimigos={_smoke['maxent']} max_particulas={_smoke['maxpart']} estado={game.state}")
            print(f"NET online={game.online} role={game.online_role} peer={game.net.connected_peer} rtt={game.net.rtt_ms:.1f}ms up={game.net.kbps_up:.1f}KB/s dn={game.net.kbps_down:.1f}KB/s puppets={len(getattr(game, 'puppets', {}))} enemies={len(game.enemies)} orbs={len(game.orbs)} hazards={len(game.hazards)} props_alive={sum(1 for p_ in game.props if p_.alive)}/{len(game.props)} partner=({game.partner.x:.0f},{game.partner.y:.0f}) hp={game.partner.hp:.0f} bullets={len(game.bullets)}" if game.partner else f"NET online={game.online} sem parceiro hazards={len(game.hazards)} props={len(game.props)}")
            running = False

pygame.quit()
sys.exit()