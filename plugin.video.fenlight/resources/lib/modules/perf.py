# -*- coding: utf-8 -*-
# INTERRUTTORE UNICO della strumentazione (lotto 83).
#
# Perche' un modulo a se' e non una costante in paginator: paginator importa kodi_utils a livello di
# modulo, quindi kodi_utils non puo' importare paginator senza creare un ciclo -- e tre delle righe di
# misura (INVOCAZIONE, IMPORT, CONSEGNA) stanno proprio in kodi_utils. Questo file e' una FOGLIA:
# a livello di modulo importa solo xbmc e xbmcgui -- moduli C dell'API di Kodi, non codice Fen Light --
# cosi' chiunque puo' prenderlo senza cicli e senza trascinarsi dietro un albero. Costa un file in
# piu' per invocazione (~6-8 ms a cache calda), che e' il prezzo di poter spegnere tutto il resto.
#
# La lettura dell'impostazione avviene UNA volta per invocazione e viene tenuta in memoria: con
# reuselanguageinvoker=false ogni invocazione e' un interprete nuovo, quindi "una volta per
# interprete" e "una volta per invocazione" sono la stessa cosa.
#
# Cio' che NON viene spento: le chiamate perf_counter() sparse nei costruttori. Sono letture di
# orologio, ordini di grandezza sotto quello che misurano, e toglierle vorrebbe dire smontare la
# struttura a fasi per rimetterla la prossima volta che serve.
import xbmc, xbmcgui

SETTING_ID = 'fenlight.perf.instrumentation'
_STATE = []

def enabled():
	# L'interruttore si legge dalla PROPRIETA' DI FINESTRA, non dal database (lotto 161).
	# sync_settings, all'avvio del servizio, rispecchia OGNI impostazione in una proprieta' di
	# Window(10000) -- e' SettingsCache.set_memory_cache -- e get_setting stesso la consulta per
	# prima. Passare dal database significava importare caches.settings_cache e con lui
	# caches.base_cache e sqlite3: 93 ms sulla stick, piu' i 36 di datetime che sqlite3.dbapi2 si
	# tira dietro. Un prezzo pagato da CHIUNQUE importi paginator, perche' li' due costanti di
	# modulo (PG_DEBUG e PERF) chiamano questa funzione durante l'import. Nell'invocazione che il
	# lotto 160 lascia cadere -- 697 ms totali, 636 di import, per confrontare due stringhe -- era
	# la voce piu' cara, ed era l'INTERRUTTORE della strumentazione a pagarla: spegnerla costava
	# quanto tenerla accesa.
	# Una lettura di proprieta' e' la stessa traversata verso la GUI che il codice fa centinaia di
	# volte per costruzione (get_property in kodi_utils e' esattamente questa riga).
	if _STATE: return _STATE[0]
	try:
		raw = xbmcgui.Window(10000).getProperty(SETTING_ID)
		if raw: value = raw == 'true'
		else:
			# Rispecchiamento non ancora avvenuto (avvio molto precoce, prima che il servizio abbia
			# chiamato sync_settings): si paga il database una volta e si ricade nel caso di prima.
			from caches.settings_cache import get_setting
			value = get_setting(SETTING_ID, 'true') == 'true'
	except:
		# Se le impostazioni non sono leggibili (avvio molto precoce, database in creazione) si
		# resta accesi: una riga di log in piu' non fa danno, una misura persa si.
		value = True
	_STATE.append(value)
	return value

def log(heading, message):
	if not enabled(): return
	try: xbmc.log('###%s###: %s' % (heading, message), 1)
	except: pass

# --------------------------------------------------------------------------------------------
# Memoria. System.FreeMemory e' l'unico numero di memoria che Kodi espone a Python senza permessi
# di sistema, e sull'Android non rootato della stick e' anche l'unico ottenibile: /proc/meminfo
# e' leggibile ma riporta la memoria della MACCHINA, non quella concessa al processo, e dumpsys
# richiede adb. Torna una stringa tipo '123MB'.
# ATTENZIONE all'interpretazione: e' memoria libera di SISTEMA. Android la tiene deliberatamente
# bassa (la RAM inutilizzata e' RAM sprecata), quindi il valore assoluto dice poco. Quello che dice
# molto e' la DERIVATA: se scende monotonicamente durante una sessione e non risale mai, qualcosa
# non viene rilasciato.
def free_memory_mb():
	try:
		raw = xbmc.getInfoLabel('System.FreeMemory') or ''
		digits = ''.join(c for c in raw if c.isdigit())
		return int(digits) if digits else -1
	except: return -1

def memory_suffix():
	# Coda da appendere a una riga esistente. Vuota quando la strumentazione e' spenta o il numero
	# non e' leggibile, cosi' il chiamante non deve mettere condizioni attorno.
	if not enabled(): return ''
	free = free_memory_mb()
	return '' if free < 0 else ' | memoria libera %s MB' % free
