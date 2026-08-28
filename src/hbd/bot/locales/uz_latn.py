"""Uzbek Latin catalogue — the default interface language.

Every ``oʻ`` and ``gʻ`` in this file uses U+02BB MODIFIER LETTER TURNED COMMA, which is the
correct Uzbek Latin orthography. Do not "fix" them to U+2018 or U+0027: this is the DISPLAY
layer, and display orthography is the half of the name subsystem the customer actually sees.
"""

from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors ------------------------------------------------------------
    "error.generic": "Bizning tomonda nimadir xato ketdi. Bir ozdan soʻng qayta urinib koʻring.",
    "error.service_unavailable": "Xizmat vaqtincha ishlamayapti. Keyinroq urinib koʻring.",
    "error.invalid_input": "Bu toʻgʻri koʻrinmayapti. Tekshirib, qaytadan yuboring.",
    "error.content_not_allowed": (
        "Bundan qoʻshiq yasay olmaymiz. Boshqacha soʻzlar bilan urinib koʻring."
    ),
    "error.provider_generic": "Studiyada nosozlik boʻldi. Bir ozdan soʻng qayta urinib koʻring.",
    "error.provider_slow": (
        "Studiya odatdagidan uzoqroq javob berayapti. Birozdan soʻng urinib koʻring."
    ),
    "error.provider_busy": "Studiya hozir band. Bir necha daqiqadan soʻng urinib koʻring.",
    "error.name_pronunciation_best_effort": (
        "Talaffuzni mukammal qila olmadik, shuning uchun eng yaxshi variantni yubordik."
    ),
    "error.delivery_failed": "Fayllarni yubora olmadik. Qaytadan urinib koʻring.",
    "error.payment_failed": "Toʻlov amalga oshmadi. Hech qanday pul yechilmadi.",
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 Salom! Men shaxsiy tabrik toʻplamini tayyorlayman: bitta qoʻshiq, uchta ovozli "
        "tabrik va qoʻshiq matni — ism toʻgʻri talaffuz qilingan holda."
    ),
    "start.choose_ui_language": "Avvalo, men siz bilan qaysi tilda gaplashay?",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Nimani nishonlayapmiz?",
    "wizard.genre.prompt": "Musiqa uslubini tanlang.",
    "wizard.vocal_gender.prompt": "Kim kuylasin?",
    "wizard.note.prompt": (
        "Ular haqida shaxsiy biror narsani ayting — sevimli mashgʻuloti, ichki hazil, laqabi. "
        "Yoki «Oʻtkazib yuborish»ni bosing."
    ),
    "wizard.note.too_long": "Biroz uzun boʻldi. Iltimos, {limit} belgidan oshmasin.",
    "wizard.name.prompt": (
        "Endi tabrik oluvchining ismini oʻzingiz yozadigan koʻrinishda yozing. "
        "Iltimos, yozing — ovozli xabar yubormang."
    ),
    "wizard.name.invalid": "Menga harflar bilan yozilgan ism kerak. Iltimos, qaytadan yozing.",
    "wizard.name.too_long": "Bu ism juda uzun. Iltimos, {limit} belgidan oshmasin.",
    "wizard.name.too_many_words": (
        "Bu gapga oʻxshaydi. Iltimos, faqat ismni yozing — {limit} tagacha soʻz."
    ),
    "wizard.name.confirm": "Men uni shunday yozaman va kuylayman:\n\n<b>{name}</b>\n\nToʻgʻrimi?",
    "wizard.name.unresolved": "Bu ismni oʻqiy olmadim. Iltimos, qaytadan yozing.",
    "wizard.output_language.prompt": "Qoʻshiq va tabriklar qaysi tilda boʻlsin?",
    "wizard.confirm.summary": (
        "<b>Sizning toʻplamingiz</b>\n"
        "Ism: <b>{name}</b>\n"
        "Sabab: {occasion}\n"
        "Uslub: {genre}\n"
        "Ovoz: {vocal_gender}\n"
        "Til: {output_language}\n"
        "Izoh: {note}\n\n"
        "Boshlaymizmi?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "Sessiya tugadi. Qaytadan boshlash uchun /start yuboring.",
    "wizard.cancelled": "Bekor qilindi. Tayyor boʻlsangiz /start yuboring.",
    "wizard.queued": "🎬 Toʻplamingiz studiyada. Tayyor boʻlishi bilan shu yerga yuboraman.",
    "wizard.enqueue_failed": (
        "Studiyani ishga tushira olmadim. Bir ozdan soʻng qayta urinib koʻring."
    ),
    "wizard.payment_declined": "Buyurtmani tasdiqlay olmadim. Hech qanday toʻlov olinmadi.",
    "wizard.name.type_only": "Iltimos, ismni matn koʻrinishida yozing — ovozli xabar boʻlmaydi.",
    "wizard.use_buttons": (
        "Iltimos, yuqoridagi tugmalardan foydalaning yoki qaytadan boshlash uchun "
        "/start yuboring."
    ),
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Orqaga",
    "button.skip": "Oʻtkazib yuborish",
    "button.cancel": "Bekor qilish",
    "button.confirm": "✅ Ha, boshlaymiz",
    "button.name_ok": "✅ Toʻgʻri",
    "button.retype": "✏️ Qaytadan yozish",
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
    "progress.queued": "🎬 Navbatda…",
    "progress.validating": "🔎 Maʼlumotlarni tekshirayapmiz…",
    "progress.moderating": "🛡 Matnni koʻrib chiqayapmiz…",
    "progress.writing_lyrics": "✍️ Qoʻshiq matnini yozayapmiz…",
    "progress.writing_scripts": "📝 Tabrik matnlarini yozayapmiz…",
    "progress.authorizing": "🔐 Buyurtmani tasdiqlayapmiz…",
    "progress.composing_song": "🎼 Qoʻshiqni bastalayapmiz…",
    "progress.verifying_name": "🔍 Ism talaffuzini tekshirayapmiz…",
    "progress.rendering_greetings": "🎙 Ovozli tabriklarni yozayapmiz…",
    "progress.post_processing": "🎚 Ovozni jilolayapmiz…",
    "progress.persisting": "💾 Toʻplamingizni saqlayapmiz…",
    "progress.delivering": "📦 Toʻplamni yigʻayapmiz…",
    "progress.done": "✅ Tayyor! Yuboryapman.",
    "progress.failed": "❌ Bu buyurtmani yakunlay olmadik. Hech qanday toʻlov olinmadi.",
    "progress.retrying_suffix": "({attempt}-urinish)",
    "progress.degraded_suffix": "(imkon qadar)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 {title} — {name} uchun",
    "delivery.greeting_caption": "🎙 {total} tadan {index}-tabrik",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.done": "🎉 Bu {name} uchun toʻplamingiz. Yana bittasi uchun /start yuboring.",
}
