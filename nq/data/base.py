"""Interface d'une source de transactions (ticks) de marche.

Une source donne d'abord un HISTORIQUE (`history`) puis, a chaque appel de `poll`, les transactions arrivees depuis le precedent appel.
Chaque transaction porte, quand la bourse le fournit, le COTE DE L'AGRESSEUR (acheteur qui frappe l'ask / vendeur qui frappe le bid) : c'est ce
qui rend le delta et le CVD reels. Sans cote, le terminal l'estime (regle du tick) et l'affiche clairement."""
import time

from engine.bars import Tick


class DataError(Exception):
    """Erreur de donnees (fichier introuvable, format inattendu...). Le message est affiche tel quel dans le terminal."""


class Source:
    name = "base"
    label = "Source"
    simulated = False           # True : prix FICTIFS (affiche en orange dans le terminal)

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def history(self, now_ms: int):
        """Transactions deja passees (ordre chronologique), jusqu'a `now_ms`."""
        raise NotImplementedError

    def poll(self, now_ms: int) -> list:
        """Nouvelles transactions depuis le dernier appel (history compris)."""
        raise NotImplementedError

    def info(self) -> dict:
        return {"name": self.name, "label": self.label, "simulated": self.simulated}


__all__ = ["DataError", "Source", "Tick"]
