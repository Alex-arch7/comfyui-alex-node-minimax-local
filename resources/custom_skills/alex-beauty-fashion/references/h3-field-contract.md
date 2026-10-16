# Compact H3 field contract (self-contained reference)

Follow the h3-prompt-writing structure for the detected mode. Official guides live in the
bundled h3-prompt-writing skill; this is the minimum viable contract so this skill stays
self-contained.

## Base modes (T2VA / I2VA / FL2VA / L2VA) - three fields, in this order

1. `integrated_multimodal_description:` - shot-by-shot timeline. Each shot: composition, subject
   action, environment, camera move, sound, and for keyframe modes an explicit alignment sentence
   ("The first frame <Picture 1> opens the timeline at 00:00.000..."). Shot headers use
   `[Shot N] At MM:SS.mmm`; Shot 1 carries no timestamp. All timestamps must be < target duration.
2. `overall_soundscape:` - every diegetic sound mapped to its on-screen source.
3. `non_diegetic_music:` - genre, tempo feel, instrumentation, dynamics arc; or `N/A`.

## Ref2VA - six fields, in this order

1. `subject_definitions:` - one line per subject: `<Subject 1> = adult woman from <Picture 1>, ...`
2. `summary:` - bracket tags, e.g. `[reference generation] + [keyframe completion]`.
3. `retention_analysis:` - one line per asset: `<Picture 1> fully_preserved; <Picture 2>
   attribute_transfer (wardrobe to subject); ...`
4. `detailed_description:` - the shot timeline (same rules as base field 1), referencing every
   connected `<Picture N>` at least once.
5. `overall_soundscape:` / 6. `non_diegetic_music:` - as above.

## Hard rules (audit-enforced downstream)

- Field order exactly as listed; field names in English even when body text is Chinese.
- Labels `<Picture N>` `<Video N>` `<Audio N>` `<Subject N>` contiguous from 1 and consistent
  across all sections; never renumber.
- Concrete details over abstractions; dialogue in the user's language; no invented on-screen text.
- Total timeline ends at or before the requested duration (4-15s).
