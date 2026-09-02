"""Uzbek Cyrillic catalogue — a full first-class locale, not a transliterated stub.

This is the same language as ``uz_latn.py`` in the other script, so it is deliberately a
MIRROR of that file rather than an independent translation of ``en.py``: same sentence
shapes, same register, same reassurance wording. Two catalogues of one language that drift
apart read as two different products to anyone who switches script mid-flow.

It mirrors the reference key set, placeholder set and HTML markup exactly:
``tests/test_bot/test_i18n.py`` asserts all three, because a dropped ``{name}`` loses the
only personal word in a message and a stray tag is a 400 at send time.

Orthography: Uzbek Cyrillic ў, ғ, қ, ҳ — never the Russian look-alikes у, г, к, х. These are
distinct letters, not decoration, and swapping one is a spelling error to a native reader.
The language-picker labels stay in their own scripts on purpose: a Cyrillic reader still
needs to recognise "Oʻzbekcha (lotin)" as an option.

The three register decisions carried over from ``uz_latn.py``. Buttons: this language
inflates short English labels (``Skip`` becomes ``Ўтказиб юбориш``) and the nav row packs
three of them, so anything on a button is kept as short as the grammar allows. Reassurance:
exactly one sentence wherever a run fails — ``Ҳеч нарса йўқолмади.`` — and nothing anywhere
claims a charge was or was not taken, because this build has no payment rail and cannot
know. Voice: the bot is **мен**, singular, in the progress bar and in failures exactly as in
``start.welcome``.
"""

from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors (keys owned by hbd.errors) ---------------------------------
    "error.generic": ("Менинг томонимда нимадир хато кетди. Бир оздан сўнг қайта уриниб кўринг."),
    "error.service_unavailable": "Хизмат вақтинча ишламаяпти. Кейинроқ уриниб кўринг.",
    "error.invalid_input": "Бу тўғри кўринмаяпти. Текшириб, қайтадан юборинг.",
    "error.content_not_allowed": (
        "Бундан қўшиқ ясай олмайман. Бошқача сўзлар билан уриниб кўринг."
    ),
    "error.provider_generic": "Студияда носозлик бўлди. Бир оздан сўнг қайта уриниб кўринг.",
    "error.provider_slow": (
        "Студия одатдагидан узоқроқ жавоб бераяпти. Бироздан сўнг уриниб кўринг."
    ),
    "error.provider_busy": "Студия ҳозир банд. Бир неча дақиқадан сўнг уриниб кўринг.",
    "error.name_pronunciation_best_effort": (
        "Талаффузни мукаммал қила олмадим, шунинг учун энг яқин вариантни юбордим."
    ),
    "error.delivery_failed": (
        "❌ Қўшиқ тайёр бўлди, лекин уни шу ерга етказа олмадим. /support юборинг — "
        "қўшиғингизни етказаман."
    ),
    "error.payment_failed": ("Буюртмани тасдиқлаб бўлмади. Бир оздан сўнг қайта уриниб кўринг."),
    # Учта лимит рад жавоби. Ишчи жараён уларни параметрсиз юборади, шунинг учун
    # ҳеч бирида ўрин эгалловчи бўлмаслиги керак: кейинги кредит санасини фақат
    # тасдиқлаш экрани юборадиган алоҳида ``credits.next_opens`` қатори олиб боради.
    "error.blocked": (
        "Бу ҳисоб ҳозирча қўшиқ буюртма қила олмайди. Буни одам қарор қилган ва одам "
        "бекор қила олади — /support юборинг ва менга айтинг."
    ),
    "error.credits_exhausted": "Ҳозирча лимитингиздаги барча қўшиқлардан фойдаландингиз.",
    "error.too_many_in_flight": (
        "Олдинги қўшиғингиз ҳали тайёрланмоқда. Тайёр бўлиши билан шу ерга юбораман — "
        "шундан сўнг кейингисига буюртма бера оласиз."
    ),
    "error.too_fast": (
        "Бир вақтда жуда кўп бўлди — улгуришим учун бир оз кутинг, сўнг қайтадан юборинг."
    ),
    # -- credits (даврий лимит) --------------------------------------------
    "credits.next_opens": "Кейинги қўшиқ {next_grant_at} куни очилади.",
    # ``/balance`` ва тасдиқлаш экранидаги қатор. Иккаласи ҳам ҳисоблагич уланган ВА
    # ``Settings.credits_enforced`` ёқилган ҳолдагина кўрсатилади: байроқ ўчиқ бўлса
    # саноқ юритилади, лекин ҳеч кимга рад жавоби берилмайди, ва "0 та қолди" маҳсулот
    # бажармайдиган рақам бўларди. Қолган ҳолатларда ҳалол жавоб —
    # ``credits.balance_none``.
    "credits.balance": (
        "🎵 Қолган қўшиқлар: <b>{credits}</b>\n\n"
        "Лимит — ҳар {period_days} кунда {allowance} та, у ўзи янгиланади: сотиб олиш "
        "ҳам, узайтириш ҳам керак эмас."
    ),
    "credits.balance_none": (
        "🎵 Ҳозирча ишни энди бошлаганим учун қўшиқлар бепул. Сизга ҳеч қандай чеклов "
        "қўлланмаяпти, шунинг учун кўрсатадиган рақам ҳам йўқ."
    ),
    # Ҳисоблагич уланган бўлса, байроқдан қатъи назар кўрсатилади: "бир вақтда битта қўшиқ"
    # чеклови биринчи кундан ишлайди, акс ҳолда баланс "ҳа", тасдиқлаш тугмаси эса "йўқ"
    # деган бўларди.
    "credits.balance_in_flight": (
        "🎬 Қўшиқларингиздан бири айни дамда тайёрланмоқда. Кейингисини у шу ерга етиб "
        "келиши билан буюртма қилсангиз бўлади."
    ),
    "credits.confirm_note": (
        "<i>Бу қўшиқ лимитингиздан биттасини олади. Ҳозир сизда: {credits}.</i>"
    ),
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 <b>Мен битта одам учун битта қўшиқ ёзаман — исми айнан айтилиши керак "
        "бўлгандек куйланади.</b>\n\n"
        "Услуб ва овозни сиз танлайсиз, ёзувдан олдин эса сўзларни ўзингиз ўқиб "
        "чиқасиз. Қўшиқ ва қўшиқ матни шу ерга келади."
    ),
    "start.choose_ui_language": "Аввало — мен сиз билан қайси тилда гаплашай?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Нимани нишонлаяпмиз?",
    "wizard.genre.prompt": "Қўшиқ қандай янграсин?",
    "wizard.vocal_gender.prompt": "Ким куйласин?",
    "wizard.note.prompt": (
        "Бу одам ҳақида битта нарсани айтинг — севимли машғулоти, эски ҳазил, фақат сиз "
        "ишлатадиган лақаб. Мен уни сўзлар ичига киритаман.\n\n"
        "Бир-икки гап етарли, {limit} белгигача. Изоҳсиз ҳам давом этса бўлади."
    ),
    "wizard.note.privacy_line": "<i>Изоҳни фақат қўшиқни ёзиб, етказгунча сақлайман.</i>",
    "wizard.note.too_long": "Бироз узун бўлди. Илтимос, {limit} белгидан ошмасин.",
    "wizard.name.prompt": (
        "Энди исмини — ўзингиз ёзадиган кўринишда ёзинг. Қандай ёзилса, "
        "шундай куйланади.\n\n"
        "Матн қилиб ёзинг, {limit} белгигача. Овозли хабар бўлмайди."
    ),
    "wizard.name.invalid": "Менга ҳарфлар билан ёзилган исм керак. Илтимос, қайтадан ёзинг.",
    "wizard.name.too_long": "Бу исм жуда узун. Илтимос, {limit} белгидан ошмасин.",
    "wizard.name.too_many_words": (
        "Бу гапга ўхшайди. Илтимос, фақат исмни ёзинг — {limit} тагача сўз."
    ),
    "wizard.name.confirm": (
        "Мен уни шундай куйлайман:\n"
        "<blockquote><b>{name}</b></blockquote>\n"
        "Талаффузни ёзилиши ҳал қилади, шунинг учун яна бир бор кўриб чиқишга "
        "арзийди. Қўшиқ ёзилгач, шу сўзни тинглаб кўраман ва нотўғри чиққан "
        "бўлса, қайтадан ёзаман.\n\n"
        "Тўғрими?"
    ),
    "wizard.name.unresolved": "Бу исмни ўқий олмадим. Илтимос, қайтадан ёзинг.",
    "wizard.output_language.prompt": "{name} учун қўшиқ қайси тилда бўлсин?",
    "wizard.output_language.prompt_noname": "Қўшиқ қайси тилда бўлсин?",
    "wizard.lyrics.writing": "✍️ {name} учун сўзларни ёзаяпман… бу бир дақиқагача олади.",
    "wizard.lyrics.preview": (
        "<b>{title}</b>\n"
        "<blockquote expandable>{lyrics}</blockquote>\n"
        "Айнан шу сўзлар куйланади. Ҳали ҳеч нарса ёзиб олинмади — шуни қолдиринг, "
        "бошқасини сўранг ёки ўз матнингизни хабар қилиб юборинг."
    ),
    "wizard.lyrics.failed": (
        "❌ Бу сафар сўзлар чиқмади. Ҳеч нарса йўқолмади — бошқа матн ёзиб бера "
        "оламан ёки ўз матнингизни хабар қилиб юборинг."
    ),
    "wizard.lyrics.too_short": "Бу қўшиқ учун қисқа. Илтимос, камида {limit} белги юборинг.",
    "wizard.lyrics.too_long": ("Бу қўшиқ учун жуда узун. Илтимос, матн {limit} белгидан ошмасин."),
    "wizard.lyrics.type_only": (
        "Илтимос, қўшиқ матнини матн кўринишида юборинг — овозли хабар бўлмайди."
    ),
    "wizard.lyrics.updated": "Қабул қилинди — сўзларингизни сиз ёзгандек куйлайман.",
    "wizard.lyrics.too_many": (
        "Бу қўшиқ учун аллақачон {limit} та матн ёздим. "
        "Юқоридагисини қолдиринг ёки ўз матнингизни хабар қилиб юборинг."
    ),
    # Ҳисоб бўйича КУНЛИК чеклов — битта қоралама чекловидан юқори қават. Буни фақат матн
    # экранининг ўзи юборади, ишчи жараён эмас, шунинг учун ўрин эгалловчи бўлиши мумкин,
    # ва иккитаси керак: чекловнинг ўзи (ҳисоблагич эмас — рад этилган уриниш ҳам
    # саналади) ва у қачон очилиши.
    "wizard.lyrics.budget_spent": (
        "Бу ҳисоб учун бир кунда рухсат этилган қадар матн ёзиб бўлдим ({limit}). "
        "Кейингисини {resets_at} куни ёзсам бўлади."
    ),
    "wizard.confirm.summary": (
        "<b>{name} учун қўшиқ</b>\n"
        "🎂 {occasion}\n"
        "🎼 {genre}\n"
        "🎙️ {vocal_gender}\n"
        "🌐 {output_language}\n"
        "✍️ {note}\n\n"
        "Сўзлар тайёр. Энди ёзиб оламан, сўнг исмни қулоқ билан текшираман.\n\n"
        "Бошлаймизми?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "Бу сессия ёпилди. Қайтадан бошлашимиз мумкин.",
    "wizard.cancelled": "Бекор қилинди — ҳеч нарса ясалмади ва ҳеч нарса сақланмади.",
    "wizard.cancel_too_late": (
        "{name} учун қўшиқ аллақачон студияда, энди уни тўхтата олмайман — тез орада "
        "шу ерга келади. Агар унда нимадир нотўғри бўлса, /support юборинг."
    ),
    "wizard.queued": (
        "🎬 Ҳамон студияда. {name} учун қўшиқ тайёр бўлиши билан шу ерга келади — "
        "бу экранда кутиб туриш шарт эмас."
    ),
    "wizard.still_in_studio": (
        "🎬 Қўшиғингиз ҳамон студияда, энди уни тўхтата олмайман — тайёр бўлиши "
        "билан шу ерга келади."
    ),
    "wizard.enqueue_failed": (
        "❌ Буни студияга топшира олмадим. Ҳеч нарса йўқолмади — қайтадан бошлашимиз мумкин."
    ),
    "wizard.payment_declined": (
        "Бу буюртмани тасдиқлай олмадим. Ҳеч нарса ясалмади — қайтадан бошлашимиз мумкин."
    ),
    "wizard.name.type_only": "Илтимос, исмни матн кўринишида ёзинг — овозли хабар бўлмайди.",
    "wizard.use_buttons": "Илтимос, бунга юқоридаги тугмалар орқали жавоб беринг.",
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Орқага",
    "button.skip": "Ўтказиб юбориш",
    "button.cancel": "Бекор қилиш",
    "button.confirm": "🎬 Ёзиб олинсин",
    "button.name_ok": "✅ Ҳа, шундай",
    "button.retype": "✏️ Қайтадан ёзиш",
    "button.lyrics_ok": "✅ Шу матн қолсин",
    "button.regenerate": "🔄 Бошқа матн ёзилсин",
    "button.start_over": "↩️ Қайтадан бошлаш",
    "button.make_another": "🎂 Яна биттаси",
    "button.report_problem": "⚠️ Нимадир нотўғри",
    "button.keep_note": "✅ Изоҳ қолсин",
    "button.try_again": "🔄 Қайта уриниш",
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
    "progress.queued": (
        "🎬 {name} учун қўшиқ студияда. Телеграмни ёпсангиз ҳам бўлади — "
        "тайёр бўлгач шу ерга келади."
    ),
    "progress.validating": "🔎 Маълумотларни текшираяпман…",
    "progress.moderating": "🛡️ Матнни кўриб чиқаяпман…",
    "progress.writing_lyrics": "✍️ Қўшиқ матнини ёзаяпман…",
    "progress.writing_scripts": "📝 Табрик матнларини ёзаяпман…",
    "progress.authorizing": "🔐 Буюртмани тасдиқлаяпман…",
    "progress.composing_song": "🎼 Қўшиқни басталаяпман…",
    "progress.verifying_name": "🔍 Исм қандай куйланганини тинглаяпман…",
    "progress.rendering_greetings": "🎙️ Овозли табрикларни ёзаяпман…",
    "progress.post_processing": "🎚️ Телефонда яхши эшитилиши учун овозни созлаяпман…",
    "progress.persisting": "💾 Қўшиқни сақлаяпман…",
    "progress.delivering": "📦 Юборишга йиғаяпман…",
    "progress.done": "✅ Тайёр — ҳозир юбораман.",
    "progress.failed": "❌ Бу қўшиқ йиғилмади. Ҳеч нарса йўқолмади.",
    "progress.timed_out": (
        "❌ Бу жуда узоқ давом этди, шунинг учун тўхтатдим. Қуйидан қайтадан бошланг, "
        "такрорланса /support юборинг."
    ),
    "progress.retrying_suffix": "({attempt}-уриниш)",
    "progress.degraded_suffix": "(имкон қадар)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 <b>{title}</b>\n{name} учун ёзилди ва куйланди. Овозни ёқинг.",
    "delivery.greeting_caption": "🎙️ {total} тадан {index}-табрик",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.lyric_sheet_part": "📄 <b>{title}</b> — {part}/{total}\n\n{body}",
    "delivery.done": (
        "🎉 Мана {name} учун қўшиқ — энди юборсангиз бўлади.\n\n"
        "Аудиони тўғридан-тўғри ўзларига йўлланг — у суҳбат ичида ижро этилади, "
        "ҳеч нарсани юклаб олиш шарт эмас.\n\n"
        "Буюртма <code>{order_ref}</code> — биз билан боғланиш керак бўлса, "
        "сақлаб қўйинг.\n\n"
        "Навбат кимга?"
    ),
    "delivery.done_degraded": (
        "⚠️ {name} учун қўшиқ тайёр, лекин жараён силлиқ ўтмади — нима "
        "етишмаётгани қуйида ёзилган. Бунинг учун узр сўрайман.\n\n"
        "Буюртма <code>{order_ref}</code>. Шу рақам билан /support юборинг, бу "
        "жараённи кўриб чиқаман."
    ),
    # -- gaps (appended to the closing message; never a retry instruction) --
    "gap.name_best_effort": (
        "Исм ҳақида: сиз эшитаётганингиз — унинг айтилишига энг яқин вариантим, мукаммали эмас."
    ),
    "gap.greeting_missing": "Овозли табриклардан бири чиқмади, шунинг учун у бу ерда йўқ.",
    # -- commands ----------------------------------------------------------
    "help.text": (
        "🎂 Мен битта одам учун битта қўшиқ ёзаман ва куйлайман — исми тўғри "
        "талаффуз билан.\n\n"
        "🎬 /start — қўшиқ ясаш\n"
        "❌ /cancel — тайёрланаётганини тўхтатиш\n"
        "📄 /help — шу рўйхат\n"
        "🎵 /balance — лимитингизда нечта қўшиқ қолгани\n"
        "🔒 /privacy — нимани ва қанча сақлайман\n"
        "✉️ /support — нимадир нотўғри кетганини айтиш\n"
        "🗑️ /forget — сиз учун сақлаб турган қўшиғимни ўчириш\n\n"
        "Олган қўшиғингизда муаммо борми? Унинг якуний хабаридаги буюртма рақами "
        "билан /support юборинг."
    ),
    "privacy.text": (
        "🔒 <b>Нимани ва қанча сақлайман</b>\n\n"
        "🎙️ Сиз берган исм: {recipient_identity_days} кун\n"
        "✍️ Сиз ёзган изоҳ: {brief_text_days} кун\n"
        "🎵 Тайёр қўшиқ ва қўшиқ матни: {paid_audio_days} кун\n"
        "🎬 Бошланган, лекин тугалланмаган қўшиқ: {abandoned_draft_days} кун\n"
        "🧾 Ясалган қўшиқлар ва сарфланган лимит ёзуви: муддатсиз\n"
        "✍️ Бугун матн неча марта ёзилгани саноғи: кейинги ёзувингизгача\n\n"
        "Муддати бор нарсанинг ҳаммаси қўлда эмас, жадвал бўйича ўчирилади. Ёзув — атайлаб "
        "қолдирилган истисно: ойлар ўтиб ҳам қўшиқларингиз ҳақидаги саволга айнан у жавоб "
        "бера олади, шунинг учун /forget ундан ҳисоб рақамингизни олиб ташлайди ва "
        "саноқнинг ўзини қолдиради, квитанцияни ўчирмайди. Кунлик ёзув саноғида ҳисоб "
        "рақамингиз ҳам қолади — айнан у бир одамнинг кун бўйи ёзишига йўл қўймайди — "
        "ва кейинги сафар ёзганингизда устига ёзилади.\n\n"
        "/forget юборсангиз, ҳозир устида ишлаётган қўшиғингиз дарҳол ўчади; студияга "
        "аллақачон юборилганига эса юқоридаги муддатлар қолади.\n\n"
        "Қўшиқ ясамоқчи бўлсангиз, /start юборинг."
    ),
    "privacy.forgotten": (
        "✅ Ўчирилди. Устида ишлаётган қўшиғингиз — исм, изоҳ, сўзлар — менинг "
        "томонимда қолмади, буни ортга қайтариб бўлмайди.\n\n"
        "Ясалган қўшиқлар ёзуви ҳам энди сиз билан боғлиқ эмас: саноқ қолади, ҳисоб "
        "рақамингиз эса йўқ. Шу билан бирга жорий даврда қолган қўшиқлар ҳам "
        "куяди: кейингилари давр алмашганда очилади.\n\n"
        "Студияга аллақачон юборилган қўшиқ /privacy даги жадвал бўйича ўчирилади.\n\n"
        "Яна қўшиқ хоҳлаганингизда, қуйидан қайтадан бошланг."
    ),
    "support.no_contact": (
        "✉️ Нима нотўғри кетганини шу ерда айтинг — шу чатга жавоб ёзсангиз кифоя.\n\n"
        "Қўшиқ остидаги якуний хабардаги буюртма рақамини ҳам қўшинг, шунда айнан "
        "қайси жараён бўлганини топаман."
    ),
    "support.text": (
        "✉️ {contact} манзилига ёзинг.\n\n"
        "Қўшиқ остидаги якуний хабардаги буюртма рақамини ҳам қўшинг — у билан айнан "
        "қайси жараён бўлганини топиб, нима нотўғри кетганини кўрамиз."
    ),
}
