# -*- coding: utf-8 -*-
# Dedicated cache for the widget "dubbed content" filter (see modules.settings.dub_filter_*).
#
# Stores, per (country, media_type, tmdb_id), a single boolean: does a localised release exist in that
# country (streaming via TMDb/JustWatch, OR home video via blu-ray.com). Once known, the filter applies
# instantly with zero network on subsequent builds.
#
# ASYMMETRIC TTL (the key design point):
#  - AVAILABLE (True): PERMANENTE. Cio' che il verdetto accerta non e' dove il titolo si trova ora, ma che
#    una traccia italiana ESISTA: se un film e' stato su una piattaforma italiana o e' uscito in home
#    video, doppiato lo e', e lo restera' anche quando sparira' dal catalogo. Fen Light non riproduce da
#    quelle piattaforme comunque. Era 180 giorni (valore originale dell'addon), cioe' ~1078 ricontrolli
#    di una domanda la cui risposta non puo' cambiare.
#  - UNAVAILABLE (False): a recent title may still get a release later, so cache it briefly and re-check.
#
# THREE-STATE reads: get_availability returns True/False for a live cache hit, or None for a miss/expired
# entry (the caller must then look it up). BaseCache.get already returns the stored bool on a hit and None
# on miss/expiry, so a cached False is distinguishable from a miss. Inconclusive lookups (network errors)
# must NOT be cached, so the next build retries them.
from time import localtime as _localtime
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

GET_ALL = 'SELECT id FROM dubcache'
DELETE_ALL = 'DELETE FROM dubcache'
CLEAN = 'DELETE FROM dubcache WHERE CAST(expires AS INT) <= ?'

class DubCache(BaseCache):
	def __init__(self):
		BaseCache.__init__(self, 'dub_db', 'dubcache')

	def _key(self, country, media_type, tmdb_id):
		return 'dub_%s_%s_%s' % (country, media_type, tmdb_id)

	def get_availability(self, country, media_type, tmdb_id):
		# True/False on a live cache hit, None on miss/expired.
		return self.get(self._key(country, media_type, tmdb_id))

	def set_availability(self, country, media_type, tmdb_id, available, year=None):
		expiration = EXPIRY_AVAILABLE if available else unavailable_expiry(year)
		self.set(self._key(country, media_type, tmdb_id), bool(available), expiration)

	# --- verdetto del solo STREAMING, separato da quello complessivo ------------------------------
	# Il verdetto del filtro e' 'streaming OPPURE home video', quindi un "non e' su streaming" non
	# puo' essere scritto come indisponibilita': manca ancora la meta' blu-ray. Va pero' ricordato lo
	# stesso, perche' e' l'informazione che i metadati freschi ci regalano (append_to_response
	# watch/providers) e che altrimenti ricompreremmo con una richiesta a parte.
	#   True  -> e' su streaming: il verdetto complessivo e' gia' deciso, si scrive anche quello
	#   False -> NON e' su streaming: si salta la chiamata e si va dritti a blu-ray.com
	#   None  -> non lo sappiamo
	def _skey(self, country, media_type, tmdb_id):
		return 'dubs_%s_%s_%s' % (country, media_type, tmdb_id)

	def get_streaming(self, country, media_type, tmdb_id):
		return self.get(self._skey(country, media_type, tmdb_id))

	def set_streaming(self, country, media_type, tmdb_id, available, year=None):
		# Un 'e' su streaming' e' stabile quanto una disponibilita'; un 'non c'e'' invecchia come le
		# altre indisponibilita', quindi segue la stessa scala per eta'.
		expiration = EXPIRY_AVAILABLE if available else unavailable_expiry(year)
		self.set(self._skey(country, media_type, tmdb_id), bool(available), expiration)

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
