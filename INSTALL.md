# Instalace TimeTrack (Windows)

Jsou dvě cesty. **Cesta A (samostatný .exe)** je nejjednodušší a nepotřebuje
Python. **Cesta B (ZIP s průvodcem)** Python vyžaduje, ale provede tě
nastavením e-mailu a tokenů.

---

## Cesta A — samostatný `TimeTrack.exe` (bez Pythonu)

1. Zkopíruj **`TimeTrack.exe`** kamkoli natrvalo (např. do
   `%LOCALAPPDATA%\TimeTrack`) a spusť ho (dvojklik). Při prvním spuštění může
   Windows SmartScreen ukázat varování u neznámého vydavatele → *Více
   informací → Přesto spustit*. Aplikace naběhne do lišty (**Ctrl+Alt+T**).
2. **Nastav vše v aplikaci:** pravý klik na ikonu → *Nastavení…* → karta
   *Integrace* → vyplň e-mail a oba tokeny (viz [krok 3](#3-tokeny-oba-zdarma)),
   dej **Otestovat připojení** a *Uložit*. Na kartě *Obecné* zapni
   **Spouštět po přihlášení** — autostart se nastaví sám, nic ručně.

To je vše — žádné ruční editování souborů. (Pokud bys přesto chtěl, config a
tokeny jsou ve složce `%USERPROFILE%\.timetrack`.)

To je vše — zbytek (jak se to ovládá) je v sekci [Hotovo](#4-hotovo--jak-se-to-používá).

---

## Cesta B — ZIP s průvodcem (vyžaduje Python)

## 1. Nainstaluj Python (pokud ho ještě nemáš)

TimeTrack potřebuje **Python 3.11 nebo novější**. Stáhni ho z
<https://www.python.org/downloads/> a při instalaci **zaškrtni
„Add python.exe to PATH"**. Nic víc instalovat netřeba — aplikace používá
jen standardní knihovnu.

> Nevíš, jestli Python máš? Nevadí — průvodce v kroku 2 to ověří a když chybí,
> řekne ti to.

## 2. Spusť průvodce instalací

Rozbal složku s TimeTrackem kamkoli a **dvojklikni na
`Nainstalovat TimeTrack.cmd`**.

Průvodce tě provede vším:

1. ověří Python,
2. nainstaluje aplikaci do `%LOCALAPPDATA%\TimeTrack`,
3. zeptá se na tvůj **Atlassian e-mail** a **adresu Jiry**
   (např. `https://firma.atlassian.net`),
4. otevře stránky pro vytvoření dvou **tokenů** (viz krok 3) a uloží je,
5. nabídne **automatický start** po přihlášení a aplikaci rovnou spustí.

Po doběhnutí najdeš ikonu v systémové liště. Hlavní zkratka je **Ctrl+Alt+T**.

## 3. Tokeny (oba zdarma)

Průvodce si o ně řekne. Když je chceš doplnit ručně, ulož každý jako jediný
řádek do složky `%USERPROFILE%\.timetrack\`:

| Soubor (bez přípony) | Kde token získáš |
| --- | --- |
| `jira_token` | <https://id.atlassian.com/manage-profile/security/api-tokens> → *Create API token* |
| `tempo_token` | v Jiře: **Tempo → Settings → API Integration** → nový token se scopes *worklogs: write* + *accounts: read* |

- **`jira_token`** stačí na čtení i základní zápis worklogů.
- **`tempo_token`** je potřeba, aby se u worklogu vyplnil **Typ činnosti
  (account)** — bez něj Tempo zápis odmítne. Když ho nemáš, aplikace tě
  upozorní.

E-mail i adresu Jiry nastaví průvodce; pole accountu (`jira_account_field`)
si aplikace najde sama (ručně vyplněné id v `config.json` má přednost).
Ostatní volby popisuje [README.md](README.md).

## 4. Hotovo — jak se to používá

- **Ctrl+Alt+T** → napiš, na čem děláš (např. `PROJ-42 obnova DB`), Enter.
- Klíč ticketu se pozná sám; když ho zjistíš až potom, napiš `ticket <klíč/URL>`.
- Večer: pravý klik na ikonu → **Odeslat do Jiry…** → zkontroluj, zašktni, odešli.

Kompletní popis ovládání je v [README.md](README.md).

## Časté otázky

- **„python nebyl nalezen"** — používej příkaz `py` místo `python`, nebo
  jen spouštěj přes `Nainstalovat TimeTrack.cmd` / vytvořeného zástupce;
  ty Python najdou samy. (Na čistých Windows zlobí předinstalovaný zástupce
  z Microsoft Store — vyřeší ho instalace Pythonu z python.org s „Add to PATH".)
- **Ukončení aplikace** — pravý klik na ikonu → *Konec*, nebo v příkazové
  řádce `py -m timetrack quit`.
- **Aktualizace** — nejjednodušší je dvojklik na **`Aktualizovat
  TimeTrack.cmd`** (je ve složce aplikace i v ZIPu). Zkontroluje GitHub, a
  pokud vyšla novější verze, stáhne ji, ověří kontrolní součet (SHA-256) a
  tiše ji nainstaluje — běžící aplikaci sám ukončí a po instalaci zase
  spustí. Vyžaduje Python (stejně jako instalace ze ZIPu). Ruční varianta:
  rozbal novou verzi a spusť `Nainstalovat TimeTrack.cmd` znovu. Na už
  vyplněné věci (e-mail, tokeny, autostart) se znovu neptá; tvoje data i
  nastavení zůstanou (jsou mimo složku aplikace).
- **Kde jsou má data** — v `Dokumenty\TimeTrack` (jeden soubor na den).
- **Chyby odesílání do Jiry** se logují do
  `%USERPROFILE%\.timetrack\api_errors.log`.
