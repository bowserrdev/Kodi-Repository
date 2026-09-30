# -*- coding: utf-8 -*-
import json
from urllib.parse import unquote
from caches.main_cache import main_cache
from indexers.people import person_search
from indexers.easynews import search_easynews_image
from modules import kodi_utils
logger = kodi_utils.logger

close_all_dialog, external = kodi_utils.close_all_dialog, kodi_utils.external
build_url, kodi_dialog, execute_builtin, select_dialog = kodi_utils.build_url, kodi_utils.kodi_dialog, kodi_utils.execute_builtin, kodi_utils.select_dialog
notification, kodi_refresh = kodi_utils.notification, kodi_utils.kodi_refresh
get_icon = kodi_utils.get_icon
modal_dialog_present = kodi_utils.modal_dialog_present
clear_history_list = [('Clear Movie Search History', 'movie_queries'),
					('Clear TV Show Search History', 'tvshow_queries'),
					('Clear Anime Search History', 'anime_queries'),
					('Clear People Search History', 'people_queries'),
					('Clear Keywords Movie Search History', 'keyword_tmdb_movie_queries'),
					('Clear Keywords TV Show Search History', 'keyword_tmdb_tvshow_queries'),
					('Clear Easynews Search History', 'easynews_video_queries'),
					('Clear Easynews Search History', 'easynews_image_queries'),
					('Clear Trakt List Search History', 'trakt_list_queries')]

def get_key_id(params):
	close_all_dialog()
	params_key_id = params.get('key_id', None)
	key_id = params_key_id or kodi_dialog().input('')
	if not key_id: return
	key_id = unquote(key_id)
	media_type = params.get('media_type', '')
	search_type = params.get('search_type', 'media_title')
	string = None
	if search_type == 'media_title':
		if media_type == 'movie': url_params, string = {'mode': 'build_movie_list', 'action': 'tmdb_movies_search'}, 'movie_queries'
		elif media_type == 'tv_show': url_params, string = {'mode': 'build_tvshow_list', 'action': 'tmdb_tv_search'}, 'tvshow_queries'
		else: url_params, string = {'mode': 'build_tvshow_list', 'action': 'tmdb_anime_search'}, 'anime_queries'
	elif search_type == 'people': string = 'people_queries'
	elif search_type == 'tmdb_keyword':
		url_params, string = {'mode': 'navigator.keyword_results', 'media_type': media_type}, 'keyword_tmdb_%s_queries' % media_type
	elif search_type == 'easynews_video':
		url_params, string = {'mode': 'easynews.search_easynews'}, 'easynews_video_queries'
	elif search_type == 'easynews_image':
		url_params, string = {'mode': 'easynews.search_easynews_image'}, 'easynews_image_queries'
	elif search_type == 'trakt_lists':
		url_params, string = {'mode': 'trakt.list.search_trakt_lists'}, 'trakt_list_queries'
	if string: add_to_search(key_id, string)
	if search_type == 'people': return person_search(key_id)
	if search_type == 'easynews_image': return search_easynews_image(key_id)
	url_params.update({'query': key_id, 'key_id': key_id, 'name': 'Search Results for %s' % key_id})
	action = 'ActivateWindow(Videos,%s,return)' if external() else 'Container.Update(%s)'
	return execute_builtin(action % build_url(url_params))

def add_to_search(search_name, search_list):
	try:
		result = []
		cache = main_cache.get(search_list)
		if cache: result = cache
		if search_name in result: result.remove(search_name)
		result.insert(0, search_name)
		result = result[:50]
		main_cache.set(search_list, result, expiration=8760)
	except: return

def remove_from_search(params):
	try:
		result = main_cache.get(params['setting_id'])
		result.remove(params.get('key_id'))
		main_cache.set(params['setting_id'], result, expiration=8760)
		notification('Fatto', 2500)
		kodi_refresh(coalesce=False)
	except: return

def clear_search():
	try:
		list_items = [{'line1': item[0]} for item in clear_history_list]
		kwargs = {'items': json.dumps(list_items), 'narrow_window': 'true'}
		setting_id = select_dialog([item[1] for item in clear_history_list], **kwargs)
		if setting_id == None: return
		clear_all(setting_id)
	except: return

def clear_all(setting_id, refresh='false'):
	main_cache.set(setting_id, '', expiration=365)
	notification('Fatto', 2500)
	if refresh == 'true': kodi_refresh(coalesce=False)

# LE ETICHETTE DEI PANNELLI DEI FILTRI, una per chiave.
# Prima il titolo si RICAVAVA dalla chiave interna:
#     'with_genres'.replace('with_', '').replace('_', ' ').title()  ->  'Genres'
# cioe' non era un testo ma un effetto collaterale del nome di una variabile. Due conseguenze, e la
# seconda pesa piu' della prima: non si poteva tradurre, e soprattutto NON ERA LEGATO a quello che
# l'utente aveva appena letto. Si clicca "Generi Inclusi" e si apriva "Genres": due nomi per la stessa
# cosa, uno dei quali nessuno aveva mai scritto.
# Qui le etichette sono le STESSE STRINGHE delle righe del pannello (Includes_Search.xml,
# Search_Advanced_Panel), e ci deve restare: il titolo di un pannello e' il nome del filtro che si e'
# aperto. Lo verifica tests/test_etichette_filtri.py, che le confronta una per una con la skin.
ETICHETTE_FILTRI = {
    'with_year_start': 'Anno Inizio',
    'with_year_end': 'Anno Fine',
    'with_genres': 'Generi Inclusi',
    'without_genres': 'Generi Esclusi',
    'with_cast': 'Cast',
    'with_network': 'Network',
    'with_rating': 'Min Valutazione',
    'with_rating_votes': 'Voti Minimi',
    'with_sort': 'Ordina',
}

def select_discover_filter(params):
    import json, xbmcgui
    from modules import meta_lists as ml
    fk = params.get('filter', '')
    mt = params.get('media_type', 'movie')
    is_movie = (mt == 'movie')
    win = xbmcgui.Window(10000)
    prop_d = 'Discover.%s' % fk
    prop_u = 'Discover.%s.url' % fk
    if fk == 'with_released':
        if win.getProperty(prop_d):
            win.clearProperty(prop_d); win.clearProperty(prop_u)
        else:
            url = ('&primary_release_date.lte=[current_date]' if is_movie
                   else '&include_null_first_air_dates=false&first_air_date.lte=[current_date]')
            win.setProperty(prop_d, 'Yes'); win.setProperty(prop_u, url)
        return
    if fk == 'with_cast':
        name = kodi_dialog().input('Nome attore')
        if not name: return
        try:
            from apis.tmdb_api import tmdb_people_info
            results = tmdb_people_info(name)['results']
        except: return notification('Nessun risultato', 2500)
        if not results: return notification('Nessun risultato', 2500)
        # LA FOTO E I TITOLI NOTI SONO LA RISPOSTA, non un ornamento: la domanda che l'utente ha
        # davanti e' "quale dei tre omonimi e'?", e un elenco di soli nomi non la risponde. Fen Light
        # la risponde gia' nel suo Discover (windows/discover.py, casts) e i due pannelli aprono la
        # STESSA finestra, select.xml: bastava consegnarle le righe complete.
        # `known_for` porta 'title' per i film e 'name' per le serie: leggerne uno solo, come fa il
        # gemello, lascia senza sottotitolo chi ha fatto soltanto televisione.
        items = []
        for r in results:
            noti = [i.get('title') or i.get('name') for i in r.get('known_for', [])]
            noti = [t for t in noti if t and t != 'NA']
            items.append({'line1': r['name'],
                          'line2': ', '.join(noti),
                          'icon': ('https://image.tmdb.org/t/p/h632/%s' % r['profile_path']
                                   if r.get('profile_path') else get_icon('genre_family')),
                          'name': r['name'], 'id': str(r['id'])})
        # Un risultato solo non e' una scelta: non c'e' nessuna omonimia da sciogliere. Anche qui
        # come il gemello.
        if len(items) == 1: choice = items[0]
        else:
            choice = select_dialog(items, **{'items': json.dumps(items), 'heading': ETICHETTE_FILTRI['with_cast'],
                                             'enumerate': 'false', 'multi_line': 'true'})
        if choice:
            win.setProperty(prop_d, choice['name'])
            win.setProperty(prop_u, '&with_cast=%s' % choice['id'])
        return
    multi = False
    if fk == 'with_year_start':
        items = [{'name': str(i['name']), 'id': str(i['id'])} for i in (ml.years_movies if is_movie else ml.years_tvshows)]
        url_t = '&primary_release_date.gte=%s-01-01' if is_movie else '&first_air_date.gte=%s-01-01'
    elif fk == 'with_year_end':
        items = [{'name': str(i['name']), 'id': str(i['id'])} for i in (ml.years_movies if is_movie else ml.years_tvshows)]
        url_t = '&primary_release_date.lte=%s-12-31' if is_movie else '&first_air_date.lte=%s-12-31'
    elif fk in ('with_genres', 'without_genres'):
        items = [{'name': i['name'], 'id': str(i['id'])} for i in (ml.movie_genres if is_movie else ml.tvshow_genres)]
        url_t = '&with_genres=%s' if fk == 'with_genres' else '&without_genres=%s'
        multi = True
    elif fk == 'with_network':
        items = [{'name': i['name'], 'id': str(i['id'])} for i in sorted(ml.networks, key=lambda k: k['name'])]
        url_t = '&with_networks=%s'
    elif fk == 'with_rating':
        items = [{'name': str(float(i)), 'id': str(i)} for i in range(1, 11)]
        url_t = '&vote_average.gte=%s'
    elif fk == 'with_rating_votes':
        items = [{'name': '1', 'id': '1'}] + [{'name': str(i), 'id': str(i)} for i in range(50, 1001, 50)]
        url_t = '&vote_count.gte=%s'
    elif fk == 'with_sort':
        items = [{'name': i['name'], 'id': i['id']} for i in (ml.movie_sorts if is_movie else ml.tvshow_sorts)]
        url_t = '%s'
    else:
        return
    heading = ETICHETTE_FILTRI.get(fk, fk)
    kwargs = {'items': json.dumps([{'line1': i['name']} for i in items]), 'heading': heading, 'narrow_window': 'true'}
    if multi:
        kwargs['multi_choice'] = 'true'
        choice = select_dialog(items, **kwargs)
        if choice is not None:
            win.setProperty(prop_d, ', '.join(i['name'] for i in choice))
            win.setProperty(prop_u, url_t % ','.join(i['id'] for i in choice))
    else:
        choice = select_dialog(items, **kwargs)
        if choice is not None:
            win.setProperty(prop_d, choice['name'])
            win.setProperty(prop_u, url_t % choice['id'])

def launch_discover(params):
	import xbmc, xbmcgui
	mt = params.get('media_type', 'movie')
	is_movie = (mt == 'movie')
	win = xbmcgui.Window(10000)
	keys = ['with_year_start','with_year_end','with_genres','without_genres',
			'with_cast','with_network','with_rating','with_sort']
	user_fragments = ''.join(win.getProperty('Discover.%s.url' % k) for k in keys)
	xbmc.log('###AF3_DISCOVER### media_type=%s user_fragments=[%s]' % (mt, user_fragments), xbmc.LOGINFO)
	if not user_fragments: return notification('Imposta almeno un filtro', 2500)
	# LOTTO 440 -- LA RICERCA PRENDE POSSESSO PER PRIMA COSA, prima di toccare il fuoco. Il path di Discover si scrive
	# ~200 ms piu' giu' (dopo lo svuotamento della casella): se il possesso fosse solo il path, in quella finestra una
	# ricerca precedente ancora in attesa troverebbe il fuoco sulla barra messo da QUESTA, il path ancora suo, e
	# porterebbe il fuoco sui propri risultati vecchi (Firestick, 30/09 18:34:14.175). Vedi superata() sotto.
	from time import time as _ora
	lancio = repr(_ora())
	win.setProperty('FenLight.Discover.Lancio', lancio)
	import re
	from datetime import date
	today = date.today().strftime('%Y-%m-%d')
	fragments = user_fragments
	date_key = 'primary_release_date' if is_movie else 'first_air_date'
	date_match = re.search(r'&%s\.lte=(\d{4})-12-31' % date_key, fragments)
	if date_match and '%s-12-31' % date_match.group(1) > today:
		fragments = fragments.replace('&%s.lte=%s-12-31' % (date_key, date_match.group(1)), '&%s.lte=%s' % (date_key, today))
	elif not date_match:
		fragments += '&%s.lte=%s' % (date_key, today)
	if not is_movie:
		fragments += '&include_null_first_air_dates=false'
	fragments += '&vote_count.gte=100'
	# When the user picks no sort, force vote_average.desc as the TMDb candidate pool (TMDb would otherwise
	# default to popularity, surfacing what's trending now instead of the best films). The indexer then
	# re-orders each page by the more reliable IMDb rating (it derives the direction from this sort_by; see
	# discover_imdb_sort_from_url). Explicit non-rating sorts and Random keep the pure TMDb order.
	if '[random]' not in user_fragments and 'sort_by=' not in user_fragments:
		fragments += '&sort_by=vote_average.desc'
	# 26/09: niente filtro fisso sulla lingua originale (inglese). Era un filtro che l'utente non sceglie: con un attore coreano
	# (Song Kang-ho) Scopri non poteva trovare nulla. I filtri di Scopri sono solo quelli scelti.
	tmdb_url = 'https://api.themoviedb.org/3/discover/%s?language=en-US&region=US%s' % ('movie' if is_movie else 'tv', fragments)
	mode = 'build_movie_list' if is_movie else 'build_tvshow_list'
	action = 'tmdb_movies_discover' if is_movie else 'tmdb_tv_discover'
	content_path = build_url({'mode': mode, 'action': action, 'url': tmdb_url, 'name': 'Discover'})
	xbmc.log('###AF3_DISCOVER### content_path=[%s]' % content_path, xbmc.LOGINFO)
	# LOTTO 440 -- proprieta' e fuoco si danno alla finestra di Discover, non a quella che ha il fuoco quando il comando
	# gira: questa funzione dura secondi, e nel frattempo l'utente puo' aprire un dialogo (vedi la coda della funzione).
	# 11105 e' la 1105 della skin: Kodi somma 10000 agli id delle finestre personalizzate, e xbmcgui.Window non traduce.
	# setFocusId manda GUI_MSG_SETFOCUS a QUELLA finestra (interfaces/legacy/Window.cpp, Omega).
	discover = xbmcgui.Window(11105)
	discover.clearProperty('Search.ActivePanel')
	discover.setProperty('Background.HideArtwork', 'True')
	discover.setFocusId(3000)
	xbmc.sleep(100)
	xbmc.log('###AF3_DISCOVER### clear_edit_result=[%s]' % xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'method': 'Input.SendText', 'params': {'text': '', 'done': True}, 'id': 1})), xbmc.LOGINFO)
	xbmc.sleep(100)
	# STRADA B, meta' Discover (lotto 162). Il token di paginazione appartiene al CONTENITORE, non
	# alla lista: appena cambia ContentPath, Kodi ricompone il <content> del row 505 e in coda ci
	# trova ancora il 'pages=N' della ricerca PRECEDENTE. Il plugin viene invocato, si accorge che
	# l'inquilino e' cambiato e butta via tutta l'invocazione -- 336 ms misurati il 04/09 (lotto 161),
	# 697 prima di quello. Azzerando il token QUI l'invocazione non nasce proprio.
	# Qui non c'e' nessuna corsa da vincere, ed e' il motivo per cui questa meta' e' piu' solida
	# dell'altra: le due proprieta' si scrivono nello stesso thread a microsecondi di distanza, prima
	# che il ciclo della GUI rivaluti gli $INFO del path. Il caso simmetrico -- la ricerca testuale --
	# non ha un punto come questo e deve passare da <ontextchange> nella skin.
	from modules.paginator import CTL_PAGES_PROP
	win.clearProperty(CTL_PAGES_PROP % ('1105', '505'))
	win.setProperty('FenLight.Discover.ContentPath', content_path)
	# DOVE VA IL FUOCO (lotto 418, richiesta dell'utente del 29/09): sul primo risultato se ce ne sono, sulla
	# barra di ricerca se non ce ne sono. Mentre carica resta sulla barra, dove l'ha appena messo lo svuotamento
	# qui sopra. Prima lo si parcheggiava su 3050, il pulsante invisibile dell'intestazione "Risultati": a
	# risultati arrivati ci restava, e sembrava perso fra la barra e la riga.
	xbmc.sleep(300)
	# LOTTO 418. Qui si leggeva 'Container(1105,505)': Kodi non conosce la forma (finestra,id), prende 1105 come
	# id del contenitore e non trova niente. Il conteggio tornava vuoto, cioe' "zero risultati", e il fuoco
	# finiva SEMPRE sulla barra di ricerca invece che su "Risultati" (3050), dal 15/06. Container(505) si
	# risolve contro la finestra in primo piano, che e' la 1105: il clic che ci ha chiamati parte da li'.
	# L'attesa dura anche finche' la riga e' IN ATTESA (il rilevatore 974505, Riga_Attesa in
	# Includes_Widgets.xml): dal 418 una ricerca nuova distrugge la riga, e fra la distruzione e la
	# ricostruzione c'e' un istante in cui Kodi non sta aggiornando e la riga contiene solo il segnaposto.
	# LOTTO 440 -- CON UN DIALOGO APERTO LA RIGA NON SI LEGGE. Container(505) e Control.IsVisible rispondono per il dialogo
	# in primo piano (PR.md, voce 12), che la 505 non ce l'ha: l'attesa finiva subito e il fuoco andava a un controllo che
	# nel dialogo non esiste, togliendolo alla sua lista. Firestick, 30/09 17:26:42: selettore dei generi aperto 21 ms
	# prima della fine di questo ciclo, e non si navigava piu'. Col dialogo aperto si aspetta che chiuda, dentro lo
	# stesso tetto; se il tetto scade col dialogo ancora aperto non si tocca niente: l'utente e' altrove.
	# E UNA RICERCA SUPERATA NON AGISCE PIU' (lotto 440). Questa funzione dura secondi, e nel frattempo l'utente puo' lanciarne
	# un'altra o cancellare i filtri: da li' la ricerca di questa invocazione non e' piu' quella a schermo. Firestick, 30/09
	# 17:40:59: la ricerca A, ancora in attesa, trova il fuoco sulla barra messo dalla ricerca B e la riga piena dei propri
	# risultati, nasconde la barra e porta il fuoco sui risultati VECCHI; alle 17:52 una e' rimasta viva 13 s, oltre la
	# ricerca dopo. La ricerca corrente e' il path di Discover: chi non lo possiede piu' esce, senza toccare niente.
	def superata(): return (win.getProperty('FenLight.Discover.Lancio') != lancio
							or win.getProperty('FenLight.Discover.ContentPath') != content_path)
	for _ in range(150):
		if not xbmc.getCondVisibility('Window.IsActive(1105)') or superata(): return
		if not modal_dialog_present() and not xbmc.getCondVisibility('Container(505).IsUpdating | Control.IsVisible(974505)'): break
		xbmc.sleep(100)
	if modal_dialog_present() or superata(): return
	# Niente risultati = riga vuota, o il solo segnaposto: finita l'attesa non puo' essere quello 'in attesa',
	# quindi e' 'vuoto'. Lo dice il segnaposto stesso (kodi_utils.SEGNAPOSTO_PROP), non la sua etichetta: prima
	# si confrontava il testo con la stringa tradotta della skin.
	from modules.kodi_utils import SEGNAPOSTO_PROP
	# Il fuoco si sposta solo se e' ancora dove l'abbiamo lasciato, sulla barra (3000, o 3001 che vi rimanda): se
	# mentre caricava l'utente si e' mosso, non glielo si strappa. Vale per entrambi gli esiti (lotto 440: prima il
	# caso senza risultati lo spostava comunque).
	if xbmc.getInfoLabel('System.CurrentControlID') not in ('3000', '3001'): return
	num = xbmc.getInfoLabel('Container(505).NumItems') or '0'
	segnaposto = xbmc.getInfoLabel('Container(505).ListItemAbsolute(0).Property(%s)' % SEGNAPOSTO_PROP) == 'true'
	if superata(): return   # ancora una volta, subito prima di agire: fra l'attesa e qui passano letture della GUI
	if num in ('0', '') or (num == '1' and segnaposto):
		discover.setFocusId(3001)
		return
	# Ci sono risultati. Il passaggio e' quello della freccia giu' dall'intestazione (3050 in Includes_Search.xml): la
	# barra si nasconde e si entra nella riga. Il primo elemento non si chiede: la ricerca nuova passa dal segnaposto
	# (lo schermo decide, lotto 418), e la riga riparte dal primo da se'.
	discover.setProperty('Searchbar.IsHidden', 'True')
	discover.setFocusId(505)

def clear_discover_filters(params):
	import xbmcgui
	win = xbmcgui.Window(10000)
	keys = ['with_year_start','with_year_end','with_genres','without_genres',
				'with_cast','with_network','with_rating','with_rating_votes','with_sort','with_released']
	for k in keys:
		win.clearProperty('Discover.%s' % k)
		win.clearProperty('Discover.%s.url' % k)
	win.clearProperty('FenLight.Discover.ContentPath')
	if params.get('reset_type') == 'true':
		win.clearProperty('Discover.MediaType')
