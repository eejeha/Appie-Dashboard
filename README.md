# Apie-Dashboard

Home Assistant custom integration voor Albert Heijn, gebaseerd op de API-beschrijving in [gwillem/appie-go](https://github.com/gwillem/appie-go). Onofficieel, niet gelieerd aan Albert Heijn.

## Functies

| Entity / actie | Wat |
| --- | --- |
| `todo.albert_heijn_shopping_list` | Boodschappenlijst (Mijn lijst): bekijken, toevoegen, afvinken, hernoemen, verwijderen. `3x eieren` zet aantal 3. |
| `sensor.albert_heijn_open_shopping_list_items` | Aantal niet-afgevinkte items |
| `sensor.albert_heijn_last_receipt` | Bedrag laatste kassabon, attribuut met laatste 10 bonnen |
| `sensor.albert_heijn_spent_this_month` | Som kassabonnen deze maand (laatste 100 bonnen) |
| `sensor.albert_heijn_order_total` | Totaal actieve online bestelling, attribuut met regels |
| `sensor.albert_heijn_next_delivery` | Starttijd eerstvolgende bezorging/ophaalmoment |
| `sensor.albert_heijn_bonus_offers` | Aantal bonusaanbiedingen deze week, attribuut `spotlight` |
| `appie.add_to_order` | Product (product-ID) toevoegen aan bestelling |
| `appie.remove_from_order` | Product uit bestelling halen |
| `appie.shopping_list_to_order` | Niet-afgevinkte producten van de lijst naar de bestelling (vrije tekst wordt overgeslagen) |
| `appie.search_products` | Zoeken, geeft product-ID's terug (response) |
| `appie.add_product_to_list` | AH-product op de boodschappenlijst zetten |

Verversen: lijst, bonnen en bestellingen elke 15 minuten, bonus elke 6 uur.

## Installatie

HACS: Custom repository `https://github.com/eejeha/Apie-Dashboard`, type Integration. Of handmatig: kopieer `custom_components/appie` naar `config/custom_components/` en herstart Home Assistant.

## Inloggen

AH staat alleen de redirect `appie://login-exit` toe, dus de code moet je handmatig overnemen:

1. Instellingen > Apparaten en diensten > Integratie toevoegen > Albert Heijn (Appie).
2. Open de getoonde inloglink in een desktopbrowser, met de ontwikkelaarstools (F12) open op het tabblad Netwerk.
3. Log in. De browser probeert `appie://login-exit?code=...` te openen en faalt; dat is verwacht.
4. Kopieer in het tabblad Netwerk de URL met `login-exit` (of alleen de `code`) en plak die in Home Assistant.

Tokens worden automatisch ververst. Bij verlopen refresh token vraagt Home Assistant om opnieuw in te loggen.

## Dashboard

Voorbeeldview in [`dashboard/appie.yaml`](dashboard/appie.yaml).

## Niet geverifieerd

De API is vanuit de ontwikkelomgeving niet bereikbaar geweest; alles is getest tegen gemockte responses. Te controleren tegen een echt account:

- Verwijderen van een lijst-item via `PATCH shoppinglist/v2/items` met `quantity: 0`.
- Afvinken via `strikeThrough: true` in dezelfde PATCH.
- Vrije-tekstitems met `originCode: TXT` (appie-go gebruikt `PRD`).

## Ontwikkeling

```
pip install pytest-homeassistant-custom-component aioresponses
pytest
```
