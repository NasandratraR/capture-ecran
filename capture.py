#!/usr/bin/env python3
"""Capture — outil de capture d'écran léger (GTK3, X11).

Usage :
  capture.py            fenêtre principale
  capture.py -r         zone rectangulaire
  capture.py -f         plein écran
  capture.py -a         fenêtre active
  capture.py -d 3       délai de 3 s (combinable)
  capture.py -f -o x.png  enregistre directement sans éditeur
"""
import argparse, math, os, datetime
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio
import cairo

# ---------------------------------------------------------------- capture

def grab(x=None, y=None, w=None, h=None):
    root = Gdk.get_default_root_window()
    if x is None:
        x, y, w, h = 0, 0, root.get_width(), root.get_height()
    return Gdk.pixbuf_get_from_window(root, x, y, w, h)

def grab_active():
    win = Gdk.Screen.get_default().get_active_window()
    if win is None:
        return grab()
    r = win.get_frame_extents()
    return grab(r.x, r.y, r.width, r.height)


class RegionSelector(Gtk.Window):
    """Fenêtre plein écran figée : on trace un rectangle à la souris."""
    def __init__(self, full, callback):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.full, self.callback = full, callback
        self.start = self.end = None
        self.set_default_size(full.get_width(), full.get_height())
        self.move(0, 0)
        da = Gtk.DrawingArea(can_focus=True)
        da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                      | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        da.connect("draw", self.on_draw)
        da.connect("button-press-event", self.on_press)
        da.connect("motion-notify-event", self.on_motion)
        da.connect("button-release-event", self.on_release)
        da.connect("key-press-event", self.on_key)
        self.add(da)
        self.da = da
        self.show_all()
        da.grab_focus()
        seat = Gdk.Display.get_default().get_default_seat()
        seat.grab(self.get_window(), Gdk.SeatCapabilities.ALL, True,
                  Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "crosshair"), None, None)

    def rect(self):
        (x1, y1), (x2, y2) = self.start, self.end
        return int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1))

    def on_draw(self, w, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.full, 0, 0)
        cr.paint()
        cr.set_source_rgba(0, 0, 0, 0.45)
        if self.start and self.end:
            x, y, rw, rh = self.rect()
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.rectangle(0, 0, self.full.get_width(), self.full.get_height())
            cr.rectangle(x, y, rw, rh)
            cr.fill()
            cr.set_source_rgb(0.2, 0.6, 1)
            cr.set_line_width(1)
            cr.rectangle(x + .5, y + .5, rw, rh)
            cr.stroke()
            cr.move_to(x + 4, y - 6 if y > 20 else y + rh + 16)
            cr.set_font_size(13)
            cr.show_text(f"{rw} × {rh}")
        else:
            cr.paint()

    def on_press(self, w, e):
        self.start = self.end = (e.x, e.y)

    def on_motion(self, w, e):
        if self.start:
            self.end = (e.x, e.y)
            self.da.queue_draw()

    def on_release(self, w, e):
        self.end = (e.x, e.y)
        x, y, rw, rh = self.rect()
        self.finish(self.full.new_subpixbuf(x, y, rw, rh).copy() if rw > 2 and rh > 2 else None)

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape:
            self.finish(None)

    def finish(self, pix):
        Gdk.Display.get_default().get_default_seat().ungrab()
        self.destroy()
        self.callback(pix)

# ---------------------------------------------------------------- annotations

def draw_arrow(cr, x1, y1, x2, y2, size):
    a = math.atan2(y2 - y1, x2 - x1)
    L = 8 + size * 3
    # le trait s'arrête à l'intérieur de la pointe : son bout arrondi ne dépasse plus
    back = min(L * 0.6, math.hypot(x2 - x1, y2 - y1))
    cr.move_to(x1, y1)
    cr.line_to(x2 - back * math.cos(a), y2 - back * math.sin(a))
    cr.stroke()
    cr.move_to(x2, y2)
    cr.line_to(x2 - L * math.cos(a - 0.45), y2 - L * math.sin(a - 0.45))
    cr.line_to(x2 - L * math.cos(a + 0.45), y2 - L * math.sin(a + 0.45))
    cr.close_path(); cr.fill()

def brace_path(cr, s):
    """Trace une accolade entre les deux points ; renvoie la hauteur de la pointe."""
    (x1, y1), (x2, y2) = s["pts"][0], s["pts"][-1]
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1:
        return 0
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    # « } » : pointe à droite quand on trace de haut en bas ; « { » : à gauche
    nx, ny = (uy, -ux) if s["kind"] == "brace_r" else (-uy, ux)
    h = min(L / 4, 6 + s["size"] * 2 + L * 0.04)
    P = lambda a, b: (x1 + a * ux + b * nx, y1 + a * uy + b * ny)
    m = L / 2
    cr.move_to(*P(0, 0))
    cr.curve_to(*P(0, h * .55), *P(h * .45, h), *P(h, h))
    cr.line_to(*P(m - h, h))
    cr.curve_to(*P(m - h * .45, h), *P(m, h * 1.45), *P(m, 2 * h))
    cr.curve_to(*P(m, h * 1.45), *P(m + h * .45, h), *P(m + h, h))
    cr.line_to(*P(L - h, h))
    cr.curve_to(*P(L - h * .45, h), *P(L, h * .55), *P(L, 0))
    return 2 * h


def callout_tail(s):
    """Triangle de la pointe : deux points de base sur le bord du cadre + la pointe."""
    (ax, ay), (bx, by), (tx, ty) = s["pts"][:3]
    x0, x1, y0, y1 = min(ax, bx), max(ax, bx), min(ay, by), max(ay, by)
    if x0 <= tx <= x1 and y0 <= ty <= y1:
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    # bord le plus proche de la direction de la pointe
    if abs(ty - cy) / h >= abs(tx - cx) / w:
        yb = y1 if ty > cy else y0
        half = min(w * 0.18, 30)
        xm = min(max(tx, x0 + half + 8), x1 - half - 8) if w > 2 * half + 16 else cx
        return (xm - half, yb), (xm + half, yb), (tx, ty)
    xb = x1 if tx > cx else x0
    half = min(h * 0.25, 30)
    ym = min(max(ty, y0 + half + 8), y1 - half - 8) if h > 2 * half + 16 else cy
    return (xb, ym - half), (xb, ym + half), (tx, ty)


def wrap_text(cr, text, width):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if cur and cr.text_extents(trial).x_advance > width:
                lines.append(cur); cur = word
            else:
                cur = trial
        lines.append(cur)
    return lines


def draw_callout(cr, s):
    c, pts = s["color"], s["pts"]
    if len(pts) < 2:
        return
    (ax, ay), (bx, by) = pts[0], pts[1]
    x0, y0, w, h = min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay)
    # le cadre s'agrandit en hauteur si le texte ne tient pas
    text = s.get("text", "")
    fs = 8 + s["size"]
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(fs)
    lines = wrap_text(cr, text, max(10, w - 20)) if text else []
    need = fs * 1.3 * len(lines) + 16
    if h < need:
        grow = need - h
        if by >= ay:
            pts[1] = (bx, by + grow)
        else:
            pts[0] = (ax, ay + grow)
        h = need
    cr.set_source_rgba(c.red, c.green, c.blue, 1)
    r = min(10, w / 4, h / 4)
    cr.new_sub_path()
    cr.arc(x0 + w - r, y0 + r, r, -math.pi / 2, 0)
    cr.arc(x0 + w - r, y0 + h - r, r, 0, math.pi / 2)
    cr.arc(x0 + r, y0 + h - r, r, math.pi / 2, math.pi)
    cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path(); cr.fill()
    if len(pts) > 2:
        tail = callout_tail(s)
        if tail:
            cr.move_to(*tail[0]); cr.line_to(*tail[2]); cr.line_to(*tail[1])
            cr.close_path(); cr.fill()
    # texte centré, passage à la ligne automatique, couleur contrastée
    if text:
        lum = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
        cr.set_source_rgb(*((0, 0, 0) if lum > 0.6 else (1, 1, 1)))
        lh = fs * 1.3
        ty = y0 + (h - lh * len(lines)) / 2 + fs
        for i, line in enumerate(lines):
            ext = cr.text_extents(line)
            cr.move_to(x0 + (w - ext.x_advance) / 2, ty + i * lh)
            cr.show_text(line)


def draw_shape(cr, s, base):
    kind, c, size = s["kind"], s["color"], s["size"]
    cr.set_source_rgba(c.red, c.green, c.blue, 1)
    cr.set_line_width(size)
    cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
    pts = s["pts"]
    x1, y1 = pts[0]; x2, y2 = pts[-1]
    x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    if kind == "rect":
        cr.rectangle(x, y, w, h); cr.stroke()
    elif kind == "rectfill":
        cr.rectangle(x, y, w, h); cr.fill()
    elif kind == "ellipse" and w > 0 and h > 0:
        cr.save(); cr.translate(x + w / 2, y + h / 2); cr.scale(w / 2, h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi); cr.restore(); cr.stroke()
    elif kind == "line":
        cr.move_to(x1, y1); cr.line_to(x2, y2); cr.stroke()
    elif kind in ("brace_l", "brace_r"):
        s["depth"] = brace_path(cr, s)
        s["poly"] = [p for t, p in cr.copy_path_flat() if t != cairo.PATH_CLOSE_PATH]
        cr.stroke()
    elif kind == "callout":
        draw_callout(cr, s)
    elif kind == "arrow":
        draw_arrow(cr, x1, y1, x2, y2, size)
    elif kind in ("pen", "marker"):
        if kind == "marker":
            cr.set_source_rgba(c.red, c.green, c.blue, 0.35)
            cr.set_line_width(size * 5)
            cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()
    elif kind == "text":
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        fs, lh = 10 + size * 3, 12 + size * 3
        cr.set_font_size(fs)
        lines = s["text"].split("\n")
        for i, line in enumerate(lines):
            cr.move_to(x1, y1 + i * lh)
            cr.show_text(line)
        wmax = max(cr.text_extents(l).x_advance for l in lines)
        s["bbox"] = (x1, y1 - fs, wmax, (len(lines) - 1) * lh + fs * 1.3)
    elif kind == "number":
        r = 9 + size * 2
        cr.arc(x1, y1, r, 0, 2 * math.pi); cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(r * 1.1)
        t = str(s["n"]); ext = cr.text_extents(t)
        cr.move_to(x1 - ext.width / 2 - ext.x_bearing, y1 - ext.height / 2 - ext.y_bearing)
        cr.show_text(t)
    elif kind in ("pixel", "blur"):
        bw, bh = base.get_width(), base.get_height()
        x, y = max(0, int(x)), max(0, int(y))
        w, h = min(int(w), bw - x), min(int(h), bh - y)
        if w < 2 or h < 2:
            return
        sub = base.new_subpixbuf(x, y, w, h)
        f = int(4 + size * 2 if kind == "pixel" else 3 + size)
        small = sub.scale_simple(max(1, w // f), max(1, h // f), GdkPixbuf.InterpType.BILINEAR)
        interp = GdkPixbuf.InterpType.NEAREST if kind == "pixel" else GdkPixbuf.InterpType.BILINEAR
        big = small.scale_simple(w, h, interp)
        Gdk.cairo_set_source_pixbuf(cr, big, x, y)
        cr.rectangle(x, y, w, h); cr.fill()


TOOLS = [("select", "Sélection", "input-mouse-symbolic"),
         ("arrow", "Flèche", "go-next-symbolic"),
         ("callout", "Bulle", "chat-symbolic"),
         ("pen", "Crayon", "document-edit-symbolic"),
         ("marker", "Surligneur", "format-text-underline-symbolic"),
         ("line", "Ligne", "list-remove-symbolic"),
         ("rect", "Rectangle", "media-playback-stop-symbolic"),
         ("rectfill", "Rect. plein", "media-record-symbolic"),
         ("ellipse", "Ellipse", "radio-symbolic"),
         ("text", "Texte", "insert-text-symbolic"),
         ("number", "Numéro", "zoom-in-symbolic"),
         ("pixel", "Pixeliser", "view-grid-symbolic"),
         ("blur", "Flouter", "weather-fog-symbolic"),
         ("brace_l", "Accolade", "{"),
         ("brace_r", "Accolade", "}")]
BRACES = ("brace_l", "brace_r")
ENDPOINTS = ("line", "arrow") + BRACES   # redimensionnées par leurs deux extrémités


def sel_box(s):
    """Cadre de sélection (x0, y0, x1, y1) d'une annotation."""
    if s["kind"] == "text" and "bbox" in s:
        x, y, w, h = s["bbox"]
        return x, y, x + w, y + h
    if s["kind"] == "number":
        (x, y), r = s["pts"][0], 9 + s["size"] * 2
        return x - r, y - r, x + r, y + r
    if s["kind"] == "callout":   # le cadre, sans la pointe
        (ax, ay), (bx, by) = s["pts"][0], s["pts"][1]
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
    xs = [p[0] for p in s["pts"]]; ys = [p[1] for p in s["pts"]]
    return min(xs), min(ys), max(xs), max(ys)


def seg_dist(x, y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)


def hit_stroke(s, x, y):
    """Vrai si (x, y) touche le trait de l'annotation (pas l'intérieur d'un contour)."""
    k, tol = s["kind"], 6 + s["size"] / 2
    pts = s.get("poly") if k in BRACES else s["pts"]
    if k == "marker":
        tol += s["size"] * 2
    if k in ("line", "arrow", "pen", "marker") + BRACES:
        if len(pts) == 1:
            return math.hypot(x - pts[0][0], y - pts[0][1]) <= tol
        return any(seg_dist(x, y, *a, *b) <= tol for a, b in zip(pts, pts[1:]))
    x0, y0, x1, y1 = sel_box(s)
    if k == "rect":
        inside = x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol
        deep = x0 + tol < x < x1 - tol and y0 + tol < y < y1 - tol
        return inside and not deep
    if k == "ellipse":
        rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
        if rx < 1 or ry < 1:
            return False
        d = math.hypot((x - x0 - rx) / rx, (y - y0 - ry) / ry)
        return abs(d - 1) * min(rx, ry) <= tol
    if k == "callout" and len(s["pts"]) > 2:
        tail = callout_tail(s)
        if tail:
            (px, py), (qx, qy), (tx, ty) = tail
            d1 = (x - qx) * (py - qy) - (px - qx) * (y - qy)
            d2 = (x - tx) * (qy - ty) - (qx - tx) * (y - ty)
            d3 = (x - px) * (ty - py) - (tx - px) * (y - py)
            if (d1 < 0 and d2 < 0 and d3 < 0) or (d1 > 0 and d2 > 0 and d3 > 0):
                return True
    # formes pleines, texte, numéro, flou, bulle : tout l'intérieur
    return x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4


def sel_handles(s):
    """Poignées : [(x, y, id)] ; id = indice d'extrémité ou (hx, hy) sur le cadre."""
    if s["kind"] in ENDPOINTS:
        return [(*s["pts"][0], 0), (*s["pts"][-1], -1)]
    x0, y0, x1, y1 = sel_box(s)
    corners = [(0, 0), (1, 0), (0, 1), (1, 1)]
    if s["kind"] not in ("text", "number"):
        corners += [(.5, 0), (.5, 1), (0, .5), (1, .5)]
    hs = [(x0 + hx * (x1 - x0), y0 + hy * (y1 - y0), (hx, hy)) for hx, hy in corners]
    if s["kind"] == "callout" and len(s["pts"]) > 2:
        hs.append((*s["pts"][2], 2))   # poignée de la pointe
    return hs


MARGIN = 16


def shape_bounds(s):
    """Rectangle (x0, y0, x1, y1) occupé par une annotation, en coordonnées image."""
    if s["kind"] == "text" and "bbox" in s:
        x, y, w, h = s["bbox"]
        return x, y, x + w, y + h
    xs = [p[0] for p in s["pts"]]; ys = [p[1] for p in s["pts"]]
    pad = {"brace_l": s.get("depth", 40), "brace_r": s.get("depth", 40),
           "marker": s["size"] * 3, "number": 9 + s["size"] * 2,
           "arrow": 6 + s["size"] * 3}.get(s["kind"], s["size"]) + 2
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


class Canvas(Gtk.ScrolledWindow):
    """Un onglet : une capture et ses annotations."""
    def __init__(self, ed, pix, title):
        super().__init__()
        self.ed, self.base, self.title = ed, pix, title
        self.shapes, self.cur, self.drag = [], None, None
        # historique : chaque entrée est une copie complète de la liste des annotations
        self.history, self.future = [], []
        self.sel = None   # annotation sélectionnée (outil Sélection)
        self.ox = self.oy = MARGIN
        self.dirty = True          # pas encore enregistrée
        self.path = None

        # la zone de dessin occupe tout l'onglet : on peut annoter hors de la capture
        self.da = Gtk.DrawingArea()
        self.da.set_size_request(pix.get_width() + 2 * MARGIN, pix.get_height() + 2 * MARGIN)
        self.da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                           | Gdk.EventMask.POINTER_MOTION_MASK)
        self.da.connect("draw", self.on_draw)
        self.da.connect("button-press-event", self.on_press)
        self.da.connect("motion-notify-event", self.on_motion)
        self.da.connect("button-release-event", self.on_release)
        self.add(self.da)

        # étiquette de l'onglet : nom + bouton fermer
        self.label = Gtk.Label()
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Fermer l'onglet")
        close.connect("clicked", lambda *_: ed.close_tab(self))
        self.tab = Gtk.Box(spacing=4)
        self.tab.pack_start(self.label, False, False, 0)
        self.tab.pack_start(close, False, False, 0)
        self.tab.show_all()
        self.update_label()

    def update_label(self):
        self.label.set_text(self.title + ("*" if self.dirty else ""))
        self.tab.set_tooltip_text(self.path or "Non enregistrée")

    def changed(self):
        self.dirty = True
        self.update_label()
        self.da.queue_draw()

    # -- rendu
    def render(self, cr, shapes):
        Gdk.cairo_set_source_pixbuf(cr, self.base, 0, 0)
        cr.paint()
        for s in shapes:
            draw_shape(cr, s, self.base)

    def on_draw(self, w, cr):
        iw, ih = self.base.get_width(), self.base.get_height()
        # capture centrée, avec au moins MARGIN autour
        self.ox = max(MARGIN, (w.get_allocated_width() - iw) // 2)
        self.oy = max(MARGIN, (w.get_allocated_height() - ih) // 2)
        cr.translate(self.ox, self.oy)
        # fine ombre autour de la capture
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.rectangle(-1, -1, iw + 2, ih + 2); cr.fill()
        self.render(cr, self.shapes + ([self.cur] if self.cur else []))
        if self.sel in self.shapes and not self.cur:
            x0, y0, x1, y1 = sel_box(self.sel)
            cr.set_source_rgb(0.2, 0.5, 0.9); cr.set_line_width(1)
            cr.set_dash([4, 3])
            cr.rectangle(x0 - 4, y0 - 4, x1 - x0 + 8, y1 - y0 + 8); cr.stroke()
            cr.set_dash([])
            for hx, hy, _ in sel_handles(self.sel):
                cr.rectangle(hx - 4, hy - 4, 8, 8)
                cr.set_source_rgb(1, 1, 1); cr.fill_preserve()
                cr.set_source_rgb(0.2, 0.5, 0.9); cr.set_line_width(1.5); cr.stroke()

    def final_pixbuf(self):
        # passe à blanc pour connaître la taille des textes
        self.render(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)), self.shapes)
        x0, y0 = 0, 0
        x1, y1 = self.base.get_width(), self.base.get_height()
        for sh in self.shapes:
            if sh["kind"] in ("pixel", "blur"):
                continue
            a, b, c, d = shape_bounds(sh)
            x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
        x0, y0 = math.floor(x0), math.floor(y0)
        w, h = math.ceil(x1) - x0, math.ceil(y1) - y0
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        cr.set_source_rgb(1, 1, 1)   # fond blanc pour la zone hors capture
        cr.paint()
        cr.translate(-x0, -y0)
        self.render(cr, self.shapes)
        return Gdk.pixbuf_get_from_surface(surf, 0, 0, w, h)

    # -- souris
    def new_shape(self, x, y):
        ed = self.ed
        return {"kind": ed.tool, "color": ed.color.get_rgba(),
                "size": int(ed.size.get_value()), "pts": [(x, y)]}

    def grab_at(self, x, y):
        """Renvoie (annotation, indice du point saisi ou None pour tout déplacer)."""
        for s in reversed(self.shapes):
            if s["kind"] in BRACES:
                for i in (0, -1):
                    px, py = s["pts"][i]
                    if math.hypot(x - px, y - py) <= 8:
                        return s, i
                poly = s.get("poly", [])
                for (ax, ay), (bx, by) in zip(poly, poly[1:]):
                    dx, dy = bx - ax, by - ay
                    t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
                    if math.hypot(x - ax - t * dx, y - ay - t * dy) <= 6 + s["size"] / 2:
                        return s, None
        t = self.text_at(x, y)
        return (t, None) if t else (None, None)

    def shape_at(self, x, y, precise=False):
        """Annotation sous le curseur : poignée de la sélection d'abord, puis le reste.
        precise : seul le trait compte (outils de dessin, pour pouvoir dessiner à l'intérieur)."""
        if self.sel in self.shapes:
            for hx, hy, hid in sel_handles(self.sel):
                if abs(x - hx) <= 6 and abs(y - hy) <= 6:
                    return self.sel, hid
        if precise:
            for s in reversed(self.shapes):
                if hit_stroke(s, x, y):
                    return s, None
            return None, None
        g, idx = self.grab_at(x, y)
        if g:
            return g, None
        for s in reversed(self.shapes):
            if s["kind"] in ENDPOINTS:
                (ax, ay), (bx, by) = s["pts"][0], s["pts"][-1]
                dx, dy = bx - ax, by - ay
                t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
                if math.hypot(x - ax - t * dx, y - ay - t * dy) <= 6 + s["size"]:
                    return s, None
                continue
            x0, y0, x1, y1 = shape_bounds(s)
            if x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4:
                return s, None
        return None, None

    def delete_selected(self):
        if self.sel in self.shapes:
            self.checkpoint()
            self.shapes.remove(self.sel)
            self.sel = None
            self.changed()

    def text_at(self, x, y):
        for s in reversed(self.shapes):
            if s["kind"] == "text" and "bbox" in s:
                bx, by, bw, bh = s["bbox"]
                if bx - 6 <= x <= bx + bw + 6 and by - 6 <= y <= by + bh + 6:
                    return s
        return None

    def on_press(self, w, e):
        if e.button != 1:
            return
        ex, ey = e.x - self.ox, e.y - self.oy
        t = self.text_at(ex, ey)
        if not t and e.type == Gdk.EventType._2BUTTON_PRESS:
            t = next((s for s in reversed(self.shapes)
                      if s["kind"] == "callout" and hit_stroke(s, ex, ey)), None)
        if t and e.type == Gdk.EventType._2BUTTON_PRESS:
            # double-clic : modifier le texte
            self.drag = None
            r = self.ed.ask_text(t["text"], t["color"], t["size"])
            if r:
                self.checkpoint()
                t["text"], t["color"], t["size"] = r
                self.changed()
            return
        # clic sur un élément existant (ou une poignée) : sélection, déplacement, redimensionnement
        g, hid = self.shape_at(ex, ey, precise=self.ed.tool != "select")
        self.sel = g
        self.clicked = bool(g)      # sélection faite par un clic (pas l'ajout automatique)
        if g:
            self.ed.show_style(g)   # la barre affiche la couleur / l'épaisseur de l'élément
        self.da.queue_draw()
        if g:
            self.drag = {"shape": g, "hid": hid, "px": ex, "py": ey, "orig": list(g["pts"]),
                         "snap": self.snapshot(), "moved": False,
                         "box": sel_box(g), "size": g["size"]}
            return
        if e.type != Gdk.EventType.BUTTON_PRESS:
            return
        tool = self.ed.tool
        if tool == "text":
            r = self.ed.ask_text("", self.ed.color.get_rgba(), int(self.ed.size.get_value()))
            if r:
                s = self.new_shape(ex, ey)
                s["text"], s["color"], s["size"] = r
                self.push(s)
            return
        if tool == "select":
            return
        if tool == "number":
            s = self.new_shape(ex, ey)
            s["n"] = 1 + sum(1 for t in self.shapes if t["kind"] == "number")
            self.push(s); return
        self.cur = self.new_shape(ex, ey)

    def on_motion(self, w, e):
        ex, ey = e.x - self.ox, e.y - self.oy
        if self.drag:
            d = self.drag
            if not d["moved"]:
                d["moved"] = True
                self.history.append(d["snap"]); self.future.clear()
            g, hid, orig = d["shape"], d["hid"], d["orig"]
            dx, dy = ex - d["px"], ey - d["py"]
            if hid is None:                       # déplacer
                g["pts"] = [(x + dx, y + dy) for x, y in orig]
            elif isinstance(hid, int):            # déplacer une extrémité
                pts = list(orig); x, y = pts[hid]; pts[hid] = (x + dx, y + dy)
                g["pts"] = pts
            else:                                 # redimensionner par le cadre
                hx, hy = hid
                ox0, oy0, ox1, oy1 = d["box"]
                nx0 = ox0 + dx if hx == 0 else ox0
                nx1 = ox1 + dx if hx == 1 else ox1
                ny0 = oy0 + dy if hy == 0 else oy0
                ny1 = oy1 + dy if hy == 1 else oy1
                if g["kind"] in ("text", "number"):
                    # texte / numéro : on agrandit la police en gardant le coin opposé fixe
                    oh = max(1, oy1 - oy0)
                    ratio = max(0.2, (ny1 - ny0) / oh)
                    if g["kind"] == "text":
                        fs = (10 + d["size"] * 3) * ratio
                        g["size"] = max(0.5, (fs - 10) / 3)
                        ax = ox1 if hx == 0 else ox0
                        ay = oy1 if hy == 0 else oy0
                        x, y = orig[0]
                        g["pts"] = [(ax + (x - ax) * ratio, ay + (y - ay) * ratio)]
                    else:
                        r = (9 + d["size"] * 2) * ratio
                        g["size"] = max(0.5, (r - 9) / 2)
                else:
                    sx = (nx1 - nx0) / (ox1 - ox0) if ox1 != ox0 else 1
                    sy = (ny1 - ny0) / (oy1 - oy0) if oy1 != oy0 else 1
                    g["pts"] = [(nx0 + (x - ox0) * sx, ny0 + (y - oy0) * sy) for x, y in orig]
                    if g["kind"] == "callout" and len(orig) > 2:
                        g["pts"][2] = orig[2]   # la pointe reste où elle est
            self.changed(); return
        if not self.cur:
            # curseur adapté : déplacer sur un élément, croix sur une poignée
            g, hid = self.shape_at(ex, ey, precise=self.ed.tool != "select")
            name = "default" if not g else ("move" if hid is None else "crosshair")
            self.da.get_window().set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name))
            return
        if not (e.state & Gdk.ModifierType.BUTTON1_MASK):
            return
        if self.cur["kind"] in ("pen", "marker"):
            self.cur["pts"].append((ex, ey))
        else:
            self.cur["pts"][1:] = [(ex, ey)]
        self.da.queue_draw()

    def on_release(self, w, e):
        self.drag = None
        if self.cur and self.cur["kind"] == "callout":
            b = self.cur; self.cur = None
            (ax, ay) = b["pts"][0]
            bx, by = b["pts"][-1] if len(b["pts"]) > 1 else (ax, ay)
            if abs(bx - ax) < 30 or abs(by - ay) < 20:     # simple clic : taille par défaut
                bx, by = ax + 260, ay + 90
            x0, y0, x1, y1 = min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
            b["pts"] = [(x0, y0), (x1, y1), (x0 + (x1 - x0) * 0.35, y1 + max(50, (y1 - y0) * 0.8))]
            self.da.queue_draw()
            r = self.ed.ask_text("", b["color"], b["size"])
            if r:
                b["text"], b["color"], b["size"] = r
                self.push(b)
            self.da.queue_draw()
            return
        if self.cur and len(self.cur["pts"]) > 1:
            self.push(self.cur)
        self.cur = None
        self.da.queue_draw()

    def snapshot(self):
        # l'image fait partie de l'historique (la rotation la modifie)
        return self.base, [dict(sh, pts=list(sh["pts"])) for sh in self.shapes]

    def restore(self, state):
        self.base, self.shapes = state
        self.sel = None; self.drag = None
        self.da.set_size_request(self.base.get_width() + 2 * MARGIN, self.base.get_height() + 2 * MARGIN)
        self.ed.update_title(self)
        self.changed()

    def rotate(self, clockwise):
        """Tourne l'image d'un quart de tour, annotations comprises."""
        self.checkpoint()
        w, h = self.base.get_width(), self.base.get_height()
        if clockwise:
            self.base = self.base.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
            f = lambda x, y: (h - y, x)
        else:
            self.base = self.base.rotate_simple(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)
            f = lambda x, y: (y, w - x)
        for sh in self.shapes:
            sh["pts"] = [f(x, y) for x, y in sh["pts"]]
        self.restore((self.base, self.shapes))

    def checkpoint(self):
        """À appeler juste avant toute modification, pour pouvoir l'annuler."""
        self.history.append(self.snapshot())
        self.future.clear()
        self.style_key = None

    def restyle(self, what, value):
        """Change la couleur ou l'épaisseur de l'élément sélectionné."""
        if self.sel not in self.shapes or not getattr(self, "clicked", False):
            return   # élément juste dessiné : le réglage vaut pour les prochains éléments
        # clics répétés sur +/- : une seule étape d'annulation
        key = (id(self.sel), what)
        if getattr(self, "style_key", None) != key:
            self.checkpoint()
            self.style_key = key
        self.sel[what] = value
        self.changed()

    def push(self, s):
        self.checkpoint()
        self.shapes.append(s)
        self.sel = s          # le nouvel élément est sélectionné : poignées visibles
        self.clicked = False
        self.changed()

    def undo(self):
        if self.history:
            self.future.append(self.snapshot())
            self.restore(self.history.pop())

    def do_redo(self):
        if self.future:
            self.history.append(self.snapshot())
            self.restore(self.future.pop())


class Editor(Gtk.Window):
    """Fenêtre principale : barre d'outils partagée + un onglet par capture."""
    def __init__(self, app):
        super().__init__(title="Capture", application=app)
        self.app = app
        self.tool = "arrow"
        self.count = 0

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        # barre du haut : actions
        self.hb = Gtk.HeaderBar(show_close_button=True, title="Capture")
        self.set_titlebar(self.hb)
        for icon, tip, cb in [("camera-photo-symbolic", "Nouvelle capture (Ctrl+N)", self.new_capture),
                              ("document-open-symbolic", "Ouvrir une image (Ctrl+O)", self.open_files),
                              ("document-save-symbolic", "Enregistrer (Ctrl+S)", self.save),
                              ("edit-copy-symbolic", "Copier (Ctrl+C)", self.copy),
                              ("edit-undo-symbolic", "Annuler (Ctrl+Z)", self.undo),
                              ("edit-redo-symbolic", "Rétablir (Ctrl+Y)", self.do_redo),
                              ("view-pin-symbolic", "Épingler au-dessus", self.pin),
                              ("object-rotate-right-symbolic", "Pivoter à droite (Ctrl+R)",
                               lambda: self.rotate(True)),
                              ("object-rotate-left-symbolic", "Pivoter à gauche (Ctrl+Maj+R)",
                               lambda: self.rotate(False))]:
            b = Gtk.Button(label=tip.split(" (")[0].replace(" au-dessus", ""))
            b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            b.set_always_show_image(True)
            b.set_tooltip_text(tip); b.connect("clicked", lambda *_, f=cb: f())
            if icon.startswith(("view-pin", "object-rotate")):
                self.hb.pack_end(b)
            else:
                self.hb.pack_start(b)

        # barre d'outils : annotations
        tb = Gtk.Box(spacing=2, margin=4)
        group = None
        for key, name, icon in TOOLS:
            rb = Gtk.RadioButton.new_from_widget(group)
            group = group or rb
            rb.set_mode(False)
            if len(icon) == 1:   # symbole texte, ex. « { »
                img = Gtk.Label(); img.set_markup(f"<span size='large' weight='bold'>{icon}</span>")
            else:
                img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            rb.set_image(img)
            rb.set_label(name)
            rb.set_always_show_image(True)
            rb.set_image_position(Gtk.PositionType.TOP)
            rb.set_tooltip_text(f"{name} {icon}" if len(icon) == 1 else name)
            rb.set_active(key == self.tool)
            rb.connect("toggled", lambda b, k=key: b.get_active() and self.set_tool(k))
            tb.pack_start(rb, False, False, 0)
        tb.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6)
        self.color = Gtk.ColorButton(rgba=Gdk.RGBA(0.9, 0.1, 0.1, 1))
        self.color.set_tooltip_text("Couleur")
        tb.pack_start(Gtk.Label(label="Couleur"), False, False, 4)
        tb.pack_start(self.color, False, False, 0)
        tb.pack_start(Gtk.Label(label="Épaisseur"), False, False, 6)
        self.size = Gtk.SpinButton.new_with_range(1, 20, 1)
        self.size.set_value(10); self.size.set_tooltip_text("Épaisseur / taille")
        tb.pack_start(self.size, False, False, 0)
        # modifier couleur / épaisseur agit aussi sur l'élément sélectionné
        self.syncing = False
        self.color.connect("color-set", lambda b: self.restyle("color", b.get_rgba()))
        self.size.connect("value-changed", lambda b: self.restyle("size", b.get_value_as_int()))
        box.pack_start(tb, False, False, 0)

        # onglets : historique des captures de la session
        self.nb = Gtk.Notebook(scrollable=True)
        self.nb.connect("switch-page", lambda nb, page, i: self.update_title(page))
        box.pack_start(self.nb, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        # glisser-déposer des images depuis le gestionnaire de fichiers
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", lambda w, ctx, x, y, data, info, t:
                     self.app.open_paths([GLib.filename_from_uri(u)[0] for u in data.get_uris()
                                          if u.startswith("file://")]))
        box.show_all()
        self.hb.show_all()   # la barre de titre n'est pas un enfant de box

    def show_style(self, shape):
        self.syncing = True
        self.color.set_rgba(shape["color"])
        self.size.set_value(round(shape["size"]))
        self.syncing = False

    def restyle(self, what, value):
        c = self.current()
        if c and not self.syncing:
            c.restyle(what, value)

    def set_tool(self, k):
        self.tool = k
        c = self.current()
        c and c.da.queue_draw()

    # -- onglets
    def current(self):
        i = self.nb.get_current_page()
        return self.nb.get_nth_page(i) if i >= 0 else None

    def update_title(self, c):
        if c is not None:
            self.hb.set_subtitle(f"{c.base.get_width()} × {c.base.get_height()}")

    def add_capture(self, pix, path=None):
        first = self.nb.get_n_pages() == 0
        if path:   # image ouverte depuis un fichier : l'onglet porte son nom
            c = Canvas(self, pix, os.path.basename(path))
            c.path, c.dirty = path, False
            c.update_label()
        else:
            self.count += 1
            c = Canvas(self, pix, f"Capture {self.count}")
        c.show_all()
        i = self.nb.append_page(c, c.tab)
        self.nb.set_tab_reorderable(c, True)
        self.nb.set_current_page(i)
        self.update_title(c)
        if first:
            scr = Gdk.Screen.get_default()
            self.set_default_size(min(pix.get_width() + 50, int(scr.get_width() * .9)),
                                  min(pix.get_height() + 170, int(scr.get_height() * .9)))

    def confirm_discard(self, n):
        msg = ("Cette capture contient des annotations non enregistrées." if n == 1 else
               f"{n} captures contiennent des annotations non enregistrées.")
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=msg)
        d.format_secondary_text("Fermer quand même ?")
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Fermer sans enregistrer", Gtk.ResponseType.OK)
        r = d.run(); d.destroy()
        return r == Gtk.ResponseType.OK

    def close_tab(self, c):
        if c.dirty and c.shapes and not self.confirm_discard(1):
            return
        self.nb.remove_page(self.nb.page_num(c))
        if self.nb.get_n_pages() == 0:
            self.destroy()

    def on_delete(self, *_):
        n = sum(1 for c in self.nb.get_children() if c.dirty and c.shapes)
        return bool(n) and not self.confirm_discard(n)

    def ask_text(self, initial, color, size):
        """Saisie du texte avec sa couleur et sa taille. Renvoie (texte, couleur, taille) ou None."""
        d = Gtk.Dialog(title="Texte", transient_for=self, modal=True)
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        area = d.get_content_area()
        area.set_spacing(8); area.set_margin_start(8); area.set_margin_end(8); area.set_margin_top(8)

        # couleurs rapides + choix libre + taille
        row = Gtk.Box(spacing=4)
        cbtn = Gtk.ColorButton(rgba=color)
        cbtn.set_tooltip_text("Autre couleur")
        for hexa in ("#e01b24", "#000000", "#ffffff", "#1c71d8", "#2ec27e", "#f6d32d", "#ff7800"):
            rgba = Gdk.RGBA(); rgba.parse(hexa)
            b = Gtk.Button()
            sw = Gtk.DrawingArea(); sw.set_size_request(18, 18)
            sw.connect("draw", lambda w, cr, c=rgba: (cr.set_source_rgba(c.red, c.green, c.blue, 1),
                                                       cr.paint(), cr.set_source_rgb(.5, .5, .5),
                                                       cr.rectangle(.5, .5, w.get_allocated_width() - 1,
                                                                    w.get_allocated_height() - 1),
                                                       cr.stroke()))
            b.add(sw)
            b.connect("clicked", lambda _b, c=rgba: cbtn.set_rgba(c))
            row.pack_start(b, False, False, 0)
        row.pack_start(cbtn, False, False, 4)
        row.pack_start(Gtk.Label(label="Taille"), False, False, 4)
        spin = Gtk.SpinButton.new_with_range(1, 20, 1); spin.set_value(size)
        row.pack_start(spin, False, False, 0)
        area.pack_start(row, False, False, 0)

        tv = Gtk.TextView(); tv.set_size_request(380, 90)
        tv.set_left_margin(6); tv.set_top_margin(6)
        buf = tv.get_buffer(); buf.set_text(initial)
        area.pack_start(tv, True, True, 0)
        d.show_all()
        tv.grab_focus()
        r = d.run()
        txt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        res = (txt, cbtn.get_rgba(), int(spin.get_value()))
        d.destroy()
        return res if r == Gtk.ResponseType.OK and txt.strip() else None

    # -- actions (sur l'onglet courant)
    def undo(self):
        c = self.current()
        c and c.undo()

    def do_redo(self):
        c = self.current()
        c and c.do_redo()

    def copy(self):
        c = self.current()
        if c:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_image(c.final_pixbuf()); cb.store()

    def save(self):
        c = self.current()
        if not c:
            return
        d = Gtk.FileChooserDialog(title="Enregistrer", transient_for=self,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Enregistrer", Gtk.ResponseType.OK)
        d.set_do_overwrite_confirmation(True)
        if c.path:
            d.set_filename(c.path)
        else:
            d.set_current_folder(default_dir())
            d.set_current_name(default_name())
        if d.run() == Gtk.ResponseType.OK:
            path = d.get_filename()
            save_pixbuf(c.final_pixbuf(), path)
            c.path, c.title, c.dirty = path, os.path.basename(path), False
            c.update_label()
        d.destroy()

    def pin(self):
        self._pinned = not getattr(self, "_pinned", False)
        self.set_keep_above(self._pinned)

    def rotate(self, clockwise):
        c = self.current()
        c and c.rotate(clockwise)

    def open_files(self):
        self.app.open_paths(choose_images(self))

    def new_capture(self):
        self.app.capture("r")

    def on_key(self, w, e):
        ctrl = e.state & Gdk.ModifierType.CONTROL_MASK
        k = Gdk.keyval_to_lower(e.keyval)
        acts = {Gdk.KEY_s: self.save, Gdk.KEY_c: self.copy, Gdk.KEY_z: self.undo,
                Gdk.KEY_y: self.do_redo, Gdk.KEY_n: self.new_capture, Gdk.KEY_o: self.open_files,
                Gdk.KEY_w: lambda: self.current() and self.close_tab(self.current())}
        if ctrl and k == Gdk.KEY_r:
            self.rotate(not e.state & Gdk.ModifierType.SHIFT_MASK); return True
        if ctrl and k in acts:
            acts[k](); return True
        c = self.current()
        if isinstance(self.get_focus(), Gtk.Entry):   # saisie en cours (ex. épaisseur)
            return False
        if c and c.sel in c.shapes and e.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            c.delete_selected(); return True
        if c and e.keyval == Gdk.KEY_Escape:
            c.sel = None; c.da.queue_draw(); return True

# ---------------------------------------------------------------- utilitaires

def default_dir():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~")
    return d

def default_name():
    return datetime.datetime.now().strftime("Capture_%Y-%m-%d_%H-%M-%S.png")

def choose_images(parent):
    """Sélecteur de fichiers image (plusieurs à la fois). Renvoie une liste de chemins."""
    d = Gtk.FileChooserDialog(title="Ouvrir des images", transient_for=parent,
                              action=Gtk.FileChooserAction.OPEN)
    d.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Ouvrir", Gtk.ResponseType.OK)
    d.set_select_multiple(True)
    d.set_current_folder(default_dir())
    f = Gtk.FileFilter(); f.set_name("Images"); f.add_pixbuf_formats()
    d.add_filter(f)
    paths = d.get_filenames() if d.run() == Gtk.ResponseType.OK else []
    d.destroy()
    return paths


def load_image(path):
    pix = GdkPixbuf.Pixbuf.new_from_file(path)
    return pix.apply_embedded_orientation() or pix


def save_pixbuf(pix, path):
    ext = os.path.splitext(path)[1].lower()
    fmt = {".jpg": "jpeg", ".jpeg": "jpeg", ".bmp": "bmp"}.get(ext, "png")
    if fmt != "png" and pix.get_has_alpha():
        pix = pix.composite_color_simple(pix.get_width(), pix.get_height(),
                                         GdkPixbuf.InterpType.NEAREST, 255, 8, 0xffffff, 0xffffff)
    pix.savev(path, fmt, [], [])

# ---------------------------------------------------------------- application

def make_parser():
    p = argparse.ArgumentParser(prog="capture-ecran", description="Capture d'écran légère")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-r", "--rect", dest="mode", action="store_const", const="r", help="zone")
    g.add_argument("-f", "--full", dest="mode", action="store_const", const="f", help="plein écran")
    g.add_argument("-a", "--active", dest="mode", action="store_const", const="a", help="fenêtre active")
    p.add_argument("-d", "--delay", type=int, default=0, help="délai en secondes")
    p.add_argument("-o", "--output", help="enregistrer directement dans ce fichier")
    p.add_argument("files", nargs="*", help="images à ouvrir dans l'éditeur")
    return p


class App(Gtk.Application):
    """Une seule instance : relancer l'application ajoute un onglet à la fenêtre existante."""
    def __init__(self):
        super().__init__(application_id="io.github.capture_ecran",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.editor = None
        self.output = None
        self.delay = 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        # thème clair forcé, même si le bureau est en mode sombre
        st = Gtk.Settings.get_default()
        st.props.gtk_application_prefer_dark_theme = False
        name = st.props.gtk_theme_name or "Adwaita"
        if "-dark" in name.lower():
            st.props.gtk_theme_name = name.replace("-dark", "").replace("-Dark", "")
        # bordure visible autour des fenêtres (gauche, droite, bas)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            decoration { border: 1px solid #8a8a8a; border-radius: 8px 8px 0 0; }
            window:backdrop decoration { border-color: #b0b0b0; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, cl):
        try:
            args = make_parser().parse_args(cl.get_arguments()[1:])
        except SystemExit as e:
            return e.code or 0
        self.delay = args.delay
        self.output = os.path.join(cl.get_cwd() or "", args.output) if args.output else None
        if args.files:
            cwd = cl.get_cwd() or ""
            self.open_paths([f if f.startswith("/") else os.path.join(cwd, f) for f in
                             (GLib.filename_from_uri(u)[0] if u.startswith("file://") else u
                              for u in args.files)])
        else:
            # lancement normal : on passe directement à la sélection de zone
            self.capture(args.mode or "r", args.delay)
        return 0

    def capture(self, mode="r", delay=0):
        self.hold()   # l'application reste active pendant que la fenêtre est cachée
        # notre fenêtre ne doit pas cacher l'écran
        if self.editor:
            self.editor.hide()
        # petit délai minimum pour que les fenêtres disparaissent de l'écran
        GLib.timeout_add(max(250, delay * 1000), self._do_capture, mode)

    def _do_capture(self, mode):
        if mode == "r":
            RegionSelector(grab(), self.done)
        else:
            self.done(grab_active() if mode == "a" else grab())
        return False

    def ensure_editor(self):
        if self.editor is None:
            self.editor = Editor(self)
            self.editor.connect("destroy", lambda *_: setattr(self, "editor", None))
        return self.editor

    def open_paths(self, paths):
        bad = []
        for path in paths:
            try:
                pix = load_image(path)
            except GLib.Error:
                bad.append(os.path.basename(path)); continue
            self.ensure_editor().add_capture(pix, path)
        if self.editor:
            self.editor.show(); self.editor.present()
        if bad:
            d = Gtk.MessageDialog(transient_for=self.editor, modal=True,
                                  message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK,
                                  text="Impossible d'ouvrir : " + ", ".join(bad))
            d.run(); d.destroy()

    def done(self, pix):
        if pix is None:
            # capture annulée : on réaffiche ce qui était ouvert
            if self.editor:
                self.editor.present()
        elif self.output:
            save_pixbuf(pix, self.output)
            print(self.output)
            self.output = None
        else:
            self.ensure_editor().add_capture(pix)
            self.editor.show()
            self.editor.present()
        self.release()


def main():
    import sys
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
