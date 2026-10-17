---
name: alex-beauty-fashion
description: |
  Turn one or more photos of an adult woman plus a short creative wish into MiniMax H3 portrait
  shorts (9:16, 4-15s) in eight proven sub-genres: city-walk lookbook, night-neon allure, cute
  daily, guofeng qipao/hanfu, resort pool, minimal architecture, cosplay 2.5D, and athleisure.
  The Skill locks facial identity and wardrobe from the reference photos, picks a sub-genre and
  a beat plan (one beat for 4-7s, three beats for 8-11s), applies action chains, camera moves,
  and lighting recipes distilled from 49 curated reference clips, and writes a ready-to-render
  H3 prompt. Not for product ads, animation, horror, explicit sexual content, or celebrity
  likenesses.
compatibility: Designed for the alex_h3_skill_local / alex_h3_skill_API ComfyUI nodes with H3
  video generation downstream; portable to any agent that can emit H3 prompt structures.
metadata:
  trigger-words: [beauty fashion, fashion short, portrait short, lookbook, allure, cute girl video,
    美女视频, 时尚短片, 写真视频, 氛围感美女, 魅惑, 甜妹, 国风旗袍, 街拍, 回眸, 甩发, 变装]
---

# Alex Beauty Fashion (alex-beauty-fashion)

Convert reference photo(s) of an adult woman plus a one-line wish into a renderable MiniMax H3
prompt for a 9:16 portrait short. Every rule below was extracted from a personal corpus of 49
curated clips (4.7-11.4s, mean 8.3s, 24fps, 96% with native audio). Follow it literally; when
the user's wish conflicts with a rule, keep the rule for SAFETY and the wish for CONTENT.

## When to use / not use

- Use: single adult female subject, portrait fashion/atmosphere shorts, photo-to-video lookbooks,
  cute or alluring action showcases, guofeng (Chinese classical) styling.
- Not for: multi-person story drama, product ads (use minimalist-product-ad-generator), animation,
  horror, nudity or explicit content, real celebrity/influencer likeness, watermark replication.

## Step 1 - Intake and identity lock

1. Require at least one reference photo. Lock: face identity, hairstyle, makeup, wardrobe items,
   accessories, body proportions. These must not drift across shots or bleed onto other subjects.
2. If the user supplies 2-3 photos (face close-up + full outfit + scene), treat as Ref2VA and
   label them `<Picture 1..3>`; a single first-frame photo is I2VA.
3. Confirm duration (default 8s; hard range 4-15s) and ratio (default 9:16).
4. The subject must read clearly as an adult; if age is ambiguous, harden styling toward mature
   fashion (heels, structured garments, refined makeup) and state "adult woman" in the prompt.
5. MINIMAL-REQUEST POLICY: if the user only types a trigger word (美女 / beauty / 氛围感 / lookbook)
   with no other wish, never ask questions. Derive the sub-genre from the reference photo itself
   (wardrobe, location, lighting), then pick an action chain from references/action-library.md and
   a closing beat; keep the node's duration and ratio widgets as the only format authority. Across
   repeated runs of the same minimal request, deliberately rotate chains (cute/allure/guofeng/
   walk-in/playful) so seeds produce visibly different videos instead of the same safe choice.

## Step 2 - Pick a sub-genre (from the corpus)

Choose by the user's keywords, wardrobe, and location in the reference; if ambiguous, ask one
question or default to city-walk lookbook.

| Sub-genre | Wardrobe | Location | Light | Signature actions |
|---|---|---|---|---|
| city-walk lookbook | bodycon slit dress, knit set, cardigan+inner | park path, European street, landmark (Eiffel/Bund/Santorini) | golden-hour backlight or overcast soft | approach walk, hair flip, over-shoulder glance |
| night-neon allure | satin/velvet mini, slip dress, heels | night street, parking lot, club edge, rooftop skyline | neon streaks + bokeh, warm lamp | slow turn to camera, hand to collarbone, eyes-closed face tilt then smile |
| cute daily | soft knit, shirt over inner top, skirt | cafe seat, balcony, mirror selfie, with pet | bright soft daylight | cat-paw fists, wave to lens, head tilt smile, playful pout |
| guofeng qipao/hanfu | floral qipao, lace qipao, red hanfu with wide sleeves | vintage lounge, Bund railing, red stage, garden | warm low-key or dusk rim | classical palm-strike dance hands, sleeve sweep, low-angle look-up, fan/hairpin touch |
| resort pool | bodycon maxi, slip gown, sun hat | infinity pool, deck chair, mountain overlook | dusk sky gradient | sit-edge pose, hand through hair, side profile hold |
| minimal architecture | black set + flowing scarf, fitted top | concrete wall, water mirror, balcony rail | overcast soft, high contrast B/W mood | lean one-leg, scarf caught by wind, wall-touch turn |
| cosplay 2.5D | cat-ear dress, anime white-hair costume | indoor studio, library | soft key + practical lights | reach hand to camera (POV), tilt-and-blink, small sway |
| athleisure | mesh top, leggings, sports bra set | sightseeing platform, park trail, field | blue sky hard sun | spin with hair flare, arm stretch, laugh-look away |

## Step 3 - Beat plan (duration grammar from the corpus)

- 4-7s = ONE beat: entrance or single gesture, end on a held pose. Do not cram.
- 8-11s = THREE beats: hook (0-2s) -> development (2-7s) -> close (last 1.5-2s held pose/glance).
- The corpus's highest-frequency closing beat is the over-shoulder glance (回眸): body turns away,
  face returns to lens, hold. Use it unless the user asks otherwise.
- One pose focus per beat; micro-actions (blinks, lip press, finger tracing) sell realism.

## Step 4 - Action chains

Pick one chain per video; vary chains between variants of the same reference to keep a series
diverse. Full bilingual library: references/action-library.md. Quick sets:

- Cute: wink -> head tilt giggle -> cat-paw fists near chin -> blow kiss -> wave-hold.
- Allure: slow turn -> fingers trace collarbone -> hair slip over shoulder -> over-shoulder glance.
- Guofeng: palm-strike salute -> sleeve sweep across frame -> look-up under lashes -> fan half-open hold.
- Walk-in: approach walk (garment swaying) -> pause at mark -> hair flip -> glance back.
- Playful: adjust sunglasses/glasses -> mock-serious face -> break into smile -> cover mouth laugh.

## Step 5 - Camera and lighting rules (corpus-proven)

- Prefer a locked camera with subject movement; add at most one slow push-in per clip.
- Shot progression that works: full body -> medium -> close-up (or stay selfie-close throughout).
- Selfie-arm angle is valid for cute daily; keep the frame stable, not shaky.
- Low-angle look-up flatters guofeng/hanfu; never voyeuristic angles from body parts.
- Optional exit beat: subject walks away with slight motion blur, then cut.
- Lighting recipes: golden-hour backlight with hair rim; overcast soft for skin; night neon +
  bokeh; warm bedside lamp interior; sunset sky as backdrop. Name the light source concretely.

## Step 6 - Sound design

- Diegetic: footsteps/heels on the surface, fabric rustle, hair movement, ambient (city hum,
  water, birds), one prop sound (glass, fan, scarf snap).
- Music: sparse low-tempo beat for allure; light pluck/percussion for cute; guzheng/dizi blend
  for guofeng; keep it under the ambience. No moaning-style vocals, no lyric text on screen.

## Step 7 - Write the H3 prompt

Follow the h3-prompt-writing structure for the detected mode (see references/h3-field-contract.md
for the compact field list). Rules that the corpus and official tips both prove:

1. Total timeline must end at or before the requested duration; timestamps in MM:SS.mmm.
2. Keep `<Picture N>` / `<Subject N>` labels identical in every section.
3. Concrete nouns beat adjectives: name the fabric, the light source, the action verb; avoid
   "beautiful/cinematic/high-class" as bare descriptors.
4. State how the first/last frame connects to the timeline (I2VA/L2VA/FL2VA alignment sentence).
5. Dialogue, if any, stays in the user's language; default is no dialogue.
6. Never invent on-screen text, logos, or watermarks unless the user supplies the exact copy.

## Step 8 - Output discipline (hard, overrides everything above)

- Output ONLY the H3 prompt body. The very first character must be the first field name:
  `subject_definitions:` (Ref2VA) or `integrated_multimodal_description:` (base modes).
- NO preamble, NO postscript, NO narration of sub-genre / action-chain / lighting choices -
  that reasoning stays internal; the downstream video node reads this text verbatim.
- NO markdown of any kind: no ``` fences, no yaml wrapper, no headings, no bold, no bullets
  around fields. Plain text, field name + colon + content, blank line between fields.
- Use the eight sub-genre names from the Step 2 table verbatim; never invent or brand sub-genre
  names.

## Prohibitions (hard)

Never output preamble/fences/markdown around the prompt; adult subject only; no nudity or explicit suggestion; no voyeuristic camera; no celebrity or
watermark replication; no body horror / extra fingers / warped limbs; no skin-plastic over-smoothing;
no non-consensual framing; wardrobe and accessories must not teleport between shots.

## Self-check before output

First character is a field name with zero preamble and zero code fences; adult reads clearly; face identity locked to reference; one beat per pose; timeline within
duration; labels consistent; light source named; at least two diegetic sounds; closing beat is a
held pose or glance; no text/watermark invented; no prohibited content.
