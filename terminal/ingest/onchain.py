"""Réseau Bitcoin : mempool.space, CoinMetrics (API communautaire), blockchain.info (V45). Publics, sans clé.

mempool.space (mempool.space/api)
  fees         /v1/fees/recommended            frais conseillés, en satoshis par octet virtuel (rapide, 30 minutes, 1 heure, économique)
  mempool      /mempool                        transactions en attente : nombre, taille (octets virtuels), frais totaux (satoshis)
  difficulty   /v1/difficulty-adjustment       avancement de la période, variation prévue de la difficulté, date du prochain ajustement
  hashrate     /v1/mining/hashrate/3d          puissance de calcul (hachages par seconde) et difficulté du moment
  tip          /blocks/tip/height              hauteur du dernier bloc
CoinMetrics (community-api.coinmetrics.io/v4), valeurs quotidiennes, publiées avec un à deux jours de retard :
  AdrActCnt adresses actives ; CapMVRVCur rapport valeur de marché / valeur réalisée (MVRV) ; TxCnt transactions ; FeeTotNtv frais (BTC) ;
  HashRate ; CapMrktCurUSD capitalisation ; FlowInExNtv / FlowOutExNtv entrées et sorties des bourses (BTC), quand l'accès gratuit les
  donne. Une mesure refusée par l'accès gratuit est retirée de la demande et nommée dans `refused` : jamais remplacée.
blockchain.info (api.blockchain.info/stats) : second avis sur la difficulté et la puissance de calcul. Ses champs de frais et de
  revenus des mineurs sont incohérents (frais négatifs constatés le 14/11/2026) : ils ne sont PAS lus.
`snapshot()` réunit le tout ; chaque partie porte sa propre erreur si sa source ne répond pas."""
from __future__ import annotations
import re
from decimal import Decimal

from quant.num import CTX, D, to_ms
from .core import HttpClient, IngestError, need

MEMPOOL = "https://mempool.space"
COINMETRICS = "https://community-api.coinmetrics.io"
BLOCKCHAIN = "https://api.blockchain.info"
CM_METRICS = ("AdrActCnt", "CapMVRVCur", "TxCnt", "FeeTotNtv", "HashRate", "CapMrktCurUSD", "FlowInExNtv", "FlowOutExNtv")
CM_REFUSED = re.compile(r"metric '([A-Za-z0-9]+)'")
EH = Decimal(10) ** 18                                   # un exahash


class OnChain:
    def __init__(self, mempool: HttpClient | None = None, cm: HttpClient | None = None, bc: HttpClient | None = None):
        self.mp = mempool or HttpClient("mempool.space", MEMPOOL, rate=1.0, burst=5.0)
        self.cm = cm or HttpClient("CoinMetrics", COINMETRICS, rate=0.5, burst=3.0, timeout=25.0)      # accès gratuit : 10 appels par 6 secondes
        self.bc = bc or HttpClient("blockchain.info", BLOCKCHAIN, rate=0.2, burst=2.0)
        self.cm_refused: list = []

    def clients(self):
        return [self.mp, self.cm, self.bc]

    # ---------- mempool.space ----------
    def fees(self) -> dict:
        r = self.mp.get("/api/v1/fees/recommended", ttl=20, retries=2)
        return {"fastest": D(need(r, "fastestFee")), "halfHour": D(need(r, "halfHourFee")), "hour": D(need(r, "hourFee")),
                "economy": D(need(r, "economyFee")), "minimum": D(need(r, "minimumFee"))}

    def mempool(self) -> dict:
        r = self.mp.get("/api/mempool", ttl=20, retries=2)
        return {"count": int(need(r, "count")), "vsize": int(need(r, "vsize")), "totalFeeSat": int(need(r, "total_fee")),
                "blocksToClear": CTX.divide(D(int(r["vsize"])), Decimal(1_000_000))}        # un bloc porte au plus 1 000 000 d'octets virtuels

    def difficulty(self) -> dict:
        r = self.mp.get("/api/v1/difficulty-adjustment", ttl=120, retries=2)
        return {"progressPct": D(need(r, "progressPercent")), "changePct": D(need(r, "difficultyChange")),
                "retargetT": to_ms(int(D(need(r, "estimatedRetargetDate")))), "remainingBlocks": int(need(r, "remainingBlocks")),
                "previousChangePct": D(r["previousRetarget"]) if r.get("previousRetarget") is not None else None}

    def hashrate(self) -> dict:
        r = self.mp.get("/api/v1/mining/hashrate/3d", ttl=600, retries=2)
        cur = D(need(r, "currentHashrate"))
        return {"hashrate": cur, "hashrateEH": CTX.divide(cur, EH), "difficulty": D(need(r, "currentDifficulty")),
                "daily": [(to_ms(x["timestamp"]), CTX.divide(D(x["avgHashrate"]), EH)) for x in r.get("hashrates") or ()]}

    def tip(self) -> int:
        return int(self.mp.get("/api/blocks/tip/height", ttl=20, retries=2))

    # ---------- CoinMetrics ----------
    def coinmetrics(self, asset: str = "btc", metrics=CM_METRICS, days: int = 30) -> dict:
        """{"rows": [{"t": ms, mesure: Decimal, ...}] du plus ancien au plus récent, "metrics": celles obtenues, "refused": celles que
        l'accès gratuit refuse}."""
        want = [m for m in metrics if m not in self.cm_refused]
        for _ in range(len(want) + 1):
            if not want:
                raise IngestError("CoinMetrics : toutes les mesures demandées sont refusées par l'accès gratuit", "blocked")
            try:
                r = self.cm.get("/v4/timeseries/asset-metrics", {"assets": asset, "metrics": ",".join(want), "frequency": "1d",
                                                                 "page_size": days, "paging_from": "end"}, ttl=3600)
            except IngestError as e:
                m = CM_REFUSED.search(str(e))
                if e.status in (400, 403) and m and m.group(1) in want:
                    want.remove(m.group(1))
                    self.cm_refused.append(m.group(1))
                    continue
                raise
            rows = []
            for x in need(r, "data"):
                row = {"t": to_ms(x["time"])}
                for m in want:
                    if x.get(m) is not None:
                        row[m] = D(x[m])
                rows.append(row)
            rows.sort(key=lambda z: z["t"])
            return {"rows": rows, "metrics": want, "refused": list(self.cm_refused)}
        raise IngestError("CoinMetrics : réponse inattendue", "format")

    # ---------- blockchain.info ----------
    def blockchain_stats(self) -> dict:
        r = self.bc.get("/stats", ttl=600, retries=2)
        return {"t": to_ms(int(D(need(r, "timestamp")))), "difficulty": D(need(r, "difficulty")),
                "hashrateEH": CTX.divide(CTX.multiply(D(need(r, "hash_rate")), Decimal(10) ** 9), EH),       # publié en gigahachages par seconde
                "blocksTotal": int(need(r, "n_blocks_total")), "minutesBetweenBlocks": D(need(r, "minutes_between_blocks"))}

    # ---------- ensemble ----------
    def snapshot(self) -> dict:
        out = {}
        for name, fn in (("fees", self.fees), ("mempool", self.mempool), ("difficulty", self.difficulty), ("hashrate", self.hashrate),
                         ("tip", self.tip), ("coinmetrics", self.coinmetrics), ("blockchain", self.blockchain_stats)):
            try:
                out[name] = fn()
            except (IngestError, KeyError, TypeError, ValueError, ArithmeticError) as e:
                out[name] = {"error": str(e)[:160]}
        hr, bc = out.get("hashrate"), out.get("blockchain")
        if isinstance(hr, dict) and isinstance(bc, dict) and "difficulty" in hr and "difficulty" in bc:
            a, b = hr["difficulty"], bc["difficulty"]
            out["crossCheck"] = {"difficultyGapPct": CTX.multiply(CTX.divide(abs(CTX.subtract(a, b)), a), Decimal(100)) if a > 0 else None}
        return out
