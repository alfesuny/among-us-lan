"""Small immediate-ish UI toolkit: text, buttons, inputs, steppers, chat."""
import math
import random
from collections import OrderedDict

import pygame as pg

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (230, 40, 40)
GREEN = (60, 220, 90)
YELLOW = (250, 220, 60)
GREY = (150, 150, 160)
DARK = (22, 24, 34)
PANEL = (36, 40, 56)
PANEL_LIGHT = (58, 64, 88)
ACCENT = (80, 170, 255)
CYAN = (120, 230, 255)

_text_cache = OrderedDict()


def render_text(assets, text, size, colour=WHITE, outline=BLACK, width=2):
    key = (text, size, colour, outline, width)
    surf = _text_cache.get(key)
    if surf is not None:
        _text_cache.move_to_end(key)
        return surf
    font = assets.font(size)
    base = font.render(text, True, colour)
    if outline is None:
        surf = base
    else:
        w, h = base.get_size()
        surf = pg.Surface((w + 2 * width, h + 2 * width), pg.SRCALPHA)
        o = font.render(text, True, outline)
        for dx in range(-width, width + 1):
            for dy in range(-width, width + 1):
                if dx * dx + dy * dy <= width * width + 1:
                    surf.blit(o, (dx + width, dy + width))
        surf.blit(base, (width, width))
    _text_cache[key] = surf
    if len(_text_cache) > 600:
        _text_cache.popitem(last=False)
    return surf


def draw_text(surf, assets, text, size, pos, colour=WHITE, anchor="topleft", outline=BLACK, width=2):
    img = render_text(assets, str(text), size, colour, outline, width)
    r = img.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
    surf.blit(img, r)
    return r


def wrap(assets, text, size, max_w):
    font = assets.font(size)
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.size(trial)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:  # hard-split words longer than the line
        while font.size(ln)[0] > max_w and len(ln) > 1:
            cut = len(ln)
            while cut > 1 and font.size(ln[:cut])[0] > max_w:
                cut -= 1
            out.append(ln[:cut])
            ln = ln[cut:]
        out.append(ln)
    return out


def panel(surf, rect, colour=PANEL, border=(10, 10, 14), radius=14, width=4, alpha=None):
    rect = pg.Rect(rect)
    if alpha is not None:
        s = pg.Surface(rect.size, pg.SRCALPHA)
        pg.draw.rect(s, (*colour, alpha), s.get_rect(), border_radius=radius)
        surf.blit(s, rect)
    else:
        pg.draw.rect(surf, colour, rect, border_radius=radius)
    if width:
        pg.draw.rect(surf, border, rect, width, border_radius=radius)


class Widget:
    enabled = True
    visible = True

    def handle(self, e):
        return False

    def update(self, dt):
        pass

    def draw(self, surf, assets):
        pass


class Button(Widget):
    def __init__(self, rect, label, on_click=None, size=26, colour=PANEL_LIGHT, text_colour=WHITE,
                 hotkey=None, icon=None, enabled=True, sound="click"):
        self.rect = pg.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.size = size
        self.colour = colour
        self.text_colour = text_colour
        self.hotkey = hotkey
        self.icon = icon
        self.enabled = enabled
        self.hover = False
        self.sound = sound
        self.assets = None

    def handle(self, e):
        if not self.visible:
            return False
        if e.type == pg.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
        elif e.type == pg.MOUSEBUTTONDOWN and e.button == 1 and self.rect.collidepoint(e.pos):
            self.click()
            return True
        elif e.type == pg.KEYDOWN and self.hotkey is not None and e.key in (
                self.hotkey if isinstance(self.hotkey, (tuple, list)) else (self.hotkey,)):
            self.click()
            return True
        return False

    def click(self):
        if not self.enabled:
            return
        if self.assets and self.sound:
            self.assets.play(self.sound, 0.6)
        if self.on_click:
            self.on_click()

    def draw(self, surf, assets):
        if not self.visible:
            return
        self.assets = assets
        if self.icon is not None:
            img = self.icon
            if not self.enabled:
                img = img.copy()
                img.set_alpha(110)
            surf.blit(img, img.get_rect(center=self.rect.center))
            if self.label:
                draw_text(surf, assets, self.label, self.size, (self.rect.centerx, self.rect.bottom - 4),
                          WHITE if self.enabled else GREY, anchor="midbottom")
            return
        col = self.colour
        if not self.enabled:
            col = tuple(int(c * 0.5) for c in col)
        elif self.hover:
            col = tuple(min(255, int(c * 1.25) + 12) for c in col)
        panel(surf, self.rect, col, radius=10, width=3)
        draw_text(surf, assets, self.label, self.size, self.rect.center,
                  self.text_colour if self.enabled else GREY, anchor="center")


class TextInput(Widget):
    def __init__(self, rect, text="", placeholder="", max_len=20, on_submit=None, size=26, allowed=None,
                 focused=False, on_change=None):
        self.rect = pg.Rect(rect)
        self.text = text
        self.placeholder = placeholder
        self.max_len = max_len
        self.on_submit = on_submit
        self.on_change = on_change
        self.size = size
        self.allowed = allowed
        self.focused = focused
        self.blink = 0.0
        self.assets = None

    def handle(self, e):
        if not self.visible:
            return False
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            self.focused = self.rect.collidepoint(e.pos)
            return self.focused
        if not self.focused:
            return False
        if e.type == pg.TEXTINPUT:
            added = False
            for ch in e.text:
                if len(self.text) >= self.max_len:
                    break
                if ch.isprintable() and (self.allowed is None or ch in self.allowed):
                    self.text += ch
                    added = True
            if added:
                if self.assets:
                    self.assets.play("key", 0.4)
                if self.on_change:
                    self.on_change(self.text)
            return True
        if e.type == pg.KEYDOWN:
            if e.key == pg.K_BACKSPACE:
                if e.mod & pg.KMOD_CTRL:
                    self.text = ""
                else:
                    self.text = self.text[:-1]
                if self.on_change:
                    self.on_change(self.text)
                return True
            if e.key in (pg.K_RETURN, pg.K_KP_ENTER):
                if self.on_submit:
                    self.on_submit(self.text)
                return True
            if e.key == pg.K_v and e.mod & pg.KMOD_CTRL:
                try:
                    pasted = pg.scrap.get_text() if hasattr(pg.scrap, "get_text") else ""
                except Exception:
                    pasted = ""
                for ch in pasted or "":
                    if len(self.text) < self.max_len and ch.isprintable() and (self.allowed is None or ch in self.allowed):
                        self.text += ch
                return True
            if e.key == pg.K_ESCAPE:
                self.focused = False
                return True
            # swallow other keys so typing never triggers game hotkeys
            return e.key not in (pg.K_TAB,)
        return False

    def update(self, dt):
        self.blink = (self.blink + dt) % 1.0

    def draw(self, surf, assets):
        if not self.visible:
            return
        self.assets = assets
        panel(surf, self.rect, (245, 245, 250) if self.focused else (215, 218, 228), border=(20, 20, 30),
              radius=8, width=3)
        font = assets.font(self.size)
        shown = self.text or self.placeholder
        col = (20, 20, 30) if self.text else (130, 130, 140)
        img = font.render(shown, True, col)
        clip = surf.get_clip()
        inner = self.rect.inflate(-16, -6)
        surf.set_clip(inner)
        x = inner.x
        if img.get_width() > inner.w:
            x = inner.right - img.get_width()
        surf.blit(img, (x, inner.centery - img.get_height() // 2))
        if self.focused and self.blink < 0.5:
            cx = x + (font.size(self.text)[0] if self.text else 0) + 2
            pg.draw.line(surf, (20, 20, 30), (cx, inner.y + 4), (cx, inner.bottom - 4), 2)
        surf.set_clip(clip)


class Stepper(Widget):
    """label  [-] value [+]"""

    def __init__(self, rect, label, value, lo, hi, step, on_change, fmt="{}", enabled=True, size=20):
        self.rect = pg.Rect(rect)
        self.label = label
        self.value = value
        self.lo, self.hi, self.step = lo, hi, step
        self.on_change = on_change
        self.fmt = fmt
        self.enabled = enabled
        self.size = size
        h = self.rect.h
        self.minus = pg.Rect(self.rect.right - 3 * h - 20, self.rect.y, h, h)
        self.plus = pg.Rect(self.rect.right - h, self.rect.y, h, h)

    def handle(self, e):
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1 and self.enabled:
            if self.minus.collidepoint(e.pos):
                self._set(self.value - self.step)
                return True
            if self.plus.collidepoint(e.pos):
                self._set(self.value + self.step)
                return True
        return False

    def _set(self, v):
        v = max(self.lo, min(self.hi, round(v, 2)))
        if v != self.value:
            self.value = v
            self.on_change(v)

    def draw(self, surf, assets):
        draw_text(surf, assets, self.label, self.size, (self.rect.x, self.rect.centery), WHITE, anchor="midleft")
        mid = (self.minus.right + self.plus.left) // 2
        draw_text(surf, assets, self.fmt.format(self.value), self.size, (mid, self.rect.centery), YELLOW,
                  anchor="center")
        if self.enabled:
            for r, t in ((self.minus, "-"), (self.plus, "+")):
                panel(surf, r, PANEL_LIGHT, radius=6, width=2)
                draw_text(surf, assets, t, self.size, r.center, WHITE, anchor="center")


class Toggle(Widget):
    def __init__(self, rect, label, value, on_change, enabled=True, size=20):
        self.rect = pg.Rect(rect)
        self.label = label
        self.value = value
        self.on_change = on_change
        self.enabled = enabled
        self.size = size
        self.box = pg.Rect(self.rect.right - self.rect.h, self.rect.y, self.rect.h, self.rect.h)

    def handle(self, e):
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1 and self.enabled and self.box.collidepoint(e.pos):
            self.value = not self.value
            self.on_change(self.value)
            return True
        return False

    def draw(self, surf, assets):
        draw_text(surf, assets, self.label, self.size, (self.rect.x, self.rect.centery), WHITE, anchor="midleft")
        panel(surf, self.box, PANEL_LIGHT if self.enabled else PANEL, radius=6, width=2)
        if self.value:
            b = self.box.inflate(-10, -10)
            pg.draw.lines(surf, GREEN, False, [(b.x, b.centery), (b.centerx - 2, b.bottom), (b.right, b.y)], 4)


class ChatBox(Widget):
    def __init__(self, rect, on_send, size=18, input_h=36):
        self.rect = pg.Rect(rect)
        self.size = size
        self.lines = []  # (name, colour_name_rgb, text, dead)
        self.input = TextInput((self.rect.x, self.rect.bottom - input_h, self.rect.w, input_h), "",
                               "Type here (Enter to send)", 100, self._submit, size=size)
        self.on_send = on_send
        self.scroll = 0

    def _submit(self, text):
        text = text.strip()
        if text:
            self.on_send(text)
        self.input.text = ""

    def add(self, name, rgb, text, dead=False):
        self.lines.append((name, rgb, text, dead))
        self.lines = self.lines[-80:]
        self.scroll = 0

    def handle(self, e):
        if e.type == pg.MOUSEWHEEL and self.rect.collidepoint(pg.mouse.get_pos()):
            self.scroll = max(0, self.scroll + e.y)
            return True
        return self.input.handle(e)

    def update(self, dt):
        self.input.update(dt)

    def draw(self, surf, assets):
        area = pg.Rect(self.rect.x, self.rect.y, self.rect.w, self.rect.h - self.input.rect.h - 6)
        panel(surf, area, (230, 232, 240), border=(20, 20, 30), radius=8, width=3)
        inner = area.inflate(-14, -10)
        rows = []
        for name, rgb, text, dead in self.lines:
            prefix = f"{name}: "
            body = wrap(assets, prefix + text, self.size, inner.w)
            for i, ln in enumerate(body):
                rows.append((ln, rgb if i == 0 else None, len(prefix) if i == 0 else 0, dead))
        lh = assets.font(self.size).get_linesize()
        fit = max(1, inner.h // lh)
        self.scroll = min(self.scroll, max(0, len(rows) - fit))
        start = max(0, len(rows) - fit - self.scroll)
        shown = rows[start:start + fit]
        clip = surf.get_clip()
        surf.set_clip(inner)
        font = assets.font(self.size)
        y = inner.y
        for ln, rgb, plen, dead in shown:
            x = inner.x
            if rgb is not None and plen:
                name_img = font.render(ln[:plen], True, tuple(int(c * 0.75) for c in rgb))
                surf.blit(name_img, (x, y))
                x += name_img.get_width()
                ln = ln[plen:]
            body = font.render(ln, True, (110, 110, 120) if dead else (25, 25, 35))
            surf.blit(body, (x, y))
            y += lh
        surf.set_clip(clip)
        self.input.draw(surf, assets)


class Starfield:
    def __init__(self, w, h, n=160, seed=4):
        rng = random.Random(seed)
        self.w, self.h = w, h
        self.stars = [[rng.uniform(0, w), rng.uniform(0, h), rng.uniform(15, 90), rng.choice((1, 1, 2, 2, 3))]
                      for _ in range(n)]
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        for s in self.stars:
            s[0] -= s[2] * dt
            if s[0] < -4:
                s[0] = self.w + 4

    def draw(self, surf):
        surf.fill((6, 8, 18))
        for x, y, sp, r in self.stars:
            c = 140 + int(115 * (sp / 90))
            pg.draw.circle(surf, (c, c, c), (int(x), int(y)), r)


def pulse(t, speed=4.0, lo=0.4, hi=1.0):
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * speed))
