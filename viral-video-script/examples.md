# Viral Video Script — worked examples

Two full beat sheets showing the formula applied end-to-end. Each maps every beat
back to the six principles. Use them as the quality bar.

---

## Example 1 — Buldak instant ramen (EN, TikTok, ~32s)

**Format stolen (#1):** spicy-challenge reaction. **Credential (#4):** Korean
street-food chef. **Identity value (#3):** *"I'm brave enough to take on the
hottest thing in the room."* **Share trigger (#5):** surprise. **Premise (#5,
one sentence):** *"A chef ranks instant ramen by how badly it wrecks you."*

```json
{
  "slug": "buldak-spicy",
  "language": "en",
  "platform": "tiktok",
  "target_seconds": 32,
  "subject": {
    "product": "Buldak instant ramen",
    "audience": "spice-loving Gen Z snackers",
    "format_steal": "spicy-challenge reaction video",
    "credential": "Korean street-food chef",
    "identity_value": "I'm the kind of person brave enough to take the hottest challenge",
    "share_trigger": "surprise",
    "shareable_premise": "A chef ranks instant ramen by how badly it wrecks you"
  },
  "captions": true,
  "cut_every_seconds": 3,
  "beats": [
    {
      "beat": "hook",
      "seconds": 2,
      "spoken": "I'm a chef and this one made me tap out in four seconds.",
      "on_screen": "Chef in whites, pro kitchen, hand hovering over a steaming bowl.",
      "caption": "I tapped out in 4 seconds.",
      "note": "Curiosity gap + credential, no product name (#2,#4)."
    },
    {
      "beat": "problem",
      "seconds": 6,
      "spoken": "Everyone says they can handle spice — until it's actually testing them in front of people.",
      "on_screen": "Quick cuts of people hyping themselves up, then sweating.",
      "caption": "Everyone THINKS they can handle it.",
      "note": "Identity-layer tension, not a product claim (#3)."
    },
    {
      "beat": "story",
      "seconds": 17,
      "spoken": "So I lined up the internet's scariest bowls and ranked them by pain. Mild. Spicy. And then this Buldak one — the bowl that ends friendships. First bite, fine. Then it climbs.",
      "on_screen": "Three bowls; chef tastes each; real reaction on the last; subtle pack reveal.",
      "caption": "The bowl that ends friendships.",
      "note": "Stolen format plays out; product enters naturally (#1,#2)."
    },
    {
      "beat": "payoff",
      "seconds": 7,
      "spoken": "If you can finish this one without reaching for milk, you're built different. Tag the friend who'd lose.",
      "on_screen": "Chef wipes a tear, laughs, points at camera; product on counter.",
      "caption": "Tag who'd lose. 🥛",
      "note": "Resolves the gap + identity reward; share-bait CTA (#3,#5)."
    }
  ]
}
```

`narration.txt` (what the avatar speaks) is just the four `spoken` lines, blank-line
separated — ready for `voice-clone` / `avatar-reel-composer`.

---

## Example 2 — Stan, creator platform (ES, Reels, ~34s)

**Formato robado (#1):** office tour estilo "¿cuánto pagas de arriendo?".
**Credencial (#4):** fundador que escaló su negocio solo. **Valor de identidad
(#3):** *"Puedo construir mi propio negocio sin un equipo gigante."* **Gatillo de
compartir (#5):** sorpresa. **Premisa (#5):** *"Un creador maneja todo su negocio
desde una sola pantalla."*

```json
{
  "slug": "stan-office-tour",
  "language": "es",
  "platform": "reels",
  "target_seconds": 34,
  "subject": {
    "product": "Stan (plataforma todo-en-uno para creadores)",
    "audience": "creadores que recién monetizan",
    "format_steal": "office tour estilo '¿cuánto pagas de arriendo?'",
    "credential": "fundador que escaló su negocio sin equipo",
    "identity_value": "Soy capaz de construir mi propio negocio sin depender de nadie",
    "share_trigger": "surprise",
    "shareable_premise": "Un creador maneja todo su negocio desde una sola pantalla"
  },
  "captions": true,
  "cut_every_seconds": 3,
  "beats": [
    {
      "beat": "hook",
      "seconds": 2,
      "spoken": "Construí todo esto solo. ¿Quieres ver el tour?",
      "on_screen": "Fundador abre la puerta de su oficina/escritorio; cámara en mano.",
      "caption": "Lo construí solo.",
      "note": "Gancho de curiosidad + credencial, sin nombrar el producto (#2,#4)."
    },
    {
      "beat": "problem",
      "seconds": 6,
      "spoken": "Todos creen que necesitas un equipo enorme para vivir de tu contenido. No es verdad.",
      "on_screen": "Cortes de gente abrumada con mil pestañas y apps abiertas.",
      "caption": "No necesitas un equipo enorme.",
      "note": "Tensión a nivel identidad, no característica (#3)."
    },
    {
      "beat": "story",
      "seconds": 18,
      "spoken": "Te muestro mi día: cobro a mis seguidores, vendo mi curso y agendo llamadas. Antes eran cinco apps distintas. Hoy abro Stan y está todo en una sola pantalla.",
      "on_screen": "Recorrido rápido: pagos, curso, calendario; reveal natural de la pantalla.",
      "caption": "Antes: 5 apps. Hoy: una.",
      "note": "El formato robado se desarrolla; el producto entra solo (#1,#2)."
    },
    {
      "beat": "payoff",
      "seconds": 8,
      "spoken": "Resulta que no te faltaba talento, te faltaban menos pestañas. Guarda esto para cuando te animes.",
      "on_screen": "Fundador se encoge de hombros sonriendo; pantalla limpia al fondo.",
      "caption": "Guárdalo para después. ✅",
      "note": "Resuelve el gap + recompensa de identidad; CTA de guardar/compartir (#3,#5)."
    }
  ]
}
```

---

## How to reproduce

```bash
# scaffold -> fill -> validate -> render
python3 .cursor/skills/viral-video-script/scripts/scaffold.py buldak-spicy \
  --product "Buldak instant ramen" --language en --platform tiktok --seconds 32 --out scripts_out/
# (edit scripts_out/buldak-spicy.script.json)
python3 .cursor/skills/viral-video-script/scripts/check_script.py scripts_out/buldak-spicy.script.json
python3 .cursor/skills/viral-video-script/scripts/render_script.py scripts_out/buldak-spicy.script.json
```
