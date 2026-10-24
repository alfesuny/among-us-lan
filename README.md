# Among Us — LAN Edition

An unofficial Among Us clone in Python/pygame for **3–12 players on the same local network** (Wi‑Fi or cable). One person hosts from the game menu; everyone else joins from a list. Roles, tasks and everything else are handled automatically.

Map, art and sounds are from the original project (Innersloth assets, see Credits).

## Quick start

**On every PC** (once):
1. Install **Python 3.8+** from [python.org](https://www.python.org/downloads/). Tick **"Add python.exe to PATH"** during setup.
2. Copy this folder to the PC and double-click **`Install.bat`** (or run `python -m pip install -r requirements.txt`).

**To play:**
1. Double-click **`Play.bat`** (or run `python main.py`) and type your name.
2. **One player** clicks **HOST GAME**. The lobby shows the address others can use, e.g. `Others join with: 192.168.0.53`.
3. **Everyone else** clicks **JOIN GAME**. The host's game appears in the list within a second or two. Click it. If it doesn't appear, type the host's IP in the box and press **JOIN IP**.
4. Pick a colour, then the host sets the options and presses **START**.

Want to try it alone? **PRACTICE WITH BOTS** hosts a game with 7 bots. In any lobby, the host can also add bots to fill empty seats.

### If friends can't see or join your game

- All PCs must be on the **same network** (same router / Wi‑Fi). Guest Wi‑Fi networks often block players from seeing each other.
- When you host for the first time, Windows asks whether Python may use the network. Tick **Private networks** and click **Allow**.
- If you clicked Cancel, or it still doesn't work: on the **host PC**, right-click **`Allow-Firewall.bat`** → *Run as administrator*. It removes Windows' "block Python" rules and opens the game ports (TCP 4321, UDP 4320).
- In Windows settings, set your network to **Private** (Settings → Network → your Wi‑Fi → Network profile).
- Joining by IP works even when the game list doesn't (some routers block broadcast).

## How to play

**Crewmates** win by finishing all tasks or by voting out every Impostor. **Impostors** win when they equal the number of crewmates, or when a Reactor/O2 sabotage isn't fixed in time.

| Key | Action |
|---|---|
| WASD / arrows | Move |
| E or Space | Use: do a task, fix a sabotage, press the emergency button, Admin map, Security cameras |
| Q | Kill (Impostor) |
| R | Report a dead body |
| V | Enter/leave a vent (Impostor). In a vent: A/D or click the arrows to switch vents |
| Tab / M | Map (Impostors sabotage from the map) |
| T | Show/hide your task list |
| Esc | Close a window |
| Enter | Chat (in meetings, and ghost chat when dead) |

Everything can also be clicked with the mouse.

**Features**
- Automatic role assignment: 1 Impostor for up to 6 players, 2 for 7+ (the host can choose 1–3)
- 13 tasks with interactive panels: Fix Wiring (3 panels), Swipe Card, Fuel Engines (2 steps), Clear Asteroids, Upload Data (2 steps), Start Reactor, Submit Scan, Empty Garbage, Reboot Wifi, Stabilize Steering, Divert Power, Align Engine Output, Prime Shields
- Common, long and short tasks; a total task bar for the whole crew
- Kills with cooldown, dead bodies, reporting, emergency meetings (limited per player, with cooldown)
- Meetings with discussion and voting timers, chat, skip vote, ties, optional anonymous votes and confirm ejects
- 4 sabotages: Lights (crew vision shrinks), Communications (task list and task bar hidden), Reactor (two players must hold both hand scanners **at the same time**) and O2 (codes entered in O2 **and** Admin). Reactor and O2 are critical: if not fixed in 45 s, the Impostors win.
- 14 vents in Skeld-style networks (Impostors only)
- Vision blocked by walls; Impostors see further; ghosts see everything
- Ghosts can float through walls, keep doing tasks and use a ghost-only chat
- Admin table (room occupancy) and Security cameras
- 12 colours, a lobby with host settings, kick, chat, and LAN game browser
- Players can join or leave at any time. Players who join mid-game wait for the next round, and anyone who leaves mid-game is removed cleanly. If the host leaves the lobby, another player becomes host.

**Host settings:** number of Impostors, kill cooldown, emergency meetings and cooldown, discussion and voting time, confirm ejects, anonymous votes, number of common/long/short tasks, crewmate and Impostor vision, player speed.

## Dedicated server (optional)

The host's game runs the server inside itself, so if the host closes their game, the round ends for everyone. To run it separately (for example on a PC nobody plays on):

```
python server.py            # or double-click Dedicated-Server.bat
python server.py --port 5000 --name "Friday night"
```

Everyone then uses JOIN GAME. The first player to join is the host (starts the game, changes settings).

## Classic mode

The original single-player version (you as the Impostor against bots) is still available from **CLASSIC MODE** in the menu or with `python classic.py`. It needs `pytmx`. Its old online mode has been replaced by this LAN version.

## Voice chat (experimental, separate)

`python server_voice.py` on one PC, then `python voice.py` on each PC (needs `pip install pyaudio`). Most LAN groups just talk in the room.

## For developers

```
python -m unittest tests.test_logic tests.test_client_panels   # rules + every UI panel (headless)
python tests/client_e2e.py                                      # real client + server + 7 bots, full round
python tests/stress.py --players 12 --duration 300 --chaos 0.1 --abuse --churn 20
python tests/multi_client.py --clients 6 --bots 4               # 6 real client processes
python -m amongus.bot --host 192.168.0.53 --count 5             # add bots to any game
```

See `CLAUDE.md` for the architecture.

## Credits
* [Innersloth](https://www.innersloth.com) for 'Among Us' and its assets.
* Original Python clone: the authors of the GitHub project this was downloaded from; base code from [kidscancode](https://github.com/kidscancode) tutorials, [Albert-91](https://github.com/Albert-91), [PlainSight](https://github.com/PlainSight) and [TomPrograms](https://github.com/TomPrograms) (voice chat).
