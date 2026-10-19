"""Where can the player walk on this map, and how do you get there? A RAM test helper for planning fixture walks (like
pokemon_fixture_walk.py; the agent never reads RAM): from a save, try every direction from every square reached,
with the emulator's own save states, so ledges, people and trees count as they do in the game.

    python scripts/pokemon_reach.py IN.state                  # the squares reached on this map, and the doors out
    python scripts/pokemon_reach.py IN.state X,Y              # ... and the shortest way there
    python scripts/pokemon_reach.py IN.state OUT.state X,Y,DIR,N [...]
        (walk to X,Y, face DIR, press A N times then B through the text, fight out any battle; then the next one;
        saves OUT.state: e.g. the Vermilion Gym trash cans, where a second A on a can resets the locks)
"""
from __future__ import annotations
import collections
import io
import shutil
import sys
import tempfile

ROM = "/mnt/project-files/roms/pokemon-red.gb"
MAP, X, Y, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057
DIRS = ("up", "down", "left", "right")


def main() -> None:
    from pyboy import PyBoy
    rom = tempfile.mkdtemp(prefix="pkreach-") + "/p.gb"
    shutil.copyfile(ROM, rom)
    pb = PyBoy(rom, window="null", sound_emulated=False)
    with open(sys.argv[1], "rb") as f:
        pb.load_state(f)
    pb.tick(2)
    m = pb.memory

    def snap():
        b = io.BytesIO()
        pb.save_state(b)
        return b.getvalue()

    def key(k, n=1):
        for _ in range(n):
            pb.button_press(k)
            pb.tick(8)
            pb.button_release(k)
            pb.tick(24)

    def fight():                        # a trainer saw us, or we talked to one: first move, healed (test helper)
        k = 0
        while m[BATTLE] and k < 1500:
            m[0xD16C], m[0xD16D] = m[0xD18D], m[0xD18E]
            key("a")
            k += 1

    def explore(goal=None, fights=False):
        here, start = m[MAP], (m[X], m[Y])
        seen, par, doors = {start: snap()}, {start: None}, collections.defaultdict(set)
        todo = collections.deque([start])
        while todo and goal not in seen:
            p = todo.popleft()
            for d in DIRS:
                pb.load_state(io.BytesIO(seen[p]))
                key(d)
                if fights:
                    fight()
                if m[BATTLE]:
                    continue
                if m[MAP] != here:
                    doors[m[MAP]].add(p)
                    continue
                q = (m[X], m[Y])
                if q not in seen:
                    seen[q], par[q] = snap(), (p, d)
                    todo.append(q)
        return here, seen, par, doors

    if len(sys.argv) > 3:
        for step in sys.argv[3:]:
            x, y, d, n = step.split(",")
            _, seen, _, _ = explore((int(x), int(y)), fights=True)
            pb.load_state(io.BytesIO(seen[(int(x), int(y))]))
            key(d)
            key("a", int(n))
            key("b", 10)
            pb.tick(60)
            fight()
            print(step, "map", m[MAP], "x", m[X], "y", m[Y], "badges", bin(m[0xD356]), flush=True)
        with open(sys.argv[2], "wb") as f:
            pb.save_state(f)
        return
    here, seen, par, doors = explore()
    xs, ys = [p[0] for p in seen], [p[1] for p in seen]
    print("map", here, "squares", len(seen), "x", min(xs), max(xs), "y", min(ys), max(ys))
    print("doors", {k: sorted(v)[:4] for k, v in doors.items()})
    grid = [[" "] * (max(xs) + 1) for _ in range(max(ys) + 1)]
    for x, y in seen:
        grid[y][x] = "."
    print("\n".join("".join(r) for r in grid))
    if len(sys.argv) > 2:
        t, path = tuple(int(v) for v in sys.argv[2].split(",")), []
        while par.get(t):
            t, d = par[t]
            path.append(f"{t[0]},{t[1]}{d[0]}")
        print("path", " ".join(reversed(path)))


if __name__ == "__main__":
    main()
