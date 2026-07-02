# TimeTrack

> **EN:** Minimalist time tracker for Windows living in the system tray. Press
> a global hotkey (**Ctrl+Alt+T**), type what you are working on, hit Enter —
> TimeTrack keeps the timestamps, renders daily/weekly Markdown summaries and
> sends worklogs to **Jira Cloud / Tempo** (including the mandatory Tempo
> account attribute, auto-discovered per instance). Pure Python 3.11+,
> **standard library only** — nothing to install. Data lives locally in
> append-only JSONL files; API tokens are encrypted with Windows DPAPI.
> Setup: see [INSTALL.md](INSTALL.md). The UI and the documentation below are
> in Czech. MIT license.

Minimalistická evidence odpracovaného času pro Windows. Během dne zapisuješ
jen krátké texty — aplikace si sama ukládá časy a večer ti vygeneruje sumář
pro zápis do Jiry.

Žádné závislosti — stačí Python 3.11+ (používá jen standardní knihovnu).

## Jak to funguje

1. Aplikace běží na pozadí s ikonou v systémové liště. Stiskneš
   **Ctrl+Alt+T** kdekoli ve Windows (nebo klikneš levým na ikonu).
2. Objeví se malé okno s jedním textovým polem. Napíšeš, na čem začínáš
   dělat (např. `PROJ-123 oprava loginu`), a dáš Enter. Okno zmizí.
3. Při dalším zadání se předchozí aktivita automaticky ukončí a začne nová.
4. Klíč Jira ticketu (`PROJ-123`) se z textu rozpozná sám.
5. Můžeš vložit i celou URL tasku z Jiry (klidně s `?parametry`) — aktivita
   dostane klíč tasku přímo do názvu (odkaz se neukládá, je odvoditelný
   z configu).
6. Když ticket zjistíš až v průběhu práce, přiřadíš ho zpětně příkazem
   `ticket <klíč nebo URL>` — běžící aktivita dostane klíč do názvu
   i status ticketu.
7. Při psaní klíče ticketu okno našeptává dříve použité klíče (z historie):
   zbytek se nabídne šedě, **Tab** ho doplní, **↑/↓** přepínají mezi shodami
   a v seznamu pod polem jde vybrat i myší.

Pravý klik na ikonu v liště otevře menu: *Zadat aktivitu*, *Dnešní sumář*,
*Týdenní přehled*, *Upravit záznamy…*, *Odeslat do Jiry…*, *Nastavení…*,
*Konec*.

### Příkazy v okně

| Zadání                  | Akce                                              |
| ----------------------- | ------------------------------------------------- |
| libovolný text          | start nové aktivity (předchozí se ukončí)         |
| `text // poznámka`      | start aktivity s poznámkou (`//` až za mezerou)   |
| URL Jira tasku          | aktivita dle klíče tasku (klíč rovnou v názvu)    |
| `pozn text`             | přidá poznámku k poslední (běžící) aktivitě       |
| `ticket <klíč/URL>`     | přiřadí ticket k poslední aktivitě (doplní název) |
| `stop` / `pauza`        | ukončí běžící aktivitu (oběd, konec dne)          |
| `?` / `den`             | vygeneruje a otevře dnešní sumář                  |
| `týden` / `week`        | vygeneruje a otevře týdenní přehled               |
| `uprav [datum]` / `edit`| otevře editor záznamů (`uprav vcera`, `uprav 2026-06-09`; bez data dnešek) |
| `jira [datum]`          | otevře výkazy k odeslání do Jiry (`jira vcera`, `jira 2026-06-09`; bez data dnešek) |
| `nastaveni` / `settings`| otevře okno s nastavením                          |
| `quit` / `konec`        | ukončí aplikaci                                   |
| Esc                     | zavře okno bez akce                               |

## Spuštění

```powershell
# na pozadí (bez konzole) — běžný provoz
pythonw -m timetrack

# automaticky po přihlášení do Windows
powershell -ExecutionPolicy Bypass -File install_autostart.ps1

# ukončení běžící aplikace (např. ze skriptu; totéž co Konec v menu)
python -m timetrack quit
```

Spouštěj ze složky projektu (kvůli `-m timetrack`).

### Samostatný .exe (bez Pythonu)

`powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install` sestaví přes
PyInstaller jediný `dist\TimeTrack.exe`, který běží i na počítači bez Pythonu
(GUI/tray; CLI příkazy zůstávají přes `py -m timetrack`). Postup instalace
pro příjemce je v [INSTALL.md](INSTALL.md), cesta A.

### Vlastní jméno procesu ve Správci úloh

Aby se proces jmenoval `TimeTrack.exe` (a ne `pythonw.exe`), vytvoř si
jednorázově projektový venv a zkopíruj jeho spouštěč pod novým jménem:

```powershell
python -m venv --without-pip .venv
copy .venv\Scripts\pythonw.exe .venv\Scripts\TimeTrack.exe
.venv\Scripts\TimeTrack.exe -m timetrack
```

Skript `install_autostart.ps1` launcher použije automaticky, pokud existuje.
(Sloupec „Popis“ ve Správci úloh zůstává „Python“ — je zadrátovaný v binárce,
ale proces se jmenuje TimeTrack.exe a tak ho i najdeš.)

## CLI

Vše jde i z terminálu:

```powershell
python -m timetrack log PROJ-123 oprava loginu   # start aktivity
python -m timetrack note cekam na review         # poznámka k poslední aktivitě
python -m timetrack stop                         # ukončení
python -m timetrack summary                      # dnešní sumář
python -m timetrack summary 2026-06-09           # sumář konkrétního dne
python -m timetrack week                         # přehled aktuálního týdne
python -m timetrack week 2026-06-09              # přehled týdne s daným dnem
python -m timetrack jira                         # odeslání dnešních worklogů do Jiry
python -m timetrack jira 2026-06-09              # odeslání worklogů konkrétního dne
python -m timetrack quit                         # ukončení běžící aplikace na pozadí
```

## Nastavení (okno)

*Nastavení…* v tray menu (nebo `nastaveni` v okně) otevře okno s kartami:

- **Obecné** — spouštění po přihlášení (přepínač rovnou vytvoří/smaže
  zástupce ve Startup), klávesová zkratka.
- **Vykazování času** — zaokrouhlování a tři přepínače auto-stopu.
- **Integrace (Jira/Tempo)** — base URL, e-mail, pole accountu a oba tokeny
  (maskované; prázdné pole = ponechat stávající). Tlačítko **Otestovat
  připojení** ověří e-mail i tokeny proti Jiře a Tempu, než je uložíš.
- **Data** — složka s daty (s výběrem a otevřením).
- **O aplikaci** — verze a otevření logů.

Většina změn se projeví **hned** (zkratka se přeregistruje za běhu, auto-stop
i přihlašovací údaje se načtou živě). Tokeny se na disk ukládají **šifrovaně
přes Windows DPAPI** (svázané s tvým účtem); starší plaintext tokeny se čtou
dál a při prvním uložení se zašifrují.

## Konfigurace

Nastavení se ukládá do `%USERPROFILE%\.timetrack\config.json` (vytvoří se při
prvním spuštění); jde upravit i ručně:

```json
{
  "data_dir": "C:\\Users\\ty\\Documents\\TimeTrack",
  "filename_format": "%Y-%m-%d.jsonl",
  "summary_filename_format": "%Y-%m-%d-summary.md",
  "week_summary_filename_format": "%G-W%V-summary.md",
  "hotkey": "ctrl+alt+t",
  "rounding_minutes": 15,
  "rounding_mode": "nearest",
  "round_times": false,
  "auto_stop_on_lock": false,
  "auto_stop_on_suspend": false,
  "auto_stop_on_logoff": false,
  "jira_base_url": "https://firma.atlassian.net/browse/",
  "jira_email": "",
  "jira_account_field": ""
}
```

- `data_dir` — kam se ukládají data i sumáře
- `filename_format` / `summary_filename_format` / `week_summary_filename_format`
  — strftime vzory názvů souborů (`%G`/`%V` = ISO rok/týden)
- `hotkey` — kombinace `ctrl`/`alt`/`shift`/`win` + písmeno/číslice/F1–F24
- `rounding_minutes` — zaokrouhlování součtů v sumáři (0 = vypnuto); u
  celkového součtu se v závorce ukáže i přesná hodnota
- `rounding_mode` — `"nearest"` (na nejbližší násobek) nebo `"up"` (vždy nahoru)
- `auto_stop_on_lock` / `auto_stop_on_suspend` / `auto_stop_on_logoff` —
  automaticky ukončí běžící aktivitu při zamčení obrazovky / uspání i
  hibernaci / odhlášení či vypnutí Windows. Každý spouštěč zvlášť, vše
  výchozí `false` (zapni si jen ty, které chceš). Zapíše `stop` jen když
  něco opravdu běží; čas ukončení = okamžik události (např. zamčení), takže
  se nepočítá doba, kdy jsi byl pryč.
- `round_times` — `true` zaokrouhlí i časy v ose (začátky a konce aktivit na
  násobky `rounding_minutes`, vždy na nejbližší). Data v JSONL zůstávají
  přesná, zaokrouhluje se jen zobrazení a export; součty pak sedí na osu
  a worklogy v Jiře začínají na čtvrthodinách. Aktivita kratší než půl
  kroku může v ose klesnout na 0 min (do Jiry se pak neposílá). S `false`
  zůstává osa přesná a zaokrouhlují se jen součty.
- `jira_base_url` — základ odkazu na tickety; klíče v sumáři se pak vykreslí
  jako klikatelné odkazy (prázdný řetězec = bez odkazů); z téže adresy se
  odvozuje i API pro odesílání worklogů
- `jira_email` — e-mail Atlassian účtu pro odesílání worklogů (viz níže)
- `jira_account_field` — id pole s accountem (Tempo Account) na požadavku;
  dialog odesílání pak u každého výkazu ukazuje account jeho ticketu.
  Prázdné (výchozí) = pole se při odesílání najde samo podle typu z Tempo
  pluginu (`GET /rest/api/3/field`); ručně vyplněné id (např.
  `customfield_10100`) má přednost.

Po změně konfigurace aplikaci restartuj. Při aktualizaci aplikace se nové
klíče do existujícího souboru doplní samy s výchozími hodnotami.

## Úprava záznamů

*Upravit záznamy…* v tray menu (nebo `uprav` v okně) otevře tabulku aktivit:
začátek, konec, text a poznámky jdou přepsat přímo, ✕ aktivitu smaže — s
volbou, jestli po ní nechat mezeru, nebo přes uvolněný čas natáhnout
předchozí aktivitu. Hodí se na doladění dne před odesláním do Jiry (časy,
klíč ticketu v textu, poznámky).

- Nahoře je **výběr dne** — můžeš upravit i včerejšek nebo starší den
  (`uprav vcera`, `uprav 2026-06-09`; bez data dnešek). Den bez záznamů se
  otevře prázdný, ať jde doplnit zapomenutá aktivita.
- **+ Přidat řádek** doplní novou aktivitu (předvyplní se na největší mezeru
  dne) — třeba na vyplnění díry, kterou jsi ráno zapomněl zadat. Řádky
  můžeš zadat v libovolném pořadí, při uložení se seřadí podle času a
  zkontroluje se, že se nepřekrývají.

- Konec jedné a začátek další aktivity je tatáž hranice — když navazují
  a chceš hranici posunout, uprav obě pole.
- Prázdný konec = běžící aktivita (smí být jen poslední).
- Klíč ticketu se z upraveného textu rozpozná znovu, stejně jako při zadávání.
- Před uložením se původní soubor dne zazálohuje jako `.bak`; zápis je
  atomický, takže přerušené uložení den nerozbije.
- Pokud posuneš začátek úseku, který už je odeslaný v Jiře, evidence
  odeslání se posune s ním — nic se nenabídne k odeslání podruhé.

## Odesílání worklogů do Jiry

Odpracovaný čas jde zapsat rovnou k ticketům v Jiře (Cloud) — z tray menu,
příkazem `jira [datum]` v okně (`jira vcera`, `jira 2026-06-09`), nebo
z terminálu. Dialog má nahoře **výběr dne**: rozbalovací seznam posledních
14 dnů, u každého rovnou vidíš stav (`neodesláno 2 h 15 min`, `vše
odesláno ✓`, `bez záznamů`) — při zpětném vykazování tak hned najdeš, kde
je resta. Přepnutí dne překreslí tabulku.

Dialog ukáže všechny výkazy dne: už odeslané se zeleným **✓ v Jiře**
(ty jdou tlačítkem *Smazat z Jiry* zase odstranit), neodeslané se
zaškrtávátkem a editovatelnými poli — **časy, ticket i komentář jdou před
odesláním přepsat** (úprava ovlivní jen to, co se pošle do Jiry, lokální
záznamy se nemění; na ty je editor záznamů). Odešle se jen zaškrtnuté;
v terminálu zadáš čísla položek, `vse`, nebo `nic`.

Jednorázové nastavení:

1. Do configu doplň `jira_email` (e-mail tvého Atlassian účtu).
2. Na <https://id.atlassian.com/manage-profile/security/api-tokens> si
   vygeneruj API token a ulož ho jako jediný řádek do souboru
   `%USERPROFILE%\.timetrack\jira_token`.
3. **Pokud používáte Tempo** s povinným accountem na worklogu („Typ
   činnosti“): v Jiře otevři Tempo → Nastavení → **API Integration** →
   nový token (scopes `worklogs:write` + `accounts:read`) a ulož ho do
   `%USERPROFILE%\.timetrack\tempo_token`. Worklogy se pak zakládají přes
   Tempo API a atribut Account se vyplní automaticky z accountu požadavku
   (pole z `jira_account_field`). Bez Tempo tokenu se používá čisté Jira
   API a Typ činnosti zůstane prázdný — aplikace na to upozorní.

Jak to funguje:

- Jeden worklog = jeden souvislý blok práce na ticketu (sousední úseky téhož
  ticketu se slijí). Bloky na sebe navazují a **nikdy se v Jiře nepřekrývají**
  — ani se zapnutým `round_times`, kdy začátky a konce přiléhají na
  čtvrthodiny.
- Všechna pole výkazu (ticket, od, do, komentář) jsou v dialogu **povinná**
  — bez nich se neodešle nic. Komentář se předvyplní poznámkami aktivit
  bloku; CLI bez poznámek výkaz odmítne (doplň `pozn ...` nebo pošli přes
  dialog). Číslo ticketu se do komentáře nikdy nedává — ticket je v Jiře
  sám o sobě.
- Sloupec **Account** ukazuje account ticketu (pole z `jira_account_field`,
  načítá se na pozadí z Jiry). Tempo přiřazuje čas k accountu podle
  požadavku samo — sloupec slouží ke kontrole, že ticket account má.
- Sloupec **Název** ukazuje název požadavku z Jiry; stáhne se jednou a
  uloží do `~/.timetrack/ticket_names.json`, takže se příště zobrazí hned.
- **Komentář se pamatuje**: po odeslání se uloží k danému výkazu a zobrazuje
  se u něj. Když worklog smažeš z Jiry, komentář zůstane předvyplněný pro
  další odeslání (nemusíš ho psát znovu).
- Běžící aktivita se počítá až po ukončení; aktivity bez ticketu se
  neposílají (v seznamu se jen připomenou). Se zapnutým `round_times` se
  neposílají ani bloky, které po zaokrouhlení klesly na 0 min — picker je
  vyjmenuje.
- Úspěšné odeslání se zapíše do denního souboru jako událost `jira_sync`
  (s ID worklogu, začátkem bloku a informací, zda šel přes Jiru nebo
  Tempo — mazání pak používá stejné API), takže opakované spuštění nabídne
  jen dosud neodeslané bloky — nic se nepošle dvakrát. Když odeslání selže
  (špatný token, chybějící oprávnění), blok zůstane nabídnutý příště.
- Smazání worklogu z Jiry přidá událost `jira_unsync` a blok se zase nabízí
  k odeslání — „upravit odeslaný výkaz" tedy znamená smazat ho z Jiry
  a poslat znovu s upravenými hodnotami.
- Dialog před odesláním hlídá, aby se výkazy (včetně už odeslaných)
  nepřekrývaly.

## Data

Jeden JSONL soubor na den, append-only — záznamy se při běžném provozu nikdy
nepřepisují, takže o data nepřijdeš ani při pádu systému. Jedinou výjimkou je
editor záznamů, který den přepíše atomicky a původní obsah nechá v `.bak`.
Soubor můžeš kdykoli ručně upravit i v textovém editoru (např. doplnit
zapomenutý `stop`); pokud po editaci chybí koncový řádek, aplikace si ho před
dalším zápisem doplní sama:

```json
{"ts": "2026-06-10T14:32:05+02:00", "type": "start", "text": "PROJ-123 oprava loginu", "ticket": "PROJ-123", "note": "cekal jsem na build"}
{"ts": "2026-06-10T14:50:00+02:00", "type": "note", "text": "pak jeste review"}
{"ts": "2026-06-10T15:10:12+02:00", "type": "stop"}
```

Aktivita běží od svého `start` do času následujícího `start`/`stop`; události
`note` se připojují k poslední aktivitě, událost `ticket` jí zpětně přiřadí
ticket (klíč se stane součástí názvu). Odeslání do Jiry přidá událost
`jira_sync` (ticket, sekundy, ID worklogu, začátek bloku), smazání worklogu
z Jiry událost `jira_unsync` — obě do souboru dne, kterému čas patří, a na
časovou osu nemají vliv. Denní sumář je Markdown s časovou
osou (včetně poznámek), součty podle aktivit a podle ticketů s odkazy do
Jiry. Týdenní přehled (ISO týden Po–Ne) shrnuje součty po dnech a agregace
za celý týden.

## Vývoj

```powershell
python -m pytest          # jednotkové testy
python tests\smoke_run.py cesta\k\config.json   # ruční spuštění GUI s vlastním configem
python tools\make_icon.py                       # přegenerování ikony v assets/
```

## Nápady na rozšíření

- automatický `stop` při zamčení počítače
- úprava odeslaného worklogu na místě přes PUT (teď: smazat a poslat znovu)
