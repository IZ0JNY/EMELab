# EMELab e gli altri programmi della stazione

## WSJT-X (fatto, EMELab 0.1.1)

Protocollo UDP «network server» di WSJT-X (Network/NetworkMessage.hpp, K1JT, G4WJS e WSJT Development Group).
In WSJT-X: *Settings → Reporting → UDP Server* = `127.0.0.1`, porta `2237`, *Accept UDP requests* spuntato.
Con JTAlert o GridTracker in contemporanea: indirizzo multicast (es. `224.0.0.1`) in WSJT-X e lo stesso in EMELab.

EMELab riceve:
- **Status**: frequenza, modo e sottomodo, DX call e locator, TX/RX;
- **Decode**: ogni decodifica (ora, SNR, DT, DF, messaggio), salvata nel database con banda e frequenza: serve alle
  statistiche e all'autoapprendimento (SNR reale contro SNR previsto);
- **QSOLogged**: quando confermi «Log QSO» in WSJT-X il QSO entra nel Log QSO di EMELab con tutte le condizioni di quel
  momento (Luna ai due capi, distanze, Doppler, spread, atmosfera, meteo).

### QSO nel log da soli: wsjtx_log.adi e UDP

Due strade indipendenti, anche insieme (scheda 📻 WSJT-X):
- **wsjtx_log.adi** (consigliata): a ogni OK in «Log QSO» WSJT-X aggiunge un record ADIF al suo file di log
  (cartella di *File → Open log directory*: `%LOCALAPPDATA%\WSJT-X` su Windows, `~/.local/share/WSJT-X` su Linux,
  `~/Library/Application Support/WSJT-X` su macOS). EMELab segue il file ogni 3 s dal punto letto l'ultima volta
  (salvato nelle impostazioni): nessuna porta UDP, nessun conflitto con JTAlert, GridTracker o altri logger.
- **UDP QSOLogged**, come sopra.

Filtro (attivo di base): banda da 10 GHz in su e Prop Mode EME. Prop Mode = EME entra sempre, un Prop Mode diverso
(TR, RS, …) mai; senza Prop Mode (WSJT-X lo lascia vuoto finché non lo scegli in «Log QSO») entra se il modo è Q65,
JT65, JT4 o QRA64 o il corrispondente è una stazione EME nota, a meno di spuntare «Solo con Prop Mode = EME».
Doppioni: stesso nominativo e banda entro ±10 minuti = stesso QSO, che arrivi da UDP, dal file o da un ADIF importato.
Q65 scritto da WSJT-X come MODE=MFSK/SUBMODE=Q65 torna «Q65», con la lettera del sottomodo presa dallo Status UDP.

### Controllo delle impostazioni di WSJT-X

A ogni Status EMELab controlla (`emelab/wsjtx_check.py`) e mostra un avviso in cima a ogni pagina:
- **modo, sottomodo, T/R** rispetto alla banda (Q65-60D a 10 GHz, Q65-60E da 24 GHz in su, o la scelta per banda):
  **corretti da soli** con Configure (spunta disattivabile), mai in trasmissione, al massimo 3 tentativi; se WSJT-X
  li ignora, avviso «Accept UDP requests»;
- **banda** fuori da quelle ≥10 GHz, **nominativo** e **locator** diversi dalla stazione EMELab, **TX watchdog**: solo
  avviso, il protocollo UDP non li può cambiare.
Doppler tracking, Prop Mode, audio e CAT non sono nello Status: EMELab non li vede.

EMELab invia:
- **HighlightCallsign**: colora i nominativi nella finestra Band Activity (verde = da collegare, grigio = già collegato);
- **Configure**: imposta Q65 e il sottomodo consigliato (60D, 60E, 120E…) in base al mutual spread con il DX;
- **Replay**: chiede a WSJT-X di rimandare le decodifiche già in finestra.

Il Doppler resta a WSJT-X (finestra Astro, CAT): EMELab non tocca il CAT per non litigare con lui.

## SDR Console (studio)

SDR Console V3 (Simon Brown G4ELI) non ha un'interfaccia di programmazione pubblica come quella di WSJT-X. Le strade
possibili, dalla più utile alla meno:

1. **Misure di rumore dall'audio** (idea di SimpleCalc di Carsten OZ9AAR): EMELab legge l'audio di SDR Console da un
   cavo audio virtuale (VB-Cable o simili), filtra una banda stretta e misura la potenza RMS nel tempo. Con questo:
   - fattore Y automatico su Sole, Luna, cielo freddo e terra, salvato nel diario misure con l'ora esatta;
   - scansioni del Sole a croce o a deriva registrate direttamente, con l'adattamento disco ⊗ fascio già in EMELab;
   - grafico del rumore nel tempo (deriva del ricevitore, interferenze, nuvole e pioggia a 24/47 GHz).
   Serve la libreria `sounddevice` (PortAudio) nel pacchetto Windows. Funziona con qualunque ricevitore, non solo SDR
   Console (anche IC-9700).
2. **Registrazioni I/Q**: SDR Console registra l'I/Q in file WAV. EMELab può aprirli dopo la sessione e misurare lo
   spettro dell'eco o del segnale: SNR, allargamento reale (libration spread) e Doppler, da confrontare con quelli
   calcolati. Nessun collegamento in tempo reale: basta il file.
3. **CAT** (porta seriale virtuale, emulazione Kenwood TS-2000 tramite com0com): EMELab potrebbe leggere frequenza e
   modo. Ma il CAT di solito è già usato da WSJT-X per il Doppler, e WSJT-X manda già la frequenza a EMELab via UDP:
   per ora non serve.
4. **Inseguimento della Luna nel modulo Satelliti di SDR Console**: corregge solo il Doppler di discesa, non quello EME
   andata e ritorno (segnalato sul forum SDR-Radio per i 10 GHz): meglio lasciarlo a WSJT-X.

**Proposta:** partire dal punto 1 (misure di rumore dall'audio), che rende automatiche le misure di sole e Luna del
diario, e poi il punto 2 per l'analisi delle eco registrate.

Da chiedere a IZ0JNY: quale ricevitore usa con SDR Console a 10/24/47 GHz, se l'audio esce già su un cavo virtuale e se
registra l'I/Q durante le prove.
