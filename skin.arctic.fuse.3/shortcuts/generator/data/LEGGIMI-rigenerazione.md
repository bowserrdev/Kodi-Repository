# Se tocchi un .xmltemplate, alza `buildv`

I file qui sotto **non vengono letti da Kodi**. Sono sorgenti da cui `script.skinvariables`
genera una volta sola `1080i/script-skinvariables-generator-includes-<utente>.xml`, ed è
*quello* il file che la skin carica.

La rigenerazione avviene solo quando cambia l'impronta calcolata in
`script.skinvariables/resources/lib/shortcuts/template.py` (`update_xml`), che è fatta di:

- gli argomenti della chiamata (fra cui `lastbuildtime`, che cambia quando si modificano i
  collegamenti dalla schermata di modifica);
- il contenuto di **`shortcuts/skinvariables-generator.json`**;
- il contenuto del file **già generato**;
- il nome del profilo.

**I `.xmltemplate` non ci sono dentro.** Modificarli non invalida niente: il generatore non
riparte e il file generato resta com'è, per sempre, in silenzio.

## Cosa è successo il 24-25/08/2026

Il token della paginazione di Fen Light è passato da `fenlight.pg.ctl501.pages` a
`fenlight.pg.whome.ctl501.pages` (serviva la finestra nel nome: gli id dei contenitori
ripartono da 501 in ogni finestra). Il `.xmltemplate` è stato aggiornato.

Sul Mi Stick i widget della home erano stati spostati lo stesso giorno, quindi
`lastbuildtime` è cambiato e il file si è rigenerato: lì funzionava.

Sul Mac non è stato toccato nulla. Il file generato è rimasto quello del 14/08 e ha continuato
a leggere il nome vecchio, che nessuno scriveva più. Risultato: il servizio scriveva il token
regolarmente, la skin non ricaricava mai, la paginazione era completamente morta — senza un
errore, senza una riga di log che lo dicesse.

## La regola

Dopo ogni modifica a un file in `generator/data/`, alza `buildv` in
`shortcuts/skinvariables-generator.json`. Quel campo non è letto da nessuno: esiste solo per
entrare nell'impronta e forzare la rigenerazione su tutte le installazioni.

Dal 25/08 Fen Light se ne accorge comunque da solo: se scrive il token e in 20 secondi non
parte nessuna build, il servizio scrive nel log `WidgetPaginator: ricarica IGNORATA` con il
nome esatto della proprietà scritta. Ma è una rete di sicurezza, non un sostituto della regola.
