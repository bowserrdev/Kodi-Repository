# -*- coding: utf-8 -*-
# LIMITI DEL DECODITORE DEL DISPOSITIVO -- lotto 203.
#
# PERCHE' ESISTE. L'08/09 due riproduzioni sono morte sulla Mi Stick, e Android le ha registrate cosi'
# (dumpsys media.metrics):
#
#     OMX.amlogic.hevc.decoder.awesome  1920x1456  errcode=0x80001001  errstate=STARTED  0 fotogrammi
#
# Nelle 45 sessioni registrate dal dispositivo, 43 sono riuscite -- tutte con altezza <= 1080, HEVC
# compreso fino a 1920x1080 con 1224 fotogrammi -- e le uniche 2 fallite sono le uniche 2 sopra i
# 1088. E 1088 e' esattamente cio' che la stick dichiara di se': max="1920x1088".
#
# NIENTE NUMERI SCRITTI QUI DENTRO. Questo e' un limite DI QUESTA stick, non del mondo: un'altra
# macchina puo' non averlo, o averne altri. Il numero si legge dal dispositivo o non esiste.
#
# SI FALLISCE IN FAVORE DELLA RIPRODUZIONE. Se i file non ci sono, non si leggono, sono scritti in
# un modo che non capiamo, o il codec non e' fra quelli mappati -- non si sa, e non sapere significa
# riprodurre. Su una Fire Stick, o su Mac, o su una macchina che non pubblica niente, questo modulo
# restituisce {} e da quel momento e' come se non esistesse. Deve essere un meccanismo che se
# funziona migliora e se non funziona non cambia niente.
from os import path as _p, listdir as _ls

# Le cartelle dove Android pubblica le capacita' dei codec. Su qualunque altra piattaforma non
# esistono, e il modulo si spegne da solo.
CARTELLE = ('/vendor/etc/', '/system/etc/', '/odm/etc/')
# I nomi Android dei mime verso i nomi con cui ffmpeg -- e quindi la nostra sonda e Kodi -- chiamano
# gli stessi codec. Cio' che non e' in questa tabella resta sconosciuto, quindi permesso.
MIME = {
	'video/hevc': 'hevc', 'video/avc': 'h264', 'video/av01': 'av1',
	'video/x-vnd.on2.vp9': 'vp9', 'video/x-vnd.on2.vp8': 'vp8',
	'video/mp4v-es': 'mpeg4', 'video/mpeg2': 'mpeg2', 'video/mpeg': 'mpeg2',
	'video/vc1': 'vc1', 'video/wvc1': 'vc1',
}
_cache = None


def _file_codec():
	trovati = []
	for cartella in CARTELLE:
		try: nomi = _ls(cartella)
		except: continue
		for nome in nomi:
			if not nome.startswith('media_codecs') or not nome.endswith('.xml'): continue
			# Il file delle prestazioni contiene le STESSE voci con update="true" e senza limite di
			# dimensione. Leggerlo come gli altri farebbe credere che ogni codec sia senza limiti e
			# spegnerebbe il controllo per intero. Si scarta due volte: qui per nome, e sotto per
			# l'attributo update, perche' l'attributo puo' comparire anche altrove.
			if 'performance' in nome: continue
			trovati.append(_p.join(cartella, nome))
	return trovati


def _leggi(percorso, dentro, profondita=0):
	"""Raccoglie (mime, larghezza, altezza) dai decoder video di un file, seguendo gli Include."""
	if profondita > 4 or percorso in dentro: return []
	dentro.add(percorso)
	try:
		import xml.etree.ElementTree as ET
		radice = ET.parse(percorso).getroot()
	except: return []
	fuori = []
	# Gli Include stanno di norma nella radice e si risolvono rispetto alla cartella del file che li
	# contiene. Questa stick non ne usa, ma AOSP si': senza, su altri dispositivi si leggerebbe meta'
	# elenco -- e meta' elenco vuol dire limiti piu' STRETTI del vero, cioe' scarti sbagliati.
	for inc in radice.iter('Include'):
		href = inc.get('href')
		if not href: continue
		fuori.extend(_leggi(_p.join(_p.dirname(percorso), href), dentro, profondita + 1))
	for decoders in radice.iter('Decoders'):
		for mc in decoders.findall('MediaCodec'):
			tipo, nome = mc.get('type', ''), mc.get('name', '')
			if not tipo.startswith('video/'): continue
			if mc.get('update') == 'true': continue
			# I decoder .secure servono ai flussi protetti e non possono servire i nostri: contarli
			# non cambia i numeri su questo dispositivo, ma su un altro potrebbe allargare il limite
			# usando una capacita' che a noi non e' accessibile.
			if nome.endswith('.secure'): continue
			massimo = None
			for lim in mc.findall('Limit'):
				if lim.get('name') != 'size': continue
				massimo = lim.get('max')
			if not massimo or 'x' not in massimo:
				# Decoder senza limite dichiarato: per quel mime non sappiamo niente, e non sapere
				# significa permettere. Si segna con None e chi legge spegne il controllo.
				fuori.append((tipo, None, None))
				continue
			try:
				larghezza, altezza = [int(_v) for _v in massimo.lower().split('x')[:2]]
				fuori.append((tipo, larghezza, altezza))
			except: fuori.append((tipo, None, None))
	return fuori


PROP = 'fenlight.decoder.limiti'


def limiti():
	"""{'hevc': [(1920, 1088)], 'h264': [...]} -- le coppie ammesse per codec.

	Una LISTA e non un massimo: un file e' riproducibile se ESISTE un decoder che lo regge, quindi
	collassare due decoder in una coppia sola inventerebbe una capacita' che nessuno dei due ha.
	Un codec che compare con un decoder senza limiti sparisce dal dizionario: sconosciuto = permesso.

	Il risultato si tiene in una proprieta' di finestra, non in una variabile: Fen Light gira con
	reuselanguageinvoker a false, quindi ogni azione e' un processo Python nuovo e una cache di
	modulo non sopravvive alla riproduzione che l'ha riempita. Cosi' l'import di ElementTree e la
	lettura dei file si pagano una volta per sessione di Kodi invece che a ogni film -- e l'import,
	non il parse, e' la parte cara: 6 ms su questo Mac, e la stick sugli import va dieci volte piu'
	piano. I file da cui esce sono immutabili, quindi la cache non puo' invecchiare male.
	"""
	global _cache
	if _cache is not None: return _cache
	try:
		import json
		from modules.kodi_utils import get_property
		salvato = get_property(PROP)
		if salvato:
			_cache = {_k: [tuple(_c) for _c in _v] for _k, _v in json.loads(salvato).items()}
			return _cache
	except: pass
	fuori, senza = {}, set()
	try:
		visti = set()
		for percorso in _file_codec():
			for tipo, larghezza, altezza in _leggi(percorso, visti):
				chiave = MIME.get(tipo)
				if not chiave: continue
				if larghezza is None: senza.add(chiave); continue
				fuori.setdefault(chiave, [])
				if (larghezza, altezza) not in fuori[chiave]: fuori[chiave].append((larghezza, altezza))
		for chiave in senza: fuori.pop(chiave, None)
	except: fuori = {}
	try:
		import json
		from modules.kodi_utils import set_property
		set_property(PROP, json.dumps(fuori))
	except: pass
	_cache = fuori
	return _cache


def riproducibile(codec, larghezza, altezza):
	"""(esito, spiegazione). esito True anche quando non si sa: il dubbio non ferma una riproduzione.

	La spiegazione serve al log e alla riga di misura: senza, una sorgente scartata sarebbe
	indistinguibile da una sorgente sparita.
	"""
	try:
		if not codec or not larghezza or not altezza: return True, 'misura mancante'
		ammessi = limiti().get(str(codec).lower())
		if not ammessi: return True, 'nessun limite noto per %s' % codec
		for _lw, _lh in ammessi:
			# Anche a dimensioni scambiate: un decoder che regge 1920x1088 regge un verticale
			# 1088x1920 su quasi tutti i dispositivi, e sbagliare in questo verso vuol dire scartare
			# un file buono. Nel dubbio si permette.
			if (larghezza <= _lw and altezza <= _lh) or (larghezza <= _lh and altezza <= _lw):
				return True, 'entro %sx%s' % (_lw, _lh)
		_lw, _lh = max(ammessi, key=lambda _c: _c[0] * _c[1])
		return False, '%s %sx%s oltre il massimo del dispositivo %sx%s' % (codec, larghezza, altezza, _lw, _lh)
	except: return True, 'controllo fallito'
