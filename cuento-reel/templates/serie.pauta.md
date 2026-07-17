# Serie de Cuentos — <obra / autor>

> **Pauta editorial y de producción** de una serie de reels-cuento. A diferencia
> de un avatar fijo que habla a cámara, aquí **cada avatar es un PERSONAJE** y el
> hilo lo sostiene un **Narrador** (voz de cuentacuentos, viejito).

---

## 0. Aviso de derechos (interno)
<¿La obra tiene copyright vigente? Si sí: TODO el texto es relato ORIGINAL nuestro,
no se reproduce la prosa del autor; uso personal. Si es dominio público: libre,
pero cuidado con traducciones modernas — adaptar en palabras propias.>

## 1. North Star
> "<la meta emocional en una frase: qué quieres SENTIR/VER al terminar>"

Cada episodio = un capítulo (o trozo) condensado en un reel.

## 2. ADN de la serie (constante en todos los episodios)
| Elemento | Definición fija |
|---|---|
| **Formato** | `reel` vertical 9:16 (TikTok/Reels) o `landscape` 16:9 (YouTube), ~90–120s, narrado en 3a persona + diálogo lip-sync en beats clave. Elige uno por serie y fíjalo en el `storyboard.json` (`"format"`). |
| **Estilo visual** | <fotorrealista cine / soft3d / anime>; paleta y luz consistentes. |
| **Idioma / voz** | español neutro LATAM. Narrador cuentacuentos (viejito); cada personaje con su voz. |
| **Estructura** | Narrador sostiene el hilo; personajes ACTÚAN (acción, no talking-heads); diálogos puntuales con lip-sync. |
| **Cierre** | "Continuará — Episodio N" sobre la última imagen. |
| **Música** | score instrumental a medida, bajo la voz (sin pumping). |

## 3. Reparto (avatares reusables en toda la serie)
| Personaje | Descripción (para `avatar-invent`) | Aparece desde |
|---|---|---|
| **Narrador** | voz cálida, grave, de cuentacuentos anciano; sin cara (voice-only). | Ep. 1 |
| **<Personaje>** | <edad/rostro/pelo/vestuario, época>. | Ep. <n> |

> Figuras de fondo NO necesitan avatar propio: se inventan como secundarios
> *dentro* de cada lámina de `broll-story`.

## 4. Pipeline por episodio (qué skill hace qué)
```
guion original
   ├─ avatar-invent      → narrador (voice-only) + cada PERSONAJE (cara + voz)   [1 vez por serie]
   ├─ broll-story / seedance i2v → beats de ACCIÓN: clips MUDOS, motion none
   ├─ audio-theater + avatar-talking-video → líneas con LIP-SYNC (escenas guest)
   └─ avatar-reel-composer (assemble_narration gap=0 → compose_reel --finish)
```

## 5. Mapa de la serie
| # | Capítulo | Beats clave | Estado |
|---|---|---|---|
| 1 | <título> | <beats> | <estado> |

## 6. Ficha técnica (cada reel)
- 9:16 (`reel`) o 16:9 (`landscape`, YouTube), ~90–120s, 30 fps; generación 720p (subir a 1080p en finales si rinde).
- Captions quemados estilo cuento (serif), español neutro.
- Transiciones: corte limpio + flash/whoosh suave en cambios de mundo.
- SFX a medida (viento, puertas, pasos…); música instrumental bajo la voz.
- Cierre: tarjeta "Continuará — Episodio N".
