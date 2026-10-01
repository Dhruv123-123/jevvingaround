"""A tiny X11 client for the desktop-device tests: one window with a title, a flat colour, that appends every key,
button and motion event it receives to a file. `python test/xclient.py <log file> [title] [w] [h]`."""
import sys, time
from Xlib import X, display, XK

log, title = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "anygame-xclient")
w, h = (int(sys.argv[3]) if len(sys.argv) > 3 else 300), (int(sys.argv[4]) if len(sys.argv) > 4 else 200)
d = display.Display()
scr = d.screen()
win = scr.root.create_window(10, 20, w, h, 0, scr.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x3b82f6,
                             event_mask=X.KeyPressMask | X.KeyReleaseMask | X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask | X.ExposureMask)
win.set_wm_name(title)
win.change_property(d.intern_atom("_NET_WM_NAME"), d.intern_atom("UTF8_STRING"), 8, title.encode())
win.map()
d.sync()
open(log, "a").write("ready\n")
while True:
    ev = d.next_event()
    if ev.type == X.KeyPress:
        sym = d.keycode_to_keysym(ev.detail, 0)
        open(log, "a").write(f"key {sym} send_event={int(ev.send_event)}\n")      # 65362 Up, 65363 Right, 32 space
    elif ev.type == X.ButtonPress:
        open(log, "a").write(f"button {ev.detail} at {ev.event_x},{ev.event_y}\n")
    elif ev.type == X.MotionNotify:
        open(log, "a").write(f"motion {ev.event_x},{ev.event_y}\n")
