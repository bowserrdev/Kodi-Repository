# -*- coding: utf-8 -*-
import re
import json
from string import printable
from urllib.parse import unquote, unquote_plus
from modules import kodi_utils
from modules.metadata import episodes_meta
from modules.settings import date_offset
from modules.utils import adjust_premiered_date, get_datetime, jsondate_to_datetime, subtract_dates
# logger = kodi_utils.logger

supported_media, string = kodi_utils.supported_media, str
set_property, notification = kodi_utils.set_property, kodi_utils.notification
expiry_3hrs, expiry_1day, expiry_2days, expiry_3days, expiry_4days, expiry_7days, expiry_10days, expiry_14days, expiry_30days = 3, 24, 48, 72, 96, 168, 240, 336, 720
int_window_prop = 'fenlight.internal_results.%s'
RES_4K = ('.4k', 'hd4k', '4khd', '.uhd', 'ultrahd', 'ultra.hd', 'hd2160', '2160hd', '2160', '2160p', '216o', '216op')
RES_1080 = ('1080', '1080p', '1080i', 'hd1080', '1080hd', 'hd1080p', 'm1080p', 'fullhd', 'full.hd', '1o8o', '1o8op', '108o', '108op', '1o80', '1o80p')
RES_720 = ('720', '720p', '720i', 'hd720', '720hd', 'hd720p', '72o', '72op')
CAM = ('.cam.', 'camrip', 'hdcam', '.hd.cam', 'hqcam', '.hq.cam', 'cam.rip', 'dvdcam')
SCR = ('.scr.', 'screener', 'dvdscr', 'dvd.scr', '.r5', '.r6')
TELE = ('.tc.', '.ts.', 'tsrip', 'hdts', 'hdtc', '.hd.tc', 'dvdts', 'telesync', 'tele.sync', 'telecine', 'tele.cine')
VIDEO_3D = ('.3d.', '.sbs.', '.hsbs', 'sidebyside', 'side.by.side', 'stereoscopic', '.tab.', '.htab.', 'topandbottom', 'top.and.bottom')
DOLBY_VISION = ('dolby.vision', 'dolbyvision', '.dovi.', '.dv.')
HDR = (
'2160p.bluray.hevc.truehd', '2160p.bluray.hevc.dts', '2160p.bluray.hevc.lpcm', '2160p.blu.ray.hevc.truehd', '2160p.blu.ray.hevc.dts', '2160p.uhd.bluray',
'2160p.uhd.blu.ray', '2160p.us.bluray.hevc.truehd', '2160p.us.bluray.hevc.dts', '.hdr.', 'hdr10', 'hdr.10', 'uhd.bluray.2160p', 'uhd.blu.ray.2160p')
HDR_TRUE = ('.hdr.', '.hdr10.', 'hdr.10')
ENHANCED_UPSCALED = ('.enhanced.', '.upscaled.', '.enhance.', '.upscale.')
# LOTTO 184 -- AV1 non ha decodifica hardware sulla Mi Stick, e il riconoscimento perdeva il 39%
# dei casi. Il test era `'.av1.' in title`: pretende un punto PRIMA e DOPO, e nel 39% dei nomi veri
# dopo c'e' un trattino (`.av1-lazarus`, `.av1-alyh`, `.av1-r&h`) oppure prima c'e' una parentesi
# quadra (`[av1.2160p`, `[av1/1080p`). Misurato sulle 2108 sorgenti del log del 07/09: 41 file AV1,
# 25 riconosciuti, 16 sfuggiti. Ora il confine e' "qualunque cosa non sia lettera o cifra", che
# accetta punto, trattino, parentesi e barra e continua a rifiutare i nomi di gruppo come `dAV1nci`.
# Compilata una volta sola: si valuta per ogni sorgente, e sono migliaia per ricerca.
AV1_RE = re.compile(r'(?<![a-z0-9])av1(?![a-z0-9])')
CODEC_H264 = ('avc', 'h264', 'h.264', 'x264', 'x.264')
CODEC_H265 = ('h265', 'h.265', 'hevc', 'x265', 'x.265')
CODEC_XVID = ('xvid', '.x.vid')
CODEC_DIVX = ('divx', 'div2', 'div3', 'div4')
CODEC_MPEG = ('.mpg', '.mp2', '.mpeg', '.mpe', '.mpv', '.mp4', '.m4p', '.m4v', 'msmpeg', 'mpegurl')
CODEC_MKV = ('.mkv', 'matroska')
REMUX = ('remux', 'bdremux')
BLURAY = ('bluray', 'blu.ray', 'bdrip', 'bd.rip')
IMAX = ('.imax.', '.(imax).', '.(.imax.).')
DVD = ('dvdrip', 'dvd.rip')
WEB = ('.web.', 'webdl', 'web.dl', 'web-dl', 'webrip', 'web.rip')
HDRIP = ('.hdrip', '.hd.rip')
DOLBY_TRUEHD = ('true.hd', 'truehd')
DOLBY_DIGITALPLUS = ('dolby.digital.plus', 'dolbydigital.plus', 'dolbydigitalplus', 'dd.plus.', 'ddplus', '.ddp.', 'ddp2', 'ddp5', 'ddp7', 'eac3', '.e.ac3')
DOLBY_DIGITALEX = ('.dd.ex.', 'ddex', 'dolby.ex.', 'dolby.digital.ex.', 'dolbydigital.ex.')
DOLBYDIGITAL = ('dd2.', 'dd5', 'dd7', 'dolby.digital', 'dolbydigital', '.ac3', '.ac.3.', '.dd.')
DTSX = ('.dts.x.', 'dtsx')
DTS_HDMA = ('hd.ma', 'hdma')
DTS_HD = ('dts.hd.', 'dtshd')
AUDIO_8CH = ('ch8.', '8ch.', '7.1ch', '7.1.')
AUDIO_7CH = ('ch7.', '7ch.', '6.1ch', '6.1.')
AUDIO_6CH = ('ch6.', '6ch.', '5.1ch', '5.1.')
AUDIO_2CH = ('ch2', '2ch', '2.0ch', '2.0.', 'audio.2.0.', 'stereo')
SUBS = ('subita', 'subfrench', 'subspanish', 'subtitula', 'swesub', 'nl.subs', 'subbed')
ADS = ('1xbet', 'betwin')
MULTI_LANG = (
'hindi.eng', 'ara.eng', 'ces.eng', 'chi.eng', 'cze.eng', 'dan.eng', 'dut.eng', 'ell.eng', 'esl.eng', 'esp.eng', 'fin.eng', 'fra.eng', 'fre.eng',
'frn.eng', 'gai.eng', 'ger.eng', 'gle.eng', 'gre.eng', 'gtm.eng', 'heb.eng', 'hin.eng', 'hun.eng', 'ind.eng', 'iri.eng', 'ita.eng', 'jap.eng', 'jpn.eng',
'kor.eng', 'lat.eng', 'lebb.eng', 'lit.eng', 'nor.eng', 'pol.eng', 'por.eng', 'rus.eng', 'som.eng', 'spa.eng', 'sve.eng', 'swe.eng', 'tha.eng', 'tur.eng',
'uae.eng', 'ukr.eng', 'vie.eng', 'zho.eng', 'dual.audio', 'multi')
EXTRAS = ('sample', 'extra', 'extras', 'deleted', 'unused', 'footage', 'inside', 'blooper', 'bloopers', 'making.of', 'feature', 'featurette', 'behind.the.scenes', 'trailer')
UNWANTED_TAGS = (
'tamilrockers.com', 'www.tamilrockers.com', 'www.tamilrockers.ws', 'www.tamilrockers.pl', 'www-tamilrockers-cl', 'www.tamilrockers.cl', 'www.tamilrockers.li',
'www.tamilrockerrs.pl', 'www.tamilmv.bid', 'www.tamilmv.biz', 'www.1tamilmv.org', 'gktorrent-bz', 'gktorrent-com', 'www.torrenting.com', 'www.torrenting.org',
'www-torrenting-com', 'www-torrenting-org', 'katmoviehd.pw', 'katmoviehd-pw', 'www.torrent9.nz', 'www-torrent9-uno', 'torrent9-cz', 'torrent9.cz',
'agusiq-torrents-pl', 'oxtorrent-bz', 'oxtorrent-com', 'oxtorrent.com', 'oxtorrent-sh', 'oxtorrent-vc', 'www.movcr.tv', 'movcr-com', 'www.movcr.to', '(imax)',
'imax', 'xtorrenty.org', 'nastoletni.wilkoak', 'www.scenetime.com', 'kst-vn', 'www.movierulz.vc', 'www-movierulz-ht', 'www.2movierulz.ac', 'www.2movierulz.ms',
'www.3movierulz.com', 'www.3movierulz.tv', 'www.3movierulz.ws', 'www.3movierulz.ms', 'www.7movierulz.pw', 'www.8movierulz.ws', 'mkvcinemas.live', 'www.bludv.tv',
'ramin.djawadi', 'extramovies.casa', 'extramovies.wiki', '13+', '18+', 'taht.oyunlar', 'crazy4tv.com', 'karibu', '989pa.com', 'best-torrents-net', '1-3-3-8.com',
'ssrmovies.club', 'va:', 'zgxybbs-fdns-uk', 'www.tamilblasters.mx', 'www.1tamilmv.work', 'www.xbay.me', 'crazy4tv-com', '(es)')
audio_filter_choices = (
('DOLBY DIGITAL', 'DD'), ('DOLBY DIGITAL PLUS', 'DD+'), ('DOLBY DIGITAL EX', 'DD-EX'), ('DOLBY ATMOS', 'ATMOS'), ('DOLBY TRUEHD', 'TRUEHD'), 
('DTS', 'DTS'), ('DTS-HD MASTER AUDIO', 'DTS-HD MA'), ('DTS-X', 'DTS-X'), ('DTS-HD', 'DTS-HD'), ('AAC', 'AAC'), ('OPUS', 'OPUS'), ('MP3', 'MP3'),
('8CH AUDIO', '8CH'), ('7CH AUDIO', '7CH'), ('6CH AUDIO', '6CH'), ('2CH AUDIO', '2CH'))
source_filters = (
('PACK', 'PACK'), ('DOLBY VISION', '[B]D/VISION[/B]'), ('HIGH DYNAMIC RANGE (HDR)', '[B]HDR[/B]'), ('IMAX', 'IMAX'), ('HYBRID', '[B]HYBRID[/B]'), ('AV1', '[B]AV1[/B]'),
('HEVC (X265)', '[B]HEVC[/B]'), ('REMUX', 'REMUX'), ('BLURAY', 'BLURAY'), ('AI ENHANCED/UPSCALED', '[B]AI ENHANCED/UPSCALED[/B]'), ('SDR', 'SDR'), ('3D', '[B]3D[/B]'),
('DOLBY ATMOS', 'ATMOS'), ('DOLBY TRUEHD', 'TRUEHD'), ('DOLBY DIGITAL EX', 'DD-EX'), ('DOLBY DIGITAL PLUS', 'DD+'), ('DOLBY DIGITAL', 'DD'), ('DTS-HD MASTER AUDIO', 'DTS-HD MA'),
('DTS-X', 'DTS-X'), ('DTS-HD', 'DTS-HD'), ('DTS', 'DTS'), ('AAC', 'AAC'), ('OPUS', 'OPUS'), ('MP3', 'MP3'), ('8CH AUDIO', '8CH'), ('7CH AUDIO', '7CH'), ('6CH AUDIO', '6CH'),
('2CH AUDIO', '2CH'), ('DVD SOURCE', 'DVD'), ('WEB SOURCE', 'WEB'), ('MULTIPLE LANGUAGES', 'MULTI-LANG'), ('SUBTITLES', 'SUBS'))

def get_aliases_titles(aliases):
	try: result = [i['title'] for i in aliases]
	except: result = []
	return result

def make_alias_dict(meta, title):
	aliases = []
	alternative_titles = meta.get('alternative_titles', [])
	original_title = meta['original_title']
	english_title = meta.get('english_title')
	country_codes = set([i.replace('GB', 'UK') for i in meta.get('country_codes', [])])
	if alternative_titles and isinstance(alternative_titles[0], dict):
		aliases = [{'title': i['title'], 'country': i['iso']} for i in alternative_titles]
	alt_strings = {a['title'] for a in aliases}
	aliases.append({'title': original_title, 'country': 'original'})
	if english_title and english_title != original_title:
		aliases.append({'title': english_title, 'country': 'en'})
	if english_title and ': ' in english_title:
		subtitle = english_title.split(': ', 1)[1]
		if subtitle and subtitle not in alt_strings and subtitle != original_title:
			aliases.append({'title': subtitle, 'country': 'en'})
	if country_codes:
		base = original_title or title
		aliases.extend([{'title': '%s %s' % (base, i), 'country': ''} for i in country_codes])
	return aliases

def alias_della_stagione(aliases, titoli, nome_stagione):
	"""Toglie gli alias che sono il titolo di UN'ALTRA parte della serie (correzione al lotto 361).

	TMDb ha fuso *Bleach: Thousand-Year Blood War* dentro *Bleach* (stagione 2 TMDb, 17 TVDB), e i suoi titoli
	sono diventati alias di Bleach: "Bleach: Thousand-Year Blood War", "Bleach Sennen Kessen-hen"... Cercando
	Bleach S1E19, le release di TYBW "S01E19" e "- 19" (numerazione propria di TYBW) passavano il controllo del
	titolo con quegli alias e dell'episodio con la coppia o l'assoluto: una trentina il 25/09.

	Il dato che li separa e' il NOME della stagione TMDb dell'episodio cercato. Se non dice niente di suo -- e'
	il titolo della serie, "Stagione 1", "Season 1", vuoto -- la stagione non ha un sottotitolo, e un alias che
	ALLUNGA il titolo ("Bleach" + "Thousand-Year Blood War") appartiene a un'altra parte: si toglie. Se il nome ha
	un sottotitolo ("Thousand Year Blood War", "The Final Season", "Wano") non si toglie niente, perche' le
	release di quella parte possono chiamarsi proprio cosi'. Nome sconosciuto (None): non si toglie niente.
	Non sono un allungamento l'anno ("Doctor Who 2005") e il paese ("The Office US"), che make_alias_dict
	aggiunge di suo.

	`titoli`: il titolo cercato e gli altri titoli principali (originale, inglese). Pura, per la prova.
	"""
	import re, unicodedata
	def _n(testo):
		try: testo = ''.join(c for c in unicodedata.normalize('NFKD', str(testo)) if unicodedata.category(c) != 'Mn')
		except: testo = str(testo or '')
		return re.sub(r'[^a-z0-9]', '', testo.lower())
	if nome_stagione is None: return aliases
	basi = set(b for b in (_n(t) for t in titoli if t) if b)
	nome = _n(nome_stagione)
	generico = not nome or nome in basi or re.match(r'^(?:season|stagione|staffel|saison|temporada|serie|series|parte?)?\d+$', nome)
	if not generico or not basi: return aliases
	def _allunga(alias):
		a = _n(alias.get('title'))
		for b in basi:
			if a.startswith(b) and len(a) > len(b):
				resto = a[len(b):]
				if re.match(r'^(?:19|20)\d{2}$', resto) or re.match(r'^[a-z]{2}$', resto): return False
				return True
		return False
	return [a for a in aliases if not _allunga(a)]

def titolo_della_stagione(titoli, nome_stagione):
	"""LOTTO 379 -- il nome della stagione TMDb come titolo in piu' per quella stagione, se dice qualcosa di suo: "Bleach:
	Thousand-Year Blood War" per Bleach S17. Senza il titolo della serie davanti glielo si mette ("The Past Arc" ->
	"Bleach The Past Arc"). Nome generico ("Season 17", "Stagione 1", il titolo della serie) o sconosciuto: None."""
	import re, unicodedata
	if not nome_stagione: return None
	def _n(testo):
		try: testo = ''.join(c for c in unicodedata.normalize('NFKD', str(testo)) if unicodedata.category(c) != 'Mn')
		except: testo = str(testo or '')
		return re.sub(r'[^a-z0-9]', '', testo.lower())
	titoli = [t for t in titoli if t]
	nome = _n(nome_stagione)
	basi = set(b for b in (_n(t) for t in titoli) if b)
	if not nome or not titoli or nome in basi or re.match(r'^(?:season|stagione|staffel|saison|temporada|serie|series|parte?|specials?|speciali)?\d*$', nome):
		return None
	if any(nome.startswith(b) for b in basi): return nome_stagione
	return '%s %s' % (titoli[0], nome_stagione)

def internal_results(provider, sources):
	set_property(int_window_prop % provider, json.dumps(sources))

def normalize(title):
	import unicodedata
	try:
		title = ''.join(c for c in unicodedata.normalize('NFKD', title) if unicodedata.category(c) != 'Mn')
		return string(title)
	except: return title

def pack_enable_check(meta, season, episode):
	try:
		status = meta['extra_info']['status']
		if status in ('Ended', 'Canceled'): return True, True
		adjust_hours, current_date = date_offset(), get_datetime()
		episodes_data = episodes_meta(season, meta)
		unaired_episodes = [adjust_premiered_date(i['premiered'], adjust_hours)[0] for i in episodes_data]
		if None in unaired_episodes or any(i > current_date for i in unaired_episodes): return False, False
		else: return True, False
	except: pass
	return False, False

def clear_scrapers_cache(silent=False):
	from caches.base_cache import clear_cache
	for item in ('internal_scrapers', 'external_scrapers'): clear_cache(item, silent=True)
	if not silent: notification('Success')

def supported_video_extensions():
	supported_video_extensions = supported_media().split('|')
	return [i for i in supported_video_extensions if not i in ('','.zip','.rar','.iso')]

# LOTTO 376: le parole dopo cui "5.1" e "7.1" sono canali audio, non stagione ed episodio
_AUDIO = ('aac', 'ac3', 'eac3', 'dts', 'dd', 'ddp', 'ma', 'truehd', 'atmos', 'flac', 'opus', 'mp3', 'pcm', 'lpcm', 'hdr', 'sdr', 'dv',
		  'audio', 'ch', 'hevc', 'avc', 'x264', 'x265', 'h264', 'h265')
_GUARDIA_AUDIO = ''.join(r'(?<!%s\.)' % t for t in _AUDIO)

def seas_ep_filter(season, episode, release_title, split=False, return_match=False, absolute=None, solo_assoluto=False, forte=False):
	# `absolute` (lotto 361): il numero assoluto TVDB, solo per le serie in numerazione TVDB. Le release
	# anime numerano cosi' ("One Piece - 1178" e' S23E23), e dentro un pacchetto della stagione il file
	# giusto non si trovava mai. Stesse forme e stesse guardie di cocoscrapers.source_utils.episodio_regex.
	str_season, str_episode = string(season), string(episode)
	season_fill, episode_fill = str_season.zfill(2), str_episode.zfill(2)
	str_ep_plus_1, str_ep_minus_1 = string(episode+1), string(episode-1)
	crudo = release_title
	release_title = re.sub(r'[^A-Za-z0-9-]+', '.', unquote(release_title).replace('\'', '')).lower()
	# LOTTO 362 -- `(?:ab)?`: gli episodi in due segmenti ("S03E04ab - The Nasty Patty - The Idiot Box", SpongeBob e
	# simili) sono l'episodio intero. Prima non si riconoscevano: l'episodio c'era nel pacchetto e la riproduzione
	# non lo trovava. "e04a" o "e04b" da soli restano fuori: sono mezzo episodio.
	# LOTTO 385 -- `v2`: la revisione di una release anime ("[Judas] Boku no Hero Academia - S07E01v2") e' l'episodio
	string1 = r'(s<<S>>[.-]?e[p]?[.-]?<<E>>(?:ab|v\d)?[.-])'
	# LOTTO 376 -- `S.E` vuole un confine a sinistra: "s01e02.(02)" non e' 2x2. Con l'episodio a una cifra (<<E1>>, "The
	# Office - 1.1 - Downsize") e' anche un formato audio: vale fuori da un elenco di canali e non dopo un codec ("ac3.5.1"
	# non e' 5x1, "[5.1, 7.1, 5.1]" non e' 1x5 ne' 5x1). "2x5", "s2.5" e "2.05" restano.
	string2 = (r'(season[.-]?<<S>>[.-]?episode[.-]?<<E>>[.-])|((?<![a-z0-9])(?:s<<S>>[x.]<<E>>|<<S>>x<<E>>|<<S>>\.<<EF>>)(?:ab)?[.-])|'
			   r'((?<![a-z0-9])(?<!\d\.)' + _GUARDIA_AUDIO + r'<<S>>\.<<E1>>[.-](?!\d))')
	string3 = r'(s<<S>>e<<E1>>[.-]?e?<<E2>>[.-])'
	string4 = r'([.-]<<S>>[.-]?<<E>>[.-])'
	string5 = r'(episode[.-]?<<E>>[.-])'
	# LOTTO 376 -- le forme "solo episodio" anche in testa al nome ("E01 A Rickle in Time", "05 Volk i Lev.mkv")
	string6 = r'((?:^|[.-])e[p]?[.-]?<<E>>[.-])'
	# LOTTO 385 -- non in un nome con la coppia stagione.episodio "N.NN": "office_02_22-1.m4v" e' S02E22, non l'episodio 2
	string7 = r'(^(?=(?:.*\.)?e?0*<<E>>\.)(?:(?!((?:s|season)[.-]?\d+[.-x]?(?:ep?|episode)[.-]?\d+)|\d+x\d+|(?<![0-9])\d{1,2}\.\d{2}(?![0-9a-z])).)*$)'
	try: _assoluto = int(absolute) if absolute else 0
	except (TypeError, ValueError): _assoluto = 0
	# `solo_assoluto` (lotto 362): solo le forme dell'assoluto, per sapere se un file numera in assoluto
	# (file_dell_episodio). Senza assoluto non ce ne sono.
	if solo_assoluto and _assoluto <= 0: return False
	string_list = []
	string_list_append = string_list.append
	string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
	string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
	string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
	string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', str_episode))
	string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', episode_fill).replace('<<EF>>', episode_fill).replace('<<E1>>', str_episode if int(episode) < 10 else episode_fill))
	string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', episode_fill).replace('<<EF>>', episode_fill).replace('<<E1>>', str_episode if int(episode) < 10 else episode_fill))
	string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', str_episode).replace('<<EF>>', episode_fill).replace('<<E1>>', str_episode if int(episode) < 10 else episode_fill))
	string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', str_episode).replace('<<EF>>', episode_fill).replace('<<E1>>', str_episode if int(episode) < 10 else episode_fill))
	# LOTTO 385 -- "1x001": NxE con gli zeri davanti ("Dragon Ball 1x001 Goku Conosce Bulma")
	string_list_append(r'((?<![a-z0-9])0*%sx0*%s(?:v\d)?[.-])' % (str_season, str_episode))
	string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', str_ep_minus_1.zfill(2)).replace('<<E2>>', episode_fill))
	string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', episode_fill).replace('<<E2>>', str_ep_plus_1.zfill(2)))
	if _assoluto <= 0:
		# LOTTO 362 -- la forma compatta ("406" = S4E06) solo senza assoluto. Con l'assoluto un numero di tre o
		# quattro cifre E' un assoluto: per Naruto Shippuden S4E6 (assoluto 77) prendeva "Naruto Shippuden - 406",
		# per One Piece S8E8 (138) "One Piece - 808", e "0406" era S04E06.
		string_list_append(string4.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
		string_list_append(string4.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
		# Lotto 362 (prova del 25/09): la sigla scene incollata, "bb204-clue.mkv" = Breaking Bad S02E04. Almeno due
		# lettere davanti, cosi' "x264" non e' S2E64.
		string_list_append(r'((?:^|[.-])[a-z]{2,5}%s%s[.-])' % (str_season, episode_fill))
	# lotto 396: la parola della stagione col numero, poi l'episodio ("GRIMM.Saison1.E06", "Season.1.E06", "Stagione 2 Ep 04"); non
	# un intervallo ("Season.1.E06-E10")
	string_list_append(r'((?<![a-z0-9])(?:season|saison|stagione|temporada)\.?0*%s\.(?:ep?|episode|episodio)\.?0*%s(?![0-9])(?!\.?[-~]\.?e?\d))' % (str_season, str_episode))
	# LOTTO 386 -- la forma rovesciata "E05 S03" ("The Sopranos E05 S03 2001 BDRip") dice anche la stagione
	string_list_append(r'((?<![a-z0-9])e0*%s[.-]?s0*%s(?![0-9]))' % (str_episode, str_season))
	# LOTTO 387 -- "S1 - 03", "S2 - E04": la stagione, un trattino, l'episodio (lo stile di SubsPlease e di quasi tutti i
	# gruppi anime). Prima era solo una forma debole ("- 03"), e nel ripescaggio non bastava. Non un intervallo ("S1 - 03-05")
	# LOTTO 388: la fine di un intervallo e' un numero che non continua con una lettera ("- 01 - (1080p ...)" non e' 01-1080)
	# lotto 391: anche "Season 2 - 08" e "2nd Season - 08" (Vinland Saga, Fruits Basket 1st Season)
	string_list_append(r'((?<![a-z0-9])(?:s0*%s|season\.?0*%s|%s(?:st|nd|rd|th)\.season)\.?-\.?(?:ep?\.?)?0*%s(?:v\d)?(?![0-9])(?!\.?[-~]\.?\d+(?![a-z0-9])))'
					   % (str_season, str_season, str_season, str_episode))
	if not forte:
		# `forte` (lotto 366): solo le forme che dicono anche la STAGIONE, piu' quelle dell'assoluto. Le forme "solo
		# episodio" ("Episode 05", "EP05", "- 05") non bastano a ribaltare un "no" del nome: in un pacchetto della
		# terza stagione "Hajime no Ippo Rising - 05" passava per S2E5 (test del 25/09).
		string_list_append(string5.replace('<<E>>', str_episode))
		string_list_append(string6.replace('<<E>>', episode_fill))
		# LOTTO 387 -- "EP 5" a una cifra senza zero ("DEATH NOTE EP 5 - Tactics"); solo con "ep": "E.5.1" e' audio
		if int(episode) < 10: string_list_append(r'((?:^|[.-])ep[.-]?%s[.-])' % str_episode)
		string_list_append(string7.replace('<<E>>', episode_fill))
	if solo_assoluto:
		string_list = []
		string_list_append = string_list.append
	# lotto 391: un nome che dichiara un'ALTRA stagione ("Fruits Basket 2nd Season - 08") numera per stagione: le forme
	# dell'assoluto valgono solo dove _assoluto_credibile le ammette, come nella scelta del file (file_dell_episodio)
	if _assoluto > 0 and not solo_assoluto and not _assoluto_credibile(crudo, release_title, season, episode, _assoluto): _assoluto = 0
	if _assoluto > 0:
		# Il titolo qui e' gia' normalizzato: minuscolo, ogni separatore diventato '.', i trattini tenuti.
		# "one.piece.-.1178..1080p" si prende; "1156-1180" no (intervallo: e' preceduto o seguito da '-');
		# "h.264"/"x.264" no (codec); "1080p" no (seguito da una lettera); sotto il 10 serve lo zero ("02").
		_num = ('0*%d' if _assoluto >= 10 else '0+%d') % _assoluto
		# Con la stagione davanti, solo la 1 o quella cercata: in un pacchetto completo di Bleach l'assoluto 19
		# (S1E19) non deve prendere il file "Bleach.S17E19".
		string_list_append(r'(s0*(?:1|%d)[.-]?e%s[.-])' % (int(season), _num))
		# Lotto 362 (prova del 25/09): la guardia contro "h.264"/"x.264" vale solo per il numero NUDO. Messa davanti
		# anche a "e158" scartava "Bleach.E158": "bleach" finisce con la h.
		# LOTTO 376: anche in testa al nome ("42 - My Hero.mkv"), e "e030" seguito da un trattino ("Dragon.Ball.E030-Polish")
		# lotto 388: "Banana Fish - 01 - (1080p ...)": la fine di un intervallo e' un numero che non continua con una lettera
		string_list_append(r'((?:^|(?<![hx])(?<!\d-)(?<!\d\.-)\.)%s(?:v\d)?\.(?!-\.?\d+(?![a-z0-9])))' % _num)
		# lotto 389: anche col trattino, "EP-05" (Scam 1992)
		string_list_append(r'((?:^|\.)(?:ep?|episode)[.-]?%s(?:v\d)?(?:\.(?!-\.?\d+(?![a-z0-9]))|-(?![\d.])))' % _num)
		# Il file che si chiama SOLO col numero ("58.mp4", "EP58.mkv"): il pacchetto italiano di Fullmetal Alchemist
		# Brotherhood "S01e01-63" ha 01.mp4 ... 63.mp4, e senza questa forma la riproduzione non trovava mai il file.
		# Solo con l'assoluto: in una serie normale "01.mp4" in un pacchetto di piu' stagioni sarebbe ambiguo.
		string_list_append(r'(^(?:ep?\.?)?%s(?:v\d)?\.[a-z0-9]{2,4}$)' % _num)
	final_string = '|'.join(string_list)
	reg_pattern = re.compile(final_string)
	if split: return release_title.split(re.search(reg_pattern, release_title).group(), 1)[1]
	if return_match: return re.search(reg_pattern, release_title).group()
	return bool(re.search(reg_pattern, release_title))

# LOTTO 371 -- il contesto del numero (SORGENTI.md). Un numero con un'etichetta davanti non e' un episodio ("Dragon Ball
# Movie 04" passava per la 1x4 di Dragon Ball), e nemmeno un menu di disco.
# LOTTO 382: anche separata da " - " ("Dragon Ball Special - 01")
_ETICHETTE = re.compile(r'(?:^|[.\-])(?:movie|movies|film|ova|oav|special|specials|sp|vol|volume|reel)[.\-]{0,3}\d+(?=[.\-]|$)')
_MENU = re.compile(r'(?:^|[.\-])menu(?:[.\-]|$)')
# La stagione dichiarata nel NOME del file (sul nome gia' normalizzato: minuscolo, separatori -> '.'): "s03e13",
# "s3.-.07", "3x04", "[3.08]" (diventato ".3.08."), "season.3". Lotto 385: "[5.01.02]" (due episodi) dichiara la 5, non la 1.
_STAGIONE_NEL_NOME = (re.compile(r'(?<![a-z0-9])s(\d{1,3})[.\-]?e[p]?[.\-]?\d'), re.compile(r'(?<![a-z0-9])(\d{1,2})x\d{2,4}(?![0-9])'),
					  re.compile(r'(?:^|\.)(?<![0-9]\.)(\d{1,2})\.\d{2}(?:\.\d{2})*(?=\.[a-z]|$)'), re.compile(r'(?<![a-z0-9])s(\d{1,2})(?![a-z0-9])'),
					  re.compile(r'(?<![a-z0-9])(?:season|stagione|saison|temporada)[.\-]?(\d{1,2})(?![0-9])'),
					  # lotto 391: l'ordinale ("Fruits Basket 2nd Season - 08")
					  re.compile(r'(?<![a-z0-9])(\d{1,2})(?:st|nd|rd|th)\.season'))
# ...e in una CARTELLA ("Season 01 - Saiyan Saga", "S02", "Stagione 2"), con gli intervalli ("S01-S09", "Season 1 to 9").
_STAGIONE_IN_CARTELLA = re.compile(r'(?:^|[^a-z0-9])(?:s|season|seasons|stagione|stagioni|saison|temporada)[ ._\-]?0*(\d{1,2})'
								   r'(?:[ ._\-]*(?:-|to|a|~|&|\+)[ ._\-]*(?:s|season)?[ ._\-]?0*(\d{1,2}))?(?![0-9e])', re.I)

def _normalizza_nome(nome):
	return re.sub(r'[^A-Za-z0-9-]+', '.', unquote(nome or '').replace('\'', '')).lower()

def stagioni_dichiarate(nome_normalizzato, percorso=''):
	"""Lotto 371. Le stagioni che il nome del file dichiara; se non ne dichiara, quelle della cartella piu' vicina che
	le dichiara (un intervallo vale come piu' stagioni). Insieme vuoto: nessuna dichiarazione."""
	for r in _STAGIONE_NEL_NOME:
		m = r.findall(nome_normalizzato)
		if m: return set(int(x) for x in m)
	for cartella in reversed((percorso or '').replace('\\', '/').split('/')[:-1]):
		m = _STAGIONE_IN_CARTELLA.findall(cartella)
		if not m: continue
		fuori = set()
		for a, b in m:
			a = int(a); b = int(b) if b else a
			fuori.update(range(a, b + 1) if a <= b and b - a < 40 else [a])
		return fuori
	return set()

_DISCO = re.compile(r'/(?:bdmv|video_ts)/')
_COPPIA = re.compile(r'(?<![a-z0-9])s\d{1,3}[.\-]?e[p]?[.\-]?(\d{1,4})(?![0-9])')

def _assoluto_credibile(crudo, grezzo, season, episode, ass):
	"""LOTTO 376 -- un nome che dichiara un'ALTRA stagione (non la nostra, non la 1) numera per stagione: l'assoluto vale
	solo come campo a se', fra parentesi ("S05E01 (186)"), subito dopo il SxxEyy ("S05E01 186") o come numero del SxxEyy
	scritto con tre cifre ("S02 E036"). Nella passata del 26/09 "S11E01 - 206 - ... 110 Years Ago" passava per l'assoluto 110
	di Bleach, "S04 E05" e "S2 Ep 05" per l'assoluto 5. Chi corrisponde nella forma della nostra stagione passa sempre."""
	# solo le dichiarazioni esplicite (s03, 3x04, season 3): "episode.44.17.times" non dichiara la stagione 44
	dichiarate = set(int(x) for i, r in enumerate(_STAGIONE_NEL_NOME) if i != 2 for x in r.findall(grezzo))
	if not dichiarate or 1 in dichiarate or int(season) in dichiarate: return True
	if seas_ep_filter(season, episode, grezzo, forte=True): return True
	if any(len(e) >= 3 and int(e) == ass for e in _COPPIA.findall(grezzo)): return True
	# lotto 386: fra parentesi solo accanto a una coppia ("S05E01 (186)"): "[Boku no Hero Academia S7][05]" non e' l'assoluto 5
	if _COPPIA.search(grezzo) and re.search(r'[(\[]\s*0*%d\s*[)\]]' % ass, crudo or ''): return True
	return bool(re.search(r'(?<![a-z0-9])s\d{1,3}[.\-]?e[p]?[.\-]?\d{1,4}[.\-]+0*%d(?![0-9])' % ass, grezzo))

def file_dell_episodio(elementi, season, episode, absolute=None, nome=lambda x: x, percorso=None):
	"""I file di un torrent che sono l'episodio cercato, nell'ordine in cui arrivano (lotto 362).

	E' seas_ep_filter su ogni file, piu' una regola che il singolo nome non puo' sapere: SE qualche file
	corrisponde nella forma ASSOLUTA, il torrent numera in assoluto e valgono solo quelli. In un pacchetto
	di Naruto Shippuden (001-500), cercando S4E6 = assoluto 77, "- 006" passava per l'episodio 6 della
	stagione, e il resolver prendeva il primo nell'ordine del debrid: partiva l'episodio 6. Tutti i
	resolver e pack_cache passano di qui, cosi' elenco e riproduzione scelgono allo stesso modo.

	LOTTO 371 -- il numero si legge nel suo contesto. Una forma "solo episodio" ("E06", "Episode 11", "- 05") vale solo
	se la stagione dichiarata (nel nome, se no nella cartella: `percorso`) e' quella cercata: nella prova del 26/09 Il
	Trono di Spade 1x6 sceglieva "S08 E06", I Soprano 1x11 "Season 3 Episode 11", Dragon Ball Z 8x6 "- 006" dalla
	cartella "S01-35". Senza una stagione sola dichiarata, con l'assoluto il numero nudo e' l'assoluto (vale solo se
	coincide). I file con un'etichetta ("Movie 04", "OVA 3") e i menu non sono episodi, tranne per la stagione 0.
	"""
	try: stagione, ep, ass = int(season), int(episode), int(absolute or 0)
	except (TypeError, ValueError): stagione, ep, ass = season, episode, 0
	trovati, forme_assolute = [], []
	for i in elementi:
		grezzo = _normalizza_nome(nome(i))
		if stagione != 0 and (_ETICHETTE.search(grezzo) or _MENU.search(grezzo)): continue
		# LOTTO 376: in un disco ("BDMV/STREAM/00005.m2ts", "VIDEO_TS") il numero e' quello del flusso, non dell'episodio
		if percorso and _DISCO.search('/' + (percorso(i) or '').replace('\\', '/').lower()): continue
		if seas_ep_filter(season, episode, grezzo, absolute=absolute, forte=True):
			if ass and not _assoluto_credibile(nome(i), grezzo, season, episode, ass): continue
			trovati.append(i)
			continue
		if not seas_ep_filter(season, episode, grezzo, absolute=absolute): continue
		# qui solo le forme "solo episodio": decide la stagione dichiarata
		dichiarate = stagioni_dichiarate(grezzo, percorso(i) if percorso else '')
		if dichiarate == set([stagione]): trovati.append(i)
		elif dichiarate:
			if stagione in dichiarate and not ass: trovati.append(i)
		# LOTTO 376: senza stagione dichiarata il numero in testa al nome non basta ("The Sopranos/05 Another Toothpick" e'
		# il quinto di QUALE stagione?): la 'x' davanti toglie le forme ancorate all'inizio
		elif (not ass or ass == ep) and seas_ep_filter(season, episode, 'x' + grezzo, absolute=absolute): trovati.append(i)
	if absolute and len(trovati) > 1:
		assoluti = [i for i in trovati if seas_ep_filter(season, episode, _normalizza_nome(nome(i)), absolute=absolute, solo_assoluto=True)]
		if assoluti: return assoluti
	return trovati

def find_season_in_release_title(release_title):
	release_title = re.sub(r'[^A-Za-z0-9-]+', '.', unquote(release_title).replace('\'', '')).lower()
	match = None
	regex_list = [r's(\d+)', r's\.(\d+)', r'(\d+)x', r'(\d+)\.x', r'season(\d+)', r'season\.(\d+)']
	for item in regex_list:
		try:
			match = re.search(item, release_title)
			if match:
				match = int(string(match.group(1)).lstrip('0'))
				break
		except: pass
	return match

def check_title(title, release_title, aliases, year, season, episode):
	try:
		all_titles = [title]
		if aliases: all_titles += aliases
		cleaned_titles = []
		cleaned_titles_append = cleaned_titles.append
		year = string(year)
		for i in all_titles:
			# Stessa pulizia del titolo della fonte, che gli scraper passano gia' da normalize(): senza,
			# 'pokémon' non corrisponde mai a 'pokemon'. Un titolo che resta vuoto (alias tutto in
			# caratteri non latini) si scarta: la stringa vuota e' contenuta in qualunque titolo.
			cleaned = strip_non_ascii_and_unprintable(normalize(i)).lower().replace('\'', '').replace(':', '').replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(' ', '.').replace(year, '')
			if cleaned: cleaned_titles_append(cleaned)
		if not cleaned_titles: return True
		release_title = strip_non_ascii_and_unprintable(release_title).lstrip('/ ').replace(' ', '.').replace(':', '.').lower()
		releasetitle_startswith = release_title.startswith
		for i in UNWANTED_TAGS:
			if releasetitle_startswith(i):
				i_startswith = i.startswith
				pattern = r'\%s' % i if i_startswith('[') or i_startswith('+') else r'%s' % i
				release_title = re.sub(r'^%s' % pattern, '', release_title, 1, re.I)
		release_title = release_title.lstrip('.-:/')
		release_title = re.sub(r'^\[.*?]', '', release_title, 1, re.I)
		release_title = release_title.lstrip('.-[](){}:/')
		if season:
			if season == 'pack': hdlr = ''
			else:
				try: hdlr = seas_ep_filter(season, episode, release_title, return_match=True)
				except: return False
		else: hdlr = year
		if hdlr:
			release_title = release_title.split(hdlr.lower())[0]
			release_title = release_title.replace(year, '').replace('(', '').replace(')', '').replace('&', 'and').rstrip('.-').rstrip('.').rstrip('-').replace(':', '')
			if not any(release_title == i for i in cleaned_titles): return False
		else:
			release_title = release_title.replace(year, '').replace('(', '').replace(')', '').replace('&', 'and').rstrip('.-').rstrip('.').rstrip('-').replace(':', '')
			if not any(i in release_title for i in cleaned_titles): return False
		return True
	except: return True

def strip_non_ascii_and_unprintable(text):
	try:
		result = ''.join(char for char in text if char in printable)
		return result.encode('ascii', errors='ignore').decode('ascii', errors='ignore')
	except: pass
	return text

def release_info_format(release_title):
	try:
		release_title = url_strip(release_title)
		release_title = release_title.lower().replace("'", "").lstrip('.').rstrip('.')
		title = '.%s.' % re.sub(r'[^a-z0-9-~]+', '.', release_title).replace('.-.', '.').replace('-.', '.').replace('.-', '.').replace('--', '.')
		return title
	except:
		return release_title.lower()

def clean_title(title):
	try:
		if not title: return
		title = title.lower()
		title = re.sub(r'&#(\d+);', '', title)
		title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
		title = title.replace('&quot;', '\"').replace('&amp;', '&')
		title = re.sub(r'\n|([\[({].+?[})\]])|([:;–\-"\',!_.?~$@])|\s', '', title)
	except: pass
	return title

def url_strip(url):
	try:
		url = unquote_plus(url)
		if 'magnet:' in url: url = url.split('&dn=')[1]
		url = url.lower().replace("'", "").lstrip('.').rstrip('.')
		title = re.sub(r'[^a-z0-9]+', ' ', url)
		if 'http' in title: return None
		if title == '': return None
		return title
	except: return None

def get_file_info(name_info=None, url=None, default_quality='SD'):
	title = None
	if name_info: title = name_info
	elif url: title = url_strip(url)
	if not title: return 'SD', ''
	quality = get_release_quality(title) or default_quality
	info = get_info(title)
	return quality, info

def get_release_quality(release_info):
	if any(i in release_info for i in SCR): return 'SCR'
	if any(i in release_info for i in CAM): return 'CAM'
	if any(i in release_info for i in TELE): return 'TELE'
	if any(i in release_info for i in RES_720): return '720p'
	if any(i in release_info for i in RES_1080): return '1080p'
	if any(i in release_info for i in RES_4K): return '4K'
	return None
	
def get_info(title):
	# thanks 123Venom and gaiaaaiaai, whom I knicked most of this code from. :)
	info = []
	info_append = info.append
	if any(i in title for i in VIDEO_3D):  info_append('[B]3D[/B]')
	if '.sdr' in title: info_append('SDR')
	elif any(i in title for i in DOLBY_VISION): info_append('[B]D/VISION[/B]')
	elif any(i in title for i in HDR): info_append('[B]HDR[/B]')
	elif all(i in title for i in ('2160p', 'remux')): info_append('[B]HDR[/B]')
	if '[B]D/VISION[/B]' in info:
		if any(i in title for i in HDR_TRUE) or 'hybrid' in title: info_append('[B]HDR[/B]')
		if '[B]HDR[/B]' in info: info_append('[B]HYBRID[/B]')
	if any(i in title for i in CODEC_H264): info_append('AVC')
	elif AV1_RE.search(title): info_append('[B]AV1[/B]')
	elif any(i in title for i in CODEC_H265): info_append('[B]HEVC[/B]')
	elif any(i in info for i in ('[B]HDR[/B]', '[B]D/VISION[/B]')): info_append('[B]HEVC[/B]')
	if any(i in title for i in IMAX): info_append('IMAX')
	elif any(i in title for i in ENHANCED_UPSCALED): info_append('[B]AI ENHANCED/UPSCALED[/B]')
	if '.atvp' in title: info_append('APPLETV+')
	elif any(i in title for i in CODEC_XVID): info_append('XVID')
	elif any(i in title for i in CODEC_DIVX): info_append('DIVX')
	if any(i in title for i in REMUX): info_append('REMUX')
	if any(i in title for i in BLURAY): info_append('BLURAY')
	elif any(i in title for i in DVD): info_append('DVD')
	elif any(i in title for i in WEB): info_append('WEB')
	elif 'hdtv' in title: info_append('HDTV')
	elif 'pdtv' in title: info_append('PDTV')
	elif any(i in title for i in HDRIP): info_append('HDRIP')
	if 'atmos' in title: info_append('ATMOS')
	if any(i in title for i in DOLBY_TRUEHD): info_append('TRUEHD')
	if any(i in title for i in DOLBY_DIGITALPLUS): info_append('DD+')
	elif any(i in title for i in DOLBY_DIGITALEX): info_append('DD-EX')
	elif any(i in title for i in DOLBYDIGITAL): info_append('DD')
	if 'aac' in title: info_append('AAC')
	elif 'mp3' in title: info_append('MP3')
	elif '.flac.' in title: info_append('FLAC')
	elif 'opus' in title and not title.endswith('opus.'): info_append('OPUS')
	if any(i in title for i in DTSX): info_append('DTS-X')
	elif any(i in title for i in DTS_HDMA): info_append('DTS-HD MA')
	elif any(i in title for i in DTS_HD): info_append('DTS-HD')
	elif '.dts' in title: info_append('DTS')
	if any(i in title for i in AUDIO_8CH): info_append('8CH')
	elif any(i in title for i in AUDIO_7CH): info_append('7CH')
	elif any(i in title for i in AUDIO_6CH): info_append('6CH')
	elif any(i in title for i in AUDIO_2CH): info_append('2CH')
	if '.wmv' in title: info_append('WMV')
	elif any(i in title for i in CODEC_MPEG): info_append('MPEG')
	elif '.avi' in title: info_append('AVI')
	elif any(i in title for i in CODEC_MKV): info_append('MKV')
	if any(i in title for i in MULTI_LANG): info_append('MULTI-LANG')
	if any(i in title for i in ADS): info_append('ADS')
	if any(i in title for i in SUBS): info_append('SUBS')
	return ' | '.join(filter(None, info))

def get_cache_expiry(media_type, meta, season):
	try:
		current_date = get_datetime()
		if media_type == 'movie':
			premiered = jsondate_to_datetime(meta['premiered'], '%Y-%m-%d', remove_time=True)
			difference = subtract_dates(current_date, premiered)
			if difference == 0: single_expiry = expiry_3hrs
			elif difference <= 7: single_expiry = expiry_1day
			elif difference <= 14: single_expiry = expiry_2days
			elif difference <= 21: single_expiry = expiry_3days
			elif difference <= 30: single_expiry = expiry_4days
			elif difference <= 60: single_expiry = expiry_7days
			else: single_expiry = expiry_14days
			season_expiry, show_expiry = 0, 0
		else:
			recently_ended = False
			extra_info = meta['extra_info']
			ended = extra_info['status'] in ('Ended', 'Canceled')
			premiered = adjust_premiered_date(meta['premiered'], date_offset())[0]
			difference = subtract_dates(current_date, premiered)
			last_episode_to_air = jsondate_to_datetime(extra_info['last_episode_to_air']['air_date'], '%Y-%m-%d', remove_time=True)
			last_ep_difference = subtract_dates(current_date, last_episode_to_air)
			if ended and last_ep_difference <= 14: recently_ended = True
			if not ended or recently_ended:
				if difference == 0: single_expiry = expiry_3hrs
				elif difference <= 3: single_expiry = expiry_1day
				elif difference <= 7: single_expiry = expiry_3days
				else: single_expiry = expiry_7days
				if meta['total_seasons'] == season:
					if last_ep_difference <= 7: season_expiry = expiry_3days
					else: season_expiry = expiry_10days
				else: season_expiry = expiry_30days
				show_expiry = expiry_10days
			else: single_expiry, season_expiry, show_expiry = expiry_10days, expiry_30days, expiry_30days
	except: single_expiry, season_expiry, show_expiry = expiry_3days, expiry_3days, expiry_10days
	return single_expiry, season_expiry, show_expiry
