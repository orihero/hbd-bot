# Bake-off prompt payload

Generated 27 Aug 2026. One fixed song, one fixed style, N orthography arms.
**The only variable is how the name is spelled.** Everything else is held constant.

> **Do not retype these from the terminal.** U+02BB, U+2018 and U+0027 look identical in most fonts and
> editors silently normalise them. That difference IS the experiment. Read strings from
> `bakeoff-prompts.json`, and verify with the command at the bottom before you spend money.

## Fixed style prompt (identical for every arm, every vendor)

```
uzbek pop birthday song, upbeat and celebratory, warm major key, 100 BPM, live doira hand percussion and dutar layered with modern pop production, clear female lead vocal high in the mix, joyful crowd energy
```

Negative styles:

```
muddy vocals, heavy reverb on lead vocal, melisma, whispered vocals, distortion, lo-fi
```

## Target name

Uzbek: **Gʻulomjon** - three syllables, stress on the final one (Gu-lom-JON), and it
contains gʻ so it is exactly the character under test.

Russian: **Алёна** - /ɐˈlʲɤnə/, the ё is the stressed vowel and is the thing that breaks.

## Arms

### A1 - canonical U+02BB  `(uz-Latn)`

*The orthographically correct form. Tokenizer literature predicts it FRAGMENTS the name.*

```
Bugun quyosh boshqacha porlaydi,
Yuraklarda quvonch jaranglaydi.
Doʻstlaring yigʻildi shu dasturxonga,
Bu kun faqat senga atalgan.

Tugʻilgan kuning bilan, Gʻulomjon!

Omad yoʻldosh boʻlsin har zamon,
Orzularing ushalsin, Gʻulomjon,
Baxting boʻlsin cheksiz osmon!
```

### A2 - U+2018 mis-encoding  `(uz-Latn)`

*What real user input mostly looks like. Must be tested because it is the true input distribution.*

```
Bugun quyosh boshqacha porlaydi,
Yuraklarda quvonch jaranglaydi.
Do‘stlaring yig‘ildi shu dasturxonga,
Bu kun faqat senga atalgan.

Tug‘ilgan kuning bilan, G‘ulomjon!

Omad yo‘ldosh bo‘lsin har zamon,
Orzularing ushalsin, G‘ulomjon,
Baxting bo‘lsin cheksiz osmon!
```

### A3 - ASCII apostrophe  `(uz-Latn)`

*Keyboard fallback. Apostrophe may be read as a quote/elision marker.*

```
Bugun quyosh boshqacha porlaydi,
Yuraklarda quvonch jaranglaydi.
Do'stlaring yig'ildi shu dasturxonga,
Bu kun faqat senga atalgan.

Tug'ilgan kuning bilan, G'ulomjon!

Omad yo'ldosh bo'lsin har zamon,
Orzularing ushalsin, G'ulomjon,
Baxting bo'lsin cheksiz osmon!
```

### A4 - stripped, no modifier  `(uz-Latn)`

*THE KEY ARM. If this wins, decouple display orthography from submitted orthography.*

```
Bugun quyosh boshqacha porlaydi,
Yuraklarda quvonch jaranglaydi.
Dostlaring yigildi shu dasturxonga,
Bu kun faqat senga atalgan.

Tugilgan kuning bilan, Gulomjon!

Omad yoldosh bolsin har zamon,
Orzularing ushalsin, Gulomjon,
Baxting bolsin cheksiz osmon!
```

### A5 - phonetic respell (EN-weighted)  `(uz-Latn)`

*Forces the target pronunciation through English grapheme rules.*

```
Bugun quyosh boshqacha porlaydi,
Yuraklarda quvonch jaranglaydi.
Dostlaring yigildi shu dasturxonga,
Bu kun faqat senga atalgan.

Tugilgan kuning bilan, Ghoo-lom-JON!

Omad yoldosh bolsin har zamon,
Orzularing ushalsin, Ghoo-lom-JON,
Baxting bolsin cheksiz osmon!
```

### A6 - Cyrillic  `(uz-Cyrl)`

*Tests whether the model reads it as Russian and applies Russian phonology.*

```
Бугун қуёш бошқача порлайди,
Юракларда қувонч жаранглайди.
Дўстларинг йиғилди шу дастурхонга,
Бу кун фақат сенга аталган.

Туғилган кунинг билан, Ғуломжон!

Омад йўлдош бўлсин ҳар замон,
Орзуларинг ушалсин, Ғуломжон,
Бахтинг бўлсин чексиз осмон!
```

### R1 - Алёна with ё  `(ru)`

*Correct. Target /ɐˈlʲɤnə/.*

```
Сегодня солнце светит по-другому,
И сердце бьётся радостью до дна,
Друзья собрались в этом тёплом доме,
Сегодня этот день — он для тебя.

С днём рожденья, Алёна!

Пусть удача не уйдёт,
Загадай желанье, Алёна,
Пусть мечта твоя придёт!
```

### R2 - Алена without ё  `(ru)`

*How Russians usually type it. Predicts wrong vowel /ɐˈlʲe nə/.*

```
Сегодня солнце светит по-другому,
И сердце бьётся радостью до дна,
Друзья собрались в этом тёплом доме,
Сегодня этот день — он для тебя.

С днём рожденья, Алена!

Пусть удача не уйдёт,
Загадай желанье, Алена,
Пусть мечта твоя придёт!
```

### R3 - АлЁна caps-stress  `(ru)`

*Tests the competitor's caps-for-stress workaround. Predicted to fail: caps = LOUDER, not stressed.*

```
Сегодня солнце светит по-другому,
И сердце бьётся радостью до дна,
Друзья собрались в этом тёплом доме,
Сегодня этот день — он для тебя.

С днём рожденья, АлЁна!

Пусть удача не уйдёт,
Загадай желанье, АлЁна,
Пусть мечта твоя придёт!
```

### E1 - English control  `(en)`

*Establishes each vendor's ceiling. If English fails, the render was just bad.*

```
Today the sun is shining like it knows,
There's something in the air that everybody feels,
Your friends have gathered round, the table's full,
And every single moment here is yours.

Happy birthday to you, Gulomjon!

May the luck be at your side,
May your dreams come true, Gulomjon,
May your sky be open wide!
```

## ElevenLabs: name gets its own chunk

The whole design is that the name line is an isolated 8 s chunk, so a re-render costs one chunk
instead of one track - and so you can measure the inpainting billing unit. Body of `POST https://api.elevenlabs.io/v1/music`:

```json
{
  "composition_plan": {
    "chunks": [
      {
        "text": "",
        "duration_ms": 8000,
        "positive_styles": [
          "instrumental intro",
          "doira percussion",
          "dutar"
        ],
        "negative_styles": [
          "vocals"
        ]
      },
      {
        "text": "Bugun quyosh boshqacha porlaydi,\nYuraklarda quvonch jaranglaydi.\nDoʻstlaring yigʻildi shu dasturxonga,\nBu kun faqat senga atalgan.",
        "duration_ms": 24000,
        "positive_styles": [
          "uzbek pop",
          "warm female lead vocal",
          "clear diction"
        ],
        "negative_styles": [
          "melisma",
          "heavy reverb"
        ],
        "context_adherence": "high"
      },
      {
        "text": "Tugʻilgan kuning bilan, Gʻulomjon!",
        "duration_ms": 8000,
        "positive_styles": [
          "anthemic",
          "clear diction",
          "one voice forward in the mix",
          "syllables evenly spaced"
        ],
        "negative_styles": [
          "melisma",
          "vocal runs",
          "harmony stack",
          "reverb"
        ],
        "context_adherence": "high"
      },
      {
        "text": "Omad yoʻldosh boʻlsin har zamon,\nOrzularing ushalsin, Gʻulomjon,\nBaxting boʻlsin cheksiz osmon!",
        "duration_ms": 20000,
        "positive_styles": [
          "big celebratory chorus",
          "crowd energy"
        ],
        "negative_styles": [
          "melisma"
        ],
        "context_adherence": "high"
      }
    ]
  },
  "model_id": "music_v2",
  "seed": 424242,
  "store_for_inpainting": true
}
```

Swap `chunks[1..3].text` per arm. Keep `seed` fixed at 424242 so arm-to-arm differences are the spelling,
not the dice. Note ElevenLabs calls seed best-effort - if two identical calls differ, say so in the notes.

`store_for_inpainting: true` is what lets you then re-render chunk 2 alone. Do that once and diff the
usage dashboard: a 15 s chunk billing at ~$0.04 vs a full $0.15 decides whether free re-renders are a moat.

## Prompt-only vendors (Lyria 3, MiniMax)

No composition plan. Concatenate verse + name line + chorus into the lyrics field and put the style
string in the prompt. You lose the isolated name chunk, so note in scoring that the name is competing
with a full arrangement - that is a real disadvantage of those vendors, not a flaw in the test.

## Verify the codepoints before spending money

```bash
python3 -c "import json;[print(a['arm'].ljust(3),[hex(ord(c)) for c in a['name_line'] if ord(c) in (0x2bb,0x2018,0x2019,0x27,0x60,0xb4)] or 'no-modifier') for a in json.load(open('bakeoff-prompts.json'))['arms']]"
```

A1 must show `0x2bb`. A2 must show `0x2018`. A3 must show `'`. A4 must show `[]`. If A1 and A2 print the
same thing, your clipboard normalised the text and every Uzbek result is invalid.
