"""
UNO rules. No pygame and no networking in here, so it is easy to test.

The server owns one UnoGame and is the only one who changes it. Clients just ask
("play this card", "draw") and the game says yes (returns None) or no (returns a
message explaining why).

Rules implemented
- Standard 108-card deck, 7 cards each, the starting card is always a number card.
- Match the top card by color or by value. Wild cards can be played any time.
- Skip: next player loses their turn.
- Reverse: flips direction (with only 2 players it works like a Skip).
- Draw 2 / Wild Draw 4: next player draws that many cards and loses their turn.
  (No stacking, and Wild Draw 4 can be played any time - no challenges.)
- Drawing: you draw ONE card. If it can be played you may play it or pass,
  otherwise your turn ends automatically.
- "UNO!" is announced automatically when you are down to one card.

How a game ends
- Whoever gets rid of all their cards finishes (1st, 2nd, 3rd...) and then watches.
  The others keep playing until only ONE player still has cards: that player is last.
- Points: with N players, 1st place gets N-1 points, 2nd gets N-2 ... last gets 0.
- Someone who disconnects while still holding cards ranks below everyone who stayed
  (and gets the fewest points). If the game ends because players left, 'forfeit' is True.
"""

import random

COLORS = ("red", "yellow", "green", "blue")
HAND_SIZE = 7

VALUE_NAMES = {
    "skip": "Skip",
    "reverse": "Reverse",
    "draw2": "Draw 2",
    "wild": "Wild",
    "wild4": "Wild Draw 4",
}


def ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


class Card:
    __slots__ = ("id", "color", "value")

    def __init__(self, card_id: int, color: str, value: str):
        self.id = card_id
        self.color = color   # "red" / "yellow" / "green" / "blue" / "wild"
        self.value = value   # "0".."9", "skip", "reverse", "draw2", "wild", "wild4"

    @property
    def is_wild(self) -> bool:
        return self.color == "wild"

    def label(self) -> str:
        name = VALUE_NAMES.get(self.value, self.value)
        return name if self.is_wild else f"{self.color.title()} {name}"

    def to_dict(self) -> dict:
        return {"id": self.id, "color": self.color, "value": self.value}


def build_deck() -> list:
    cards = []

    def add(color, value):
        cards.append(Card(len(cards), color, value))

    for color in COLORS:
        add(color, "0")
        for value in list("123456789") + ["skip", "reverse", "draw2"]:
            add(color, value)
            add(color, value)
    for _ in range(4):
        add("wild", "wild")
        add("wild", "wild4")
    return cards  # 108 cards


class UnoGame:
    def __init__(self, players, rng=None):
        """players: list of (player_id, name) in seating order."""
        self.rng = rng or random.Random()
        self.names = {pid: name for pid, name in players}
        self.total = len(players)

        self.seats = [pid for pid, _ in players]   # everyone still connected (incl. finished)
        self.order = list(self.seats)               # only players who still hold cards
        self.hands = {pid: [] for pid in self.seats}

        self.draw_pile = build_deck()
        self.rng.shuffle(self.draw_pile)
        self.discard = []

        self.current = 0          # index into self.order
        self.direction = 1        # 1 or -1
        self.drawn_card = None    # card the current player just drew and may still play
        self.finished = []        # player ids, in the order they ran out of cards
        self.leavers = []         # players who left while still holding cards, in order
        self.over = False
        self.forfeit = False      # the game ended because players left
        self.ranking = []         # final standings (player ids, 1st to last), set when over
        self.points = {}          # player id -> points earned, set when over
        self.winner = None        # 1st place, set when over
        self.log = []
        self.events = []          # recent things that happened, so screens can animate them
        self._seq = 0

        for _ in range(HAND_SIZE):
            for pid in self.seats:
                self.hands[pid].append(self.draw_pile.pop())

        # The starting card is the first number card we find in the pile.
        index = next(i for i, c in enumerate(self.draw_pile) if c.value.isdigit())
        start = self.draw_pile.pop(index)
        self.discard.append(start)
        self.color = start.color
        self._log(f"The game starts with a {start.label()}.")

    # ------------------------------------------------------------ helpers

    @property
    def top(self) -> Card:
        return self.discard[-1]

    @property
    def current_id(self):
        """Whose turn it is, or None once the game is over."""
        return self.order[self.current] if (self.order and not self.over) else None

    def _log(self, text: str):
        self.log.append(text)
        del self.log[:-20]

    def _event(self, kind: str, pid, **data):
        """Record "pid played a card" / "pid drew cards" for the screens to animate."""
        self._seq += 1
        self.events.append({"seq": self._seq, "kind": kind, "pid": pid, **data})
        del self.events[:-10]

    def _can_play(self, card: Card) -> bool:
        return card.is_wild or card.color == self.color or card.value == self.top.value

    def _advance(self, steps: int = 1):
        if self.order:
            self.current = (self.current + self.direction * steps) % len(self.order)

    def _next_id(self):
        return self.order[(self.current + self.direction) % len(self.order)]

    def _draw_one(self):
        """Take a card from the pile, reshuffling the discard pile if it ran out."""
        if not self.draw_pile and len(self.discard) > 1:
            top = self.discard.pop()
            self.draw_pile, self.discard = self.discard, [top]
            self.rng.shuffle(self.draw_pile)
        return self.draw_pile.pop() if self.draw_pile else None

    def _give(self, pid, count: int) -> list:
        """Deal `count` cards to pid (fewer if the pile runs dry). Returns the cards given."""
        given = []
        for _ in range(count):
            card = self._draw_one()
            if card is None:
                break
            self.hands[pid].append(card)
            given.append(card)
        if given:
            self._event("draw", pid, count=len(given), cards=[c.id for c in given])
        return given

    def _check_turn(self, pid):
        if self.over:
            return "The game is over."
        if pid not in self.hands:
            return "You are not in this game."
        if pid in self.finished:
            return "You already finished, sit back and watch."
        if pid != self.current_id:
            return "It's not your turn."
        return None

    def _end(self):
        """Called when at most one player still holds cards."""
        self.over = True
        self.drawn_card = None
        self.current = 0
        # Finishers by finishing order, then whoever is left with cards, then the people
        # who walked out (the later they left, the better they rank).
        self.ranking = self.finished + list(self.order) + self.leavers[::-1]
        self.points = {pid: self.total - (i + 1) for i, pid in enumerate(self.ranking)}
        self.winner = self.ranking[0]
        self._log(f"Game over! {self.names[self.winner]} takes 1st place.")

    def _finish(self, pid):
        """`pid` just played their last card: they leave the turn order and the game goes on."""
        pos = self.order.index(pid)
        # Who plays next, worked out before the finisher disappears from the order.
        nxt = self.order[self.current]
        if nxt == pid:
            nxt = self.order[(pos + self.direction) % len(self.order)]

        self.finished.append(pid)
        self.order.pop(pos)
        self._log(f"{self.names[pid]} finished in {ordinal(len(self.finished))} place!")

        if len(self.order) <= 1:
            self._end()
        else:
            self.current = self.order.index(nxt)

    # ------------------------------------------------------------ actions
    # Each returns None on success, or a message saying why it was refused.

    def play(self, pid, card_id, color=None):
        error = self._check_turn(pid)
        if error:
            return error

        hand = self.hands[pid]
        card = next((c for c in hand if c.id == card_id), None)
        if card is None:
            return "You don't have that card."
        if self.drawn_card is not None and card is not self.drawn_card:
            return "You can only play the card you just drew (or pass)."
        if not self._can_play(card):
            return "That card can't be played on the current card."
        if card.is_wild and color not in COLORS:
            return "Pick a color for the wild card."

        hand.remove(card)
        self.discard.append(card)
        self.color = color if card.is_wild else card.color
        self.drawn_card = None
        self._event("play", pid, card=card.to_dict())

        name = self.names[pid]
        shown = card.label() + (f", color {color}" if card.is_wild else "")
        self._log(f"{name} played {shown}.")

        if not hand:
            # Going out. The card's effect still happens, unless the game is about to end.
            if len(self.order) > 2:
                self._apply_effect(card)
            self._finish(pid)
            return None

        if len(hand) == 1:
            self._log(f"{name} has UNO!")
        self._apply_effect(card)
        return None

    def _apply_effect(self, card: Card):
        value = card.value
        if value == "skip":
            self._log(f"{self.names[self._next_id()]} is skipped.")
            self._advance(2)
        elif value == "reverse":
            self.direction *= -1
            self._log("Direction reversed.")
            self._advance(2 if len(self.order) == 2 else 1)
        elif value in ("draw2", "wild4"):
            victim = self._next_id()
            got = len(self._give(victim, 2 if value == "draw2" else 4))
            self._log(f"{self.names[victim]} draws {got} and is skipped.")
            self._advance(2)
        else:
            self._advance(1)

    def draw(self, pid):
        error = self._check_turn(pid)
        if error:
            return error
        if self.drawn_card is not None:
            return "You already drew a card - play it or pass."

        name = self.names[pid]
        card = self._draw_one()
        if card is None:
            self._log(f"{name} can't draw, there are no cards left.")
            self._advance(1)
            return None

        self.hands[pid].append(card)
        self._event("draw", pid, count=1, cards=[card.id])
        if self._can_play(card):
            self.drawn_card = card
            self._log(f"{name} drew a card.")
        else:
            self._log(f"{name} drew a card and had to pass.")
            self._advance(1)
        return None

    def pass_turn(self, pid):
        error = self._check_turn(pid)
        if error:
            return error
        if self.drawn_card is None:
            return "Draw a card first."
        self.drawn_card = None
        self._log(f"{self.names[pid]} passed.")
        self._advance(1)
        return None

    def remove_player(self, pid):
        """A player disconnected. Their cards go back into the pile."""
        if pid not in self.seats:
            return
        self.seats.remove(pid)
        self._log(f"{self.names[pid]} left the game.")
        self.draw_pile.extend(self.hands.pop(pid, []))

        if self.over or pid in self.finished:
            return  # their result (if any) is already locked in

        self.rng.shuffle(self.draw_pile)
        pos = self.order.index(pid)
        was_current = pos == self.current
        self.order.pop(pos)
        self.leavers.append(pid)

        if len(self.order) <= 1:
            self.forfeit = True
            self._end()
            return
        if pos < self.current:
            self.current -= 1
        elif was_current:
            self.drawn_card = None
            if self.direction == -1:
                self.current -= 1  # the next player in line slid into this slot
        self.current %= len(self.order)

    # ------------------------------------------------------------ what a player may see

    def view(self, pid) -> dict:
        """Everything player `pid` is allowed to know (their own hand, only counts for others)."""
        my_turn = not self.over and pid == self.current_id
        hand = self.hands.get(pid, [])
        playable = []
        if my_turn:
            playable = [c.id for c in hand
                        if self._can_play(c)
                        and (self.drawn_card is None or c is self.drawn_card)]

        def place(p):
            return self.finished.index(p) + 1 if p in self.finished else None

        return {
            "hand": [c.to_dict() for c in hand],
            "playable": playable,
            "drawn": self.drawn_card.id if (my_turn and self.drawn_card) else None,
            "players": [{"id": p, "name": self.names[p], "count": len(self.hands[p]),
                         "place": place(p)} for p in self.seats],
            "place": place(pid),   # my own place if I already finished, else None
            "current": self.current_id,
            "direction": self.direction,
            "top": self.top.to_dict(),
            "color": self.color,
            "draw_count": len(self.draw_pile),
            "over": self.over,
            "winner": self.winner,
            "winner_name": self.names.get(self.winner),
            "forfeit": self.forfeit,
            "ranking": [{"id": p, "name": self.names[p], "points": self.points[p]}
                        for p in self.ranking],
            "log": self.log[-4:],
            # Who played/drew what. Card ids of other people's draws stay private.
            "events": [{k: v for k, v in e.items() if not (k == "cards" and e["pid"] != pid)}
                       for e in self.events[-6:]],
        }
