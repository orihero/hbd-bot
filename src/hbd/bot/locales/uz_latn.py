"""Uzbek Latin catalogue — the default interface language.

This is the copy most customers actually read, so it is written as an original rather than
as a translation of ``en.py``. It still mirrors the reference key set, placeholder set and
HTML markup exactly: ``tests/test_bot/test_i18n.py`` asserts all three, because a dropped
``{name}`` loses the only personal word in a message and a stray tag is a 400 at send time.

Every ``oʻ`` and ``gʻ`` in this file uses U+02BB MODIFIER LETTER TURNED COMMA, which is the
correct Uzbek Latin orthography. Do not "fix" them to U+2018 or U+0027: this is the DISPLAY
layer, and display orthography is the half of the name subsystem the customer actually sees.
(U+02BC MODIFIER LETTER APOSTROPHE in ``Maʼlumot`` is a different letter and is correct.)

Three register decisions worth keeping. Buttons: this language inflates short English labels
(``Skip`` becomes ``Oʻtkazib yuborish``) and the nav row packs three of them, so anything
that lands on a button is kept as short as the grammar allows. Reassurance: exactly one
sentence is used everywhere a run fails — ``Hech narsa yoʻqolmadi.`` — and nothing anywhere
claims a charge was or was not taken, because this build has no payment rail and cannot
know. Voice: the bot is **men**, singular, in the progress bar and in failures exactly as in
``start.welcome`` — a first person that turns plural the moment work starts reads as a
different speaker.
"""

from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors (keys owned by hbd.errors) ---------------------------------
    "error.generic": "Mening tomonimda nimadir xato ketdi. Bir ozdan soʻng qayta urinib koʻring.",
    "error.service_unavailable": "Xizmat vaqtincha ishlamayapti. Keyinroq urinib koʻring.",
    "error.invalid_input": "Bu toʻgʻri koʻrinmayapti. Tekshirib, qaytadan yuboring.",
    "error.content_not_allowed": (
        "Bundan qoʻshiq yasay olmayman. Boshqacha soʻzlar bilan urinib koʻring."
    ),
    "error.provider_generic": "Studiyada nosozlik boʻldi. Bir ozdan soʻng qayta urinib koʻring.",
    "error.provider_slow": (
        "Studiya odatdagidan uzoqroq javob berayapti. Birozdan soʻng urinib koʻring."
    ),
    "error.provider_busy": "Studiya hozir band. Bir necha daqiqadan soʻng urinib koʻring.",
    "error.name_pronunciation_best_effort": (
        "Talaffuzni mukammal qila olmadim, shuning uchun eng yaqin variantni yubordim."
    ),
    "error.delivery_failed": (
        "❌ Qoʻshiq tayyor boʻldi, lekin uni shu yerga yetkaza olmadim. /support yuboring — "
        "qoʻshigʻingizni yetkazaman."
    ),
    "error.payment_failed": "Buyurtmani tasdiqlab boʻlmadi. Bir ozdan soʻng qayta urinib koʻring.",
    # Uchta limit rad javobi. Ishchi jarayon ularni parametrsiz yuboradi, shuning uchun
    # hech birida oʻrin egallovchi boʻlmasligi kerak: keyingi kredit sanasini faqat
    # tasdiqlash ekrani yuboradigan alohida ``credits.next_opens`` qatori olib boradi.
    "error.blocked": (
        "Bu hisob hozircha qoʻshiq buyurtma qila olmaydi. Buni odam qaror qilgan va odam "
        "bekor qila oladi — /support yuboring va menga ayting."
    ),
    "error.credits_exhausted": "Hozircha limitingizdagi barcha qoʻshiqlardan foydalandingiz.",
    "error.too_many_in_flight": (
        "Oldingi qoʻshigʻingiz hali tayyorlanmoqda. Tayyor boʻlishi bilan shu yerga "
        "yuboraman — shundan soʻng keyingisiga buyurtma bera olasiz."
    ),
    "error.too_fast": (
        "Bir vaqtda juda koʻp boʻldi — ulgurishim uchun bir oz kuting, soʻng qaytadan yuboring."
    ),
    # -- credits (davriy limit) --------------------------------------------
    "credits.next_opens": "Keyingi qoʻshiq {next_grant_at} kuni ochiladi.",
    # ``/balance`` va tasdiqlash ekranidagi qator. Ikkalasi ham hisoblagich ulangan VA
    # ``Settings.credits_enforced`` yoqilgan holdagina koʻrsatiladi: bayroq oʻchiq boʻlsa
    # sanoq yuritiladi, lekin hech kimga rad javobi berilmaydi, va "0 ta qoldi" mahsulot
    # bajarmaydigan raqam boʻlardi. Qolgan holatlarda halol javob —
    # ``credits.balance_none``.
    "credits.balance": (
        "🎵 Qolgan qoʻshiqlar: <b>{credits}</b>\n\n"
        "Limit — har {period_days} kunda {allowance} ta, u oʻzi yangilanadi: sotib "
        "olish ham, uzaytirish ham kerak emas."
    ),
    "credits.balance_none": (
        "🎵 Hozircha ishni endi boshlaganim uchun qoʻshiqlar bepul. Sizga hech qanday "
        "cheklov qoʻllanmayapti, shuning uchun koʻrsatadigan raqam ham yoʻq."
    ),
    # Hisoblagich ulangan boʻlsa, bayroqdan qatʼi nazar koʻrsatiladi: "bir vaqtda bitta
    # qoʻshiq" cheklovi birinchi kundan ishlaydi, aks holda balans "ha", tasdiqlash tugmasi
    # esa "yoʻq" degan boʻlardi.
    "credits.balance_in_flight": (
        "🎬 Qoʻshiqlaringizdan biri ayni damda tayyorlanmoqda. Keyingisini u shu yerga yetib "
        "kelishi bilan buyurtma qilsangiz boʻladi."
    ),
    "credits.confirm_note": (
        "<i>Bu qoʻshiq limitingizdan bittasini oladi. Hozir sizda: {credits}.</i>"
    ),
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 <b>Men bitta odam uchun bitta qoʻshiq yozaman — ismi aynan aytilishi kerak "
        "boʻlgandek kuylanadi.</b>\n\n"
        "Uslub va ovozni siz tanlaysiz, yozuvdan oldin esa soʻzlarni oʻzingiz oʻqib "
        "chiqasiz. Qoʻshiq va qoʻshiq matni shu yerga keladi."
    ),
    "start.choose_ui_language": "Avvalo — men siz bilan qaysi tilda gaplashay?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Nimani nishonlayapmiz?",
    "wizard.genre.prompt": "Qoʻshiq qanday yangrasin?",
    "wizard.vocal_gender.prompt": "Kim kuylasin?",
    "wizard.note.prompt": (
        "Bu odam haqida bitta narsani ayting — sevimli mashgʻuloti, eski hazil, faqat siz "
        "ishlatadigan laqab. Men uni soʻzlar ichiga kiritaman.\n\n"
        "Bir-ikki gap yetarli, {limit} belgigacha. Izohsiz ham davom etsa boʻladi."
    ),
    "wizard.note.privacy_line": ("<i>Izohni faqat qoʻshiqni yozib, yetkazguncha saqlayman.</i>"),
    "wizard.note.too_long": "Biroz uzun boʻldi. Iltimos, {limit} belgidan oshmasin.",
    "wizard.name.prompt": (
        "Endi ismini — oʻzingiz yozadigan koʻrinishda yozing. Qanday yozilsa, "
        "shunday kuylanadi.\n\n"
        "Matn qilib yozing, {limit} belgigacha. Ovozli xabar boʻlmaydi."
    ),
    "wizard.name.invalid": "Menga harflar bilan yozilgan ism kerak. Iltimos, qaytadan yozing.",
    "wizard.name.too_long": "Bu ism juda uzun. Iltimos, {limit} belgidan oshmasin.",
    "wizard.name.too_many_words": (
        "Bu gapga oʻxshaydi. Iltimos, faqat ismni yozing — {limit} tagacha soʻz."
    ),
    "wizard.name.confirm": (
        "Men uni shunday kuylayman:\n"
        "<blockquote><b>{name}</b></blockquote>\n"
        "Talaffuzni yozilishi hal qiladi, shuning uchun yana bir bor koʻrib chiqishga "
        "arziydi. Qoʻshiq yozilgach, shu soʻzni tinglab koʻraman va notoʻgʻri chiqqan "
        "boʻlsa, qaytadan yozaman.\n\n"
        "Toʻgʻrimi?"
    ),
    "wizard.name.unresolved": "Bu ismni oʻqiy olmadim. Iltimos, qaytadan yozing.",
    "wizard.output_language.prompt": "{name} uchun qoʻshiq qaysi tilda boʻlsin?",
    "wizard.output_language.prompt_noname": "Qoʻshiq qaysi tilda boʻlsin?",
    "wizard.lyrics.writing": ("✍️ {name} uchun soʻzlarni yozayapman… bu bir daqiqagacha oladi."),
    "wizard.lyrics.preview": (
        "<b>{title}</b>\n"
        "<blockquote expandable>{lyrics}</blockquote>\n"
        "Aynan shu soʻzlar kuylanadi. Hali hech narsa yozib olinmadi — shuni qoldiring, "
        "boshqasini soʻrang yoki oʻz matningizni xabar qilib yuboring."
    ),
    "wizard.lyrics.failed": (
        "❌ Bu safar soʻzlar chiqmadi. Hech narsa yoʻqolmadi — boshqa matn yozib bera "
        "olaman yoki oʻz matningizni xabar qilib yuboring."
    ),
    "wizard.lyrics.too_short": ("Bu qoʻshiq uchun qisqa. Iltimos, kamida {limit} belgi yuboring."),
    "wizard.lyrics.too_long": (
        "Bu qoʻshiq uchun juda uzun. Iltimos, matn {limit} belgidan oshmasin."
    ),
    "wizard.lyrics.type_only": (
        "Iltimos, qoʻshiq matnini matn koʻrinishida yuboring — ovozli xabar boʻlmaydi."
    ),
    "wizard.lyrics.updated": "Qabul qilindi — soʻzlaringizni siz yozgandek kuylayman.",
    "wizard.lyrics.too_many": (
        "Bu qoʻshiq uchun allaqachon {limit} ta matn yozdim. "
        "Yuqoridagisini qoldiring yoki oʻz matningizni xabar qilib yuboring."
    ),
    # Hisob boʻyicha KUNLIK cheklov — bitta qoralama chekloviidan yuqori qavat. Buni faqat
    # matn ekranining oʻzi yuboradi, ishchi jarayon emas, shuning uchun oʻrin egallovchi
    # boʻlishi mumkin, va ikkitasi kerak: cheklovning oʻzi (hisoblagich emas — rad etilgan
    # urinish ham sanaladi) va u qachon ochilishi.
    "wizard.lyrics.budget_spent": (
        "Bu hisob uchun bir kunda ruxsat etilgan qadar matn yozib boʻldim ({limit}). "
        "Keyingisini {resets_at} kuni yozsam boʻladi."
    ),
    "wizard.confirm.summary": (
        "<b>{name} uchun qoʻshiq</b>\n"
        "🎂 {occasion}\n"
        "🎼 {genre}\n"
        "🎙️ {vocal_gender}\n"
        "🌐 {output_language}\n"
        "✍️ {note}\n\n"
        "Soʻzlar tayyor. Endi yozib olaman, soʻng ismni quloq bilan tekshiraman.\n\n"
        "Boshlaymizmi?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "Bu sessiya yopildi. Qaytadan boshlashimiz mumkin.",
    "wizard.cancelled": "Bekor qilindi — hech narsa yasalmadi va hech narsa saqlanmadi.",
    "wizard.cancel_too_late": (
        "{name} uchun qoʻshiq allaqachon studiyada, endi uni toʻxtata olmayman — tez orada "
        "shu yerga keladi. Agar unda nimadir notoʻgʻri boʻlsa, /support yuboring."
    ),
    "wizard.queued": (
        "🎬 Hamon studiyada. {name} uchun qoʻshiq tayyor boʻlishi bilan shu yerga keladi — "
        "bu ekranda kutib turish shart emas."
    ),
    "wizard.still_in_studio": (
        "🎬 Qoʻshigʻingiz hamon studiyada, endi uni toʻxtata olmayman — tayyor boʻlishi "
        "bilan shu yerga keladi."
    ),
    "wizard.enqueue_failed": (
        "❌ Buni studiyaga topshira olmadim. Hech narsa yoʻqolmadi — qaytadan boshlashimiz mumkin."
    ),
    "wizard.payment_declined": (
        "Bu buyurtmani tasdiqlay olmadim. Hech narsa yasalmadi — qaytadan boshlashimiz mumkin."
    ),
    "wizard.name.type_only": "Iltimos, ismni matn koʻrinishida yozing — ovozli xabar boʻlmaydi.",
    "wizard.use_buttons": "Iltimos, bunga yuqoridagi tugmalar orqali javob bering.",
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Orqaga",
    "button.skip": "Oʻtkazib yuborish",
    "button.cancel": "Bekor qilish",
    "button.confirm": "🎬 Yozib olinsin",
    "button.name_ok": "✅ Ha, shunday",
    "button.retype": "✏️ Qaytadan yozish",
    "button.lyrics_ok": "✅ Shu matn qolsin",
    "button.regenerate": "🔄 Boshqa matn yozilsin",
    "button.start_over": "↩️ Qaytadan boshlash",
    "button.make_another": "🎂 Yana bittasi",
    "button.report_problem": "⚠️ Nimadir notoʻgʻri",
    "button.keep_note": "✅ Izoh qolsin",
    "button.try_again": "🔄 Qayta urinish",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "Tugʻilgan kun",
    "occasion.anniversary": "Yubiley",
    "occasion.custom": "Boshqa sabab",
    "genre.pop": "Pop",
    "genre.retro_estrada": "Retro estrada",
    "genre.hip_hop": "Xip-xop",
    "genre.rock": "Rok",
    "genre.acoustic_ballad": "Akustik ballada",
    "genre.dance_electronic": "Raqs / elektron",
    "genre.uzbek_pop": "Oʻzbek estradasi",
    "genre.uzbek_folk": "Oʻzbek xalq qoʻshigʻi",
    "genre.shashmaqom": "Shashmaqom",
    "genre.jazz_lounge": "Jaz-launj",
    "vocal_gender.female": "Ayol ovozi",
    "vocal_gender.male": "Erkak ovozi",
    "vocal_gender.duet": "Duet",
    "vocal_gender.any": "Har qanday ovoz",
    "language.uz_latn": "Oʻzbekcha (lotin)",
    "language.uz_cyrl": "Ўзбекча (кирилл)",
    "language.ru": "Русский",
    "language.en": "English",
    # -- progress (keys mirror hbd.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": (
        "🎬 {name} uchun qoʻshiq studiyada. Telegramni yopsangiz ham boʻladi — "
        "tayyor boʻlgach shu yerga keladi."
    ),
    "progress.validating": "🔎 Maʼlumotlarni tekshirayapman…",
    "progress.moderating": "🛡️ Matnni koʻrib chiqayapman…",
    "progress.writing_lyrics": "✍️ Qoʻshiq matnini yozayapman…",
    "progress.writing_scripts": "📝 Tabrik matnlarini yozayapman…",
    "progress.authorizing": "🔐 Buyurtmani tasdiqlayapman…",
    "progress.composing_song": "🎼 Qoʻshiqni bastalayapman…",
    "progress.verifying_name": "🔍 Ism qanday kuylanganini tinglayapman…",
    "progress.rendering_greetings": "🎙️ Ovozli tabriklarni yozayapman…",
    "progress.post_processing": "🎚️ Telefonda yaxshi eshitilishi uchun ovozni sozlayapman…",
    "progress.persisting": "💾 Qoʻshiqni saqlayapman…",
    "progress.delivering": "📦 Yuborishga yigʻayapman…",
    "progress.done": "✅ Tayyor — hozir yuboraman.",
    "progress.failed": "❌ Bu qoʻshiq yigʻilmadi. Hech narsa yoʻqolmadi.",
    "progress.timed_out": (
        "❌ Bu juda uzoq davom etdi, shuning uchun toʻxtatdim. Quyidan qaytadan boshlang, "
        "takrorlansa /support yuboring."
    ),
    "progress.retrying_suffix": "({attempt}-urinish)",
    "progress.degraded_suffix": "(imkon qadar)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": (
        "🎵 <b>{title}</b>\n{name} uchun yozildi va kuylandi. Ovozni yoqing."
    ),
    "delivery.greeting_caption": "🎙️ {total} tadan {index}-tabrik",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.lyric_sheet_part": "📄 <b>{title}</b> — {part}/{total}\n\n{body}",
    "delivery.done": (
        "🎉 Mana {name} uchun qoʻshiq — endi yuborsangiz boʻladi.\n\n"
        "Audioni toʻgʻridan-toʻgʻri oʻzlariga yoʻllang — u suhbat ichida ijro etiladi, "
        "hech narsani yuklab olish shart emas.\n\n"
        "Buyurtma <code>{order_ref}</code> — biz bilan bogʻlanish kerak boʻlsa, "
        "saqlab qoʻying.\n\n"
        "Navbat kimga?"
    ),
    "delivery.done_degraded": (
        "⚠️ {name} uchun qoʻshiq tayyor, lekin jarayon silliq oʻtmadi — nima "
        "yetishmayotgani quyida yozilgan. Buning uchun uzr soʻrayman.\n\n"
        "Buyurtma <code>{order_ref}</code>. Shu raqam bilan /support yuboring, bu "
        "jarayonni koʻrib chiqaman."
    ),
    # -- gaps (appended to the closing message; never a retry instruction) --
    "gap.name_best_effort": (
        "Ism haqida: siz eshitayotganingiz — uning aytilishiga eng yaqin variantim, mukammali emas."
    ),
    "gap.greeting_missing": "Ovozli tabriklardan biri chiqmadi, shuning uchun u bu yerda yoʻq.",
    # -- commands ----------------------------------------------------------
    "help.text": (
        "🎂 Men bitta odam uchun bitta qoʻshiq yozaman va kuylayman — ismi toʻgʻri "
        "talaffuz bilan.\n\n"
        "🎬 /start — qoʻshiq yasash\n"
        "❌ /cancel — tayyorlanayotganini toʻxtatish\n"
        "📄 /help — shu roʻyxat\n"
        "🎵 /balance — limitingizda nechta qoʻshiq qolgani\n"
        "🔒 /privacy — nimani va qancha saqlayman\n"
        "✉️ /support — nimadir notoʻgʻri ketganini aytish\n"
        "🗑️ /forget — siz uchun saqlab turgan qoʻshigʻimni oʻchirish\n\n"
        "Olgan qoʻshigʻingizda muammo bormi? Uning yakuniy xabaridagi buyurtma raqami "
        "bilan /support yuboring."
    ),
    "privacy.text": (
        "🔒 <b>Nimani va qancha saqlayman</b>\n\n"
        "🎙️ Siz bergan ism: {recipient_identity_days} kun\n"
        "✍️ Siz yozgan izoh: {brief_text_days} kun\n"
        "🎵 Tayyor qoʻshiq va qoʻshiq matni: {paid_audio_days} kun\n"
        "🎬 Boshlangan, lekin tugallanmagan qoʻshiq: {abandoned_draft_days} kun\n"
        "🧾 Yasalgan qoʻshiqlar va sarflangan limit yozuvi: muddatsiz\n"
        "✍️ Bugun matn necha marta yozilgani sanogʻi: keyingi yozuvingizgacha\n\n"
        "Muddati bor narsaning hammasi qoʻlda emas, jadval boʻyicha oʻchiriladi. Yozuv — "
        "ataylab qoldirilgan istisno: oylar oʻtib ham qoʻshiqlaringiz haqidagi savolga aynan "
        "u javob bera oladi, shuning uchun /forget undan hisob raqamingizni olib tashlaydi va "
        "sanoqning oʻzini qoldiradi, kvitansiyani oʻchirmaydi. Kunlik yozuv sanogʻida hisob "
        "raqamingiz ham qoladi — aynan u bir odamning kun boʻyi yozishiga yoʻl qoʻymaydi — "
        "va keyingi safar yozganingizda ustiga yoziladi.\n\n"
        "/forget yuborsangiz, hozir ustida ishlayotgan qoʻshigʻingiz darhol oʻchadi; "
        "studiyaga allaqachon yuborilganiga esa yuqoridagi muddatlar qoladi.\n\n"
        "Qoʻshiq yasamoqchi boʻlsangiz, /start yuboring."
    ),
    "privacy.forgotten": (
        "✅ Oʻchirildi. Ustida ishlayotgan qoʻshigʻingiz — ism, izoh, soʻzlar — mening "
        "tomonimda qolmadi, buni ortga qaytarib boʻlmaydi.\n\n"
        "Yasalgan qoʻshiqlar yozuvi ham endi siz bilan bogʻliq emas: sanoq qoladi, hisob "
        "raqamingiz esa yoʻq. Shu bilan birga joriy davrda qolgan qoʻshiqlar ham "
        "kuyadi: keyingilari davr almashganda ochiladi.\n\n"
        "Studiyaga allaqachon yuborilgan qoʻshiq /privacy dagi jadval boʻyicha oʻchiriladi.\n\n"
        "Yana qoʻshiq xohlaganingizda, quyidan qaytadan boshlang."
    ),
    "support.no_contact": (
        "✉️ Nima notoʻgʻri ketganini shu yerda ayting — shu chatga javob yozsangiz "
        "kifoya.\n\n"
        "Qoʻshiq ostidagi yakuniy xabardagi buyurtma raqamini ham qoʻshing, shunda aynan "
        "qaysi jarayon boʻlganini topaman."
    ),
    "support.text": (
        "✉️ {contact} manziliga yozing.\n\n"
        "Qoʻshiq ostidagi yakuniy xabardagi buyurtma raqamini ham qoʻshing — u bilan aynan "
        "qaysi jarayon boʻlganini topib, nima notoʻgʻri ketganini koʻramiz."
    ),
}
