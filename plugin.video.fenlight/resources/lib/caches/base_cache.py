# -*- coding: utf-8 -*-
# json NON si importa piu' qui (lotto 126). Serviva a due soli metodi -- BaseCache.get e
# BaseCache.set, cioe' la serializzazione degli oggetti in cache -- ma base_cache lo importa
# CHIUNQUE tocchi un database, comprese le azioni che fanno una sola DELETE. E json non viene solo:
# si tira dietro 're', e con lui enum, functools, collections, operator, copyreg, sre_* -- una
# quindicina di moduli. Misurato sulla stick: ~8 ms per modulo, cioe' un ottavo di secondo per una
# riga di codice che quell'azione non esegue mai.
import time
# _thread invece di threading (lotto 101): threading.local E' _thread._local -- lo stesso oggetto,
# threading.py lo importa da li'. _thread e' un modulo BUILTIN (compilato nell'interprete), quindi
# costa zero; threading e' un file .py che sul Mi Stick si legge in 27-129 ms e si trascina dietro
# _weakrefset (27-131 ms) e, primo ad arrivarci, functools/collections. base_cache lo importava per
# QUESTA SOLA RIGA, ed e' importato da ogni cache, quindi da ogni invocazione: nel log di
# riferimento le quattro build_movie_list pagavano 98/72/133/27 ms per un thread-local.
# _local e' il nome privato che threading stesso importa; il ripiego esiste solo per non legare
# il modulo a un dettaglio interno di CPython.
try: from _thread import _local as _ThreadLocal
except ImportError: from threading import local as _ThreadLocal
import sqlite3 as database
from modules import kodi_utils

kodi_refresh, sleep, path_join, translatePath, addon_profile = kodi_utils.kodi_refresh, kodi_utils.sleep, kodi_utils.path_join, kodi_utils.translatePath, kodi_utils.addon_profile
delete_file, get_property, set_property, clear_property = kodi_utils.delete_file, kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property
notification, confirm_dialog, ok_dialog, open_file, show_text = kodi_utils.notification, kodi_utils.confirm_dialog, kodi_utils.ok_dialog, kodi_utils.open_file, kodi_utils.show_text
path_exists, list_dirs, progress_dialog, make_directory = kodi_utils.path_exists, kodi_utils.list_dirs, kodi_utils.progress_dialog, kodi_utils.make_directory

userdata_path = addon_profile()
databases_path = path_join(userdata_path, 'databases/')
database_path_raw = path_join(userdata_path, 'databases')
navigator_db = translatePath(path_join(database_path_raw, 'navigator.db'))
watched_db = translatePath(path_join(database_path_raw, 'watched.db'))
favorites_db = translatePath(path_join(database_path_raw, 'favourites.db'))
trakt_db = translatePath(path_join(database_path_raw, 'traktcache.db'))
maincache_db = translatePath(path_join(database_path_raw, 'maincache.db'))
lists_db = translatePath(path_join(database_path_raw, 'lists.db'))
discover_db = translatePath(path_join(database_path_raw, 'discover.db'))
metacache_db = translatePath(path_join(database_path_raw, 'metacache.db'))
debridcache_db = translatePath(path_join(database_path_raw, 'debridcache.db'))
external_db = translatePath(path_join(database_path_raw, 'external.db'))
settings_db = translatePath(path_join(database_path_raw, 'settings.db'))
episode_groups_db = translatePath(path_join(database_path_raw, 'episode_groups.db'))
dub_db = translatePath(path_join(database_path_raw, 'dub.db'))
# LOTTO 201 -- misure delle riproduzioni, ingresso del wizard della banda. Database a se' e non una
# tabella dentro maincache: e' l'unico dato che NON e' una cache (non scade e non si rigenera
# leggendo di nuovo una API), e finirebbe cancellato dalle pulizie insieme al resto.
playback_db = translatePath(path_join(database_path_raw, 'playback.db'))

database_timeout = 20
current_dbs = ('navigator.db', 'watched.db', 'favourites.db', 'traktcache.db', 'maincache.db', 'lists.db',
				'discover.db', 'metacache.db', 'debridcache.db', 'external.db', 'settings.db', 'episode_groups.db', 'dub.db',
				'playback.db')   # <- senza questa riga remove_old_databases() lo cancella al primo avvio
database_locations = {
	'navigator_db': navigator_db, 'watched_db': watched_db, 'favorites_db': favorites_db, 'settings_db': settings_db,
	'trakt_db': trakt_db, 'maincache_db': maincache_db, 'metacache_db': metacache_db, 'debridcache_db': debridcache_db,
	'lists_db': lists_db, 'discover_db': discover_db, 'external_db': external_db, 'episode_groups_db': episode_groups_db,
	'dub_db': dub_db, 'playback_db': playback_db
}
integrity_check = {
	'settings_db': ('settings',),
	'navigator_db': ('navigator',),
	'watched_db': ('watched_status', 'progress'),
	'favorites_db': ('favourites',),
	'trakt_db': ('trakt_data', 'watched_status', 'progress'),
	'maincache_db': ('maincache',),
	'metacache_db': ('metadata', 'season_metadata', 'function_cache'),
	'lists_db': ('lists',),
	'discover_db': ('discover',),
	'debridcache_db': ('debrid_data', 'pack_files'),
	'external_db': ('results_data',),
	'episode_groups_db': ('groups_data',),
	'dub_db': ('dubcache',),
	'playback_db': ('playback_stats', 'sorgenti_bocciate')
}
# LOTTO 133 -- lo stato di sincronizzazione e' una COLONNA, non piu' una deduzione.
#   sync_state  'synced' | 'pending_put' | 'pending_delete'  (vedi caches/progress_sync)
#   misses      quante risposte di Trakt di fila hanno omesso una riga nostra non ancora pubblicata
# La definizione sta qui una volta sola: le tabelle `progress` sono due -- watched_db (indicatori
# locali, nessun remoto) e trakt_db (sincronizzata) -- ed erano due stringhe copiate a mano.
PROGRESS_CREATE = (
	'CREATE TABLE IF NOT EXISTS progress '
	'(db_type text not null, media_id text not null, season integer, episode integer, resume_point text, '
	'curr_time text, last_played text, resume_id integer, title text, '
	"sync_state text not null default 'synced', misses integer not null default 0, "
	'unique (db_type, media_id, season, episode))')

# LOTTO 235 -- IL LUCCHETTO DEL RINNOVO TRAKT E' UNA RIGA, NON UN OGGETTO DI MEMORIA.
# Gli interpreti di Kodi non condividono memoria: con reuselanguageinvoker=false ogni invocazione
# del plugin e' un interprete nuovo e il servizio e' un altro ancora, quindi un threading.Lock di
# modulo produce N lucchetti distinti e serializza zero. L'unico arbitro che tutti vedono e' questo
# file. Una riga sola, e la colonna `expires` E' la proprieta' del lucchetto: nel passato = libero,
# nel futuro = preso da qualcuno. La scadenza fa anche da recupero, perche' un processo che muore
# con il lucchetto in mano lo rilascia da solo invece di bloccare tutti gli altri per sempre.
# NON va aggiunta a integrity_check: li' una tabella mancante fa CANCELLARE il database, e
# settings.db contiene i token.
TRAKT_AUTH_LOCK_CREATE = (
	'CREATE TABLE IF NOT EXISTS trakt_auth_lock (id integer primary key check (id = 1), expires real not null default 0)',
	'INSERT OR IGNORE INTO trakt_auth_lock (id, expires) VALUES (1, 0)')

table_creators = {
	'navigator_db': (
		'CREATE TABLE IF NOT EXISTS navigator (list_name text, list_type text, list_contents text, unique (list_name, list_type))',),
	'watched_db': (
		'CREATE TABLE IF NOT EXISTS watched \
		(db_type text not null, media_id text not null, season integer, episode integer, last_played text, title text, unique (db_type, media_id, season, episode))',
		PROGRESS_CREATE,
		'CREATE TABLE IF NOT EXISTS watched_status (db_type text not null, media_id text not null, status text, unique (db_type, media_id))'),
	'favorites_db': (
		'CREATE TABLE IF NOT EXISTS favourites (db_type text not null, tmdb_id text not null, title text not null, unique (db_type, tmdb_id))',),
	'settings_db': (
		'CREATE TABLE IF NOT EXISTS settings (setting_id text not null unique, setting_type text, setting_default text, setting_value text)',) + TRAKT_AUTH_LOCK_CREATE,
	'trakt_db': (
		'CREATE TABLE IF NOT EXISTS trakt_data (id text unique, data text)',
		'CREATE TABLE IF NOT EXISTS watched \
		(db_type text not null, media_id text not null, season integer, episode integer, last_played text, title text, unique (db_type, media_id, season, episode))',
		PROGRESS_CREATE,
		'CREATE TABLE IF NOT EXISTS watched_status (db_type text not null, media_id text not null, status text, unique (db_type, media_id))'),
	'maincache_db': (
		'CREATE TABLE IF NOT EXISTS maincache (id text unique, data text, expires integer)',),
	'metacache_db': (
		'CREATE TABLE IF NOT EXISTS metadata (db_type text not null, tmdb_id text not null, imdb_id text, tvdb_id text, meta text, expires integer, unique (db_type, tmdb_id))',
		'CREATE TABLE IF NOT EXISTS season_metadata (tmdb_id text not null unique, meta text, expires integer)',
		'CREATE TABLE IF NOT EXISTS function_cache (string_id text not null unique, data text, expires integer)'),
	'debridcache_db': (
		'CREATE TABLE IF NOT EXISTS debrid_data (hash text not null, debrid text not null, cached text, expires integer, unique (hash, debrid))',
		# LOTTO 207 -- l'elenco dei file di un torrent. Non ha `expires` e non e' un errore:
		# l'infohash E' il contenuto, quindi la lista dei file non puo' cambiare. Sta accanto a
		# `debrid_data` ma ha vita opposta: quella scade a 24 h perche' l'ESSERE IN CACHE cambia,
		# questa non scade mai. Cresce a limite: ci pensa pack_cache.manutenzione().
		'CREATE TABLE IF NOT EXISTS pack_files (hash text primary key, files text, quando integer)',),
	'lists_db': (
		'CREATE TABLE IF NOT EXISTS lists (id text unique, data text, expires integer)',),
	'external_db': (
		'CREATE TABLE IF NOT EXISTS results_data (provider text not null, db_type text not null, tmdb_id text not null, title text, year integer, season text, episode text, results text, \
		expires integer, unique (provider, db_type, tmdb_id, title, year, season, episode))',),
	'discover_db': (
		'CREATE TABLE IF NOT EXISTS discover (id text not null unique, db_type text not null, data text)',),
	'episode_groups_db': (
		'CREATE TABLE IF NOT EXISTS groups_data (tmdb_id text not null unique, data text)',),
	'dub_db': (
		'CREATE TABLE IF NOT EXISTS dubcache (id text unique, data text, expires integer)',),
	# Una riga per riproduzione. Colonne separate e non un blob json: il wizard ci fa percentili e
	# medie, e su un blob dovrebbe rileggere e decodificare tutto ogni volta.
	# NULL dove la misura non c'e' (nessun salto, dimensione non ottenuta): il wizard deve poter
	# distinguere 'non misurato' da 'misurato zero', ed e' la distinzione che nei lotti 191-198 mi e'
	# costata due sonde.
	'playback_db': (
		'CREATE TABLE IF NOT EXISTS playback_stats ('
		'  id integer primary key autoincrement,'
		'  quando integer not null,'          # epoch
		'  cdn text,'                         # nexus-226.nord.tb-cdn.st
		'  dimensione integer,'               # byte veri dal Content-Range, NULL se non ottenuti
		'  durata integer,'                   # secondi, da Kodi
		'  bitrate real,'                     # Mbit/s = dimensione*8/durata
		'  salti integer,'
		'  portata_prima real,'               # Mbit/s sostenuti, surplus + bitrate
		'  portata_dopo real,'
		# LOTTO 212 -- COME e' stata presa la misura, non solo quanto vale. `portata_campioni` sono i
		# campioni del tratto piu' lungo rimasto sotto il tetto del buffer, `portata_punti` i punti
		# percentuali che quel tratto ha coperto (negativi se la cache CALAVA, cioe' se la linea non
		# ce la faceva: e' una misura, non un errore). Servono al wizard per pesare o scartare, e
		# servivano a me: davanti alla vecchia "sostenuta" che usciva 5,1%/s dieci volte su ventisette
		# non c'era modo di accorgersi che non era una misura ma la lunghezza della finestra.
		'  portata_campioni_prima integer,'
		'  portata_punti_prima integer,'
		# LOTTO 215 -- la coppia qui sopra descrive portata_PRIMA e basta: nata quando la misura era
		# una sola, non si rinomina per non perdere le righe gia' raccolte. Questa descrive
		# portata_DOPO, ed e' servita subito: Boogie Nights (10/09) non aveva nessun tratto valido
		# prima del salto e uno da 76 campioni dopo -- la seconda misura migliore dell'archivio, che
		# risultava con campioni NULL e il wizard avrebbe scartato come inaffidabile.
		'  portata_campioni_dopo integer,'
		'  portata_punti_dopo integer,'
		# LOTTO 217 -- quanti campioni del tratto vincente erano a cache ZERO. E' cio' che separa una
		# misura da un limite superiore: a zero il buffer non puo' scendere oltre, smette di
		# registrare il deficit e la pendenza legge "capacita' = bitrate" mentre la verita' e'
		# "capacita' MINORE del bitrate, di quanto non si sa". La regola che li separa e'
		# playback_stats.e_prova_di_capacita(), e sta li' e non qui perche' il wizard deve poterla
		# chiamare invece di reinventarla.
		'  portata_secchi_prima integer,'
		'  portata_secchi_dopo integer,'
		# LOTTO 219 -- la DURATA della finestra, in secondi, e non si ricava dai campioni: il passo
		# non e' costante (250 ms finche' il fitto e' acceso, poi 1 s), quindi 46 campioni valgono
		# 15,8 s e 77 ne valgono 48,3. Serve perche' le finestre corte leggono sistematicamente piu'
		# alto: 4,4 s -> 47,5 Mbit/s | 15,8 s -> 46,2 | 48,3 s -> 43,2 | 117 s -> 44,3, su quattro
		# riproduzioni indipendenti. Senza questa colonna il wizard non puo' distinguere una raffica
		# di apertura da una portata sostenuta, e mediarle insieme sovrastima la linea.
		'  portata_secondi_prima real,'
		'  portata_secondi_dopo real,'
		# LOTTO 221 -- quanto la finestra e' andata in una direzione sola (1,0 monotona, ~0 andata e
		# ritorno). E' il numero su cui la regola decide, conservato per poterla verificare
		# dall'archivio invece che dai log -- come `portata_secchi` per la guardia sul pavimento.
		'  portata_direzione_prima real,'
		'  portata_direzione_dopo real,'
		'  cache_media_prima integer, cache_max_prima integer,'
		'  cache_media_dopo integer, cache_max_dopo integer,'
		# LOTTO 218 -- "a secco", non "a zero", e la soglia e' player.PAVIMENTO_CACHE. A zero esatto
		# questo numero usciva sei volte piu' piccolo del vero: su 28 Years Later (10/09) il buffer e'
		# stato a terra 42 secondi rimbalzando fra 0 e 1, e gli 1% spezzavano la sequenza -> 7.
		'  secondi_a_secco integer,'         # il piu' lungo tratto consecutivo col buffer vuoto
		'  campioni integer,'
		# LOTTO 202. Il guasto dell'08/09 non era di banda: 2,1 Mbit/s su cache piena, e nessuna delle
		# colonne qui sopra lo avrebbe distinto da una riproduzione riuscita. Il file era HEVC 10 bit
		# 1920x1456, e il decoder della stick dichiara max="1920x1088" (/vendor/etc/media_codecs.xml):
		# la misura che mancava era la forma del flusso, non la sua velocita'.
		'  larghezza integer, altezza integer,'
		'  codec text,'                        # hevc, h264, av1 ... da Player.GetProperties
		'  esito text,'                        # NULL = normale; 'mai_partito' / 'bloccato' = cambio sorgente
		# Identita' della sorgente. `nome` non serve alla banda: serve a poter riscegliere lo stesso
		# season pack o lo stesso gruppo di rilascio per gli episodi successivi.
		'  nome text,'
		# `dimensione_dichiarata` e' cio' su cui il filtro di results.line_speed decide, in GiB, ed e'
		# il terzo sospetto del conto (gli altri due: le unita' GiB/GB e il ripiego sulla durata).
		# Da sola pero' NON si legge: significa tre cose diverse a seconda di chi l'ha prodotta, e
		# provider+pacchetto sono le due colonne che la rendono interpretabile.
		#   cloud (tb_cloud, rd_cloud, ...)  byte veri del file / 1073741824      -> deve combaciare
		#   external, singolo                la taglia dell'indicizzatore         -> approssimata
		#   external, pacchetto              taglia del pacco / numero episodi    -> una STIMA, e per
		#                                    i provider fuori da correct_pack_sizes e' l'unica che c'e'
		'  dimensione_dichiarata real,'
		'  provider text,'
		'  pacchetto text,'
		# LOTTO 222 -- LA SONDA DELLA LINEA (modules/sonda_linea.py), presa PRIMA di questa
		# riproduzione mentre gli scraper lavoravano. E' l'altra meta' della coppia con cui si tara
		# il margine: `sonda_mbps` dice cosa la linea consegnava trenta secondi prima, `bitrate`
		# dice cosa il film chiedeva, e le colonne di cache qui sopra dicono se ha tenuto. Il
		# rapporto bitrate/sonda_mbps, ordinato su venti-trenta righe, separa le riproduzioni sane
		# dalle sofferenti: quel confine e' 1/MARGINE, ed e' l'unico numero che il wizard deve
		# imparare. Dopo, `line_speed = sonda / MARGINE` e questo archivio non serve piu' a nessuno.
		'  sonda_mbps real,'                # regime, cioe' il tratto dopo la salita del tcp
		'  sonda_lorda real,'               # rampa compresa: si tengono entrambe per vedere quanto pesa
		'  sonda_secondi real,'             # durata del tratto di regime
		'  sonda_ttfb integer,'             # ms fino al primo byte: latenza, NON banda
		'  sonda_byte integer,'
		# LOTTO 223 -- DA CHE PROFONDITA' e' stata letta, in byte. Non e' un dettaglio di diagnosi:
		# e' la variabile che il 10/09 ha fatto leggere 3,0 Mbit/s dove la linea ne faceva 46, sullo
		# stesso file e sullo stesso nodo di una sonda che al 20% ne aveva letti 37,5. Senza questa
		# colonna una riga presa in profondita' e una presa in testa sono indistinguibili in
		# archivio, e il margine si tarerebbe mescolandole.
		'  sonda_offset integer,'
		# LOTTO 226 -- QUANTA CPU C'ERA e QUANTA SE NE E' USATA. Sono le due colonne che rendono
		# leggibile una riga senza sapere quando e' stata scritta, come sonda_offset. Il rapporto
		# fra `sonda_cpu / sonda_secondi` e `sonda_quota` dice se la sonda ha misurato la linea o il
		# proprio tetto di decifratura: vicino a 1 il regime e' un MINIMO. Le tre righe del 10/09
		# con 4,18 / 26,0 / 8,01 Mbit/s su una linea da 45 avevano quota 0,10-0,25 e in archivio
		# erano indistinguibili da una misura buona.
		'  sonda_quota real,'              # frazione di un core disponibile, da un ciclo occupato
		'  sonda_cpu integer,'             # ms di cpu del thread spesi nella lettura
		# Eta' della misura all'avvio del film. Una sonda vale se e' fresca: questa colonna e' cio'
		# che permette di verificarlo invece di darlo per scontato.
		'  sonda_eta integer,'
		# Il nodo che ha risposto ALLA SONDA. `cdn` piu' in alto e' il nodo che ha servito il FILM:
		# quando i due differiscono, la sonda ha misurato un pezzo di rete diverso da quello che ha
		# riprodotto, ed e' proprio l'obiezione con cui e' morta la sonda dei lotti 191-195. Due
		# colonne separate perche' la domanda si possa porre ai dati.
		'  sonda_cdn text,'
		# Il link risolto di QUESTA riproduzione: e' il bersaglio della PROSSIMA sonda. Sta qui e non
		# in un'impostazione perche' deve sopravvivere allo spegnimento e perche' va letto insieme a
		# `dimensione`, che e' cio' che decide da che offset leggere.
		'  link text)',
		# LISTA NERA -- tabella A PARTE, e la separazione e' il punto. playback_stats e' una finestra
		# scorrevole di 50 righe che si pota a ogni scrittura: una bocciatura messa li' sparirebbe
		# dopo cinquanta riproduzioni, cioe' proprio quando comincia a servire. Stesso database --
		# resta lo storico delle riproduzioni -- ma senza potatura.
		'CREATE TABLE IF NOT EXISTS sorgenti_bocciate ('
		'  chiave text primary key,'         # provider|nome: il link risolto cambia a ogni giro, il nome no
		'  nome text, provider text,'
		'  quando integer,'
		'  motivo text,'                     # mai_partito / bloccato
		'  volte integer)')
}

media_prop = 'fenlight.%s'
BASE_GET = 'SELECT expires, data FROM %s WHERE id = ?'
BASE_SET = 'INSERT OR REPLACE INTO %s(id, data, expires) VALUES (?, ?, ?)'
BASE_DELETE = 'DELETE FROM %s WHERE id = ?'

# Thread-local storage for per-thread connection pooling.
# Each thread maintains its own open connections, avoiding the overhead of
# opening/closing a connection on every cache read or write.
_local = _ThreadLocal()

def connect_database(database_name):
	if not hasattr(_local, 'connections'):
		_local.connections = {}
	conn = _local.connections.get(database_name)
	if conn is None:
		conn = database.connect(
			database_locations[database_name],
			timeout=database_timeout,
			isolation_level=None,  # autocommit
			check_same_thread=False
		)
		# WAL mode: allows concurrent readers while writing, and is crash-safe.
		# NORMAL synchronous: no fsync on every commit, but safe at WAL checkpoints.
		conn.execute('PRAGMA journal_mode = WAL')
		conn.execute('PRAGMA synchronous = NORMAL')
		_local.connections[database_name] = conn
	return conn

def checkpoint_database(database_name):
	"""Forza su disco cio' che e' appena stato scritto.

	In WAL con synchronous = NORMAL un commit sopravvive alla morte del processo ma non a un riavvio
	duro, e su queste macchine i riavvii duri capitano (watchdog_reboot). Si usa per il solo dato che
	non si puo' riottenere: il refresh token di Trakt, che nell'istante in cui ci arriva e' gia' stato
	ruotato dalla loro parte -- perderlo qui significa perdere l'autenticazione, non una cache.
	"""
	try: connect_database(database_name).execute('PRAGMA wal_checkpoint(FULL)')
	except Exception as e: kodi_utils.logger('Fen Light', 'checkpoint di %s fallito: %s' % (database_name, e))

def get_timestamp(offset=0):
	# offset is in hours
	return int(time.time()) + (offset * 3600)

def make_database(database_name):
	dbcon = connect_database(database_name)
	for command in table_creators[database_name]:
		dbcon.execute(command)

def make_databases():
	if not path_exists(databases_path):
		make_directory(databases_path)
	for database_name in database_locations:
		dbcon = connect_database(database_name)
		for command in table_creators[database_name]:
			dbcon.execute(command)
	migrate_progress_schema()
	migrate_playback_schema()

def migrate_progress_schema():
	"""Porta la tabella `progress` allo schema del lotto 133. Gira una volta per sessione.

	Due tabelle, due trattamenti diversi, e la differenza NON e' un dettaglio:

	  trakt_db    e' una copia di Trakt. Si puo' buttare e rifare, ed e' la strada piu' pulita:
	              nessuna riga vecchia si porta dietro uno stato inventato a posteriori.
	  watched_db  sono gli indicatori LOCALI: non esiste nessun remoto da cui ricostruirli. Buttarla
	              distruggerebbe l'avanzamento dell'utente senza possibilita' di recupero, quindi qui
	              si aggiungono le colonne e basta. Le righe esistenti nascono 'synced', che per un
	              database senza remoto e' l'unico stato sensato.

	Dopo aver svuotato trakt_db si cancella anche il segnalibro delle attivita': senza, la prima
	sincronizzazione direbbe 'nessuna modifica' e lascerebbe 'continua a guardare' vuoto fino al
	primo cambiamento su Trakt. Cancellandolo, il giro successivo riscarica tutto.
	"""
	for database_name, ricostruibile in (('trakt_db', True), ('watched_db', False)):
		try:
			dbcon = connect_database(database_name)
			cols = {r[1] for r in dbcon.execute('PRAGMA table_info(progress)')}
			if not cols or 'sync_state' in cols: continue
			if ricostruibile:
				dbcon.execute('DROP TABLE progress')
				dbcon.execute(PROGRESS_CREATE)
				dbcon.execute("DELETE FROM trakt_data WHERE id = 'trakt_get_activity'")
			else:
				dbcon.execute("ALTER TABLE progress ADD COLUMN sync_state text not null default 'synced'")
				dbcon.execute('ALTER TABLE progress ADD COLUMN misses integer not null default 0')
			kodi_utils.logger('Fen Light', 'progress: schema del lotto 133 applicato a %s (%s)'
					% (database_name, 'tabella rifatta' if ricostruibile else 'colonne aggiunte'))
		except Exception as e:
			kodi_utils.logger('Fen Light', 'progress: migrazione di %s FALLITA: %s' % (database_name, e))

def migrate_playback_schema():
	"""Se lo schema di `playback_stats` non e' quello atteso, la tabella si RIFA' da zero.

	LOTTO 218 -- niente piu' migrazioni incrementali, e la ragione e' che siamo in taratura. Fino
	al lotto 217 ogni cambiamento aggiungeva colonne e teneva le righe vecchie, e il risultato erano
	diciassette righe di quattro annate diverse: portate calcolate includendo il pavimento accanto ad
	altre che lo escludevano, colonne di peso che descrivevano solo la misura `prima`, un
	`secondi_a_zero` contato su una soglia poi cambiata. Un archivio cosi' non si puo' leggere --
	ogni riga andrebbe interpretata sapendo quando e' stata scritta -- e le statistiche che ci si
	fanno sopra non significano niente.

	Finche' il wizard non esiste, il valore di una riga vecchia e' molto minore del costo di dover
	ricordare come veniva prodotta. Si butta e si rifa' la raccolta: costa qualche riproduzione.

	`sorgenti_bocciate` NON si tocca: e' un'altra tabella e un altro tipo di dato -- cancellarla
	farebbe ricomparire sorgenti gia' dimostrate rotte, che non e' una misura da rifare ma una
	conoscenza da perdere.
	"""
	try:
		dbcon = connect_database('playback_db')
		# senza `re`: base_cache e' un modulo sensibile al costo di import (lotto 126) e una regex
		# non vale un modulo in piu' per leggere una lista di nomi separati da virgole.
		_sql = table_creators['playback_db'][0]
		_atteso = [_c.strip().split()[0]
				   for _c in _sql[_sql.index('(') + 1:_sql.rindex(')')].split(',')]
		_ora = [r[1] for r in dbcon.execute('PRAGMA table_info(playback_stats)')]
		if not _ora or _ora == _atteso: return
		_quante = dbcon.execute('SELECT COUNT(*) FROM playback_stats').fetchone()[0]
		dbcon.execute('DROP TABLE playback_stats')
		dbcon.execute(table_creators['playback_db'][0])
		dbcon.commit()
		kodi_utils.logger('Fen Light', 'playback_stats: schema cambiato, tabella rifatta da zero '
						  '(%d misure buttate). Mancavano: %s | in piu\': %s'
						  % (_quante, ', '.join(_c for _c in _atteso if _c not in _ora) or 'niente',
							 ', '.join(_c for _c in _ora if _c not in _atteso) or 'niente'))
	except Exception as e:
		kodi_utils.logger('Fen Light', 'playback_stats: rifacimento FALLITO: %s' % e)

def remove_old_databases():
	try:
		files = list_dirs(databases_path)[1]
		for item in files:
			if item not in current_dbs:
				try: delete_file(databases_path + item)
				except: pass
	except: pass

def check_databases_integrity():
	def _process(database_name, tables):
		database_location = database_locations[database_name]
		try:
			dbcon = database.connect(database_location)
			for db_table in tables:
				dbcon.execute(command_base % db_table)
		except:
			database_errors.append(database_name)
			if path_exists(database_location):
				try: dbcon.close()
				except: pass
				# Evict stale connection from thread-local pool so the rebuilt DB gets a fresh one.
				if hasattr(_local, 'connections'):
					_local.connections.pop(database_name, None)
				delete_file(database_location)
	command_base = 'SELECT * FROM %s LIMIT 1'
	database_errors = []
	for database_name, tables in integrity_check.items():
		_process(database_name, tables)
	make_databases()
	if database_errors:
		ok_dialog(text='[B]Following Databases Rebuilt:[/B][CR][CR]%s' % ', '.join(database_errors))
	else:
		notification('No Corrupt or Missing Databases', time=3000)

def get_size(file):
	with open_file(file) as f:
		s = f.size()
	return s

def clean_databases():
	from caches.external_cache import external_cache
	from caches.main_cache import main_cache
	from caches.lists_cache import lists_cache
	from caches.meta_cache import meta_cache
	from caches.debrid_cache import debrid_cache
	clean_cache_list = (
		('EXTERNAL CACHE', external_cache, external_db),
		('MAIN CACHE', main_cache, maincache_db),
		('LISTS CACHE', lists_cache, lists_db),
		('META CACHE', meta_cache, metacache_db),
		('DEBRID CACHE', debrid_cache, debridcache_db)
	)
	results = []
	for name, function, location in clean_cache_list:
		start_bytes = get_size(location)
		result = function.clean_database()
		if not result:
			results.append('[B]%s: [COLOR red]FAILED[/COLOR][/B]' % name)
			continue
		end_bytes = get_size(location)
		saved_bytes = start_bytes - end_bytes
		results.append('[B]%s: [COLOR green]SUCCESS[/COLOR][/B][CR]    [B]Saved Size: %sMB[/B][CR]    Start Size/End Size: %sMB/%sMB' % (
			name,
			round(float(saved_bytes) / 1024 / 1024, 2),
			round(float(start_bytes) / 1024 / 1024, 2),
			round(float(end_bytes) / 1024 / 1024, 2)
		))
	return show_text('Cache Clean Results', text='[CR]----------------------------------[CR]'.join(results), font_size='large')

def clear_cache(cache_type, silent=False, clear_hashes=True):
	"""LOTTO 205 -- `clear_hashes` esiste per il rescrape di UN titolo.

	La cache degli hash (hash -> e' gia' in cache sul debrid?) NON e' per titolo: e' una tabella di
	consultazione globale, e svuotarla per rifare la ricerca di un episodio costava, misurato l'08/09,
	`TB_check: hash_list: 110, already_cached: 0, unchecked: 110` -- centodieci hash richiesti da capo
	alla rete per un titolo solo, piu' la stessa perdita per ogni altro titolo mai cercato.
	Non serviva nemmeno a tenerla fresca: `debrid_cache` scrive `expires = get_timestamp(24)`, quindi
	si rinnova da sola ogni ventiquattro ore. Chi vuole ricontrollare gli hash di QUESTO titolo usa la
	bandiera `fs_rescrape`, che salta la consultazione senza cancellare niente a nessuno.
	"""
	def _confirm(): return silent or confirm_dialog()
	success = True
	if cache_type == 'meta':
		from caches.meta_cache import delete_meta_cache
		success = delete_meta_cache(silent=silent)
	elif cache_type == 'internal_scrapers':
		if not _confirm(): return
		from apis import easynews_api
		results = [easynews_api.clear_media_results_database()]
		for item in ('pm_cloud', 'rd_cloud', 'ad_cloud', 'oc_cloud', 'ed_cloud', 'tb_cloud', 'folders'):
			results.append(clear_cache(item, silent=True, clear_hashes=clear_hashes))
		success = False not in results
	elif cache_type == 'external_scrapers':
		from caches.external_cache import external_cache
		from caches.debrid_cache import debrid_cache
		success = False not in [external_cache.clear_cache(), debrid_cache.clear_cache()]
	elif cache_type == 'trakt':
		from caches.trakt_cache import clear_all_trakt_cache_data
		success = clear_all_trakt_cache_data(silent=silent)
	elif cache_type == 'imdb':
		if not _confirm(): return
		from apis.imdb_api import clear_imdb_cache
		success = clear_imdb_cache()
	elif cache_type == 'pm_cloud':
		if not _confirm(): return
		from apis.premiumize_api import PremiumizeAPI
		success = PremiumizeAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'rd_cloud':
		if not _confirm(): return
		from apis.real_debrid_api import RealDebridAPI
		success = RealDebridAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'ad_cloud':
		if not _confirm(): return
		from apis.alldebrid_api import AllDebridAPI
		success = AllDebridAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'oc_cloud':
		if not _confirm(): return
		from apis.offcloud_api import OffcloudAPI
		success = OffcloudAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'ed_cloud':
		if not _confirm(): return
		from apis.easydebrid_api import EasyDebridAPI
		success = EasyDebridAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'tb_cloud':
		if not _confirm(): return
		from apis.torbox_api import TorBoxAPI
		success = TorBoxAPI().clear_cache(clear_hashes=clear_hashes)
	elif cache_type == 'folders':
		if not _confirm(): return
		from caches.main_cache import main_cache
		success = main_cache.delete_all_folderscrapers()
	elif cache_type == 'list':
		if not _confirm(): return
		from caches.lists_cache import lists_cache
		success = lists_cache.delete_all_lists()
	elif cache_type == 'dub':
		if not _confirm(): return
		from caches.dub_cache import dub_cache
		success = dub_cache.delete_all()
	else:  # main
		if not _confirm(): return
		from caches.main_cache import main_cache
		success = main_cache.delete_all()
	if not silent and success:
		notification('Success')
	return success

def clear_all_cache():
	if not confirm_dialog(): return
	progressDialog = progress_dialog()
	line = 'Clearing....[CR]%s'
	caches = (
		('meta', 'Meta Cache'), ('internal_scrapers', 'Internal Scrapers Cache'),
		('external_scrapers', 'External Scrapers Cache'), ('trakt', 'Trakt Cache'),
		('imdb', 'IMDb Cache'), ('list', 'List Data Cache'), ('dub', 'Dubbed Filter Cache'), ('main', 'Main Cache'),
		('pm_cloud', 'Premiumize Cloud'), ('rd_cloud', 'Real Debrid Cloud'),
		('ad_cloud', 'All Debrid Cloud'), ('oc_cloud', 'OffCloud Cloud'),
		('ed_cloud', 'Easy Debrid Cloud'), ('tb_cloud', 'TorBox Cloud')
	)
	for count, (cache_type, cache_name) in enumerate(caches, 1):
		try:
			progressDialog.update(line % cache_name, int(float(count) / float(len(caches)) * 100))
			clear_cache(cache_type, silent=True)
			sleep(100)
		except: pass
	progressDialog.close()
	sleep(100)
	ok_dialog(text='Success')

def refresh_cached_data(meta):
	from caches.meta_cache import meta_cache
	media_type, tmdb_id, imdb_id = meta['mediatype'], meta['tmdb_id'], meta['imdb_id']
	try: meta_cache.delete(media_type, 'tmdb_id', tmdb_id, meta)
	except: return notification('Error')
	from apis.imdb_api import refresh_imdb_meta_data
	refresh_imdb_meta_data(imdb_id)
	notification('Success')
	kodi_refresh(coalesce=False)

class BaseCache:
	def __init__(self, dbfile, table):
		self.table = table
		self.dbfile = dbfile

	def get(self, string):
		try:
			current_time = get_timestamp()
			dbcon = connect_database(self.dbfile)
			row = dbcon.execute(BASE_GET % self.table, (string,)).fetchone()
			if row:
				if row[0] > current_time:
					import json
					return json.loads(row[1])
				self.delete(string)
		except: pass
		return None

	def set(self, string, data, expiration=720):
		try:
			dbcon = connect_database(self.dbfile)
			expires = get_timestamp(expiration)
			import json
			dbcon.execute(BASE_SET % self.table, (string, json.dumps(data, ensure_ascii=False), int(expires)))
		except: pass

	def delete(self, string):
		try:
			dbcon = connect_database(self.dbfile)
			dbcon.execute(BASE_DELETE % self.table, (string,))
			self.delete_memory_cache(string)
		except: pass

	def delete_memory_cache(self, string):
		clear_property(media_prop % string)

	def manual_connect(self, dbfile):
		return connect_database(dbfile)