# -*- coding: utf-8 -*-
"""`canwritedatabases` del profilo: spegnerlo da dentro Fen Light, e farlo restare spento.

COSA SPEGNE. `ApplicationPlayerCallback.cpp:159` (ramo Omega) e' l'UNICO punto da cui Kodi salva lo
stato di riproduzione alla chiusura del player:

    if (...GetProfileManager()->GetCurrentProfile().canWriteDatabases())
      CSaveFileState::DoWork(fileItem, resumeBookmark, playCountUpdate);

`DoWork` scrive nel database video usando come chiave l'URL risolto del momento -- nodo CDN e token in
scadenza, quindi una riga nuova a ogni riproduzione -- e quella scrittura annuncia
`VideoLibrary.OnUpdate`, che nel ramo libreria di `CDirectoryProvider::Announce` invalida TUTTI i
contenitori senza guardare niente: al rientro dal player si ricostruisce ogni widget della home. Fen
Light quel database non lo legge mai (usa `StartPercent` e Trakt), quindi spegnendolo non si perde
nulla di nostro. Le soglie di `advancedsettings.xml` non servono: `ignoresecondsatstart` arriva a 900
e comunque `DoWork` viene chiamata lo stesso. L'interruttore vero e' questo flag, ed e' per profilo.

Effetto collaterale, lo stesso di quando la modifica si faceva a mano: le voci native di Kodi "Segna
come gia' visto"/"non visto" restano visibili ma inerti. La lista e' fissa in
`CContextMenuManager::Init()` e non e' rimovibile da un addon.

PERCHE' NON BASTA SCRIVERE IL FILE. `profiles.xml` lo possiede Kodi: lo legge una volta all'avvio e da
li' in poi la verita' e' la sua copia in memoria. `CProfileManager` e' registrato come settings
handler (`ProfileManager.cpp:97`) e il suo `OnSettingsSaved()` chiama `Save()`: OGNI
`CSettings::Save()` riscrive `profiles.xml` con il valore che Kodi ha in memoria. Lo spegnimento
pulito e' uno di quei momenti -- la riga "Saving settings" di `CApplication::Stop()`. Quindi una
modifica scritta a meta' sessione non serve a niente e non sopravvive: la sessione in corso ha gia'
il vecchio valore in memoria, e il boot successivo trova di nuovo `true`. E' esattamente il motivo
per cui il 07/09 la modifica e' stata fatta a mano, a Kodi FERMO.

COME SI FA DA DENTRO. Riscrivendo il file DOPO il salvataggio di Kodi. Il posto dove farlo esiste
gia' e non va costruito: i servizi Python muoiono dopo. Misurato sulla Mi Stick, log del 17/09 04:48:

    04:48:31.818  Saving settings                 <- Kodi riscrive profiles.xml dalla memoria
    04:48:32.619  SkinUpdater Service Finished    <- i servizi vedono l'abort 0,8 s dopo
    04:48:33.695  Exiting the application...

Non e' una corsa vinta per fortuna: e' l'ordine di `CApplication::Stop()`, che salva le impostazioni
come terzo passo e aspetta gli script Python molto piu' avanti. La scrittura fatta all'uscita del
servizio e' sempre l'ultima parola sul file.

CHI COMANDA. Il file non e' lo stato: e' il risultato. Lo stato e' il marcatore in `addon_data`,
scritto dal pulsante, e dice cosa l'utente ha chiesto. Senza marcatore questo modulo non scrive mai
niente -- su un dispositivo dove il pulsante non e' mai stato premuto non esiste comportamento
aggiunto. Con il marcatore si riconcilia in due momenti, avvio e uscita del servizio, e in nessun
altro: niente timer, niente sorveglianza. I due momenti bastano perche' il file conta solo all'avvio
di Kodi, e l'unico che lo cambia alle nostre spalle e' Kodi stesso.

Serve anche l'avvio, non solo l'uscita: se il processo viene ucciso da Android fra un
`CSettings::Save()` di meta' sessione e l'uscita dei servizi, il file resta con `true` e il flag
sarebbe perso in silenzio. Il controllo all'avvio lo rimette, e vale dal boot dopo.
"""

import os
import xml.etree.ElementTree as ET

PROFILES_PATH = 'special://masterprofile/profiles.xml'
BACKUP_SUFFIX = '.bak-canwritedatabases'
FLAG = 'canwritedatabases'
MARKER = 'profile_canwritedatabases'


def _profiles_file():
	from modules.kodi_utils import translate_path
	# masterprofile e non userdata: `special://userdata` segue il profilo corrente
	# (`SpecialProtocol.cpp:154`), mentre profiles.xml sta sempre nel profilo master
	# (`PROFILES_FILE` in ProfileManager.cpp:71).
	return translate_path(PROFILES_PATH)


def _marker_file():
	from modules.kodi_utils import addon_profile
	return os.path.join(addon_profile(), MARKER)


# --- marcatore: cosa ha chiesto l'utente ----------------------------------------------------------

def wanted():
	"""'false', 'true' oppure None quando Fen Light non gestisce il flag (caso normale)."""
	try:
		with open(_marker_file(), 'r', encoding='utf-8') as handle:
			value = handle.read().strip().lower()
		return value if value in ('true', 'false') else None
	except Exception: return None


def set_wanted(value):
	"""`None` toglie il marcatore: da quel momento il flag torna a essere affare di Kodi."""
	path = _marker_file()
	if value is None:
		try: os.remove(path)
		except Exception: pass
		return
	directory = os.path.dirname(path)
	if not os.path.exists(directory): os.makedirs(directory)
	with open(path, 'w', encoding='utf-8') as handle: handle.write(value)


# --- il file dei profili --------------------------------------------------------------------------

def read_flag():
	"""Cosa dice il file adesso: 'true', 'false', o None se non si legge.

	Con piu' profili vince il piu' restrittivo: finche' ne resta uno con `true` il lavoro non e'
	finito, e dire 'false' nasconderebbe proprio il profilo rimasto indietro."""
	path = _profiles_file()
	if not os.path.exists(path): return None
	try: root = ET.parse(path).getroot()
	except Exception: return None
	values = [(node.findtext(FLAG) or 'true').strip().lower() for node in root.findall('profile')]
	if not values: return None
	return 'true' if 'true' in values else 'false'


def write_flag(value):
	"""Scrive il valore su tutti i profili. Torna quanti ne ha cambiati (0 = era gia' cosi').

	Il backup si fa una volta sola e solo prima della prima modifica: la copia di un file gia'
	modificato non e' un originale, e sovrascrivere il backup buono con quella lo perderebbe. Stesso
	nome usato dalla modifica a mano del 07/09, cosi' i dispositivi restano leggibili allo stesso
	modo."""
	path = _profiles_file()
	root = ET.parse(path).getroot()
	changed = 0
	for node in root.findall('profile'):
		flag = node.find(FLAG)
		if flag is None: flag = ET.SubElement(node, FLAG)
		if (flag.text or '').strip().lower() == value: continue
		flag.text = value
		changed += 1
	if not changed: return 0
	backup = path + BACKUP_SUFFIX
	if not os.path.exists(backup):
		import shutil
		# copyfile, non copy2: vedi skin_updater._carry_over -- su Android 11+ la copia degli xattr
		# SELinux fallisce con EACCES e la scrittura del flag non avverrebbe mai.
		shutil.copyfile(path, backup)
	try: ET.indent(root, space='    ')
	except Exception: pass
	# Scrittura in due tempi: se il processo muore a meta' -- e qui si scrive proprio mentre Kodi
	# chiude -- un profiles.xml troncato lascerebbe Kodi senza profili al boot successivo.
	temp = path + '.fenlight-tmp'
	ET.ElementTree(root).write(temp, encoding='utf-8', xml_declaration=False)
	os.replace(temp, path)
	return changed


# --- riconciliazione ------------------------------------------------------------------------------

def reconcile(where):
	"""Rimette nel file cio' che l'utente ha chiesto, se Kodi nel frattempo l'ha riscritto.

	Idempotente e silenziosa quando non c'e' niente da fare: senza marcatore non legge nemmeno
	profiles.xml, con il marcatore costa una lettura di ~1 KB."""
	from modules.kodi_utils import logger
	value = wanted()
	if value is None: return False
	current = read_flag()
	if current is None or current == value: return False
	changed = write_flag(value)
	if changed: logger('Fen Light', 'profile_flag: %s riportato a %s su %s profilo/i (%s) -- vale dal prossimo avvio'
						% (FLAG, value, changed, where))
	return bool(changed)


def on_service_start():
	"""Avvio del servizio. Riconcilia, e poi si toglie di mezzo se non serve piu'.

	Il marcatore sparisce quando la richiesta e' `true` ED e' in vigore: `true` e' il valore di Kodi
	e da quel momento non ha piu' bisogno di nessuno che lo difenda -- la copia in memoria e' `true`
	e ogni riscrittura di Kodi scrive `true`. Cosi' il ripristino non lascia dietro di se' uno stato
	da ricordare."""
	reconcile('avvio')
	if wanted() == 'true' and read_flag() == 'true': set_wanted(None)


def on_service_stop():
	"""Uscita del servizio: l'ultima parola sul file, dopo il "Saving settings" di Kodi."""
	reconcile('uscita')
