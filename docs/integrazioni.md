# EME Assistant e gli altri programmi della stazione

## WSJT-X (fatto, EME Assistant 0.1.1)

Protocollo UDP «network server» di WSJT-X (Network/NetworkMessage.hpp, K1JT, G4WJS e WSJT Development Group).
In WSJT-X: *Settings → Reporting → UDP Server* = `127.0.0.1`, porta `2237`, *Accept UDP requests* spuntato.
Con JTAlert o GridTracker in contemporanea: indirizzo multicast (es. `224.0.0.1`) in WSJT-X e lo stesso in EME Assistant.

EME Assistant riceve:
- **Status**: frequenza, modo e sottomodo, DX call e locator, TX/RX;
- **Decode**: ogni decodifica (ora, SNR, DT, DF, messaggio), salvata nel database con banda e frequenza: serve alle
  statistiche e all'autoapprendimento (SNR reale contro SNR previsto);
- **QSOLogged**: quando confermi «Log QSO» in WSJT-X il QSO entra nel Log QSO di EME Assistant con tutte le condizioni di quel
  momento (Luna ai due capi, distanze, Doppler, spread, atmosfera, meteo).

EME Assistant invia:
- **HighlightCallsign**: colora i nominativi nella finestra Band Activity (verde = da collegare, grigio = già collegato);
- **Configure**: imposta Q65 e il sottomodo consigliato (60D, 60E, 120E…) in base al mutual spread con il DX;
- **Replay**: chiede a WSJT-X di rimandare le decodifiche già in finestra.

Il Doppler resta a WSJT-X (finestra Astro, CAT): EME Assistant non tocca il CAT per non litigare con lui.

## SDR Console (studio)

SDR Console V3 (Simon Brown G4ELI) non ha un'interfaccia di programmazione pubblica come quella di WSJT-X. Le strade
possibili, dalla più utile alla meno:

1. **Misure di rumore dall'audio** (idea di SimpleCalc di Carsten OZ9AAR): EME Assistant legge l'audio di SDR Console da un
   cavo audio virtuale (VB-Cable o simili), filtra una banda stretta e misura la potenza RMS nel tempo. Con questo:
   - fattore Y automatico su Sole, Luna, cielo freddo e terra, salvato nel diario misure con l'ora esatta;
   - scansioni del Sole a croce o a deriva registrate direttamente, con l'adattamento disco ⊗ fascio già in EME Assistant;
   - grafico del rumore nel tempo (deriva del ricevitore, interferenze, nuvole e pioggia a 24/47 GHz).
   Serve la libreria `sounddevice` (PortAudio) nel pacchetto Windows. Funziona con qualunque ricevitore, non solo SDR
   Console (anche IC-9700).
2. **Registrazioni I/Q**: SDR Console registra l'I/Q in file WAV. EME Assistant può aprirli dopo la sessione e misurare lo
   spettro dell'eco o del segnale: SNR, allargamento reale (libration spread) e Doppler, da confrontare con quelli
   calcolati. Nessun collegamento in tempo reale: basta il file.
3. **CAT** (porta seriale virtuale, emulazione Kenwood TS-2000 tramite com0com): EME Assistant potrebbe leggere frequenza e
   modo. Ma il CAT di solito è già usato da WSJT-X per il Doppler, e WSJT-X manda già la frequenza a EME Assistant via UDP:
   per ora non serve.
4. **Inseguimento della Luna nel modulo Satelliti di SDR Console**: corregge solo il Doppler di discesa, non quello EME
   andata e ritorno (segnalato sul forum SDR-Radio per i 10 GHz): meglio lasciarlo a WSJT-X.

**Proposta:** partire dal punto 1 (misure di rumore dall'audio), che rende automatiche le misure di sole e Luna del
diario, e poi il punto 2 per l'analisi delle eco registrate.

Da chiedere a IZ0JNY: quale ricevitore usa con SDR Console a 10/24/47 GHz, se l'audio esce già su un cavo virtuale e se
registra l'I/Q durante le prove.
