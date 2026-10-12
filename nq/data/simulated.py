"""Source SIMULEE : un NQ synthetique, deterministe, avec le cote de l'agresseur. Les prix ne sont PAS reels.

Sert a essayer le terminal sans abonnement (et a tester les calculs). Pour chaque minute ouverte du Globex, on tire (graine fixe) un
mouvement, un nombre de transactions et leurs quantites selon la phase de la journee (volatilite et activite fortes a l'ouverture de New York,
faibles la nuit et a midi), puis un chemin de prix continu au tick de 0,25. Le cote de l'agresseur suit la direction du prix, avec de temps en temps
des minutes d'ABSORPTION (gros delta contre le sens du prix) pour pouvoir tester la detection. Meme historique a chaque lancement le meme jour."""
import math
import random

from engine import clock
from engine.bars import Tick
from engine.instruments import NQ, Instrument

from .base import Source

MIN = 60_000

#           volatilite (points par minute), nombre de transactions par minute, taille moyenne
PROFILE = {
    "asia": (2.0, 12, 4.0), "london": (3.5, 25, 5.0), "pre": (4.5, 30, 6.0), "open": (11.0, 90, 10.0), "am": (8.0, 60, 9.0),
    "lunch": (4.5, 38, 7.0), "pm": (6.5, 52, 8.0), "power": (9.0, 70, 9.5), "post": (3.0, 20, 5.0),
}


class SimulatedSource(Source):
    name = "simulated"
    label = "Données SIMULÉES (prix fictifs)"
    simulated = True

    def __init__(self, inst: Instrument = NQ, days: int = 4, seed: int = 7, base: float = 25_000.0, now_fn=None):
        self.inst = inst
        self.days = days
        self.seed = seed
        self.base = base
        self._now_fn = now_fn
        self._px = base
        self._next_m = None            # prochaine minute a generer
        self._buf: list = []           # transactions generees mais pas encore emises (apres `now`)

    def now_ms(self) -> int:
        return self._now_fn() if self._now_fn else super().now_ms()

    # ---------- une minute ----------
    def _minute(self, m: int) -> list:
        t0 = m * MIN
        ph = clock.phase(t0)
        vol, n_mean, q_mean = PROFILE.get(ph["key"], PROFILE["asia"])
        vol *= self.base / 25_000.0                              # les profils sont ecrits pour un NQ a 25 000 : on les met a l'echelle des autres indices
        rnd = random.Random(((self.seed * 1_000_003) ^ (m * 2_654_435_761)) & 0xFFFFFFFFFFFF)
        w = clock.et(t0)
        if w.hour == 9 and w.minute == 30:                      # la premiere minute de New York est la plus violente
            vol *= 1.8
            n_mean = int(n_mean * 1.6)
        move = rnd.gauss(0.0, vol)
        p_flow = 0.0                                            # biais du flux independant du prix
        episode = (m * 40503) % 307
        if episode == 0:                                        # absorption acheteuse : beaucoup de ventes agressives, le prix tient
            move, p_flow = abs(move) * 0.3, -0.38
            n_mean = int(n_mean * 1.8)
        elif episode == 150:                                    # absorption vendeuse
            move, p_flow = -abs(move) * 0.3, 0.38
            n_mean = int(n_mean * 1.8)
        n = max(3, int(rnd.gauss(n_mean, n_mean * 0.25)))
        offs = sorted(rnd.randrange(MIN) for _ in range(n))
        open_p = self._px
        step_sd = vol * 0.8 / math.sqrt(n)
        walk, prev_p, out = 0.0, open_p, []
        walks = []
        for _ in range(n):
            walk += rnd.gauss(0.0, step_sd)
            walks.append(walk)
        bridge_end = walks[-1]
        for k in range(n):
            frac = (k + 1) / n
            raw = open_p + move * frac + (walks[k] - frac * bridge_end)
            p = self.inst.snap(raw)
            dp = p - prev_p
            pb = 0.5 + (0.22 if dp > 0 else -0.22 if dp < 0 else 0.1 * math.tanh(move / max(vol, 1e-9))) + p_flow
            side = 1 if rnd.random() < min(0.97, max(0.03, pb)) else -1
            q = max(1, int(round(rnd.lognormvariate(math.log(q_mean), 0.7))))
            if rnd.random() < 0.012:
                q = rnd.randint(40, 160)                        # gros ordre
            out.append(Tick(t0 + offs[k], p, q, side))
            prev_p = p
        self._px = prev_p
        return out

    # ---------- flux ----------
    def _start_minute(self, now_ms: int) -> int:
        day = clock.trading_day(now_ms)
        for _ in range(self.days - 1):
            day = clock.prev_day(day)
        return clock.window(day, "globex")[0] // MIN

    def _advance(self, now_ms: int) -> list:
        if self._next_m is None:
            self._px = self.base
            self._next_m = self._start_minute(now_ms)
        last_m = now_ms // MIN
        while self._next_m <= last_m:
            if clock.is_open(self._next_m * MIN):
                self._buf.extend(self._minute(self._next_m))
            self._next_m += 1
        i = 0
        while i < len(self._buf) and self._buf[i].t <= now_ms:
            i += 1
        out, self._buf = self._buf[:i], self._buf[i:]
        return out

    def history(self, now_ms: int):
        self._next_m = None
        self._buf = []
        return self._advance(now_ms)

    def poll(self, now_ms: int) -> list:
        if self._next_m is None:
            return self.history(now_ms)
        return self._advance(now_ms)
