# Rule of Six — worked cut sheets

Two full cut sheets showing the hierarchy applied to a reel's edit. Each cut
names emotion + story first (the 74%), then the lower criteria, and marks any
**bottom-up** sacrifices. Both also carry the optional **`sound`** axis (the
soundtrack move at the cut — split edit vs hard-cut punch, which music edit) plus
a top-level **`soundtrack`** intent — see all three music moves demonstrated
across the three cuts. Use them as the quality bar. Both pass `check_cuts.py`.

They pair with the `viral-video-script` examples (same reels), so you can see the
**words** and the **cuts** side by side.

---

## Example 1 — Buldak spicy-challenge reel (EN, reels, 4 scenes / 3 cuts)

**Throughline:** bravado → dread → comic relief. The edit's job is to make the
viewer *feel* the heat climb, then release it in a laugh.

```json
{
  "slug": "buldak-spicy",
  "language": "en",
  "platform": "reels",
  "reel_ref": "lolo/reels/001_buldak-spicy/storyboard.json",
  "emotional_throughline": "bravado -> dread -> comic relief",
  "soundtrack": "driving percussive bed, low under the voice; a variation lifts into the c2 reveal, then a HARD-CUT beat lands on the c3 laugh (the punch)",
  "hierarchy": {"emotion": 0.51, "story": 0.23, "rhythm": 0.10, "eye_trace": 0.07, "plane_2d": 0.05, "space_3d": 0.04},
  "cuts": [
    {
      "id": "c1",
      "at": "s1 -> s2",
      "from": "s1 [talking_head] hook: 'made me tap out in 4 seconds'",
      "to": "s2 [broll] people hyping up, then sweating",
      "emotion": "snap the confident hook into collective dread — the feeling that everyone secretly fears the test",
      "story": "sets the stakes: everyone THINKS they can handle spice",
      "rhythm": "cut hard on the word 'seconds' — ~2s hook, no lingering",
      "eye_trace": "chef's face is centered; keep the sweating faces centered so the eye doesn't hunt",
      "plane_2d": "eye-level, chef addressing camera; B-roll stays eye-level",
      "space_3d": "sacrificed — jump from kitchen to unrelated people",
      "sound": "SPLIT edit — the hook's voice runs across the cut into the B-roll; no beat here, the voice carries it",
      "sacrifices": ["space_3d"],
      "note": "Emotion picks the cut; the location jump is invisible at this speed."
    },
    {
      "id": "c2",
      "at": "s2 -> s3",
      "from": "s2 [broll] sweating faces",
      "to": "s3 [talking_head] the three bowls lined up",
      "emotion": "anticipation — the itch to see how bad it gets",
      "story": "reveal the lineup; the 'bowl that ends friendships' is coming",
      "rhythm": "quick beat cut, momentum building into the reveal",
      "eye_trace": "faces (center) -> bowls (center); interest lands where the eye already is",
      "plane_2d": "match the eye-level framing so the reveal reads instantly",
      "space_3d": "sacrificed",
      "sound": "VARIATION on the cut — the bed lifts (quiet->loud) into the reveal; same track, rising energy",
      "sacrifices": ["space_3d"],
      "note": ""
    },
    {
      "id": "c3",
      "at": "s3 -> s4",
      "from": "s3 [talking_head] tasting the killer bowl, heat climbing",
      "to": "s4 [talking_head] chef wipes a tear, laughs, points at camera",
      "emotion": "release — the climb pays off in a laugh; that's what they'll remember",
      "story": "the verdict + the challenge thrown to the viewer",
      "rhythm": "land the cut on the laugh; a beat of held breath before it",
      "eye_trace": "chef stays center-frame; the point-at-camera pulls the eye to lens",
      "plane_2d": "sacrificed — a deliberate jump-cut tightens on his face for comic jolt",
      "space_3d": "sacrificed",
      "sound": "HARD-CUT PUNCH — drop the beat on the laugh frame; sound + picture hit together for the payoff",
      "sacrifices": ["space_3d", "plane_2d"],
      "note": "Breaking 2D grammar on PURPOSE for the punchline — bottom-up, emotion intact."
    }
  ]
}
```

---

## Example 2 — Stan office-tour reel (ES, reels, 4 escenas / 3 cortes)

**Throughline:** agobio → curiosidad → alivio. El montaje debe hacer *sentir* el
caos de mil apps y luego el descanso de tener todo en una pantalla.

```json
{
  "slug": "stan-office-tour",
  "language": "es",
  "platform": "reels",
  "reel_ref": "nora/reels/001_stan-office-tour/storyboard.json",
  "emotional_throughline": "agobio -> curiosidad -> alivio",
  "soundtrack": "cama musical calma bajo la voz; una variación abre curiosidad en c2 y un outro que se asienta (loud->mellow) entrega el cierre en c3; sin golpes duros",
  "hierarchy": {"emotion": 0.51, "story": 0.23, "rhythm": 0.10, "eye_trace": 0.07, "plane_2d": 0.05, "space_3d": 0.04},
  "cuts": [
    {
      "id": "c1",
      "at": "s1 -> s2",
      "from": "s1 [talking_head] gancho: 'construí todo esto solo'",
      "to": "s2 [broll] pantallas con mil pestañas y apps abiertas",
      "emotion": "pasar de la confianza del gancho al agobio que el espectador ya siente",
      "story": "plantea el problema: creen que necesitas un equipo enorme",
      "rhythm": "corte seco al terminar la frase; gancho ~2-3s",
      "eye_trace": "cara centrada -> mantener el caos de pestañas centrado para no dispersar la vista",
      "plane_2d": "nivel de ojos; el inserto respeta el encuadre",
      "space_3d": "sacrificado — salto de la presentadora al plano de la pantalla",
      "sound": "SPLIT edit — la voz del gancho cruza el corte sobre el B-roll; sin golpe, la narración lo sostiene",
      "sacrifices": ["space_3d"],
      "note": "La emoción manda; el salto de espacio no se nota al ritmo del reel."
    },
    {
      "id": "c2",
      "at": "s2 -> s3",
      "from": "s2 [broll] caos de apps",
      "to": "s3 [talking_head] recorrido: cobros, curso, agenda en una pantalla",
      "emotion": "curiosidad -> promesa de orden",
      "story": "muestra la solución en acción (el producto entra natural, sin pitch)",
      "rhythm": "corte al ritmo, momentum hacia el reveal",
      "eye_trace": "el punto de interés se mueve al centro donde ya estaba el ojo",
      "plane_2d": "encuadre coincidente para que el reveal se lea al instante",
      "space_3d": "sacrificado",
      "sound": "VARIACIÓN sobre el corte — el mismo track abre curiosidad hacia el reveal (giro de dinámica)",
      "sacrifices": ["space_3d"],
      "note": ""
    },
    {
      "id": "c3",
      "at": "s3 -> s4",
      "from": "s3 [talking_head] 'antes: 5 apps. hoy: una'",
      "to": "s4 [broll] pantalla limpia + CTA de guardar",
      "emotion": "alivio — el descanso de tenerlo todo en un lugar; eso se recuerda",
      "story": "cierra el arco + recompensa de identidad y CTA de guardar",
      "rhythm": "aterrizar el corte en la frase de cierre",
      "eye_trace": "la pantalla limpia queda centrada, sin competir por la vista",
      "plane_2d": "regla de tercios en el CTA final",
      "space_3d": "sacrificado",
      "sound": "ENTREGA SUAVE (outro) — la resolución arranca ANTES del corte y deja al espectador en el CTA; música y corte no coinciden a propósito",
      "sacrifices": ["space_3d"],
      "note": "Todos los cortes sacrifican solo 3D — el más barato de soltar."
    }
  ]
}
```

---

## How to reproduce

```bash
# scaffold (from a storyboard) -> fill emotion+story first -> validate -> render
python3 .cursor/skills/rule-of-six-edit/scripts/scaffold.py buldak-spicy \
  --from-storyboard lolo/reels/001_buldak-spicy/storyboard.json --language en --out cuts_out/
# (edit cuts_out/buldak-spicy.cutsheet.json — emotion + story on every cut)
python3 .cursor/skills/rule-of-six-edit/scripts/check_cuts.py cuts_out/buldak-spicy.cutsheet.json
python3 .cursor/skills/rule-of-six-edit/scripts/render_cuts.py cuts_out/buldak-spicy.cutsheet.json
```
