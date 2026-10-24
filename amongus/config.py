"""Constants shared by server, client and bots."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "Assets")

GAME_VERSION = "2.0"
PROTOCOL_VERSION = 3

TCP_PORT = 4321
DISCOVERY_PORT = 4320
DISCOVERY_MAGIC = b"AMONGUS_LAN_DISCOVER_V3"

SERVER_TICK_HZ = 30          # simulation + snapshot rate
CLIENT_SEND_HZ = 30          # position updates from clients
CLIENT_TIMEOUT = 15.0        # seconds of silence before a client is dropped
MAX_FRAME_BYTES = 1 << 20    # largest accepted network message
MAX_OUTBUF_BYTES = 4 << 20   # slow-consumer cutoff per client

MAX_PLAYERS = 12
MIN_PLAYERS_TO_START = 3
MAX_NAME_LEN = 12
MAX_CHAT_LEN = 100

# name: (main colour, shadow colour) — official Among Us palette
COLOURS = {
    "Red": ((197, 17, 17), (122, 8, 56)),
    "Blue": ((19, 46, 209), (9, 21, 142)),
    "Green": ((17, 127, 45), (10, 77, 46)),
    "Pink": ((237, 84, 186), (171, 43, 173)),
    "Orange": ((239, 125, 13), (179, 62, 21)),
    "Yellow": ((245, 245, 87), (194, 135, 34)),
    "Black": ((63, 71, 78), (30, 31, 38)),
    "White": ((214, 224, 240), (132, 149, 192)),
    "Purple": ((107, 47, 187), (59, 23, 124)),
    "Brown": ((113, 73, 30), (94, 38, 21)),
    "Cyan": ((56, 254, 220), (36, 168, 190)),
    "Lime": ((80, 239, 57), (21, 167, 66)),
}
COLOUR_NAMES = list(COLOURS)

# Gameplay tuning (world units are map pixels)
PLAYER_SPEED = 330.0
KILL_RANGE = 130.0
REPORT_RANGE = 170.0
USE_RANGE = 130.0
VENT_RANGE = 110.0
EMERGENCY_RANGE = 230.0
POSITION_SLACK = 90.0        # tolerance the server allows on client-reported distances

ROLE_REVEAL_SECONDS = 5.0
MEETING_INTRO_SECONDS = 3.0
VOTE_RESULTS_SECONDS = 5.0
EJECT_SECONDS = 6.5
GAME_OVER_SECONDS = 9.0
SABOTAGE_COOLDOWN = 30.0
REACTOR_SECONDS = 45.0
O2_SECONDS = 45.0
POST_MEETING_KILL_RESET = True

DEFAULT_SETTINGS = {
    "imposters": 0,            # 0 = automatic (1 for <=6 players, 2 for 7+)
    "kill_cooldown": 25,
    "emergency_meetings": 1,
    "emergency_cooldown": 15,
    "discussion_time": 15,
    "voting_time": 30,
    "confirm_ejects": True,
    "anonymous_votes": False,
    "common_tasks": 1,
    "long_tasks": 1,
    "short_tasks": 3,
    "crew_vision": 1.0,
    "imposter_vision": 1.5,
    "player_speed": 1.0,
}

# Allowed values for each setting: (min, max) for numbers, None for bools
SETTING_LIMITS = {
    "imposters": (0, 3),
    "kill_cooldown": (10, 60),
    "emergency_meetings": (0, 9),
    "emergency_cooldown": (0, 60),
    "discussion_time": (0, 120),
    "voting_time": (15, 300),
    "confirm_ejects": None,
    "anonymous_votes": None,
    "common_tasks": (0, 2),
    "long_tasks": (0, 3),
    "short_tasks": (0, 5),
    "crew_vision": (0.5, 3.0),
    "imposter_vision": (0.5, 3.0),
    "player_speed": (0.5, 2.0),
}


def auto_imposters(n_players):
    return 1 if n_players <= 6 else 2


def max_imposters(n_players):
    """Largest imposter count that still leaves crew a real game."""
    if n_players >= 9:
        return 3
    if n_players >= 7:
        return 2
    return 1


def clamp_setting(key, value):
    limits = SETTING_LIMITS.get(key, ())
    if limits is None:
        return bool(value)
    lo, hi = limits
    if isinstance(DEFAULT_SETTINGS[key], float) or isinstance(lo, float):
        v = float(value)
    else:
        v = int(round(float(value)))
    return max(lo, min(hi, v))
