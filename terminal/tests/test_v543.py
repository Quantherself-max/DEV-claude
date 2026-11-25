"""V54.3 : l'onglet Quant restait vide chez qui utilise un bloqueur de publicités. Cause : la liste anti-pistage EasyPrivacy (active par
défaut dans uBlock Origin, Brave, AdGuard, Ghostery…) contient la règle générique « /quant.js », écrite pour le script de Quantcast ; elle
bloquait le fichier de la page Quant, qui portait ce nom. Le fichier s'appelle désormais qtab.js.

Ce test garde les noms des fichiers de la page hors des noms de fichiers que ces listes bloquent partout. La liste ci-dessous reprend les
règles « /mot.js » (un seul mot, 2 à 12 lettres) d'EasyPrivacy, d'EasyList et des filtres AdGuard (anti-pistage et de base), relevées le
25 novembre 2026 ; toutes les adresses du terminal (fichiers de la page et adresses /api) ont été vérifiées ce jour-là contre ces listes
complètes et celles d'uBlock Origin : seule « /quant.js » bloquait."""
from __future__ import annotations
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")

BLOCKED = set("""
    acclog acctag aclib adanalytics adasync adcount adengine admanager admgr admiral admitad adocean adrecover adscroll adslide adstat adstrack
    adtools adutil advstats analyse analyticsjs apopwin apstag aptrk astrack astracker atapixel atatus atrk autotrack awstats aztracker banalytics
    baynote bcsensor beacon bizo blogcounter bloomreach bluekai boomerang boomr bottomads bpsma brightedge bstat buysellads bypassma caixinlog cedexis
    certifica chartbeat cklog clickcount clickctrl clickheat clicklog clickm clickscript clickstream clicktag clicktale clicktracker clicky cnstats
    cnt cnvtr confiant contentiq convertro coradiant countertab countly crypta dataunlocker diffuser divolte doctracking drwebstat dspixel dtrack
    dwanalytics eatms ecanalytics edata edmonds efxanalytics eloqua elqcfg elqfcs elqidg elqimg elqscr emstrack eroclick estat estatistica eulerian
    eventtracker evercookie evergage exactag exitpop exitpopup exittracker ezytrack fbanalytics fbevents fbpixel flipptag floatingad floatingads
    gaaddons gainit ganalytics gapro gascript gatag gatc gatrack gatracking gemius geocc getbglog getclicky getintent googleana googletag googletrack
    gosquared gpt grgfbigo gtag gtm hawk hawkeye hawklinks histats hitbox hitslink hmapxy honeybadger hoverad indextools instantpage instart
    itgdtracksdk jscounter jspopunder kameleoon keywee kissmetrics kontera krux leadtag leftad linkinformer linkpulse linktrack linktracker
    linktracking livestats localga locotrack logclick logcollect logstat logview magpie mediametrie mendelstats metricool microad minescripts mmclient
    mmcore moksa monetate monitus monsido mormont mpixel mpulse mtc nativeads nativendo neilson netmining netresults newrelic nielsen nlogger nnamdnas
    ntpagetag obtp odoscope omniunih onestat opdc openpixel opinionlab outbrain pageear pageview parsely pepperjam perfmetrics pgout phpmyvisites
    piwikapi pixeltag pixeltracker plausible plista pogoadkit pomegranate popu popupads pphlogger ppms printpixel printtracker ptrack publishertag
    pubtag pulsario pvcount pvcounter pvlog pvmax pvnoju pxtrack qapcore qlitics quant quantcast realytics referrer reftracker resxclsa resxclsx
    revinit rightad rivraddon rmntracking rntracking roiengine roitrack rollbar rrweb rtd rtoaster rwtag salog satismeter segmentify segmentio
    sessioncam sgtracker showbanner showcounter sidead sideads sitecatalist sitecatalyst sitecrm sitestat sitetrek sliderad smarttag snowplow
    softclick solarcode somni sophus sourcepoint spymonitor sranalytics statcounter statsadvance statscript stattag stickyad stracking supercookie
    swatag taboola tailtarget targetpushad tghr thermostat thetracker thixel tongji toplytics trackga trackjs trafic trbo triggertag trkga twiga tynt
    umami updatestats urchin userfly usertracking uthnafrwy utiqloader utracker vecapture vglnk vidtrack visistat visitcounter visitinfo vissense
    vppdzdrw webdig webmr webstat webstats webtag webtrack webtraffic webtraxs webtrends webxmr wmxtracker woopra wreport writelog wtbase wtid wtinit
    wxhawkeye wysistat xgemius xiti xtclick xtclicks xtcore xtroi yastat ystat zaius zanox zhugeio ztracker
""".split())


class BlockerSafeNamesTest(unittest.TestCase):
    def test_list_is_meaningful(self):
        self.assertIn("quant", BLOCKED)                                           # la règle qui a causé la panne
        self.assertGreater(len(BLOCKED), 300)

    def test_no_page_file_has_a_blocked_name(self):
        for f in WEB.rglob("*"):
            if f.is_file():
                self.assertNotIn(f.stem.lower(), BLOCKED, f"{f.name} : nom bloqué par les listes anti-pistage")
        for src in re.findall(r'<script src="([^"]+)"', read("index.html")):
            self.assertNotIn(Path(src).stem.lower(), BLOCKED, src)

    def test_quant_page_renamed(self):
        self.assertFalse((WEB / "quant.js").exists())
        self.assertIn('<script src="qtab.js"></script>', read("index.html"))
        self.assertNotIn('<script src="quant.js">', read("index.html"))
        app = read("app.js")
        self.assertIn("['QUANTV', 'qtab.js']", app)
        self.assertIn("modMissing('Quant', 'qtab.js')", app)
        self.assertNotIn("'quant.js'", app)

    def test_diagnosis(self):
        app, html = read("app.js"), read("index.html")
        self.assertIn("load: true", html)                                          # fichier non reçu, distingué d'un fichier qui plante
        for s in ("async function probeFile(f)", "fetch(f + '?p=' + Date.now(), {cache: 'no-store'})", "fetch('/api/health', {cache: 'no-store'})",
                  "MOD_WHY[f] = await probeFile(f)", "désactive-la pour cette page", "new Map();"):
            self.assertIn(s, app, s)

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_syntax(self):
        for f in ("app.js", "qtab.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(WEB / f)]).returncode, 0, f)


if __name__ == "__main__":
    unittest.main()
