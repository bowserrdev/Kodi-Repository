# -*- coding: utf-8 -*-
from modules.kodi_utils import external, mark_phase, parse_qsl
# from modules.kodi_utils import logger

def sys_exit_check(): return external()

def _timbra_query(params):
	"""La riga dichiara di quale ricerca sono i suoi elementi (kodi_utils.QUERY_PROP).

	E' tutto quel che resta di _text_search_start, che oltre a questo teneva in piedi un canale
	globale di proprieta' della finestra Home per dire all'hub "sto caricando" e "ho finito". Era uno
	stato per TIPO DI MEDIA, mentre le righe le configura l'utente e possono essere una o dieci, anche
	tutte dello stesso tipo. L'asse sbagliato, e da li' lo stesso difetto e' tornato due volte: il
	19/09 una riga che finiva parlava per tutte, il 21/09 "Nessun risultato" e' rimasto 1,73 s sopra
	una ricerca da sedici titoli. Adesso ogni riga porta il proprio stato nel primo elemento e quel
	canale non lo legge piu' nessuno.
	Il timbro invece resta, ed e' il perno: senza, una riga non e' attribuibile alla sua ricerca. Lo legge
	una sola espressione per riga, generata (Exp_Search_{id}_Risponde, lotto 419), e da li' la riga, la sua
	linguetta e la decisione dell'attesa. Vale anche per le ricostruzioni di paginazione, che riconsegnano
	la stessa query. Il segnaposto d'attesa lo porta anche lui, timbrato da _consegna_attesa.
	"""
	# La condizione e' la stessa dei due cancelli qui sotto, e prima non lo era: qui si accettavano i
	# tre valori ('true', 'combined', 'standard') mentre loro guardano solo se il parametro c'e'. Il
	# valore non lo legge piu' nessuno da quando il canale globale e' stato demolito (allo scope
	# serviva per sapere se le righe erano una o due), e di fatto ne viene emesso uno solo. Due
	# definizioni di "questa e' una costruzione dell'hub di ricerca" erano una in piu': un path con un
	# valore inatteso sarebbe passato dai cancelli e non dal timbro, e una riga senza timbro non si
	# mostra piu'.
	if not params.get('search_hub'): return
	query = params.get('query', '')
	if not query: return
	from modules.kodi_utils import timbra_primo_elemento, QUERY_PROP
	timbra_primo_elemento(QUERY_PROP, query)

def _chiudi_discover(params, azioni):
	"""Una ricerca testuale e Discover non stanno a schermo insieme: la riga Discover si mostra solo
	a casella vuota, quindi appena si cerca il suo path va via.

	LA CONDIZIONE E' LA CASELLA, NON QUESTA COSTRUZIONE, ed e' la correzione. Prima bastava che una
	costruzione di ricerca passasse di qui con una query nel path. Ma una costruzione in volo non dice
	niente su cosa c'e' a schermo ADESSO: _search_debounce_abort dorme 500 ms prima di lasciar
	passare, e in quei 500 ms l'utente puo' applicare i filtri. launch_discover svuota la casella,
	scrive il path e se ne va; l'invocazione si sveglia, trova la casella vuota, e una casella vuota
	non e' un sorpasso (regola di _live_supersedes: "vuoto" vuol dire "non lo so", e una costruzione
	legittima non si butta per un dubbio), quindi prosegue e cancella il path appena scritto. La riga
	Discover spariva subito dopo essere comparsa.
	Chiederlo alla casella toglie il caso invece di rilevarlo: se non c'e' testo non c'e' nessuna
	ricerca in corso, e niente da chiudere. Se la casella non e' leggibile (un'altra finestra in
	primo piano) si tace, che e' il verso prudente e lo stesso di tutti gli altri lettori.
	"""
	if params.get('action') not in azioni or not params.get('query'): return
	from modules import paginator
	if not paginator.query_viva(): return
	from xbmcgui import Window
	Window(10000).clearProperty('FenLight.Discover.ContentPath')

def _search_debounce_abort(sys, params, action_filtered):
	# Debounce gate for the live search hub, run BEFORE _timbra_query so a superseded keystroke's
	# build never touches the skin state nor builds anything. paginator.search_should_abort waits the
	# debounce window and compares this build's query against the live search-box text; if they differ
	# the user has moved on -> close the (now-irrelevant) directory empty and bail.
	if params.get('action') != action_filtered or not params.get('search_hub'): return False
	from modules import paginator
	from modules.kodi_utils import get_property, end_directory
	query = params.get('query', '')
	# PRIMA DI TUTTO, e senza attendere: la casella ha gia' lasciato questa query? Allora questa
	# costruzione e' un residuo, e non lo diventa di meno perche' il contenitore e' occupato.
	# Le esenzioni qui sotto rispondono alla domanda "e' un passo di paginazione?" guardando SE IL
	# CONTENITORE E' IN VOLO, che e' un'altra domanda: la prima costruzione di una query e' essa
	# stessa il lavoro in volo per quella chiave, quindi si auto-esentava. Nel log del 21/09
	# (shrek -> zodiaco) tre costruzioni sono passate da questa porta e sono arrivate in fondo --
	# chiamate TMDb comprese -- per query che l'utente aveva gia' lasciato:
	#     02:15:17.333  query="shr"  live="zodic"     1973 ms
	#     02:15:19.249  query="shr"  live="zodiaco"   3845 ms
	#     02:15:21.227  query="sh"   live="zodiaco"   5771 ms
	# 11,6 s di lavoro buttato, e i contenitori tenuti occupati per tutto quel tempo: nello stesso
	# intervallo il watcher ha mollato il riposizionamento di 1105.503 dopo i suoi 3 s di attesa.
	# Se ne accorgeva solo search_is_stale, in fondo, al momento di pubblicare.
	# Chi molla qui NON rilascia niente. La bandiera "in ricostruzione" del watcher (LOADING_PROP) la
	# azzera set_head, e a set_head ci arriva la costruzione della query VIVA, che per questo
	# contenitore esiste sempre: il testo e' cambiato, quindi il path e' cambiato, quindi Kodi ne ha
	# gia' chiesta un'altra. Rilasciarla qui vorrebbe dire cancellare la marca di QUELLA -- e' una
	# proprieta' per contenitore, non per costruzione -- e far credere al canale dei rinvii che non
	# ci sia niente in volo.
	if paginator.search_superseded(query):
		paginator.log('debounce: residuo di una query lasciata, chiudo subito query="%s"' % query)
	else:
		# Un passo di paginazione o un refresh globale ricostruiscono la STESSA query in posto: quelli
		# non si mettono mai in attesa, o l'infinite-scroll singhiozza. Arrivati qui sappiamo gia' che
		# la query e' quella viva, quindi l'esenzione vale solo per cio' per cui e' nata.
		key = paginator.widget_key(params)
		if paginator.is_loading(key) or get_property(paginator.PG_REFRESH_PROP) == 'true':
			return False
		if not paginator.search_should_abort(query): return False
	# NON SI CONSEGNA NIENTE, E NON SI DICHIARA NIENTE AL PONTE. Questa invocazione risponde a un path
	# che Kodi ha gia' abbandonato, che e' la definizione stessa di residuo: quando la cartella torna,
	# il contenitore ha gia' chiesto altro e quella risposta viene SCARTATA. L'unica cartella che Kodi
	# applica e' quella dell'ultimo path.
	# Dallo step 3 fino alla sonda delle 06:05 qui si consegnava STATO_ATTESA. Quella consegna non
	# arrivava mai a schermo, ma chiamava testa_vuota, che porta BUILT_PROP a 0: da li' in poi il ponte
	# diceva "contenitore vuoto" mentre a schermo c'erano quaranta elementi della ricerca precedente.
	# E la distruzione del plugin di allora (_svuota_prima, tolta col lotto 419: adesso decide la skin),
	# che agiva sull'invocazione del path VIVO, chiedeva proprio BUILT_PROP > 0 per sapere se c'era qualcosa
	# da togliere: trovava 0 e si fermava. Misurato con la sonda 3098:
	#     06:05:45.566  testa vuota 1105.502 stato=attesa query="bur"
	#     06:05:45.956  box=[burn]  502[vis=40 q=sea sel=Blu profondo]
	# Il ponte descrive quello che si VEDE. Chi sa che la propria cartella sara' scartata non lo tocca.
	try: end_directory(int(sys.argv[1]), cacheToDisc=False, segnaposto=None)
	except: pass
	return True

# LOTTO 418 -- le azioni dell'hub di ricerca: quella che arriva dalla skin e quella in cui il router la
# riscrive. Stanno qui perche' la riscrittura va fatta PRIMA di qualunque cancello che confronti
# l'impronta della lista: CTL_KEY_PROP e' stato registrato con l'azione riscritta, e confrontarlo con
# quella originale darebbe "lista diversa" a ogni passo di paginazione.
_AZIONI_HUB_RICERCA = {'build_movie_list': ('tmdb_movies_search', 'tmdb_movies_search_filtered'),
						'build_tvshow_list': ('tmdb_tv_search', 'tmdb_tv_search_filtered')}

def _cancelli_riga(sys, params, mode):
	"""I cancelli di una costruzione di RIGA (chi ha 'pgctl' nel path), in un punto solo e in quest'ordine.

	1. la riscrittura dell'azione dell'hub di ricerca, che l'impronta della lista presuppone;
	2. il debounce della ricerca: una query gia' lasciata non deve distruggere niente, o il ponte
	   direbbe "vuoto" mentre a schermo ci sono ancora i risultati (sonda 3098 delle 06:05, 21/09);
	3. l'attesa chiesta dalla skin (attesa=1, lotto 418 rivisto: lo schermo decide). Dopo la riscrittura,
	   perche' dichiara l'impronta; dopo il debounce, perche' dichiararla per una query gia' lasciata
	   azzererebbe il gettone di quella viva e consegnerebbe a un path abbandonato (code review del 29/09).
	Tutto il resto costruisce: attesa=0 (il path normale delle righe che possono cambiare lista) e le righe
	senza attesa nel path, cioe' Home e hub, la cui lista non cambia mai nello stesso contenitore (lotto 419,
	RIPOSIZIONAMENTO.md, *La decisione 8, rivista*). Fino al 419 qui c'era un quarto cancello, la distruzione
	decisa dal plugin (_svuota_prima): decideva dal ponte, cioe' da cio' che il plugin credeva consegnato, e
	una consegna a un path abbandonato Kodi la scarta senza dirlo. Ora decide sempre la skin, che vede lo schermo.
	Il controllo del gettone scaduto (_stale_token_abort) viene DOPO, nel ramo delle costruzioni: l'attesa
	azzera il gettone della lista vecchia, quindi farlo prima butterebbe un'invocazione (tests/test_418.py).
	Torna True se l'invocazione e' gia' stata servita.
	"""
	from modules.kodi_utils import ATTESA_PARAM
	coppia = _AZIONI_HUB_RICERCA.get(mode)
	if coppia and params.get('action') == coppia[0] and params.get('search_hub'): params['action'] = coppia[1]
	if coppia and _search_debounce_abort(sys, params, coppia[1]): return True
	return params.get(ATTESA_PARAM) == '1' and _consegna_attesa(sys, params)

def _consegna_attesa(sys, params):
	"""LO SCHERMO DECIDE (lotto 418, revisione del 29/09): la riga mostra un'altra lista e la skin chiede il
	solo segnaposto per quella che sta per costruire. RIPOSIZIONAMENTO.md, *Lo schermo decide*.

	La skin confronta il timbro del primo elemento a schermo (kodi_utils.LISTA_PROP) con la lista che la riga
	deve mostrare: se sono diversi e in testa c'e' un elemento vero (non un segnaposto), il path diventa quello
	con attesa=1. Qui si consegna il segnaposto e basta: quando e' a schermo la condizione della skin cade, il
	path torna quello normale e parte la costruzione, con il cursore sul primo. Kodi riseleziona l'elemento
	che aveva selezionato se la lista nuova ne ha uno con lo stesso path, e altrimenti tiene l'indice (PR.md
	§4): il segnaposto non e' mai nella lista nuova, e da un elemento solo l'indice e' il primo. Un titolo vero
	invece puo' esserci (lotto 419, "visitor q" -> "visitor": il cursore restava sul film di prima).
	NIENTE ORDINE DI RICARICA, ed e' il punto. La distruzione del plugin (_svuota_prima, tolta col lotto 419)
	decideva da cio' che il ponte diceva consegnato, e un segnaposto consegnato a un path gia' abbandonato Kodi
	lo scarta in silenzio: la costruzione dopo trovava il ponte "vuoto" e costruiva sopra la lista vecchia, col
	cursore dov'era (Firestick, 13:49 del 29/09). E la ricarica ordinata cambiava il path di una riga gia'
	passata ad altro, facendo buttare anche la consegna successiva. Qui il path lo cambia la skin, guardando
	lo schermo.

	LA RICERCA TESTUALE (lotto 419). Per le sue righe l'identita' della lista non e' il path ma la query: la
	skin chiede l'attesa se il primo elemento e' un titolo (non un segnaposto) e non porta la query scritta adesso
	(Exp_Search_{id}_Attesa). Il giro lo chiude il segnaposto stesso (con lui in testa, Attesa cade); il timbro serve perche' ogni
	consegna dica di quale lista e' (R1), segnaposto compresi: i lettori di "la riga risponde" (il pannello
	informazioni, la riga vuota) devono vedere il segnaposto come della query scritta, non di nessuna. La
	query VIVA, non quella del path: _timbra_query, che la timbra per le costruzioni, qui non si raggiunge.

	reconcile_position dichiara la lista nuova e azzera il gettone della vecchia: il path normale, quando la
	skin ci torna, arriva senza il '&pages=N' di un'altra lista, e _stale_token_abort non ha niente da buttare.
	Il gettone non e' nel path dell'attesa, quindi azzerarlo non cambia il path di questa invocazione.
	LA MARCA "IN COSTRUZIONE" SI CHIUDE PRIMA DI CONSEGNARE. E' per posizione, non per invocazione: appena il
	segnaposto e' a schermo parte la costruzione normale della stessa posizione e alza la sua. Chiusa dopo
	end_directory -- che dopo endOfDirectory scrive ancora nel db e chiede il lock grafico per il timbro --
	potrebbe cancellare quella della costruzione viva, e il canale dei rinvii la crederebbe finita. Prima
	della consegna la costruzione dopo non puo' ancora essere partita. Stesso ordine di consegna_posizione.
	Torna False solo se la riga non ha chiesto il segnaposto o non ha posizione: allora si costruisce e basta.
	"""
	from modules.kodi_utils import vuole_segnaposto, end_directory, timbra_primo_elemento, QUERY_PROP, STATO_ATTESA
	from modules import paginator
	if len(sys.argv) < 3 or not vuole_segnaposto(sys.argv[2]): return False
	scope, cid = paginator.position_of(params)
	if not scope: return False
	key = '%s.%s' % (scope, cid)
	paginator.reconcile_position(key, params)
	query = params.get('query') if params.get('search_hub') else None
	if query: timbra_primo_elemento(QUERY_PROP, paginator.query_viva() or query)
	paginator.log('attesa chiesta dalla skin key=%s: lista %s%s'
				% (key, paginator.short(paginator.make_key(params)), ' query="%s"' % query if query else ''))
	paginator.mark_build_end(key)
	try: end_directory(int(sys.argv[1]), cacheToDisc=False, segnaposto=STATO_ATTESA)
	except: pass
	return True

def _stale_token_abort(sys, params):
	# LOTTO 160. Fratello di _search_debounce_abort: quello lascia cadere una build la cui QUERY e'
	# gia' superata, questo una build il cui CONTEGGIO PAGINE lo e'. Entrambi chiudono la cartella
	# a vuoto sapendo che ne arriva subito un'altra corretta.
	# La condizione vera sta in paginator.token_is_stale, che e' anche l'unico posto che tocca lo
	# stato; qui c'e' solo il filtro a costo zero che evita di importare il paginator per le
	# invocazioni che non sono widget (navigator, riproduzione, dialoghi: niente pgctl nel path).
	if 'pgctl' not in params or not params.get('pages'): return False
	from modules import paginator
	if not paginator.token_is_stale(params): return False
	from modules.kodi_utils import end_directory
	# segnaposto=None, al contrario del fratello qui sopra: li' il contenitore tiene i risultati di
	# una query che l'utente ha lasciato, qui tiene quelli GIUSTI con un conteggio di pagine vecchio,
	# e la cartella corretta e' gia' in arrivo per lo stesso contenuto. Svuotarlo vorrebbe dire farlo
	# sfarfallare -- vuoto e poi di nuovo pieno degli stessi titoli -- per niente.
	try: end_directory(int(sys.argv[1]), cacheToDisc=False, segnaposto=None)
	except: pass
	return True

def routing(sys):
	# Marcatore (lotto 50 ter): da qui a mark_phase('indexer_in') c'e' SOLO il parsing dei parametri e
	# l'import PIGRO del modulo indexer. E' il taglio che separa "caricare i moduli" da "fare il
	# lavoro", dentro i ~10 s che nessuno strumento vedeva. Timbrato solo sui rami usati all'avvio e
	# nella navigazione serie: non serve sporcare tutti i trenta rami per rispondere a una domanda.
	mark_phase('routing_in')
	# LOTTO 323 -- da qui in poi ogni impostazione si legge UNA volta. E' il punto giusto perche' e' il
	# punto da cui passa ogni invocazione del plugin e nessun servizio: il ricordo non deve mai armarsi
	# in un processo che vive per tutta la sessione, o smetterebbe di vedere i cambiamenti. Va prima di
	# qualunque lettura, quindi prima ancora di leggere i parametri.
	try:
		from caches.settings_cache import memo_avvia
		memo_avvia()
	except Exception: pass
	params = dict(parse_qsl(sys.argv[2][1:], keep_blank_values=True))
	_get = params.get
	mode = _get('mode', 'navigator.main')
	# Il clic sul segnaposto "nessun risultato" di una riga vuota (kodi_utils.end_directory): niente da fare.
	if mode == 'segnaposto': return
	# LOTTO 261 -- L'INVOCAZIONE SI PRESENTA. Kodi crea un thread `LanguageInvoker` per ogni
	# invocazione del plugin, ma su Android non lo NOMINA (pthread_setname_np e' compilato solo per
	# glibc, vedi modules/diagnostica.battezza), quindi in /proc tutte le nostre invocazioni portano
	# il `comm` ereditato dal thread Java e sono indistinguibili fra loro. Scrivendo il mode nel
	# `comm` la sonda esterna vede "FL:movies" invece di un anonimo, e si capisce quale widget sta
	# mangiando il core SENZA dover incrociare il log.
	# Una scrittura di 16 byte, una volta per invocazione, e solo a diagnostica accesa: a log
	# normale questa riga non tocca niente. E' qui e non in fenlight.py perche' qui il `mode` e' gia'
	# stato letto e non costa una seconda analisi di sys.argv.
	try:
		from modules.diagnostica import battezza
		battezza('FL:' + mode.split('.')[-1])
	except Exception: pass
	# LOTTO 176, PASSO 1.2 BIS. Chi ha un pgctl E' la costruzione di un widget, e questo e' l'istante
	# piu' presto in cui lo si sa: i parametri sono appena stati letti e non e' ancora stato importato
	# nessun indexer. Prima si dichiarava l'inizio in passi_da_caricare e in mark_build_start, che pero'
	# stanno entrambe DOPO gli import pigri: fra l'avvio dell'interprete e quel punto passa oltre un
	# secondo in cui la costruzione e' in corso e builds_in_flight() risponde "niente in volo".
	# Vedi paginator.mark_invocation_start per la misura.
	# LOTTO 307 -- il contatore delle traversate (vedi kodi_utils.installa_traversate). Solo a
	# strumentazione accesa, e PRIMA di importare qualunque indexer: gli indexer copiano i nomi di
	# kodi_utils a livello di modulo, quindi devono trovarli gia' avvolti. perf.enabled() e' una
	# lettura di proprieta' tenuta in memoria, la stessa che l'import del paginator paga comunque.
	try:
		from modules.perf import enabled as _perf_enabled
		if _perf_enabled():
			from modules.kodi_utils import installa_traversate
			installa_traversate()
	except Exception: pass
	_pgctl = _get('pgctl')
	if _pgctl:
		try:
			from modules.paginator import mark_invocation_start
			mark_invocation_start(_pgctl)
		except: pass
		# LOTTO 418, revisione del 29/09 -- la lista di questa consegna, sul primo elemento: e' cio' con cui la
		# skin decide se la riga deve passare dall'attesa (kodi_utils.LISTA_PROP). Qui e in nessun altro posto,
		# cosi' la portano tutte le consegne di una riga, segnaposto compresi.
		try:
			from modules.kodi_utils import timbra_primo_elemento, lista_della_riga, LISTA_PROP
			_lista = lista_della_riga()
			if _lista: timbra_primo_elemento(LISTA_PROP, _lista)
		except: pass
		# LOTTO 418 -- i cancelli di una riga, prima di smistare: vedi _cancelli_riga.
		if _cancelli_riga(sys, params, mode): return
	# QUI C'ERA IL CANCELLO RIPRODUZIONE (lotto 111, rimosso col lotto 113).
	# Chiudeva la cartella con succeeded=False quando un widget veniva ricostruito durante la
	# riproduzione. Funzionava -- 18 invocazioni tagliate su tre film, da 5-6 s a 150-280 ms l'una --
	# ma la misura successiva ha spostato la domanda: contando i risvegli dei CDirectoryProvider per
	# fase, i provider si svegliano PRIMA del passaggio a schermo intero e DOPO Player.OnStop, e
	# ZERO volte durante il fullscreen (crash_film 5/0/0, sess_ok 5/0/40, sess_112 3/0/21). Kodi non
	# aggiorna da se' un provider che non e' visibile: la CPU durante il film era gia' tutta della
	# riproduzione, e il cancello non stava proteggendo il film ma solo i pochi secondi di
	# transizione in cui la home e' ancora a schermo. In cambio svuotava il contenitore -- non
	# esiste nessun modo, nell'API dei plugin, di chiudere una cartella dicendo "tieni quello che
	# hai": qualunque cosa diversa da un elenco completo e riuscito lascia il widget senza elementi.
	# Da qui la paginazione persa, il fuoco al primo elemento e la ricostruzione totale al ritorno.
	# La transizione ora si affronta marcandola come refresh IN POSTO (vedi 'playback.media' qui
	# sotto e Player.OnStop in service.py), non tagliandola.
	if 'navigator.' in mode:
		from indexers.navigator import Navigator
		return getattr(Navigator(params), mode.split('.')[1])()
	if 'menu_editor.' in mode:
		from modules.menu_editor import MenuEditor
		return getattr(MenuEditor(params), mode.split('.')[1])()
	if 'easynews.' in mode:
		from indexers import easynews
		return getattr(easynews, mode.split('.')[1])(params)
	if 'playback.' in mode:
		if mode == 'playback.media':
			# MARCATORE IN POSTO (lotto 113). Questo e' l'istante del Select: si apre
			# sources_playback.xml, la home passa in secondo piano e Kodi reinvalida i suoi
			# CDirectoryProvider. Senza marcatore _passi_legacy tratta quelle ricostruzioni come
			# l'APERTURA di un widget nuovo e torna al default (2 pagine). Nel log del 29/08 alle
			# 17:46:50 un contenitore da 101 elementi e' cosi' tornato a 50 col fuoco sul primo --
			# NOVE secondi prima di Player.OnPlay, cioe' la paginazione si perdeva gia' al Select,
			# anche senza arrivare a riprodurre niente. Il cancello non poteva vederlo: la bandiera
			# di riproduzione si alza molto dopo.
			from modules.kodi_utils import mark_inplace_rebuild
			mark_inplace_rebuild()
			from modules.sources import Sources
			return Sources().playback_prep(params)
		if mode == 'playback.video':
			from modules.player import FenLightPlayer
			return FenLightPlayer().run(_get('url', None), _get('obj', None))
	if 'choice' in mode:
		from indexers import dialogs
		return getattr(dialogs, mode)(params)
	if 'custom_key.' in mode:
		from modules import custom_keys
		return getattr(custom_keys, mode.split('custom_key.')[1])()
	if 'advancedsettings.' in mode:
		from modules import advanced_settings
		return getattr(advanced_settings, mode.split('.')[1])(params)
	if 'trakt.' in mode:
		if '.list' in mode:
			from indexers import trakt_lists
			mark_phase('indexer_in')
			return getattr(trakt_lists, mode.split('.')[2])(params)
		from apis import trakt_api
		return getattr(trakt_api, mode.split('.')[1])(params)
	if 'mdblist.' in mode:
		if '.list' in mode:
			from indexers import mdblist_lists
			mark_phase('indexer_in')
			return getattr(mdblist_lists, mode.split('.')[2])(params)
		from apis import mdblist_api
		return getattr(mdblist_api, mode.split('.')[1])(params)
	if 'build' in mode:
		# Prima di qualunque costruzione: se il path porta il conteggio pagine di un'altra lista
		# questa invocazione e' gia' superata. Vale per home, hub e ricerca allo stesso modo --
		# il cambio inquilino non e' un fatto della ricerca, li' si vede soltanto piu' spesso.
		if _stale_token_abort(sys, params): return
		if mode == 'build_movie_list':
			_timbra_query(params)
			_chiudi_discover(params, ('tmdb_movies_search', 'tmdb_movies_search_filtered'))
			from indexers.movies import Movies
			mark_phase('indexer_in')
			movies = Movies(params)
			return movies.fetch_list()
		if mode == 'build_tvshow_list':
			_timbra_query(params)
			_chiudi_discover(params, ('tmdb_tv_search', 'tmdb_tv_search_filtered'))
			from indexers.tvshows import TVShows
			mark_phase('indexer_in')
			tvshows = TVShows(params)
			return tvshows.fetch_list()
		if mode == 'build_season_list':
			from indexers.seasons import build_season_list
			mark_phase('indexer_in')
			return build_season_list(params)
		if mode == 'build_episode_list':
			from indexers.episodes import build_episode_list
			mark_phase('indexer_in')
			return build_episode_list(params)
		if mode == 'build_in_progress_episode':
			from indexers.episodes import build_single_episode
			return build_single_episode('episode.progress', params)
		if mode == 'build_recently_watched_episode':
			from indexers.episodes import build_single_episode
			return build_single_episode('episode.recently_watched', params)
		if mode == 'build_next_episode':
			from indexers.episodes import build_single_episode
			return build_single_episode('episode.next', params)
		if mode == 'build_continue_watching':
			from indexers.continue_watching import build_continue_watching
			mark_phase('indexer_in')
			return build_continue_watching(params)
		if mode == 'build_my_calendar':
			from indexers.episodes import build_single_episode
			return build_single_episode('episode.trakt', params)
		if mode == 'build_next_episode_manager':
			from modules.episode_tools import build_next_episode_manager
			return build_next_episode_manager()
		if mode == 'build_tmdb_people':
			from indexers.people import tmdb_people
			return tmdb_people(params)
		if mode == 'build_cast_list':
			from indexers.people import build_cast_list
			return build_cast_list(params)
		if 'random.' in mode:
			from indexers.random_lists import RandomLists
			return RandomLists(params).run_random()
	if 'watched_status.' in mode:
		if mode == 'watched_status.mark_episode':
			from modules.watched_status import mark_episode
			return mark_episode(params)
		if mode == 'watched_status.mark_season':
			from modules.watched_status import mark_season
			return mark_season(params)
		if mode == 'watched_status.mark_tvshow':
			from modules.watched_status import mark_tvshow
			return mark_tvshow(params)
		if mode == 'watched_status.mark_movie':
			from modules.watched_status import mark_movie
			return mark_movie(params)
		if mode == 'watched_status.erase_bookmark':
			from modules.watched_status import erase_bookmark
			return erase_bookmark(_get('media_type'), _get('tmdb_id'), _get('season', ''), _get('episode', ''), _get('refresh', 'false'))
	if 'search.' in mode:
		if mode == 'search.get_key_id':
			from modules.search import get_key_id
			return get_key_id(params)
		if mode == 'search.clear_search':
			from modules.search import clear_search
			return clear_search()
		if mode == 'search.remove':
			from modules.search import remove_from_search
			return remove_from_search(params)
		if mode == 'search.clear_all':
			from modules.search import clear_all
			return clear_all(_get('setting_id'), _get('refresh', 'false'))
		if mode == 'search.select_discover_filter':
			from modules.search import select_discover_filter
			return select_discover_filter(params)
		if mode == 'search.launch_discover':
			from modules.search import launch_discover
			return launch_discover(params)
		if mode == 'search.clear_discover_filters':
			from modules.search import clear_discover_filters
			return clear_discover_filters(params)
	if 'real_debrid' in mode:
		if mode == 'real_debrid.rd_cloud':
			from indexers.real_debrid import rd_cloud
			return rd_cloud()
		if mode == 'real_debrid.rd_downloads':
			from indexers.real_debrid import rd_downloads
			return rd_downloads()
		if mode == 'real_debrid.browse_rd_cloud':
			from indexers.real_debrid import browse_rd_cloud
			return browse_rd_cloud(_get('id'))
		if mode == 'real_debrid.resolve_rd':
			from indexers.real_debrid import resolve_rd
			return resolve_rd(params)
		if mode == 'real_debrid.rd_account_info':
			from indexers.real_debrid import rd_account_info
			return rd_account_info()
		if mode == 'real_debrid.authenticate':
			from apis.real_debrid_api import RealDebridAPI
			return RealDebridAPI().auth()
		if mode == 'real_debrid.revoke_authentication':
			from apis.real_debrid_api import RealDebridAPI
			return RealDebridAPI().revoke()
		if mode == 'real_debrid.delete':
			from indexers.real_debrid import rd_delete
			return rd_delete(_get('id'), _get('cache_type'))
	if 'premiumize' in mode:
		if mode == 'premiumize.pm_cloud':
			from indexers.premiumize import pm_cloud
			return pm_cloud(_get('id', None), _get('folder_name', None))
		if mode == 'premiumize.pm_transfers':
			from indexers.premiumize import pm_transfers
			return pm_transfers()
		if mode == 'premiumize.pm_account_info':
			from indexers.premiumize import pm_account_info
			return pm_account_info()
		if mode == 'premiumize.authenticate':
			from apis.premiumize_api import PremiumizeAPI
			return PremiumizeAPI().auth()
		if mode == 'premiumize.revoke_authentication':
			from apis.premiumize_api import PremiumizeAPI
			return PremiumizeAPI().revoke()
		if mode == 'premiumize.rename':
			from indexers.premiumize import pm_rename
			return pm_rename(_get('file_type'), _get('id'), _get('name'))
		if mode == 'premiumize.delete':
			from indexers.premiumize import pm_delete
			return pm_delete(_get('file_type'), _get('id'))
	if 'alldebrid' in mode:
		if mode == 'alldebrid.ad_cloud':
			from indexers.alldebrid import ad_cloud
			return ad_cloud(_get('id', None))
		if mode == 'alldebrid.browse_ad_cloud':
			from indexers.alldebrid import browse_ad_cloud
			return browse_ad_cloud(_get('folder'))
		if mode == 'alldebrid.resolve_ad':
			from indexers.alldebrid import resolve_ad
			return resolve_ad(params)
		if mode == 'alldebrid.ad_account_info':
			from indexers.alldebrid import ad_account_info
			return ad_account_info()
		if mode == 'alldebrid.authenticate':
			from apis.alldebrid_api import AllDebridAPI
			return AllDebridAPI().auth()
		if mode == 'alldebrid.revoke_authentication':
			from apis.alldebrid_api import AllDebridAPI
			return AllDebridAPI().revoke()
		if mode == 'alldebrid.delete':
			from indexers.alldebrid import ad_delete
			return ad_delete(_get('id'))
	if 'offcloud' in mode:
		if mode == 'offcloud.oc_cloud':
			from indexers.offcloud import oc_cloud
			return oc_cloud()
		if mode == 'offcloud.browse_oc_cloud':
			from indexers.offcloud import browse_oc_cloud
			return browse_oc_cloud(_get('folder_id'))
		if mode == 'offcloud.resolve_oc':
			from indexers.offcloud import resolve_oc
			return resolve_oc(params)
		if mode == 'offcloud.oc_account_info':
			from indexers.offcloud import oc_account_info
			return oc_account_info()
		if mode == 'offcloud.authenticate':
			from apis.offcloud_api import OffcloudAPI
			return OffcloudAPI().auth()
		if mode == 'offcloud.revoke_authentication':
			from apis.offcloud_api import OffcloudAPI
			return OffcloudAPI().revoke()
		if mode == 'offcloud.delete':
			from indexers.offcloud import oc_delete
			return oc_delete(_get('folder_id'))
	if 'easydebrid' in mode:
		if mode == 'easydebrid.authenticate':
			from apis.easydebrid_api import EasyDebridAPI
			return EasyDebridAPI().auth()
		if mode == 'easydebrid.revoke_authentication':
			from apis.easydebrid_api import EasyDebridAPI
			return EasyDebridAPI().revoke()
	if 'torbox' in mode:
		if mode == 'torbox.tb_cloud':
			from indexers.torbox import tb_cloud
			return tb_cloud()
		if mode == 'torbox.browse_tb_cloud':
			from indexers.torbox import browse_tb_cloud
			return browse_tb_cloud(_get('folder_id'), _get('media_type'))
		if mode == 'torbox.resolve_tb':
			from indexers.torbox import resolve_tb
			return resolve_tb(params)
		if mode == 'torbox.tb_account_info':
			from indexers.torbox import tb_account_info
			return tb_account_info()
		if mode == 'torbox.authenticate':
			from apis.torbox_api import TorBoxAPI
			return TorBoxAPI().auth()
		if mode == 'torbox.revoke_authentication':
			from apis.torbox_api import TorBoxAPI
			return TorBoxAPI().revoke()
		if mode == 'torbox.delete':
			from indexers.torbox import tb_delete
			return tb_delete(_get('folder_id'), _get('media_type'))
	if '_cache' in mode:
		from caches import base_cache
		if mode == 'clear_cache':
			return base_cache.clear_cache(_get('cache'))
		if mode == 'clear_all_cache':
			return base_cache.clear_all_cache()
		if mode == 'clean_databases_cache':
			return base_cache.clean_databases()
		if mode == 'check_databases_integrity_cache':
			return base_cache.check_databases_integrity()
	if '_image' in mode:
		from indexers.images import Images
		return Images().run(params)
	if '_text' in mode:
		if mode == 'show_text':
			from modules.kodi_utils import show_text
			return show_text(_get('heading'), _get('text', None), _get('file', None), _get('font_size', 'small'), _get('kodi_log', 'false') == 'true')
	if 'settings_manager.' in mode:
		from caches import settings_cache
		return getattr(settings_cache, mode.split('.')[1])(params)
	if 'downloader.' in mode:
		from modules import downloader
		return getattr(downloader, mode.split('.')[1])(params)
	##EXTRA modes##
	if mode == 'fen_blur': 
		from modules.blur_service import blur_image
		return blur_image(params)
	if mode == 'sync_settings':
		from caches.settings_cache import sync_settings
		return sync_settings(params)
	if mode == 'person_direct.search':
		from indexers.people import person_direct_search
		return person_direct_search(_get('key_id') or _get('query'))
	if mode == 'kodi_refresh':
		from modules.kodi_utils import kodi_refresh
		return kodi_refresh(_get('coalesce', 'true') != 'false')
	if mode == 'kodi_refresh_ids':
		# Ricarica mirata a partire da un elenco di tmdb_id (lotto 59): la usa il monitor Trakt, che
		# dopo la ricostruzione sa quali titoli sono cambiati. Se l'elenco arriva vuoto kodi_refresh_ids
		# ricade da sola sul globale, quindi non puo' comportarsi peggio di prima.
		# LOTTO 119 -- passano anche le AZIONI. Questo era il collo di bottiglia del canale: in
		# processo kodi_refresh_ids le accettava gia', ma chi arriva da RunPlugin (il monitor Trakt e
		# WidgetRefresher, cioe' proprio i due che sanno cosa e' cambiato su Trakt) poteva mandare
		# solo gli id. Le azioni si perdevano QUI, e con loro l'unico criterio capace di ricostruire un
		# widget in cui il titolo cambiato non e' ANCORA entrato -- watchlist e continua a guardare.
		# Un id puo' contenere ':' (identita' di episodio, vedi paginator.episode_uid): urlencode lo
		# cita e parse_qsl lo restituisce intatto, quindi lo split su ',' resta corretto.
		from modules.kodi_utils import kodi_refresh_ids
		return kodi_refresh_ids([i for i in _get('ids', '').split(',') if i],
								tuple(a for a in _get('actions', '').split(',') if a),
								coalesce=_get('coalesce', 'true') != 'false')
	if mode == 'refresh_widgets':
		from modules.kodi_utils import refresh_widgets
		# coalesce=false lo mette WidgetRefresher quando consuma un RINVIO globale (lotto 130): e'
		# lavoro gia' rimandato una volta, e riaccorparlo dietro la costruzione d'avvio lo perde per
		# sempre. La voce di menu "Aggiorna widget" non arriva piu' qui: e' aggiorna_riga (lotto 424).
		return refresh_widgets(_get('show_notification', 'false'), _get('coalesce', 'true') != 'false')
	if mode == 'aggiorna_riga':
		from modules.paginator import aggiorna_riga
		return aggiorna_riga(_get('riga'))
	if mode == 'person_data_dialog':
		from indexers.people import person_data_dialog
		return person_data_dialog(params)
	if mode == 'favorite_people':
		from indexers.people import favorite_people
		return favorite_people()
	if mode == 'manual_add_magnet_to_cloud':
		from modules.debrid import manual_add_magnet_to_cloud
		return manual_add_magnet_to_cloud(params)
	if mode == 'upload_logfile':
		from modules.kodi_utils import upload_logfile
		return upload_logfile(params)
	if mode == 'toggle_language_invoker':
		from modules.kodi_utils import toggle_language_invoker
		return toggle_language_invoker()
	if mode == 'set_videoinfo_properties':
		from modules.skin_properties import set_videoinfo_properties
		return set_videoinfo_properties(params)
	if mode == 'build_person_credits_list':
			from indexers.people import build_person_credits_list
			return build_person_credits_list(params)
	if mode == 'open_media_info':
		from modules.skin_properties import open_media_info
		return open_media_info(params)
	if mode == 'browse_media': 
		from modules.skin_properties import browse_media
		return browse_media(params)
	if mode == 'downloader':
		from modules.downloader import runner
		return runner(params)
	if mode == 'debrid.browse_packs':
		from modules.sources import Sources
		return Sources().debridPacks(_get('provider'), _get('name'), _get('magnet_url'), _get('info_hash'))
	if mode == 'open_settings':
		from modules.kodi_utils import open_settings
		return open_settings()
	if mode == 'hide_unhide_progress_items':
		from modules.watched_status import hide_unhide_progress_items
		hide_unhide_progress_items(params)
	if mode == 'open_external_scraper_settings':
		from modules.kodi_utils import external_scraper_settings
		return external_scraper_settings()
