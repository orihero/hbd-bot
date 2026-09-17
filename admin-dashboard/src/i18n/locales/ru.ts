import type { TranslationSchema } from "../types";

export const ru: TranslationSchema = {
  common: {
    confirm: "Подтвердить",
    cancel: "Отмена",
    save: "Сохранить",
    delete: "Удалить",
    close: "Закрыть",
    dismiss: "Закрыть",
    retry: "Повторить",
    retrying: "Повтор…",
    refresh: "Обновить",
    reload: "Перезагрузить",
    export: "Экспорт",
    exportCsv: "Экспорт в CSV",
    search: "Поиск",
    send: "Отправить",
    done: "Готово",
    all: "Все",
    yes: "Да",
    no: "Нет",
    active: "Активен",
    inactive: "Неактивен",
    blocked: "Заблокирован",
    notBlocked: "Не заблокирован",
    loading: "Загрузка…",
    loadingApp: "Загрузка приложения…",
    previous: "Назад",
    next: "Вперед",
    pageOf: "{start}–{end} из {total}",
    pagination: "Навигация по страницам",
    filters: "Фильтры",
    filtersCount: "Фильтры · {count}",
    clearFilters: "Сбросить фильтры",
    clearAll: "Сбросить все",
    clearAllFilters: "Сбросить все фильтры",
    activeFilters: "Активные фильтры",
    removeFilter: "Удалить фильтр {field}: {value}",
    requiredAsterisk: " *",
    usersCount: "{count} пользователей",
    neverMetered: "учет не велся",
    notTracked: "не отслеживается",
    unknown: "неизвестно",
    justNow: "только что",
    noCreditRow:
      "Строки credit_accounts нет вовсе. Это не то же самое, что баланс 0 — строка заводится первым списанием или начислением.",
    none: "нет",
    any: "Любой",
    selectLanguage: "Выбрать язык",
    switchToDark: "Переключить на тёмную тему",
    switchToLight: "Переключить на светлую тему",
    to: "по",
    rangeFrom: "{label}: с",
    rangeTo: "{label}: по",
    stats: {
      unavailable: {
        noFxRate: "Курс валют не опубликован",
        noPricePublished: "Цена за песню не опубликована",
        mixedCurrencies: "В чеках несколько валют",
        notPriced: "Тариф провайдера не настроен",
        noDenominator: "Делить не на что",
        notInstrumented: "Это ещё никто не записывает",
      },
    },
  },

  nav: {
    brandTitle: "Bayram Admin",
    ariaNavigation: "Навигация",
    sections: "Разделы",
    groupOperations: "Операции",
    groupAdministration: "Администрирование",
    dashboard: "Дашборд",
    chats: "Чаты",
    users: "Пользователи",
    generations: "Генерации",
    audit: "Аудит",
    admins: "Администраторы",
    collapseSidebar: "Свернуть панель",
    expandSidebar: "Развернуть панель",
    signedInAs: "Вы вошли как {username}, {role}",
    signedInAsPrefix: "Вы вошли как",
    signedIn: "В сети",
    signOut: "Выйти",
    signingOut: "Выход…",
    groups: {
      operations: "Операции",
      administration: "Администрирование",
    },
    items: {
      dashboard: "Дашборд",
      chats: "Чаты",
      users: "Пользователи",
      generations: "Генерации",
      billing: "Биллинг",
      broadcasts: "Рассылки",
      support: "Поддержка",
      audit: "Аудит",
      admins: "Администраторы",
    },
    footer: {
      signOut: "Выйти",
      signingOut: "Выход…",
      signedInAs: "Вы вошли как {username}, {role}",
      signedIn: "В сети",
      expandSidebar: "Развернуть панель",
      collapseSidebar: "Свернуть панель",
    },
  },

  auth: {
    loginTitle: "Вход в учетную запись",
    loginSubtitle: "Учетные данные оператора консоли Bayram.",
    loginSubtitleIssued:
      "Войдите с учетной записью, выданной владельцем системы.",
    usernameLabel: "Имя пользователя",
    usernamePlaceholder: "operator",
    passwordLabel: "Пароль",
    passwordPlaceholder: "••••••••",
    rememberMe: "Запомнить меня на 7 дней",
    rememberUsername: "Запомнить имя пользователя",
    signIn: "Войти",
    signingIn: "Вход…",
    forgotPassword: "Забыли пароль?",
    forgotPasswordHint:
      "Учетные записи операторов создаются и сбрасываются администраторами консоли. Свяжитесь с владельцем системы или воспользуйтесь CLI начальной настройки для получения временного пароля.",
    ownerProvisionedNote: "Учетные записи создаются владельцем системы.",
    showPassword: "Показать пароль",
    hidePassword: "Скрыть пароль",
    invalidCredentials: "Неверное имя пользователя или пароль.",
    networkError:
      "Не удалось подключиться к серверу. Проверьте соединение с сетью.",
    rateLimited: "Слишком много неудачных попыток. Повторите позже.",

    consoleTitle: "Операционная консоль Bayram",
    consoleDescription:
      "Обслуживание клиентов, конвейер генерации песен, журнал аудита и конфигурация системы Bayram.",
    featurePipelineTitle: "Сквозной конвейер",
    featurePipelineDesc:
      "Отслеживание текстов, аудиосинтеза и доставки клиентам в реальном времени.",
    featureAuditTitle: "Полный журнал аудита",
    featureAuditDesc:
      "Каждое действие оператора подписывается криптографической HMAC-подписью и защищено от подделки.",
    featurePrivacyTitle: "Конфиденциальность данных",
    featurePrivacyDesc:
      "Персональные данные клиентов маскируются по умолчанию с обязательной повторной аутентификацией.",

    changePasswordTitle: "Смена пароля",
    changePasswordSubtitle:
      "Для продолжения работы необходимо обновить пароль учетной записи.",
    changePasswordForcedTitle: "Создайте новый пароль",
    changePasswordForcedNote:
      "Эта учетная запись создана с временным паролем. Пока он не изменен, все остальные маршруты (включая выход) возвращают 403. Установите новый пароль для продолжения.",
    changePasswordRegularNote:
      "Новый пароль завершит все ранее авторизованные сеансы.",
    currentPasswordLabel: "Текущий пароль",
    currentPasswordPlaceholder: "Текущий временный пароль",
    newPasswordLabel: "Новый пароль",
    newPasswordPlaceholder: "Не менее {min} символов",
    confirmPasswordLabel: "Подтверждение нового пароля",
    confirmPasswordPlaceholder: "Повторите новый пароль",
    passwordRequirements:
      "Не менее 12 символов, включая заглавные и строчные буквы, цифры и спецсимволы.",
    passwordTooShort: "Пароль должен содержать не менее {min} символов.",
    passwordsDoNotMatch: "Пароли не совпадают.",
    updatePassword: "Обновить пароль",
    updatingPassword: "Обновление пароля…",
    updateAndContinue: "Обновить и перейти в консоль",
    signOut: "Выйти",

    login: {
      title: "Вход в учетную запись",
      subtitle: "Учетные данные оператора консоли Bayram.",
      username: "Имя пользователя",
      password: "Пароль",
      rememberMe: "Запомнить имя пользователя",
      forgotPassword: "Забыли пароль?",
      resetHint: "Для сброса пароля обратитесь к владельцу системы.",
      signIn: "Войти",
      signingIn: "Вход…",
      ownerProvisionedNote: "Учетные записи создаются владельцем системы.",
      showPassword: "Показать пароль",
      hidePassword: "Скрыть пароль",
    },
    console: {
      heroTitle: "Операторская консоль бота Bayram для песен-поздравлений",
      heroDescription:
        "Заказы, тексты, генерации и доставка — в одном месте. Войдите, чтобы увидеть, что отработало, что упало и что до сих пор кого-то ждёт.",
    },
    passwordChange: {
      forcedTitle: "Создайте новый пароль",
      title: "Смена пароля",
      forcedNote:
        "Эта учетная запись создана с временным паролем. Пока он не изменен, все остальные маршруты (включая выход) возвращают 403. Установите новый пароль для продолжения.",
      regularNote: "Новый пароль завершит все ранее авторизованные сеансы.",
      currentPassword: "Текущий пароль",
      currentPlaceholder: "Текущий временный пароль",
      newPassword: "Новый пароль",
      newPlaceholder: "Не менее {min} символов",
      confirmPassword: "Подтверждение нового пароля",
      confirmPlaceholder: "Повторите новый пароль",
      tooShort: "Пароль должен содержать не менее {min} символов.",
      minLengthHint: "Должен содержать не менее {min} символов.",
      mismatched: "Пароли не совпадают.",
      updateAndContinue: "Обновить и перейти в консоль",
      submit: "Обновить пароль",
      updating: "Обновление пароля…",
    },
  },

  dashboard: {
    title: "Дашборд Bayram",
    overviewTitle: "Обзор",
    subtitle: "Сводные показатели и операционная телеметрия.",
    chartWindowAria: "Период графиков",
    sectionTabsAria: "Раздел дашборда",
    figureWindowAria: "Окно показателей",
    cardPeriodAria: "Период: {label}",
    unreported: "не сообщено",
    refreshMetrics: "Обновить метрики",

    balanceHealthy: "Баланс API в норме",
    balanceLow: "Низкий баланс провайдера",
    balanceCritical: "Критический баланс провайдера",
    balancesUnavailable: "балансы недоступны",
    balancesNotPolled: "балансы не опрашиваются",
    balancesNotPolledTitle:
      "Ни один провайдер в этой конфигурации не сообщает баланс, опрос не выполняется.",
    fxUnavailable: "курс валют недоступен",
    fxNoRate: "курс валют не опубликован",
    fxRate: "1 USD = {rate} сум",
    fxSubtitle: "{span} · {rate} UZS/$",

    periods: {
      today: "Сегодня",
      week: "Неделя",
      month: "Месяц",
      year: "Год",
      all: "Все время",
    },
    periodsMini: {
      today: "Д",
      week: "Н",
      month: "М",
      year: "Г",
    },
    groups: {
      audience: "Аудитория",
      finances: "Финансы",
      vendor: "Провайдеры",
      performance: "Производительность",
      charts: "Графики",
    },
    header: {
      allTime: "за всё время",
      allTimeTo: "за всё время до {date}",
      to: "до {date}",
    },
    componentState: {
      ok: "OK",
      degraded: "деградация",
      notProbed: "не проверялось",
    },
    subjects: {
      audience: "Аудитория",
      finances: "Финансы",
      planBook: "Книга планов",
      performance: "Производительность",
      vendorSpend: "Расходы и балансы у провайдеров",
      vendorDetail: "Детали по провайдерам",
      customerLists: "Списки клиентов",
    },
    figures: {
      heading: "Показатели",
      planBook: "Книга планов",
      interfaceLanguage: "Язык интерфейса",
      identifiedCustomers: "Идентифицированные клиенты",
      activeAccounts: {
        title: "Активные аккаунты",
      },
      planUtilisation: {
        title: "Насколько полно использовались планы",
      },
      planLiability: {
        title: "Что планы ещё должны",
      },
      vendorBalances: {
        title: "Балансы у провайдеров",
      },
      pollerFreshness: {
        title: "Свежесть опроса",
      },
      songConsumption: {
        title: "Что потребляет песня",
      },
      costProvenance: {
        title: "Как была рассчитана стоимость",
      },
    },
    note: {
      noCorrelationId: "нет correlation id",
      deniedTitle: "{subject}: раздел недоступен этой роли",
      deniedMessage: "Ваша роль не может читать этот раздел.",
      driftTitle: "{subject}: эта сборка не понимает ответ сервера",
      refusedTitle: "{subject}: сервер отклонил запрос",
      refusedMessage: "{message} Сузьте окно или измените детализацию.",
      staleTitle: "{subject}: обновление остановилось",
      staleMessage: "{message} Цифры ниже — последний удачный ответ.",
      offlineTitle: "{subject}: не удалось связаться с API",
      failedTitle: "{subject}: не удалось загрузить",
    },
    balances: {
      unavailable: "балансы недоступны",
      notPolled: "балансы не опрашиваются",
      notPolledTitle:
        "Ни один провайдер в этой конфигурации не сообщает баланс, опрос не выполняется.",
    },
    fx: {
      rate: "1 USD = {rate} сум",
    },
    cards: {
      totalUsers: {
        label: "Всего пользователей",
        title: "Всего пользователей",
        subtitle: "когда-либо запускали бота",
      },
      newUsers: {
        label: "Новые пользователи",
        title: "Новые пользователи",
        subtitle: "первый контакт за период",
      },
      activeUsers: {
        label: "Активные пользователи",
        title: "Активные пользователи",
        subtitle: "скользящее окно, не календарное",
      },
      churn: {
        label: "Отток",
        title: "Отток",
        subtitle: "заблокировали бота за период",
      },
      barred: {
        label: "Заблокированы оператором",
        title: "Заблокированы оператором",
        subtitle: "флаг блокировки администратором",
      },
      totalRevenue: {
        label: "Выручка",
        title: "Выручка",
        subtitle: "зафиксированные поступления",
      },
      topups: {
        label: "Продано пополнений",
        title: "Продано пополнений",
        subtitle: "сумма не фиксировалась",
      },
      vendorSpend: {
        label: "Расходы на провайдеров",
        title: "Расходы на провайдеров",
        subtitle: "тарифицированные вызовы",
      },
      costPerSong: {
        label: "Себестоимость песни",
        title: "Себестоимость песни",
        subtitle: "все провайдеры, за песню",
      },
      mrr: {
        label: "MRR",
        title: "MRR",
        subtitle: "выручка − расходы, период",
      },
      arr: {
        label: "ARR",
        title: "ARR",
        subtitle: "чистая, в пересчете на год",
      },
      vendorBalance: {
        label: "Баланс у провайдеров",
        title: "Баланс у провайдеров",
        subtitle: "последний успешный опрос",
      },
      songsRemaining: {
        label: "Оставшиеся песни",
        title: "Оставшиеся песни",
        subtitle: "оценка по остатку баланса",
      },
      medianSongTime: {
        label: "Медианное время песни",
        title: "Медианное время песни",
        subtitle: "от брифа до доставки",
      },
      songsDelivered: {
        label: "Доставлено песен",
        title: "Доставлено песен",
        subtitle: "готовые наборы, по песне",
      },
      musicRenders: {
        label: "Генерации музыки",
        title: "Генерации музыки",
        subtitle: "вызовы провайдеров, с повторами",
      },
      musicRenderTime: {
        label: "Время генерации музыки",
        title: "Время генерации музыки",
        subtitle: "только создание композиции",
      },
      systemStatus: {
        label: "Состояние системы",
        title: "Состояние системы",
        subtitle: "проверено компонентов",
      },
    },
    cardCaptions: {
      spendAllPriced: "{count} вызовов провайдеров, все тарифицированы",
      spendPartialPriced: "{costed} из {calls} вызовов тарифицированы",
      fakeCallsExcluded: " · {count} тестовых, исключено",
      cpsAllAttributed: "{count} доставлено, все учтены",
      cpsPartialAttributed: "{attributed} из {delivered} учтены",
      runRateRevCost: "выручка − расходы, {span}",
      runRateNetAnnual: "чистая × 365 ÷ {span}",
    },
    charts: {
      signups: {
        title: "Регистрации",
        sub: "одна точка = один период",
        subWeekend: "точка = период · контур = выходной",
      },
      revcost: {
        title: "Выручка и расходы",
        sub: "темный = выручка · светлый = расход",
      },
      delivered: {
        title: "Доставлено песен",
        sub: "одна линия = один период",
      },
      cps: {
        title: "Себестоимость песни",
        sub: "деление = 1 цент",
      },
      costsplit: {
        title: "Структура расходов",
        sub: "одно деление = {amount}",
        subPending: "одно деление = фиксированный шаг в долларах",
      },
      funnel: {
        title: "Воронка заказов",
        sub: "ступень = {count} заказов · пунктир = потери",
        subOne: "ступень = один заказ · пунктир = потери",
        subPending: "ступень = фиксированное число заказов · пунктир = потери",
      },
      grans: {
        hourly: "Почасовой",
        daily: "Дневной",
        weekly: "Еженедельный",
        monthly: "Ежемесячный",
      },
    },
  },

  chats: {
    title: "Чаты",
    subtitle:
      "Реплицированные диалоги клиентов, экраны бота, коллбэки и расшифровки медиа.",
    searchPlaceholder: "Поиск по юзернейму, имени, телефону, ID…",
    clearSearch: "Очистить поиск",
    filterStatus: "Фильтр по статусу",
    refresh: "Обновить",
    emptyListTitle: "Нет активных диалогов",
    emptyListMessage:
      "По вашему запросу или выбранным фильтрам чаты не найдены.",
    noThreadsFound: "Чаты не найдены",
    noThreadsSearchHint: "Попробуйте изменить поисковый запрос.",
    noThreadsEmptyHint: "Здесь будут отображаться диалоги с клиентами.",
    selectConversation: "Выберите диалог",
    selectConversationHint:
      "Выберите диалог из списка слева для просмотра деталей.",
    noChatSelectedTitle: "Выберите диалог",
    noChatSelectedMessage:
      "Выберите беседу из списка слева для просмотра сообщений и профиля клиента.",
    noMessagesYet: "Для этого пользователя пока нет записанных сообщений",
    noMessagesHint:
      "Входящие и исходящие сообщения будут фиксироваться автоматически.",
    sectionTranscript: "Транскрипт сообщений",
    sectionProfile: "Профиль клиента",
    openUserDetails: "Открыть карточку пользователя",
    viewProfile: "Профиль пользователя",
    backToList: "Назад к диалогам",
    senderCustomer: "Клиент",
    senderBot: "Бот Bayram",
    customer: "Клиент",
    bayramBot: "Бот Bayram",
    wizardStep: "шаг: {step}",
    buttonCallback: "Нажатие кнопки:",
    audioPreview: "Аудиосообщение",
    songPreview: "Превью песни на день рождения",
    voiceNote: "Голосовое сообщение",
    voiceMessage: "Голосовое сообщение",
    truncatedNote: "Примечание: Текст сокращен из-за ограничения длины.",
    inputPlaceholder: "Введите сообщение…",
    sendButton: "Отправить",
    audioMessage: "🎵 Аудиосообщение",
    callback: "🔘 Callback: {data}",
    media: "(медиа)",
    badgeAudioMessage: "🎵 Аудиосообщение",
    badgeVoiceNote: "Голосовая заметка",
    badgeButtonTap: "🔘 Кнопка: {action}",
    messagesCount: "Сообщений: {count}",
    tgId: "TG ID: {id}",
    userFallbackName: "Пользователь #{id}",
  },

  users: {
    title: "Пользователи",
    stats: {
      accounts: "Аккаунты",
      reachable: "Доступны для рассылки",
      blocked: "Заблокированы нами",
      botBlocked: "Заблокировали бота",
    },
    paginationSubtitle: "Показано {start}–{end} из {total} пользователей",
    searchLabel: "Поиск по Telegram ID",
    searchPlaceholder: "Поиск по Telegram ID или юзернейму…",
    searchHint:
      "Поиск выполняется строго по подстроке Telegram ID. Имена, юзернеймы и номера телефонов маскируются для всех ролей и намеренно недоступны для поиска: поиск по ним являлся бы раскрытием персональных данных без повторной аутентификации, бюджета и записи в аудит.",
    noMatchHint:
      "Этот список ищет только по Telegram ID, поэтому поиск по имени или юзернейму не даст результатов.",
    subject: "Справочник",
    notes: {
      forbiddenMessage:
        "Ваша роль не может читать /api/users. Записи существуют — этой учётной записи не разрешено их перечислять.",
      sessionEndedMessage:
        "{message} Сессионная кука пропала, поэтому вернуться можно только повторным входом.",
      refusedFiltersMessage:
        "{message} Повтор ничего не изменит — снимите или сузьте названный фильтр.",
    },
    filtersAria: "Фильтры пользователей",
    tableCaption: "Пользователи, начиная с новых аккаунтов",
    chips: {
      query: "Telegram id содержит",
      blocked: "Заблокирован",
      creditBalance: "Баланс кредитов",
      language: "Язык",
      createdFrom: "Аккаунт создан с",
      createdBefore: "Аккаунт создан до",
      aboveZero: "больше нуля",
      zeroOrNever: "ноль или никогда не тарифицировался",
      languageJoin: " или ",
    },
    hints: {
      blocked:
        "«Любой» запрашивает всех: параметр отсутствует, а не равен false.",
      language:
        "Можно включить несколько сразу: параметр повторяется, и API читает это как ИЛИ.",
      accountCreated:
        "Полуоткрытый интервал, в вашем часовом поясе: «по» включает весь выбранный день.",
    },
    subtitles: {
      reading: "Читаем справочник…",
      failed: "Справочник прочитать не удалось.",
      onThisPage: "На этой странице: {count}.",
      onThisPageSorted:
        "На этой странице: {count}. Без итога: эту сортировку и подсчёт нельзя запросить вместе.",
      accounts: "Аккаунтов: {total}.",
      accountsFiltered: "Под фильтры подходит аккаунтов: {total}.",
    },
    sort: {
      descending:
        "Сортировать по столбцу «{column}» — сначала наибольшие или самые недавние",
      ascending:
        "Сортировать по столбцу «{column}» — сначала наименьшие или самые давние",
      clear:
        "Отменить сортировку по столбцу «{column}» и вернуться к порядку «сначала новые аккаунты»",
    },
    segment: {
      heading: "Расширенный сегмент",
      description:
        "Соберите аудиторию из полей, которые публикует сервер. Каждое правило объединяется по И с быстрыми фильтрами выше, и ту же аудиторию можно сразу передать в рассылку.",
      builderLabel: "Правила аудитории",
    },
    audience: {
      counting: "Считаем аудиторию…",
      matched: "Сегменту соответствует аккаунтов: {count}",
      reachable:
        "Из них получат сообщение: {reachable}. Заблокированы нами: {blocked}; заблокировали бота: {botBlocked} — эти группы пересекаются, складывать их нельзя.",
      quickFiltersExcluded:
        "Это число — только сегмент: быстрые фильтры выше в него не входят.",
      failed: "Посчитать аудиторию не удалось. {message}",
      forbidden: "Ваша роль не может считать аудиторию.",
    },
    broadcast: {
      action: "Написать этим пользователям",
      ariaSegment:
        "Написать этим пользователям — открыть мастер рассылки с этим сегментом",
      ariaEveryone:
        "Написать этим пользователям — открыть мастер рассылки без сегмента, то есть по всем аккаунтам",
      blockedByQuickFilters:
        "Написать этим пользователям — недоступно: аудитория рассылки это сегмент. Очистите быстрые фильтры или выразите их правилами сегмента, чтобы перенести этот вид в рассылку.",
    },
    range: {
      loadingNext: "Загружается следующая страница",
      loading: "Загрузка пользователей",
      noneLoaded: "Пользователи не загружены",
      none: "Нет пользователей",
      noneMatching: "Нет подходящих пользователей",
      ofTotal: " из {total}",
      onThisPage: "На этой странице пользователей: {count}{total}",
      numbered: "{start}–{end}{total}",
    },
    atLeast: "{count}+",
    table: {
      user: "Пользователь",
      language: "Язык",
      orders: "Заказы",
      paid: "Оплачено",
      credits: "Кредиты",
      standing: "Состояние",
      lastOrder: "Последний заказ",
      firstContact: "Первый контакт",
      noOrders: "нет заказов",
      noUsername: "нет юзернейма",
    },
    standing: {
      blocked: "Заблокирован",
      notBlocked: "Не заблокирован",
    },
    empty: {
      noUsers: "Пользователей пока нет",
      noMatching: "Нет пользователей по этим фильтрам",
      noUsersHint:
        "Строка появляется в тот момент, когда человек впервые пишет боту — события регистрации, которое можно было бы посчитать, не существует.",
      unmatchable:
        "«{query}» содержит символы, которых в Telegram id быть не может. {hint}",
    },
    filter: {
      blocked: "Блокировка",
      creditBalance: "Баланс кредитов",
      aboveZero: "Больше нуля",
      zeroOrNever: "Ноль или не начислялись",
      botLanguage: "Язык бота",
      accountCreated: "Дата создания",
    },
    detail: {
      customer: "Клиент",
      customerSubtitle:
        "Профиль клиента, заказы, баланс кредитов и текущий черновик в визарде.",
      viewChatHistory: "История сообщений",
      grantCredits: "Начислить кредиты",
      block: "Заблокировать",
      unblock: "Разблокировать",
      profile: "Профиль",
      standing: "статус",
      firstContact: "первый контакт",
      uiLanguage: "язык интерфейса",
      photo: "фото",
      firstName: "имя",
      lastName: "фамилия",
      username: "@юзернейм",
      phone: "телефон",
      phoneShared: "телефон передан",
      firstOrder: "первый заказ",
      lastOrder: "последний заказ",
      wizardSession: "Сессия визарда",
    },
    profileStanding: {
      onFile: "профиль есть",
      onFileHint:
        "Строка user_profiles существует. Её поля здесь замаскированы; открытый текст стоит причины, повторной аутентификации и строки в аудите.",
      absentWithOrders: "строки профиля нет",
      absentWithOrdersHint:
        "Этот клиент заказывал, но строки user_profiles сейчас нет. /forget УДАЛЯЕТ эту строку, а таблица не ведёт часов хранения, так что так выглядит стирание — и так же выглядит профиль, который никогда не собирали. Отсюда их не различить.",
      absent: "никогда не онбордился",
      absentHint:
        "Нет ни строки user_profiles, ни заказов. Почти наверняка человек, который дальше первого контакта не ушёл — но стёртый аккаунт с давно удалёнными заказами выглядит так же.",
    },
    profileAria: "контактный профиль",
    identityNotes: {
      firstContact:
        "Когда этот аккаунт впервые написал боту — НЕ первый заказ. Читать это как заказ значит занижать возраст аккаунта.",
      uiLanguage: "Язык, на котором бот с ними говорит.",
      photo:
        "Когда МЫ последний раз забирали их картинку, а не когда они её меняли. `hasAvatar` — утверждение о сохранённом файле, а не о его состоянии, поэтому в шапке подставляется монограмма.",
      username:
        "Хэндл, который клиент выбрал сам и может сменить в любой момент. Не стабильный идентификатор и не имя.",
      phone:
        "В маске намеренно нет кода страны. Сам номер не уходит по проводу ни на одной роли — его даёт только раскрытие.",
      phoneShared:
        "Когда клиент нажал кнопку «поделиться контактом» в Telegram. Пусто — значит не нажимал.",
    },
    ordersPanel: {
      noun: "заказы этого клиента",
      caption: "Заказы этого клиента, начиная с новых",
      nonePage: "На этой странице заказов нет",
      noneAtAll: "Заказов нет ни в одном состоянии.",
      goBackPage: "На предыдущей странице строки есть. Вернитесь к ней.",
      neverConfirmed:
        "У этого аккаунта есть строка в users, значит он писал боту — просто ни разу не подтвердил заказ.",
      order: "заказ",
      credits: "кредиты",
      assets: "материалы",
      delivered: "доставлено",
      correlationId: "correlation id",
    },
    creditsPanel: {
      noun: "кредитный журнал этого клиента",
      caption: "Движения кредитов этого аккаунта, начиная с новых",
      movement: "движение",
      kind: "тип",
      reason: "причина",
      order: "заказ",
      actor: "кто",
      when: "когда",
      idempotencyKey: "ключ идемпотентности",
    },
    wizard: {
      title: "Сессия мастера",
      aria: "сессия мастера",
      noun: "черновик мастера",
      nothingChosen: "Пока ничего не выбрано.",
      noTextFields: "В этом черновике нет текстовых полей.",
      noDraft:
        "Под этим Telegram id черновика нет. Либо человек не в середине мастера, либо сессия истекла и её забрала уборка брошенных черновиков. Ни то ни другое не является ошибкой.",
      noStepRecorded: "шаг не записан",
      step: "шаг",
      presenceOnly:
        "Только наличие и длины. Сам текст черновика не уходит по этому проводу ни на одной роли, и маршрута раскрытия за ним нет — для брошенной сессии это единственная существующая копия.",
    },
    detailNouns: {
      record: "запись этого клиента",
      grant: "начисление",
    },
    notFound: {
      badIdTitle: "Это не Telegram user id",
      badIdMessage: "Этот адрес его не называет.",
      missingMessage: "Под этим Telegram id записи нет.",
    },
    orderSummaryLine: "заказов: {orders} · оплачено: {paid} · {language}",
    blockedBanner: "Этому аккаунту бот отказывает.",
    ableToOrder: "может заказывать",
    blockedShort: "заблокирован",
    reasonRefPlaceholder: "SUP-1423",
    credits: {
      title: "Журнал начислений кредитов",
      balance: "баланс",
      currentBalance: "Текущий баланс: {balance} кредитов",
      projected: "прогноз",
      rendersInFlight: "генераций в процессе",
      lifetimeGranted: "начислено за все время",
      balanceHint:
        "Сохранённый баланс ровно в том виде, в каком его держит журнал.",
      projectedHint:
        "Что бот сказал бы этому клиенту прямо сейчас: сохранённый баланс плюс периодическое начисление, которое уже положено, но ещё не выпущено.",
      inFlightHint:
        "Списания, которые этот аккаунт ещё не закрыл, внутри льготного окна расчёта. Единственное число здесь, которое объясняет отказ клиенту с кредитами.",
      lifetimeHint:
        "Все когда-либо добавленные кредиты, включая начисления — был ли этот аккаунт уже компенсирован, без чтения журнала.",
      allowanceHint:
        "Последнее окно периодического начисления, на которое был выпущен этот аккаунт. Пусто по двум причинам — нет строки аккаунта либо начислений никогда не было — и различить их помогает баланс рядом.",
      noAccountTitle: "Кредитного счёта нет",
      noAccountMessage:
        "Здесь ничего не начисляли, не тратили и не возвращали — строки счёта, по которой было бы движение, нет.",
      nothingMovedTitle: "На этой странице движений нет",
      nothingMovedMessage: "Счёт существует; эта страница его истории пуста.",
      allowancePeriod: "период лимита",
    },
    orders: {
      title: "Заказы",
      state: "состояние",
      recipient: "получатель",
      paid: "оплачен",
      failure: "ошибка",
      created: "создан",
      historySummary:
        "{delivered} доставлено и {failed} с ошибкой за всю историю — подсчитано сервером, а не по странице ниже.",
    },
    blockDialog: {
      blockTitle: "Блокировка клиента",
      unblockTitle: "Разблокировка клиента",
      blockConfirm: "Заблокировать {subject}",
      unblockConfirm: "Разблокировать {subject}",
      blocking: "Блокировка…",
      unblocking: "Разблокировка…",
    },
    grantDialog: {
      title: "Начислить кредиты",
      confirm: "Начислить {count} {unit} для {subject}",
      granting: "Начисление…",
      creditsLabel: "кредиты (обязательно)",
    },
  },

  generations: {
    title: "Генерации",
    stats: {
      attempts: "Попытки",
      passRate: "Доля подтверждённых",
      checked: "Проверено",
    },
    paginationSubtitle: "Показано {start}–{end} из {total} попыток",
    subtitleAll: "{count} попыток в журнале рендеринга",
    subtitleFiltered: "{count} попыток соответствуют фильтрам",
    searchPlaceholder: "Поиск по ID попытки или ID корреляции…",
    subjects: {
      ledger: "Журнал генераций",
      attempt: "Эта попытка",
    },
    subtitleAllOne: "{count} попытка в журнале генераций",
    subtitleFilteredOne: "{count} попытка подходит под эти фильтры",
    countNotRequested: "количество не запрашивалось",
    filtersAria: "Фильтры генераций",
    tableCaption: "Попытки генерации, начиная с новых",
    noVendorCall: "вызова к провайдеру не было",
    chips: {
      kind: "Тип",
      nameStrategy: "Стратегия имени",
      outcome: "Результат",
      hasOrder: "Есть заказ",
      provider: "Провайдер",
      errorCode: "Код ошибки",
      createdFrom: "Создано с",
      createdBefore: "Создано до",
      succeeded: "успешно",
      failed: "с ошибкой",
      orphanedNo: "нет — без заказа",
    },
    hints: {
      nameStrategy: "По одной стратегии за раз — параметр скалярный.",
      provider:
        "Точное имя адаптера. В списке — те, что пишет это развёртывание; новый можно ввести вручную.",
      errorCode: "Точный код ошибки конвейера, не подстрока.",
    },
    range: {
      loadingNext: "Загружается следующая страница",
      loading: "Загрузка попыток…",
      noneLoaded: "Страница не загружена",
      noneOnPage: "На этой странице попыток нет",
      ofTotal: " из {total}",
      onThisPage: "На этой странице попыток: {count}{total}",
      numbered: "{start}–{end}{total}",
    },
    notes: {
      sessionEndedMessage:
        "Войдите снова, чтобы продолжить читать журнал генераций. Ничего не потеряно — это чтение, оно ничего не записало.",
      forbiddenMessage:
        "Ваша роль не может это читать. Строки существуют — этой учётной записи не разрешено их видеть.",
      notFoundMessage:
        "{message} Ссылка может быть из другого развёртывания, либо строку удалили при очистке.",
    },
    empty: {
      failedTitle: "Показать нечего",
      failedMessage:
        "Чтение выше не удалось, поэтому таблица пуста по причине, не связанной с фильтрами.",
      noMatchTitle: "Под эти фильтры не подходит ни одна попытка",
      noMatchMessage:
        "Каждый вызов провайдера пишет сюда строку. Расширьте окно или снимите фильтр — чипсы выше показывают, какие заданы.",
      ledgerEmptyTitle: "Журнал генераций пуст",
      ledgerEmptyMessage:
        "Ни одного вызова провайдера ещё не записано. Каждая попытка конвейера попадает сюда, удачная или нет.",
    },
    table: {
      created: "Создано ({zone})",
      kind: "Тип",
      provider: "Провайдер",
      sequence: "Порядок / поп.",
      outcome: "Результат",
      language: "Язык",
      latency: "Задержка",
      cost: "Стоимость",
    },
    kinds: {
      song: "песня",
      song_inpaint: "доработка песни",
      greeting: "поздравление",
      lyrics: "текст",
      name_preview: "превью имени",
      name_verification: "проверка имени",
      cover: "обложка",
    },
    strategies: {
      canonical: "каноническая",
      stripped: "без диакритики",
      ascii: "ASCII",
      cyrillic: "кириллица",
      hyphenated: "через дефис",
      phonetic: "фонетическая",
    },
    orphanedLabel: "Без заказа",
    orphanedExplanation:
      "Строки заказа нет: либо это превью имени, отрисованное до появления заказа, либо заказ, который потом удалили. Попытку в любом случае сохраняют для настройки, и по строке нельзя сказать, какой из двух случаев это.",
    outcomes: {
      succeeded: "Успешно",
      failed: "Ошибка",
      orphaned: "Без заказа",
    },
    fields: {
      attemptId: "id попытки",
      order: "заказ",
      created: "создано",
      result: "результат",
      errorCode: "код ошибки",
      errorMessage: "сообщение об ошибке",
      retryable: "можно повторить",
      provider: "провайдер",
      providerId: "id у провайдера",
      language: "язык",
      candidate: "кандидат",
      strategy: "стратегия",
      verified: "подтверждено",
      matchConfidence: "уверенность совпадения",
      length: "длина",
      cost: "стоимость",
      latency: "задержка",
    },
    detailAria: "Попытка генерации",
    sequenceLine: "последовательность {sequence} · попытка {attempt}",
    detail: {
      identity: "Идентификация",
      outcome: "Результат",
      vendor: "Провайдер",
      nameVerification: "Проверка имени",
      transcript: "Транскрипт",
      telemetry: "Телеметрия",
      close: "Закрыть",
      verified: "Подтверждено",
      noMatch: "Не совпадает",
      retryable: "Можно повторить",
      notRetryable: "Не повторять",
    },
  },

  audit: {
    title: "Аудит",
    paginationSubtitle: "Показано {start}–{end} из {total} записей аудита",
    subtitleAll: "Все зафиксированные действия, сначала новые — {note}.",
    subtitleFiltered: "Действия по выбранным фильтрам, сначала новые — {note}.",
    subjects: {
      log: "Журнал аудита",
      verdict: "Вердикт по цепочке",
    },
    noTotalNote:
      "этот эндпойнт не считает строки, поэтому цифры — в пределах страницы",
    filtersAria: "Фильтры аудита",
    tableCaption: "Записи аудита, начиная с новых",
    recordCount: "записей: {count}",
    chips: {
      actor: "Кто",
      action: "Действие",
      outcome: "Результат",
      subjectType: "Тип объекта",
      subjectId: "Id объекта",
      recordedFrom: "Записано с",
      recordedThrough: "Записано по",
    },
    hints: {
      actor:
        "UUID совпадает с id актора точно; всё остальное — точно с юзернеймом, без учёта регистра. Никогда не префикс и не подстрока.",
      subjectType: "По одному типу за раз — параметр скалярный.",
      subjectId:
        "Точное совпадение по непрозрачному идентификатору — UUID, Telegram id или версия конфига. Никогда не имя.",
      action: "Сколько угодно: повторы — это ИЛИ внутри поля и И между полями.",
    },
    actorPlaceholder: "юзернейм или id",
    subtitles: {
      reading: "Читаем журнал…",
      failed: "Журнал прочитать не удалось.",
    },
    range: {
      loadingNext: "Загружается следующая страница",
      loading: "Загрузка журнала…",
      noneLoaded: "Страница не загружена",
      noneOnPage: "На этой странице записей нет",
      spanned: "записей: {count}, с {first} до {last}",
      numbered: "{start}–{end}",
    },
    notes: {
      sessionEndedMessage:
        "Войдите снова, чтобы продолжить читать журнал. Ничего не потеряно — это чтение, оно ничего не записало.",
      stepUpMessage:
        "{message} Ни один из маршрутов аудита её не требует, так что никакой пароль на это не ответит. Это сбой на стороне сервера, о котором стоит сообщить, указав id ниже.",
      forbiddenMessage:
        "Читать журнал аудита могут только Owner и Admin. Строки существуют — этой учётной записи не разрешено их видеть, и сам этот отказ тоже записан.",
      refusedFiltersMessage:
        "{message} Повтор ничего не изменит — снимите названный фильтр. Вставленный курсор, который этот эндпойнт не выдавал, отклоняется так же.",
    },
    empty: {
      failedTitle: "Показать нечего",
      failedMessage:
        "Чтение выше не удалось, поэтому таблица пуста по причине, не связанной с фильтрами.",
      noMatchTitle: "Под эти фильтры нет записей",
      noMatchMessage:
        "Каждое аудируемое действие пишет сюда строку, включая отказы. Расширьте окно или снимите фильтр — чипсы выше показывают, какие заданы.",
      logEmptyTitle: "В журнале нет записей",
      logEmptyMessage:
        "Ничего ещё не записано — что на развёрнутой системе, куда кто-то входил, невозможно: сам вход пишет свою строку.",
    },
    table: {
      recorded: "Записано ({zone})",
      seq: "Порядковый номер",
      actor: "Инициатор",
      action: "Действие",
      outcome: "Результат",
      subject: "Объект",
      exposure: "Объем раскрытия",
      reason: "Обоснование",
      correlation: "Корреляция",
    },
    outcome: {
      ok: "Успешно",
      denied: "Доступ запрещен",
      error: "Системная ошибка",
    },
    reasons: {
      reasonWithheld:
        "обоснование записано, у вашей роли нет прав на его чтение",
      noReasonText: "в этой строке нет свободного текста",
    },
    verify: {
      title: "Проверка целостности журнала аудита",
      description:
        "Проверяет криптографическую хэш-цепочку HMAC последовательных записей аудита для обнаружения несанкционированного изменения БД.",
      successTitle: "Целостность журнала аудита подтверждена",
      successMessage:
        "Цепочка HMAC-подписей непрерывна для всех {count} проверенных записей.",
      failureTitle: "Нарушение целостности: цепочка прервана!",
      failureMessage:
        "Обнаружено несовпадение HMAC-подписи в записи #{entryId}. Возможно вмешательство в журнал.",
      checkAgain: "Повторить проверку",
      checking: "Проверка цепочки…",
      checkedAt: "Время проверки",
      rowsChecked: "Проверено строк",
      lastSeq: "Последний номер",
      walk: "Обход",
      firstBreak: "Первый сбой",
      protection: "Защита",
      validSentence: "Данные журнала не изменялись с момента их записи.",
      brokenSentence:
        "Журнал поврежден или подвергся постороннему вмешательству.",
      partialSentence:
        "Корректно в пределах проверенного диапазона; проверены не все записи.",
    },
  },

  admins: {
    title: "Администраторы",
    subtitle: "{active} активных · {deactivated} отключено",
    subject: "Реестр операторов",
    subtitles: {
      reading: "Читаем реестр…",
      failed: "Реестр прочитать не удалось.",
      truncated:
        "{counted} — Сервер возвращает не более {cap} учётных записей и ничего не сообщает о том, что осталось за кадром, поэтому список может быть неполным.",
    },
    tableCaption:
      "Операторские учётные записи — сначала те, кто может войти, затем отключённые",
    tooltips: {
      deactivated:
        "Учётная запись существует и не может войти. Её сохраняют, потому что на неё ссылается журнал аудита.",
      temporaryCredential:
        "На этой учётной записи всё ещё стоит пароль, который выбрал кто-то другой.",
    },
    roleHints: {
      owner:
        "Единственная роль, которая может читать этот реестр, и единственная, которой достанутся операции над учётными записями, когда они появятся.",
      admin:
        "Блокировки, разблокировки и начисления кредитов, плюс всё, что может Support. Читать этот реестр не может.",
      support:
        "Читает записи и может раскрывать персональные данные с повторной аутентификацией. Читать этот реестр не может.",
      viewer:
        "Читает только маскированные записи — без раскрытия и без изменений. Читать этот реестр не может.",
    },
    notes: {
      sessionEndedMessage: "{message} Вернуться можно только повторным входом.",
      stepUpTitle:
        "Сервер запросил повторную аутентификацию, которой у этого маршрута нет",
      stepUpMessage:
        "{message} Чтение реестра не требует повторной аутентификации (§6.8, строка 949), так что это изменение прав на стороне сервера, а не то, на что можно ответить здесь.",
      forbiddenMessage:
        "{message} У {who} нет ячейки admin.read, поэтому учётные записи существуют, а этой сессии их перечислять нельзя. Повтор этого не изменит, и каждая попытка записывается в журнал аудита как отказ.",
      forbiddenRoleNamed: "роли {role}",
      forbiddenRoleUnknown: "роли этой учётной записи",
      staleMessage:
        "{message} Учётные записи ниже — последний удачный ответ, а не текущий.",
    },
    table: {
      username: "Имя пользователя",
      role: "Роль",
      signIn: "Доступ",
      credential: "Пароль",
      lastSignIn: "Последний вход",
      created: "Создан",
      attention: "Требует внимания",
    },
    status: {
      active: "Активен",
      deactivated: "Отключен",
      cannotSignIn: "вход заблокирован",
    },
    credential: {
      temporary: "Временный",
      rotated: "Сменен",
    },
    lastLogin: {
      never: "Никогда",
      noSignInRecorded: "вход не зафиксирован",
    },
    roles: {
      owner: "Владелец",
      admin: "Администратор",
      support: "Поддержка",
      viewer: "Наблюдатель",
    },
    attentionTitle: "Учетные записи, требующие внимания",
    staleReasons: {
      neverSignedIn: "ни разу не входил",
      temporaryPassword: "временный пароль не сменен",
      dormant: "нет входа более {days} дн.",
    },
    emptyTitle: "Список операторов пуст",
    emptyMessage:
      "В рабочей системе этого не может быть — в списке должна присутствовать ваша собственная учетная запись. Проверьте подключение к базе данных.",
    noWritesNote:
      "Создание оператора — единственная запись по учетным записям в этой сборке. Смена роли, сброс чужого пароля и деактивация пока не поддерживаются ни здесь, ни через CLI; кнопка для них вернула бы только 404. CLI (bayram.admin.bootstrap) создает первого Владельца и восстанавливает права, когда активных Владельцев не осталось, а свой пароль вы меняете в этой консоли.",
    forbiddenTitle: "Список доступен только Владельцу",
    create: {
      button: "Новый оператор",
      title: "Добавить оператора",
      description:
        "Учетная запись создается активной, с паролем, который вы вводите здесь. Владелец записи обязан заменить его при первом входе — до этого любой маршрут отвечает 403, — а само действие записывается в журнал аудита с указанной причиной.",
      noun: "новую учетную запись",
      usernameLabel: "имя пользователя (обязательно)",
      usernameHint:
        "От {min} до {max} символов: строчные латинские буквы, цифры, точка, подчеркивание и дефис; первый и последний символ — буква или цифра. Без @ — логин в виде адреса почты создается только на сервере, потому что подтверждение действия использует само имя как субъект.",
      usernameInvalid:
        "Для такого имени нельзя подтвердить действие паролем. Только строчные латинские буквы, цифры, точка, подчеркивание и дефис; первый и последний символ — буква или цифра.",
      passwordLabel: "временный пароль (обязательно)",
      passwordHint:
        "Не менее {min} символов. Передайте его отдельным каналом — он заменяется при первом входе и больше здесь не показывается.",
      roleLabel: "роль (обязательно)",
      ownerNote:
        "Роли «Владелец» в списке нет: в базе может быть только один активный Владелец, а передача владения выполняется командой `python -m bayram.admin.bootstrap --reset-owner` на сервере.",
      submit: "Создать {username}",
      submitFallback: "Создать оператора",
      pending: "Создаем…",
      stepUpNote:
        "Создание {username} требует подтверждения для этого имени пользователя.",
      createdTitle: "{username} создан",
      createdMessage:
        "Передайте пароль отдельным каналом. {username} обязан заменить его при первом входе, до этого любой маршрут отвечает 403.",
    },
  },

  errors: {
    notFoundTitle: "Страница не найдена.",
    backToDashboard: "Вернуться на дашборд",
    detail: {
      sessionEndedTitle: "Сессия завершена",
      sessionEndedMessage:
        "Войдите снова, чтобы это прочитать. Сессионная кука и её CSRF-двойник ставятся и снимаются вместе, поэтому отклонённый токен означает, что самой сессии больше нет — повтор её не вернёт.",
      misconfiguredTitle: "Это развёртывание настроено неверно",
      misconfiguredMessage:
        "API отклонил источник запроса. Это ошибка развёртывания, а не ваше действие, и повтор её не исправит — BAYRAM_ADMIN_PUBLIC_ORIGIN не совпадает с адресом, откуда отдаётся эта панель.",
      forbiddenTitle: "Ваша роль не может читать: {noun}",
      roleCannotTitle: "Ваша роль не может это сделать",
      needsReauthTitle: "Для этого действия нужна повторная аутентификация",
      notFoundTitle: "Ничего не хранится для: {noun}",
      conflictTitle: "Кто-то изменил это раньше вас",
      conflictMessage:
        "{message} Состояние на экране перечитано; проверьте его, прежде чем действовать снова.",
      invalidTitle: "Запрос отклонён как некорректный",
      invalidMessage:
        "{message} Тот же запрос будет отклонён так же; измените его, а не повторяйте.",
      tooManyStepUpsTitle: "Слишком много попыток повторной аутентификации",
      tooManyStepUpsMessage:
        "{message} Этот счётчик привязан к сессии, поэтому ожидание на этом экране его не сбросит — войдите заново.",
      rateLimitedTitle: "Ограничение частоты запросов",
      budgetSpentTitle: "Ваш лимит раскрытий исчерпан",
      driftTitle: "Эта панель и сервер расходятся в контракте",
      driftMessage:
        "{message}{fields} Ничему здесь нельзя доверять, пока сборки не совпадут; сообщите об этом, а не обходите.",
      driftFields: " Поля: {paths}.",
      offlineTitle: "Не удалось связаться с API для: {noun}",
      dependencyTitle: "Зависимость не отвечает",
      failedTitle: "Не удалось загрузить: {noun}",
      noCountdown: "{message} В конверте не было обратного отсчёта.",
      tryAgainIn: "{message} Повторите через {seconds} с.",
    },
    query: {
      noCorrelationId: "нет correlation id",
      sessionEndedTitle: "Сессия завершена",
      originTitle: "Консоль отдаётся с источника, который API не принимает",
      originMessage:
        "{message} Это настройка развёртывания (BAYRAM_ADMIN_PUBLIC_ORIGIN), а не ваше действие — повтор ничего не изменит.",
      stepUpTitle:
        "{subject}: сервер запросил повторную аутентификацию, которой у этого маршрута нет",
      forbiddenTitle: "{subject}: раздел недоступен этой роли",
      driftTitle: "{subject}: эта сборка не понимает ответ сервера",
      driftMessage: "{message} ({paths})",
      refusedFiltersTitle: "{subject}: сервер отклонил эти фильтры",
      rateLimitedTitle:
        "{subject}: API ограничивает частоту запросов этой сессии",
      rateLimitedWait: " Повторите через {seconds} с.",
      staleTitle: "{subject}: обновление остановилось",
      staleMessage:
        "{message} Строки ниже — последний удачный ответ, а не текущий.",
      offlineTitle: "{subject}: не удалось связаться с API",
      failedTitle: "{subject}: не удалось загрузить",
      notFoundTitle: "{subject}: с таким id ничего нет",
    },
    notFound: {
      title: "Страница не найдена.",
      backToDashboard: "Вернуться на дашборд",
    },
    routeError: {
      title:
        "Ошибка отображения экрана. Подробная информация доступна в консоли браузера.",
      reload: "Перезагрузить",
    },
    emptyState: {
      defaultTitle: "Нет данных",
      defaultMessage: "Записи пока отсутствуют.",
    },
    dialog: {
      defaultCancel: "Отмена",
      defaultConfirm: "Подтвердить",
    },
  },

  reveal: {
    stepUpTitle: "Повторная аутентификация",
    stepUpExplanation:
      "Это действие требует подтверждения пароля (A+S): наличия прав недостаточно, панели требуется повторный ввод вашего пароля именно для этого объекта.",
    stepUpCostsNoBudgetNote:
      "Средства не списаны и данные не раскрыты: проверка пароля выполняется до проверки бюджета, поэтому отказ или отмена не расходуют лимит записей.",
    stepUpChangesNothingNote:
      "Никаких изменений еще не произошло: проверка пароля выполняется до записи в базу, поэтому отказ или отмена не меняют состояние учетной записи и лишь фиксируют отказ в журнале аудита.",
    revealIsAuditedNote:
      "Каждое раскрытие создает запись аудита с вашим именем, объектом, списком полей и этой причиной до выполнения чтения. Раскрытие будет зафиксировано, даже если чтение завершится сбоем. Запись фиксирует, КАКИЕ поля были раскрыты, но не их содержимое.",
    roleRefusalNote:
      "Отказ получен от обработчика маршрута, а не от проверки разового доступа. Повторный ввод пароля ничего не изменит: у вашей роли нет прав на эту операцию.",
    costRecords: "{count} записей",
    revealButton: "Раскрыть",
    revealFieldAria: "Раскрыть: {field}",
    revealedRecordsAria: "раскрытые записи",
    fields: {
      recipientNameDisplay: "имя получателя, как показано",
      recipientNameRaw: "имя получателя ровно так, как набрано",
      recipientLookupKey: "ключ поиска получателя",
      recipientCandidates: "варианты имени получателя",
      note: "записка получателю",
      approvedLyrics: "утверждённый текст песни",
      sttTranscript: "расшифровки голосовых",
      nameCandidateText: "варианты имени, как расслышано",
      phone: "номер телефона",
      firstName: "имя, как в Telegram",
      lastName: "фамилия, как в Telegram",
      telegramUsername: "@юзернейм",
    },
    fieldHints: {
      recipientNameDisplay:
        "Имя, которое спел конвейер. Везде ещё замаскировано до первого символа.",
      recipientNameRaw:
        "То, что клиент набрал — ответ на вопрос «какой именно апостроф он поставил».",
      recipientLookupKey:
        "Свёрнутый ключ, с которым сравнивал сопоставитель имён.",
      recipientCandidates:
        "Все рассмотренные варианты написания и стратегия, которая каждый из них дала.",
      note: "Свободный текст, который клиент написал о получателе. На 30-дневных часах.",
      approvedLyrics: "Полный текст песни, который утвердил клиент.",
      sttTranscript:
        "Что расслышала распознавалка, по записи на дубль. Постранично, оплата за страницу.",
      nameCandidateText:
        "Текст имени, предложенный каждой попыткой, по записи на дубль. Постранично, оплата за страницу.",
      phone:
        "Номер в формате E.164, переданный один раз кнопкой «поделиться контактом» в Telegram. Везде ещё замаскирован до последних цифр. Хранится, пока существует аккаунт; /forget его удаляет.",
      firstName:
        "Не имя получателя — собственное имя клиента из его контакта в Telegram.",
      lastName: "Часто отсутствует: Telegram её не требует.",
      telegramUsername:
        "Без «@». Хэндл, который клиент выбрал сам и может сменить; не стабильный идентификатор.",
    },
    actions: {
      reveal: "раскрытие персональных данных по этому объекту",
      orderForceDeliver: "принудительная смена статуса заказа на «доставлен»",
      userBlock: "блокировка или разблокировка этого клиента",
      creditGrant: "начисление кредитов на этот аккаунт",
      moderationDecide: "принятие решения по модерации",
      userPurge: "удаление персональных данных этого клиента",
      configWrite: "изменение настроек конфигурации",
      orderEvidenceExport: "экспорт пакета подтверждений по этому заказу",
      auditExport: "экспорт журнала аудита",
      adminManage: "управление учетными записями администраторов",
      broadcastSend:
        "отправить эту рассылку аудитории, зафиксированной при её создании",
    },
    reasons: {
      customerRequest: "по запросу клиента",
      gdprErasure: "запрос на удаление данных",
      abuseReport: "жалоба на нарушение правил",
      supportInvestigation: "расследование службы поддержки",
      incident: "инцидент",
      bakeOff: "сравнение качества стратегий",
      routineOps: "регламентные операции",
      other: "другое — укажите причину ниже",
    },
    dialog: {
      title: "Раскрыть: {subjectType} {subjectLabel}",
      reasonRequired:
        "Выберите код причины. Он обязателен, попадает в строку аудита, и без него сервер откажет в раскрытии.",
      confirm: "Раскрыть — {cost}",
      pending: "Раскрываем…",
      nextPage: "Следующая страница — новое раскрытие, снова {cost}",
      budgetSpentTitle: "Ваш лимит ({scope}) исчерпан.",
      recordsUnknown:
        "Сервер не сообщил, сколько записей запросило это раскрытие.",
      recordsAsked: "Это раскрытие запросило записей: {count}.",
      recordsLeft: " Осталось записей в этом часе: {count}.",
      conversationsLeft: " Осталось диалогов на сегодня: {count}.",
      noCountdown: "В конверте не было обратного отсчёта.",
      windowResets:
        "Это окно сбросится через {delay}. Окно фиксированное, а не скользящее.",
      nothingCharged:
        "Ничего не списано и ничего не раскрыто — отклонённое раскрытие возвращает свою стоимость.",
      roleRefused: "Ваша роль не может это сделать.",
      refused: "В раскрытии отказано.",
      stepUpPendingTitle: "Ещё один шаг: подтвердите пароль.",
      stepUpNote:
        "Вы запросили снятие маски: {cost} на этом объекте ({subjectType}).",
      stepUpAsk:
        "Раскрытие {cost} для {subjectType} {subjectLabel} требует разрешения, выданного именно на этот объект. Ничего не списано.",
      budgetNotMeasured:
        "Лимит: в этой сессии ещё не измерялся. Сервер сообщает остаток при каждом раскрытии.",
      budgetRecords: "осталось записей в этом часе: {count}",
      budgetConversations: "осталось диалогов на сегодня: {count}",
      pageSize: "записей: {count}",
      pageSizeLabel: "сколько записей может вернуть эта страница",
      mixedShape: "Эти столбцы нельзя раскрыть одним запросом.",
      nothingToShow: "Показать нечего.",
      reasonCodeLabel: "код причины (обязательно)",
      reasonRefLabel: "ссылка на тикет (необязательно)",
      reasonTextLabel:
        "зачем (необязательно, {max} символов, хранится 90 дней)",
      ceilingsSeparate:
        " Два лимита независимы: расход одного не тратит другой.",
      recordsNotTouched: "записи: последнее раскрытие их не затронуло",
      conversationsNotTouched: "диалоги: не затронуты",
      pageSizeNote:
        "Это списание, а не потолок того, что существует: бюджет списывается до чтения, поэтому неполная страница всё равно стоит столько, сколько запросили.",
      refMalformed:
        "Только буквы, цифры, #, _ и -, до 64 символов. Всё остальное сервер отклонит — а отклонённое тело не пишет строку аудита, что неверный способ провалить действие §9.2.",
      refCredentialShaped:
        "40 и более символов из букв, цифр, _ и - граница аудита читает как учётные данные, и раскрытие будет отклонено до списания. Сократите строку или добавьте # либо другой разделитель.",
      scopeRecords: "часовой лимит записей",
      scopeUnknown: "раскрытий",
      scopeConversations: "суточный лимит диалогов",
      costRecordsOne: "{count} запись",
      costRecordsMany: "записей: {count}",
      costConversationsOne: "{count} диалог",
      costConversationsMany: "диалогов: {count}",
      costAnd: "{records} и {conversations}",
      retrySeconds: "{count} с",
      retryMinutes: "{count} мин",
      returnedRecords:
        "Возвращено {returned} из {charged} оплаченных записей. ",
      chargeIsThePage:
        "Списано за страницу, которую это раскрытие имело право вернуть, а не за то, что нашлось.",
    },
    shapes: {
      single: "одна запись",
      paged: "одна страница записей",
    },
    stepUpDialog: {
      submit: "Подтвердить",
      pending: "Подтверждаем…",
      passwordLabel: "Ваш пароль",
      zeroGrace:
        "Разрешение на это действие истекает в момент выдачи: оно авторизует ровно один этот запрос.",
      graceWindow:
        "Разрешение не одноразовое. В том коротком окне, которое задаёт сервер, оно допускает и повтор, и следующую страницу постраничного раскрытия — сколько будет раскрыто, ограничивает лимит, а не разрешение.",
      wrongPassword: "Этот пароль не принят.",
      refused: "В повторной аутентификации отказано.",
      rateLimited:
        "Лимит повторных аутентификаций исчерпан. Он привязан к сессии, поэтому новый вход начинает новое окно — ожидание здесь не поможет.",
      invalidScope:
        "Сервер не смог сохранить этот id объекта как область действия. Это ошибка панели в том, как id был построен, а не то, что можно перенабрать.",
    },
    dateRange: {
      recorded: "Записано",
      recordedFrom: "Записано с",
      recordedTo: "Записано по",
      created: "Создано",
      createdFrom: "Создано с",
      createdTo: "Создано по",
      halfOpenHint:
        "Полуоткрытый интервал: «с» включается, «по» — нет. Время в {zone}.",
      bothEndsHint:
        "Включены оба конца, в отличие от всех остальных списков этого API. Время в {zone}.",
    },
    stepUp: {
      title: "Повторная аутентификация",
    },
  },
  broadcasts: {
    title: "Рассылки",
    stats: {
      campaigns: "Рассылки",
      inFlight: "В отправке",
      recipients: "Записано получателей",
      lastSend: "Последняя отправка",
      noSendYet: "Ни одна отправка ещё не начиналась",
    },
    subject: "Список рассылок",
    subjectOne: "Эта рассылка",
    subjectRecipients: "Журнал получателей",
    tableCaption:
      "Рассылки, начиная с недавно составленных — одна строка на рассылку, а не на получателя",
    filtersAria: "Фильтры рассылок",
    newCampaign: "Новая рассылка",
    newCampaignAria:
      "Новая рассылка — составить сообщение и зафиксировать аудиторию",
    atLeast: "не менее {count}",
    subtitles: {
      reading: "Читаем рассылки…",
      failed: "Рассылки прочитать не удалось.",
      onThisPage: "На этой странице: {count}.",
      campaigns: "Рассылок: {total}.",
      campaignsFiltered: "Рассылок по этим фильтрам: {total}.",
    },
    range: {
      loading: "Загружаем первую страницу…",
      loadingNext: "Загружаем следующую страницу…",
      noneLoaded: "Ни одна страница не загружена.",
      none: "Рассылок пока нет.",
      noneMatching: "Ни одна рассылка не подходит под эти фильтры.",
      numbered: "{start}–{end}{total}",
      onThisPage: "{count} на этой странице{total}",
      ofTotal: " из {total}",
    },
    filter: {
      state: "Состояние",
      stateHint:
        "Несколько сразу — это ИЛИ: параметр повторяется, и API читает его именно так.",
      kind: "Вид",
      kindHint:
        "Вид объявляется при составлении рассылки, и правка текста его не меняет.",
    },
    chips: {
      state: "Состояние",
      kind: "Вид",
      join: " или ",
    },
    table: {
      title: "Рассылка",
      kind: "Вид",
      state: "Состояние",
      audience: "Аудитория",
      progress: "Доставка",
      createdBy: "Составил",
      created: "Составлена",
      noCreator: "учётная запись удалена",
      scheduledFor: "запланирована на {at}",
    },
    empty: {
      title: "Рассылок пока нет",
      message:
        "На этой установке ещё ничего не составлено. Рассылка начинается с аудитории — соберите её в справочнике или откройте мастер здесь.",
      filteredTitle: "Ни одна рассылка не подходит под эти фильтры",
      filteredMessage:
        "Фильтры сужают только по состоянию и виду; рассылка в другом состоянии никуда не делась.",
    },
    notes: {
      forbiddenMessage:
        "Ваша роль не может читать /api/broadcasts. Рассылки существуют — этой учётной записи не разрешено их перечислять.",
      sessionEndedMessage:
        "{message} Сессионная кука пропала, поэтому вернуться можно только повторным входом.",
      refusedFiltersMessage:
        "{message} Повтор ничего не изменит — снимите или сузьте названный фильтр.",
      notFoundMessage:
        "Рассылки с таким идентификатором нет. Отказ не повторяет идентификатор в ответе, поэтому проверьте ссылку, по которой вы перешли.",
    },
    state: {
      draft: "Черновик",
      expanding: "Собираем аудиторию",
      ready: "Готова к отправке",
      sending: "Отправляется",
      paused: "Приостановлена",
      completed: "Завершена",
      cancelled: "Отменена",
      failed: "Сбой",
    },
    stateHint: {
      draft:
        "Составлена, но аудитория ещё не развёрнута. В этом состоянии API не возвращает ничего: строки получателей начинают писаться сразу при создании.",
      expanding:
        "Строки получателей ещё пишутся. Пока они не все на месте, отправку авторизовать нельзя — наполовину записанный журнал это половина аудитории.",
      ready:
        "Аудитория записана, ничего не отправлено. Это единственное состояние, из которого можно авторизовать отправку.",
      sending:
        "Сообщения уходят прямо сейчас. Счётчики растут сами, без действий на этом экране.",
      paused:
        "Остановлена между блоками. Строки, уже взятые обработчиком, ещё несколько секунд доходят до итога, поэтому счётчики продолжают двигаться.",
      completed:
        "Каждая строка получателя дошла до итога. Сообщения, отклонённые Telegram, посчитаны, а не спрятаны — рассылка всё равно завершена.",
      cancelled:
        "Остановлена окончательно. То, что уже ушло, ушло; счётчики не обнулялись.",
      failed:
        "Сбой самого прогона — причина в коде ошибки. Отдельные отказы получателям так рассылку не оценивают.",
    },
    kind: {
      service: "Сервисная",
      marketing: "Маркетинговая",
    },
    kindHint: {
      service:
        "Сообщение, которое продукт обязан отправить клиенту — сбой, изменение цены. Уходит всем, кого выбрала аудитория, кроме отозвавших маркетинговое согласие.",
      marketing:
        "Сообщение, которое продукт хочет отправить — акция, анонс. Уходит только тем, кто дал маркетинговое согласие.",
    },
    recipientState: {
      pending: "В очереди",
      sending: "Отправляется",
      sent: "Доставлено",
      failed: "Ошибка",
      skippedBlocked: "Пропущено — блокировка",
      undeliverable: "Недоставляемо",
      unknown: "Итог неизвестен",
    },
    progress: {
      settledOf: "{settled} из {total} с итогом",
      notStarted: "Пока ничего не отправлено",
    },
    audience: {
      size: "{count} аккаунтов",
      frozenAt: "Зафиксирована {at}",
      frozenNote:
        "Аудитория зафиксирована при составлении рассылки и больше не меняется. Кто пришёл позже — в неё не попал, кто ушёл — всё ещё в ней.",
      written: "записано {written} строк получателей из {size}",
      incomplete:
        "Аудитория ещё записывается, поэтому эти числа не окончательные.",
      everyone:
        "В этой аудитории нет ни одного правила: это КАЖДЫЙ аккаунт, а не пустой выбор.",
      unreadable:
        "Эта сборка не может прочитать сохранённый фильтр. Он был допустим при записи, а более поздняя версия схемы его не понимает; судьба рассылки уже решена.",
      missing: "Вместе с этой рассылкой документ фильтра не сохранялся.",
      chipsLabel: "Зафиксированная аудитория",
    },
    detail: {
      backToList: "Все рассылки",
      loading: "Читаем рассылку…",
      headingAudience: "Аудитория",
      captionAudience:
        "На кого была нацелена рассылка и когда это решили. Только чтение: сменить, кто услышит сообщение, — это новая рассылка.",
      headingMessage: "Сообщение",
      captionMessage:
        "Что видит получатель — ровно то, что уходит в Telegram: по одному тексту на язык и без какой-либо персонализации.",
      headingDelivery: "Доставка",
      captionDelivery:
        "Две версии одной воронки: свод обработчика и те же числа, пересчитанные по строкам получателей. Во время отправки они расходятся — это честная картина, а не ошибка.",
      headingRecipients: "Получатели",
      captionRecipients:
        "По строке на аккаунт, в маскированном виде. Отфильтруйте по итогу, чтобы найти отказы.",
      headingRecord: "Запись",
      rolledUp: "Свод обработчика",
      recounted: "Пересчёт по строкам",
      counters: {
        audience: "Аудитория",
        written: "Строк записано",
        unsettled: "Без итога",
        sent: "Доставлено",
        failed: "Ошибки",
        skipped: "Пропущено",
        undeliverable: "Недоставляемо",
        unknown: "Неизвестно",
        settled: "С итогом",
      },
      countersHint: {
        audience:
          "Сколько насчитал сегмент при составлении. Больше не меняется.",
        written:
          "Сколько строк получателей развёртывание записало на данный момент.",
        unsettled:
          "Строки без итога — ждут очереди или взяты обработчиком прямо сейчас.",
        sent: "Сообщения, принятые Telegram.",
        failed: "Сообщения, отклонённые Telegram, с записанным кодом причины.",
        skipped: "Аккаунты, пропущенные из-за блокировки в любую сторону.",
        undeliverable: "Telegram сообщает, что чата больше нет.",
        unknown:
          "Убитая задача оставила эти строки взятыми, и они никогда не переотправляются. Сообщение вполне могло дойти — это не ошибка и никогда ею не считается.",
        settled:
          "Сумма пяти конечных исходов. Эти пять не обязаны совпасть с размером аудитории.",
      },
      facts: {
        createdBy: "Составил",
        createdAt: "Составлена",
        scheduledFor: "Запланирована на",
        scheduledBy: "Авторизовал",
        startedAt: "Начата",
        finishedAt: "Завершена",
        reasonCode: "Причина",
        reasonRef: "Тикет",
        errorCode: "Код ошибки",
        segmentHash: "Отпечаток аудитории",
        unknownActor: "учётная запись удалена",
        notScheduled: "не запланирована",
        notStarted: "не начиналась",
        notFinished: "не завершена",
        noReason: "не записана",
        noError: "нет",
      },
      body: {
        language: "Язык",
        asSent: "Как это видит получатель",
        renderedLength: "{length} из {limit} символов по счёту Telegram",
        overLimit: "Больше, чем Telegram примет для такого сообщения.",
        image: "Есть изображение",
        imageCached:
          "уже загружено один раз — следующая отправка загрузки не стоит",
        imageNotCached:
          "ещё не загружено — за загрузку заплатит первый получатель",
        noImage: "Без изображения",
        button: "Кнопка: {label} → {url}",
        noButton: "Без кнопки",
        none: "У этой рассылки нет текстов сообщения.",
      },
      recipients: {
        tableCaption: "Получатели этой рассылки, в маскированном виде",
        filterState: "Итог",
        filterStateHint:
          "Несколько сразу — это ИЛИ. «Неизвестно» — самостоятельный итог, он никогда не приписывается к ошибкам.",
        columnRecipient: "Получатель",
        columnLanguage: "Язык",
        columnState: "Итог",
        columnAttempts: "Попыток",
        columnError: "Код ошибки",
        columnSettled: "Итог получен",
        erased: "стёрт по запросу",
        notSettled: "итога нет",
        noError: "—",
        emptyTitle: "Строк получателей пока нет",
        emptyMessage:
          "Аудитория ещё записывается, либо эта рассылка не выбрала никого.",
        emptyFilteredTitle: "Под этот фильтр не подходит ни один получатель",
        emptyFilteredMessage:
          "Строки могут быть у другого итога — снимите фильтр, чтобы их увидеть.",
        noIdColumnNote:
          "Столбца с Telegram ID здесь нет ни для одной роли, и раскрытия, которое его дало бы, тоже нет.",
      },
    },
    actions: {
      send: "Отправить",
      sendAria:
        "Отправить — авторизовать рассылку по зафиксированной аудитории",
      pause: "Приостановить",
      resume: "Продолжить",
      cancel: "Отменить рассылку",
      readOnly: "Ваша роль может читать рассылки, но не отправлять их.",
    },
    sendDialog: {
      title: "Авторизовать эту рассылку",
      description:
        "Это действие, после которого сообщения уходят. Оно записывается в аудит с вашим именем, указанной причиной и размером аудитории.",
      countWarning: "Это сообщение получат {count} человек.",
      frozenNote:
        "Аудитория зафиксирована {at} и сейчас не пересчитывается. Никто из пришедших позже в неё не попал.",
      whenLabel: "Когда",
      whenNow: "Отправить сейчас",
      whenLater: "Запланировать на потом",
      atLabel: "Отправить в",
      atHint:
        "В вашем часовом поясе. Рассылку подхватывает планировщик, а не этот экран.",
      atInPast:
        "Этот момент уже прошёл. Выберите более поздний или отправьте сейчас.",
      atMissing: "Выберите момент отправки.",
      confirmNow: "Отправить сейчас {count} людям",
      confirmLater: "Запланировать для {count} людей",
      pending: "Авторизуем…",
      stepUpNote:
        "Для отправки нужен ваш пароль ещё раз, в рамках этой рассылки. Ничего ещё не ушло: проверка пароля идёт до записи.",
      noRecipients: "У этой рассылки нет строк получателей, отправлять некому.",
    },
    pauseDialog: {
      title: "Приостановить рассылку",
      description:
        "Доставка остановится за секунды. Строки, уже взятые обработчиком, доводятся до итога, а не бросаются, поэтому счётчики ещё немного подрастут — так пауза и работает.",
      confirm: "Приостановить доставку",
      pending: "Приостанавливаем…",
    },
    resumeDialog: {
      title: "Продолжить рассылку",
      description:
        "Доставка продолжится с места остановки. Аудитория не меняется — она зафиксирована при составлении — и никто не получит сообщение дважды.",
      confirm: "Продолжить доставку",
      pending: "Продолжаем…",
    },
    cancelDialog: {
      title: "Отменить рассылку",
      description:
        "Рассылка останавливается окончательно, возобновить её нельзя. Составить заново — это новая рассылка с заново зафиксированной аудиторией.",
      noRecall:
        "Это ничего не отзывает: {count} сообщений уже доставлены и останутся доставленными. Счётчики не обнуляются.",
      confirm: "Отменить рассылку",
      pending: "Отменяем…",
    },
    conflict: {
      title: "Рассылка уже перешла в другое состояние",
      message:
        "Сейчас она: {state}, поэтому это действие больше не применимо. На экране текущее состояние — прочтите его, прежде чем пробовать снова.",
    },
    wizard: {
      title: "Новая рассылка",
      subtitle:
        "Выберите, кто её получит, напишите текст и перечитайте его — до того, как что-либо уйдёт.",
      subject: "Эта рассылка",
      stepsAria: "Шаги рассылки",
      stepOf: "{index} из {total} · {name}",
      back: "Назад",
      next: "Далее: {name}",
      readOnlyTitle: "Для составления рассылки нужны права на рассылки",
      readOnlyMessage:
        "Ваша роль видит рассылки и их доставку, но не может составлять и отправлять их. Попросите администратора отправить её или расширить вашу роль.",
      createdNote:
        "Рассылка создана, её аудитория зафиксирована: {count} аккаунтов. Пока ничего не отправлено.",
      createdLink: "Открыть рассылку",
      steps: {
        audience: "Аудитория",
        message: "Сообщение",
        review: "Проверка и отправка",
      },
      audience: {
        heading: "Кто это получит",
        caption:
          "Соберите аудиторию из полей, которые публикует сервер. Число ниже точное — именно на него выдаётся разрешение на отправку.",
        builderLabel: "Аудитория рассылки",
        frozenLocked:
          "Эта аудитория зафиксирована: строки получателей уже созданы, а фильтр стал записью о том, кто был выбран. Написать другим людям — это новая рассылка.",
        everyoneWarning:
          "Правил нет: это КАЖДЫЙ аккаунт, а не пустой выбор. Добавьте правило, если вы не имели в виду всю базу.",
        registryFailedTitle: "Не удалось прочитать поля аудитории",
        registryForbidden:
          "Ваша роль не может читать словарь аудитории, поэтому конструктор не показан.",
        refusalCounting:
          "Считаем аудиторию… следующий шаг откроется, когда придёт число.",
        refusalInvalid:
          "В аудитории есть правило, которое сервер отклонит. Исправьте отмеченное выше правило.",
        refusalNobody:
          "В этой аудитории некому доставить сообщение, поэтому и писать его не для кого. Расширьте её или проверьте, кто заблокирован.",
        refusalUnreadable:
          "Поля аудитории недоступны, поэтому проверить эту аудиторию нельзя.",
        counting: "Считаем…",
        countForbidden: "Ваша роль не может считать аудиторию.",
        countFailed: "Не удалось посчитать аудиторию: {message}",
        reachable: "Сообщение получат {count} человек",
        matched:
          "{matched} подходят под фильтр · {blocked} заблокированы нами · {botBlocked} заблокировали бота. Две последние группы пересекаются; аудитория — это первое число.",
        byLanguage: "По языкам: {split}",
        sampleShow: "Показать несколько аккаунтов",
        sampleHide: "Скрыть выборку",
        sampleCaption:
          "{count} аккаунтов из этой аудитории — с тем же маскированием, что и в справочнике.",
        sampleAccount: "Аккаунт",
        sampleLanguage: "Язык",
        sampleJoined: "Первый контакт",
        sampleEmpty: "Под этот фильтр никто не подходит, показывать нечего.",
        sampleFailed: "Не удалось прочитать выборку: {message}",
        sampleNote:
          "Это проверка на здравый смысл, а не сама аудитория: откройте справочник с тем же фильтром, чтобы пролистать её целиком, по {limit} за раз.",
      },
      message: {
        heading: "Что там написано",
        caption:
          "Заголовок — наш, по нему рассылка находится. Сообщение — то, что читает клиент.",
        titleLabel: "Заголовок рассылки",
        titleHint: "Внутренний — получателю он не уходит. До {limit} символов.",
        titleMissing: "У рассылки должен быть заголовок.",
        kindLabel: "Тип",
        bodiesHeading: "Сообщение",
        bodiesCaption:
          "По одному сообщению на каждый язык аудитории. Язык, который в ней никто не читает, не предлагается; язык, который читают, пропустить нельзя.",
        noLanguages:
          "У этой аудитории пока нет языков, поэтому писать нечего. Вернитесь и проверьте счёт.",
        languagesAria: "Языки этой аудитории",
        languageReady: "готово",
        languageMissing: "не написано",
        bodyLabel: "Сообщение на языке: {language}",
        counter:
          "{sent} из {limit} символов так, как их считает Telegram (набрано {typed}).",
        markupHint:
          "Только разметка Telegram: {tags}. Каждый тег должен быть закрыт, а ссылке нужен абсолютный http(s)-адрес.",
        imageLabel: "Изображение (необязательно)",
        imageHint:
          "Ключ файла, который уже лежит в нашем хранилище. С изображением предел сообщения падает до 1 024 символов.",
        buttonLabelLabel: "Подпись кнопки (необязательно)",
        buttonHint:
          "Кнопке нужны и подпись, и ссылка — либо ни того, ни другого.",
        buttonUrlLabel: "Ссылка кнопки (необязательно)",
        buttonUrlHint: "Абсолютный http(s) с публичным хостом.",
        previewHeading: "Как это увидит получатель",
        previewCaption:
          "Строится тем же разбором, которым меряется длина: чего нет здесь — не будет и в отправке.",
        previewAria: "Предпросмотр сообщения на языке: {language}",
        previewEmpty: "Пока ничего не написано.",
        previewImage: "Прикреплено изображение: {key}",
        previewSpoiler: "Скрыто, пока получатель не нажмёт на него в Telegram.",
        previewUnparsed:
          "Предпросмотр невозможен, пока разметка ниже не исправлена.",
        incomplete: "Ещё нужно написать: {languages}.",
        issues: {
          empty: "Для этого языка сообщение ещё не написано.",
          blankText: "После разбора разметки в сообщении не остаётся слов.",
          incompleteTag: "У тега не хватает закрывающей «>».",
          unknownTag: "Такой HTML-тег Telegram не принимает.",
          badAttribute:
            "У тега есть недопустимый атрибут. Атрибут href разрешён только у ссылки.",
          selfClosing:
            "Самозакрывающийся тег — это не разметка Telegram; напишите пару.",
          unbalanced: "Тег не закрыт или закрывает тот, который не открывали.",
          nestedLink: "Ссылка не может содержать другую ссылку.",
          notMarkup:
            "В тексте есть комментарий или объявление — это не разметка.",
          badHref: "Адрес ссылки должен быть абсолютным http(s)-URL.",
          tooLong:
            "{actual} символов, а Telegram принимает {limit}. Амперсанды и теги на проводе стоят дороже, чем в поле ввода.",
          badUrl:
            "Ссылка кнопки должна быть абсолютным http(s)-URL с публичным хостом.",
          buttonPair:
            "Кнопке нужны и подпись, и ссылка — либо ни того, ни другого.",
          badStorageKey:
            "Это не ключ хранилища, который записало это развёртывание.",
        },
        testSend: {
          action: "Отправить тестовую копию",
          actionAria:
            "Отправить тестовую копию — доставить это сообщение одному аккаунту из списка",
          title: "Отправить тестовую копию",
          description:
            "Составленное сообщение уходит одному аккаунту, чтобы его можно было прочитать в Telegram. Действие записывается в журнал аудита.",
          freezeWarning:
            "Для тестовой отправки рассылка должна существовать, поэтому подтверждение ЗАФИКСИРУЕТ аудиторию прямо сейчас. Самой аудитории ничего не уйдёт, пока вы не подтвердите отправку на следующем шаге.",
          allowlistNote:
            "Получить её могут только аккаунты из списка тестовых получателей этого развёртывания; этот список — конфигурация, а не право доступа.",
          recipientLabel: "Telegram id тестового получателя",
          recipientHint:
            "Только цифры. Аккаунт должен быть в списке тестовых получателей.",
          confirm: "Отправить тестовую копию",
          pending: "Отправляем…",
          sent: "Отправлено на {recipient}. Прочитайте в Telegram, прежде чем подтверждать рассылку.",
          refusedTitle: "Тестовая отправка отклонена",
          refusedMessage:
            "Получателя нет в списке тестовых получателей этого развёртывания. Список поставляется пустым и задаётся в окружении админ-панели — попросите ответственного добавить аккаунт.",
          subject: "Тестовая отправка",
        },
      },
      review: {
        audienceHeading: "Аудитория",
        audienceCaption: "Число, на которое выдаётся разрешение на отправку.",
        audienceCount: "Сообщение получат {count} человек",
        audienceFrozenCount: "Строк получателей создано и ждёт: {count}",
        freezeWarning:
          "Отправка сначала фиксирует аудиторию: получатели определяются в этот момент и больше не пересчитываются. Кто присоединится потом — в неё не попадёт, а кто уйдёт — всё равно останется.",
        audienceRulesAria: "Аудитория, которая будет зафиксирована",
        messageHeading: "Сообщение",
        messageCaption: "Ровно то, что получит каждый язык.",
        sendHeading: "Отправка",
        sendCaption:
          "Это действие отправляет сообщения. Оно записывается с вашим именем, вашей причиной и размером аудитории.",
        confirmLabel: "Введите {count}, чтобы подтвердить аудиторию",
        confirmHint: "Последняя проверка перед отправкой: наберите число выше.",
        confirmMismatch: "Это не размер аудитории. Введите {count}.",
        submitNow: "Зафиксировать аудиторию и отправить {count} людям сейчас",
        submitLater:
          "Зафиксировать аудиторию и запланировать для {count} людей",
        pending: "Отправляем…",
        stepUpNote:
          "Для отправки снова нужен ваш пароль — в рамках этой рассылки. Пока ничего не ушло: проверка пароля идёт до записи.",
        driftTitle: "Аудитория изменилась с момента подсчёта",
        driftMessage:
          "Вам показали {expected} аккаунтов; сейчас фильтр выбирает {actual}. Ничего не создано.",
        driftReview: "Вернуться и перечитать аудиторию",
        driftInsist: "Зафиксировать как есть сейчас ({count})",
      },
    },
  },
  segments: {
    title: "Расширенный сегмент",
    description:
      "Соберите аудиторию из полей, которые публикует сервер. Здесь нет ни имени, ни номера телефона, ни текста сообщений — только факты об аккаунте.",
    builderLabel: "Правила сегмента",
    everyone: "Правил пока нет — выбраны все.",
    everyoneWarning:
      "Пустой сегмент — это не суженный сегмент: под него попадает каждый аккаунт в базе.",
    frozenNote:
      "Аудитория фиксируется в момент создания рассылки. Изменение сегмента после этого ничего не меняет в уже запланированной рассылке.",
    readOnlyNote: "Эта аудитория зафиксирована и больше не редактируется.",
    summary:
      "Правил: {rules} из {maxRules} · вложенность {depth} из {maxDepth}",
    addRule: "Добавить правило",
    addGroup: "Добавить группу",
    removeRule: "Удалить это правило",
    removeGroup: "Удалить эту группу",
    clearAll: "Очистить сегмент",
    fieldLabel: "Поле",
    conditionLabel: "Условие",
    valueLabel: "Значение",
    chooseField: "Выберите поле…",
    unknownField: "{key} — больше не предлагается",
    unavailableField:
      "Требуется таблица {capability}, которой нет в этой установке.",
    unavailableOption: "{label} — здесь недоступно",
    aggregateField:
      "Считается по другим таблицам, поэтому такое правило дороже выполняется.",
    groupLabel: "Группа с условием «{mode}»",
    ruleLabel: "Правило {index}",
    depthLimitReached: "Вложенность достигла серверного предела в {maxDepth}.",
    ruleLimitReached:
      "В сегменте уже {maxRules} правил — это серверный предел.",
    matchLabel: "Как они сочетаются",
    loading: "Читаем реестр полей…",
    loadFailed:
      "Реестр полей не удалось прочитать, поэтому правило составить нельзя.",
    forbidden:
      "У вашей роли нет доступа к рассылкам, поэтому реестр полей закрыт.",
    match: {
      all: "Все",
      any: "Любое",
      none: "Ни одно",
    },
    heading: {
      all: "Аккаунты, подходящие под ВСЕ условия:",
      any: "Аккаунты, подходящие хотя бы под ОДНО условие:",
      none: "Аккаунты, не подходящие НИ ПОД ОДНО условие:",
    },
    ops: {
      eq: "равно",
      neq: "не равно",
      in: "одно из",
      not_in: "ни одно из",
      gt: "больше чем",
      gte: "не меньше",
      lt: "меньше чем",
      lte: "не больше",
      between: "в диапазоне",
      is_true: "да",
      is_false: "нет",
      is_null: "не происходило",
      is_not_null: "происходило",
      within_last_days: "за последние N дней",
      not_within_last_days: "не за последние N дней",
      within_next_days: "в ближайшие N дней",
    },
    opsInstant: {
      gt: "после",
      gte: "начиная с",
      lt: "до",
      lte: "не позже",
      is_null: "не происходило",
      is_not_null: "происходило",
    },
    opHints: {
      between: "Полуинтервал: первая граница входит, вторая — нет.",
      not_within_last_days:
        "Там, где поле может быть пустым, сюда попадают и аккаунты, у которых этого не было никогда.",
      within_next_days:
        "Отсчёт идёт вперёд от текущего момента и никогда не смотрит в прошлое.",
      in: "Несколько значений внутри одного поля читаются как ИЛИ.",
    },
    value: {
      number: "Число",
      numberFrom: "От",
      numberTo: "До (не включая)",
      date: "Дата",
      dateFrom: "С",
      dateTo: "По (не включая)",
      wholeMonth: "Целый месяц",
      wholeMonthHint:
        "Заполняет обе границы этим месяцем в вашем часовом поясе.",
      days: "Дней",
      daysPreset: "{days} дн.",
      daysRange: "От {min} до {max} дней.",
      none: "Это условие не требует значения.",
      members: "Значения",
      memberPlaceholder: "Добавьте значение",
      addMember: "Добавить",
      removeMember: "Удалить {value}",
      memberCount: "{count} из {max} значений",
      empty: "Выберите хотя бы одно значение.",
    },
    sort: {
      label: "Порядок результатов",
      key: "Сортировать по",
      direction: "Направление",
      asc: "Сначала наименьшие",
      desc: "Сначала наибольшие",
      registryDefault: "Порядок по умолчанию (первый контакт, сначала новые)",
      narrowsNothing:
        "Сортировка задаёт порядок аудитории, но никогда её не сужает. Для этого добавьте правило.",
      aggregateCost:
        "Эта сортировка считается по другим таблицам, поэтому точный итог рядом с ней запрещён.",
      nullsSortLow:
        "Аккаунты без этого события сортируются как ноль или как начало эпохи.",
    },
    issues: {
      heading: "Исправьте это, прежде чем использовать сегмент",
      maxRules: "Правил {actual}, а сервер принимает не более {limit}.",
      maxDepth: "Вложенность {actual}, а сервер принимает не более {limit}.",
      maxValueMembers:
        "В поле «{field}» {actual} значений, а сервер принимает не более {limit}.",
      maxAggregateRules:
        "{actual} правил считаются по другим таблицам, а сервер принимает не более {limit}.",
      emptyGroup: "Во вложенной группе должно быть хотя бы одно правило.",
      missingValue: "Для поля «{field}» нужно значение.",
      unknownField: "«{field}» — такого поля сервер не публикует.",
      unavailableField:
        "Для поля «{field}» нужна таблица, которой нет в этой установке.",
      unsupportedOp: "Поле «{field}» не принимает это условие.",
      betweenIncomplete: "Для поля «{field}» нужны обе границы диапазона.",
      betweenOrder: "У поля «{field}» конец диапазона раньше начала.",
      daysOutOfRange:
        "Для поля «{field}» число дней должно быть от {min} до {max}.",
      unsortableKey: "По полю «{field}» сортировать нельзя.",
      versionMismatch:
        "Эта панель пишет документы версии {expected}, а сервер запросил версию {actual}. Перезагрузите страницу перед сбором аудитории.",
    },
    chips: {
      label: "Правила сегмента",
      rule: "{op} {value}",
      separatorAnd: "и",
      separatorOr: "или",
      separatorNone: "ни",
    },
    fields: {
      telegram_user_id: "Telegram id",
      ui_language: "Язык бота",
      is_blocked: "Заблокирован нами",
      bot_blocked: "Заблокировал бота",
      bot_blocked_at: "Заблокировал бота когда",
      joined_at: "Первый контакт",
      last_activity_at: "Последняя активность",
      is_reachable: "Доступен для рассылки",
      has_profile: "Есть профиль",
      has_phone: "Есть телефон",
      has_username: "Есть username",
      has_avatar: "Есть аватар",
      onboarded_at: "Завершил онбординг",
      phone_shared_at: "Поделился телефоном",
      language_chosen_at: "Выбрал язык",
      has_credit_account: "Есть кредитный счёт",
      credit_balance: "Баланс кредитов",
      lifetime_credits_granted: "Начислено кредитов за всё время",
      first_metered_at: "Первое списание",
      order_count: "Заказы",
      paid_order_count: "Оплаченные заказы",
      delivered_order_count: "Доставлено песен",
      failed_order_count: "Неудачные заказы",
      first_order_at: "Первый заказ",
      last_order_at: "Последний заказ",
      last_delivered_at: "Последняя доставка",
      order_state: "Состояние заказа",
      plan_status: "Состояние подписки",
      plan_ends_at: "Подписка заканчивается",
      plan_purchase_count: "Куплено подписок",
      topup_count: "Пополнения",
      topup_spend_minor: "Сумма пополнений, в минорных единицах",
      last_topup_at: "Последнее пополнение",
      has_paid_ever: "Когда-либо платил",
      has_abandoned_checkout: "Бросил оплату",
      bot_block_event_count: "Сколько раз блокировал бота",
      has_returned_after_block: "Вернулся после блокировки",
      inbound_message_count: "Отправленных сообщений",
      last_inbound_message_at: "Последнее сообщение от него",
      wizard_step: "Шаг мастера",
    },
    members: {
      ui_language: {
        uz_latn: "Узбекский (латиница)",
        uz_cyrl: "Узбекский (кириллица)",
        ru: "Русский",
        en: "Английский",
      },
      order_state: {
        draft: "Черновик",
        brief_ready: "Бриф готов",
        lyrics_ready: "Текст готов",
        authorized: "Оплата подтверждена",
        generating: "Генерируется",
        delivered: "Доставлен",
        failed: "Ошибка",
        cancelled: "Отменён",
      },
      plan_status: {
        none: "Никогда не покупал подписку",
        active: "Подписка действует, песни остались",
        exhausted: "Подписка действует, песни закончились",
        lapsed: "Подписка истекла и не куплена снова",
      },
    },
  },
  billing: {
    title: "Платёжный канал",
    stats: {
      intents: "Открытые платежи",
      settled: "Завершено",
      faults: "Сбойные входящие вызовы",
      attention: "Требуют вмешательства",
      ofPayments: "{count} платежей",
      period: {
        label: "Период",
        day: "День",
        week: "Неделя",
        month: "Месяц",
        year: "Год",
      },
    },
    range: {
      onPage: "{count} на этой странице",
      onPageOf: "{count} из {total}",
    },
    subject: "Канал",
    subjectPayments: "Платежи",
    subjectPayment: "Этот платёж",
    subjectCalls: "Входящие вызовы",
    attention: {
      awaitingStale: "Держится дольше таймаута канала",
      paidUnnotified: "Оплачено, но не объявлено",
      paidNoReceipt: "Оплачено, продажа не записана",
    },
    lookup: {
      label: "Ссылка или идентификатор транзакции Payme",
      placeholder: "a1b2c3d4e5f60718293a4b5c",
      submit: "Найти",
      malformed:
        "Это не ссылка. И ссылка на платёж, и идентификатор транзакции Payme — ровно 24 шестнадцатеричных символа.",
      noMatch: "На этой установке нет платежа с такой ссылкой.",
      matchedRef: "Совпало с нашей ссылкой на платёж.",
      matchedTransaction: "Совпало с идентификатором транзакции Payme.",
    },
    intents: {
      title: "Платежи",
      caption: "Платежи",
      columns: {
        opened: "Открыт",
        reference: "Ссылка",
        state: "Состояние",
        product: "Продукт",
        amount: "Сумма",
        buyer: "Покупатель",
        rail: "Канал",
        settled: "Завершён",
        chain: "Цепочка",
      },
      buyerErased: "покупатель удалён",
      settledByRail: "через Payme",
      settledByOperator: "вручную",
      notSettled: "не завершён",
      railNever: "не открывалась",
      railTransactions: "{count} × {state}",
      chainReceipt: "продажа",
      chainGrant: "кредит",
      chainNotified: "сообщено",
      chainNone: "пока ничего",
      sandboxBadge: "песочница",
      planShape: "{songs} песен · {days} дней",
      emptyVirgin: "Здесь ни разу не открывали платёж",
      emptyFiltered: "Ни один платёж не подходит под фильтры",
      emptyFailed: "Список платежей не загрузился",
      chips: {
        state: "Состояние",
        product: "Продукт",
        settledBy: "Завершил",
        attention: "Требует внимания",
        sandbox: "Песочница",
        openedFrom: "Открыт с",
        openedThrough: "Открыт по",
      },
    },
    lifeline: {
      title: "Что стало с этими деньгами",
      steps: {
        opened: "Оплата открыта",
        railTransaction: "Payme открыла транзакцию",
        performed: "Payme списала деньги",
        receipt: "Продажа записана",
        creditGranted: "Кредит выдан",
        customerTold: "Клиенту сообщено",
      },
      status: {
        done: "выполнено",
        pending: "ещё нет",
        notApplicable: "неприменимо",
        missing: "отсутствует",
      },
      notes: {
        neverOpened:
          "Payme ни разу не открывала транзакцию по этому платежу. Так же выглядит платёж, закрытый вручную.",
        awaitingRail:
          "Транзакция открыта, и канал пока не ответил. Наши часы и часы Payme — разные часы, поэтому это ожидание, а не опоздание.",
        buyerErased:
          "Покупатель попросил себя забыть. Деньги прошли, а выдавать кредит и сообщать уже некому — это состояние, а не расхождение.",
        planGrantsNothing:
          "Тариф выдаёт песни по мере использования, поэтому при покупке кредит не начисляется.",
        notSettled:
          "Этот платёж не завершился, поэтому всё последующее и не должно было произойти.",
        alreadyTold: "Подтверждение отправлено.",
        purged:
          "Строка, где это было записано, удалена по сроку хранения. Событие было; свидетельство устарело и удалено.",
      },
    },
    dossier: {
      title: "Платёж {reference}",
      back: "Все платежи",
      notFound: "Платежа с таким идентификатором нет",
      notFoundMessage:
        "На этой установке нет платежа с таким идентификатором. Проверьте ссылку в поле поиска на доске.",
      intentPanel: "Платёж",
      transactionsPanel: "Транзакции Payme",
      receiptPanel: "Продажа",
      ledgerPanel: "Журнал кредитов",
      callsPanel: "Вызовы Payme по этому платежу",
      chainStopPanel: "Стало ли это песней?",
      transactionsNone:
        "Payme ни разу не открывала транзакцию по этому платежу.",
      receiptNone: "По этому платежу продажа не записана.",
      ledgerNone: "По этому платежу не записано ни одного движения кредитов.",
      callsNever: "Payme ни разу не обращалась к нам по поводу этого платежа.",
      callsPurged:
        "Этот платёж старше 90 дней, которые хранится журнал входящих, поэтому его вызовы удалены по сроку. Удалены, а не отсутствовали.",
      chainStopSingle:
        "Ответа нет по устройству системы. Баланс кредитов — одно число без партий, поэтому ни один запрос не докажет, какую песню оплатил купленный кредит.",
      chainStopPlan: "Использовано {used} из {included} песен по тарифу.",
      chainStopPlanUnknown:
        "Запись о покупке тарифа не найдена, поэтому песни по нему никто не считает.",
      settleByHand: "Закрыть вручную",
      settleByHandCaveat:
        "Консоль этого не делает и не предложит. Команда выполняется в терминале и только после того, как списание по этой ссылке подтверждено в кабинете Payme, который этот процесс не имеет права видеть.",
      copyCommand: "Скопировать команду",
      copied: "Скопировано",
      fields: {
        reference: "Ссылка",
        state: "Состояние",
        product: "Продукт",
        amount: "Сумма",
        buyer: "Покупатель",
        merchant: "Касса",
        opened: "Открыт",
        validUntil: "Действует до",
        settled: "Завершён",
        notified: "Подтверждение отправлено",
        settleNote: "Кем завершён",
        cancelReason: "Причина отмены",
        performTime: "Проведена",
        createTime: "Создана",
        cancelTime: "Отменена",
        paymeTime: "Часы Payme",
        source: "Записано в",
        provider: "Провайдер",
        cabinetReference: "Ссылка в кабинете",
        creditsGranted: "Выдано кредитов",
        songsIncluded: "Песен в тарифе",
        songsUsed: "Песен использовано",
        planEndsAt: "Тариф до",
        kind: "Вид",
        delta: "Изменение",
        reason: "Причина",
        actor: "Кем записано",
      },
    },
    notify: {
      action: "Отправить подтверждение ещё раз",
      pending: "Ставим в очередь…",
      confirmTitle: "Отправить подтверждение ещё раз?",
      confirmBody:
        "Клиент получит сообщение о платеже, который уже совершил. Ничего не списывается, кредит не выдаётся, денежные строки не пишутся. Двойное нажатие отправит одно сообщение.",
      confirmLabel: "Отправить подтверждение",
      refusalNotPaid: "Этот платёж не завершён, подтверждать нечего.",
      refusalBuyerErased:
        "Покупатель попросил себя забыть. Отправлять некому; продажа и кредит не тронуты.",
      refusalAlreadyNotified:
        "Подтверждение уже отправлено. Задача останавливается на этой отметке, поэтому повтор ничего не даст.",
      sent: "Поставлено в очередь. Воркер отправит в течение минуты.",
      replayed:
        "Уже в очереди — это нажатие ничего не изменило, и так и должно быть.",
      reasonLabel: "Почему отправляем повторно",
      reasonHint:
        "Попадёт в журнал аудита на ваше имя. Ваши слова, а не слова клиента.",
      notDelivered:
        "Здесь записано, что мы отправили. Увидел ли клиент — факт на стороне Telegram, которого в этой базе нет.",
    },
    pause: {
      pauseAction: "Приостановить оплату",
      resumeAction: "Возобновить оплату",
      pauseTitle: "Приостановить выдачу оплат?",
      pauseBody:
        "Бот перестанет выдавать новые ссылки на оплату. На платежи в процессе это не влияет, деньги никуда не двигаются. Любой оператор вернёт это одним нажатием.",
      pauseLabel: "Приостановить оплату",
      pausePending: "Приостанавливаем…",
      resumeTitle: "Возобновить выдачу оплат?",
      resumeBody:
        "Бот снова начнёт выдавать ссылки на оплату. Ничего из того, что случилось на паузе, не повторяется.",
      resumeLabel: "Возобновить оплату",
      resumePending: "Возобновляем…",
      reasonLabel: "Почему переключаем",
      reasonHint:
        "Попадёт в журнал аудита на ваше имя. Достаточно одной строки.",
    },
    calls: {
      title: "Входящие вызовы",
      subtitle: "Каждый JSON-RPC вызов Payme к этой установке, сначала новые.",
      caption: "Входящие вызовы от Payme",
      columns: {
        at: "Когда",
        method: "Метод",
        replyCode: "Ответ",
        reference: "Ссылка",
        transactionId: "Транзакция Payme",
        duration: "Заняло",
        peerIp: "Узел",
      },
      peerIpNote: "Дата-центр Payme, а не клиент.",
      faultsOnly: "Только ошибки",
      allCalls: "Все вызовы",
      empty: "Payme ни разу не обращалась к этому адресу",
      emptyMessage:
        "На работающем канале так же выглядит платёж, закрытый вручную, поэтому это никогда не значит «шлюз лежит».",
      emptyFiltered: "Ни один вызов не подходит под фильтры",
      emptyFilteredMessage:
        "Вызовы на этой установке есть, но ни один не попадает в выбранный интервал или вид.",
      emptyFailed: "Журнал не загрузился",
      emptyFailedMessage:
        "В примечании выше — ответ сервера и идентификатор корреляции, который стоит указать.",
      chips: {
        method: "Метод",
        faultsOnly: "Только ошибки",
        reference: "Ссылка",
        transactionId: "Транзакция Payme",
        from: "С",
        through: "По",
      },
    },
  },
  support: {
    title: "Поддержка",
    subject: "очередь обращений",
    subjectOne: "это обращение",
    subjectBoard: "доска поддержки",
    atLeast: "не менее {count}",
    refresh: "Обновить",
    backToBoard: "Назад к доске",
    openTicket: "Открыть обращение",
    tableCaption: "Обращения в поддержку, сначала новые",
    filtersAria: "Фильтры обращений",
    subtitles: {
      reading: "Читаем очередь…",
      failed: "Очередь прочитать не удалось",
      onThisPage: "{count} на этой странице",
      tickets: "{count} обращений",
      ticketsFiltered: "{count} обращений подходят под фильтры",
    },
    range: {
      onPage: "{count} на этой странице",
      onPageOf: "{count} из {total}",
      none: "Обращений пока нет",
      noneMatching: "Ни одно обращение не подходит под фильтры",
    },
    board: {
      aria: "Доска поддержки, четыре колонки",
      columnAria: "{status}, обращений: {count}",
      cardAria: "Обращение {reference} от {customer}, {status}",
      columnCount: "{count} в этой колонке",
      empty: "В этой колонке пусто",
      emptyFiltered: "Здесь ничего не подходит под фильтры",
      loading: "Читаем доску…",
      undescribedHidden:
        "Обращения без описания на доску не попадают — человек нажал кнопку и ничего не написал. Эти записи сохраняются, искать их нужно в списке.",
      dropHere: "Перенести в «{status}»",
      cannotDropHere: "Обращение из «{from}» нельзя перенести в «{to}»",
    },
    status: {
      new: "Новое",
      inProgress: "В работе",
      waiting: "Ждём клиента",
      resolved: "Решено",
    },
    statusHint: {
      new: "Сюда ещё никто не заглядывал. Обратно в эту колонку ничего не возвращается.",
      inProgress: "Обращение у кого-то в работе, и клиент ждёт нас.",
      waiting:
        "Мы задали клиенту вопрос, и ответ за ним. Пока он не напишет, здесь ничего не сдвинется.",
      resolved:
        "Ответили и закрыли. Ответ клиента снова открывает обращение в «В работе», а дата закрытия сохраняется.",
    },
    source: {
      deliveryButton: "Готовая песня",
      supportCommand: "/support",
    },
    sourceHint: {
      deliveryButton:
        "Открыто кнопкой под готовой песней, поэтому заказ известен.",
      supportCommand:
        "Набрано где угодно в боте, поэтому заказа нет. Очередь та же самая.",
    },
    card: {
      reference: "Номер",
      customer: "Клиент",
      order: "Заказ",
      noOrder: "Без заказа",
      opened: "Открыто",
      updated: "Последнее изменение",
      assignee: "У кого",
      unassigned: "Ни у кого",
      events: "записей: {count}",
      language: "Язык обращения",
      body: "Что нам написали",
      noBody: "Описание не оставили",
      noBodyHint:
        "Клиент открыл обращение и ничего не написал. Запись сохраняется: это единственная мера того, сколько людей попытались нам сказать и бросили.",
      inGroup: "Отправлено в группу поддержки",
      notInGroup: "В группе поддержки нет",
      notInGroupHint:
        "Карточка ещё не отправлена, либо группа поддержки на этом стенде не настроена. Обращение не потеряно, и номер у клиента есть.",
      resolvedAt: "Закрыто",
      reopened: "Открыто снова",
      reopenedHint:
        "Обращение уже закрывали, и оно вернулось. Дата закрытия сохраняется намеренно.",
    },
    actions: {
      move: "Перенести",
      moveTo: "Перенести в «{status}»",
      claim: "Взять себе",
      assign: "Передать",
      reply: "Ответить клиенту",
      note: "Внутренняя заметка",
      reopen: "Открыть снова",
      resolve: "Решено",
      pickColumn: "Выберите колонку",
      readOnly: "Ваша роль позволяет читать обращения, но не отвечать на них.",
      cancel: "Отмена",
    },
    dialogs: {
      assign: {
        title: "Передать обращение оператору",
        label: "Имя оператора",
        placeholder: "dilnoza",
        hint: "Список операторов не проверяется: имя записывается как есть, чтобы ушедший оператор не унёс с собой историю очереди.",
        submit: "Передать",
        pending: "Передаём…",
        invalid:
          "Только строчные латинские буквы, цифры, точки, дефисы и подчёркивания.",
      },
      reply: {
        title: "Ответить клиенту",
        label: "Ваш ответ",
        placeholder: "Пишите на том языке, на котором открыто обращение.",
        hint: "Уйдёт клиенту в бот, на том языке, на котором он написал нам.",
        submit: "Отправить",
        pending: "Отправляем…",
        warning: "Эти слова попадут человеку в телефон. Отозвать их нельзя.",
        remaining: "осталось символов: {count}",
      },
      note: {
        title: "Внутренняя заметка",
        label: "Заметка",
        placeholder: "Что нужно знать следующему оператору.",
        hint: "Останется в истории обращения рядом со всем остальным, что с ним происходило.",
        submit: "Сохранить заметку",
        pending: "Сохраняем…",
        warning:
          "Клиент этого не увидит — и сотрудники, работающие с карточкой в группе Telegram, тоже.",
      },
      move: {
        title: "Перенести обращение",
        body: "Переносим в «{status}».",
        reopenBody:
          "Открываем обращение снова, в «{status}». Дата закрытия сохраняется, поэтому видно, что жалоба вернулась.",
        submit: "Перенести",
        pending: "Переносим…",
      },
    },
    timeline: {
      title: "Что происходило",
      empty: "С этим обращением пока ничего не происходило",
      relayed: "Доставлено {when}",
      notRelayed: "Не доставлено",
      notRelayedHint:
        "Ответ написан и до клиента не дошёл. Возможно, он заблокировал бота или в момент отправки не работал воркер.",
      statusMove: "{from} → {to}",
      assignedTo: "Передано: {username}",
      unknownAuthor: "Неизвестно",
      kind: {
        opened: "Обращение открыто",
        described: "Клиент описал проблему",
        statusChange: "Перенесено",
        note: "Внутренняя заметка",
        reply: "Ответ клиенту",
        assigned: "Передано",
        groupPosted: "Отправлено в группу поддержки",
      },
      author: {
        customer: "Клиент",
        operator: "Оператор",
        staffGroup: "Сотрудник, в группе Telegram",
        system: "Система",
      },
    },
    dnd: {
      instructions:
        "Пробел — взять обращение, стрелки — выбрать колонку, пробел ещё раз — перенести, Escape — вернуть на место.",
      grabbed:
        "Обращение {reference} взято из колонки «{status}». Выберите колонку стрелками.",
      dropped: "Обращение {reference} возвращено в «{status}».",
      moved: "Обращение {reference} перенесено из «{from}» в «{to}».",
      cancelled:
        "Перенос отменён. Обращение {reference} осталось в «{status}».",
      blocked: "Обращение из «{from}» нельзя перенести в «{to}».",
    },
    empty: {
      title: "Нам никто не писал",
      message:
        "Обращение появляется, когда клиент нажимает кнопку под готовой песней или набирает /support в боте.",
      filteredTitle: "Ни одно обращение не подходит под фильтры",
      filteredMessage:
        "Обращения есть, но ни одно не попадает в выбранный период или вид.",
    },
    notes: {
      forbiddenMessage:
        "Вашей роли это читать нельзя. Повтор ничего не изменит и лишь запишет ещё один отказ.",
      sessionEndedMessage:
        "{message} Войдите снова — очередь останется там же.",
      refusedFiltersMessage: "{message} Сузьте фильтры и повторите.",
      notFoundMessage:
        "Обращения с таким идентификатором нет. Возможно, оно удалено по просьбе клиента — обращения удаляются, а не обезличиваются.",
      conflictTitle: "Обращение уже перенесли",
      conflictMessage:
        "Пока вы читали, его перенёс кто-то другой — чаще всего сотрудник нажал кнопку на карточке в группе Telegram. Ничего не записано, обращение перечитывается.",
      workerTitle: "Воркер недоступен",
      workerMessage:
        "Ничего не записано. Изменение должно дойти до карточки в группе Telegram, поэтому действие отклоняется целиком, а не наполовину — иначе доска и карточка навсегда разошлись бы.",
    },
    filter: {
      status: "Колонка",
      statusHint: "Где обращение сейчас.",
      source: "Откуда открыто",
      sourceHint: "Через какую дверь пришло. Обе создают одинаковые обращения.",
      language: "Язык обращения",
      languageHint:
        "Язык, на котором обращение открыто, — тот, на котором нужно отвечать.",
      assignedTo: "У кого",
      assignedToHint:
        "Точное имя, и намеренно не часть поиска: «обращения Дилнозы» и «обращения, где упомянута Дилноза» — разные вопросы.",
      search: "Номер или слова",
      searchHint: "Ищет по номеру и по словам самого клиента.",
      onlyDescribed: "Только с описанием",
      onlyDescribedHint:
        "Скрыть обращения, которые открыли и не заполнили. На доске их не бывает никогда.",
    },
    chips: {
      status: "Колонка",
      source: "Откуда открыто",
      language: "Язык обращения",
      assignedTo: "У кого",
      search: "Поиск",
      onlyDescribed: "Только с описанием",
      join: ", ",
    },
    groups: {
      open: "Группа поддержки",
      title: "Куда отправляются карточки обращений",
      subject: "группу поддержки",
      subtitle:
        "Обращения регистрируются в любом случае. Здесь — та группа в Telegram, куда бот отправляет карточку нового обращения, и проверено ли, что он вообще может туда писать.",
      constraint:
        "Telegram не даёт боту список своих групп — он узнаёт о группе, только когда его в неё добавляют. Группу, где бот был раньше, добавьте по chat id.",
      close: "Закрыть",
      refresh: "Обновить",
      known: "Чаты, о которых знает бот",
      listAria: "Чаты, о которых знает бот",
      loading: "Читаем справочник чатов…",
      emptyMessage:
        "Пока ничего не записано. Добавьте бота в группу — и она появится здесь, либо вставьте chat id ниже.",
      readOnly:
        "Ваша роль видит группу, но не может её менять. Нужно право support.group.write.",
      botStatusHint:
        "Что Telegram сказал о положении бота здесь в последний раз, на тот момент. Это свидетельство, а не разрешение: только проверка доказывает, что бот может писать.",
      current: {
        heading: "Карточки уходят в",
        none: "Группа не выбрана",
        noneHint:
          "Обращения работают и клиент получает номер. Не уходит только карточка в Telegram.",
        thread: "В теме {id}",
        noThread: "В саму группу, без темы",
        chosenBy: "выбрал {username}, {when}",
      },
      row: {
        selected: "Принимает обращения",
        thread: "тема {id}",
        selectAria: "Отправлять карточки в {chat}",
      },
      type: {
        group: "Группа",
        supergroup: "Супергруппа",
        channel: "Канал",
      },
      source: {
        membershipEvent: "Сказал Telegram",
        manual: "Введено вручную",
      },
      sourceHint: {
        membershipEvent:
          "Бота добавили в этот чат или убрали из него, и Telegram прислал об этом событие.",
        manual:
          "Этот chat id кто-то вставил вручную. Ничто не подтверждает, что бот действительно в этом чате, кроме проверки.",
      },
      botStatus: {
        member: "Участник",
        administrator: "Администратор",
        restricted: "Ограничен",
        left: "Вышел",
        kicked: "Удалён",
        unknown: "Неизвестно",
      },
      verification: {
        verified: "Отправка работает",
        failed: "Писать не может",
        checking: "Проверяем…",
        verifiedWhen: "Сообщение дошло до этого чата {when}.",
        checkingHint:
          "Проверочное сообщение отправляется. Обновите через минуту; если ничего не меняется — воркер не запущен.",
      },
      actions: {
        select: "Отправлять сюда",
        recheck: "Проверить ещё раз",
        selecting: "Выбираем…",
        clear: "Перестать писать в группу",
        clearing: "Отключаем…",
        clearHint:
          "Обращения продолжат работать — перестанет уходить только карточка в Telegram.",
      },
      paste: {
        heading: "Указать chat id",
        hint:
          "Для группы, где бот уже состоит. Перешлите из неё сообщение боту, показывающему chat id.",
        chatLabel: "Chat id",
        chatPlaceholder: "-1001234567890",
        chatHint: "Chat id группы отрицательный и начинается с минуса.",
        chatIsPerson:
          "Это не группа. Chat id без минуса принадлежит одному человеку, и карточки обращений там не увидит никто, кроме него.",
        threadLabel: "Id темы (необязательно)",
        threadPlaceholder: "12",
        threadHint:
          "Пусто — писать в саму группу.",
        threadInvalid: "Id темы — целое число больше нуля.",
        submit: "Отправлять сюда",
      },
      notes: {
        forbiddenMessage:
          "Ваша роль не может менять, куда отправляются карточки обращений. Повторная попытка ничего не изменит, а каждая записывается как отказ.",
        sessionEndedMessage:
          "{message} Войдите снова — экран останется там, где вы его оставили.",
        conflictTitle: "Кто-то изменил это раньше",
        conflictMessage:
          "Другой оператор выбрал группу в тот же момент, а выбранной может быть только одна. Ваше изменение не записано — перечитайте список и выберите из того, что в нём теперь.",
        refusedTitle: "Этот chat id отклонён",
        refusedMessage: "{message} Ничего не записано.",
        workerTitle: "Выбрано, но проверить некому",
        workerMessage:
          "Группа изменена, и изменение сохранено. Воркер не запущен, поэтому проверочное сообщение никто не отправил — чат останется непроверенным, пока воркер не появится.",
      },
    },
  },
};

export default ru;
