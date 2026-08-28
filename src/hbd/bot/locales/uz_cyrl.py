"""Uzbek Cyrillic catalogue — a full first-class locale, not a transliterated stub.

Uzbek Cyrillic uses ў, ғ, қ, ҳ. The language-picker labels stay in their own scripts on
purpose: a Cyrillic reader still needs to recognise "Oʻzbekcha (lotin)" as an option.
"""


# character below is the correct letter for the language, not a Latin look-alike.


from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors ------------------------------------------------------------
    "error.generic": "Бизнинг томонда нимадир хато кетди. Бир оздан сўнг қайта уриниб кўринг.",
    "error.service_unavailable": "Хизмат вақтинча ишламаяпти. Кейинроқ уриниб кўринг.",
    "error.invalid_input": "Бу тўғри кўринмаяпти. Текшириб, қайтадан юборинг.",
    "error.content_not_allowed": (
        "Бундан қўшиқ ясай олмаймиз. Бошқача сўзлар билан уриниб кўринг."
    ),
    "error.provider_generic": "Студияда носозлик бўлди. Бир оздан сўнг қайта уриниб кўринг.",
    "error.provider_slow": (
        "Студия одатдагидан узоқроқ жавоб бераяпти. Бироздан сўнг уриниб кўринг."
    ),
    "error.provider_busy": "Студия ҳозир банд. Бир неча дақиқадан сўнг уриниб кўринг.",
    "error.name_pronunciation_best_effort": (
        "Талаффузни мукаммал қила олмадик, шунинг учун энг яхши вариантни юбордик."
    ),
    "error.delivery_failed": "Файлларни юбора олмадик. Қайтадан уриниб кўринг.",
    "error.payment_failed": "Тўлов амалга ошмади. Ҳеч қандай пул ечилмади.",
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 Салом! Мен шахсий табрик тўпламини тайёрлайман: битта қўшиқ ва қўшиқ "
        "матни — исм тўғри талаффуз қилинган ҳолда."
    ),
    "start.choose_ui_language": "Аввало, мен сиз билан қайси тилда гаплашай?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Нимани нишонлаяпмиз?",
    "wizard.genre.prompt": "Мусиқа услубини танланг.",
    "wizard.vocal_gender.prompt": "Ким куйласин?",
    "wizard.note.prompt": (
        "Улар ҳақида шахсий бирор нарсани айтинг — севимли машғулоти, ички ҳазил, лақаби. "
        "Ёки «Ўтказиб юбориш»ни босинг."
    ),
    "wizard.note.too_long": "Бироз узун бўлди. Илтимос, {limit} белгидан ошмасин.",
    "wizard.name.prompt": (
        "Энди табрик олувчининг исмини ўзингиз ёзадиган кўринишда ёзинг. "
        "Илтимос, ёзинг — овозли хабар юборманг."
    ),
    "wizard.name.invalid": "Менга ҳарфлар билан ёзилган исм керак. Илтимос, қайтадан ёзинг.",
    "wizard.name.too_long": "Бу исм жуда узун. Илтимос, {limit} белгидан ошмасин.",
    "wizard.name.too_many_words": (
        "Бу гапга ўхшайди. Илтимос, фақат исмни ёзинг — {limit} тагача сўз."
    ),
    "wizard.name.confirm": "Мен уни шундай ёзаман ва куйлайман:\n\n<b>{name}</b>\n\nТўғрими?",
    "wizard.name.unresolved": "Бу исмни ўқий олмадим. Илтимос, қайтадан ёзинг.",
    "wizard.output_language.prompt": "Қўшиқ қайси тилда бўлсин?",
    "wizard.lyrics.writing": "✍️ Қўшиқ матнини ёзаяпман… бу бир неча сония олади.",
    "wizard.lyrics.preview": (
        "<b>{title}</b>\n\n"
        "<pre>{lyrics}</pre>\n\n"
        "Шу матн қолсин десангиз ✅ ни, бошқасини кўрмоқчи бўлсангиз 🔄 ни босинг "
        "ёки ўз матнингизни хабар қилиб юборинг."
    ),
    "wizard.lyrics.failed": (
        "Қўшиқ матнини ёза олмадим. Бир оздан сўнг қайта уриниб кўринг."
    ),
    "wizard.lyrics.too_short": (
        "Бу қўшиқ учун қисқа. Илтимос, камида {limit} белги юборинг."
    ),
    "wizard.lyrics.too_long": (
        "Бу қўшиқ учун жуда узун. Илтимос, матн {limit} белгидан ошмасин."
    ),
    "wizard.lyrics.type_only": (
        "Илтимос, қўшиқ матнини матн кўринишида юборинг — овозли хабар бўлмайди."
    ),
    "wizard.lyrics.updated": "Қабул қилинди — сизнинг матнингиздан фойдаланаман.",
    "wizard.lyrics.too_many": (
        "Бу қўшиқ учун аллақачон {limit} та матн ёздим. "
        "Юқоридагисини қолдиринг ёки ўз матнингизни хабар қилиб юборинг."
    ),
    "wizard.confirm.summary": (
        "<b>Сизнинг тўпламингиз</b>\n"
        "Исм: <b>{name}</b>\n"
        "Сабаб: {occasion}\n"
        "Услуб: {genre}\n"
        "Овоз: {vocal_gender}\n"
        "Тил: {output_language}\n"
        "Изоҳ: {note}\n\n"
        "Бошлаймизми?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "Сессия тугади. Қайтадан бошлаш учун /start юборинг.",
    "wizard.cancelled": "Бекор қилинди. Тайёр бўлсангиз /start юборинг.",
    "wizard.queued": "🎬 Тўпламингиз студияда. Тайёр бўлиши билан шу ерга юбораман.",
    "wizard.enqueue_failed": (
        "Студияни ишга тушира олмадим. Бир оздан сўнг қайта уриниб кўринг."
    ),
    "wizard.payment_declined": "Буюртмани тасдиқлай олмадим. Ҳеч қандай тўлов олинмади.",
    "wizard.name.type_only": "Илтимос, исмни матн кўринишида ёзинг — овозли хабар бўлмайди.",
    "wizard.use_buttons": (
        "Илтимос, юқоридаги тугмалардан фойдаланинг ёки қайтадан бошлаш учун "
        "/start юборинг."
    ),
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Орқага",
    "button.skip": "Ўтказиб юбориш",
    "button.cancel": "Бекор қилиш",
    "button.confirm": "✅ Ҳа, бошлаймиз",
    "button.name_ok": "✅ Тўғри",
    "button.retype": "✏️ Қайтадан ёзиш",
    "button.lyrics_ok": "✅ Шу матн қолсин",
    "button.regenerate": "🔄 Бошқа матн ёзилсин",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "Туғилган кун",
    "occasion.anniversary": "Юбилей",
    "occasion.custom": "Бошқа сабаб",
    "genre.pop": "Поп",
    "genre.retro_estrada": "Ретро эстрада",
    "genre.hip_hop": "Хип-хоп",
    "genre.rock": "Рок",
    "genre.acoustic_ballad": "Акустик баллада",
    "genre.dance_electronic": "Рақс / электрон",
    "genre.uzbek_pop": "Ўзбек эстрадаси",
    "genre.uzbek_folk": "Ўзбек халқ қўшиғи",
    "genre.shashmaqom": "Шашмақом",
    "genre.jazz_lounge": "Жаз-лаунж",
    "vocal_gender.female": "Аёл овози",
    "vocal_gender.male": "Эркак овози",
    "vocal_gender.duet": "Дуэт",
    "vocal_gender.any": "Ҳар қандай овоз",
    "language.uz_latn": "Oʻzbekcha (lotin)",
    "language.uz_cyrl": "Ўзбекча (кирилл)",
    "language.ru": "Русский",
    "language.en": "English",
    # -- progress (keys mirror hbd.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": "🎬 Навбатда…",
    "progress.validating": "🔎 Маълумотларни текшираяпмиз…",
    "progress.moderating": "🛡 Матнни кўриб чиқаяпмиз…",
    "progress.writing_lyrics": "✍️ Қўшиқ матнини ёзаяпмиз…",
    "progress.writing_scripts": "📝 Табрик матнларини ёзаяпмиз…",
    "progress.authorizing": "🔐 Буюртмани тасдиқлаяпмиз…",
    "progress.composing_song": "🎼 Қўшиқни басталаяпмиз…",
    "progress.verifying_name": "🔍 Исм талаффузини текшираяпмиз…",
    "progress.rendering_greetings": "🎙 Овозли табрикларни ёзаяпмиз…",
    "progress.post_processing": "🎚 Овозни жилолаяпмиз…",
    "progress.persisting": "💾 Тўпламингизни сақлаяпмиз…",
    "progress.delivering": "📦 Тўпламни йиғаяпмиз…",
    "progress.done": "✅ Тайёр! Юборяпман.",
    "progress.failed": "❌ Бу буюртмани якунлай олмадик. Ҳеч қандай тўлов олинмади.",
    "progress.retrying_suffix": "({attempt}-уриниш)",
    "progress.degraded_suffix": "(имкон қадар)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 {title} — {name} учун",
    "delivery.greeting_caption": "🎙 {total} тадан {index}-табрик",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.done": "🎉 Бу {name} учун тўпламингиз. Яна биттаси учун /start юборинг.",
}
