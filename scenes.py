import math

import pygame

import clipboard
import relay

import device
from device import touch
from anim import Confetti, Flight, approach, clamp, ease_out_cubic, lerp_color
from network import (Client, Server, DEFAULT_PORT, MAX_PLAYERS, MIN_PLAYERS, MAX_NAME,
                     MAX_CODE, format_bytes, parse_address)
from theme import theme
from ui_objects import (Button, Checkbox, Label, Leaderboard, Logo, Panel, Tabs, TextBlock,
                        TextBox, ThemeToggle, COLOR_RGB, dim_surface, draw_card, fit_text, text_surface)
from uno import COLORS, ordinal
from viewport import pointer_pos, view


ADDRESS_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:/"


class Scene:
    """One screen of the game. Owns its UI objects and a background color role."""

    bg_role = "bg"
    toggle_pos = None   # where the light/dark button sits; None = top right corner
    FULL = False        # False: laid out in its own (width x 600) area, centred on tall screens
                        # True: uses the whole canvas and positions everything from its size

    def __init__(self, game):
        self.game = game
        self.size = game.area_size(self.FULL)     # the area this screen is laid out in
        self.objects = []
        self.setup()
        # Added last so it is drawn on top and gets clicks first, on every screen.
        self.add(ThemeToggle(self.toggle_position()))

    def toggle_position(self):
        return self.toggle_pos or (self.size[0] - 56, 12)

    def setup(self):
        """Override: create your UI objects here with self.add(...)."""
        pass

    def add(self, obj):
        self.objects.append(obj)
        return obj

    def background(self):
        return theme[self.bg_role]

    def handle_event(self, event):
        # Reversed so objects drawn on top get events first.
        for obj in reversed(self.objects):
            if obj.enabled:
                obj.handle_event(event)

    def update(self, dt):
        for obj in self.objects:
            if obj.enabled:
                obj.update(dt)

    def draw(self, screen):
        screen.fill(self.background())
        for obj in self.objects:
            if obj.visible:
                obj.draw(screen)


class MenuScene(Scene):
    def setup(self):
        w = self.size[0]
        self.add(Logo((w // 2, 140)))
        self.add(Label((w // 2, 235), "Play UNO with your friends", size=22,
                       color="muted", center=True))
        self.add(Button((w // 2 - 110, 290), (220, 60), "Play", 28, "btn_red",
                        action=self.game.change_scene, args=("mode_select",)))
        self.add(Button((w // 2 - 110, 370), (220, 60), "Quit", 28, "btn_neutral",
                        action=self.game.quit))
        self.touch_btn = self.add(Button((w // 2 - 110, 450), (220, 44), "", 19, "btn_neutral",
                                         action=touch.toggle))
        hint = "F2: light / dark     F3: touch mode" + ("" if device.ANDROID else "     F4: window size")
        self.add(Label((w // 2, 565), hint, size=16,
                       color="muted", center=True))

        # What this screen looks like to the game: handy on a phone, where there is no console.
        self.info = self.add(TextBlock((10, 8), w - 70, "", size=14, color="muted", line_gap=2))
        self.info.visible = False
        self.add(Button((w // 2 - 110, 500), (220, 36), "Screen info", 17, "btn_neutral",
                        action=self._toggle_info))

    def _toggle_info(self):
        self.info.visible = not self.info.visible

    def update(self, dt):
        super().update(dt)
        self.touch_btn.text = "Touch mode: " + ("On" if touch.enabled else "Off")
        if self.info.visible:
            self.info.text = "\n".join(view.describe())


class ModeSelectScene(Scene):
    def setup(self):
        w = self.size[0]
        self.add(Label((w // 2, 80), "Play", size=48, center=True))
        self.add(Button((w // 2 - 120, 160), (240, 70), "Host Game", 28, "btn_green",
                        action=self.game.change_scene, args=("host",)))
        self.add(Label((w // 2, 252), "Start a lobby for your friends", size=19,
                       color="muted", center=True))
        self.add(Button((w // 2 - 120, 300), (240, 70), "Join Game", 28, "btn_blue",
                        action=self.game.change_scene, args=("join",)))
        self.add(Label((w // 2, 392), "Enter the host's address", size=19,
                       color="muted", center=True))
        self.add(Button((w // 2 - 150, 440), (300, 44), "Playing over the internet?", 20,
                        "btn_neutral", action=open_help, args=(self.game, "mode_select")))
        self.add(Button((20, 20), (120, 45), "Back", 22, "btn_neutral",
                        action=self.game.change_scene, args=("menu",)))

        # Shows why we ended up here (e.g. "The lobby was closed."), then forgets it.
        self.message = self.add(TextBlock((w // 2 - 250, 510), 500, self.game.notice, size=20,
                                          color="error", center=True))
        self.game.notice = ""


def data_meter(game):
    """
    The corner readout: ping and data used so far (compressed bytes actually sent/received,
    not counting the ~50 bytes of packet headers every message also costs). When hosting, it
    shows what your connection has sent to / received from your guests, which is the part
    that comes out of your internet quota (your own player's traffic never leaves the PC).
    """
    client, server = game.client, game.server
    if client is None:
        return ""
    if server is not None:
        sent = max(0, server.traffic.sent - client.traffic.received)
        received = max(0, server.traffic.received - client.traffic.sent)
        return f"Sent to guests {format_bytes(sent)}   Received {format_bytes(received)}"
    parts = []
    if client.ping_ms is not None:
        parts.append(f"Ping {client.ping_ms} ms")
    parts.append(f"Data {format_bytes(client.traffic.sent + client.traffic.received)}")
    return "   ".join(parts)


def open_help(game, came_from):
    game.help_from = came_from
    game.change_scene("help")


class HostScene(Scene):
    """Choose a port and an optional lobby code, then open the lobby."""

    def setup(self):
        w = self.size[0]
        x = w // 2 - 150
        self.add(Label((w // 2, 50), "Host Game", size=48, center=True))
        self.add(Panel((w // 2 - 190, 90), (380, 408)))

        self.add(Label((x, 110), "Port", size=20, color="muted"))
        self.port_box = self.add(TextBox((x, 134), (300, 50), text=str(DEFAULT_PORT),
                                         allowed="0123456789", max_length=5,
                                         on_submit=self._focus_code))
        self.add(Label((x, 200), "Code for direct joins (optional)", size=20, color="muted"))
        self.code_box = self.add(TextBox((x, 224), (300, 50), max_length=MAX_CODE,
                                         placeholder="Leave empty for none",
                                         on_submit=self.start))
        self.online_box = self.add(Checkbox((x, 296), 300, "Also open an online room", True))
        self.add(TextBlock((x + 36, 328), 264, "Friends join with a room code, through a free "
                           "public relay. Works behind most home internet.", size=16,
                           color="muted"))
        self.start_btn = self.add(Button((w // 2 - 100, 408), (200, 60), "Open Lobby", 26,
                                         "btn_green", action=self.start))
        self.status = self.add(TextBlock((w // 2 - 190, 508), 380, "", size=18,
                                         color="error", center=True))
        self.add(Button((w // 2 - 130, 545), (260, 40), "How to play online", 20, "btn_neutral",
                        action=open_help, args=(self.game, "host")))
        self.add(Button((20, 20), (120, 45), "Back", 22, "btn_neutral",
                        action=self.game.change_scene, args=("mode_select",)))
        self.port_box.focused = True

    def _focus_code(self):
        self.port_box.focused = False
        self.code_box.focused = True

    def start(self):
        port = int(self.port_box.text) if self.port_box.text else 0
        if not 1 <= port <= 65535:
            self.status.text = "Invalid port."
            return
        try:
            server = Server(port, code=self.code_box.text.strip())
            server.start()
        except OSError:
            self.status.text = f"Could not start a server on port {port}. Is it already in use?"
            return
        if self.online_box.checked:
            server.start_relay()   # in the background; the lobby shows its progress

        # The host plays through a normal client connected to its own server.
        client = Client()
        client.connect("127.0.0.1", server.port, token=server.host_token)
        self.game.server = server
        self.game.client = client
        self.game.change_scene("lobby")


ROOM_CHARS = relay.ALPHABET + relay.ALPHABET.lower() + "-"


class JoinScene(Scene):
    def setup(self):
        w = self.size[0]
        x = w // 2 - 150
        narrow = w < 700        # an upright phone: no room beside the title for two buttons
        self.add(Label((w // 2, 46), "Join Game", size=40 if narrow else 48, center=True))
        self.panel = self.add(Panel((w // 2 - 190, 80), (380, 500)))

        self.tabs = self.add(Tabs((x, 96), (300, 40), ["Room code", "Address"], 0,
                                  on_change=self._set_mode))
        self.add(Label((x, 152), "Username", size=20, color="muted"))
        self.name_box = self.add(TextBox((x, 176), (300, 50), max_length=MAX_NAME,
                                         placeholder="Your name", on_submit=self._focus_next))

        # "Room code" tab
        self.room_label = self.add(Label((x, 242), "Room code from the host", size=20,
                                         color="muted"))
        self.room_box = self.add(TextBox((x, 266), (300, 50), allowed=ROOM_CHARS, max_length=14,
                                         placeholder="XXXX-XXXX-XXXX", on_submit=self.join))
        # "Address" tab
        self.addr_label = self.add(Label((x, 242), "Server address", size=20, color="muted"))
        self.address_box = self.add(TextBox((x, 266), (300, 50), text_size=22,
                                            allowed=ADDRESS_CHARS, max_length=80,
                                            placeholder="address or address:port",
                                            on_submit=self._focus_code))
        self.code_label = self.add(Label((x, 332), "Lobby code (if there is one)", size=20,
                                         color="muted"))
        self.code_box = self.add(TextBox((x, 356), (300, 50), max_length=MAX_CODE,
                                         on_submit=self.join))

        self.join_btn = self.add(Button((w // 2 - 100, 340), (200, 60), "Join", 28, "btn_blue",
                                        action=self.join))
        self.status = self.add(TextBlock((w // 2 - 170, 412), 340, "", size=18,
                                         color="error", center=True))
        self.add(Button((20, 20), (120, 45), "Back", 22, "btn_neutral", action=self.back))
        help_pos, help_size = ((w // 2 - 65, 534), (130, 36)) if narrow else ((150, 20), (130, 45))
        self.add(Button(help_pos, help_size, "Online help", 20, "btn_neutral",
                        action=open_help, args=(self.game, "join")))
        self._set_mode(0)
        self.name_box.focused = True

    def _set_mode(self, index):
        """Show the fields for the chosen tab (0 = room code, 1 = address)."""
        room = index == 0
        for obj in (self.room_label, self.room_box):
            obj.visible = obj.enabled = room
        for obj in (self.addr_label, self.address_box, self.code_label, self.code_box):
            obj.visible = obj.enabled = not room
        for box in (self.room_box, self.address_box, self.code_box):
            box.focused = False
        self.join_btn.rect.y = 340 if room else 430
        self.status.rect.y = 412 if room else 502
        self.panel.rect.height = 400 if room else 500
        self.status.text = ""

    def _focus_next(self):
        self.name_box.focused = False
        (self.room_box if self.tabs.selected == 0 else self.address_box).focused = True

    def _focus_code(self):
        self.address_box.focused = False
        self.code_box.focused = True

    def _show(self, text, error):
        self.status.color = "error" if error else "muted"
        self.status.text = text

    def back(self):
        self.game.disconnect()
        self.game.change_scene("mode_select")

    def join(self):
        if self.game.client:  # already connecting
            return
        name = " ".join(self.name_box.text.split())
        if not name:
            self._show("Please enter a username.", error=True)
            return

        if self.tabs.selected == 0:
            try:
                code, _ = relay.parse_room_code(self.room_box.text)
            except ValueError as problem:
                self._show(str(problem), error=True)
                return
            self.game.client = Client()
            self.game.client.connect_room(code, name)
            self._show("Connecting to the room...", error=False)
        else:
            try:
                host, port = parse_address(self.address_box.text)
            except ValueError as problem:
                self._show(str(problem), error=True)
                return
            self.game.client = Client()
            self.game.client.connect(host, port, name=name, code=self.code_box.text.strip())
            self._show(f"Connecting to {host}:{port}...", error=False)
        self.join_btn.enabled = False

    def update(self, dt):
        super().update(dt)
        client = self.game.client
        if client is None:
            return
        if client.status == "connected":
            self.game.change_scene("lobby")
        elif client.status in ("failed", "closed"):
            message = client.message
            self.game.disconnect()
            self.join_btn.enabled = True
            self._show(message, error=True)


HELP_CARDS = [
    ("Private network: Tailscale",
     "Everyone installs Tailscale (free for up to 6 people). Friends join using the host's "
     "Tailscale address (starts with 100.) on the Address tab."),
    ("Free tunnel: playit.gg",
     "Only the host installs it. Make a TCP tunnel to port 5555, then share the address it "
     "shows (like name.at.ply.gg:7261) on the Address tab."),
    ("Always-on server",
     "Run server.py on a cloud server or a spare PC that stays on. Friends join its IP on "
     "the Address tab. See README_INTERNET.md."),
    ("Router port forwarding",
     "Forward TCP port 5555 on the host's router. It won't work if your provider shares one "
     "public IP between customers (CGNAT)."),
]
HELP_ROOM = ("Online room (built in, easiest)",
             "Tick \"Also open an online room\" when you host. You get a room code like "
             "K7QX-M2PD-9TNA. Friends choose the Room code tab and type it. It works behind "
             "home routers and CGNAT with nothing to install. It goes through a free public "
             "relay server (shared, no guarantees); everything is encrypted with the code.")


class HelpScene(Scene):
    FULL = True     # a long page: on an upright phone it gets the whole tall screen

    def setup(self):
        w = self.size[0]
        if w < 700:
            return self._setup_narrow(w)
        self.add(Label((w // 2, 40), "Playing over the internet", size=40, center=True))
        left = 20
        full = w - 2 * left
        title, body = HELP_ROOM
        self.add(Panel((left, 80), (full, 122)))
        self.add(Label((left + 18, 92), title, size=24))
        self.add(TextBlock((left + 18, 124), full - 36, body, size=18, color="muted"))

        card_w, card_h, gap = (full - 16) // 2, 150, 16
        for i, (title, body) in enumerate(HELP_CARDS):
            x = left + (i % 2) * (card_w + gap)
            y = 216 + (i // 2) * (card_h + 12)
            self.add(Panel((x, y), (card_w, card_h)))
            self.add(Label((x + 16, y + 12), title, size=22))
            self.add(TextBlock((x + 16, y + 44), card_w - 32, body, size=18, color="muted"))
        self.add(TextBlock((left, 540), full,
                           "Set a lobby code or keep the room code private so strangers can't "
                           "join. Everyone needs the same version of the game.",
                           size=17, color="muted", center=True))
        self.add(Button((20, 20), (120, 45), "Back", 22, "btn_neutral", action=self.back))

    def _setup_narrow(self, w):
        """One column, each box as tall as its text needs (measured, so it fits any font)."""
        self.add(Button((20, 20), (120, 45), "Back", 22, "btn_neutral", action=self.back))
        self.add(Label((w // 2, 100), "Playing over the internet", size=28, center=True))
        left = 14
        full = w - 2 * left
        y = 128
        for title, body in [HELP_ROOM] + HELP_CARDS:
            block = TextBlock((left + 14, y + 40), full - 28, body, size=17, color="muted")
            height = 40 + block.rect.height + 14
            self.add(Panel((left, y), (full, height)))
            self.add(Label((left + 14, y + 10), fit_text(title, 21, full - 28), size=21))
            self.add(block)
            y += height + 10
        self.add(TextBlock((left, y + 4), full,
                           "Set a lobby code or keep the room code private so strangers can't "
                           "join. Everyone needs the same version of the game.",
                           size=16, color="muted", center=True))

    def back(self):
        self.game.change_scene(getattr(self.game, "help_from", "mode_select"))


class LobbyScene(Scene):
    def setup(self):
        w = self.size[0]
        server = self.game.server  # set only if I am running the server myself

        self.add(Label((w // 2, 42), "Lobby", size=44, center=True))
        self.count = self.add(Label((w // 2, 84), "", size=20, color="muted", center=True))
        self.player_list = self.add(Leaderboard((w // 2 - 230, 110), (460, 336)))

        self.leave_btn = self.add(Button((w // 2 - 110, 456), (220, 50),
                                         "Close Lobby" if server else "Leave", 22, "btn_red",
                                         action=self.leave))
        self.start_btn = self.add(Button((w // 2 + 30, 456), (200, 50), "Start Game", 22,
                                         "btn_green", action=self.start))
        self.start_btn.visible = self.start_btn.enabled = False

        self.footer = self.room_line = self.copy_btn = self.note_line = None
        self.copy_timer = 0.0
        if server:
            where = f"{server.ip}:{server.port}" + (f"    Code: {server.code}" if server.code else "")
            if server.relay:
                self.room_line = self.add(Label((w // 2, 533), "", size=26, center=True))
                self.copy_btn = self.add(Button((0, 518), (84, 30), "Copy", 18, "btn_neutral",
                                                action=self.copy_code))
                self.copy_btn.visible = self.copy_btn.enabled = False
                self.add(Label((w // 2, 563), f"Direct: {where}", size=17, color="muted",
                               center=True))
                self.note_line = self.add(Label((w // 2, 583), "", size=15, color="muted",
                                                center=True))
            else:
                self.add(Label((w // 2, 543), "Friends on your Wi-Fi join with", size=16,
                               color="muted", center=True))
                self.add(Label((w // 2, 566), where, size=24, center=True))
        else:
            self.footer = self.add(Label((w // 2, 560), "", size=20, color="muted", center=True))
        self.ping = self.add(Label((12, 580), "", size=15, color="muted"))

    def start(self):
        client = self.game.client
        if client:
            client.send({"type": "start"})

    def leave(self):
        self.game.disconnect()
        self.game.change_scene("mode_select")

    def copy_code(self):
        server = self.game.server
        if server and server.room_code:
            self.copy_btn.text = "Copied!" if clipboard.copy(relay.format_code(server.room_code)) \
                else "Copy failed"
            self.copy_timer = 2.0

    def _update_room(self, dt):
        """The host's online-room line: opening... / the code + Copy / unavailable."""
        server = self.game.server
        status = server.room_status
        code = server.room_code
        self.copy_timer = max(0.0, self.copy_timer - dt)
        if self.copy_timer == 0.0 and self.copy_btn.text != "Copy":
            self.copy_btn.text = "Copy"
        if code:
            self.room_line.color = "text"
            self.room_line.text = f"Room code  {relay.format_code(code)}"
            self.copy_btn.visible = self.copy_btn.enabled = True
            self.note_line.text = ("Lost the relay server. Reconnecting..."
                                   if status == "reconnecting" else "")
            # centre the code and the Copy button together (computed fresh every frame)
            total = self.room_line.rect.width + 14 + self.copy_btn.rect.width
            self.room_line.rect.x = self.size[0] // 2 - total // 2
            self.copy_btn.rect.x = self.room_line.rect.right + 14
        else:
            self.copy_btn.visible = self.copy_btn.enabled = False
            if status == "error":
                self.room_line.color = "error"
                self.room_line.text = "Online room unavailable"
                self.note_line.text = server.room_detail[:92] + " (retrying)"
            else:
                self.room_line.color = "muted"
                self.room_line.text = "Opening online room..."
                self.note_line.text = ""

    def update(self, dt):
        super().update(dt)
        client = self.game.client
        w = self.size[0]

        if client is None or client.status in ("failed", "closed"):
            self.game.disconnect(client.message if client else "")
            self.game.change_scene("mode_select")
        elif client.game is not None:
            self.game.change_scene("game")  # the leader started the game
        elif client.status == "connected":
            self.player_list.set_players(client.players, client.my_id)
            self.count.text = f"Players: {len(client.players)}/{MAX_PLAYERS}"

            # Only the lobby leader gets a Start button. Leadership can pass to someone else
            # when the leader leaves a dedicated server, so this is checked every frame.
            leader = client.is_host
            self.start_btn.visible = leader
            self.start_btn.enabled = leader and len(client.players) >= MIN_PLAYERS
            self.leave_btn.rect.x = w // 2 - (230 if leader else 110)
            self.leave_btn.rect.width = 200 if leader else 220
            if leader and not self.start_btn.enabled:
                self.count.text += f"   (need {MIN_PLAYERS} to start)"

            if self.footer is not None:
                boss = next((p["name"] for p in client.players if p.get("host")), "the host")
                self.footer.text = ("You are the lobby leader. Start when everyone is in."
                                    if leader else f"Waiting for {boss} to start...")
            if self.room_line is not None:
                self._update_room(dt)
            self.ping.text = data_meter(self.game)
        else:
            self.count.text = "Connecting..."


# ---------------------------------------------------------------- the game

CARD_W, CARD_H = 70, 100
HAND_BELOW = 130        # the cards in your hand start this far above the bottom of the screen
OPP_W, OPP_H, OPP_GAP = 150, 56, 6    # a box showing another player
CENTER_BLOCK = 244      # height of the table's middle (piles, status line, messages)
PLAYABLE_LIFT = 10      # cards you can play sit a little higher on your turn
HOVER_LIFT = 26         # ...and pop up more when the mouse is over them
COLOR_ORDER = {"red": 0, "yellow": 1, "green": 2, "blue": 3, "wild": 4}
SPECIAL_ORDER = ["skip", "reverse", "draw2", "wild", "wild4"]
AVATARS = [(231, 76, 60), (230, 126, 34), (39, 174, 96), (41, 128, 185),
           (142, 68, 173), (22, 160, 133), (211, 84, 0), (52, 73, 94)]


def card_sort_key(card):
    value = card["value"]
    rank = int(value) if value.isdigit() else 10 + SPECIAL_ORDER.index(value)
    return (COLOR_ORDER[card["color"]], rank)


def avatar_color(name):
    return AVATARS[sum(map(ord, name)) % len(AVATARS)]  # same color on every computer


class GameScene(Scene):
    """
    Draws whatever the server last told us (client.game) and sends the player's clicks back.
    It never decides anything about the rules itself; the server is the referee.

    Animations are driven by the server's "events" (who played / drew what): cards fly
    between the piles, the hand and the other players' boxes.
    """

    bg_role = "table"
    FULL = True     # the table uses the whole canvas, whatever its shape

    def _geometry(self):
        """Where things go, from the canvas size. Sideways (wide) screens keep the classic
        layout; an upright phone gets the same pieces stacked down a tall, narrow canvas."""
        w, h = self.size
        g = self.state
        others = max(1, len(g["players"]) - 1) if g else 1
        self.upright = h > w
        self.per_row = max(1, min(5, (w - 12) // (OPP_W + OPP_GAP)))   # boxes that fit in a row
        rows = -(-others // self.per_row)
        self.opp_bottom = 10 + rows * (OPP_H + 8)
        self.hand_y = h - HAND_BELOW
        # the table's middle sits half-way between the other players and your hand
        self.cy = self.opp_bottom + max(0, (self.hand_y - self.opp_bottom - CENTER_BLOCK) // 2)
        if self.upright:    # no room beside the piles: Leave and the theme button go above the hand
            self.leave_pos = (w - 140, self.hand_y - 124)
            self.toggle_at = (w - 54, self.hand_y - 82)
        else:
            self.leave_pos = (w - 140, self.cy)
            self.toggle_at = (w - 54, self.cy + 42)

    def toggle_position(self):
        return self.toggle_at

    def setup(self):
        self._geometry()
        w, h = self.size
        cy = self.cy
        client = self.game.client
        is_host = self.game.server is not None

        self.leave_btn = self.add(Button(self.leave_pos, (130, 34),
                                         "Close Lobby" if is_host else "Leave", 18, "btn_red",
                                         action=self.leave))
        self.pass_btn = self.add(Button((w // 2 - 200, cy + 30), (90, 40), "Pass", 22, "btn_yellow",
                                        action=self.pass_turn))
        self.lobby_btn = self.add(Button((w // 2 - 110, cy + 140), (220, 50), "Back to Lobby", 22,
                                         "btn_green", action=self.back_to_lobby))
        for btn in (self.pass_btn, self.lobby_btn):
            btn.visible = btn.enabled = False

        self.draw_rect = pygame.Rect(w // 2 - 95, cy, CARD_W, CARD_H)
        self.discard_rect = pygame.Rect(w // 2 + 25, cy, CARD_W, CARD_H)

        self.pending_wild = None    # id of a wild card waiting for the player to pick a color
        self.toast = ""
        self.toast_time = 0.0
        self._seen_toast = client.toast_seq if client else 0

        # animation state
        self.time = 0.0
        self.mouse = (0, 0)
        self.flights = []           # cards currently in the air
        self.hidden = set()         # ids of my cards that are still flying in (not drawn yet)
        self.lift = {}              # card id -> how far it is raised right now
        self.hover_i = None
        self.raised = None          # touch mode: id of the card that was tapped once (raised)
        self._tap_hint = False      # the "tap again to play" hint has been shown
        self.play_pending = 0       # played cards still flying to the discard pile
        self.last_slots = {}        # card id -> where it was drawn last frame
        self.opp_layout = []        # [(player dict, rect)] for the other players
        self.box_rects = {}         # player id -> rect
        self.ping_label = self.add(Label((12, h - 18), "", size=14, color="table_muted"))
        self.over_t = 0.0           # seconds since the game ended
        self.confetti = None

        g = self.state
        self.shown_top = g["top"] if g else None
        self.last_seq = 0
        if g:
            self.last_seq = max((e["seq"] for e in g.get("events", [])), default=0)
            self._layout(g)
            if not g.get("events"):
                self._deal(g)

    # -- helpers

    @property
    def state(self):
        client = self.game.client
        return client.game if client else None

    def _my_turn(self, g):
        return not g["over"] and g["current"] == self.game.client.my_id

    def _say(self, text):
        self.toast = text
        self.toast_time = 3.0

    def _send(self, msg):
        if self.game.client:
            self.game.client.send(msg)

    def _text(self, screen, text, size, color, center=None, topleft=None):
        text = fit_text(text, size, self.size[0] - 16)     # never wider than the screen
        surf = text_surface(text, size, theme.resolve(color))
        rect = surf.get_rect()
        if center is not None:
            rect.center = center
        else:
            rect.topleft = topleft
        screen.blit(surf, rect)

    def _layout(self, g):
        """Where the other players' boxes go: starting with whoever plays after you."""
        w = self.size[0]
        me = self.game.client.my_id
        players = g["players"]
        ids = [p["id"] for p in players]
        if me in ids:
            i = ids.index(me)
            players = players[i + 1:] + players[:i]
        box_w, box_h, gap = OPP_W, OPP_H, OPP_GAP
        self.opp_layout, self.box_rects = [], {}
        for row_start in range(0, len(players), self.per_row):
            row = players[row_start:row_start + self.per_row]
            x0 = (w - (len(row) * box_w + (len(row) - 1) * gap)) // 2
            y = 10 + (row_start // self.per_row) * (box_h + 8)
            for k, p in enumerate(row):
                rect = pygame.Rect(x0 + k * (box_w + gap), y, box_w, box_h)
                self.opp_layout.append((p, rect))
                self.box_rects[p["id"]] = rect

    def _hand_rects(self, count):
        if count == 0:
            return []
        room = min(self.size[0] - 40, 1100)      # how wide the hand may spread
        step = min(80, (room - CARD_W) / (count - 1)) if count > 1 else 0
        total = (count - 1) * step + CARD_W
        x0 = (self.size[0] - total) / 2
        return [pygame.Rect(int(x0 + i * step), self.hand_y, CARD_W, CARD_H) for i in range(count)]

    def _card_at(self, pos, count, first=None):
        """Index of the card under `pos` (the rightmost one wins, it's drawn on top).
        `first`: a card drawn on top of the others (the raised one) that is tested first."""
        rects = self._hand_rects(count)
        order = list(reversed(range(count)))
        if first is not None and 0 <= first < count:
            order.remove(first)
            order.insert(0, first)
        for i in order:
            r = rects[i]
            if pygame.Rect(r.x, r.y - HOVER_LIFT, r.width, r.height + HOVER_LIFT).collidepoint(pos):
                return i
        return None

    def _sorted_hand(self, g):
        return sorted(g["hand"], key=card_sort_key)

    def _picker_rects(self):
        w = self.size[0]
        size, gap = 80, 16
        x0 = (w - (4 * size + 3 * gap)) // 2
        return [(color, pygame.Rect(x0 + i * (size + gap), self.cy + 100, size, size))
                for i, color in enumerate(COLORS)]

    def _panel_rect(self, g):
        """The game-over box. Tall enough for one row per player plus the button underneath."""
        w, h = self.size
        height = 120 + 26 * max(1, len(g["ranking"])) + 80
        return pygame.Rect(w // 2 - 230, max(15, (h - height) // 2), 460, height)

    def _over_offset(self):
        """The game-over box slides down into place."""
        return int((1 - ease_out_cubic(self.over_t / 0.45)) * -90)

    # -- animation

    def _slot_pos(self, card_id):
        """Where card `card_id` sits in my hand right now (None if it isn't there)."""
        g = self.state
        if not g:
            return None
        hand = self._sorted_hand(g)
        for i, c in enumerate(hand):
            if c["id"] == card_id:
                return self._hand_rects(len(hand))[i].topleft
        return None

    def _box_pos(self, pid):
        """Top-left for a card sitting centered on player pid's box."""
        rect = self.box_rects.get(pid)
        if rect is None:  # finished or left: come from just above the screen
            return (self.size[0] // 2 - CARD_W // 2, -CARD_H)
        return (rect.centerx - CARD_W // 2, rect.centery - CARD_H // 2)

    def _fly_to_hand(self, card_id, delay):
        self.hidden.add(card_id)
        self.flights.append(Flight(None, self.draw_rect.topleft,
                                   lambda: self._slot_pos(card_id), 0.42, delay,
                                   lambda: self.hidden.discard(card_id)))

    def _fly_to_player(self, pid, delay):
        self.flights.append(Flight(None, self.draw_rect.topleft,
                                   lambda: self._box_pos(pid), 0.42, delay))

    def _deal(self, g):
        """The opening deal: my cards fly in one by one; others get a couple each."""
        for k, card in enumerate(self._sorted_hand(g)):
            self._fly_to_hand(card["id"], 0.07 * k)
        n = max(1, len(self.opp_layout))
        for j, (p, _) in enumerate(self.opp_layout):
            for k in range(2):
                self._fly_to_player(p["id"], 0.05 * (k * n + j))

    def _process_events(self, g):
        me = self.game.client.my_id
        for e in g.get("events", []):
            if e["seq"] <= self.last_seq:
                continue
            self.last_seq = e["seq"]
            if e["kind"] == "play":
                card, pid = e["card"], e["pid"]
                if pid == me:
                    start = self.last_slots.get(card["id"],
                                                (self.size[0] // 2 - CARD_W // 2, self.hand_y))
                else:
                    start = self._box_pos(pid)
                self.play_pending += 1
                self.flights.append(Flight(card, start, self.discard_rect.topleft, 0.35, 0.0,
                                           lambda card=card: self._landed(card)))
            elif e["kind"] == "draw":
                if e["pid"] == me:
                    for k, cid in enumerate((e.get("cards") or [])[:6]):
                        self._fly_to_hand(cid, 0.12 * k)
                else:
                    for k in range(min(e.get("count", 1), 4)):
                        self._fly_to_player(e["pid"], 0.12 * k)

    def _landed(self, card):
        self.play_pending -= 1
        self.shown_top = card

    # -- actions

    def pass_turn(self):
        self._send({"type": "pass"})

    def back_to_lobby(self):
        self._send({"type": "to_lobby"})

    def leave(self):
        self.game.disconnect()
        self.game.change_scene("mode_select")

    # -- input

    def handle_event(self, event):
        g = self.state
        if g and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not g["over"]:
            if self.pending_wild is not None:
                self._click_color_picker(event.pos)
                return
            self._click_table(event.pos, g)
        super().handle_event(event)

    def _click_table(self, pos, g):
        my_turn = self._my_turn(g)
        if self.draw_rect.collidepoint(pos):
            self.raised = None
            if g["place"] is not None:
                self._say("You already finished. Sit back and watch!")
            elif not my_turn:
                self._say("It's not your turn.")
            elif g["drawn"] is not None:
                self._say("You already drew. Play that card or pass.")
            else:
                self._send({"type": "draw"})
            return

        hand = self._sorted_hand(g)
        if touch.enabled:
            # Overlapping cards can't be previewed by hovering, so: tap a card to raise it
            # (you can see it, nothing is played), tap the raised card again to play it.
            ids = [c["id"] for c in hand]
            raised = ids.index(self.raised) if self.raised in ids else None
            index = self._card_at(pos, len(hand), first=raised)
            if index is None:
                self.raised = None              # a tap anywhere else puts the card back
                return
            card = hand[index]
            if card["id"] in self.hidden:
                return
            if card["id"] != self.raised:
                self.raised = card["id"]
                if not self._tap_hint and my_turn and card["id"] in g["playable"]:
                    self._tap_hint = True
                    self._say("Tap the raised card again to play it.")
                return
            self.raised = None                  # second tap: play it (checks below)
        else:
            index = self._card_at(pos, len(hand))
            if index is None:
                return
            card = hand[index]
            if card["id"] in self.hidden:
                return  # still flying in
        if not my_turn:
            self._say("It's not your turn.")
        elif card["id"] not in g["playable"]:
            self._say("You can't play that card right now.")
        elif card["color"] == "wild":
            self.pending_wild = card["id"]  # ask which color first
        else:
            self._send({"type": "play", "card": card["id"]})

    def _click_color_picker(self, pos):
        for color, rect in self._picker_rects():
            if rect.collidepoint(pos):
                self._send({"type": "play", "card": self.pending_wild, "color": color})
                break
        self.pending_wild = None  # a click anywhere else cancels

    # -- per frame

    def update(self, dt):
        super().update(dt)
        client = self.game.client

        if client is None or client.status in ("failed", "closed"):
            self.game.disconnect(client.message if client else "")
            self.game.change_scene("mode_select")
            return
        g = client.game
        if g is None:  # the host sent everyone back to the lobby
            self.game.change_scene("lobby")
            return

        self.time += dt
        self.mouse = pointer_pos()
        self.ping_label.text = data_meter(self.game)

        if client.toast_seq != self._seen_toast:
            self._seen_toast = client.toast_seq
            self._say(client.toast)
        self.toast_time = max(0.0, self.toast_time - dt)

        # cards in the air
        self._layout(g)
        self._process_events(g)
        for f in self.flights:
            f.update(dt)
        self.flights = [f for f in self.flights if not f.landed]
        if self.play_pending == 0:
            self.shown_top = g["top"]  # nothing in flight: always show the real top card

        over = g["over"]
        my_turn = self._my_turn(g)
        self.pass_btn.visible = self.pass_btn.enabled = my_turn and g["drawn"] is not None
        self.lobby_btn.visible = self.lobby_btn.enabled = over and client.is_host
        if not my_turn:
            self.pending_wild = None

        # my hand: playable cards sit raised, the hovered one pops up
        hand = self._sorted_hand(g)
        self.hover_i = None
        if touch.enabled:
            # no hover on a touch screen: only the card that was tapped once is raised
            ids = [c["id"] for c in hand]
            if self.raised in ids and self.raised not in self.hidden:
                self.hover_i = ids.index(self.raised)
            else:
                self.raised = None
        elif my_turn and self.pending_wild is None:
            i = self._card_at(self.mouse, len(hand))
            if i is not None and hand[i]["id"] in g["playable"] and hand[i]["id"] not in self.hidden:
                self.hover_i = i
        for i, card in enumerate(hand):
            target = PLAYABLE_LIFT if (my_turn and card["id"] in g["playable"]) else 0
            if i == self.hover_i:
                target = HOVER_LIFT
            self.lift[card["id"]] = approach(self.lift.get(card["id"], 0.0), target, dt, 16)
        ids = {c["id"] for c in hand}
        self.lift = {cid: v for cid, v in self.lift.items() if cid in ids}

        # game over: panel slides in, confetti falls
        if over:
            self.over_t += dt
            if self.confetti is None:
                self.confetti = Confetti(*self.size, seed=g["winner"] or 0)
            self.confetti.update(dt)
            self.lobby_btn.rect.y = self._panel_rect(g).bottom - 65 + self._over_offset()

    # -- drawing

    def draw(self, screen):
        screen.fill(self.background())
        g = self.state
        if g:
            self._draw_table(screen, g)
        for obj in self.objects:
            if obj.visible:
                obj.draw(screen)
        if g and self.pending_wild is not None:
            self._draw_color_picker(screen)

    def _draw_table(self, screen, g):
        w = self.size[0]
        my_turn = self._my_turn(g)
        table = theme["table"]

        for p, rect in self.opp_layout:
            self._draw_opponent(screen, g, p, rect)

        # draw pile (a little stack), discard pile with a ring in the current color
        layers = 2 if g["draw_count"] > 10 else 1 if g["draw_count"] > 0 else 0
        if layers == 0:
            pygame.draw.rect(screen, theme["table_muted"], self.draw_rect, width=2, border_radius=8)
        for k in range(layers, 0, -1):
            draw_card(screen, self.draw_rect.move(k * 2, k * 2), None)
        if layers:
            draw_card(screen, self.draw_rect, None, shadow=True)
        self._text(screen, f'Draw pile ({g["draw_count"]})', 18, "table_text",
                   center=(self.draw_rect.centerx, self.draw_rect.bottom + 16))

        pygame.draw.rect(screen, COLOR_RGB[g["color"]], self.discard_rect.inflate(12, 12),
                         width=4, border_radius=12)
        draw_card(screen, self.discard_rect, self.shown_top or g["top"], shadow=True)
        swatch = (self.discard_rect.right + 65, self.discard_rect.centery)
        pygame.draw.circle(screen, (255, 255, 255), swatch, 26)
        pygame.draw.circle(screen, COLOR_RGB[g["color"]], swatch, 22)
        self._text(screen, "Color", 18, "table_text", center=(swatch[0], swatch[1] + 42))
        arrows = ">>" if g["direction"] == 1 else "<<"
        self._text(screen, f"Direction {arrows}", 20, "table_muted", topleft=(20, self.cy + 40))

        # whose turn is it
        if g["over"]:
            pass
        elif g["place"] is not None:
            self._text(screen, f'You finished {ordinal(g["place"])}! Watching the rest play...',
                       24, (255, 225, 80), center=(w // 2, self.cy + 154))
        elif my_turn:
            hint = ("You drew a card: play it or pass." if g["drawn"] is not None
                    else "Your turn! Play a card or draw.")
            self._text(screen, hint, 28, (255, 225, 80), center=(w // 2, self.cy + 154))
        else:
            name = next((p["name"] for p in g["players"] if p["id"] == g["current"]), "?")
            self._text(screen, f"{fit_text(name, 28, 400)}'s turn", 28, "table_text",
                       center=(w // 2, self.cy + 154))

        if self.toast_time > 0:
            color = lerp_color(table, theme["toast"], clamp(self.toast_time))  # fades out
            self._text(screen, self.toast, 22, color, center=(w // 2, self.cy + 182))
        log = g["log"]
        for n, line in enumerate(log):
            color = lerp_color(table, theme["table_text"], 0.45 + 0.55 * n / max(1, len(log) - 1))
            self._text(screen, line, 19, color, center=(w // 2, self.cy + 212 + 21 * n))

        # my hand; the hovered card is drawn last so it sits on top of its neighbours
        hand = self._sorted_hand(g)
        rects = self._hand_rects(len(hand))
        order = [i for i in range(len(hand)) if i != self.hover_i]
        if self.hover_i is not None:
            order.append(self.hover_i)
        slots = {}
        for i in order:
            card = hand[i]
            r = rects[i].move(0, -int(self.lift.get(card["id"], 0)))
            slots[card["id"]] = r.topleft
            if card["id"] in self.hidden:
                continue
            dim = my_turn and card["id"] not in g["playable"]
            draw_card(screen, r, card, dim=dim, shadow=True)
        self.last_slots = slots

        # cards in the air
        for f in self.flights:
            pos = f.position()
            if pos:
                draw_card(screen, pygame.Rect(pos[0], pos[1], CARD_W, CARD_H), f.card, shadow=True)

        if g["over"]:
            self._draw_game_over(screen, g)

    def _draw_opponent(self, screen, g, p, rect):
        current = p["id"] == g["current"] and not g["over"]
        finished = p["place"] is not None
        pygame.draw.rect(screen, theme["highlight"] if finished else theme["box"], rect,
                         border_radius=12)
        if current:  # a pulsing gold ring
            pulse = 0.5 + 0.5 * math.sin(self.time * 6)
            pygame.draw.rect(screen, lerp_color((255, 190, 0), (255, 240, 150), pulse), rect,
                             width=4, border_radius=12)
        else:
            pygame.draw.rect(screen, theme["border"], rect, width=1, border_radius=12)

        pygame.draw.circle(screen, avatar_color(p["name"]), (rect.x + 28, rect.centery), 18)
        initial = text_surface(p["name"][:1].upper() or "?", 24, (255, 255, 255))
        screen.blit(initial, initial.get_rect(center=(rect.x + 28, rect.centery)))

        tx = rect.x + 54
        self._text(screen, fit_text(p["name"], 18, rect.right - tx - 8), 18, "text",
                   topleft=(tx, rect.y + 9))
        if finished:
            self._text(screen, f'Finished {ordinal(p["place"])}', 16, "highlight_text",
                       topleft=(tx, rect.y + 32))
        elif p["count"] == 1:
            self._text(screen, "UNO!", 18, "error", topleft=(tx, rect.y + 31))
        else:
            self._text(screen, f'{p["count"]} cards', 16, "muted", topleft=(tx, rect.y + 32))

    def _draw_game_over(self, screen, g):
        w = self.size[0]
        me = self.game.client.my_id
        fade = ease_out_cubic(self.over_t / 0.4)
        shade = dim_surface(self.size)
        shade.set_alpha(int(150 * fade))
        screen.blit(shade, (0, 0))
        if self.confetti:
            self.confetti.draw(screen)

        oy = self._over_offset()
        panel = self._panel_rect(g).move(0, oy)
        pygame.draw.rect(screen, theme["shadow"], panel.move(0, 5), border_radius=16)
        pygame.draw.rect(screen, theme["panel"], panel, border_radius=16)
        pygame.draw.rect(screen, theme["border"], panel, width=1, border_radius=16)

        won = g["winner"] == me
        title = "You win!" if won else f'{fit_text(g["winner_name"], 40, 400)} wins!'
        self._text(screen, title, 40, theme["btn_red"] if won else "text",
                   center=(w // 2, panel.y + 35))
        sub = "Some players left the game." if g["forfeit"] else "Last player with cards loses."
        self._text(screen, sub, 18, "muted", center=(w // 2, panel.y + 72))

        y = panel.y + 100
        for place, row in enumerate(g["ranking"], start=1):
            mine = row["id"] == me
            if mine:
                pygame.draw.rect(screen, theme["highlight"],
                                 pygame.Rect(panel.x + 12, y - 2, panel.width - 24, 26),
                                 border_radius=8)
            self._text(screen, f"{place}.", 20, "text", topleft=(panel.x + 28, y + 3))
            name = fit_text(row["name"], 20, 240) + (" (You)" if mine else "")
            self._text(screen, name, 20, "text", topleft=(panel.x + 70, y + 3))
            pts = text_surface(f'+{row["points"]} pts', 20, theme["ok"])
            screen.blit(pts, pts.get_rect(topright=(panel.right - 28, y + 3)))
            y += 26

        if not self.game.client.is_host:
            self._text(screen, "Waiting for the leader...", 22, "muted",
                       center=(w // 2, panel.bottom - 40))

    def _draw_color_picker(self, screen):
        w = self.size[0]
        shade = dim_surface(self.size)
        shade.set_alpha(170)
        screen.blit(shade, (0, 0))
        self._text(screen, "Choose a color", 34, (255, 255, 255), center=(w // 2, self.cy + 65))
        for color, rect in self._picker_rects():
            if rect.collidepoint(self.mouse):
                rect = rect.inflate(10, 10)  # the swatch under the mouse grows
            pygame.draw.rect(screen, (255, 255, 255), rect.inflate(8, 8), border_radius=12)
            pygame.draw.rect(screen, COLOR_RGB[color], rect, border_radius=9)


# Register every scene here.
SCENES = {
    "menu": MenuScene,
    "mode_select": ModeSelectScene,
    "host": HostScene,
    "join": JoinScene,
    "help": HelpScene,
    "lobby": LobbyScene,
    "game": GameScene,
}
