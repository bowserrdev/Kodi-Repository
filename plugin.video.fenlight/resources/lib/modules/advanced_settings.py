# -*- coding: utf-8 -*-
# Generatore di advancedsettings.xml ottimizzato per cache di rete / streaming.
# Tiene conto della RAM del dispositivo e (opzionale) di un test di velocita' reale.
import os
import time
import xml.etree.ElementTree as ET
from modules.kodi_utils import (translate_path, get_infolabel, confirm_dialog, ok_dialog,
								notification, show_text, execute_builtin, progressDialogBG)
# logger = __import__('modules.kodi_utils', fromlist=['logger']).logger

SETTINGS_PATH = 'special://userdata/advancedsettings.xml'

# Endpoint per la misura della banda (in ordine di preferenza, con fallback).
SPEEDTEST_URLS = (
	'https://speed.cloudflare.com/__down?bytes=25000000',
	'https://speed.hetzner.de/100MB.bin',
	'https://proof.ovh.net/files/100Mb.dat')
SPEEDTEST_TARGET_BYTES = 25 * 1024 * 1024  # ~25 MB scaricati
SPEEDTEST_MAX_SECONDS = 12				   # tetto di durata del test

# Preset: memorysize in MB (Kodi alloca ~3x in RAM), readfactor, buffermode.
# buffermode 1 = bufferizza TUTTI gli stream di rete (consigliato per streaming).
PRESETS = {
	'slow':   {'name': 'Lenta / Mobile',        'memorysize_mb': 50,  'readfactor': 4,  'buffermode': 1},
	'medium': {'name': 'ADSL / Media',          'memorysize_mb': 100, 'readfactor': 8,  'buffermode': 1},
	'fast':   {'name': 'Fibra / Veloce',        'memorysize_mb': 150, 'readfactor': 20, 'buffermode': 1},
	'ultra':  {'name': 'Gigabit / Ultraveloce', 'memorysize_mb': 200, 'readfactor': 30, 'buffermode': 1}}
PRESET_ORDER = ('slow', 'medium', 'fast', 'ultra')

# -------------------------------------------------------------------------- #
# Rilevamento dispositivo
# -------------------------------------------------------------------------- #
def _total_ram_mb():
	# System.Memory(total) restituisce qualcosa tipo "16384 MB".
	try:
		raw = get_infolabel('System.Memory(total)') or ''
		digits = ''.join(c for c in raw if c.isdigit())
		return int(digits) if digits else 0
	except Exception:
		return 0

def _ram_capped_memorysize_mb(desired_mb, total_ram_mb):
	# Kodi usa ~3x memorysize. Non superare il 25% della RAM totale.
	if total_ram_mb <= 0:
		return desired_mb
	cap_mb = int(total_ram_mb * 0.25 / 3)
	return max(20, min(desired_mb, cap_mb))

# -------------------------------------------------------------------------- #
# Test di rete
# -------------------------------------------------------------------------- #
def _speed_test_mbps():
	# UNICO punto che vuole ancora requests: iter_content, cioe' la lettura a blocchi senza tenere in
	# memoria l'intero file. Il nostro client legge la risposta tutta in una volta e qui non va bene --
	# il test di velocita' scarica decine di MB. E' un'azione manuale, si paga solo se la si chiede.
	from modules.kodi_utils import import_requests_real
	requests = import_requests_real('_speed_test_mbps')
	for url in SPEEDTEST_URLS:
		try:
			start = time.time()
			downloaded = 0
			with requests.get(url, stream=True, timeout=15) as r:
				r.raise_for_status()
				for chunk in r.iter_content(chunk_size=65536):
					downloaded += len(chunk)
					elapsed = time.time() - start
					if downloaded >= SPEEDTEST_TARGET_BYTES or elapsed > SPEEDTEST_MAX_SECONDS:
						break
			elapsed = time.time() - start
			if elapsed > 0 and downloaded > 1024 * 1024:
				return round((downloaded * 8) / elapsed / 1_000_000, 1)
		except Exception:
			continue
	return None

def _preset_for_speed(mbps):
	if mbps is None: return 'medium'
	if mbps < 10:    return 'slow'
	if mbps < 30:    return 'medium'
	if mbps < 100:   return 'fast'
	return 'ultra'

# -------------------------------------------------------------------------- #
# Scrittura del file (preservando le altre impostazioni gia' presenti)
# -------------------------------------------------------------------------- #
def _load_root(path):
	if os.path.exists(path):
		try:
			root = ET.parse(path).getroot()
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

def _write_cache_block(memorysize_mb, readfactor, buffermode):
	path = translate_path(SETTINGS_PATH)
	root = _load_root(path)
	_backup(path)
	for existing in root.findall('cache'):
		root.remove(existing)
	cache = ET.SubElement(root, 'cache')
	ET.SubElement(cache, 'buffermode').text = str(buffermode)
	ET.SubElement(cache, 'memorysize').text = str(int(memorysize_mb) * 1024 * 1024)
	ET.SubElement(cache, 'readfactor').text = str(readfactor)
	_save_root(root, path)
	return path

# -------------------------------------------------------------------------- #
# Flusso comune di applicazione
# -------------------------------------------------------------------------- #
def _apply_preset(preset_key, mbps=None):
	preset = PRESETS[preset_key]
	total_ram = _total_ram_mb()
	memorysize_mb = _ram_capped_memorysize_mb(preset['memorysize_mb'], total_ram)
	capped = memorysize_mb < preset['memorysize_mb']

	lines = []
	if mbps is not None:
		lines.append('Connessione misurata: [B]%s Mbps[/B]' % mbps)
	lines.append('Preset: [B]%s[/B]' % preset['name'])
	lines.append('RAM totale rilevata: %s' % ('%s MB' % total_ram if total_ram else 'sconosciuta'))
	lines.append('')
	lines.append('Cache (memorysize): [B]%s MB[/B] (~%s MB di RAM usata)' % (memorysize_mb, memorysize_mb * 3))
	if capped:
		lines.append('[COLOR orange](ridotta da %s MB per limite RAM)[/COLOR]' % preset['memorysize_mb'])
	lines.append('readfactor: [B]%s[/B]   buffermode: [B]%s[/B]' % (preset['readfactor'], preset['buffermode']))
	lines.append('')
	lines.append('Scrivere advancedsettings.xml? (le altre impostazioni verranno mantenute)')

	confirm = confirm_dialog(heading='Ottimizza Cache & Streaming', text='[CR]'.join(lines),
							ok_label='Applica', cancel_label='Annulla')
	if not confirm:
		return
	try:
		path = _write_cache_block(memorysize_mb, preset['readfactor'], preset['buffermode'])
	except Exception as e:
		return ok_dialog(heading='Errore', text='Impossibile scrivere il file:[CR]%s' % e)

	notification('advancedsettings.xml aggiornato')
	restart = confirm_dialog(heading='Riavvio richiesto',
							text='Le impostazioni cache hanno effetto solo dopo il riavvio di Kodi.[CR]Riavviare ora?',
							ok_label='Riavvia', cancel_label='Piu\' tardi')
	if restart:
		execute_builtin('RestartApp')

# -------------------------------------------------------------------------- #
# Voci richiamate dal router (navigator -> advancedsettings.<func>)
# -------------------------------------------------------------------------- #
def network_test(params):
	progress = progressDialogBG()
	progress.create('Fen Light', 'Test di velocita\' in corso...')
	try:
		mbps = _speed_test_mbps()
	finally:
		try: progress.close()
		except Exception: pass
	if mbps is None:
		return ok_dialog(heading='Test di Rete',
						text='Impossibile completare il test di rete.[CR]Scegli un preset manualmente.')
	preset_key = _preset_for_speed(mbps)
	preset = PRESETS[preset_key]
	notification('Velocita\': %s Mbps - consigliato: %s' % (mbps, preset['name']))
	return _apply_preset(preset_key, mbps=mbps)

def auto(params):
	return network_test(params)

def apply(params):
	preset_key = params.get('preset', 'medium')
	if preset_key not in PRESETS:
		return
	return _apply_preset(preset_key)

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

def show(params):
	path = translate_path(SETTINGS_PATH)
	if not os.path.exists(path):
		return ok_dialog(heading='advancedsettings.xml', text='Il file non esiste ancora.')
	return show_text('advancedsettings.xml', file=path, font_size='small')

def reset(params):
	confirm = confirm_dialog(heading='Rimuovi ottimizzazione cache',
							text='Rimuovere il blocco <cache> da advancedsettings.xml?[CR]Le altre impostazioni restano invariate.',
							ok_label='Rimuovi', cancel_label='Annulla')
	if not confirm:
		return
	path = translate_path(SETTINGS_PATH)
	if not os.path.exists(path):
		return notification('Nessun file da modificare')
	root = _load_root(path)
	removed = False
	for existing in root.findall('cache'):
		root.remove(existing)
		removed = True
	if not removed:
		return notification('Nessun blocco cache presente')
	_backup(path)
	_save_root(root, path)
	notification('Ottimizzazione cache rimossa')
	ok_dialog(heading='Fatto', text='Riavvia Kodi per applicare la modifica.')
