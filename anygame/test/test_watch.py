"""Press and watch: background shift, movers (and their ghosts on a tiled floor), the player, walking, the walk book."""
import numpy as np

from anygame.perceive.watch import Watcher, WalkBook, bg_shift, movers


def _world(h=400, w=400, seed=0):
    """A big tiled map: a checker floor with scattered dark blocks, RGB."""
    rng = np.random.default_rng(seed)
    floor = np.indices((8, 8)).sum(0) % 2 * 60 + 150
    img = np.tile(floor, (h // 8, w // 8)).astype(np.uint8)
    for _ in range(60):
        r, c = rng.integers(0, h // 8), rng.integers(0, w // 8)
        img[r * 8:(r + 1) * 8, c * 8:(c + 1) * 8] = 30
    return np.repeat(img[:, :, None], 3, axis=2)


def _sprite(n=16, seed=1):
    rng = np.random.default_rng(seed)
    s = rng.integers(0, 3, size=(n, n)) * 100 + 5        # three colours the floor never uses
    s[0, :] = -1                                         # a transparent row
    return s


def _draw(world, cam, sprite=None, at=None):
    x, y = cam
    img = world[y:y + 144, x:x + 160].copy()
    if sprite is not None:
        sx, sy = at
        on = sprite >= 0
        patch = img[sy:sy + sprite.shape[0], sx:sx + sprite.shape[1]]
        patch[on] = sprite[on][:, None].astype(np.uint8)
    return img


def test_bg_shift_finds_a_scroll():
    world = _world()
    a, b = _draw(world, (100, 100)), _draw(world, (116, 100))
    dx, dy, agree = bg_shift(a, b)
    assert (dx, dy) == (-16, 0) and agree > 0.99
    assert bg_shift(a, a)[:2] == (0, 0)


def test_a_sprite_walking_on_a_tiled_floor_is_one_mover_without_its_ghost():
    world = _world()
    spr = _sprite()
    a = _draw(world, (100, 100), spr, (64, 64))
    b = _draw(world, (100, 100), spr, (48, 64))
    ms, changed, _ = movers(a, b, (0, 0))
    assert len(ms) == 1
    m = ms[0]
    assert m.v == (-16, 0) and abs(m.x - 48) <= 1 and abs(m.y - 64) <= 2


def test_a_player_the_camera_follows_moves_against_the_background():
    world = _world()
    spr = _sprite()
    a = _draw(world, (100, 100), spr, (72, 64))
    b = _draw(world, (116, 100), spr, (72, 64))     # walked right: the map scrolled left, the player stayed
    ms, _, _ = movers(a, b, bg_shift(a, b)[:2])
    assert [m.v for m in ms] == [(16, 0)]


def _walk(presses, blocked=lambda cam: False):
    """Play a screen-locked player through `presses` on the big map; yields (prev, press, cur, moved)."""
    world = _world()
    spr = _sprite()
    cam = [100, 100]
    prev = _draw(world, cam, spr, (72, 64))
    step = {"right": (16, 0), "left": (-16, 0), "down": (0, 16), "up": (0, -16)}
    for p in presses:
        d = step.get(p, (0, 0))
        moved = p in step and not blocked((cam[0] + d[0], cam[1] + d[1]))
        if moved:
            cam = [cam[0] + d[0], cam[1] + d[1]]
        cur = _draw(world, cam, spr, (72, 64))
        yield prev, p, cur, moved
        prev = cur


def test_the_player_is_found_and_its_walks_judged():
    w = Watcher()
    presses = ["right", "down", "left", "up"] * 6
    verdicts = []
    for prev, p, cur, moved in _walk(presses):
        eff = w.see(prev, p, cur)
        verdicts.append((eff.moved, moved))
    assert w.player is not None and abs(w.player.x - 72) <= 2 and abs(w.player.y - 64) <= 2
    judged = [(v, m) for v, m in verdicts[6:] if v is not None]
    assert len(judged) >= 12 and all(v == m for v, m in judged)
    assert w.steps.most_common(1)[0][0] == 16


def test_a_press_that_changes_nothing_after_walking_is_a_bump():
    w = Watcher()
    presses = ["right", "down", "left", "up"] * 4 + ["right", "right", "right"]
    out = []
    for prev, p, cur, moved in _walk(presses, blocked=lambda cam: cam[0] > 116):
        out.append((w.see(prev, p, cur).moved, moved))
    assert out[-1] == (False, False) and out[-2] == (False, False)


def test_walk_book_trusts_any_step_over_bumps():
    wb = WalkBook()
    keys = np.array([[f"k{r}{c}" for c in range(20)] for r in range(18)], dtype=object)
    cells = WalkBook.targets(keys, (0, 0), (64, 64, 16, 16), "right", 16)
    assert sorted(cells) == ["k810", "k811", "k910", "k911"]
    assert wb.says(cells) is None
    wb.add(cells, False)
    assert wb.says(cells) is False
    wb.add(cells, True)
    assert wb.says(cells) is True
