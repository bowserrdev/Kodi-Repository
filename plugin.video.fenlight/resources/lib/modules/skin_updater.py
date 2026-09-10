# -*- coding: utf-8 -*-
"""Aggiornamento della skin senza ReloadSkin: si sostituiscono i byte su disco, non la skin viva.

PERCHE' ESISTE (log della stick, 09/09/2026 18:49). L'aggiornamento nativo della skin ATTIVA e' due
guasti in uno, entrambi osservati in quella finestra di 15 secondi:

  1. `CAddonInstaller` scarica, scompatta e chiama `ReloadSkin` a caldo. Alle 18:49:35.019 il log
     dice `skin loaded...` e subito dopo `------ Window Init () ------` -- senza il consueto
     `Activating window ID:` che al boot porta a Startup.xml e poi a Home.xml. Kodi e' rimasto sulla
     finestra di caricamento vuota: schermo nero, e da li' in poi ogni tasto finisce su
     `window 9999`, cioe' su nessuna finestra (`HandleKey: backspace pressed, window 9999`, 18:49:41).
     L'utente era dentro l'Addon Browser e stava premendo Down e Select mentre la skin veniva
     smontata sotto di lui (18:49:26.974 e 18:49:27.186).
  2. L'installer RIMPIAZZA la cartella dell'addon, quindi i file che il dispositivo genera e che il
     pacchetto -- di proposito -- non contiene non vengono sovrascritti: vengono cancellati. Alle
     18:49:34.326: `Error loading include file .../script-skinvariables-generator-includes-.xml:
     Failed to open file`. Quel file contiene la configurazione reale dei widget della home (guid,
     list_id mdblist, label): ogni aggiornamento azzerava la home del dispositivo, anche quando non
     faceva schermo nero. Vedi la tabella EXCLUDE in generate_repo.py per il perche' non e' nel
     pacchetto: spedirlo significherebbe sovrascrivere la home di ogni dispositivo con quella del Mac.

Il peso non c'entra piu': 5,9 MB scaricati in 11 secondi, md5 verificato, unzip riuscito. Il guasto e'
il reload a caldo in se', e non si aggiusta rendendo il pacchetto piu' piccolo.

COME LO EVITA. Kodi legge gli XML della skin all'AVVIO (Home.xml e compagnia sono KEEP_IN_MEMORY /
LOAD_ON_GUI_INIT): una cartella cambiata a meta' sessione non esiste per la sessione in corso. Quindi
si scrive la versione nuova sul disco e non si dice niente a nessuno. La sessione corrente prosegue
con gli XML che ha gia' in memoria; al boot successivo `CAddonMgr::FindAddons` legge addon.xml, trova
la versione nuova e la carica per la via normale. Nessun ReloadSkin, nessuna finestra distrutta,
nessuna notifica: l'utente non si accorge che c'e' stato un aggiornamento, che era il requisito.

Perche' il servizio sta in Fen Light e non in un addon della skin: un aggiornatore che vive DENTRO il
pacchetto che sta sostituendo si aggiorna da se' mentre lavora -- e' lo stesso problema, in piccolo.
La skin dichiara gia' `<import addon="plugin.video.fenlight" version="2.1.1"/>`, i due addon sono una
coppia accoppiata per dichiarazione. (L'ipotesi dell'addon helper separato era gia' stata valutata e
scartata il 31/08.)

TRE COSE DA SAPERE PRIMA DI TOCCARE QUESTO FILE.

  - Lo scambio e' UN RENAME DI CARTELLA, non una copia file per file. O c'e' la vecchia o c'e' la
    nuova, mai un ibrido: un fallimento a meta' di una copia lascerebbe una skin che al boot dopo non
    parte. Il `media/Textures.xbt` che Kodi tiene aperto (`OpenBundle` nel log) resta valido sul
    vecchio inode fino a fine sessione, che e' esattamente il comportamento POSIX che serve.
    Verificato sulla stick il 09/09: `/data/media` montato sdcardfs, rename fra `.kodi/temp` e
    `.kodi/addons` riuscito.
  - Lo scambio pretende che l'auto-update NATIVO della skin sia spento, o `CAddonInstaller` rifarebbe
    il danno per conto suo. Si spegne per la SOLA skin (`update_rules`, la stessa tabella che gia'
    contiene service.xbmc.versioncheck): Fen Light e cocoscrapers restano sul canale nativo, perche'
    il loro codice viene riletto solo al boot e li' l'aggiornamento a caldo non fa danni.
  - Fra lo scambio e il riavvio la sessione e' IBRIDA: XML vecchi in memoria, file nuovi su disco.
    Conta solo per cio' che Kodi carica su richiesta (le texture sciolte): un'immagine tolta nella
    versione nuova sparirebbe fino al riavvio. E' il motivo per cui lo scambio si fa a stick ferma,
    il piu' tardi possibile nella sessione, e non appena il download e' finito.
"""

import os
import xbmc, xbmcgui

SKIN_ID = 'skin.arctic.fuse.3'
REPO_ID = 'repository.bowserr'
# Regola 1 = USER_DISABLED_AUTO_UPDATE nell'enum AddonUpdateRule di Kodi.
NO_AUTO_UPDATE = 1

# I file che il DISPOSITIVO genera e che il pacchetto non contiene: sono la lista di EXCLUDE in
# generate_repo.py vista dall'altro lato. Vengono portati a mano nella cartella nuova prima dello
# scambio, ed e' l'unico motivo per cui questo modulo tocca file singoli.
PRESERVE = (
	'1080i/script-skinvariables-generator-includes*.xml',
	'1080i/script-skinvariables-skinusers.xml',
	'1080i/script-skinshortcuts-includes.xml',
)

# Nomi dentro l'area di lavoro. Il marcatore e' il giornale dello scambio: se al prossimo avvio si
# trova ancora li', lo scambio e' stato interrotto a meta' e va finito o disfatto.
BACKUP = 'old'
STAGED = SKIN_ID
MARKER = 'SCAMBIO_IN_CORSO'

# Cio' senza cui la skin non parte. Un pacchetto che non li ha e' un pacchetto da buttare, non da
# installare: meglio restare indietro di una versione che non avere una GUI al prossimo avvio.
ESSENTIAL = ('addon.xml', '1080i/Includes.xml', '1080i/Home.xml', 'media/Textures.xbt')


def _vtuple(version):
	"""'3.3.13' -> (3, 3, 13). Tollera i suffissi stile Kodi ('1.2.3+matrix.1', '0.5.27~beta')."""
	main = version.split('~')[0].split('+')[0].split('-')[0]
	out = []
	for part in main.split('.'):
		digits = ''
		for ch in part:
			if not ch.isdigit(): break
			digits += ch
		out.append(int(digits) if digits else 0)
	while len(out) < 4: out.append(0)
	return tuple(out)


class SkinUpdater:
	# Primo controllo. Non e' fretta: e' che il servizio parte gia' differito (vedi
	# FenLightMonitor._deferred_services) e questo aspetta ancora, perche' un GET di 10 KB dentro la
	# coda di costruzione dei widget e' esattamente la raffica di rete che le note sui crash da avvio
	# dicono di evitare.
	FIRST_CHECK_DELAY = 90.0
	# Ricontrollo dentro la stessa sessione. Le stick restano accese per giorni: senza questo,
	# committare a meta' pomeriggio significherebbe aspettare il riavvio successivo per il solo
	# CONTROLLO, non per l'applicazione.
	RECHECK = 6 * 3600
	# Un giro fallito non deve costare come un giro riuscito. Il 09/09 il difetto di `iter_content` ha
	# mandato il servizio a dormire per sei ore su un errore che si sarebbe ripresentato identico:
	# nessun danno, ma nessuna diagnosi prima del riavvio manuale. Dieci minuti bastano a distinguere
	# un guasto passeggero (rete assente, GitHub lento) da uno vero, senza martellare.
	RETRY_AFTER_ERROR = 600
	POLL = 20.0
	# Quanto deve essere ferma la stick prima di scambiare le cartelle. Alto di proposito: lo scambio
	# non e' urgente (si vede al riavvio, comunque), e in cambio si evita di far sparire per qualche
	# millisecondo il percorso da cui Kodi sta caricando le texture mentre l'utente scorre una lista.
	IDLE_BEFORE_SWAP = 120
	# Blocchi del download, con una pausa fra l'uno e l'altro. 5,9 MB / 64 KB = ~92 blocchi, cioe'
	# ~5 s aggiunti a un download che ne dura 11: il costo e' irrilevante e la banda della stick
	# resta libera per cio' che l'utente sta guardando. Vedi le note sul 5 GHz -> 2,4 GHz: qui si
	# preferisce sempre essere lenti.
	CHUNK = 64 * 1024
	CHUNK_PAUSE = 0.05

	def run(self):
		from modules.kodi_utils import logger
		self.logger = logger
		logger('Fen Light', 'SkinUpdater Service Starting')
		monitor, player = xbmc.Monitor(), xbmc.Player()
		wait_for_abort, is_playing = monitor.waitForAbort, player.isPlayingVideo
		window = xbmcgui.Window(10000)
		self.monitor = monitor
		# Prima di ogni altra cosa, e prima di qualunque attesa: se lo scambio precedente e' stato
		# interrotto a meta', il percorso della skin non esiste e Kodi e' appena partito senza. Qui si
		# rimette a posto, per la sessione successiva.
		try: self._repair()
		except Exception as e: logger('Fen Light', 'SkinUpdater: riparazione fallita (%s)' % e)
		try: self.rule_in_force = self._ensure_no_auto_update()
		except Exception as e:
			self.rule_in_force = False
			logger('Fen Light', 'SkinUpdater: regola di auto-update non scritta (%s)' % e)
		if wait_for_abort(self.FIRST_CHECK_DELAY): return self._finish()
		# `staged` e' la cartella pronta che aspetta solo la stick ferma. Sopravvive ai giri del ciclo
		# ma non alla sessione: se non si scambia entro lo spegnimento, il pacchetto scaricato e
		# verificato resta in temp e il boot successivo ricomincia dal controllo, che lo ritrova.
		staged, next_check = None, 0.0
		from time import time
		while not monitor.abortRequested():
			try:
				if is_playing() or window.getProperty('fenlight.pause_services') == 'true': pass
				elif staged is not None:
					if xbmc.getGlobalIdleTime() >= self.IDLE_BEFORE_SWAP:
						self._swap(staged)
						staged = None
				elif time() >= next_check:
					next_check = time() + self.RECHECK
					staged = self._prepare()
			except Exception as e:
				logger('Fen Light', 'SkinUpdater: giro fallito (%s)' % e)
				staged = None
				next_check = time() + self.RETRY_AFTER_ERROR
				self._clean_work()
			if wait_for_abort(self.POLL): break
		return self._finish()

	def _finish(self):
		try: del self.monitor
		except: pass
		return self.logger('Fen Light', 'SkinUpdater Service Finished')

	# --- percorsi ---------------------------------------------------------------------------------

	def _paths(self):
		"""Cartella installata, area di lavoro. L'area di lavoro sta sotto special://temp e NON sotto
		addons/ apposta: `CAddonMgr::FindAddons` cammina addons/ e legge ogni addon.xml che trova, e
		una copia della skin li' dentro sarebbe un secondo addon con lo stesso id. Stesso filesystem
		(entrambe sotto .kodi/), quindi il rename resta un rename."""
		from modules.kodi_utils import translate_path
		installed = os.path.join(translate_path('special://home/addons/'), SKIN_ID)
		work = os.path.join(translate_path('special://temp/'), 'fenlight_skinswap')
		return installed, work

	def _xml_version(self, addon_xml):
		from xml.etree import ElementTree
		return ElementTree.parse(addon_xml).getroot().attrib['version']

	# --- auto-update nativo -----------------------------------------------------------------------

	def _ensure_no_auto_update(self):
		"""Spegne l'auto-update di Kodi per la SOLA skin, com'e' gia' per service.xbmc.versioncheck.

		Kodi tiene le regole in memoria (CAddonUpdateRules le carica all'avvio), quindi scrivere qui
		non ha effetto sulla sessione corrente: vale dal boot successivo. E' accettabile perche' la
		riga si scrive una volta sola, al primo avvio dopo l'arrivo di questa versione di Fen Light,
		e da li' in poi non cambia mai. Idempotente: se la riga c'e' gia', non si tocca niente.

		Torna True se la regola era GIA' li' quando Kodi e' partito, cioe' se e' in vigore ADESSO.
		Serve a _wake_kodi_for_the_others, che senza questa risposta rischierebbe di svegliare
		l'aggiornatore nativo proprio nell'unico avvio in cui la skin non e' ancora protetta."""
		import sqlite3
		from modules.kodi_utils import translate_path, logger
		dbcon = sqlite3.connect(translate_path('special://database/Addons33.db'), timeout=40.0)
		try:
			row = dbcon.execute('SELECT updateRule FROM update_rules WHERE addonID = ?', (SKIN_ID,)).fetchone()
			if row and row[0] == NO_AUTO_UPDATE: return True
			if row: dbcon.execute('UPDATE update_rules SET updateRule = ? WHERE addonID = ?', (NO_AUTO_UPDATE, SKIN_ID))
			else: dbcon.execute('INSERT INTO update_rules (addonID, updateRule) VALUES (?, ?)', (SKIN_ID, NO_AUTO_UPDATE))
			dbcon.commit()
			logger('Fen Light', 'SkinUpdater: auto-update nativo disattivato per %s (vale dal prossimo avvio)' % SKIN_ID)
			return False
		finally: dbcon.close()

	# --- preparazione -----------------------------------------------------------------------------

	def _prepare(self):
		"""Controlla, scarica, verifica, scompatta. Torna la cartella pronta, o None se non c'e'
		niente da fare. Non tocca la skin installata: quello lo fa _swap, e solo a stick ferma."""
		from modules.kodi_utils import logger
		installed, work = self._paths()
		local = self._xml_version(os.path.join(installed, 'addon.xml'))
		urls = self._repo_urls()
		if not urls: return None
		info_url, datadir = urls
		published = self._published_versions(info_url)
		remote = published.get(SKIN_ID)
		skin_behind = bool(remote) and _vtuple(remote) > _vtuple(local)
		self._wake_kodi_for_the_others(published, skin_behind)
		if not skin_behind: return None
		logger('Fen Light', 'SkinUpdater: %s %s -> %s, preparo lo scambio' % (SKIN_ID, local, remote))
		import shutil
		shutil.rmtree(work, ignore_errors=True)
		os.makedirs(work)
		name = '%s-%s.zip' % (SKIN_ID, remote)
		url = '%s%s/%s' % (datadir, SKIN_ID, name)
		zip_path = os.path.join(work, name)
		self._download(url, zip_path)
		expected = self._fetch(url + '.md5').split()[0].strip().lower()
		got = self._md5(zip_path)
		if got != expected:
			# E' la stessa guardia che il repo dichiara con <hashes>true</hashes>: il 28/08 uno zip da
			# 16,8 MB su 52 era finito in packages/ senza che nessuno se ne accorgesse.
			shutil.rmtree(work, ignore_errors=True)
			raise ValueError('md5 del pacchetto non corrisponde (%s != %s)' % (got, expected))
		import zipfile
		with zipfile.ZipFile(zip_path) as zf: zf.extractall(work)
		os.remove(zip_path)
		staged = os.path.join(work, SKIN_ID)
		self._carry_over(installed, staged)
		self._sanity(staged, remote)
		logger('Fen Light', 'SkinUpdater: %s pronta in temp, aspetto %s s di inattivita\'' % (remote, self.IDLE_BEFORE_SWAP))
		return staged

	def _clean_work(self):
		"""L'area di lavoro non deve sopravvivere a un errore. Non e' pulizia estetica: uno zip
		troncato o vuoto lasciato li' -- come quello da 0 byte del 09/09 -- e' esattamente il genere di
		residuo che al giro dopo si prende per buono."""
		import shutil
		try: shutil.rmtree(self._paths()[1], ignore_errors=True)
		except Exception: pass

	def _repo_urls(self):
		"""Legge gli URL dall'addon.xml del repo installato invece di ripeterli qui: se un giorno il
		repo cambia indirizzo, cambia in un posto solo e questo modulo lo segue."""
		from xml.etree import ElementTree
		from modules.kodi_utils import translate_path
		path = os.path.join(translate_path('special://home/addons/'), REPO_ID, 'addon.xml')
		if not os.path.exists(path): return None
		root = ElementTree.parse(path).getroot()
		info = root.find(".//extension[@point='xbmc.addon.repository']/dir/info")
		datadir = root.find(".//extension[@point='xbmc.addon.repository']/dir/datadir")
		if info is None or datadir is None: return None
		base = datadir.text.strip()
		if not base.endswith('/'): base += '/'
		return info.text.strip(), base

	def _published_versions(self, info_url):
		"""Tutto cio' che il repo pubblica, non la sola skin: serve anche a _wake_kodi_for_the_others."""
		from xml.etree import ElementTree
		root = ElementTree.fromstring(self._fetch(info_url))
		return {a.attrib['id']: a.attrib['version'] for a in root.findall('addon') if 'id' in a.attrib and 'version' in a.attrib}

	def _wake_kodi_for_the_others(self, published, skin_behind):
		"""Sveglia l'aggiornatore nativo se un addon del repo -- che non sia la skin -- e' indietro.

		Perche' serve. `CRepositoryUpdater` non ricontrolla a ogni avvio: rilegge il repo quando scade
		il `nextcheck` scritto in Addons33.db, e quel valore arriva dall'header HTTP
		`X-Kodi-Recheck-After` della risposta al checksum, con default 24 ORE quando l'header non c'e'.
		Misurato il 09/09 su questa stick, e i due casi si vedono affiancati nella stessa tabella:
		  repository.xbmc.org  lastcheck 15:39:37  nextcheck 21:39:37   (+6 h)
		  repository.bowserr   lastcheck 18:49:12  nextcheck 10/09 18:49:12  (+24 h)
		mirrors.kodi.tv manda `X-Kodi-Recheck-After: 21600`, raw.githubusercontent.com non manda
		niente (solo `cache-control: max-age=300`, che Kodi non guarda). GitHub non permette header
		propri, quindi quelle 24 ore non si accorciano dal lato server: un commit fatto oggi puo'
		restare invisibile a un dispositivo per un giorno intero, e chi lo usa non ha modo di saperlo.

		Cosa fa. Lo stesso gesto che si fa a mano dal browser degli addon -- *Controlla
		aggiornamenti* -- che e' il builtin `UpdateAddonRepos`. Il servizio ha gia' scaricato
		`addons.xml` per la skin: le versioni degli altri addon sono li' dentro, gratis. Si sveglia
		Kodi solo quando c'e' davvero qualcosa da prendere, mai a vuoto.

		Il cancello sulla skin. Le regole di update Kodi le legge in memoria all'avvio, quindi
		nell'avvio in cui la riga viene scritta per la prima volta la skin NON e' ancora protetta:
		svegliare l'aggiornatore proprio li' significherebbe farsi installare la skin alla vecchia
		maniera, cioe' il guasto del 09/09. In quel solo caso si aspetta: lo scambio a freddo avviene
		comunque in questa sessione, e gli altri addon li prende il giro dopo."""
		from modules.kodi_utils import execute_builtin, logger, translate_path
		behind = []
		addons_dir = translate_path('special://home/addons/')
		for addon_id, version in published.items():
			if addon_id == SKIN_ID: continue
			path = os.path.join(addons_dir, addon_id, 'addon.xml')
			if not os.path.exists(path): continue
			try: local = self._xml_version(path)
			except Exception: continue
			if _vtuple(version) > _vtuple(local): behind.append('%s %s -> %s' % (addon_id, local, version))
		if not behind: return
		if skin_behind and not getattr(self, 'rule_in_force', False):
			return logger('Fen Light', 'SkinUpdater: %s da aggiornare, ma la skin non e\' ancora protetta in questa sessione: aspetto' % len(behind))
		logger('Fen Light', 'SkinUpdater: indietro %s -- sveglio l\'aggiornatore di Kodi' % ', '.join(behind))
		execute_builtin('UpdateAddonRepos')

	def _fetch(self, url):
		from modules.kodi_utils import make_session
		session = make_session(url)
		try:
			response = session.get(url, timeout=30)
			response.raise_for_status()
			return response.text
		finally: session.close()

	def _download(self, url, dest):
		"""Scarica a blocchi. Vuole `requests` VERO, non `make_session`.

		Costato un giro a vuoto il 09/09 (`SkinUpdater: giro fallito ('Response' object has no
		attribute 'iter_content')`, log 20:21:21, con uno zip da 0 byte lasciato in temp). Dal lotto
		84 `make_session` non torna piu' requests ma `modules.http_client`, che legge la risposta
		**tutta in una volta**: ottimo per i 10 KB di `addons.xml`, inutilizzabile per 5,9 MB che si
		vogliono leggere a blocchi. E' lo stesso motivo per cui `advanced_settings._speed_test_mbps`
		usa `import_requests_real`, ed e' l'unico altro punto del progetto che lo fa.

		Il prezzo (337 moduli contro 66) si paga solo quando c'e' davvero un aggiornamento da
		prendere, cioe' quasi mai, e comunque almeno 90 s dopo l'avvio."""
		from modules.kodi_utils import import_requests_real
		requests = import_requests_real('skin_updater')
		with requests.get(url, stream=True, timeout=60) as response:
			response.raise_for_status()
			with open(dest, 'wb') as output:
				for chunk in response.iter_content(chunk_size=self.CHUNK):
					if not chunk: continue
					output.write(chunk)
					# waitForAbort e non sleep: se Kodi chiude a meta' download il thread non resta
					# appeso su 5,9 MB di rete.
					if self.monitor.waitForAbort(self.CHUNK_PAUSE): raise InterruptedError('chiusura di Kodi durante il download')

	def _md5(self, path):
		import hashlib
		digest = hashlib.md5()
		with open(path, 'rb') as handle:
			for chunk in iter(lambda: handle.read(1024 * 1024), b''): digest.update(chunk)
		return digest.hexdigest()

	def _carry_over(self, installed, staged):
		"""Porta nella cartella nuova i file che il dispositivo si e' generato. Senza questo passaggio
		lo scambio riprodurrebbe il guasto delle 18:49:34 con un meccanismo diverso."""
		import glob, shutil
		from modules.kodi_utils import logger
		for pattern in PRESERVE:
			for source in glob.glob(os.path.join(installed, pattern.replace('/', os.sep))):
				target = os.path.join(staged, os.path.relpath(source, installed))
				directory = os.path.dirname(target)
				if not os.path.exists(directory): os.makedirs(directory)
				shutil.copy2(source, target)
				logger('Fen Light', 'SkinUpdater: conservato %s' % os.path.relpath(source, installed))

	def _sanity(self, staged, expected):
		for relative in ESSENTIAL:
			if not os.path.exists(os.path.join(staged, relative.replace('/', os.sep))):
				raise ValueError('pacchetto incompleto, manca %s' % relative)
		found = self._xml_version(os.path.join(staged, 'addon.xml'))
		if found != expected:
			raise ValueError('addon.xml del pacchetto dice %s, il repo diceva %s' % (found, expected))

	# --- scambio ----------------------------------------------------------------------------------

	def _repair(self):
		"""Rimette a posto uno scambio interrotto. Costa due `exists` quando non c'e' niente da fare.

		Il caso che questa funzione esiste per coprire: il processo ucciso -- Kodi chiuso, o il
		`watchdog_reboot` che su questa stick non e' teorico -- fra i due rename di `_swap`. I rename
		in se' sono atomici e non possono rompersi a meta', ma fra l'uno e l'altro c'e' una finestra di
		microsecondi in cui `addons/skin.arctic.fuse.3` NON ESISTE. Se il colpo arriva li', al
		riavvio Kodi non trova la skin e ricade su quella di sistema: il dispositivo funziona, ma
		l'utente si trova davanti una GUI che non e' la sua, ed e' esattamente cio' che tutto questo
		lavoro serve a non fare.

		La regola di riparazione e' quella dei giornali, e si legge da sola: se la skin non c'e', la
		nuova vince sulla vecchia (lo scambio era voluto, si finisce), e se la nuova non c'e' si
		rimette la vecchia. Se invece la skin c'e', lo scambio era gia' arrivato in fondo e resta solo
		da buttare l'area di lavoro."""
		import shutil
		from modules.kodi_utils import logger
		installed, work = self._paths()
		marker = os.path.join(work, MARKER)
		if not os.path.exists(marker): return
		staged, backup = os.path.join(work, STAGED), os.path.join(work, BACKUP)
		if not os.path.exists(installed):
			source = staged if os.path.exists(staged) else (backup if os.path.exists(backup) else None)
			if source is None:
				return logger('Fen Light', 'SkinUpdater: scambio interrotto e nessuna copia da rimettere -- la skin va reinstallata a mano')
			os.rename(source, installed)
			logger('Fen Light', 'SkinUpdater: scambio interrotto, rimessa in posizione la %s (%s)'
					% ('nuova' if source == staged else 'precedente', self._xml_version(os.path.join(installed, 'addon.xml'))))
		else: logger('Fen Light', 'SkinUpdater: scambio precedente gia\' completo, ripulisco')
		shutil.rmtree(work, ignore_errors=True)

	def _swap(self, staged):
		"""Due rename e una cancellazione, con un giornale intorno.

		I rename sono atomici: nessuno dei due puo' rompersi a meta'. Fra l'uno e l'altro pero' c'e'
		una finestra di microsecondi in cui il percorso della skin non esiste, e su Android il processo
		puo' essere ucciso in qualunque momento. Per questo si scrive `SCAMBIO_IN_CORSO` prima di
		cominciare e lo si toglie solo alla fine: e' quel file a dire a `_repair`, al prossimo avvio,
		che c'e' qualcosa da finire. Non elimina la finestra -- in Python non si puo' -- ma la rende
		una sessione da recuperare invece di un dispositivo senza GUI.

		Se il secondo rename FALLISCE (errore vero, non uccisione) si rimette a posto il vecchio qui e
		subito, e si riprova al prossimo giro."""
		import shutil
		from modules.kodi_utils import logger
		installed, work = self._paths()
		backup = os.path.join(work, BACKUP)
		shutil.rmtree(backup, ignore_errors=True)
		# Ultimo controllo prima di toccare il disco: se Kodi sta gia' chiudendo non si comincia
		# nemmeno. Non chiude la finestra (l'uccisione puo' arrivare un istante dopo), ma toglie di
		# mezzo il caso piu' probabile -- l'utente che spegne dopo essere stato fermo due minuti,
		# cioe' proprio la condizione che ci ha portati qui.
		if self.monitor.abortRequested(): raise InterruptedError('Kodi sta chiudendo, scambio rimandato')
		with open(os.path.join(work, MARKER), 'w', encoding='utf-8') as handle: handle.write(SKIN_ID)
		os.rename(installed, backup)
		try: os.rename(staged, installed)
		except Exception:
			os.rename(backup, installed)
			logger('Fen Light', 'SkinUpdater: scambio fallito, la skin precedente e\' stata rimessa al suo posto')
			raise
		shutil.rmtree(work, ignore_errors=True)
		version = self._xml_version(os.path.join(installed, 'addon.xml'))
		logger('Fen Light', 'SkinUpdater: %s %s in posizione. Nessun ReloadSkin: si vedra\' al prossimo avvio.' % (SKIN_ID, version))
