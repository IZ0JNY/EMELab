# Metodo scientifico di EMELab

## 1. Un modello della stazione, stimato da tutte le misure
Parametri: efficienza d'apertura η, errore RMS della superficie ε, spillover e frazione verso terra, perdite feed→LNA,
temperatura di rumore del ricevitore (NF), HPBW per banda, termini di puntamento. Ogni misura è un'equazione del modello
(Y Sole, Y Luna, carico caldo/cielo, terra/cielo, cielo a più elevazioni, scansioni, eco). Stima con minimi quadrati pesati,
incertezze per propagazione e Monte Carlo; i valori attesi da FeedLab e dalla teoria sono le «informazioni a priori».

## 2. Autoapprendimento
- Aggiornamento bayesiano dei parametri a ogni misura (a priori = progetto FeedLab).
- Fattori appresi da eco e QSO: riflettività efficace della Luna con il proprio fascio (BWF reale) per banda, soglie dei
  decoder, fattori G della scansione del Sole.
- Previsione della riuscita di un QSO (regressione sulle condizioni registrate) usata dal pianificatore.
- Trasparenza: di quanto la misura sposta la teoria e con quale incertezza.

## 3. Puntamento
Modello come nei radiotelescopi: zero AZ/EL, non perpendicolarità, inclinazione della base, flessione gravitazionale,
eccentricità, rifrazione radio. Misure: croci e 5 punti su Sole e Luna con adattamento 2D disco ⊗ fascio. Obiettivo:
residuo < HPBW/10 (< 0.05 dB).

## 4. Simulazione
Lobo del feed da FeedLab (simulatore veloce o openEMS, portato dal file di progetto); ottica fisica della parabola per
lobi secondari e spillover verso terra, tarata con le misure di terra/cielo.

## 5. Validità dei modelli
Ogni modello dichiara il campo di validità ed è verificato da test (es. approssimazione di Baars della larghezza della
scansione: −1.6 % a θ_fascio = θ_Sole, −20 % a 0.3·θ_Sole → si usa l'adattamento 2D completo).
