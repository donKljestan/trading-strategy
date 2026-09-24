# Live Trading Setup - Preporuke i Uputstva

## ⚠️ KRITIČNA SIGURNOST

### 1. API Ključevi
- **NIKADA** ne ostavljaj API ključeve u kodu
- Kreiran je `.env.example` fajl kao template
- Kopiraj `.env.example` u `.env` i dodaj svoje ključeve
- `.env` fajl je u `.gitignore` i neće biti commitovan

```bash
# Kopiraj template
copy .env.example .env

# Otvori .env i dodaj svoje ključeve
notepad .env
```

### 2. Binance API Permisije
Za testiranje OBAVEZNO postavi:
- ✅ Enable Reading (čitanje podataka)
- ✅ Enable Spot & Margin Trading (ako tesiraš na spot)
- ✅ Enable Futures (ako testiraš na futures)
- ❌ **ISKLJUČI** Enable Withdrawals (povlačenja)
- ✅ Postavi IP Whitelist (samo tvoja IP adresa)

## 🔧 Instalacija

```bash
# Instaliraj dependencies
pip install -r requirements.txt

# Kreiraj .env fajl
copy .env.example .env

# Dodaj svoje API ključeve u .env fajl
```

## 🐛 ISPRAVKI BUGOVI

### Bug #1: Operator dodele ✅ ISPRAVLJENO
- Linija ~418: `side == "BUY"` → `side = "BUY"` (već bilo ispravno)
- Linija ~434: `side == "SELL"` → `side = "SELL"` ✅

### Bug #2: Bollinger Bands parametri ✅ ISPRAVLJENO
- `BBU_5_2.0` → `BBU_20_2.0`
- `BBL_5_2.0` → `BBL_20_2.0`

## ✨ DODATO - Sigurnosni Featuri

### 1. Risk Management
- **MAX_POSITION_SIZE_USD**: Maksimalna veličina pozicije
- **MAX_DAILY_LOSS_USD**: Dnevni limit gubitka (bot automatski prestaje da trguje)
- **MAX_OPEN_POSITIONS**: Maksimalan broj istovremenih pozicija

### 2. Error Handling
- Retry logika za API pozive (3 puta pre pada)
- Rate limit handling (automatsko čekanje)
- Timeout protection (10 sekundi)
- Validacija podataka pre otvaranja pozicija

### 3. Logging Poboljšanja
- Tracking razloga zatvaranja (StopLoss/TakeProfit)
- Dnevni PnL tracking
- Broj aktivnih pozicija

### 4. Data Validation
- Provera NULL vrednosti u podacima
- Validacija indikatora pre trgovanja
- Volume data validation

## 📊 STRATEGIJSKE SUGESTIJE

### 1. Position Sizing
**PROBLEM**: Trenutno ulaziš sa fiksnim iznosom (100 USD).

**PREPORUKA**: Implementiraj position sizing baziran na:
- ATR (volatilnost) - više ATR = manji position
- Account balance percentage (npr. 2% po trade)
- Risk-Reward ratio

```python
def calculate_position_size(account_balance, risk_percent, stop_loss_percent):
    risk_amount = account_balance * (risk_percent / 100)
    position_size = risk_amount / (stop_loss_percent / 100)
    return min(position_size, MAX_POSITION_SIZE_USD)
```

### 2. Slippage & Funding Rates
**PROBLEM**: Nemaš u obzir slippage i funding rate na futures.

**PREPORUKA**: 
- Dodaj slippage od 0.1-0.2% u kalkulaciju profita
- Prati funding rate (može biti -0.1% do +0.1% svaka 8h)
- Za live testing, dodaj ove troškove

### 3. Market Conditions Filter
**PROBLEM**: Strategija trguje u svim tržišnim uslovima.

**PREPORUKA**:
- Dodaj filter za trend (samo long u uptrend, short u downtrend)
- Pauziraj trgovanje u periodu niske volatilnosti
- Prati correlation između kriptovaluta

### 4. Backtesting vs Live
**PROBLEM**: Backtesting često daje bolje rezultate od live trgovanja.

**RAZLOZI**:
- Look-ahead bias (koristiš podatke iz budućnosti?)
- Slippage (nemaš ga u backtestingu?)
- Latency (delay između signala i izvršenja)
- Market impact (tvoj order može pomeriti cenu)

**PREPORUKA** za Live Testing:
- Počni sa MINIMALNIM iznosima (5-10 USD po poziciji)
- Uporedi sa backtesting rezultatima nakon 100+ tradeova
- Očekuj 20-30% slabije rezultate nego u backtestingu

### 5. Timing Risk
**PROBLEM**: Svi tvoji entry/exit su na zatvaranju 15min svećice.

**RIZIK**: Ako se svi izvršavaju u isto vreme, možeš imati slippage.

**PREPORUKA**:
- Dodaj mali offset (30s-60s) između simbola
- Koristi limit ordere umesto market ordersa

## 🎯 PLAN ZA LIVE TESTING

### Faza 1: Paper Trading (1 nedelja)
- Pokreni skriptu bez realnih ordersa
- Samo loguj šta bi napravio
- Validuj da logika radi kako treba

### Faza 2: Micro Live (2 nedelje)
- $5-10 po poziciji
- Maksimalno 3 pozicije istovremeno
- Ciljaj 50+ tradeova za statistiku

### Faza 3: Small Live (1 mesec)
- $20-50 po poziciji
- Maksimalno 5 pozicija istovremeno
- 100+ tradeova

### Faza 4: Regular Live (2+ meseca)
- Normalne veličine pozicija
- Uporedi sa backtestingom

## 📈 Metrike za Praćenje

Napravi Excel/CSV sa ovim metrikama:
- **Win Rate**: % profitabilnih tradeova
- **Profit Factor**: Total Profit / Total Loss
- **Average Win / Average Loss**
- **Max Drawdown**: Najveći pad od peak-a
- **Sharpe Ratio**: Risk-adjusted returns
- **Consec. Losses**: Najduža serija gubitaka

## 🔍 Monitoring Checklist

Svaki dan proveri:
- [ ] Da li skripta još radi?
- [ ] Da li ima novih errorsa u log fajlovima?
- [ ] Koliko je aktivnih pozicija?
- [ ] Kakav je dnevni PnL?
- [ ] Da li ima anomalija (npr. 10 uzastopnih gubitaka)?

## ⚠️ Red Flags - Kada STOPIRATI

ODMAH stopiranje ako:
- Daily loss > $500 (ili tvoj MAX_DAILY_LOSS_USD)
- 10+ uzastopnih gubitaka
- API keys compromised
- Neobična aktivnost na nalogu
- Veći gubitak od backtestinga za >50%

## 🚀 Dodatne Sugestije

1. **Webhook Notifikacije** (Telegram/Discord bot)
   - Obaveštenje za svaki trade
   - Alert za velike gubitke
   - Dnevni report

2. **Dashboard**
   - Streamlit ili Dash app za live monitoring
   - Real-time grafikoni PnL-a
   - Active positions pregled

3. **Database**
   - Umesto CSV fajlova, koristi SQLite/PostgreSQL
   - Bolja analiza podataka kasnije

4. **A/B Testing**
   - Test različite parametre istovremeno
   - 50% sa jednim setom, 50% sa drugim

5. **Machine Learning**
   - Posle 3 meseca, koristi podatke za ML model
   - Optimizuj parametre bazno na live rezultatima

## 📝 Dodatne Napomene

- **Leverage 10x je VISOK** - Za testiranje razmisli 2x-5x
- **Diversifikacija** - Ne stavljaj sve u kripto strategiju
- **Emotions** - Automatska strategija ne radi sve sama, moraš nadgledati
- **Market Changes** - Strategija koja radi 3 godine možda neće raditi sledeće

## 📞 Support

Ako imaš problema:
1. Proveri log fajlove (error.log, info.log)
2. Proveri da li je API key validan
3. Proveri Binance status (status.binance.com)
4. Proverio si dokumentaciju

---

**Sreća u testiranju! 🍀**

NAPOMENA: Ovo nije finansijski savet. Kripto trading je rizičan. Trguj samo sa novcem koji možeš da izgubiš.
