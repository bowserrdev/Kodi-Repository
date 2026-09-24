# -*- coding: utf-8 -*-
# La cache dei filtri "uscito" e "doppiato" (FILTRO-USCITA.md; la regola e' modules/uscita.py). Nata come cache del
# filtro doppiaggio "per paese", che il lotto 348 ha sostituito: le chiavi di allora (dub_, dubs_) le butta
# migra_verdetti alla revisione 2.
#
# Le chiavi, tutte con un verdetto che una volta noto applica il filtro senza rete:
#   rel_   uscito                       relt_  solo film: il "no" di TMDb, con la data annunciata
#   dubl_  doppiato in UNA lingua       tmdbw_ il riassunto della risposta TMDb che le regole leggono
#
# TTL ASIMMETRICO (il punto del disegno):
#  - SI' PERMANENTE. Cio' che il verdetto accerta non e' dove il titolo si trova ora, ma che una versione o una
#    traccia ESISTA: un titolo uscito resta uscito, un doppiaggio che c'e' stato c'e' ancora anche quando sparisce da
#    un catalogo. Fen Light non riproduce da quelle piattaforme comunque.
#  - NO A TEMPO, secondo l'eta' del titolo, e mai oltre il giorno dopo un'uscita gia' annunciata (scadenza_negativa).
#
# TRE STATI in lettura: vero/falso da una voce viva, None se manca o e' scaduta. Un esito inconcludente (rete) non si
# scrive mai: il giro dopo lo richiede.
from time import localtime as _localtime, mktime as _mktime, time as _time
from caches.base_cache import BaseCache, get_timestamp

# 100 anni invece di 'mai': la voce non scade in nessun orizzonte utile, ma resta un intero ordinario e
# clean_database (DELETE ... WHERE expires <= now) continua a funzionare come sempre, senza casi speciali.
EXPIRY_AVAILABLE = 24 * 365 * 100
# TTL del verdetto NEGATIVO, proporzionale all'eta' del titolo. Era 7 giorni per tutti, e la
# giustificazione ("un titolo recente potrebbe ancora uscire") vale solo per i titoli recenti.
# Misurato il 24/08 su dub.db della stick: 355 voci negative, di cui 322 con anno noto incrociando
# metacache.db --
#     0-1 anno 155 (48%) | 2 anni 5 (2%) | 3-5 anni 19 (6%) | 6-15 anni 48 (15%) | oltre 15: 95 (30%)
# -- cioe' META' dei ricontrolli settimanali riguardava titoli usciti da oltre due anni, e il 30% da
# oltre quindici. Un film del 2005 senza edizione italiana non ne avra' una la settimana prossima, e
# ogni ricontrollo e' il percorso CARO: non essendo su streaming paga TMDb piu' blu-ray.com.
EXPIRY_UNAVAILABLE = 24 * 7          # <= 1 anno: puo' ancora uscire, si ricontrolla spesso
EXPIRY_UNAVAILABLE_MID = 24 * 30     # 2 anni: uscita tardiva ancora possibile, ma rara
EXPIRY_UNAVAILABLE_OLD = 24 * 180    # oltre: come i disponibili, non cambiera'
UNAVAILABLE_RECENT_YEARS = 1
UNAVAILABLE_MID_YEARS = 2

def unavailable_expiry(year):
	# year = anno di uscita del titolo (int o stringa). Ignoto -> si tiene il comportamento prudente.
	if not year: return EXPIRY_UNAVAILABLE
	try: age = _localtime().tm_year - int(str(year)[:4])
	except: return EXPIRY_UNAVAILABLE
	if age <= UNAVAILABLE_RECENT_YEARS: return EXPIRY_UNAVAILABLE
	if age <= UNAVAILABLE_MID_YEARS: return EXPIRY_UNAVAILABLE_MID
	return EXPIRY_UNAVAILABLE_OLD

SCARTO_MEZZANOTTE = 60   # secondi

def scadenza_negativa(year, prossima=''):
	"""Ore di vita di un "non e' uscito" (lotto 344). La scala per eta', e in piu' un tetto: se TMDb ha gia' annunciato il
	giorno in cui il titolo uscira' (`prossima`, 'AAAA-MM-GG'), il "no" non puo' sopravvivergli. Scade alla mezzanotte
	LOCALE del giorno dopo, che e' anche il primo giorno in cui la regola conta quella data (modules/uscita.py): alla
	scadenza la risposta e' gia' cambiata. Coyote vs. Acme, 24/09: digitale USA il 29/09; con la sola scala il "no"
	sarebbe durato fino al 01/10."""
	ore = unavailable_expiry(year)
	if not prossima: return ore
	try:
		anno, mese, giorno = (int(x) for x in prossima[:10].split('-'))
		secondi = _mktime((anno, mese, giorno + 1, 0, 0, 0, 0, 0, -1)) - _time()   # mktime normalizza il 32 del mese
		# Un minuto DOPO la mezzanotte, non a mezzanotte: get_timestamp tronca i secondi, e un "no" scaduto alle
		# 23:59:59 verrebbe richiesto quando e' ancora il giorno prima, cioe' riscritto per un altro giro.
		return min(ore, (max(0, secondi) + SCARTO_MEZZANOTTE) / 3600.0)
	except Exception: return ore

GET_ALL = 'SELECT id FROM dubcache'
DELETE_ALL = 'DELETE FROM dubcache'
CLEAN = 'DELETE FROM dubcache WHERE CAST(expires AS INT) <= ?'

# LOTTO 340 -- quale regola ha scritto i verdetti che stanno nel database (PRAGMA user_version di dub.db).
# Quando la regola cambia in un modo che rende sbagliati dei verdetti gia' scritti, si alza il numero e
# migra_verdetti butta quelli e solo quelli, una volta.
#   1  blu-ray.com interrogato anche nel catalogo DVD. Si buttavano i soli "no" del filtro per paese.
#   2  LOTTO 348 -- il filtro per paese non c'e' piu': si buttano TUTTE le sue chiavi, anche i "si'". Erano scritti
#      con la regola "uscito nel paese", che fa passare i sottotitolati (Visitor Q, Il vero Oppenheimer), e le
#      regole nuove non le leggono. Le chiavi rel_/relt_ del lotto 344 restano: la loro regola non cambia.
#   3  LOTTO 349 -- un film senza parlato (muto, corto senza dialoghi) non ha niente da doppiare e passa il filtro
#      doppiaggio. I "no" del doppiato scritti prima potevano essere di film muti (L'uomo che ride, La danza degli
#      scheletri, visti sul Mac il 25/09): si buttano i "no" e si ricalcolano; i "si'" restano.
# Ogni revisione ha la sua cancellazione, e un database fermo a una revisione vecchia le fa tutte, in ordine.
# substr e non LIKE: in LIKE '_' e' un jolly, e 'dub_%' prenderebbe anche 'dubl_'.
REVISIONI = (
	(1, "DELETE FROM dubcache WHERE substr(id, 1, 4) = 'dub_' AND data = 'false'"),
	(2, "DELETE FROM dubcache WHERE substr(id, 1, 4) = 'dub_' OR substr(id, 1, 5) = 'dubs_'"),
	(3, "DELETE FROM dubcache WHERE substr(id, 1, 5) = 'dubl_' AND data = 'false'"),
)
VERDETTI_REV = REVISIONI[-1][0]

def migra_verdetti():
	"""Porta i verdetti di dub.db alla regola corrente. La chiama il servizio all'avvio, una volta per sessione.

	Deve girare PRIMA del preparatore, che e' il lettore di questi verdetti e parte subito, mentre
	make_databases aspetta la Home piena: messa li', la prima sessione dopo l'aggiornamento avrebbe scartato
	di nuovo, con i "no" vecchi, i titoli che questa migrazione esiste per recuperare. Sulle sessioni
	successive costa una CREATE IF NOT EXISTS e una lettura di PRAGMA.

	La cancellazione e il nuovo numero stanno nella stessa transazione: un'interruzione a meta' lascia il
	database alla revisione vecchia, e la sessione dopo rifa' tutto.
	"""
	from caches.base_cache import connect_database, make_database
	from modules.kodi_utils import logger
	try:
		make_database('dub_db')   # al primo avvio in assoluto la tabella non c'e' ancora
		dbcon = connect_database('dub_db')
		attuale = dbcon.execute('PRAGMA user_version').fetchone()[0]
		if attuale >= VERDETTI_REV: return
		dbcon.execute('BEGIN')
		try:
			tolti = sum(dbcon.execute(cancella).rowcount for revisione, cancella in REVISIONI if revisione > attuale)
			dbcon.execute('PRAGMA user_version = %d' % VERDETTI_REV)
			dbcon.execute('COMMIT')
		except Exception:
			dbcon.execute('ROLLBACK')
			raise
		logger('Fen Light', 'dub.db: verdetti portati alla revisione %d, %d verdetti vecchi buttati' % (VERDETTI_REV, tolti))
	except Exception as e:
		logger('Fen Light', 'dub.db: migrazione dei verdetti FALLITA: %s' % e)

class DubCache(BaseCache):
	def __init__(self):
		BaseCache.__init__(self, 'dub_db', 'dubcache')

	# --- LOTTO 344: filtro "uscito" (FILTRO-USCITA.md) --------------------------------------------------------------
	# Stessa tabella e stessa scala: un'uscita non si disfa, quindi il si' e' permanente; il no invecchia con
	# l'eta' del titolo. Due chiavi:
	#   rel_   il verdetto sull'uscita, completo
	#   relt_  solo i FILM: TMDb ha detto no (nessuna piattaforma, nessuna uscita digitale, disco o TV), resta
	#          da chiedere a blu-ray.com. E' cio' che la scheda appena scaricata regala, e che altrimenti si
	#          ricomprerebbe con una richiesta a parte. Per le serie il no di TMDb e' gia' il verdetto. Il valore
	#          e' la data d'uscita gia' annunciata ('' se nessuna): serve a far scadere anche il verdetto completo
	#          che blu-ray.com chiudera' dopo, senza richiedere TMDb.
	# Ogni "no" riceve `prossima`, la data annunciata: vedi scadenza_negativa.
	def get_released(self, media_type, tmdb_id):
		return self.get('rel_%s_%s' % (media_type, tmdb_id))

	def set_released(self, media_type, tmdb_id, released, year=None, prossima=''):
		expiration = EXPIRY_AVAILABLE if released else scadenza_negativa(year, prossima)
		self.set('rel_%s_%s' % (media_type, tmdb_id), bool(released), expiration)

	def get_released_tmdb(self, media_type, tmdb_id):
		"""None se TMDb non e' stato sentito; altrimenti ha detto no, e il valore e' la data annunciata ('' se nessuna)."""
		return self.get('relt_%s_%s' % (media_type, tmdb_id))

	def set_released_tmdb(self, media_type, tmdb_id, prossima='', year=None):
		self.set('relt_%s_%s' % (media_type, tmdb_id), prossima or '', scadenza_negativa(year, prossima))

	# --- LOTTO 347: filtro doppiaggio per LINGUA (FILTRO-USCITA.md, regole D0-D3) -----------------------------------
	#   dubl_  doppiato in QUELLA lingua. Per lingua e non per l'insieme scelto: chi aggiunge una lingua tiene i
	#          verdetti delle altre. Un si' e' permanente (una traccia che esiste non sparisce); un no invecchia.
	#   tmdbw_ il riassunto della risposta TMDb che le regole leggono: lingua originale e, per i paesi delle lingue,
	#          offerte si'/no, Netflix si'/no e il link della pagina "dove guardarlo". I provider cambiano: 7 giorni, e
	#          mai oltre il giorno dopo la prima uscita annunciata (revisione del 25/09). Il "no" del doppiato scade quel
	#          giorno per essere ricalcolato, e il ricalcolo legge le offerte da qui: un riassunto piu' vecchio direbbe
	#          ancora "nessuna offerta in Italia", JustWatch verrebbe saltato e il "no" si riscriverebbe per 7 giorni.
	def get_doppiato(self, lingua, media_type, tmdb_id):
		return self.get('dubl_%s_%s_%s' % (lingua, media_type, tmdb_id))

	def set_doppiato(self, lingua, media_type, tmdb_id, doppiato, year=None, prossima=''):
		# `prossima`: un'uscita gia' annunciata nei paesi della lingua (lotto 348), come per rel_.
		expiration = EXPIRY_AVAILABLE if doppiato else scadenza_negativa(year, prossima)
		self.set('dubl_%s_%s_%s' % (lingua, media_type, tmdb_id), bool(doppiato), expiration)

	def get_riassunto_tmdb(self, media_type, tmdb_id):
		return self.get('tmdbw_%s_%s' % (media_type, tmdb_id))

	def set_riassunto_tmdb(self, media_type, tmdb_id, riassunto):
		uscite = [g for g in (riassunto.get('uscite') or {}).values() if g]
		self.set('tmdbw_%s_%s' % (media_type, tmdb_id), riassunto, scadenza_negativa(None, min(uscite) if uscite else ''))

	def delete_all(self):
		try:
			dbcon = self.manual_connect('dub_db')
			for i in dbcon.execute(GET_ALL):
				self.delete_memory_cache(str(i[0]))
			dbcon.execute(DELETE_ALL)
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = self.manual_connect('dub_db')
			dbcon.execute(CLEAN, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

dub_cache = DubCache()
