# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Among Us clone in Python/pygame, rebuilt for **LAN multiplayer (3–12 players)**. The owner's goal: one person hosts from the game menu, everyone on the same network joins, and the game runs everything (roles, tasks, meetings) automatically. Not a git repo locally. The target machines are Windows with Python 3.12.

Two codebases live side by side:
- **`amongus/` + `main.py` + `server.py`**: the new LAN game. All new work goes here.
- **Root legacy modules** (`classic.py`, `game.py`, `menu.py`, `board.py`, `sprites.py`, `settings.py`, `tasks.py`, `tilemap.py`, `gamefunctions.py`, `drawable.py`): the original single-player "Classic Mode", launched via `classic.py`. It is client-authoritative and full of hardcoded state, so don't extend it. Its online mode was disabled in `menu.py`. `legacy/server_old_asyncore.py` is the original broken server, kept for reference only.

## Commands

```bash
pip install -r requirements.txt          # pygame, numpy (vision), pytmx (classic only)
python main.py                           # game (menu: Host / Join / Practice with bots)
python server.py [--port N] [--name X]   # optional dedicated server
python -m amongus.bot --host IP --count N

python -m unittest tests.test_logic                 # rules: ~44 tests, <2 s, no pygame needed
python -m unittest tests.test_client_panels         # every panel/overlay, headless (SDL dummy), ~45 s
python -m unittest tests.test_logic.MeetingTests.test_tie_and_skip   # single test
python tests/client_e2e.py [shot_dir]               # real client + server + 7 bots; E2E_ROLE=imposter|crew
python tests/stress.py --players 12 --duration 300 [--chaos 0.1 --abuse --churn 20 --subprocess]
python tests/multi_client.py --clients 6 --bots 4   # N real client *processes*
python tools/gen_colours.py                         # regenerate colour sprite sheets (needs numpy)
```

Always run from the repo root (legacy code uses CWD-relative paths; the new code uses `config.ASSETS`). Headless tests set `SDL_VIDEODRIVER=dummy` / `SDL_AUDIODRIVER=dummy`. `tests/client_e2e.py` writes screenshots, so **look at them** after UI changes.

## Architecture (new game)

**Server-authoritative rules, client-authoritative movement.** Clients send positions and *intents*. The server validates every intent (role, alive, phase, cooldown, distance to target/station using `POSITION_SLACK`) and owns all game state.

- `amongus/config.py`: ports (TCP 4321, UDP discovery 4320), tick rates, ranges, durations, colour palette, `DEFAULT_SETTINGS` + `SETTING_LIMITS` (host-editable), `PROTOCOL_VERSION`. Bump `PROTOCOL_VERSION` on any wire change.
- `amongus/protocol.py`: 4-byte length prefix + JSON frames, `FrameReader` for TCP reassembly. **Never pickle/eval network data.**
- `amongus/world.py`: pure-Python map data shared by server/client/bots. Loads walls and vents from `Assets/Maps/map.tmx` (rendered image is `map2.png`, 5792×3168). Contains `ROOMS` rects, `STATIONS` (every interactable point), `TASKS` (kind common/long/short, steps = `[(station, minigame)]`), `SABOTAGES` (panels), `CAMERAS`, the `Collider` (spatial hash, feet hitbox 36×20 above the position point), the vent network, spawn ring, and BFS flow fields for bots. A player's `(x, y)` is the point between the feet.
- `amongus/logic.py`: `GameLogic`, **all rules**, no sockets and no clock (`now` is passed in). Phases: `lobby → reveal → play ⇄ meeting (intro/discussion/vote/results) → eject → play … → over → lobby`. It emits messages through `Outbox` (`send(pid, msg)`, `broadcast(msg, only=predicate)`, special `("close", pid)` for kicks). `snapshot()` is the common 30 Hz state; `personal()` is per-player cooldowns. Win checks run after kills, task steps, disconnects, end of eject, and sabotage expiry. `force_imposters` is a test hook.
- `amongus/server.py`: `Server`, a single-threaded `selectors` loop (TCP accept/read/write + UDP discovery + tick), so there are no locks. Per-connection out-buffers with a slow-consumer cutoff, idle timeout, and exception isolation (`stats["handler_errors"]` must stay 0, `protocol_errors` counts rejected garbage). The game hosts by running `Server.run` on a daemon thread (`App.start_server`).
- `amongus/discovery.py`: UDP broadcast browse (`discover()`) and responder (`answer()`).
- `amongus/bot.py`: headless bot using the real protocol (walks via flow fields, tasks, kills, reports, fixes, votes, chats; optional `chaos`). Used by tests and the lobby's "Add bot".
- `amongus/client/`: `app.py` (window 1280×720 `SCALED|RESIZABLE`, scene loop, hosting, bots, background asset preloading), `net.py` (reader thread → queue), `menus.py`, `lobby.py`, `game.py` (`GameScene`: movement, interpolation, targets for use/kill/report/vent, HUD, `net_<type>` message handlers), `overlays.py` (role reveal, meeting/voting, eject, game over, kill animation), `minigames.py` (all task/fix/utility panels + Tab map), `vision.py` (numpy ray-cast line of sight against TMX `walls` only), `assets.py` (cached images/fonts, sound wrapper that no-ops without audio), `ui.py` (widgets, cached outlined text).

### Wire protocol (client → server `t` values)
`hello{v,name,colour}` (first message), `ping{c}`, `colour`, `settings{settings}` (host), `start` (host), `kick{id}` (host), `chat{text}`, `pos{x,y,d,m,ep}`, `kill{target}`, `report{body}`, `emergency`, `vote{target|"skip"}`, `task{task,step}`, `sabotage{kind}`, `fix{panel}`, `hold{panel,on}` (reactor), `vent{act:enter|move|exit,id|to}`.
Server → client: `welcome`, `lobby`, `spectate`, `game_start` (role; impostor ids only sent to impostors), `play`, `snap{ph,pl:[[id,x,y,dir,moving,alive,vent]],bd,tb,sab,ms,me}`, `teleport{x,y,ep}`, `killed`, `kill_ok`, `deny`, `task_ok`, `vent_state`, `sabotage`, `sabotage_end`, `meeting`, `meeting_stage`, `voted`, `vote_result`, `eject`, `resume`, `chat`, `left`, `game_over`, `to_lobby`, `error`, `kicked`, `pong`.

**Position epochs:** every server-side teleport (kill snap, vent exit, post-meeting respawn) increments the player's `epoch` and sends `teleport`. `pos` messages carrying an old `ep` are ignored. Preserve this whenever you add a server-forced move. Entering or moving between vents moves the player server-side without a teleport; the client snaps itself on `vent_state`.

### Adding things
- **New task:** add a station to `STATIONS` (check reachability, see below), an entry in `TASKS`, a `Minigame` subclass in `minigames.py` registered in `MINIGAMES`, a solver branch in `tests/client_e2e.py:solve`, and optionally a highlight in `game.py:HIGHLIGHT`.
- **New setting:** `DEFAULT_SETTINGS` + `SETTING_LIMITS` in config, a row in `lobby.py:SETTING_ROWS`, use it in `logic.py`.
- Minigames call `on_success` **once** via `succeed()`. They expose their hit geometry as attributes, which the headless tests rely on.
- Station coordinates must be reachable on foot: `tests.test_logic.WorldTests` checks every station, vent exit and spawn against the real map (many props are solid; e.g. the Navigation console point had to sit in front of the console).

## Gotchas
- Windows `time.monotonic()` has 15.6 ms resolution. Use `time.perf_counter()` for anything timed (server ticks, RTT).
- Never block the main thread on big images. The map/minimap PNGs are decoded on a thread in the menus and lobby (`App.start_preload`/`preload_tick`), and first-use surfaces are warmed during the role reveal (`GameScene._preload`). `convert()` must happen on the main thread.
- Legacy code relies on Windows case-insensitive paths and backslash literals. The new code uses exact on-disk case.
- Sprites: `Assets/Images/Player/Sheets/<Colour>.png` are generated from the Blue frames by `tools/gen_colours.py` (layout constants in `client/assets.py`). Only 5 colours had original animations.
- Bots and the in-process host server share the GIL with the client. Stress numbers measured in-process are pessimistic; `--subprocess` gives real server numbers.

## Known limitations
- Movement is client-authoritative (fine for a trusted LAN; a modified client could teleport). Kill/report/task range checks on the server limit the damage.
- No reconnect-into-the-same-round: a player who drops mid-game is removed (their tasks leave the total); they can rejoin for the next round.
- The game hosted from the menu dies with the host's window. Use `server.py` for a host-independent server.
- Doors sabotage and some Skeld tasks (e.g. calibrate distributor) are not implemented.
