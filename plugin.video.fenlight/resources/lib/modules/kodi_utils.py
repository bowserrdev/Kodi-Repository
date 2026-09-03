# -*- coding: utf-8 -*-
# TRUMP WON
import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
from os import path as osPath
from modules import icons
# Interruttore unico della strumentazione (lotto 83). perf e' una foglia: non importa nulla di
# Fen Light a livello di modulo, quindi si puo' prendere da qui senza il ciclo che paginator
# creerebbe (paginator importa questo file in testa).
from modules.perf import log as perf_log, memory_suffix as perf_memory
try: xbmc_actor = xbmc.Actor
except: xbmc_actor = None
xbmc_player, numeric_input, xbmc_monitor, translatePath = xbmc.Player, 1, xbmc.Monitor, xbmcvfs.translatePath
ListItem, getSkinDir, log, getCurrentWindowId, Window = xbmcgui.ListItem, xbmc.getSkinDir, xbmc.log, xbmcgui.getCurrentWindowId, xbmcgui.Window
File, exists, copy, delete, rmdir, rename = xbmcvfs.File, xbmcvfs.exists, xbmcvfs.copy, xbmcvfs.delete, xbmcvfs.rmdir, xbmcvfs.rename
get_infolabel, get_visibility, execute_JSON, window_xml_dialog = xbmc.getInfoLabel, xbmc.getCondVisibility, xbmc.executeJSONRPC, xbmcgui.WindowXMLDialog
executebuiltin, xbmc_sleep, convertLanguage, getSupportedMedia, PlayList = xbmc.executebuiltin, xbmc.sleep, xbmc.convertLanguage, xbmc.getSupportedMedia, xbmc.PlayList
progressDialogBG = xbmcgui.DialogProgressBG
endOfDirectory, addSortMethod, listdir, mkdir, mkdirs = xbmcplugin.endOfDirectory, xbmcplugin.addSortMethod, xbmcvfs.listdir, xbmcvfs.mkdir, xbmcvfs.mkdirs
addDirectoryItem, addDirectoryItems, setContent, setCategory = xbmcplugin.addDirectoryItem, xbmcplugin.addDirectoryItems, xbmcplugin.setContent, xbmcplugin.setPluginCategory
path_join = osPath.join
img_url = 'https://i.imgur.com/%s.png'
invoker_switch_dict = {'true': 'false', 'false': 'true'}
empty_poster, nextpage = img_url % icons.box_office, img_url % icons.nextpage
nextpage_landscape = img_url % icons.nextpage_landscape
tmdb_default_api = 'b370b60447737762ca38457bd77579b3'
trakt_default_id = '87e3f055fc4d8fcfd96e61a47463327ca877c51e8597b448e132611c5a677b13'
trakt_default_secret = '4a1957a52d5feb98fafde53193e51f692fa9bdcd0cc13cf44a5e39975539edf0'
myvideos_db_paths = {19: '119', 20: '121', 21: '124'}
sort_method_dict = {'episodes': 24, 'files': 5, 'label': 2, 'none': 0}
playlist_type_dict = {'music': 0, 'video': 1}
tmdb_dict_removals = ('adult', 'backdrop_path', 'genre_ids', 'original_language', 'original_title', 'overview', 'popularity', 'vote_count', 'video', 'origin_country', 'original_name')
with_media_removals = ('description', 'privacy', 'type', 'share_link', 'display_numbers', 'allow_comments', 'sort_by', 'sort_how', 'created_at', 'updated_at', 'comment_count')
single_ep_list = ('episode.progress', 'episode.recently_watched', 'episode.next_trakt', 'episode.next_fenlight', 'episode.trakt_recently_aired', 'episode.trakt_calendar')
scraper_names = ['EXTERNAL SCRAPERS', 'EASYNEWS', 'RD CLOUD', 'PM CLOUD', 'AD CLOUD', 'OC CLOUD', 'TB CLOUD', 'FOLDERS 1-5']
random_valid_type_check = {'build_movie_list': 'movie', 'build_tvshow_list': 'tvshow', 'build_season_list': 'season', 'build_episode_list': 'episode',
				'build_in_progress_episode': 'single_episode', 'build_recently_watched_episode': 'single_episode', 'build_next_episode': 'single_episode',
				'build_my_calendar': 'single_episode', 'build_trakt_lists': 'trakt_list', 'trakt.list.build_trakt_list': 'trakt_list', 'build_trakt_my_lists_contents': 'trakt_list'}
extras_button_label_values = {
				'movie':
					{'movies_play': 'Playback', 'show_trailers': 'Trailer', 'show_images': 'Images',  'show_extrainfo': 'Extra Info', 'show_genres': 'Genres',
					'show_director': 'Director', 'show_options': 'Options', 'show_recommended': 'Recommended', 'show_more_like_this': 'More Like This',
					'show_trakt_manager': 'Trakt Manager', 'playback_choice': 'Playback Options', 'show_favorites_manager': 'Favorites Manager', 'show_plot': 'Plot',
					'show_keywords': 'Keywords', 'show_in_trakt_lists': 'In Trakt Lists', 'close_all': 'Close All Dialogs'},
				'tvshow':
					{'tvshow_browse': 'Browse', 'show_trailers': 'Trailer', 'show_images': 'Images', 'show_extrainfo': 'Extra Info', 'show_genres': 'Genres',
					'play_nextep': 'Play Next', 'show_options': 'Options', 'show_recommended': 'Recommended', 'show_more_like_this': 'More Like This',
					'show_trakt_manager': 'Trakt Manager', 'play_random_episode': 'Play Random', 'show_favorites_manager': 'Favorites Manager', 'show_plot': 'Plot',
					'show_keywords': 'Keywords', 'show_in_trakt_lists': 'In Trakt Lists', 'close_all': 'Close All Dialogs'}}
video_extensions = ('m4v', '3g2', '3gp', 'nsv', 'tp', 'ts', 'ty', 'pls', 'rm', 'rmvb', 'mpd', 'ifo', 'mov', 'qt', 'divx', 'xvid', 'bivx', 'vob', 'nrg', 'img', 'iso', 'udf', 'pva',
					'wmv', 'asf', 'asx', 'ogm', 'm2v', 'avi', 'bin', 'dat', 'mpg', 'mpeg', 'mp4', 'mkv', 'mk3d', 'avc', 'vp3', 'svq3', 'nuv', 'viv', 'dv', 'fli', 'flv', 'wpl',
					'xspf', 'vdr', 'dvr-ms', 'xsp', 'mts', 'm2t', 'm2ts', 'evo', 'ogv', 'sdp', 'avs', 'rec', 'url', 'pxml', 'vc1', 'h264', 'rcv', 'rss', 'mpls', 'mpl', 'webm',
					'bdmv', 'bdm', 'wtv', 'trp', 'f4v', 'pvr', 'disc')
image_extensions = ('jpg', 'jpeg', 'jpe', 'jif', 'jfif', 'jfi', 'bmp', 'dib', 'png', 'gif', 'webp', 'tiff', 'tif',
					'psd', 'raw', 'arw', 'cr2', 'nrw', 'k25', 'jp2', 'j2k', 'jpf', 'jpx', 'jpm', 'mj2')
_WINDOW = Window(10000)
_KODI_VERSION = int(get_infolabel('System.BuildVersion')[0:2])

def kodi_dialog():
	return xbmcgui.Dialog()

def addon_info(info):
	return xbmcaddon.Addon('plugin.video.fenlight').getAddonInfo(info)

def addon_version():
	return get_property('fenlight.addon_version') or addon_info('version')

def addon_path():
	return get_property('fenlight.addon_path') or addon_info('path')

def addon_profile():
	return get_property('fenlight.addon_profile') or translatePath(addon_info('profile'))

def addon_icon():
	return get_property('fenlight.addon_icon') or addon_info('icon')

def addon_fanart():
	return get_property('fenlight.addon_fanart') or addon_info('fanart')

def get_icon(image_name):
	return img_url % getattr(icons, image_name, 'I1JJhji')

def get_addon_fanart():
	return get_property('fenlight.default_addon_fanart') or addon_fanart()

# --- codifica URL: rimpiazza urllib.parse (lotto 74) -------------------------------------------
# Di urllib.parse servivano TRE funzioni: urlencode (qui, in build_url), parse_qsl (router e
# paginator, su ogni invocazione) e unquote (apis.trakt_api). Il modulo si portava pero' dietro un
# albero di dipendenze e, misurato sulla stick a cache fredda, ogni FILE aperto costa 80-250 ms
# indipendentemente da quanto contiene (`keyword`, 50 righe, misurava 97 ms). Il costo di import non
# e' lavoro, e' latenza di apertura file, quindi si paga a file e non a byte.
#
# Le tre funzioni sono riportate qui come port fedele di CPython, non come riscrittura "che dovrebbe
# andare bene": stessa tabella di caratteri sicuri (lettere, cifre, _.-~), stesso maiuscolo negli
# esadecimali, stessa gestione delle sequenze percent NON valide (urllib le lascia com'erano) e
# stessa divisione in tratti ASCII / non-ASCII di unquote. La corrispondenza e' verificata da un test
# differenziale contro urllib su corpus reale piu' casi limite (vedi OTTIMIZZAZIONI.md, lotto 74).
_URL_SAFE = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~')
# Tabella byte -> pezzo di stringa gia' codificato. Lo spazio diventa '+' come in quote_plus.
_QUOTED_PLUS = [(chr(_i) if chr(_i) in _URL_SAFE else '%%%02X' % _i) for _i in range(256)]
_QUOTED_PLUS[32] = '+'
_HEXTOBYTE = None

def quote_plus(string):
	if not isinstance(string, bytes): string = str(string).encode('utf-8')
	return ''.join([_QUOTED_PLUS[c] for c in string])

def urlencode(query):
	if hasattr(query, 'items'): query = query.items()
	return '&'.join(['%s=%s' % (quote_plus(k), quote_plus(v)) for k, v in query])

def _hextobyte():
	# Costruita alla prima decodifica e non all'import: una build di widget percent-DECODIFICA solo
	# la query dell'invocazione, mentre il dizionario e' 484 voci.
	global _HEXTOBYTE
	if _HEXTOBYTE is None:
		_hexdig = '0123456789ABCDEFabcdef'
		_HEXTOBYTE = {(a + b).encode(): bytes([int(a + b, 16)]) for a in _hexdig for b in _hexdig}
	return _HEXTOBYTE

def _unquote_to_bytes(string):
	bits = string.encode('utf-8').split(b'%')
	if len(bits) == 1: return bits[0]
	table, res = _hextobyte(), [bits[0]]
	for item in bits[1:]:
		try:
			res.append(table[item[:2]])
			res.append(item[2:])
		except KeyError:
			# Sequenza percent non valida ('%zz', '%2', '%' finale): urllib la lascia letterale.
			res.append(b'%')
			res.append(item)
	return b''.join(res)

def unquote(string, encoding='utf-8', errors='replace'):
	if isinstance(string, bytes): return string.decode(encoding, errors)
	if '%' not in string: return string
	# urllib divide su tratti ASCII / non-ASCII e percent-decodifica SOLO i primi: un carattere gia'
	# in chiaro fuori da ASCII non deve finire dentro una sequenza di byte da decodificare.
	out, i, n = [], 0, len(string)
	while i < n:
		is_ascii = ord(string[i]) < 128
		j = i
		while j < n and (ord(string[j]) < 128) == is_ascii: j += 1
		chunk = string[i:j]
		out.append(_unquote_to_bytes(chunk).decode(encoding, errors) if is_ascii else chunk)
		i = j
	return ''.join(out)

def parse_qsl(qs, keep_blank_values=False, encoding='utf-8', errors='replace'):
	if not qs: return []
	r = []
	for name_value in qs.split('&'):
		if not name_value: continue
		nv = name_value.split('=', 1)
		if len(nv) != 2:
			if keep_blank_values: nv.append('')
			else: continue
		if len(nv[1]) or keep_blank_values:
			r.append((unquote(nv[0].replace('+', ' '), encoding, errors),
					unquote(nv[1].replace('+', ' '), encoding, errors)))
	return r

def build_url(url_params):
	return 'plugin://plugin.video.fenlight/?%s' % urlencode(url_params)

def cast_label(cast):
	# Equivalente esatto di ListItem.Cast: Kodi lo compone come i soli NOMI separati da un a capo
	# (CVideoInfoTag::GetCast senza ruolo), ed e' l'unica cosa che la skin legge del cast.
	# Farlo comporre a Kodi costava un oggetto xbmc.Actor per attore -- una ventina per elemento,
	# quasi cinquemila per una lista da 250 -- piu' la chiamata setCast, per una stringa che si
	# vede solo aprendo il pannello trama. Qui e' una join, e finisce nella setProperties che
	# l'elemento fa comunque: zero attraversamenti in piu' verso il C++.
	if not cast: return ''
	return '\n'.join([i['name'] for i in cast if i.get('name')])

def add_dir(url_params, list_name, handle, iconImage='folder', fanartImage=None, isFolder=True):
	fanart = fanartImage or get_addon_fanart()
	icon = get_icon(iconImage)
	url = build_url(url_params)
	listitem = make_listitem()
	listitem.setLabel(list_name)
	listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': fanart})
	info_tag = listitem.getVideoInfoTag()
	info_tag.setPlot(' ')
	add_item(handle, url, listitem, isFolder)

def make_listitem():
	return ListItem(offscreen=True)

def add_item(handle, url, listitem, isFolder):
	addDirectoryItem(handle, url, listitem, isFolder)

# PERF (lotto 48): la CONSEGNA a Kodi, cioe' l'unico pezzo grosso mai misurato. Tutta la
# strumentazione finora si fermava a log_build, che scatta PRIMA di add_items; ma nel log della stick
# del 23/08 l'invocazione dura 14.8s dove la costruzione ne dichiara 4.6 -- dieci secondi spesi qui.
# Serve a decidere una cosa sola, e non e' una sfumatura: se il costo sta in add_items e' il PESO di
# ogni elemento (proprieta', menu contestuale, artwork) e va alleggerito l'elemento; se sta in
# endOfDirectory e' il NUMERO di elementi e il peso non c'entra. Le due correzioni sono diverse e
# senza questa misura si sceglierebbe a caso.
_DELIVERY = [0.0, 0]

# MARCATORI DI INVOCAZIONE (lotto 50). Il log di debug del 23/08 ha mostrato che un'invocazione widget
# vive 21-23 s mentre il PERF dichiara 3 s di costruzione: l'85-90% del costo sta FUORI da tutto cio'
# che finora sapevamo misurare. Questi timbri esistono per rispondere a una domanda sola -- DOVE stanno
# quei secondi -- e non per aggiungere l'ennesima statistica. Sono quattro letture di orologio per
# invocazione, niente proprieta' di finestra e niente traversate verso la GUI: la diagnostica non deve
# diventare essa stessa il carico (e' l'errore gia' fatto con DIAG in paginator).
# Vanno spente quando avranno risposto, come PERF_SELFTEST e DIAG prima di loro.
_PHASE = {}
# Gemello di _PHASE con il tempo di CPU DEL THREAD (lotto 131): vedi il commento in fenlight.py.
# Stessi nomi di fase, cosi' le due serie si sottraggono a coppie senza altra contabilita'.
_PHASE_CPU = {}

def _thread_cpu():
	try:
		from time import thread_time
		return thread_time()
	except Exception: return None

def mark_phase(name):
	# Timbro nudo: una lettura di orologio in un dizionario di processo. Serve a router.routing() per
	# separare i due pezzi dentro cui si nascondono i ~10 s ciechi -- il caricamento PIGRO del modulo
	# indexer (gli import che stanno dentro le funzioni e che il conteggio degli import in cima ai file
	# non vedeva) dal lavoro vero dell'indexer. Nessuna traversata verso la GUI, nessuna proprieta' di
	# finestra: la diagnostica non deve diventare il carico che sta misurando.
	from time import perf_counter
	_PHASE[name] = perf_counter()
	_c = _thread_cpu()
	if _c is not None: _PHASE_CPU[name] = _c

def add_items(handle, item_list):
	from time import perf_counter as _pc
	_t = _pc()
	_PHASE['add_start'] = _t
	_c = _thread_cpu()
	if _c is not None: _PHASE_CPU['add_start'] = _c
	addDirectoryItems(handle, item_list)
	_DELIVERY[0] = (_pc() - _t) * 1000
	_DELIVERY[1] = len(item_list) if item_list else 0

def set_content(handle, content):
	setContent(handle, content)

def set_category(handle, label):
	setCategory(handle, label)

# Istante in cui l'ULTIMA cartella Fen Light ha finito di costruirsi, chiunque l'abbia chiesta. Serve
# a una domanda sola, ed e' quella che decide il doppione post-riproduzione: uscendo dal player, Kodi
# rilegge da sola i DirectoryProvider della finestra che torna in primo piano? Se si', ordinare anche
# la nostra ricarica e' lavoro doppio. Il timbro sta in una proprieta' di finestra, quindi lo vedono
# anche gli altri interpreti: ogni costruzione di widget e' un processo Python a se'.
LAST_BUILD_PROP = 'fenlight.lastbuild'
# Gemella della precedente per le cartelle NON widget: la lista aperta di una finestra. Due timbri
# separati e non uno solo perche' rispondono a due domande diverse, e chi cerca l'una non deve poter
# essere accontentato dall'altra. Vedi open_folder_built_since.
OPEN_FOLDER_BUILD_PROP = 'fenlight.lastbuild.openfolder'
# REGISTRO delle ultime costruzioni, 'ts|query' separati da a capo, la piu' recente in fondo.
# Nasce dal fallimento della prima versione del lotto 125, ed e' l'unico modo di porre la domanda
# "il contenitore X e' stato ricostruito?" senza doverne indovinare la casella. I due timbri qui
# sopra ne tengono UNO solo a testa, e su quale dei due finisca una costruzione decide external(),
# che NON risponde alla domanda "sono un widget?": legge Container.PluginName della finestra
# corrente. Dentro la finestra Video, dove il contenitore attivo e' gia' una lista Fen Light,
# external() e' falso anche per i DirectoryProvider -- quindi lista stagioni E pannello episodi
# scrivono nella stessa casella, e la seconda cancella la prima. Misurato sulla stick il 02/09 alle
# 14:22: il pannello si era ricostruito con il dato nuovo a +1,1 s dalla scrittura, la guardia lo
# cercava in LAST_BUILD_PROP dove non e' mai arrivato, ha aspettato sei secondi e ha ordinato una
# ricostruzione identica. Con un registro la domanda si fa sull'IDENTITA' e la casella non conta.
BUILD_LOG_PROP = 'fenlight.lastbuild.log'
# Otto voci coprono qualunque raffica plausibile in una finestra sola (all'avvio della Home sono
# cinque widget insieme) restando una stringa corta da rileggere a ogni costruzione.
BUILD_LOG_CAP = 8

def end_directory(handle, cacheToDisc=True):
	# La misura avvolge la chiamata, non la duplica: endOfDirectory resta una sola, fuori da qualunque
	# try, cosi' nessun errore della diagnostica puo' impedirla o farla eseguire due volte.
	from time import perf_counter as _pc
	_t = _pc()
	endOfDirectory(handle, cacheToDisc=cacheToDisc)
	_eod = (_pc() - _t) * 1000
	_PHASE['eod_end'] = _pc()
	try:
		# Il timbro sta DOPO endOfDirectory, e la ragione non e' stilistica. external() interroga la
		# GUI (getInfoLabel su Container.PluginName): metterlo PRIMA significava chiedere il lock
		# grafico mentre il thread GUI di Kodi e' fermo ad aspettare proprio questa cartella. E' la
		# forma classica di un abbraccio mortale, e all'avvio -- cinque widget che costruiscono insieme
		# mentre Kodi carica Home.xml -- e' il momento in cui e' piu' probabile. Su Android un Kodi
		# bloccato viene ucciso dal sistema, che dall'esterno si vede come un crash.
		# Dopo endOfDirectory il thread GUI e' libero: e' lo stesso punto in cui set_view_mode chiama
		# gia' external() da sempre, senza mai aver dato problemi.
		from time import time as _stamp_now
		# IL TIMBRO PORTA ANCHE L'IDENTITA' DI CIO' CHE E' STATO COSTRUITO, non solo l'istante
		# (lotto 125). Con il solo istante la domanda "Kodi ha gia' ricostruito?" e' ambigua: la
		# risposta puo' arrivare da una cartella che non c'entra. Misurato sulla stick il 02/09 alle
		# 12:12: la guardia del player cercava la ricostruzione del PANNELLO EPISODI -- l'unico
		# contenitore che disegna il segnalibro -- e si e' accontentata della lista STAGIONI, che di
		# segnalibri non ne mostra. E' andata bene perche' il pannello e' arrivato 0,6 s dopo, non
		# perche' la guardia lo avesse verificato. sys.argv[2] e' la query di QUESTA costruzione
		# ('?mode=build_episode_list&season=1&tmdb_id=287238'): chi interroga il timbro puo' cosi'
		# chiedere un contenitore preciso invece di accontentarsi del primo che passa.
		import sys as _sys
		try: _what = _sys.argv[2] if len(_sys.argv) > 2 else ''
		except: _what = ''
		_mark = '%s|%s' % (_stamp_now(), _what)
		# Il registro riceve OGNI costruzione, prima della biforcazione: e' proprio la biforcazione
		# ad aver reso la domanda inaffidabile. La lettura-modifica-scrittura non e' protetta, quindi
		# sotto contesa una voce puo' perdersi; la conseguenza e' al massimo una ricostruzione di
		# troppo, mai una guardia soddisfatta a torto.
		try:
			_raw = get_property(BUILD_LOG_PROP)
			_rows = [r for r in _raw.split('\n') if r] if _raw else []
			_rows.append(_mark)
			set_property(BUILD_LOG_PROP, '\n'.join(_rows[-BUILD_LOG_CAP:]))
		except: pass
		if external():
			set_property(LAST_BUILD_PROP, _mark)
		else:
			# LA CARTELLA APERTA DI UNA FINESTRA NON E' UN WIDGET, e fino al lotto 121 non timbrava
			# niente. LAST_BUILD_PROP sta dentro `if external()`, cioe' copre solo le costruzioni dei
			# widget: la lista stagioni e il pannello episodi dentro la finestra Video non ci finiscono
			# mai. Chi chiedeva "Kodi ha gia' ricostruito?" per decidere se ricaricare la cartella
			# aperta riceveva quindi SEMPRE no, e ordinava una seconda ricostruzione identica.
			# Misurato sulla stick il 02/09: Kodi ricostruisce stagioni ed episodi alle 04:42:12,0 e
			# 04:42:12,8 -- dopo la scrittura dello stato, quindi con il dato giusto -- e la guardia
			# ha comunque aspettato i suoi 6 s e ordinato tutto da capo alle 04:42:17,5. Un difetto
			# che non produce nessun errore: solo lavoro doppio, e per questo era invisibile.
			set_property(OPEN_FOLDER_BUILD_PROP, _mark)
	except: pass
	if _DELIVERY[1]:
		try:
			_n, _add = _DELIVERY[1], _DELIVERY[0]
			_DELIVERY[0], _DELIVERY[1] = 0.0, 0
			perf_log('FenLight PERF CONSEGNA', '%s elementi | add_items %.0f ms (%.2f ms/elemento) + endOfDirectory %.0f ms (%.2f ms/elemento) | consegna totale %.0f ms'
					% (_n, _add, _add / _n, _eod, _eod / _n, _add + _eod))
		except: pass

def log_invocation(argv, t_start, t_import, t_end, c_start=None, c_import=None, c_end=None):
	# LA misura del lotto 50. Il log di debug ha mostrato invocazioni widget da 21-23 s dove il PERF
	# dichiarava 3 s: questa riga divide l'invocazione INTERA nei segmenti che PERF non vede mai.
	#   import        -> costo di caricare i moduli (verificato piccolo: l'albero e' gia' pigro)
	#   routing->lista-> dall'ingresso in routing a quando la lista e' pronta. CONTIENE la costruzione
	#                    che PERF gia' misura: la differenza fra questo numero e il PERF 'totale' e' il
	#                    preparativo mai visto (impostazioni, database, attese, contesa sul GIL).
	#   consegna      -> add_items + endOfDirectory (gia' dettagliato da PERF CONSEGNA)
	#   coda          -> tutto cio' che gira DOPO la consegna e prima dell'uscita
	# Non tocca la GUI e non scrive proprieta' di finestra: quattro sottrazioni e una riga di log.
	try:
		_ms = lambda a, b: (b - a) * 1000
		mode = ''
		try:
			for part in (argv[2] if len(argv) > 2 else '').lstrip('?').split('&'):
				if part.startswith('mode='): mode = part[5:]; break
		except: pass
		add_start, eod_end = _PHASE.get('add_start'), _PHASE.get('eod_end')
		rt_in, ix_in = _PHASE.get('routing_in'), _PHASE.get('indexer_in')
		parts = ['import %.0f' % _ms(t_start, t_import)]
		# Il taglio nuovo (lotto 50 ter): 'import pigri' e' parsing dei parametri + caricamento del modulo
		# indexer, 'indexer' e' il lavoro vero. Se i ~10 s ciechi stanno nel primo, sono import mascherati
		# e la correzione e' alleggerire l'albero; se stanno nel secondo, e' lavoro o contesa sul GIL e la
		# correzione e' la coda. Sono due strade diverse e senza questo taglio si sceglierebbe a caso.
		if rt_in and ix_in:
			parts.append('import pigri %.0f' % _ms(rt_in, ix_in))
			if add_start: parts.append('indexer %.0f' % _ms(ix_in, add_start))
		elif add_start: parts.append('routing->lista %.0f' % _ms(t_import, add_start))
		if add_start and eod_end: parts.append('consegna %.0f' % _ms(add_start, eod_end))
		if eod_end: parts.append('coda %.0f' % _ms(eod_end, t_end))
		if not add_start: parts.append('nessuna cartella costruita, solo azione %.0f' % _ms(t_import, t_end))
		if 'view_ms' in _PHASE: parts.append('(set_view %.0f)' % _PHASE['view_ms'])
		# La memoria libera in coda a OGNI invocazione: e' la serie storica che mancava. Il valore
		# assoluto dice poco (Android tiene la libera bassa di proposito), la derivata dice tutto.
		perf_log('FenLight PERF INVOCAZIONE', '%s | totale %.0f ms | %s ms%s'
				% (mode or '?', _ms(t_start, t_end), ' + '.join(parts), perf_memory()))
		_log_invocation_cpu(mode, t_start, t_import, t_end, c_start, c_import, c_end, rt_in, ix_in, add_start)
	except: pass

def _log_invocation_cpu(mode, t_start, t_import, t_end, c_start, c_import, c_end, rt_in, ix_in, add_start):
	"""Le stesse fasi, in tempo di CPU del thread invece che di orologio (lotto 131).

	Riga separata e non allungata su quella sopra: quella si legge a colpo d'occhio e serve tutti i
	giorni, questa serve a rispondere a UNA domanda e va spenta quando avra' risposto.

	Come si legge: 'cpu/orologio'. Vicini = il thread stava macinando, il tempo e' lavoro vero e
	l'unico rimedio e' fare meno lavoro. Lontani = il thread era FERMO ad aspettare, e allora togliere
	import non restituisce niente -- il tempo se n'e' andato altrove (GIL conteso fra sotto-interpreti,
	letture dalla flash, il resto dell'avvio di Kodi).

	Vale come PROVA sulle due fasi di import, che sono a thread singolo. Sulla fase 'indexer' NO: li'
	il lavoro sta nei worker e questo thread e' legittimamente fermo ad aspettarli, quindi un rapporto
	basso non significa contesa. E' scritto qui perche' e' esattamente il modo in cui questa misura
	verrebbe letta male.
	"""
	if c_start is None or c_end is None: return
	try:
		_ms = lambda a, b: (b - a) * 1000
		def _quota(cpu_a, cpu_b, wall_a, wall_b):
			w = _ms(wall_a, wall_b)
			c = _ms(cpu_a, cpu_b)
			return '%.0f/%.0f ms (%.0f%%)' % (c, w, (c / w * 100) if w > 0 else 0)
		parts = []
		if c_import is not None:
			parts.append('import %s' % _quota(c_start, c_import, t_start, t_import))
			ci, cx = _PHASE_CPU.get('routing_in'), _PHASE_CPU.get('indexer_in')
			ca = _PHASE_CPU.get('add_start')
			if ci is not None and cx is not None and rt_in and ix_in:
				parts.append('import pigri %s' % _quota(ci, cx, rt_in, ix_in))
				if ca is not None and add_start:
					parts.append('indexer %s' % _quota(cx, ca, ix_in, add_start))
		perf_log('FenLight PERF CPU', '%s | totale %s | %s'
				% (mode or '?', _quota(c_start, c_end, t_start, t_end), ' + '.join(parts) or 'nessuna fase'))
	except: pass

_FENLIGHT_PKGS = ('modules', 'indexers', 'apis', 'caches', 'windows')

def log_import_profile(argv, times, order, parents=None, top=18, floor_ms=25.0):
	# Rendiconto del profilatore installato in fenlight.py (lotto 54, DIAGNOSTICO).
	# I tempi sono PROPRI, non cumulativi: sommandoli si ottiene il costo totale degli import, e ogni
	# modulo si vede attribuito solo cio' che esegue davvero. Stampa i primi `top` sopra `floor_ms`,
	# piu' una riga di totali per sapere quanta parte della somma sta nella coda non elencata.
	try:
		if not times: return
		mode = ''
		try:
			for part in (argv[2] if len(argv) > 2 else '').lstrip('?').split('&'):
				if part.startswith('mode='): mode = part[5:]; break
		except: pass
		parents = parents or {}
		total_ms = sum(times.values()) * 1000
		fenlight = sum(t for n, t in times.items() if n.split('.')[0] in _FENLIGHT_PKGS) * 1000
		perf_log('FenLight PERF IMPORT', '%s | %d moduli | totale %.0f ms | di cui Fen Light %.0f ms | resto %.0f ms'
				% (mode or '?', len(times), total_ms, fenlight, total_ms - fenlight))
		# Raggruppa per pacchetto di primo livello: e' li' che si vede dove sta davvero la massa,
		# perche' il costo e' spalmato su oltre 100 moduli e nessuno singolo domina.
		groups = {}
		for name, t in times.items():
			root = name.split('.')[0] or '(relativo)'
			groups[root] = groups.get(root, 0.0) + t
		ext = sorted(((r, t * 1000) for r, t in groups.items() if r not in _FENLIGHT_PKGS), key=lambda kv: kv[1], reverse=True)
		perf_log('FenLight PERF IMPORT', '  -- esterni per pacchetto --')
		for root, ms in ext[:top]:
			if ms < floor_ms: break
			# Il richiedente del pacchetto: il primo modulo ESTERNO al pacchetto che lo ha tirato
			# dentro. Senza il filtro si otterrebbe 'email <- email.header', cioe' il pacchetto che
			# importa se stesso, che non dice nulla su chi lo ha fatto entrare.
			who = next((parents[n] for n in order
						if n.split('.')[0] == root and parents.get(n) and parents[n].split('.')[0] != root), None)
			if not who: who = parents.get(root) or '?'
			perf_log('FenLight PERF IMPORT', '  %7.0f ms  %-22s <- %s' % (ms, root, who))
		fen = sorted(((n, t * 1000) for n, t in times.items() if n.split('.')[0] in _FENLIGHT_PKGS), key=lambda kv: kv[1], reverse=True)
		perf_log('FenLight PERF IMPORT', '  -- Fen Light, primi moduli --')
		for name, ms in fen[:8]:
			if ms < floor_ms: break
			perf_log('FenLight PERF IMPORT', '  %7.0f ms  %s' % (ms, name))
	except: pass

def build_mark_since(prop, since_ts):
	"""L'identita' dell'ultima costruzione timbrata in `prop`, se e' POSTERIORE a since_ts.

	Torna la query del plugin ('?mode=build_episode_list&season=1&tmdb_id=287238'), stringa vuota se
	la costruzione c'e' ma non ha saputo dire chi era, None se non c'e' nessuna costruzione recente.
	La differenza fra '' e None conta: la prima e' 'e' successo qualcosa, non so cosa', e chi vuole
	un contenitore PRECISO deve rifiutarla.
	"""
	try:
		raw = get_property(prop) or ''
		if not raw: return None
		ts, _, what = raw.partition('|')
		if float(ts or 0) > float(since_ts or 0): return what
	except: pass
	return None

# Qui viveva il registro delle scritture locali del lotto 128 (PROGRESS_LOCAL_WRITES_PROP, la grazia
# di 120 s, note_local_progress_write, recent_local_progress). RIMOSSO dal lotto 133: era un modo di
# ricostruire dall'orologio uno stato che adesso sta scritto sulla riga, nella colonna `sync_state`.
# La grazia sbagliava per costruzione, perche' 'l'ho scritta io da poco' e 'Trakt ce l'ha ancora'
# sono due domande diverse: il 03/09 la stick ha resuscitato per due giri un film cancellato dal Mac
# trenta secondi prima. Vedi caches/progress_sync.

def build_log_rows(since_ts):
	"""Le identita' delle costruzioni registrate DOPO since_ts, dalla piu' vecchia alla piu' recente.

	Chi deve aspettare un contenitore preciso interroga questo, non i due timbri a casella singola:
	vedi BUILD_LOG_PROP per il motivo.
	"""
	out = []
	try:
		raw = get_property(BUILD_LOG_PROP) or ''
		for row in raw.split('\n'):
			if not row: continue
			ts, _, what = row.partition('|')
			try:
				if float(ts or 0) > float(since_ts or 0): out.append(what)
			except: continue
	except: pass
	return out

def build_mark_param(what, name):
	"""Il valore del parametro `name` dentro l'identita' di una costruzione, o None.

	Il confronto per sottostringa non basta e non e' un caso di scuola: 'tmdb_id=2872' e' contenuto
	in 'tmdb_id=287238'. Oggi nessuna situazione reale lo produce -- nella finestra Video la serie
	aperta e' una sola -- ma una guardia che si accontenta di una corrispondenza parziale e'
	esattamente la categoria di difetto che questo lotto esiste per togliere, e costa sei righe
	toglierla del tutto invece di argomentare perche' non capitera'.
	"""
	if not what: return None
	for chunk in what.lstrip('?').split('&'):
		key, _, value = chunk.partition('=')
		if key == name: return value
	return None

def directory_built_since(since_ts):
	# ATTENZIONE: risponde SOLO per le costruzioni dei WIDGET (vedi il timbro in end_directory, dentro
	# `if external()`), e la domanda e' GENERICA: 'un widget, uno qualunque'. Va bene a chi cerca un
	# segno di vita; chi deve aspettare un contenitore PRECISO usa build_mark_since piu'
	# build_mark_param, che confrontano l'identita' timbrata invece dell'istante soltanto.
	return build_mark_since(LAST_BUILD_PROP, since_ts) is not None

def open_folder_built_since(since_ts):
	"""La cartella APERTA di una finestra e' stata ricostruita dopo questo istante?

	Gemella di directory_built_since per l'altra meta' del mondo: le cartelle che non sono widget --
	lista stagioni, pannello episodi, qualunque elenco dentro la finestra Video. Sono esattamente
	quelle che Kodi rilegge da solo tornando dal player, ed erano l'unica cosa che il timbro dei
	widget non poteva vedere.
	"""
	return build_mark_since(OPEN_FOLDER_BUILD_PROP, since_ts) is not None

# Quanto si concede al contenitore per dichiarare il contenuto atteso, OLTRE al settle da 100 ms.
# Tarato su tutti i campioni raccolti il 24/08, non su una stima:
#   build_season_list  19 campioni, set_view 100-287 ms  -> il minimo E' il settle: in 19 casi su 19
#                                                           il contenuto era gia' giusto al primo
#                                                           controllo. Massimo oltre il settle: 187 ms.
#   build_episode_list  7 campioni, tutti al tetto       -> 7 fallimenti su 7 (vedi sotto).
# L'attesa non e' quindi "a volte utile": non e' MAI servita. 300 ms coprono con margine 1,6x il caso
# piu' lento mai osservato, e riducono a ~0,4 s il costo del caso che non puo' riuscire.
VIEW_MODE_WAIT_SECONDS = 0.3

# I contenuti per cui, in questa skin, l'attesa e' gia' scaduta almeno una volta: non ci si riprova.
# In Arctic Fuse la lista episodi vive in un pannello (CDirectoryProvider legato al FolderPath
# dell'elemento a fuoco, Includes_Views_Combined.xml), quindi il contenitore della finestra resta
# 'seasons' e 'episodes' non arrivera' mai. Non esiste un segnale per saperlo PRIMA -- la proprieta'
# TMDBHelper.WidgetContainer che la skin userebbe non e' piu' scritta da nessuno dopo la rimozione di
# TMDbHelper -- quindi lo si impara dal primo tentativo e non lo si ripaga.
# Si auto-corregge: il controllo d'ingresso avviene comunque, e se un giorno il contenuto combacia si
# procede e il marchio viene tolto. Nessun rischio di restare bloccati su una vista diversa.
VIEW_MODE_HOPELESS_PROP = 'fenlight.view_wait_hopeless'

def set_view_mode(view_type, content='files', is_external=None):
	# Involucro di sola misura (lotto 50): la logica e' intatta in _set_view_mode_impl. Serve perche'
	# questa funzione contiene un'attesa attiva -- sleep(100) e poi fino a 3000 letture di
	# Container.Content a 1 ms -- che gira DOPO endOfDirectory, cioe' a lista gia' consegnata, dentro
	# un'invocazione che sappiamo durare 15-20 s. Per i widget esce subito (is_external), quindi non
	# spiega il costo dei widget; per stagioni ed episodi puo' valere fino a 3 secondi e non era mai
	# stata cronometrata.
	from time import perf_counter as _pc
	_t = _pc()
	try: return _set_view_mode_impl(view_type, content, is_external)
	finally: _PHASE['view_ms'] = (_pc() - _t) * 1000

def _set_view_mode_impl(view_type, content='files', is_external=None):
	if not get_property('fenlight.use_viewtypes') == 'true': return
	if is_external == None: is_external = external()
	if is_external: return
	view_id = get_property('fenlight.%s' % view_type) or None
	if not view_id: return
	# Il limite era a ITERAZIONI (3000 giri di sleep(1) + una lettura di infolabel), cioe' "3 secondi"
	# solo su un dispositivo dove un giro costa 1 ms. Sulla stick un giro costa ~3,5 ms fra sleep,
	# passaggio Python->C++ e contesa sul GIL: misurato il 24/08, `build_episode_list` spendeva
	# 10598 ms e 8636 ms qui dentro -- il 94% dell'invocazione -- per poi **arrendersi** senza
	# impostare la vista. Dieci secondi buttati, non dieci secondi di lavoro.
	# Il limite ora e' sul TEMPO, quindi vale lo stesso su qualunque hardware. Per confronto, nella
	# lista stagioni l'attesa si chiude in 101-287 ms: due secondi sono larghi.
	try:
		from time import perf_counter as _pc
		hopeless = set((get_property(VIEW_MODE_HOPELESS_PROP) or '').split(',')) - {''}
		sleep(100)
		seen = container_content()
		if seen != content:
			# Gia' scoperto inutile per questo contenuto: si esce senza pagare l'attesa. Il controllo
			# sopra e' comunque avvenuto, quindi se la situazione cambia il caso buono passa lo stesso.
			if content in hopeless: return
			deadline = _pc() + VIEW_MODE_WAIT_SECONDS
			while seen != content:
				if _pc() >= deadline:
					set_property(VIEW_MODE_HOPELESS_PROP, ','.join(sorted(hopeless | {content})))
					# Si registra anche TMDbHelper.WidgetContainer: e' la proprieta' con cui la skin marca
					# il contenitore-pannello a fuoco, ed e' l'ultimo candidato per sapere PRIMA che
					# l'attesa non puo' riuscire. Il dubbio e' che segua il FUOCO e non chi costruisce:
					# il pannello episodi si ricarica mentre il fuoco e' sulla lista stagioni, dove la
					# skin la cancella (Includes_Views_Combined.xml:166). Se qui esce vuota, cade.
					try: _wc = get_infolabel('Window.Property(TMDbHelper.WidgetContainer)')
					except: _wc = '?'
					logger('Fen Light', 'DIAG vista: attesa scaduta a %.1fs | Container.Content=%r atteso %r | WidgetContainer=%r | vista NON impostata | %r marcato irraggiungibile per la sessione'
							% (VIEW_MODE_WAIT_SECONDS, seen, content, _wc, content))
					return
				sleep(1)
				seen = container_content()
		if hopeless and content in hopeless:
			# Il contenuto stavolta combacia: la vista e' tornata raggiungibile (skin o vista diversa).
			set_property(VIEW_MODE_HOPELESS_PROP, ','.join(sorted(hopeless - {content})))
		execute_builtin('Container.SetViewMode(%s)' % view_id)
	except: return

def remove_keys(dict_item, dict_removals):
	for k in dict_removals: dict_item.pop(k, None)
	return dict_item

def append_path(_path):
	import sys
	sys.path.append(translatePath(_path))

def logger(heading, function):
	log('###%s###: %s' % (heading, function), 1)

def kodi_window():
	return _WINDOW

def get_property(prop):
	return _WINDOW.getProperty(prop)

def set_property(prop, value):
	return _WINDOW.setProperty(prop, value)

def clear_property(prop):
	return _WINDOW.clearProperty(prop)

def clear_all_properties():
	return _WINDOW.clearProperties()

def addon(addon_id='plugin.video.fenlight'):
	return xbmcaddon.Addon(id=addon_id)

def addon_installed(addon_id):
	return get_visibility('System.HasAddon(%s)' % addon_id)

def addon_enabled(addon_id):
	return get_visibility('System.AddonIsEnabled(%s)' % addon_id)

def container_content():
	return get_infolabel('Container.Content')

def set_sort_method(handle, method):
	addSortMethod(handle, sort_method_dict[method])

# Unico punto in cui 'requests' entra in un interprete (lotto 52). Serve a rispondere a una domanda
# precisa: al boot i widget hanno metadati al 100% in cache e zero rete nel filtro doppiaggio, eppure
# la fase 'risoluzione' e' passata da 0,65 s a 7,22 s (misure entrambe della stick, log 23:57 e 00:28)
# quando l'import di requests si e' spostato li' dentro. Quindi qualcuno sveglia la rete su un widget
# che dovrebbe essere tutto in cache -- e finche' non sappiamo CHI, qualunque correzione sarebbe a
# indovinare. La riga si scrive una sola volta per interprete: costa un log, non un ciclo.
_REQUESTS = [None]

def import_requests(who=''):
	# Dal lotto 84 NON importa piu' requests: torna modules.http_client, che espone Session con la
	# stessa superficie usata nel progetto. Il nome resta perche' trakt_api chiama
	# import_requests('trakt_api').Session(). Misurato: requests = 337 moduli, http.client = 66.
	if _REQUESTS[0] is None:
		from time import perf_counter as _pc
		_t = _pc()
		from modules import http_client
		_REQUESTS[0] = http_client
		try: perf_log('FenLight PERF HTTP', 'client http importato in %.0f ms | primo richiedente: %s' % ((_pc() - _t) * 1000, who or '?'))
		except: pass
	return _REQUESTS[0]

def import_requests_real(who=''):
	# La libreria vera, per i pochi usi che il nostro client non copre: al momento solo il download
	# in streaming di advanced_settings (iter_content). Tenuta separata cosi' che si veda subito, in
	# un log, se qualcuno la risveglia senza accorgersene.
	from time import perf_counter as _pc
	_t = _pc()
	import requests
	try: perf_log('FenLight PERF REQUESTS', 'requests VERO importato in %.0f ms | richiedente: %s' % ((_pc() - _t) * 1000, who or '?'))
	except: pass
	return requests

def make_session(url='https://'):
	return import_requests('make_session(%s)' % url).Session()

def make_playlist(playlist_type='video'):
	return PlayList(playlist_type_dict[playlist_type])

def convert_language(lang):
	return convertLanguage(lang, 1)

def supported_media():
	return getSupportedMedia('video')

def path_exists(path):
	return exists(path)

def open_file(_file, mode='r'):
	return File(_file, mode)

def copy_file(source, destination):
	return copy(source, destination)

def delete_file(_file):
	delete(_file)

def delete_folder(_folder, force=False):
	rmdir(_folder, force)

def rename_file(old, new):
	rename(old, new)

def list_dirs(location):
	return listdir(location)

def make_directory(path):
	mkdir(path)

def make_directories(path):
	mkdirs(path)

def translate_path(path):
	return translatePath(path)

def sleep(time):
	return xbmc_sleep(time)

def execute_builtin(command, block=False):
	return executebuiltin(command, block)

def current_skin():
	return getSkinDir()

def get_window_id():
	return getCurrentWindowId()

def current_window_object():
	return Window(get_window_id())

def kodi_version():
	return _KODI_VERSION

def get_video_database_path():
	db_version = myvideos_db_paths.get(_KODI_VERSION)
	if db_version:
		return translate_path('special://profile/Database/MyVideos%s.db' % db_version)
	try:
		import re
		db_dir = translate_path('special://profile/Database/')
		db_files = [f for f in list_dirs(db_dir)[1] if re.match(r'MyVideos\d+\.db', f)]
		if db_files: return '%s%s' % (db_dir, sorted(db_files)[-1])
	except: pass
	return None

def show_busy_dialog():
	return execute_builtin('ActivateWindow(busydialognocancel)')

def hide_busy_dialog():
	execute_builtin('Dialog.Close(busydialognocancel)')
	execute_builtin('Dialog.Close(busydialog)')

def close_dialog(dialog, block=False):
	execute_builtin('Dialog.Close(%s,true)' % dialog, block)

def close_all_dialog():
	execute_builtin('Dialog.Close(all,true)')

def run_addon(addon='plugin.video.fenlight', block=False):
	return execute_builtin('RunAddon(%s)' % addon, block)

def external():
	return 'fenlight' not in get_infolabel('Container.PluginName')

def home():
	return getCurrentWindowId() == 10000

def folder_path():
	return get_infolabel('Container.FolderPath')

def path_check(string):
	return string in folder_path()

def reload_skin():
	execute_builtin('ReloadSkin()')

# Nessuna ricostruzione di interfaccia mentre un video e' in riproduzione. UpdateLibrary e' un evento
# GLOBALE: ricostruisce ogni widget della schermata, ognuno con un interprete Python nuovo, e su un
# dispositivo debole ruba alla decodifica proprio la CPU che le serve (sul Mi Stick si vede come
# 'large audio sync error' e 'timeout waiting for buffer'). La richiesta non viene persa: si annota qui
# e il player la esegue alla chiusura della riproduzione (FenLightPlayer.flush_pending_refresh).
PENDING_REFRESH_PROP = 'fenlight.refresh_pending'
# Gli id che accompagnano un refresh rimandato: senza di loro il rinvio degrada in ricostruzione
# globale, buttando via un'informazione che avevamo gia'. Vedi kodi_refresh_ids e WidgetRefresher.
PENDING_IDS_PROP = 'fenlight.refresh_pending_ids'
# Le AZIONI che accompagnano un refresh rimandato (lotto 119). Gemella esatta di PENDING_IDS_PROP e
# per lo stesso motivo: gli id da soli non sanno dire 'ricostruisci il widget della watchlist' o
# 'ricostruisci continua a guardare' quando il titolo cambiato non e' ANCORA nella lista. Finche'
# questo canale non esisteva, un rinvio che nasceva da un'azione la perdeva per strada e a valle
# restava solo l'elenco degli id -- cioe' proprio il criterio che in aggiunta non puo' funzionare.
PENDING_ACTIONS_PROP = 'fenlight.refresh_pending_actions'
# Lo scope che ha PRODOTTO un rinvio, quando a produrlo e' stata la rete di sicurezza qui sotto. Quel
# riarmo e' per definizione lavoro destinato a un'ALTRA finestra: consumarlo dove e' nato non fa
# niente di utile e lo rimette in coda identico, cioe' un ciclo a ogni giro di WidgetRefresher (10 s).
# Non serviva finche' il rinvio si consumava solo sulla Home, dove questa rete non scatta mai.
# Un rinvio depositato dal monitor Trakt e' invece valido ovunque, e infatti azzera questa marca.
PENDING_SCOPE_PROP = 'fenlight.refresh_pending_scope'
# Nella vista "Combined" della finestra Video il pannello episodi NON e' il contenitore della finestra:
# e' un pannello della skin il cui <content> vale $INFO[Container(52X).ListItem.FolderPath], cioe' la
# URL della stagione a fuoco. Container.Refresh ricostruisce la lista stagioni, ma quella URL torna
# IDENTICA e Kodi non ha motivo di ricaricare il pannello: misurato il 24/08 alle 16:49, dopo
# 'segna come visto' su S1E2 si e' ricostruita solo build_season_list e il badge dell'episodio e'
# rimasto fermo finche' l'utente non e' uscito e rientrato nella serie.
# Rimedio: seasons.py accoda questo nonce alla URL di ogni stagione. Cambiarlo cambia la FolderPath,
# quindi il pannello si ricarica da solo -- stesso principio del token pagine dei widget. 'reload' e'
# in paginator._VOLATILE_PARAMS, quindi non entra nella chiave del widget ne' nella paginazione.
PANEL_RELOAD_PROP = 'fenlight.panel_reload'

# Riproduzione in corso, letta SENZA toccare la GUI (lotto 111).
#
# playback_active() qui sotto usa get_visibility, cioe' chiede il lock grafico. Dal thread di un
# plugin che sta costruendo una cartella e' la mossa vietata descritta nel commento di
# end_directory: il thread GUI di Kodi e' fermo ad aspettare PROPRIO quella cartella. Questa
# proprieta' di finestra risponde alla stessa domanda con una lettura che non attraversa nulla.
#
# Chi la alza: modules/player.py subito PRIMA di consegnare l'URL a Kodi (l'istante esatto in cui
# la scelta dell'utente diventa riproduzione) e service.py su Player.OnPlay, per la riproduzione
# che non parte da noi. Chi la abbassa: service.py su Player.OnStop e media_watched_marker.
PLAYBACK_ACTIVE_PROP = 'fenlight.playback.active'

def playback_running():
	return get_property(PLAYBACK_ACTIVE_PROP) == 'true'

# Istante in cui la riproduzione e' stata dichiarata attiva, e istante del Select (lotto 113).
# Servono alla DIAGNOSTICA: la riga PERF di ogni costruzione stampa la distanza da questi due
# momenti, cosi' il prossimo log dice quanto lavoro di interfaccia cade davvero nella finestra di
# transizione -- Select -> apertura sorgenti -> Player.OnPlay -> schermo intero. E' la sola finestra
# in cui i widget si ricostruiscono: durante il fullscreen i provider non si svegliano mai.
PLAYBACK_START_PROP = 'fenlight.perf.playstart'
SELECT_PROP = 'fenlight.perf.select'

def mark_playback_start():
	set_property(PLAYBACK_ACTIVE_PROP, 'true')
	try:
		from time import time
		set_property(PLAYBACK_START_PROP, str(time()))
	except: pass

# Bandiera di refresh in posto. Il nome e' paginator.PG_REFRESH_PROP, ripetuto qui alla lettera
# perche' kodi_utils non puo' importare paginator (sarebbe un ciclo, e 1206 righe caricate a ogni
# invocazione). service.py usa la stessa stringa su Player.OnStop.
PG_REFRESH_FLAG = 'fenlight.pg.refresh'

def mark_inplace_rebuild():
	"""Dichiara che le prossime ricostruzioni sono un REFRESH IN POSTO, non l'apertura di un widget.

	get_pages, quando trova questa bandiera, ricostruisce alla LUNGHEZZA CORRENTE invece che al
	default: gli elementi restano fermi dove sono e il fuoco e' preservato. E' lo stesso meccanismo
	del lotto 112 alla chiusura del player, esteso all'altro estremo della riproduzione.

	hold_refresh_flag scrive una SCADENZA e torna subito -- nessuna attesa dentro l'invocazione,
	e a spegnere la bandiera pensa WidgetRefresher, che gira gia' ogni 10 s. La finestra di 20 s
	copre l'intera transizione misurata: fra il Select (17:46:50) e Player.OnPlay (17:46:59)
	passano nove secondi, e altri cinque fino allo schermo intero.
	"""
	try:
		from time import time
		set_property(SELECT_PROP, str(time()))
	except: pass
	hold_refresh_flag(PG_REFRESH_FLAG)

# Nome della proprieta' con cui una build dichiara "sono partita", per widget. Definito QUI e non
# in paginator perche' lo rileggono anche moduli che non possono permettersi di caricarne le 1206
# righe. paginator.LASTBUILD_PROP lo rilegge da qui: una definizione sola.
PG_LASTBUILD_PROP = 'fenlight.pg.%s.lastbuild'

def playback_active():
	return get_visibility('Player.HasVideo')

def _defer_refresh_if_playing(kind):
	if not playback_active(): return False
	# Questo rinvio non porta id con se': gli eventuali id di un rinvio precedente vanno tolti, o
	# WidgetRefresher ricaricherebbe i contenitori del titolo SBAGLIATO invece di ricadere sul globale.
	clear_property(PENDING_IDS_PROP)
	clear_property(PENDING_ACTIONS_PROP)
	clear_property(PENDING_SCOPE_PROP)
	set_property(PENDING_REFRESH_PROP, kind)
	logger('Fen Light', 'DIAG refresh: RIMANDATO (%s), riproduzione in corso' % kind)
	return True

# Istante dell'ultima ricostruzione globale effettivamente eseguita. Serve a chi puo' innescarne una
# per un cambiamento che potrebbe essere gia' stato mostrato: al momento il monitor Trakt, che a fine
# riproduzione rileva come 'cambiamento' lo scrobble che abbiamo appena mandato noi -- vedi TraktMonitor.
LAST_REFRESH_PROP = 'fenlight.refresh.last'
# Due ricostruzioni globali che si accavallano sono la STESSA ricostruzione. Non e' un'ipotesi: nel
# log del Mac del 21/08 23:50 le due UpdateLibrary post-riproduzione distavano 282 ms -- il flush di
# fine film e il monitor Trakt che rileggeva il nostro stesso scrobble. Chi arriva primo ricostruisce,
# il secondo si accoda a vuoto. La finestra e' corta apposta: sopprime solo le collisioni, non un
# cambiamento davvero diverso arrivato qualche secondo dopo.
REFRESH_COALESCE_SECONDS = 5
# COSA ha coperto l'ultima ricostruzione: '*' se globale, altrimenti gli id ricaricati. Senza questo,
# l'accorpamento guardava solo l'orologio e buttava via la richiesta di un elemento DIVERSO arrivata
# entro la finestra. Nel log del 22/08 00:32 si vedeva come un'alternanza perfetta: azzerando
# l'avanzamento ogni ~4 s, la 1a passava, la 2a veniva saltata, la 3a passava... perche' una richiesta
# saltata non timbra l'orologio e la successiva si misurava dall'ultima ESEGUITA.
LAST_REFRESH_SCOPE_PROP = 'fenlight.refresh.last.scope'

# I widget leggono 'fenlight.pg.refresh' / 'fenlight.refresh_widgets' per capire che questa e' una
# ricostruzione IN CORSO e conservare le pagine gia' espanse. Finora il segnale si teneva alzato con
# sleep(2000) DENTRO l'invocazione del plugin, e la cosa era sbagliata due volte: teneva vivo un
# interprete Python per due secondi a non fare nulla -- su un dispositivo dove avviarne uno e' gia'
# caro e i processi contendono -- ed era comunque troppo corto, perche' sulla stick fra l'ordine di
# ricarica e la prima costruzione passano ELEVEN secondi (log 22/08: 23:15:09.240 -> 23:15:20.219),
# quindi la build leggeva il segnale gia' spento. Ora si scrive una SCADENZA e si esce subito: a
# spegnerlo pensa WidgetRefresher, che gira gia' ogni 10 s. L'interprete si libera e la finestra
# utile si allunga invece di accorciarsi.
REFRESH_FLAG_UNTIL_PROP = 'fenlight.refresh.flag.until'
REFRESH_FLAG_SECONDS = 20

def hold_refresh_flag(name):
	from time import time
	set_property(name, 'true')
	set_property(REFRESH_FLAG_UNTIL_PROP, str(time() + REFRESH_FLAG_SECONDS))

def refresh_flag_expired():
	from time import time
	try: return time() >= float(get_property(REFRESH_FLAG_UNTIL_PROP) or 0)
	except: return True

def _scope_items(ids, actions=()):
	# Le azioni si marcano con '@' per non confonderle con gli id: senza il prefisso un'azione e un
	# tmdb_id finirebbero nello stesso insieme e un accorpamento potrebbe scattare a sproposito.
	return set(str(i) for i in (ids or []) if i) | set('@%s' % a for a in (actions or ()) if a)

def _refresh_covered_by_last(ids, actions=()):
	# Vero solo se l'ultima ricostruzione ha gia' coperto TUTTO questo: o era globale, o lo conteneva.
	# Due richieste ravvicinate per elementi diversi restano due eventi distinti e vanno eseguite entrambe.
	scope = get_property(LAST_REFRESH_SCOPE_PROP)
	if scope == '*': return True
	items = _scope_items(ids, actions)
	if not scope or not items: return False
	return items.issubset(set(scope.split(',')))

def _stamp_refresh(scope):
	try:
		from time import time
		set_property(LAST_REFRESH_PROP, str(time()))
		set_property(LAST_REFRESH_SCOPE_PROP, scope)
	except: pass

def stamp_startup_rebuild():
	# All'avvio Kodi costruisce da sola TUTTI i widget della schermata: e' una ricostruzione globale a
	# tutti gli effetti, solo che non passa da noi e quindi non timbrava niente. Conseguenza misurata
	# (log 23/08 20:57): la prima sincronizzazione Trakt dopo l'avvio trovava refresh_age() = 1e9 --
	# nessuna ricostruzione registrata -- superava SEMPRE la guardia dei 30 s e ordinava UpdateLibrary
	# 15 s dentro la sessione, sopra la costruzione iniziale ancora in corso. I widget 91378 e 101881
	# risultavano costruiti DUE volte in quindici secondi, a ogni singolo avvio, senza eccezioni.
	# Timbrando qui, quella prima sincronizzazione si accorpa e salta il doppione; una modifica Trakt
	# davvero fatta altrove arriva comunque, perche' dopo TRAKT_REFRESH_COALESCE la guardia riapre.
	_stamp_refresh('*')

def refresh_age():
	# Secondi trascorsi dall'ultima ricostruzione globale. Un numero enorme se non ne risulta nessuna,
	# cosi' chi lo interroga in caso di dubbio ricostruisce invece di saltare.
	try:
		from time import time
		return time() - float(get_property(LAST_REFRESH_PROP) or 0)
	except: return 1e9

# L'accorpamento serve a UN solo problema: due chiamanti automatici che reagiscono allo STESSO evento
# (fine riproduzione + monitor Trakt, che arrivano a un paio di secondi l'uno dall'altro). Non serve,
# ed e' anzi dannoso, quando a chiedere e' l'utente: due comandi consecutivi sono due eventi distinti
# anche quando toccano lo stesso titolo. Il 22/08 alle 11:52 "segna come visto" e subito dopo "segna
# come non visto" avevano lo stesso id, e il secondo e' stato ingoiato: l'operazione era andata a buon
# fine su Trakt ma l'interfaccia non lo mostrava. Da qui coalesce=False su tutto cio' che nasce da un
# comando dell'utente.
def kodi_refresh(coalesce=True):
	# Global soft refresh (Trakt monitor / periodic WidgetRefresher). Flag the rebuild as an in-place
	# refresh so interactive widgets keep their already-expanded page count instead of collapsing back to
	# the initial batch (which would shrink the container and bounce the focus). The flag is held only for
	# the short window in which the widget builds read it, then cleared. A genuine fresh open carries no
	# flag, so it still starts from the initial batch. Mirrors the existing 'fenlight.refresh_widgets' hold.
	if _defer_refresh_if_playing('kodi_refresh'): return
	# Si azzera comunque: la richiesta rimandata e' soddisfatta dalla ricostruzione appena avvenuta.
	# Lasciarla accesa farebbe scattare la rete di sicurezza del WidgetRefresher, cioe' una TERZA onda.
	clear_property(PENDING_REFRESH_PROP)
	clear_property(PENDING_IDS_PROP)
	clear_property(PENDING_ACTIONS_PROP)
	age = refresh_age()
	# Si accorpa solo dietro un'altra ricostruzione GLOBALE: quella e' davvero un superset. Dietro una
	# mirata no -- la globale potrebbe riguardare tutt'altro, e saltarla lo perderebbe.
	if coalesce and age < REFRESH_COALESCE_SECONDS and get_property(LAST_REFRESH_SCOPE_PROP) == '*':
		logger('Fen Light', 'kodi_refresh accorpato: ricostruzione globale %.2fs fa' % age)
		return
	hold_refresh_flag('fenlight.pg.refresh')
	# NOTA (lotto 43): qui era stato messo Container.Refresh quando la finestra e' la Video, per non
	# perdere il fuoco a fine episodio. Ritirato: Container.Refresh ricarica SOLO la cartella aperta,
	# mentre le cartelle padre restano quelle in cache -- in finestra Video end_directory usa
	# cacheToDisc=True -- e cosi' il badge "episodi rimanenti" della serie non si aggiornava finche'
	# non la si riapriva. Un badge sbagliato e' correttezza, il fuoco perso e' comodita': vince la
	# correttezza. Il fuoco resta un problema aperto, da risolvere conservando la posizione, non
	# rinunciando all'aggiornamento.
	_stamp_refresh('*')
	logger('Fen Light', 'DIAG refresh: GLOBALE (UpdateLibrary) | finestra=%s' % getCurrentWindowId())
	# Timbro per la diagnostica: UpdateLibrary non lascia traccia nel path, quindi le ricostruzioni
	# che innesca arrivavano nel log etichettate 'apertura/re-show', identiche a quelle spontanee di
	# Kodi. Nel log del 23/08 le due cose erano indistinguibili e questo rendeva impossibile dire
	# quante ricostruzioni fossero davvero nostre. Vedi paginator._build_cause.
	try:
		from time import time
		set_property('fenlight.diag.updatelibrary', str(time()))
	except: pass
	execute_builtin('UpdateLibrary(video,special://skin/foo)')

# AZIONE di 'continua a guardare' (lotto 114). Come 'trakt_watchlist', questo widget cambia
# COMPOSIZIONE e non stato: azzerando l'avanzamento di un film quel film ESCE dalla lista, e la
# regola per id non basta a decidere se va ricostruito. Il nome vive qui perche' lo usano quattro
# moduli che non hanno motivo di importarsi a vicenda (indexers/continue_watching, watched_status,
# player, apis/trakt_api).
CONTINUE_WATCHING_ACTION = 'continue_watching'

# AZIONE della watchlist di Trakt. Stesso nome per DUE widget -- film e serie -- che vanno colpiti
# separatamente: vedi qualify_action e paginator._action_matches.
WATCHLIST_ACTION = 'trakt_watchlist'

def qualify_action(action, media_type):
	"""Azione qualificata per tipo di media: 'trakt_watchlist' + 'movie' -> 'trakt_watchlist:movie'.

	Il separatore ':' e' una convenzione con UN solo proprietario, questa funzione, perche' la
	compongono i costruttori (indexers/movies, indexers/tvshows) e la interroga chi chiede la ricarica
	(apis/trakt_api): due convenzioni diverse non darebbero nessun errore, solo un widget che non si
	aggiorna mai. media_type e' 'movie' o 'tvshow', gli stessi due valori del resto del codice.
	"""
	if not action: return None
	return '%s:%s' % (action, media_type)

def episode_uid(tmdb_id, season, episode):
	"""Identita' di UN episodio nel canale della ricarica mirata: 'tmdb:stagione:episodio'.

	Il tmdb_id di un episodio E' quello della serie: senza questa forma, nel canale degli id
	'S03E04 di X in pausa' e 'la serie X' sono la stessa stringa, e un avanzamento su un episodio
	ricarica OGNI widget che contenga quella serie. Vive qui e non in paginator perche' la compongono
	due mondi che non devono importarsi a vicenda: chi PUBBLICA (paginator._publish_ids, leggendola
	dagli URL degli elementi) e chi CHIEDE (apis/trakt_api, leggendola dalle righe della tabella
	progress). Stagione ed episodio sono quelli REMAPPATI su tvdb -- e' cio' che finisce nella tabella
	progress e quindi anche negli URL costruiti a partire da lei.

	Torna None su valori non numerici: chi la chiama ricade sul solo livello serie, che e' il
	comportamento di prima e non peggiora nulla.
	"""
	try: return '%s:%s:%s' % (int(tmdb_id), int(season), int(episode))
	except: return None

def kodi_refresh_ids(ids, actions=(), coalesce=True):
	# Ricarica MIRATA: ricostruisce i soli contenitori che contengono uno degli id cambiati -- piu'
	# quelli la cui AZIONE e' fra le richieste, per i casi in cui a cambiare e' la composizione della
	# lista invece dello stato di un elemento (aggiunta alla watchlist) -- invece di
	# sparare UpdateLibrary, che e' globale. Chiudere un film cambia UN elemento; oggi se ne
	# ricostruiscono centinaia su tutti i widget della schermata.
	# Se il sondaggio non identifica nessun contenitore (skin diversa, ids sbagliati, infolabel che non
	# risolve fuori dal fuoco) si ricade sul globale: non puo' comportarsi peggio di prima.
	if _defer_refresh_if_playing('kodi_refresh'): return
	clear_property(PENDING_REFRESH_PROP)
	clear_property(PENDING_IDS_PROP)
	clear_property(PENDING_ACTIONS_PROP)
	# Stessa finestra di kodi_refresh(): due ricostruzioni accavallate sono la stessa, e non importa
	# se una e' mirata e l'altra globale -- chi arriva secondo lavorerebbe a vuoto.
	age = refresh_age()
	if coalesce and age < REFRESH_COALESCE_SECONDS and _refresh_covered_by_last(ids, actions):
		logger('Fen Light', 'refresh mirato accorpato: gli stessi id ricostruiti %.2fs fa' % age)
		return
	# Dentro la finestra Video (10025) la lista aperta NON e' un widget: e' il contenitore della
	# finestra, e il token delle pagine non lo governa. Finora paginator tornava 0 e QUI si ricadeva
	# sul globale, cioe' UpdateLibrary: marcare un episodio stando dentro la serie ricostruiva ogni
	# widget video della skin, invisibili compresi. Nel log della stick del 22/08 alle 23:16:29 si
	# legge 'nessun contenitore identificato, si ricostruisce tutto' seguito dallo scan globale: e' il
	# caso in cui l'utente se ne accorge di piu' ed era anche il piu' costoso di tutti.
	# Container.Refresh ricarica SOLO la cartella aperta -- esattamente quella che si sta guardando --
	# e ne conserva la posizione, quindi rimedia anche al fuoco perso. Le cartelle padre non le tocca:
	# per quelle vedi cacheToDisc in seasons.py/episodes.py, ora False in finestra Video, cosi'
	# tornando indietro Kodi le rilegge invece di servirle dalla cache (era il difetto del lotto 43,
	# che aveva fatto ritirare Container.Refresh la prima volta).
	if getCurrentWindowId() == 10025:
		_stamp_refresh(','.join(sorted(_scope_items(ids, actions))))
		logger('Fen Light', 'DIAG refresh: MIRATO finestra Video (Container.Refresh sulla lista aperta) | id=%s azioni=%s' % (len(ids or []), len(actions or ())))
		# Il nonce va cambiato PRIMA del refresh: la lista stagioni si ricostruisce subito dopo e deve
		# gia' pubblicare le URL nuove, altrimenti il pannello episodi resta sulla vecchia FolderPath.
		from time import time as _now
		set_property(PANEL_RELOAD_PROP, '%d' % (_now() * 1000))
		execute_builtin('Container.Refresh')
		# Container.Refresh ricarica SOLO la cartella aperta. I widget della schermata principale --
		# 'continua a guardare' e il conteggio episodi rimanenti sulla serie -- non sono raggiungibili
		# da qui, e questo ramo usciva senza toccarli. Due guardie a valle davano poi per scontato che
		# ci avessimo pensato noi -- entrambe fondate su self_mark_recent(), in trakt_api (rebuild
		# saltato) e in service.py (refresh saltato) -- e sopprimevano le due occasioni successive di
		# rimediare. La loro premessa e' vera per il DATABASE, falsa per lo SCHERMO. Esito misurato il
		# 24/08 alle 02:36: segnando un episodio come NON visto, Trakt si aggiornava ma
		# 'continua a guardare' e il badge della serie restavano fermi a tempo indeterminato.
		# La proprieta' qui sotto e' lo stesso canale gia' usato per il refresh rimandato durante la
		# riproduzione: WidgetRefresher (service.py) la vede entro 10 s e lancia 'refresh_widgets'.
		# Costo: un aggiornamento widget mentre non sono nemmeno a schermo, fuori dal percorso critico.
		# Gli id vanno tramandati, non buttati (lotto 60). Finora questo ramo alzava solo la bandiera e
		# WidgetRefresher rispondeva con refresh_widgets, cioe' UpdateLibrary globale: misurato il
		# 24/08 alle 15:19, un refresh MIRATO su 1 titolo diventava una ricostruzione di tutto solo
		# perche' l'utente si trovava dentro la finestra Video. L'informazione c'era, la buttavamo noi.
		set_property(PENDING_IDS_PROP, ','.join(str(i) for i in (ids or []) if i))
		set_property(PENDING_ACTIONS_PROP, ','.join(str(a) for a in (actions or ()) if a))
		set_property(PENDING_REFRESH_PROP, 'kodi_refresh_ids')
		return
	# Stesso segnale che alza refresh_widgets(): i widget 'random' lo leggono per riestrarre
	# (random_lists.py:84 e :270). Va tenuto o cambierebbe il loro comportamento di riflesso.
	hold_refresh_flag('fenlight.refresh_widgets')
	try:
		from modules import paginator
		hit = paginator.refresh_containers_for_ids(ids, actions)
		seen_any, other = paginator.LAST_SEEN_ANY[0], paginator.LAST_OTHER_HITS[0]
	except:
		hit, seen_any, other = 0, False, 0
	# LOTTO 119 -- il fallback globale scatta solo se non si e' potuto verificare NIENTE, da nessuna
	# parte. Prima bastava 'zero contenitori ricaricati a schermo', che confonde due esiti opposti:
	#   - nessun contenitore nostro in questa finestra, e nessuna altra finestra raggiunta
	#     -> non sappiamo niente, il globale e' l'unica rete;
	#   - contenitori identificati e SCARTATI perche' dimostrato che non contengono i titoli cambiati
	#     -> e' la risposta, non un fallimento. Ricostruire tutto qui vuol dire buttare via proprio il
	#     lavoro appena fatto, ed e' il modo in cui una ricarica mirata tornava a essere globale.
	#   - niente a schermo ma ALTRE finestre gia' invalidate -> il lavoro e' fatto, si rileggeranno
	#     da sole al rientro; un UpdateLibrary adesso non aggiungerebbe nulla.
	if not hit and not seen_any and not other:
		logger('Fen Light', 'DIAG refresh: nessun contenitore identificato, si ricade sul GLOBALE | id=%s azioni=%s finestra=%s'
				% (len(ids or []), len(actions or ()), getCurrentWindowId()))
		kodi_refresh(coalesce)
		return
	if not hit:
		# Niente da ricostruire a schermo, e non e' un errore: si timbra comunque, o il monitor Trakt
		# sparerebbe il globale un istante dopo per lo stesso evento.
		_stamp_refresh(','.join(sorted(_scope_items(ids, actions))))
		logger('Fen Light', 'DIAG refresh: MIRATO senza esito a schermo (%s) | altre finestre %s | id=%s azioni=%s finestra=%s'
				% ('nessun contenitore contiene i titoli cambiati' if seen_any else 'nessun contenitore nostro qui',
					other, len(ids or []), len(actions or ()), getCurrentWindowId()))
		return
	# Conta come ricostruzione ai fini dell'accorpamento: senza questo, il monitor Trakt sparerebbe
	# comunque il globale un secondo dopo per lo stesso evento e il lavoro mirato sarebbe sprecato.
	_stamp_refresh(','.join(sorted(_scope_items(ids, actions))))
	window_id = getCurrentWindowId()
	# Le infolabel dei contenitori risolvono SOLO per la finestra a schermo, quindi 'hit' copre solo
	# quella. Il resto lo fa refresh_containers_for_ids sul censimento (lotto 69): i token delle altre
	# finestre vengono cambiati adesso, nello stesso istante, e Kodi li rilegge quando quelle finestre
	# tornano a schermo. Niente due tempi, e nessuna finestra puo' restare disallineata.
	# Rete di sicurezza per il solo caso in cui non ci fosse NIENTE di censito da raggiungere -- una
	# finestra mai aperta in questa sessione. Se il censimento ha risposto, un rinvio sarebbe lavoro
	# doppio sugli stessi contenitori.
	if window_id != 10000 and not other:
		set_property(PENDING_IDS_PROP, ','.join(str(i) for i in (ids or []) if i))
		set_property(PENDING_ACTIONS_PROP, ','.join(str(a) for a in (actions or ()) if a))
		set_property(PENDING_REFRESH_PROP, 'kodi_refresh_ids')
		# Marca la finestra d'origine: questo riarmo serve alle ALTRE, e senza la marca verrebbe
		# riconsumato qui ogni 10 s all'infinito. Vedi PENDING_SCOPE_PROP.
		try:
			from modules import paginator as _pg
			set_property(PENDING_SCOPE_PROP, _pg.ctl_scope())
		except: pass
	logger('Fen Light', 'DIAG refresh: MIRATO %s contenitori ricaricati | altre finestre %s | id=%s azioni=%s finestra=%s%s'
			% (hit, other, len(ids or []), len(actions or ()), window_id,
				'' if (window_id == 10000 or other) else ' | nessuna finestra censita, resto RIMANDATO alla Home'))

def refresh_widgets(show_notification='false', coalesce=True):
	# Due padroni: la voce di menu "Aggiorna widget" (comando esplicito dell'utente, da eseguire
	# sempre) e il servizio periodico (automatico, accorpabile). Al router arrivano identici, percio'
	# la voce di menu si dichiara con user=true nell'URL. Accorpare una richiesta esplicita di
	# aggiornamento sarebbe il caso peggiore possibile: l'utente ha chiesto proprio quello.
	if _defer_refresh_if_playing('refresh_widgets'): return
	clear_property(PENDING_REFRESH_PROP)
	clear_property(PENDING_IDS_PROP)
	clear_property(PENDING_ACTIONS_PROP)
	hold_refresh_flag('fenlight.refresh_widgets')
	sleep(250)
	run_plugin({'mode': 'kodi_refresh', 'coalesce': 'true' if coalesce else 'false'}, block=True)
	if show_notification == 'true': notification('Widgets Refreshed', 2500)

def run_plugin(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('RunPlugin(%s)' % params, block)

def container_update(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('Container.Update(%s)' % params, block)

def activate_window(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('ActivateWindow(Videos,%s,return)' % params, block)

def container_refresh():
	return execute_builtin('Container.Refresh')

def container_refresh_input(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('Container.Refresh(%s)' % params, block)

def replace_window(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('ReplaceWindow(Videos,%s)' % params, block)

def disable_enable_addon(addon_name='plugin.video.fenlight'):
	import json
	try:
		execute_JSON(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled', 'params': {'addonid': addon_name, 'enabled': False}}))
		execute_JSON(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled', 'params': {'addonid': addon_name, 'enabled': True}}))
	except: pass

def update_local_addons():
	execute_builtin('UpdateLocalAddons', True)
	sleep(2500)
 
def update_kodi_addons_db(addon_name='plugin.video.fenlight'):
	import time
	import sqlite3 as database
	try:
		date = time.strftime('%Y-%m-%d %H:%M:%S')
		dbcon = database.connect(translate_path('special://database/Addons33.db'), timeout=40.0)
		dbcon.execute("INSERT OR REPLACE INTO installed (addonID, enabled, lastUpdated) VALUES (?, ?, ?)", (addon_name, 1, date))
		dbcon.close()
	except: pass

def get_jsonrpc(request):
	import json
	response = execute_JSON(json.dumps(request))
	result = json.loads(response)
	return result.get('result', None)

def jsonrpc_get_directory(directory, properties=['title', 'file', 'thumbnail']):
	command = {'jsonrpc': '2.0', 'id': 1, 'method': 'Files.GetDirectory', 'params': {'directory': directory, 'media': 'files', 'properties': properties}}
	try: results = [i for i in get_jsonrpc(command).get('files') if i['file'].startswith('plugin://') and i['filetype'] == 'directory']
	except: results = None
	return results

def jsonrpc_get_addons(_type, properties=['thumbnail', 'name']):
	command = {'jsonrpc': '2.0', 'method': 'Addons.GetAddons','params':{'type':_type, 'properties': properties}, 'id': '1'}
	results = get_jsonrpc(command).get('addons')
	return results

def jsonrpc_get_system_setting(setting_id, setting_value=''):
	command = {'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue', 'params': {'setting': setting_id}}
	try: result = get_jsonrpc(command)['value']
	except: result = setting_value
	return result

def open_settings():
	from windows.base_window import open_window
	open_window(('windows.settings_manager', 'SettingsManager'), 'settings_manager.xml')

def external_scraper_settings():
	try:
		external = get_property('fenlight.external_scraper.module')
		if external in ('empty_setting', ''): return
		execute_builtin('Addon.OpenSettings(%s)' % external)
	except: pass

def progress_dialog(heading='', icon=None):
	from threading import Thread
	from windows.base_window import create_window
	progress_dialog = create_window(('windows.progress', 'Progress'), 'progress.xml', heading=heading, icon=icon or addon_icon())
	Thread(target=progress_dialog.run).start()
	return progress_dialog

def select_dialog(function_list, **kwargs):
	from windows.base_window import open_window
	selection = open_window(('windows.default_dialogs', 'Select'), 'select.xml', **kwargs)
	if selection in (None, []): return selection
	if kwargs.get('multi_choice', 'false') == 'true': return [function_list[i] for i in selection]
	return function_list[selection]

def confirm_dialog(heading='', text='Are you sure?', ok_label='OK', cancel_label='Cancel', default_control=11):
	from windows.base_window import open_window
	kwargs = {'heading': heading, 'text': text, 'ok_label': ok_label, 'cancel_label': cancel_label, 'default_control': default_control}
	return open_window(('windows.default_dialogs', 'Confirm'), 'confirm.xml', **kwargs)

def ok_dialog(heading='', text='No Results', ok_label='OK'):
	from windows.base_window import open_window
	kwargs = {'heading': heading, 'text': text, 'ok_label': ok_label}
	return open_window(('windows.default_dialogs', 'OK'), 'ok.xml', **kwargs)

def show_text(heading, text=None, file=None, font_size='small', kodi_log=False):
	from windows.base_window import open_window
	heading = heading.replace('[B]', '').replace('[/B]', '')
	if file:
		with open(file, encoding='utf-8') as r: text = r.readlines()
	if kodi_log:
		confirm = confirm_dialog(text='Show Log Errors Only?', ok_label='Yes', cancel_label='No')
		if confirm == None: return
		if confirm: text = [i for i in text if any(x in i.lower() for x in ('exception', 'error', '[test]'))]
	text = ''.join(text)
	return open_window(('windows.textviewer', 'TextViewer'), 'textviewer.xml', heading=heading, text=text, font_size=font_size)

def notification(line1, time=5000, icon=None):
	kodi_dialog().notification('Fen Light', line1, icon or addon_icon(), time)

def timeIt(func):
	# Thanks to 123Venom
	import time
	fnc_name = func.__name__
	def wrap(*args, **kwargs):
		started_at = time.time()
		result = func(*args, **kwargs)
		logger('%s.%s' % (__name__ , fnc_name), (time.time() - started_at))
		return result
	return wrap

def volume_checker():
	# 0% == -60db, 100% == 0db
	try:
		if get_property('fenlight.playback.volumecheck_enabled') == 'false' or get_visibility('Player.Muted'): return
		from modules.utils import string_alphanum_to_num
		max_volume = min(int(get_property('fenlight.playback.volumecheck_percent') or '50'), 100)
		if int(100 - (float(string_alphanum_to_num(get_infolabel('Player.Volume').split('.')[0]))/60)*100) > max_volume: execute_builtin('SetVolume(%d)' % max_volume)
	except: pass

def focus_index(index):
	current_window = current_window_object()
	focus_id = current_window.getFocusId()
	try: current_window.getControl(focus_id).selectItem(index)
	except: pass

def get_all_icon_vars(include_values=False):
	if include_values: return [(k, v) for k, v in vars(icons).items() if not k.startswith('__')]
	else: return [k for k, v in vars(icons).items() if not k.startswith('__')]

def toggle_language_invoker():
	from xml.dom.minidom import parse as mdParse
	close_all_dialog()
	addon_xml = translate_path('special://home/addons/plugin.video.fenlight/addon.xml')
	root = mdParse(addon_xml)
	invoker_instance = root.getElementsByTagName('reuselanguageinvoker')[0].firstChild
	current_invoker_setting = invoker_instance.data
	new_value = invoker_switch_dict[current_invoker_setting]
	if not confirm_dialog(text='Turn [B]Reuse Langauage Invoker[/B] %s?' % ('On' if new_value == 'true' else 'Off')): return
	invoker_instance.data = new_value
	new_xml = str(root.toxml()).replace('<?xml version="1.0" ?>', '')
	with open(addon_xml, 'w') as f: f.write(new_xml)
	execute_builtin('ActivateWindow(Home)', True)
	update_local_addons()
	disable_enable_addon()

def upload_logfile(params):
	import json
	# Azione manuale e rara, ma il nostro client la copre (post + .json()): niente requests.
	requests = import_requests('upload_logfile')
	log_files = [('Current Kodi Log', 'kodi.log'), ('Previous Kodi Log', 'kodi.old.log')]
	list_items = [{'line1': i[0]} for i in log_files]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Choose Which Log File to Upload', 'narrow_window': 'true'}
	log_file = select_dialog(log_files, **kwargs)
	if log_file == None: return
	log_name, log_file = log_file
	if not confirm_dialog(heading=log_name): return
	show_busy_dialog()
	url = 'https://paste.kodi.tv/'
	log_file = translate_path('special://logpath/%s' % log_file)
	if not path_exists(log_file): return ok_dialog(text='Error. Log Upload Failed')
	try:
		with open_file(log_file) as f: text = f.read()
		UserAgent = 'Fenlight %s' % addon_version()
		response = requests.post('%s%s' % (url, 'documents'), data=text.encode('utf-8', errors='ignore'), headers={'User-Agent': UserAgent}).json()
		user_code = response['key']
		if 'key' in response:
			try:
				from modules.utils import copy2clip
				copy2clip('%s%s' % (url, user_code))
			except: pass
			ok_dialog(text='%s%s' % (url, user_code))
		else: ok_dialog(text='Error. Log Upload Failed')
	except: ok_dialog(text='Error. Log Upload Failed')
	hide_busy_dialog()

def fetch_kodi_imagecache(image):
	import sqlite3 as database
	result = None
	try:
		dbcon = database.connect(translate_path('special://database/Textures13.db'), timeout=40.0)
		dbcur = dbcon.cursor()
		dbcur.execute("SELECT cachedurl FROM texture WHERE url = ?", (image,))
		result = dbcur.fetchone()[0]
	except: pass
	return result