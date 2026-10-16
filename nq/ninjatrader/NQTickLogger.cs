#region Using declarations
using System;
using System.IO;
using System.Text;
using System.Globalization;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

// -----------------------------------------------------------------------------
// NQTickLogger — enregistreur de transactions pour le NQ Scalp Terminal.
//
// Ce qu'il fait : à chaque transaction (trade) reçue du flux de ta plateforme
// (le flux CQG que Lucid te fournit via NinjaTrader), il écrit UNE ligne dans un
// fichier CSV que le terminal lit en temps réel :
//
//     time,price,size,side,bid,ask
//     1760616000123,25011.25,2,B,25011.00,25011.25
//
//   time  : millisecondes depuis 1970 en UTC (sans ambiguïté de fuseau) ;
//   price : prix de la transaction ;
//   size  : quantité (contrats) ;
//   side  : B = acheteur agressif (exécuté à l'ask), S = vendeur agressif (au bid),
//           vide = indéterminé (le terminal retombe alors sur la règle du tick) ;
//   bid,ask : meilleures limites au moment du trade (le terminal peut en déduire
//           le côté lui-même si « side » est vide).
//
// Ce N'EST PAS un robot : il n'envoie AUCUN ordre, ne se connecte à rien, ne
// contourne rien. Il écoute le flux que NinjaTrader reçoit déjà et le recopie
// dans un fichier. C'est un usage en lecture seule, à confirmer avec Lucid.
//
// Installation : voir README du terminal, section « Brancher NinjaTrader ».
// En deux mots : copie ce fichier dans
//   Documents\NinjaTrader 8\bin\Custom\Indicators\
// puis dans NinjaTrader : New > NinjaScript Editor > Compile (F5). Ajoute ensuite
// l'indicateur « NQTickLogger » sur un graphique du contrat NQ en cours.
// Pointe NQ_CSV_PATH (réglage du terminal) sur le fichier écrit ici.
// -----------------------------------------------------------------------------

namespace NinjaTrader.NinjaScript.Indicators
{
	public class NQTickLogger : Indicator
	{
		private StreamWriter writer;
		private double lastBid = 0.0;
		private double lastAsk = 0.0;
		private long lineCount = 0;
		private readonly object gate = new object();
		private static readonly DateTime EpochUtc = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "Écrit chaque transaction (heure UTC ms, prix, taille, côté, bid/ask) dans un CSV lu par le NQ Scalp Terminal.";
				Name		= "NQTickLogger";
				Calculate	= Calculate.OnEachTick;
				IsOverlay	= true;
				DisplayInDataBox = false;
				PaintPriceMarkers = false;
				IsSuspendedWhileInactive = false;   // on veut les ticks même quand le graphique n'est pas au premier plan

				FilePath			= Path.Combine(
					Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
					"NQ-Terminal", "nq-ticks.csv");
				LogHistorical		= false;        // par défaut : seulement le temps réel (ne pas réécrire le passé à chaque démarrage)
				FlushEveryNLines	= 50;           // écrit sur le disque tous les N lignes (compromis sûreté / performance)
			}
			else if (State == State.Configure)
			{
				// un marché par instance : on s'abonne au flux de marché de la série du graphique
			}
			else if (State == State.Realtime)
			{
				OpenWriter();
			}
			else if (State == State.Terminated)
			{
				CloseWriter();
			}
		}

		private void OpenWriter()
		{
			lock (gate)
			{
				if (writer != null)
					return;
				try
				{
					string dir = Path.GetDirectoryName(FilePath);
					if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
						Directory.CreateDirectory(dir);
					bool isNew = !File.Exists(FilePath) || new FileInfo(FilePath).Length == 0;
					writer = new StreamWriter(new FileStream(FilePath, FileMode.Append, FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
					if (isNew)
						writer.WriteLine("time,price,size,side,bid,ask");
					writer.Flush();
					Print("NQTickLogger : écriture dans " + FilePath);
				}
				catch (Exception ex)
				{
					Print("NQTickLogger : impossible d'ouvrir le fichier (" + ex.Message + ")");
					writer = null;
				}
			}
		}

		private void CloseWriter()
		{
			lock (gate)
			{
				if (writer == null)
					return;
				try { writer.Flush(); writer.Dispose(); }
				catch (Exception) { }
				writer = null;
			}
		}

		// Reçoit CHAQUE mise à jour du flux de marché (trades, bid, ask), indépendamment des barres.
		protected override void OnMarketData(MarketDataEventArgs e)
		{
			if (e.MarketDataType == MarketDataType.Ask)
			{
				lastAsk = e.Price;
				return;
			}
			if (e.MarketDataType == MarketDataType.Bid)
			{
				lastBid = e.Price;
				return;
			}
			if (e.MarketDataType != MarketDataType.Last)
				return;
			if (!LogHistorical && State != State.Realtime)      // on ignore le rejeu de l'historique au démarrage
				return;
			if (e.Volume <= 0 || e.Price <= 0)
				return;

			long ms = ToUnixMs(e.Time);
			// côté de l'agresseur : prix au-dessus (ou au) de l'ask = acheteur ; au-dessous (ou au) du bid = vendeur ; sinon on laisse vide
			string side = "";
			if (lastAsk > 0 && e.Price >= lastAsk)
				side = "B";
			else if (lastBid > 0 && e.Price <= lastBid)
				side = "S";

			string bidStr = lastBid > 0 ? lastBid.ToString(CultureInfo.InvariantCulture) : "";
			string askStr = lastAsk > 0 ? lastAsk.ToString(CultureInfo.InvariantCulture) : "";
			string line = ms.ToString(CultureInfo.InvariantCulture) + ","
				+ e.Price.ToString(CultureInfo.InvariantCulture) + ","
				+ e.Volume.ToString(CultureInfo.InvariantCulture) + ","
				+ side + "," + bidStr + "," + askStr;

			lock (gate)
			{
				if (writer == null)
					return;
				try
				{
					writer.WriteLine(line);
					lineCount++;
					if (FlushEveryNLines <= 1 || (lineCount % FlushEveryNLines) == 0)
						writer.Flush();
				}
				catch (Exception ex)
				{
					Print("NQTickLogger : erreur d'écriture (" + ex.Message + ")");
				}
			}
		}

		// Convertit l'heure d'une transaction (fournie par NinjaTrader dans le fuseau des heures de bourse de l'instrument)
		// en millisecondes UTC, sans aucune hypothèse « en dur » : on passe par le fuseau de la série.
		private long ToUnixMs(DateTime t)
		{
			try
			{
				TimeZoneInfo tz = (Bars != null && Bars.TradingHours != null) ? Bars.TradingHours.TimeZoneInfo : TimeZoneInfo.Local;
				DateTime utc;
				if (t.Kind == DateTimeKind.Utc)
					utc = t;
				else
					utc = TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(t, DateTimeKind.Unspecified), tz);
				return (long)(utc - EpochUtc).TotalMilliseconds;
			}
			catch (Exception)
			{
				return (long)(DateTime.UtcNow - EpochUtc).TotalMilliseconds;   // repli : heure de réception
			}
		}

		#region Properties
		[NinjaScriptProperty]
		[Display(Name = "Chemin du fichier", Description = "Fichier CSV écrit (à pointer avec NQ_CSV_PATH dans le terminal).", Order = 1, GroupName = "NQ Terminal")]
		public string FilePath { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Inclure l'historique", Description = "Si activé, écrit aussi les transactions rejouées au démarrage (sinon temps réel seulement).", Order = 2, GroupName = "NQ Terminal")]
		public bool LogHistorical { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Écrire sur le disque toutes les N lignes", Description = "1 = à chaque transaction (plus sûr, plus lent).", Order = 3, GroupName = "NQ Terminal")]
		public int FlushEveryNLines { get; set; }
		#endregion
	}
}
