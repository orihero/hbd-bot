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
    # -- errors (keys owned by bayram.errors) ---------------------------------
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
    #
    # Bu qatorlarning hech biri endi qoʻshiqlar bepul yoki sotib oladigan narsa yoʻq deb
    # vaʼda bera olmaydi: ``Settings.free_allowance_credits`` sukut boʻyicha 0, yaʼni
    # yetkazilayotgan konfiguratsiyada har bir yozuv sotiladi, va "sotib olish kerak emas"
    # degan gap narxli tugmadan bir ekran oldin aytilgan yolgʻon boʻlardi.
    "credits.balance": (
        "🎵 Qolgan qoʻshiqlar: <b>{credits}</b>\n\n"
        "Limitingiz — har {period_days} kunda {allowance} ta. Qoʻshiqlarni sotib ham "
        "olsangiz boʻladi: bittalab yoki boshlangʻich reja bilan."
    ),
    "credits.balance_none": (
        "🎵 Hozir bu hisob boʻyicha hech narsa sanalmayapti, shuning uchun "
        "koʻrsatadigan raqam ham yoʻq."
    ),
    # Har bir qoʻshiq sotiladigan konfiguratsiyadagi ``/balance`` javobi: taʼriflaydigan
    # limit yoʻq, raqam esa faqat uni toʻldiradigan narsa yonida maʼnoga ega — bu endi
    # taqvim emas, xarid.
    "credits.balance_metered": (
        "🎵 Qolgan qoʻshiqlar: <b>{credits}</b>\n\n"
        "Har bir qoʻshiq bittasini oladi. Bittalab sotib oling yoki boshlangʻich rejani oling."
    ),
    # Hisoblagich ulangan boʻlsa, bayroqdan qatʼi nazar koʻrsatiladi: "bir vaqtda bitta
    # qoʻshiq" cheklovi birinchi kundan ishlaydi, aks holda balans "ha", tasdiqlash tugmasi
    # esa "yoʻq" degan boʻlardi.
    "credits.balance_in_flight": (
        "🎬 Qoʻshiqlaringizdan biri ayni damda tayyorlanmoqda. Keyingisini u shu yerga yetib "
        "kelishi bilan buyurtma qilsangiz boʻladi."
    ),
    "credits.confirm_note": (
        "<i>Bu qoʻshiq sizdagilardan bittasini oladi. Hozir sizda: {credits}.</i>"
    ),
    # -- checkout (pulli ekran) --------------------------------------------
    # Hisobda yetarli qoʻshiq boʻlmasa, tasdiqlash ekrani ikkinchi qiyofasini kiyadi.
    # Matnning vazifasi bitta: mahsulotning ikki yarmini ajratish. Soʻzlar allaqachon
    # yozilgan, ular bepul va mijozniki boʻlib qoladi; pul faqat yozuvga toʻlanadi. Shu
    # sababli har bir xabar avval soʻzlarni, keyin narxni ataydi va hech biri "mumkin
    # emas" demaydi — bu ekran taklif.
    #
    # ``{single_amount}`` va ``{plan_amount}`` ``bayram.bot.pricing.format_amount`` orqali
    # allaqachon uch xonaga ajratilgan holda keladi ("7 000", "49 000") va valyuta soʻzini
    # OLIB KELMAYDI: u soʻz tilga bogʻliq va shu yerda yashaydi. Raqamlarning oʻzi
    # ``Settings``dan olinadi, shuning uchun narxni oʻzgartirish — konfiguratsiya
    # oʻzgarishi, toʻrtta katalog tahriri emas.
    "checkout.paywall": (
        "🔒 <b>Soʻzlar sizniki. Pul yozib olishga toʻlanadi.</b>\n\n"
        "💳 Bitta qoʻshiq — <b>{single_amount} soʻm</b>\n"
        "🌟 Boshlangʻich — <b>{plan_amount} soʻm</b>: {plan_days} kunda {plan_songs} ta\n\n"
        "Siz tanlamaguningizcha hech narsa yozib olinmaydi."
    ),
    # Oʻsha ekran, lekin reja allaqachon ishlayapti va unda qoʻshiq qolmagan. Birinchisi
    # ustiga ikkinchi rejani sotish — hech narsa uchun pul olish, shuning uchun faqat bitta
    # qoʻshiq taklif qilinadi va rejaning oʻzi tugab qolgani ochiq aytiladi.
    # Reja umuman sotilmaydi (``Settings.is_starter_plan_offered`` 2026-09-14 dan False).
    # Bitta mahsulot, bitta narx va reja haqida bir ogʻiz ham emas: ``paywall_topup``
    # "rejangizda qoʻshiq qolmadi" deydi — bu mijozda hech qachon boʻlmagan reja haqidagi gap.
    "checkout.paywall_single": (
        "🔒 <b>Soʻzlar sizniki. Pul yozib olishga toʻlanadi.</b>\n\n"
        "💳 Bitta qoʻshiq — <b>{single_amount} soʻm</b>\n\n"
        "Siz tanlamaguningizcha hech narsa yozilmaydi."
    ),
    "checkout.paywall_topup": (
        "🔒 <b>Soʻzlar sizniki. Pul yozib olishga toʻlanadi.</b>\n\n"
        "Rejangizda qoʻshiq qolmadi va u tugagunicha yangisi qoʻshilmaydi.\n\n"
        "💳 Yana bitta qoʻshiq — <b>{single_amount} soʻm</b>"
    ),
    # Toʻlov oʻtgandan keyin. Raqamni aytadi va tugmani koʻrsatadi: toʻlov qoʻshiqni
    # navbatga QOʻYMAYDI — mijoz qayta chizilgan ekranda oʻzi "Yozib olinsin"ni bosadi.
    "checkout.paid_single": (
        "✅ Toʻlandi. Sizda {credits} ta qoʻshiq tayyor — 🎬 Yozib olinsin tugmasini bosing."
    ),
    # ``{ends_on}`` — oddiy ``YYYY-MM-DD`` taqvim sanasi, xuddi ``credits.next_opens``
    # kabi va oʻsha sababga koʻra: reja sotib olingan kunga bogʻlangan, shuning uchun "30
    # kunga" degan gap ikkinchi oʻqishda rost boʻlmay qolardi.
    "checkout.paid_plan": "✅ Toʻlandi. {ends_on} kunigacha {songs} ta qoʻshiq sizniki.",
    # Oʻsha ikki gap, ammo SOVUQ aytilgan: toʻlov havola orqali mijoz telefonini qoʻygandan
    # keyin — daqiqalar yoki soatlar oʻtib — oʻtganda ularni ishchi jarayon yuboradi. Bu
    # ataylab yuqoridagi ikkitasi emas: u yerda mijoz koʻrib turgan ekrandagi 🎬 tugmasi
    # koʻrsatiladi, bu xabar esa mijoz butunlay boshqa joyga qarab turganda keladi. Tugma
    # NOMI bu yerda aytilmaydi: klaviaturani xabarni yuboradigan vazifa qoʻyadi.
    "checkout.paid_late_single": (
        "✅ <b>Toʻlovingiz oʻtdi.</b>\n\n"
        "Sizda {credits} ta qoʻshiq tayyor — qoʻshiq yasash uchun quyidagi tugmalardan "
        "foydalaning."
    ),
    "checkout.paid_late_plan": (
        "✅ <b>Toʻlovingiz oʻtdi.</b>\n\n"
        "{ends_on} kunigacha {songs} ta qoʻshiq sizniki — qoʻshiq yasash uchun quyidagi "
        "tugmalardan foydalaning."
    ),
    # Uchinchi "sovuq" jumla, va yagona chek boʻlmagani: toʻlov oʻtdi VA qoʻshiq allaqachon
    # yozilmoqda, chunki toʻlov paytida odamda tayyor qoralama bor edi
    # (``runtime.render_resume``). Yozuv boshlanganda u yuqoridagi ikkala jumlani almashtiradi,
    # shuning uchun hech qanday tugmani vada qilmaydi: jarayon ekrani bir soniyadan keyin
    # keladi va bu xabar ostida klaviatura umuman yoʻq.
    #
    # **``{credits}`` oʻrni bu yerda ataylab yoʻq.** Qoʻshiq tayyor deb aytib, oʻsha zahoti uni
    # sarflash — yuqoridagi izoh ogohlantirayotgan holatning oʻzi.
    "checkout.paid_late_resuming": (
        "✅ <b>Toʻlovingiz oʻtdi.</b>\n\nQoʻshigʻingizni hozir yozishni boshlayapman."
    ),
    # Reja ishlab turganda tasdiqlash ekrani va ``/balance`` qoʻshadigan yagona qator.
    "checkout.plan_note": "<i>Rejangizda {songs} ta qoʻshiq qoldi, {ends_on} kunigacha.</i>",
    # Tashqi toʻlov sahifasida BOSHLANGAN toʻlov — bu muvaffaqiyat. Bu kalit paydo boʻlgunicha
    # bot aynan toʻlov muvaffaqiyatli boshlangan paytda ``checkout.failed`` ("hech narsa
    # yechilmadi") deb aytardi.
    #
    # ``{amount}`` yuqoridagi vitrinadagidek allaqachon uch xonaga ajratilgan va valyuta
    # soʻzisiz keladi, va bu — ``Settings``dan qayta oʻqilgan emas, balki toʻlov tizimiga
    # yuborilgan aynan oʻsha raqam. Yozuv haqida bu yerda hech narsa vada qilinmaydi: hali
    # hech narsa hisobga olinmagan.
    "checkout.pending": (
        "🔗 <b>Sal qoldi.</b>\n\n"
        "Quyidagi tugmani bosing va <b>{amount} soʻm</b> toʻlang. Toʻlov oʻtmaguncha hech "
        "narsa yozib olinmaydi — u oʻtishi bilan shu yerda xabar beraman."
    ),
    # Xarid haqida emas, HAVOLA haqidagi ikki fakt: shuning uchun bu alohida kalit va shuning
    # uchun unda birorta ham oʻrin almashtirgich yoʻq — u har qanday mahsulot va har qanday
    # narx uchun bir xil oʻqiladi.
    #
    # Oʻn ikki soat — bu blokdagi konfiguratsiyadan kelmaydigan yagona raqam: u Payme'ning
    # oʻz oynasi hamda ``BAYRAM_PAYME_TRANSACTION_TIMEOUT_MS`` va ``BAYRAM_PAYME_INTENT_TTL_S``
    # uchun standart qiymat. Sozlamani oʻzgartirsangiz, bu gapni toʻrtala katalogda ham
    # oʻzgartirasiz.
    "checkout.pending_hint": (
        "<i>Havola 12 soat amal qiladi va bir vaqtning oʻzida faqat bitta toʻlov ochiq "
        "boʻlishi mumkin. Sahifani yopib, keyin qaytsangiz ham hech narsa yoʻqolmaydi.</i>"
    ),
    # Ataylab ``error.`` ostida turmagan ikkita rad javobi: u prefiks ``bayram.errors``ga
    # tegishli va u yerdagi hamma narsani ishchi jarayon YOZUV muvaffaqiyatsiz tugaganda
    # yuborishi mumkin — muvaffaqiyatli toʻlovdan keyin yiqilgan qoʻshiq esa "hech narsa
    # yechilmadi" yolgʻonga aylanadigan aynan oʻsha holat.
    "checkout.failed": (
        "Toʻlov oʻtmadi va sizdan hech narsa yechilmadi. Bir ozdan soʻng qayta urinib koʻring."
    ),
    "checkout.unavailable": (
        "Hozir toʻlovni qabul qila olmayman. Iltimos, bir ozdan soʻng qayta urinib koʻring."
    ),
    # ``CheckoutPausedError``. ``checkout.unavailable``dan farq qiladi: u yerda toʻlov umuman
    # ulanmagan, bu yerda esa operator ishlab turgan toʻlovni bir necha daqiqaga ataylab
    # yopib qoʻygan — shuning uchun vada qisqaroq va mijozdan qaytish soʻraladi.
    "checkout.paused": (
        "Toʻlovlar bir necha daqiqaga toʻxtatib turildi — biz bir narsani tuzatyapmiz. "
        "Sizdan hech narsa yechilmadi, iltimos, birozdan soʻng qayta urinib koʻring."
    ),
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 <b>Men bitta odam uchun bitta qoʻshiq yozaman — ismi aynan aytilishi kerak "
        "boʻlgandek kuylanadi.</b>\n\n"
        "Uslub va ovozni siz tanlaysiz, yozuvdan oldin esa soʻzlarni oʻzingiz oʻqib "
        "chiqasiz. Qoʻshiq va qoʻshiq matni shu yerga keladi."
    ),
    # -- onboarding (hammasidan oldingi ikki ekran) -------------------------
    # Buni bu bot telefon raqamiga arziydimi-yoʻqmi degan qarorga hali kelmagan odam
    # oʻqiydi, shuning uchun har bir qator nima kerakligini, bu unga nima berishini va uni
    # qanday qaytarib olish mumkinligini shu tartibda aytadi. ``onboarding.contact.required``
    # ataylab ``error.`` ostida emas: u prefiks ``bayram.errors``ga tegishli,
    # ``runtime.jobs._tell_the_customer_why`` uni parametrsiz yuboradi va ``test_i18n.py``
    # u yerda oʻrin egallovchini taqiqlaydi — ``error.`` ostidagi rad javobi esa aynan shu
    # matnni yozdirgan yagona narsani, yaʼni pastdagi tugmani bosish koʻrsatmasini,
    # olib yura olmasdi.
    "onboarding.language.prompt": (
        "🌐 Assalomu alaykum. Avvalo — men siz bilan qaysi tilda gaplashay?\n\n"
        "Buni keyin ⚙️ Sozlamalar orqali oʻzgartirsangiz boʻladi."
    ),
    "onboarding.contact.prompt": (
        "📱 Endi telefon raqamingizni qoldiring — quyidagi tugmani bosing.\n\n"
        "Bir marta soʻrayman. Agar qoʻshigʻingiz shu yerga yetib bormasa, oʻsha raqamga "
        "yuboramiz."
    ),
    "onboarding.contact.privacy_line": (
        "<i>Raqamni faqat qoʻshigʻingizni yetkazish uchun saqlayman, /forget uni oʻchiradi.</i>"
    ),
    "onboarding.contact.saved": ("✅ Rahmat, raqamingiz saqlandi. Endi qoʻshiq yasashimiz mumkin."),
    "onboarding.contact.required": (
        "📱 Qoʻshiq yasashdan oldin raqamingiz kerak — bir marta soʻrayman. Quyidagi "
        "tugmani bosing."
    ),
    # Telegram joʻnatuvchining manzillar kitobidagi istalgan odam uchun ``Contact``
    # beradi, shuning uchun uzatilgan karta — hech narsaga rozilik bermagan odamning
    # toʻgʻri raqami. Ishlovchi ``contact.user_id`` ni joʻnatuvchi bilan solishtiradi.
    "onboarding.contact.foreign": (
        "⚠️ Bu boshqa odamning raqami. Iltimos, oʻzingiznikini quyidagi tugma bilan yuboring."
    ),
    # -- menu (doimiy javob klaviaturasi) -----------------------------------
    # Bu toʻrt yozuv kiruvchi xabarning MATNI bilan solishtiriladi. Javob klaviaturasi —
    # tilni almashtirishdan ham omon qoladigan chat holati: bugun ertalab rus tiliga
    # oʻtgan odamning yozuv maydoni ostida hamon kechagi oʻzbekcha tugmalar turadi, va
    # ``keyboards.MENU_LABELS`` aynan shuning uchun joriy til boʻyicha emas, toʻrtala
    # katalog boʻyicha yigʻiladi. ``menu.prompt`` esa XABAR MATNI va
    # ``keyboards.MENU_BUTTON_KEYS`` ichida ataylab yoʻq: izoh bosqichida tasodifan "Nima
    # qilamiz?" deb yozilgan izoh hech qanday tugmasi yoʻq dispetcherga tushmasligi kerak.
    "menu.prompt": "Nima qilamiz?",
    "menu.generate": "🎵 Qoʻshiq yasash",
    "menu.balance": "🎫 Limitim",
    "menu.settings": "⚙️ Sozlamalar",
    "menu.help": "❓ Yordam",
    # -- settings ------------------------------------------------------------
    # ``{language}`` — bu oʻzgarish qoʻshadigan yagona oʻrin egallovchi, va unga til KODI
    # emas, ``language.*`` yozuvi — tilning oʻz yozuvidagi oʻz nomi — qoʻyiladi: "Joriy
    # til: ru" bu kodni oʻqiy olmaydigan odamga hech narsa demaydi, ikki bosishdan keyingi
    # tanlov ekrani esa aynan oʻsha yozuvni chizadi.
    "settings.title": "⚙️ <b>Sozlamalar</b>\n\nJoriy til: {language}",
    "settings.language.prompt": "🌐 Men siz bilan qaysi tilda gaplashay?",
    "settings.language.saved": "✅ Til saqlandi.",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Nimani nishonlayapmiz?",
    "wizard.genre.prompt": "Qoʻshiq qanday yangrasin?",
    "wizard.vocal_gender.prompt": "Kim kuylasin?",
    "wizard.note.prompt": (
        "Endi eng muhimi!\n"
        "Janr ham, sabab ham bor — endi qoʻshiqni chinakam shaxsiy qilamiz 🎯\n\n"
        "💬 Ilhom beradigan hamma narsani yozing:\n"
        "— U qanday odam? Qanaqa qiziq odatlari bor?\n"
        "— Kulgili voqealar yoki sevimli iboralari bormi?\n"
        "— Bu trek nimani aytsin: sevgimi, hazilmi, minnatdorlikmi?\n\n"
        "Bemalol yozing, {limit} belgigacha. Ismni keyingi qadamda alohida soʻrayman — "
        "bu qadamni esa oʻtkazib yuborsa ham boʻladi."
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
    # -- «oʻz matnim» yoʻli -------------------------------------------------
    # Sabablar roʻyxatidan ochiladi, yaʼni matn haqida aytilgan birinchi gap shu — shuning
    # uchun chegaralar darrov aytiladi: aks holda ular haqida faqat rad javobidan bilinadi,
    # chegarani buzgandan keyin bilish esa eng yomon yoʻl. Ikkala son ``lyrics_entry``dan.
    "wizard.lyrics.own_prompt": (
        "✍️ Kuylanadigan soʻzlarni yuboring.\n\n"
        "Ularni xabar qilib yozing — kupletlar orasida boʻsh qator qoldiring, men shu "
        "boʻlinishni saqlayman. {minimum} tadan {limit} tagacha belgi.\n\n"
        "Qanday yozsangiz, shundayligicha kuylanadi — ism kerak boʻlsa, oʻzingiz yozing."
    ),
    # Koʻrib chiqish oynasining egizagi — mijozning oʻzi yozgan soʻzlari uchun. Bu yerda
    # «oʻz matningizni yuboring» deyish mumkin emas: u buni endigina qildi.
    "wizard.lyrics.own_preview": (
        "<b>{title}</b>\n"
        "<blockquote expandable>{lyrics}</blockquote>\n"
        "Sizning soʻzlaringiz — aynan shundayligicha kuylanadi. Hali hech narsa yozib "
        "olinmadi: shuni qoldiring yoki boshqasini xabar qilib yuboring."
    ),
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
        "{occasion}\n"
        "{genre}\n"
        "{vocal_gender}\n"
        "🌐 {output_language}\n"
        "✍️ {note}\n\n"
        "Soʻzlar tayyor. Endi yozib olaman, soʻng ismni quloq bilan tekshiraman.\n\n"
        "Boshlaymizmi?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.confirm.summary_noname": (
        "<b>{title}</b>\n"
        "{occasion}\n"
        "{genre}\n"
        "{vocal_gender}\n"
        "🌐 {output_language}\n\n"
        "Soʻzlaringiz tayyor. Endi yozib olaman.\n\n"
        "Boshlaymizmi?"
    ),
    "wizard.lyrics.untitled": "Sizning qoʻshigʻingiz",
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
    "button.skip": "⏭️ Oʻtkazib yuborish",
    "button.cancel": "✖️ Bekor qilish",
    "button.confirm": "🎬 Yozib olinsin",
    # Ikkita xarid tugmasi. Narx toʻrtta katalogga yozib qoʻyilmay, ``Settings``dan
    # qoʻyiladi: yozib qoʻyilgan raqam bir kuni ``BAYRAM_SINGLE_SONG_PRICE_MINOR`` bilan
    # kelishmay qoladi — va aynan narxni oʻzgartirgan odam oʻqimaydigan tillarda. Emoji
    # baribir BIRINCHI turadi, shuning uchun "har bir tugma emoji bilan boshlanadi"
    # qoidasi buzilmaydi.
    #
    # Har biri oʻz qatorini oladi: {amount} = "49 000" bilan uzunlik yigirmadan sal
    # oshadi, ``MAX_ROW_LABEL_CHARS`` = 30 esa butun qatorga hisoblanadi.
    "button.pay": "💳 {amount} soʻm — 1 qoʻshiq",
    "button.subscribe": "🌟 {amount} soʻm — {songs} ta",
    # Mahsulotdagi tashqi havolali birinchi tugma — u toʻlov sahifasiga olib chiqadi. 💳 emas,
    # 🔗: 💳 bir ekran oldin ``button.pay``ga tegishli. Narx unda yoʻq — narx tepadagi xabarda.
    "button.pay_now": "🔗 Toʻlash",
    "button.name_ok": "✅ Ha, shunday",
    "button.retype": "✏️ Qaytadan yozish",
    "button.lyrics_ok": "✅ Shu matn qolsin",
    "button.regenerate": "🔄 Boshqa matn yozilsin",
    "button.own_lyrics": "✍️ Oʻz matnim",
    "button.start_over": "↩️ Qaytadan boshlash",
    "button.make_another": "🎂 Yana bittasi",
    "button.report_problem": "⚠️ Nimadir notoʻgʻri",
    "button.keep_note": "✅ Izoh qolsin",
    "button.try_again": "🔄 Qayta urinish",
    # Sozlamalar boʻlimi va berk koʻchadan chiqadigan ikki yoʻl. ``button.share_contact`` —
    # kolbek emas, ``request_contact`` javob tugmasining yozuvi: raqam aynan joʻnatuvchiga
    # tegishli ekanini isbotlaydigan yagona narsa shu tugma, va yuqoridagi
    # ``onboarding.contact.foreign`` ham shuning uchun bor.
    "button.set_language": "🌐 Tilni oʻzgartirish",
    "button.show_privacy": "🔒 Maʼlumotlarim",
    "button.show_support": "✉️ Yordam soʻrash",
    "button.to_menu": "🏠 Menyuga qaytish",
    "button.to_settings": "⬅️ Sozlamalarga",
    "button.share_contact": "📱 Raqamni yuborish",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "🎂 Tugʻilgan kun",
    "occasion.love": "❤️ Sevgi izhori",
    "occasion.support": "💪 Dalda",
    "occasion.prank": "😂 Hazil",
    "occasion.holiday": "🎉 Bayram",
    "occasion.wedding": "💒 Toʻy",
    "occasion.anniversary": "💍 Yubiley",
    "occasion.kids": "👶 Bolalar uchun",
    "occasion.no_occasion": "🎶 Sababsiz",
    "occasion.custom": "✨ Boshqa sabab",
    "genre.pop": "🎤 Pop",
    "genre.retro_estrada": "📻 Retro estrada",
    "genre.hip_hop": "🎧 Xip-xop",
    "genre.rock": "🤘 Rok",
    "genre.acoustic_ballad": "🎸 Akustik ballada",
    "genre.dance_electronic": "🕺 Raqs / elektron",
    "genre.uzbek_pop": "🌟 Oʻzbek estradasi",
    "genre.uzbek_folk": "🪕 Oʻzbek xalq qoʻshigʻi",
    "genre.shashmaqom": "🎻 Shashmaqom",
    "genre.jazz_lounge": "🎷 Jaz-launj",
    "vocal_gender.female": "👩 Ayol ovozi",
    "vocal_gender.male": "👨 Erkak ovozi",
    "vocal_gender.duet": "👫 Duet",
    "vocal_gender.any": "🎲 Har qanday ovoz",
    # A language button is labelled in its own language, so these four are byte-identical
    # in every catalogue and stay that way. The flags are deliberate and so is the repeated
    # 🇺🇿: the product owner chose an emoji on every button with no exceptions and accepted
    # that both Uzbek options carry the same one, because the endonym in its own script is
    # what tells them apart. That acceptance is what forces ``keyboards.LANGUAGE_COLUMNS``
    # to 1 — with the flags on, a two-column row measures 39 characters against a 30 budget,
    # and a truncated endonym would take away the only thing distinguishing the two.
    "language.uz_latn": "🇺🇿 Oʻzbekcha (lotin)",
    "language.uz_cyrl": "🇺🇿 Ўзбекча (кирилл)",
    "language.ru": "🇷🇺 Русский",
    "language.en": "🇬🇧 English",
    # -- progress (keys mirror bayram.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": (
        "🎬 {name} uchun qoʻshiq studiyada. Telegramni yopsangiz ham boʻladi — "
        "tayyor boʻlgach shu yerga keladi."
    ),
    "progress.queued_noname": (
        "🎬 Qoʻshigʻingiz studiyada. Telegramni yopsangiz ham boʻladi — shu yerga keladi."
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
    # -- watermark ---------------------------------------------------------
    # Bot CHIQARGAN hamma narsani belgilaydigan ikki qator. Ular audio izohiga, tabrik
    # izohlariga, matn varagʻining qismlariga va matn koʻrinishiga kodda qoʻshiladi, oʻsha
    # oltita shablonning ichiga yozilmaydi: oltita tirik kalitga ``{handle}`` qoʻshish
    # ularning oʻrin egallovchilar TOʻPLAMINI oʻzgartirardi, testi esa uni toʻrtta fayl
    # boʻyicha ikki tomonlama solishtiradi; ``delivery._split_for_telegram`` esa matnning
    # sof funksiyasi boʻlib qolishi shart, chunki u qaytaradigan qism raqami qayta
    # yetkazish jurnalida takrorni aniqlash kaliti.
    #
    # ``{handle}`` — bu ``bayram.watermark.WATERMARK_HANDLE``, muqova, ID3 teglari va shu
    # izohlar oʻqiydigan yagona konstanta, shunda toʻrtta tashuvchi qoʻshiqni kim
    # yaratgani haqida bir-biriga zid gapirmaydi.
    #
    # Ikkala kalit ham ``LyricDraft``ga HECH QACHON tushmaydi: matn ichidagi belgi
    # vendorga ketardi va KUYLANARDI.
    "watermark.song": "🎧 Bu qoʻshiq {handle} tomonidan yaratilgan",
    "watermark.invite": "✨ Oʻzingiznikini {handle} da yarating",
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
    "delivery.song_caption_noname": (
        "🎵 <b>{title}</b>\nSizning soʻzlaringiz, kuylandi. Ovozni yoqing."
    ),
    "delivery.done_noname": (
        "🎉 Mana qoʻshigʻingiz — yuborsangiz boʻladi.\n\n"
        "Audioni toʻgʻridan-toʻgʻri ularga yuboring: u chat ichida ijro etiladi, hech "
        "narsa yuklab olish shart emas.\n\n"
        "Buyurtma <code>{order_ref}</code> — biz bilan bogʻlanish kerak boʻlsa, saqlab qoʻying.\n\n"
        "Yana bittasini qilamizmi?"
    ),
    "delivery.done_degraded_noname": (
        "⚠️ Qoʻshigʻingiz keldi, lekin jarayon silliq oʻtmadi — nima yetishmagani quyida "
        "yozilgan. Buning uchun uzr.\n\n"
        "Buyurtma <code>{order_ref}</code>. Shu raqam bilan /support yuboring, "
        "bu jarayonni koʻramiz."
    ),
    # -- gaps (appended to the closing message; never a retry instruction) --
    "gap.name_best_effort": (
        "Ism haqida: siz eshitayotganingiz — uning aytilishiga eng yaqin variantim, mukammali emas."
    ),
    "gap.greeting_missing": "Ovozli tabriklardan biri chiqmadi, shuning uchun u bu yerda yoʻq.",
    # -- commands ----------------------------------------------------------
    "command.start": "Bir odamga qoʻshiq yasash",
    "command.cancel": "Toʻxtatib, qaytadan boshlash",
    "command.balance": "Nechta qoʻshigʻingiz qolgan",
    "command.help": "Bu qanday ishlaydi",
    "command.privacy": "Nima saqlanadi, nima yoʻq",
    "command.support": "Tirik odamga yozish",
    "command.forget": "Siz haqingizdagi hammasini oʻchirish",
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
    # Roʻyxatning birinchi qatorida ataylab muddat yoʻq. Odam OʻZI HAQIDA aytgan narsaning
    # soati yoʻq: ``/forget`` yozuvni oʻchiradi va yozuvning yoʻqligining oʻzi oʻchirilgan
    # deganidir — bu yerda muddat yozish esa mavjud boʻlmagan, koddagi hech narsa hech
    # qachon ishga tushirmaydigan tozalashni vaʼda qilish boʻlardi.
    #
    # Toʻlov qatori bu yerda, chunki ``plan_purchases`` jadvali bor: telegram_user_id yonida
    # summa, valyuta, provayder, toʻlov havolasi va plan tugash sanasi — yaʼni aniq bir odam
    # haqidagi toʻlov yozuvi. Kassa ishga tushganda bu bildirishnoma hamon faqat
    # raqam/ism/surat, izoh, fayllar, chalajon qoralama, qoʻshiqlar yozuvi va kunlik sanoqni
    # sanardi. Oʻchirish teshik emas edi: ``anonymise_plans`` ``forget_account`` dan
    # chaqiriladi va ``plans_anonymised`` boʻlib hisobot beradi. Teshik AYTIB OʻTISHda edi,
    # bot mijozlari haqida yozadigan jadvalni tilga olmaydigan bildirishnomani esa odatda
    # tashqaridan topishadi. Bu qatorda ataylab plexolder yoʻq: ``test_i18n.py`` toʻrtala
    # katalogning plexolder toʻplamlarini ikki tomonlama solishtiradi, ustiga-ustak bu
    # yozuvda ataydigan tozalash muddatining oʻzi yoʻq.
    "privacy.text": (
        "🔒 <b>Nimani va qancha saqlayman</b>\n\n"
        "📱 Telefon raqamingiz, @username, ismingiz va profil suratingiz: hisobingiz "
        "turgunicha\n"
        "🎙️ Siz bergan ism: {recipient_identity_days} kun\n"
        "✍️ Siz yozgan izoh: {brief_text_days} kun\n"
        "🎵 Tayyor qoʻshiq va qoʻshiq matni: {paid_audio_days} kun\n"
        "🎬 Boshlangan, lekin tugallanmagan qoʻshiq: {abandoned_draft_days} kun\n"
        "🧾 Yasalgan qoʻshiqlar va sarflangan limit yozuvi: muddatsiz\n"
        "💳 Nima uchun toʻlaganingiz, evaziga nima olganingiz va plan qachon tugashi: "
        "muddatsiz\n"
        "✍️ Bugun matn necha marta yozilgani sanogʻi: keyingi yozuvingizgacha\n\n"
        "Muddati bor narsaning hammasi qoʻlda emas, jadval boʻyicha oʻchiriladi. Qoʻshiqlar "
        "yozuvi bilan toʻlov yozuvi — ataylab qoldirilgan ikki istisno: oylar oʻtib ham "
        "qoʻshiqlaringiz yoki ketgan pulingiz haqidagi savolga aynan shu ikkisi javob bera "
        "oladi, shuning uchun /forget ikkalasidan ham hisob raqamingizni olib tashlaydi va "
        "sanoq bilan summalarni qoldiradi, kvitansiyani oʻchirmaydi. Kunlik yozuv sanogʻida "
        "hisob raqamingiz ham qoladi — aynan u bir odamning kun boʻyi yozishiga yoʻl "
        "qoʻymaydi — "
        "va keyingi safar yozganingizda ustiga yoziladi. Oʻzingiz haqingizda menga "
        "aytganlaringiz — raqam, foydalanuvchi nomi, ism, surat — muddatsiz: bu yerda "
        "hisobingiz turgan ekan, saqlab turaman, /forget esa hammasini bir yoʻla "
        "oʻchiradi.\n\n"
        "/forget yuborsangiz, hozir ustida ishlayotgan qoʻshigʻingiz raqamingiz, ismingiz "
        "va suratingiz bilan birga darhol oʻchadi; studiyaga allaqachon yuborilganiga esa "
        "yuqoridagi muddatlar qoladi. Keyingi safar tilingizni ham, raqamingizni ham "
        "qaytadan soʻrayman.\n\n"
        "Qoʻshiq yasamoqchi boʻlsangiz, /start yuboring."
    ),
    # Oxirgi qator tugmani emas, /start ni aytadi: /forget dan keyin hisob yana birinchi
    # muloqot nuqtasida boʻladi, va keyingi xabarni — qaysi tugma yuborishidan qatʼi
    # nazar — onboarding oladi va tilni ham, raqamni ham qaytadan soʻraydi. "Quyidan
    # qaytadan boshlang" esa aynan shu oʻchirish olib qoʻygan qisqa yoʻlni vaʼda qilardi.
    "privacy.forgotten": (
        "✅ Oʻchirildi. Ustida ishlayotgan qoʻshigʻingiz — ism, izoh, soʻzlar — mening "
        "tomonimda qolmadi, buni ortga qaytarib boʻlmaydi.\n\n"
        "Telefon raqamingiz, foydalanuvchi nomingiz, ismingiz va suratingiz ham oʻchdi: "
        "endi men siz haqingizda hech narsa bilmayman, keyingi safar qoʻshiq yasashdan "
        "oldin qaysi tilda gaplashishimni ham, raqamingizni ham qaytadan soʻrayman.\n\n"
        "Yasalgan qoʻshiqlar yozuvi ham endi siz bilan bogʻliq emas: sanoq qoladi, hisob "
        "raqamingiz esa yoʻq. Shu bilan birga joriy davrda qolgan qoʻshiqlar ham "
        "kuyadi: keyingilari davr almashganda ochiladi.\n\n"
        "Studiyaga allaqachon yuborilgan qoʻshiq /privacy dagi jadval boʻyicha oʻchiriladi.\n\n"
        "Yana qoʻshiq xohlaganingizda, /start yuboring."
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
