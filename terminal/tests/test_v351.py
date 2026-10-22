"""V35.1 : les onglets de la barre du Desk (d'origine et personnels) se déplacent et se retirent."""
from __future__ import annotations
import unittest
from pathlib import Path

from server import VERSION

WEB = Path(__file__).resolve().parent.parent / "web"


class TabBarTests(unittest.TestCase):
    DESK = (WEB / "desk.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")
    CSS = (WEB / "style.css").read_text(encoding="utf-8")

    def test_move_and_remove(self):
        for k in ("function moveTab(", "function hideTab(", "function restoreTab(", "function resetBar(", "function showTabMenu(",
                  "'dragstart'", "'drop'", "'contextmenu'", "data-urest", "data-ureset", "data-tm=\"left\"", "Garde au moins un onglet"):
            self.assertIn(k, self.DESK)
        self.assertIn("hiddenTabs().includes(w.layout)", self.DESK)            # un onglet retiré n'est jamais rouvert
        self.assertIn("tabOrder: st.tabOrder, tabHide: st.tabHide", self.APP)     # gardés avec les réglages
        self.assertIn("Array.isArray(p.tabOrder)", self.APP)
        self.assertIn("Desk.firstTab()", self.APP)
        self.assertIn("button.dropl", self.CSS)

    def test_version(self):
        self.assertGreaterEqual(float(VERSION), 35.1)


if __name__ == "__main__":
    unittest.main()
