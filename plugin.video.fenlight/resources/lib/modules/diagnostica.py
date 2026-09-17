# -*- coding: utf-8 -*-
# LOTTO 261 -- LA PARTE DELLA DIAGNOSTICA CHE VIVE DENTRO KODI.
#
# E' quasi vuota, ED E' IL PUNTO. Il censimento per thread del lotto 246 girava qui dentro, in un
# thread Python del servizio, e costava 53 ms mediani con punte a 1875 (11/09, 64 finestre): il lotto
# 248 l'ha visto produrre da solo i tredici ritardi del ciclo che poi denunciava. Non era questione
# di costanti. Dentro Kodi una sonda contende il GIL agli altri sotto-interpreti e il lock della GUI
# al thread che disegna, cioe' proprio le due risorse che deve misurare, e la sua riga di log passa
# da spdlog che a livello debug fa flush a ogni riga sul thread chiamante (xbmc/utils/log.cpp:53).
#
# Dal 261 il censimento sta FUORI: strumenti/diagnostica/sonda.sh, un processo a se' che legge
# /proc/<pid di kodi>/task. Misurato sulla stick: ~83 ms a campione su 113 thread, cadenza 2 s, cioe'
# l'1% della macchina, e senza toccare nessun lock di Kodi. Qui restano solo le due cose che da fuori
# NON si possono fare:
#
#   1. RILEVARE IL LIVELLO DI LOG. E' l'interruttore chiesto: la suite si accende quando il log passa
#      da info a debug, perche' e' a debug che Kodi scrive i NOMI dei thread -- da fuori /proc non li
#      ha (vedi `battezza`).
#   2. BATTEZZARE I NOSTRI THREAD, cosi' che nella traccia esterna si riconoscano senza bisogno del
#      log. Costa UNA scrittura per thread, una volta nella vita del thread.
#
# Quello che qui NON c'e', e non deve tornarci: cicli di campionamento, getInfoLabel ripetute,
# letture di /proc. Se serve un numero nuovo, si aggiunge alla sonda.
#
# Modulo FOGLIA come modules/perf.py: a livello di modulo importa solo xbmc e xbmcgui, che sono
# moduli C dell'API di Kodi. Chiunque puo' prenderlo senza cicli di import e senza trascinarsi dietro
# un albero.
import xbmc, xbmcgui

# La proprieta' di finestra e' il canale, come per l'interruttore di perf.py (lotto 161): una
# lettura di proprieta' e' la stessa traversata che il codice fa centinaia di volte, mentre aprire il
# database delle impostazioni costava 93 ms sulla stick piu' i 36 di datetime tirato da sqlite3.
PROP_LIVELLO = 'fenlight.diag.livello'
PROP_OVERLAY = 'fenlight.diag.overlay'

# I livelli sono quelli di Kodi, xbmc/commons/ilog.h:
#   -1 NONE   0 NORMAL (solo info e peggio)   1 DEBUG (tutto)   2 DEBUG_FREEMEM (tutto + overlay)
NORMALE, DEBUG, DEBUG_OVERLAY = 0, 1, 2

_CACHE = []


def rileva():
	"""(livello, overlay, fonte). Da chiamare UNA volta, dal servizio. Costa una getCondVisibility
	e al massimo una lettura di file.

	DUE STRADE PORTANO AL DEBUG, e vanno guardate entrambe perche' non sono equivalenti:

	  a) l'impostazione GUI `debug.showloginfo`. Porta il livello a 2 e ACCENDE ANCHE L'OVERLAY a
	     schermo (xbmc/settings/AdvancedSettings.cpp:58 -> LOG_LEVEL_DEBUG_FREEMEM).
	  b) <loglevel>1</loglevel> in advancedsettings.xml. Porta il livello a 1: stesso identico log,
	     NIENTE overlay, perche' CGUIWindowDebugInfo::UpdateVisibility si apre solo da 2 in su
	     (xbmc/windows/GUIWindowDebugInfo.cpp:45).

	E LA DIFFERENZA NON E' COSMETICA. L'overlay ricostruisce a ogni giro la stringa con MEM e FPS, e
	`m_layout->Update(info)` chiama MarkDirtyRegion() ogni volta che il testo cambia -- cioe' quasi
	sempre, perche' contiene i KB liberi. Con `algorithmdirtyregions` al valore predefinito 3
	(FILL_VIEWPORT_ON_CHANGE) una qualunque regione sporca fa ridisegnare TUTTO IL VIEWPORT
	(xbmc/guilib/GUIWindowManager.cpp:1303). Cioe': accendere il debug dal menu di Kodi trasforma una
	interfaccia ferma in una che ridisegna a schermo pieno sessanta volte al secondo. Chi misura gli
	fps con l'overlay acceso sta misurando l'overlay.
	La regola che ne discende sta in DIAGNOSTICA.md: per misurare si usa (b); (a) si accende solo per
	leggere un numero al volo, sapendo che in quel momento il carico non e' quello vero.
	"""
	livello, fonte, overlay = NORMALE, 'nessuna', False
	try:
		if xbmc.getCondVisibility('System.GetBool(debug.showloginfo)'):
			livello, overlay, fonte = DEBUG_OVERLAY, True, 'impostazione GUI (con overlay)'
	except Exception: pass
	# advancedsettings.xml: si legge solo se serve, e non e' un percorso caldo -- gira una volta
	# all'avvio del servizio.
	try:
		import xbmcvfs
		percorso = xbmcvfs.translatePath('special://profile/advancedsettings.xml')
		if xbmcvfs.exists(percorso):
			with xbmcvfs.File(percorso) as f: testo = f.read()
			import re
			m = re.search(r'<loglevel[^>]*>\s*(-?\d+)\s*<', testo or '')
			if m:
				da_file = int(m.group(1))
				# CAdvancedSettings fa `m_logLevel = max(m_logLevel, m_logLevelHint)` quando trova il
				# tag (AdvancedSettings.cpp:892): vince il piu' alto dei due, non l'ultimo letto.
				if da_file > livello:
					livello, fonte = da_file, 'advancedsettings.xml (loglevel %d)' % da_file
				elif da_file >= DEBUG and livello >= DEBUG:
					fonte += ' + advancedsettings.xml'
	except Exception: pass
	return livello, overlay, fonte


def pubblica(livello, overlay):
	"""Il servizio rispecchia il livello dove tutti possono leggerlo senza aprire niente."""
	try:
		w = xbmcgui.Window(10000)
		w.setProperty(PROP_LIVELLO, str(livello))
		w.setProperty(PROP_OVERLAY, 'true' if overlay else 'false')
	except Exception: pass


def livello():
	"""Il livello di log, dalla proprieta' di finestra. Una lettura per interprete.

	Con reuselanguageinvoker=false ogni invocazione e' un interprete nuovo, quindi "una volta per
	interprete" e "una volta per invocazione" sono la stessa cosa -- vedi perf.enabled().
	"""
	if _CACHE: return _CACHE[0]
	valore = NORMALE
	try:
		grezzo = xbmcgui.Window(10000).getProperty(PROP_LIVELLO)
		if grezzo: valore = int(grezzo)
		else:
			# Rispecchiamento non ancora avvenuto (avvio molto precoce): si paga il rilevamento una
			# volta invece di restare ciechi.
			valore = rileva()[0]
	except Exception: pass
	_CACHE.append(valore)
	return valore


def attiva():
	"""La suite e' accesa? Vero da livello DEBUG in su."""
	return livello() >= DEBUG


# ------------------------------------------------------------------------------------------------
def battezza(nome, percorso=None):
	"""Da' un nome al thread CORRENTE, visibile da fuori in /proc/<pid>/task/<tid>/comm.

	PERCHE' SERVE. Su Android Kodi non nomina i propri thread: CThreadImplLinux::SetThreadInfo chiama
	pthread_setname_np solo `#if defined(__GLIBC__)` e Android e' Bionic
	(xbmc/platform/linux/threads/ThreadImplLinux.cpp:80-83). Su Linux un thread EREDITA il `comm` da chi
	lo crea, quindi nella traccia esterna tutti i nostri thread -- i servizi, le code, ogni
	invocazione del plugin -- compaiono col nome del thread Java che ha generato l'applicazione, e
	sono indistinguibili fra loro e da quelli di Kodi. Il lotto 249 ha perso una serata proprio cosi':
	`Thread-3` presente in tutti e tredici i ritardi del ciclo, e nessun modo di dire quale fosse.
	Kodi i suoi non li puo' nominare; i NOSTRI si.

	COME. Si scrive su /proc/self/task/<tid>/comm, che il kernel consente al processo proprietario
	senza alcun permesso speciale. NON serve ctypes con prctl: `threading.get_native_id()` esiste da
	Python 3.8 e Kodi 21.1 porta 3.11.7 (tools/depends/target/python3/PYTHON3-VERSION), quindi il tid
	si ottiene senza dipendenze e senza caricare una libreria.

	E SI SCRIVE CON os.open/os.write, NON CON open(percorso, 'w'). Verificato sulla stick il 13/09:
	il gestore `comm` del kernel accetta una write semplice all'offset zero -- `dd` ci riesce, anche
	con 22 byte (il kernel tronca a 15) -- ma rifiuta con EINVAL cio' che arriva in altre forme: il
	`printf` di toybox fallisce sistematicamente, con e senza a capo. `open(percorso, 'w')` di Python
	aggiunge O_TRUNC e un livello di buffering, cioe' proprio le variabili che distinguono i due casi.
	os.open(O_WRONLY) + os.write e' la forma provata: una write, senza troncamento, senza buffer.
	La prima stesura usava `open(..., 'w')` e non era stata provata su nessun kernel.

	COSTO. Una open e una write di al piu' 15 byte, UNA volta nella vita del thread. Il `comm` del
	kernel e' lungo 15 caratteri piu' il terminatore: si tronca qui invece di lasciarlo fare al
	kernel, cosi' il nome che si legge nella traccia e' quello che si e' scelto.

	`percorso` e' un parametro per la stessa ragione per cui `censimento_cpu` ha `radice`: senza,
	questa funzione si potrebbe provare solo su una macchina con /proc, cioe' mai sul Mac.

	E' l'unica cosa che questo modulo fa al sistema, e la fa solo a diagnostica accesa: a log normale
	non si tocca niente, perche' una misura che cambia cio' che misura non e' una misura.
	"""
	if not attiva(): return False
	try:
		# LOTTO 307: _thread e non threading. threading si tira dietro functools, collections, reprlib e
		# compagnia, e il profilatore degli import lo attribuiva proprio a questo modulo in OGNI invocazione
		# a diagnostica accesa (referti af-hub-302 e 304): lo strumento pesava sulla misura. _thread e' un
		# modulo C gia' caricato e ha la stessa get_native_id.
		import os
		from _thread import get_native_id
		if percorso is None:
			percorso = '/proc/self/task/%d/comm' % get_native_id()
		fd = os.open(percorso, os.O_WRONLY)
		try: os.write(fd, nome[:15].encode('utf-8', 'replace'))
		finally: os.close(fd)
		return True
	except Exception:
		return False
