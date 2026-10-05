# Apie-Dashboard: Albert Heijn in Home Assistant

Een Home Assistant-integratie voor je Albert Heijn-account (de Appie-app):

- **Boodschappenlijst**: de lijst uit de AH-app als to-do-lijst, twee kanten op gesynchroniseerd (elke minuut). Toevoegen, afvinken, hernoemen en verwijderen werkt vanuit HA én vanuit de app. Typ een productnummer (bijv. `441199`) om een echt AH-product toe te voegen in plaats van vrije tekst.
- **Bonus voor ons**: alleen de bonus die ertoe doet: je persoonlijke bonus, bonus op producten die je eerder kocht, en bonus op wat op je lijst staat (die staat bovenaan).
- **Kassabonnen**: je laatste kassabon met artikelen en korting, en wat je deze maand bij AH hebt uitgegeven.

> Dit gebruikt de onofficiële, reverse-engineered API van de AH-app. Niet gelieerd aan Albert Heijn. AH kan de API of de inlogstap op elk moment veranderen.

## Entiteiten

| Entiteit | Inhoud |
|---|---|
| `todo.albert_heijn_boodschappenlijst` | De boodschappenlijst. Aantal en bonus staan in de omschrijving van een item. |
| `sensor.albert_heijn_bonus_voor_ons` | Aantal relevante aanbiedingen. Attribuut `offers`: lijst met `title`, `mechanism` ("1 + 1 GRATIS"), `price`, `price_was`, `image`, `source` (`op_lijst` / `persoonlijk` / `eerder_gekocht`), `on_list`, `activated`, `end_date`. Ook `period_start`, `period_end`, `on_list`, `personal`. |
| `sensor.albert_heijn_laatste_kassabon` | Totaal van de laatste kassabon (€). Attributen `datetime`, `items`, `discounts`, `discount_total`, `payments`, `recent` (laatste 10 bonnen). |
| `sensor.albert_heijn_uitgaven_deze_maand` | Som van de kassabonnen deze maand (€, reset op de 1e; met langetermijnstatistiek). |

Grote attributen (`offers`, `items`, `recent`) worden niet in de database opgeslagen.

Kassabonnen zijn alleen de bonnen uit de winkel waarbij je je Bonuskaart (app) hebt gescand, net als in de app.

## Installeren

1. HACS → ⋮ → **Custom repositories** → `https://github.com/eejeha/Apie-Dashboard`, type **Integration**.
2. Installeer **Albert Heijn** en herstart Home Assistant.
3. Instellingen → Apparaten & diensten → **Integratie toevoegen** → *Albert Heijn*.

## Inloggen

AH stuurt na het inloggen door naar `appie://login-exit?code=...`, een adres dat alleen de app kan openen. Die link vang je op met de ontwikkelaarstools van je browser:

1. Open de inlogpagina uit het configuratiescherm in Chrome, maar **log nog niet in**.
2. Open de ontwikkelaarstools (Cmd+Option+I of F12), tabblad **Network**, vink **Preserve log** aan en typ `login-exit` in het filterveld.
3. Log in (inclusief de sms-code).
4. Rechtsklik op de regel `login-exit` → **Copy** → **Copy URL** en plak die in Home Assistant. De code is maar een paar minuten geldig.

Daarna ververst de integratie zelf de toegang (een token is 7 dagen geldig en wordt een dag van tevoren vernieuwd). Lukt dat niet meer, dan vraagt Home Assistant om opnieuw in te loggen.

## Ontwikkelen

```bash
python3 -m venv .venv
.venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

## Bronnen en licentie

De endpoints, headers en inlogstap volgen [gwillem/appie-go](https://github.com/gwillem/appie-go) en zijn gecontroleerd tegen een echt account. [KixAss/home-assistant-appie](https://github.com/KixAss/home-assistant-appie) liet zien hoe de v2-boodschappenlijst werkt. Dit is een eigen Python-implementatie, onder dezelfde licentie als appie-go: [AGPL-3.0](LICENSE).
