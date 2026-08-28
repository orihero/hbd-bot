"""Russian catalogue.

The ``ё`` vowel is written out in full everywhere it belongs — the product's whole claim
is that we get names and vowels right, and ``Алёна`` is not ``Алена``.
"""


# character below is the correct letter for the language, not a Latin look-alike.


from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    # -- errors ------------------------------------------------------------
    "error.generic": "Что-то пошло не так с нашей стороны. Попробуйте ещё раз через минуту.",
    "error.service_unavailable": "Сервис временно недоступен. Попробуйте позже.",
    "error.invalid_input": "Кажется, здесь ошибка. Проверьте и отправьте ещё раз.",
    "error.content_not_allowed": "Мы не можем сделать песню из этого. Попробуйте другие слова.",
    "error.provider_generic": "В студии сбой. Попробуйте ещё раз через минуту.",
    "error.provider_slow": "Студия отвечает дольше обычного. Попробуйте чуть позже.",
    "error.provider_busy": "Студия сейчас загружена. Попробуйте через несколько минут.",
    "error.name_pronunciation_best_effort": (
        "Мы не смогли довести произношение до идеала и отправили лучший вариант."
    ),
    "error.delivery_failed": "Не получилось отправить файлы. Попробуйте ещё раз.",
    "error.payment_failed": "Оплата не прошла. Деньги не списаны.",
    # -- start -------------------------------------------------------------
    "start.welcome": (
        "🎂 Привет! Я собираю персональный поздравительный набор: песня, три голосовых "
        "поздравления и текст песни — с правильно произнесённым именем."
    ),
    "start.choose_ui_language": "Сначала выберите язык общения со мной.",
    # -- wizard ------------------------------------------------------------
    "wizard.occasion.prompt": "Что празднуем?",
    "wizard.genre.prompt": "Выберите музыкальный стиль.",
    "wizard.vocal_gender.prompt": "Кто должен петь?",
    "wizard.note.prompt": (
        "Расскажите что-нибудь личное: увлечение, шутку, прозвище. Или нажмите «Пропустить»."
    ),
    "wizard.note.too_long": "Немного длинновато. Уложитесь, пожалуйста, в {limit} символов.",
    "wizard.name.prompt": (
        "Теперь напишите имя получателя так, как вы его пишете. "
        "Именно напишите — голосовое сообщение не подойдёт."
    ),
    "wizard.name.invalid": "Мне нужно имя буквами. Напишите его ещё раз.",
    "wizard.name.too_long": "Это имя слишком длинное. Уложитесь в {limit} символов.",
    "wizard.name.too_many_words": (
        "Это похоже на предложение. Напишите только имя — не более {limit} слов."
    ),
    "wizard.name.confirm": "Я напишу и спою его так:\n\n<b>{name}</b>\n\nВсё верно?",
    "wizard.name.unresolved": "Не удалось разобрать это имя. Напишите его ещё раз.",
    "wizard.output_language.prompt": "На каком языке спеть песню и записать поздравления?",
    "wizard.confirm.summary": (
        "<b>Ваш набор</b>\n"
        "Имя: <b>{name}</b>\n"
        "Повод: {occasion}\n"
        "Стиль: {genre}\n"
        "Голос: {vocal_gender}\n"
        "Язык: {output_language}\n"
        "Заметка: {note}\n\n"
        "Начинаем?"
    ),
    "wizard.confirm.no_note": "—",
    "wizard.expired": "Сессия истекла. Отправьте /start, чтобы начать заново.",
    "wizard.cancelled": "Отменено. Отправьте /start, когда будете готовы.",
    "wizard.queued": "🎬 Ваш набор в студии. Я пришлю его сюда, как только всё будет готово.",
    "wizard.enqueue_failed": "Не удалось запустить студию. Попробуйте ещё раз через минуту.",
    "wizard.payment_declined": "Не удалось подтвердить заказ. Деньги не списаны.",
    "wizard.name.type_only": "Пожалуйста, напишите имя текстом — голосовое сообщение не подойдёт.",
    "wizard.use_buttons": (
        "Пожалуйста, воспользуйтесь кнопками выше или отправьте /start, "
        "чтобы начать заново."
    ),
    # -- buttons -----------------------------------------------------------
    "button.back": "⬅️ Назад",
    "button.skip": "Пропустить",
    "button.cancel": "Отмена",
    "button.confirm": "✅ Да, начинаем",
    "button.name_ok": "✅ Верно",
    "button.retype": "✏️ Написать заново",
    # -- enum labels -------------------------------------------------------
    "occasion.birthday": "День рождения",
    "occasion.anniversary": "Юбилей",
    "occasion.custom": "Другой повод",
    "genre.pop": "Поп",
    "genre.retro_estrada": "Ретро-эстрада",
    "genre.hip_hop": "Хип-хоп",
    "genre.rock": "Рок",
    "genre.acoustic_ballad": "Акустическая баллада",
    "genre.dance_electronic": "Танцевальная / электронная",
    "genre.uzbek_pop": "Узбекская эстрада",
    "genre.uzbek_folk": "Узбекская народная",
    "genre.shashmaqom": "Шашмаком",
    "genre.jazz_lounge": "Джаз-лаунж",
    "vocal_gender.female": "Женский голос",
    "vocal_gender.male": "Мужской голос",
    "vocal_gender.duet": "Дуэт",
    "vocal_gender.any": "Любой голос",
    "language.uz_latn": "Oʻzbekcha (lotin)",
    "language.uz_cyrl": "Ўзбекча (кирилл)",
    "language.ru": "Русский",
    "language.en": "English",
    # -- progress (keys mirror hbd.pipeline.events.STAGE_MESSAGE_KEYS) ------
    "progress.queued": "🎬 В очереди…",
    "progress.validating": "🔎 Проверяем детали…",
    "progress.moderating": "🛡 Проверяем формулировки…",
    "progress.writing_lyrics": "✍️ Пишем текст песни…",
    "progress.writing_scripts": "📝 Пишем тексты поздравлений…",
    "progress.authorizing": "🔐 Подтверждаем заказ…",
    "progress.composing_song": "🎼 Сочиняем песню…",
    "progress.verifying_name": "🔍 Проверяем произношение имени…",
    "progress.rendering_greetings": "🎙 Записываем голосовые поздравления…",
    "progress.post_processing": "🎚 Сводим звук…",
    "progress.persisting": "💾 Сохраняем ваш набор…",
    "progress.delivering": "📦 Собираем набор…",
    "progress.done": "✅ Готово! Отправляю.",
    "progress.failed": "❌ Не получилось довести заказ до конца. Деньги не списаны.",
    "progress.retrying_suffix": "(попытка {attempt})",
    "progress.degraded_suffix": "(по возможности)",
    # -- delivery ----------------------------------------------------------
    "delivery.song_caption": "🎵 {title} — для {name}",
    "delivery.greeting_caption": "🎙 Поздравление {index} из {total}",
    "delivery.lyric_sheet": "📄 <b>{title}</b>\n\n{body}",
    "delivery.done": "🎉 Это ваш набор для {name}. Отправьте /start, чтобы сделать ещё один.",
}
