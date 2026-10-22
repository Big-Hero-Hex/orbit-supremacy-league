"""Opening diagnostics: actual fire before each player's first ship loss.

Runs on the trusted host after the isolated games. It only reads each game's
captured visual frames and action log (both already published); it never loads
a model or the official engine, so the locked worker core and every cached
pair stay valid. Frames are stored every 2 ticks, so shot times have 2-tick
resolution; every game is cross-checked against the official weapon counters.
"""
import array
import ast
import csv
import gzip
import json
import math
import statistics
import struct
import sys
import zipfile
from pathlib import Path

VERSION = 1
AIM_DEGREES = 15
REPLAY_LIMIT = 96 * 1024 * 1024
ACTIONS_LIMIT = 1024 * 1024

def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi

def read_replay(path):
    """Bounded read: recordings come from the networkless model container."""
    with gzip.open(path, "rb") as stream: raw = stream.read(REPLAY_LIMIT + 1)
    if len(raw) > REPLAY_LIMIT: raise ValueError("Replay too large")
    return json.loads(raw)

def read_actions(path):
    """Stdlib reader for the float32 (ticks, 2 seats, 3) actions array in audit NPZ."""
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("actions.npy")
        if info.file_size > ACTIONS_LIMIT: raise ValueError("Action log too large")
        raw = archive.read(info)
    if raw[:6] != b"\x93NUMPY": raise ValueError("Not an npy array")
    size, start = (struct.unpack("<H", raw[8:10])[0], 10) if raw[6] == 1 else (struct.unpack("<I", raw[8:12])[0], 12)
    header = ast.literal_eval(raw[start:start + size].decode("latin1"))
    shape = tuple(header["shape"])
    if header["descr"] != "<f4" or header["fortran_order"] or len(shape) != 3 or shape[1:] != (2, 3): raise ValueError("Unexpected action array")
    values = array.array("f"); values.frombytes(raw[start + size:])
    if sys.byteorder == "big": values.byteswap()
    if len(values) != shape[0] * 6: raise ValueError("Truncated action array")
    return values, shape[0]

def heading_error(me, them):
    """Radians between a ship's nose and the direction to another object.

    Ship nose is local (0,-20) rotated by angle: heading (sin a, -cos a)."""
    return abs(wrap(math.atan2(them[1] - me[1], them[0] - me[0]) - math.atan2(-math.cos(me[2]), math.sin(me[2]))))

def fired(before, after, ticks):
    """Discharges between two frames of one ship.

    Counts the ammo + laser charges that disappeared, or one shot when the
    weapon cooldown was re-armed (a reload in the same window hides the ammo
    drop, never the cooldown)."""
    spent = max(0, before[5] - after[5]) + max(0, before[7] - after[7])
    return max(spent, int(after[6] > max(0, before[6] - ticks)))

def discharges(frames, seat):
    """Window-end tick of every actual gun/laser discharge by one seat."""
    ticks = []
    for p, c in zip(frames, frames[1:]):
        ticks += [c["t"]] * fired(p["s"][seat], c["s"][seat], c["t"] - p["t"])
    return ticks

def game_opening(row, record, actions=None):
    frames = record["frames"]
    if not frames or any(len(f["s"]) != 2 or any(len(s) != 9 for s in f["s"]) for f in frames): raise ValueError("Unexpected frame layout")
    if any(b["t"] <= a["t"] for a, b in zip(frames, frames[1:])): raise ValueError("Frames out of order")
    start = frames[0]["t"]; players = {}
    for seat, sid in enumerate(("ship1", "ship2")):
        pid = row["assignment"][sid]
        loss = min((e["tick"] for e in row["timeline"] if e["kind"] in ("eject", "kill") and e.get("target") == pid), default=None)
        shots = discharges(frames, seat)
        # A pilot cannot fire, so a discharge in the window holding the loss
        # happened at or before the loss tick.
        before = [t for t in shots if loss is None or t <= loss + 1]
        aimed = sampled = 0
        for f in frames:
            if loss is not None and f["t"] >= loss: break
            me, them = f["s"][seat], f["s"][1 - seat]
            if not (me[3] and not me[4] and them[3]): continue
            sampled += 1; aimed += heading_error(me, them) <= math.radians(AIM_DEGREES)
        trigger = None
        if actions is not None:
            values, steps = actions
            # actions[j] is applied in the step that produces tick start+j+1.
            trigger = sum(1 for j in range(steps) if (loss is None or start + j + 1 <= loss) and values[j * 6 + seat * 3 + 2] > 0)
        audited = row["metrics"][pid]["gun_shots"] + row["metrics"][pid]["laser_shots"]
        players[pid] = {"first_shot": shots[0] if shots else None, "first_loss": loss, "shots_before_loss": len(before),
                        "trigger_before_loss": trigger, "aim_before_loss": round(aimed / sampled, 4) if sampled else None,
                        "exact": len(shots) == audited}
    return {"version": VERSION, "players": players}

def attach(pair, folder):
    """Fill missing per-game opening records from the pair's stored recordings."""
    folder = Path(folder); failed = 0
    for row in pair["games"]:
        if (row.get("opening") or {}).get("version") == VERSION: continue
        try:
            record = read_replay(folder / row["replay"])
            try: actions = read_actions(folder / row["audit"])
            except Exception: actions = None
            row["opening"] = game_opening(row, record, actions)
        except Exception:
            row.pop("opening", None); failed += 1
    pair["opening"] = {pid: summary(pair["games"], pid) for pid in (pair["a"], pair["b"])}
    return failed

def fired_first(row, player):
    """1 if this player discharged first, 0 if the opponent did, .5 same window."""
    data = row["opening"]["players"]; mine = data[player]["first_shot"]
    theirs = next(v["first_shot"] for k, v in data.items() if k != player)
    if mine is None and theirs is None: return None
    if theirs is None or (mine is not None and mine < theirs): return 1
    if mine is None or mine > theirs: return 0
    return .5

def summary(games, player):
    rows = [r for r in games if (r.get("opening") or {}).get("version") == VERSION and player in r["opening"]["players"]]
    mine = [r["opening"]["players"][player] for r in rows]
    lost = [o for o in mine if o["first_loss"] is not None]
    silent = [o for o in lost if o["shots_before_loss"] == 0]
    first = [(fired_first(r, player), r["winner"] == player) for r in rows]
    def median(values): return round(statistics.median(values), 3) if values else None
    def rate(flags): return sum(flags) / len(flags) if flags else None
    aims = [o["aim_before_loss"] for o in mine if o["aim_before_loss"] is not None]
    return {"games": len(rows), "lost_first_ship": len(lost), "silent_losses": len(silent),
            "silent_loss_rate": rate([o["shots_before_loss"] == 0 for o in lost]),
            "silent_without_trigger": sum(o["trigger_before_loss"] == 0 for o in silent),
            "shots_before_loss_median": median([o["shots_before_loss"] for o in lost]),
            "first_shot_median_s": median([o["first_shot"] / 50 for o in mine if o["first_shot"] is not None]),
            "never_fired": sum(o["first_shot"] is None for o in mine),
            "first_loss_median_s": median([o["first_loss"] / 50 for o in lost]),
            "fired_first_rate": rate([f for f, _ in first if f is not None]),
            "win_rate_fired_first": rate([won for f, won in first if f == 1]),
            "win_rate_opponent_fired_first": rate([won for f, won in first if f == 0]),
            "aim_before_loss_mean": statistics.mean(aims) if aims else None,
            "exact_games": sum(o["exact"] for o in mine)}

SUMMARY_FIELDS = ["games", "lost_first_ship", "silent_losses", "silent_loss_rate", "silent_without_trigger",
                  "shots_before_loss_median", "first_shot_median_s", "never_fired", "first_loss_median_s",
                  "fired_first_rate", "win_rate_fired_first", "win_rate_opponent_fired_first", "aim_before_loss_mean", "exact_games"]
LOG_FIELDS = ["pair", "game_id", "seed", "player_id", "name", "opponent_id", "seat", "result", "game_ticks",
              "first_shot_tick", "first_shot_s", "first_loss_tick", "first_loss_s", "shots_before_loss",
              "trigger_ticks_before_loss", "silent_loss", "fired_first", "aim_share_before_loss", "timing_matches_official_count"]

def export(folder, state):
    """UTF-8 BOM per-game log and per-player summary; blank means not applicable."""
    folder = Path(folder); people = {p["id"]: p for p in state["players"]}; log = []; table = []
    for pair in state["pairs"]:
        for r in pair["games"]:
            if (r.get("opening") or {}).get("version") != VERSION: continue
            for seat, pid in r["assignment"].items():
                o = r["opening"]["players"][pid]
                log.append({"pair": pair["key"], "game_id": r["id"], "seed": r["seed"], "player_id": pid, "name": people[pid]["name"],
                            "opponent_id": next(v for v in r["assignment"].values() if v != pid), "seat": seat,
                            "result": "draw" if r["winner"] is None else "win" if r["winner"] == pid else "loss", "game_ticks": r["ticks"],
                            "first_shot_tick": o["first_shot"], "first_shot_s": None if o["first_shot"] is None else o["first_shot"] / 50,
                            "first_loss_tick": o["first_loss"], "first_loss_s": None if o["first_loss"] is None else o["first_loss"] / 50,
                            "shots_before_loss": o["shots_before_loss"], "trigger_ticks_before_loss": o["trigger_before_loss"],
                            "silent_loss": None if o["first_loss"] is None else int(o["shots_before_loss"] == 0),
                            "fired_first": fired_first(r, pid), "aim_share_before_loss": o["aim_before_loss"], "timing_matches_official_count": int(o["exact"])})
        for pid in (pair["a"], pair["b"]):
            table.append({"scope": "pair", "pair": pair["key"], "player_id": pid, "name": people[pid]["name"], **(pair.get("opening") or {}).get(pid, {})})
    table[:0] = [{"scope": "all", "pair": "", "player_id": r["id"], "name": people[r["id"]]["name"], **r.get("opening", {})} for r in state["standings"]]
    for name, rows, fields in (("opening_log.csv", log, LOG_FIELDS), ("opening_summary.csv", table, ["scope", "pair", "player_id", "name", *SUMMARY_FIELDS])):
        with (folder / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
