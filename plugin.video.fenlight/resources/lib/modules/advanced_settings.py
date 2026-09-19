# -*- coding: utf-8 -*-
# Voci di Tools -> Cache & Streaming Optimization: le poche manopole che scrivono nei file di Kodi
# (advancedsettings.xml, profiles.xml) invece che nei nostri.
import os
import xml.etree.ElementTree as ET
from modules.kodi_utils import (translate_path, confirm_dialog, ok_dialog,
								notification, show_text, execute_builtin, progressDialogBG)
# logger = __import__('modules.kodi_utils', fromlist=['logger']).logger

SETTINGS_PATH = 'special://userdata/advancedsettings.xml'

# -------------------------------------------------------------------------- #
# Lettura e scrittura del file (preservando le altre impostazioni gia' presenti)
# -------------------------------------------------------------------------- #
def _load_root(path):
	# insert_comments: il file sulla stick e' documentato con commenti, e il parser di default li
	# butta via -- ogni scrittura da questo menu li cancellava tutti.
	if os.path.exists(path):
		try:
			parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
			root = ET.parse(path, parser=parser).getroot()
			if root.tag == 'advancedsettings':
				return root
		except Exception:
			pass
	return ET.Element('advancedsettings')

def _backup(path):
	if os.path.exists(path):
		try:
			import shutil
			shutil.copy(path, path + '.bak')
		except Exception:
			pass

def _save_root(root, path):
	try:
		ET.indent(root, space='  ')  # py3.9+ (Kodi 21 = py3.11)
	except Exception:
		pass
	ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=False)

def _set_child_text(parent, tag, text):
	node = parent.find(tag)
	if node is None:
		node = ET.SubElement(parent, tag)
	node.text = text
	return node

# -------------------------------------------------------------------------- #
# Risoluzione delle immagini in cache (imageres / fanartres) per la GUI attuale
# -------------------------------------------------------------------------- #
# Come le usa Kodi (CPicture::CacheTexture, Picture.cpp:219-232, ramo Omega): ogni immagine viene
# salvata in cache ridotta a stare dentro max_height = imageres e max_width = imageres * 16/9,
# mantenendo le proporzioni. fanartres prende il posto di imageres SOLO se e' maggiore, e solo per le
# immagini 16:9 (tolleranza 1% sul rapporto). Default di Kodi: 720 e 1080.
#
# La regola la decide modules/tmdb_art.py (kodi_limits): imageres all'altezza del poster piu' grande
# che la skin mostra (820 su base 1080), fanartres all'altezza della GUI. Nessuna immagine arriva a
# schermo ingrandita, e la cache non tiene piu' di quanto si vede. La misura scaricata da TMDb la
# sceglie lo stesso modulo; cambiando GUI cambiano gli URL, e le voci in cache con la misura vecchia
# non verranno piu' chieste: la pulizia toglie anche quelle.
#
#   GUI  720 -> imageres 547,  fanartres 720
#   GUI 1080 -> imageres 820,  fanartres 1080
#   GUI 2160 -> imageres 1640, fanartres 2160
KODI_DEFAULT_IMAGERES, KODI_DEFAULT_FANARTRES = 720, 1080
TEXTURES_DB = 'special://database/Textures13.db'

def _gui_size():
	# I pixel in cui Kodi disegna la GUI. Non l'infolabel System.ScreenHeight, che e' lo schermo (sul Mac
	# Retina in punti): il perche' sta in modules/tmdb_art.py, che e' l'unica fonte di questo valore.
	from modules.tmdb_art import gui_size
	return gui_size()

def _target_res(gui_height):
	from modules.tmdb_art import kodi_limits
	return kodi_limits(gui_height)

def _read_int(root, tag, default):
	node = root.find(tag)
	try: return int(node.text.strip())
	except Exception: return default

def _current_res(root):
	return _read_int(root, 'imageres', KODI_DEFAULT_IMAGERES), _read_int(root, 'fanartres', KODI_DEFAULT_FANARTRES)

def _bounds(width, height, imageres, fanartres):
	# Il limite che Kodi applica a un'immagine di queste proporzioni. Calcolato sulle dimensioni in
	# cache invece che sull'originale, che non e' conservato: le proporzioni sono le stesse.
	max_h = imageres
	if fanartres > imageres and abs(width / height / (16.0 / 9.0) - 1.0) <= 0.01:
		max_h = fanartres
	return max_h * 16 // 9, max_h

def _stale_textures(new_res, old_res, new_tokens):
	"""Le voci in cache con una dimensione diversa da quella che Kodi darebbe coi valori nuovi.

	Kodi non ricalcola mai una texture gia' in cache al cambio di imageres: senza questa pulizia i
	valori nuovi valgono solo per le immagini mai viste. Due casi:
	  - troppo grande per i limiti nuovi;
	  - tagliata dal limite vecchio (un lato uguale al tetto vecchio) quando il nuovo e' piu' largo,
	    quindi l'originale potrebbe dare di piu'. Un'immagine nativamente grande quanto il tetto
	    vecchio viene rifatta per niente: costa un download, non un errore.
	E un terzo: un'immagine TMDb con una misura che tmdb_art puo' scegliere ma che coi valori nuovi non
	scegliera' -- il suo URL non verra' piu' chiesto (tmdb_art.MANAGED_TOKENS dice quali). La misura
	da sola non basta: w500 puo' essere il poster nuovo e il logo vecchio. Il tipo lo dice
	l'estensione, perche' metadata.py chiede i loghi sempre in PNG e poster e sfondi sono JPG."""
	import sqlite3
	dbcon = sqlite3.connect(translate_path(TEXTURES_DB), timeout=40.0)
	try:
		rows = dbcon.execute('SELECT t.id, t.cachedurl, t.url, s.width, s.height FROM texture t JOIN sizes s ON s.idtexture = t.id').fetchall()
	finally:
		dbcon.close()
	from modules.tmdb_art import TMDB_PREFIX, MANAGED_TOKENS
	wanted_png, wanted_jpg = {new_tokens['logo']}, {new_tokens['poster'], new_tokens['fanart'], new_tokens['landscape']}
	stale = []
	for texture_id, cachedurl, url, width, height in rows:
		if url and url.startswith(TMDB_PREFIX):
			token = url[len(TMDB_PREFIX):].split('/', 1)[0]
			if token in MANAGED_TOKENS and token not in (wanted_png if url.endswith('.png') else wanted_jpg):
				stale.append((texture_id, cachedurl))
				continue
		if not width or not height: continue
		new_w, new_h = _bounds(width, height, *new_res)
		if width > new_w or height > new_h:
			stale.append((texture_id, cachedurl))
			continue
		old_w, old_h = _bounds(width, height, *old_res)
		if (height == old_h or width == old_w) and (new_h > height and new_w > width):
			stale.append((texture_id, cachedurl))
	return stale

def _purge_textures(stale):
	# Riga e file insieme. Il trigger textureDelete dello schema toglie anche la riga di sizes.
	# Si fa solo subito prima di RestartApp: a sessione in corso Kodi rigenererebbe le voci con i
	# valori VECCHI, che restano in memoria fino al riavvio.
	import sqlite3
	thumbnails = translate_path('special://thumbnails/')
	progress = progressDialogBG()
	progress.create('Fen Light', 'Pulizia cache immagini...')
	try:
		for count, (texture_id, cachedurl) in enumerate(stale, 1):
			try: os.remove(os.path.join(thumbnails, cachedurl))
			except Exception: pass
			if count % 200 == 0:
				progress.update(int(count * 100 / len(stale)), 'Pulizia cache immagini...')
		dbcon = sqlite3.connect(translate_path(TEXTURES_DB), timeout=40.0)
		try:
			dbcon.executemany('DELETE FROM texture WHERE id = ?', [(i[0],) for i in stale])
			dbcon.commit()
		finally:
			dbcon.close()
	finally:
		try: progress.close()
		except Exception: pass

def image_res_label():
	# Per l'etichetta del menu: lo stato va detto, altrimenti si clicca alla cieca.
	width, height = _gui_size()
	current = _current_res(_load_root(translate_path(SETTINGS_PATH)))
	if not height: return 'Risoluzione immagini: %s/%s' % current
	target = _target_res(height)
	return 'Risoluzione immagini per la GUI %sp: %s/%s%s' % ((height,) + current +
			('' if current == target else ' (consigliato %s/%s)' % target,))

def image_res(params):
	width, height = _gui_size()
	if not height:
		return ok_dialog(heading='Risoluzione immagini', text='Impossibile leggere la risoluzione della GUI.')
	path = translate_path(SETTINGS_PATH)
	root = _load_root(path)
	old_res = _current_res(root)
	new_res = _target_res(height)
	from modules.tmdb_art import compute_tokens
	new_tokens = compute_tokens(height)
	try: stale = _stale_textures(new_res, old_res, new_tokens)
	except Exception as e:
		return ok_dialog(heading='Errore', text='Impossibile leggere la cache immagini:[CR]%s' % e)
	if old_res == new_res and not stale:
		return ok_dialog(heading='Risoluzione immagini',
						text='GUI %sx%s: imageres e fanartres sono gia\' a [B]%s/%s[/B] e la cache e\' allineata.' % ((width, height) + new_res))
	lines = ['GUI attuale: [B]%sx%s[/B]' % (width, height),
			'imageres  %s  ->  [B]%s[/B]' % (old_res[0], new_res[0]),
			'fanartres %s  ->  [B]%s[/B]' % (old_res[1], new_res[1]),
			'Ogni immagine alla piena risoluzione della GUI, nella misura piu\' leggera che la copre.',
			'Da TMDb: poster %s, sfondi %s, landscape %s, loghi %s.' % (new_tokens['poster'], new_tokens['fanart'], new_tokens['landscape'], new_tokens['logo']),
			'',
			'Immagini in cache da rifare: [B]%s[/B] (verranno riscaricate quando servono).' % len(stale),
			'',
			'Kodi legge questi valori solo all\'avvio: si applica e si riavvia subito.']
	if not confirm_dialog(heading='Risoluzione immagini', text='[CR]'.join(lines),
						ok_label='Applica e riavvia', cancel_label='Annulla'): return
	try:
		if old_res != new_res:
			_backup(path)
			_write_image_res(root, new_res, width, height)
			_save_root(root, path)
		_purge_textures(stale)
	except Exception as e:
		return ok_dialog(heading='Errore', text='Impossibile completare:[CR]%s' % e)
	execute_builtin('RestartApp')

def _write_image_res(root, new_res, width, height):
	# Il commento subito sopra <imageres>, se c'e', parla dei valori vecchi: lo si sostituisce con uno
	# che dice da dove vengono questi.
	children = list(root)
	for index, child in enumerate(children):
		if child.tag == 'imageres':
			if index and children[index - 1].tag is ET.Comment:
				root.remove(children[index - 1])
			break
	for tag in ('imageres', 'fanartres'):
		for existing in root.findall(tag):
			root.remove(existing)
	comment = ET.Comment(' Scritti da Fen Light (Tools -> Cache & Streaming Optimization) per la GUI %sx%s: '
						'poster piu\' grande della skin e altezza della GUI. Vedi modules/tmdb_art.py. ' % (width, height))
	for element in (comment, _text_element('imageres', new_res[0]), _text_element('fanartres', new_res[1])):
		root.append(element)

def _text_element(tag, value):
	element = ET.Element(tag)
	element.text = str(value)
	return element

# -------------------------------------------------------------------------- #
# Voci richiamate dal router (navigator -> advancedsettings.<func>)
# -------------------------------------------------------------------------- #
def hide_parent(params):
	confirm = confirm_dialog(heading='Nascondi cartella superiore (..)',
							text='Scrivere <filelists><showparentdiritems>false in advancedsettings.xml?[CR]'
								'Nasconde la voce ".." in cima alle liste. Le altre impostazioni restano invariate.',
							ok_label='Applica', cancel_label='Annulla')
	if not confirm:
		return
	path = translate_path(SETTINGS_PATH)
	root = _load_root(path)
	_backup(path)
	filelists = root.find('filelists')
	if filelists is None:
		filelists = ET.SubElement(root, 'filelists')
	_set_child_text(filelists, 'showparentdiritems', 'false')
	_save_root(root, path)
	notification('Impostazione scritta')
	ok_dialog(heading='Fatto', text='Riavvia Kodi per applicare la modifica.')

# -------------------------------------------------------------------------- #
# Stato di riproduzione scritto da Kodi (profiles.xml -> canwritedatabases)
# -------------------------------------------------------------------------- #
# Non e' cache ne' streaming, ma sta qui perche' e' l'altra manopola che riguarda il comportamento di
# Kodi durante e dopo la riproduzione, e perche' e' l'unico menu del progetto che scrive nei file di
# Kodi invece che nei propri. Il meccanismo -- e perche' la scrittura non puo' essere immediata -- sta
# tutto in modules/profile_flag.py.
def playback_state(params):
	from modules import profile_flag
	stato = profile_flag.read_flag()
	if stato is None:
		return ok_dialog(heading='Stato di riproduzione',
						text='profiles.xml non trovato o illeggibile.[CR]Nessuna modifica fatta.')
	if stato == 'true':
		lines = ['Adesso: [B]Kodi scrive[/B] lo stato di riproduzione nel proprio database.',
				'',
				'A ogni chiusura del player Kodi salva una riga usando come chiave l\'URL risolto del momento,',
				'che non si ripete mai. La scrittura annuncia un aggiornamento della libreria, e Kodi ricostruisce',
				'[B]tutti[/B] i widget della schermata principale.',
				'',
				'Fen Light quel database non lo legge: visto/non visto e punto di ripresa vengono da Trakt e dal',
				'proprio archivio. Bloccandolo si perdono solo le voci native di Kodi "Segna come gia\' visto",',
				'che restano visibili ma non fanno piu\' niente.',
				'',
				'Bloccare la scrittura?']
		if not confirm_dialog(heading='Stato di riproduzione di Kodi', text='[CR]'.join(lines),
							ok_label='Blocca', cancel_label='Annulla'): return
		voluto, azione = 'false', 'bloccata'
	else:
		lines = ['Adesso: la scrittura e\' [B]bloccata[/B].',
				'',
				'Ripristinandola Kodi tornera\' a salvare lo stato di riproduzione nel proprio database, e i widget',
				'della schermata principale torneranno a ricostruirsi tutti al rientro dal player.',
				'',
				'Ripristinare?']
		if not confirm_dialog(heading='Stato di riproduzione di Kodi', text='[CR]'.join(lines),
							ok_label='Ripristina', cancel_label='Annulla'): return
		voluto, azione = 'true', 'ripristinata'
	try:
		# Prima il marcatore: se la scrittura del file fallisce, la richiesta resta registrata e la
		# riconciliazione all'uscita o al prossimo avvio ci riprova. Al contrario -- file scritto e
		# richiesta non registrata -- Kodi riscriverebbe profiles.xml alla chiusura e la modifica
		# sparirebbe senza che nessuno se ne accorga.
		profile_flag.set_wanted(voluto)
		profile_flag.write_flag(voluto)
	except Exception as e:
		return ok_dialog(heading='Errore', text='Impossibile scrivere profiles.xml:[CR]%s' % e)
	notification('Scrittura %s' % azione)
	restart = confirm_dialog(heading='Riavvio richiesto',
							text='La sessione in corso tiene il valore vecchio in memoria: la modifica vale dal[CR]'
								'prossimo avvio di Kodi. Riavviare ora?',
							ok_label='Riavvia', cancel_label='Piu\' tardi')
	if restart:
		execute_builtin('RestartApp')

def show(params):
	path = translate_path(SETTINGS_PATH)
	if not os.path.exists(path):
		return ok_dialog(heading='advancedsettings.xml', text='Il file non esiste ancora.')
	return show_text('advancedsettings.xml', file=path, font_size='small')
