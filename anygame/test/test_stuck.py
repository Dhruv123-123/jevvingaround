import numpy as np

from anygame.stuck import Stuck, fingerprint


def test_a_loop_through_seen_screens_is_raised_with_what_repeated():
    s = Stuck(window=20, quiet=10)
    out = []
    for t in range(60):
        # a conversation that sends the player back: the same three screens, two actions
        screen = ["text", "world", "world"][t % 3]
        text = "Don't go away yet!" if screen == "text" else ""
        pos = (5, 1 + t % 3, 0) if screen == "world" else None
        out.append(s.see(t, "auto: key a" if screen == "text" else "explore_up: up up", screen, text, pos))
    raised = [o for o in out if o]
    assert raised and raised[0]["tick"] < 25
    assert set(raised[0]["repeated"]) == {"auto: key a", "explore_up"}
    assert all(b["tick"] - a["tick"] >= 10 for a, b in zip(raised, raised[1:]))
    assert s.suggest(["explore_up: up", "explore_left: left", "talk: A"])[:3] == \
        ["explore_left: left", "talk: A", "press B"]


def test_exploring_and_reading_new_text_never_raise():
    s = Stuck(window=20)
    for t in range(200):
        assert s.see(t, "explore_right: right", "world", "", (t, 3, 0)) is None
    s = Stuck(window=20)
    for t in range(200):
        assert s.see(t, "auto: key a", "text", f"line {t}") is None


def test_new_frames_count_as_news_when_the_reads_say_nothing():
    s = Stuck(window=20)
    rng = np.random.default_rng(0)
    for t in range(100):
        frame = np.zeros((144, 160), np.uint8)
        frame[:, (t * 7) % 160:] = 255              # a scrolling level: the print changes every step
        assert s.see(t, "hold_right", "play", "", None, frame=frame) is None
    frame = rng.integers(0, 255, (144, 160)).astype(np.uint8)
    assert fingerprint(frame) == fingerprint(frame.copy())
