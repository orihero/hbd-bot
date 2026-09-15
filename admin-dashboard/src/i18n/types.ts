/**
 * Type-safe i18n schema and contract definitions for the Bayram Admin Dashboard.
 *
 * Covers 13 namespaces: common, nav, auth, dashboard, chats, users, generations,
 * audit, admins, errors, reveal, segments, and broadcasts.
 */

/* -------------------------------------------------------------------------- */
/* Supported Locales & Metadata                                               */
/* -------------------------------------------------------------------------- */

export type SupportedLocale = "uz" | "ru" | "en";
export type Locale = SupportedLocale;

export const SUPPORTED_LOCALES: readonly SupportedLocale[] = ["uz", "ru", "en"] as const;
export const DEFAULT_LOCALE: SupportedLocale = "en";
export const LOCALE_STORAGE_KEY = "bayram.dashboard.locale";

export interface LocaleMeta {
  readonly code: SupportedLocale;
  readonly label: string;
  readonly name: string;
  readonly dir: "ltr" | "rtl";
}

export const LOCALES: Readonly<Record<SupportedLocale, LocaleMeta>> = {
  uz: { code: "uz", label: "UZ", name: "Oʻzbekcha", dir: "ltr" },
  ru: { code: "ru", label: "RU", name: "Русский", dir: "ltr" },
  en: { code: "en", label: "EN", name: "English", dir: "ltr" },
};

/* -------------------------------------------------------------------------- */
/* Namespace 1: Common                                                        */
/* -------------------------------------------------------------------------- */

export interface CommonTranslations {
  readonly confirm: string;
  readonly cancel: string;
  readonly save: string;
  readonly delete: string;
  readonly close: string;
  readonly dismiss: string;
  readonly retry: string;
  readonly retrying: string;
  readonly refresh: string;
  readonly reload: string;
  readonly export: string;
  readonly exportCsv: string;
  readonly search: string;
  readonly send: string;
  readonly done: string;
  readonly all: string;
  readonly yes: string;
  readonly no: string;
  readonly active: string;
  readonly inactive: string;
  readonly blocked: string;
  readonly notBlocked: string;
  readonly loading: string;
  readonly loadingApp: string;
  readonly previous: string;
  readonly next: string;
  readonly pageOf: string;
  readonly pagination: string;
  readonly filters: string;
  readonly filtersCount: string;
  readonly clearFilters: string;
  readonly clearAll: string;
  readonly clearAllFilters: string;
  readonly activeFilters: string;
  readonly removeFilter: string;
  readonly requiredAsterisk: string;
  readonly usersCount: string;
  readonly neverMetered: string;
  readonly notTracked: string;
  readonly unknown: string;
  /** Under a minute, where a relative formatter would say "in 0 seconds". */
  readonly justNow: string;
  /** A row with no credit_accounts row at all, which is not a balance of zero. */
  readonly noCreditRow: string;
  /** What an empty username, name or handle column prints. */
  readonly none: string;
  /** A tri-state filter's absent arm. Not a value: it is the parameter not being sent. */
  readonly any: string;
  /**
   * The language control's group label.
   *
   * Translated like everything else, and the one string where that matters most: an operator
   * who cannot read this console cannot read the label on the control that fixes it either,
   * so it has to already be in a language they might have.
   */
  readonly selectLanguage: string;
  /** The palette button, whose face says what the click will DO, not what is on screen. */
  readonly switchToDark: string;
  readonly switchToLight: string;
  /** The word between the two ends of a range picker. */
  readonly to: string;
  /** One end of a labelled range, for a screen reader: `{label}` names the range. */
  readonly rangeFrom: string;
  readonly rangeTo: string;
}

/* -------------------------------------------------------------------------- */
/* Namespace 2: Navigation & Shell                                            */
/* -------------------------------------------------------------------------- */

export interface NavTranslations {
  readonly brandTitle: string;
  readonly ariaNavigation: string;
  readonly sections: string;
  readonly groupOperations: string;
  readonly groupAdministration: string;
  readonly dashboard: string;
  readonly chats: string;
  readonly users: string;
  readonly generations: string;
  readonly audit: string;
  readonly admins: string;
  readonly collapseSidebar: string;
  readonly expandSidebar: string;
  readonly signedInAs: string;
  readonly signedInAsPrefix: string;
  readonly signedIn: string;
  readonly signOut: string;
  readonly signingOut: string;
  readonly groups: {
    readonly operations: string;
    readonly administration: string;
  };
  readonly items: {
    readonly dashboard: string;
    readonly chats: string;
    readonly users: string;
    readonly generations: string;
    /** The Payme rail. One rail entry, above the rule, between Generations and Campaigns. */
    readonly billing: string;
    /** The campaign section. One rail entry, above the rule, after Generations. */
    readonly broadcasts: string;
    readonly audit: string;
    readonly admins: string;
  };
  readonly footer: {
    readonly signOut: string;
    readonly signingOut: string;
    readonly signedInAs: string;
    readonly signedIn: string;
    readonly expandSidebar: string;
    readonly collapseSidebar: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 3: Authentication & Security                                     */
/* -------------------------------------------------------------------------- */

export interface AuthTranslations {
  readonly loginTitle: string;
  readonly loginSubtitle: string;
  readonly loginSubtitleIssued: string;
  readonly usernameLabel: string;
  readonly usernamePlaceholder: string;
  readonly passwordLabel: string;
  readonly passwordPlaceholder: string;
  readonly rememberMe: string;
  readonly rememberUsername: string;
  readonly signIn: string;
  readonly signingIn: string;
  readonly forgotPassword: string;
  readonly forgotPasswordHint: string;
  readonly ownerProvisionedNote: string;
  readonly showPassword: string;
  readonly hidePassword: string;
  readonly invalidCredentials: string;
  readonly networkError: string;
  readonly rateLimited: string;

  readonly consoleTitle: string;
  readonly consoleDescription: string;
  readonly featurePipelineTitle: string;
  readonly featurePipelineDesc: string;
  readonly featureAuditTitle: string;
  readonly featureAuditDesc: string;
  readonly featurePrivacyTitle: string;
  readonly featurePrivacyDesc: string;

  readonly changePasswordTitle: string;
  readonly changePasswordSubtitle: string;
  readonly changePasswordForcedTitle: string;
  readonly changePasswordForcedNote: string;
  readonly changePasswordRegularNote: string;
  readonly currentPasswordLabel: string;
  readonly currentPasswordPlaceholder: string;
  readonly newPasswordLabel: string;
  readonly newPasswordPlaceholder: string;
  readonly confirmPasswordLabel: string;
  readonly confirmPasswordPlaceholder: string;
  readonly passwordRequirements: string;
  readonly passwordTooShort: string;
  readonly passwordsDoNotMatch: string;
  readonly updatePassword: string;
  readonly updatingPassword: string;
  readonly updateAndContinue: string;
  readonly signOut: string;

  readonly login: {
    readonly title: string;
    readonly subtitle: string;
    readonly username: string;
    readonly password: string;
    readonly rememberMe: string;
    readonly forgotPassword: string;
    readonly resetHint: string;
    readonly signIn: string;
    readonly signingIn: string;
    readonly ownerProvisionedNote: string;
    readonly showPassword: string;
    readonly hidePassword: string;
  };
  readonly console: {
    readonly heroTitle: string;
    readonly heroDescription: string;
  };
  readonly passwordChange: {
    readonly forcedTitle: string;
    readonly title: string;
    readonly forcedNote: string;
    readonly regularNote: string;
    readonly currentPassword: string;
    readonly currentPlaceholder: string;
    readonly newPassword: string;
    readonly newPlaceholder: string;
    readonly confirmPassword: string;
    readonly confirmPlaceholder: string;
    readonly tooShort: string;
    readonly minLengthHint: string;
    readonly mismatched: string;
    readonly updateAndContinue: string;
    readonly submit: string;
    readonly updating: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 4: Dashboard & Metrics                                           */
/* -------------------------------------------------------------------------- */

export interface CardTranslation {
  readonly label: string;
  /*
   * `sub` was here: the caption under the figure — `ever contacted the bot`, `delivered ×
   * published price`, `net, annualised`. Eighteen cards across three tabs each spent a line on
   * one, and the owner's instruction was a title and a value.
   *
   * `title` / `subtitle` are NOT that caption and stay: they are the card's hover text, which
   * costs no space on the page until it is asked for.
   */
  readonly title: string;
  readonly subtitle: string;
}

export interface DashboardTranslations {
  readonly title: string;
  readonly overviewTitle: string;
  readonly subtitle: string;
  readonly chartWindowAria: string;
  /** The tab strip's landmark name. */
  readonly sectionTabsAria: string;
  /** The page-wide period picker's accessible name. */
  readonly figureWindowAria: string;
  /** One card's own mini period picker: `{label}` is that card's label. */
  readonly cardPeriodAria: string;
  /** A card whose section answered but said nothing about it. */
  readonly unreported: string;
  readonly refreshMetrics: string;

  readonly balanceHealthy: string;
  readonly balanceLow: string;
  readonly balanceCritical: string;
  readonly balancesUnavailable: string;
  readonly balancesNotPolled: string;
  readonly balancesNotPolledTitle: string;
  readonly fxUnavailable: string;
  readonly fxNoRate: string;
  readonly fxRate: string;
  readonly fxSubtitle: string;

  readonly periods: {
    readonly today: string;
    readonly week: string;
    readonly month: string;
    readonly year: string;
    readonly all: string;
  };
  readonly periodsMini: {
    readonly today: string;
    readonly week: string;
    readonly month: string;
    readonly year: string;
  };
  readonly groups: {
    readonly audience: string;
    readonly finances: string;
    readonly vendor: string;
    readonly performance: string;
    readonly charts: string;
  };
  /** The meta line's window suffix, which is a span and not a measurement. */
  readonly header: {
    readonly allTime: string;
    readonly allTimeTo: string;
    readonly to: string;
  };
  /** `ComponentState`, as the system-status card titles it. */
  readonly componentState: {
    readonly ok: string;
    readonly degraded: string;
    readonly notProbed: string;
  };
  /**
   * What a section's failure note calls the read behind it. Passed to `SectionNote` as a key
   * rather than derived from the tab: Vendor's cards come off the FINANCE response, and a
   * note headed "Finances" under a tab called Vendor names a section nobody is looking at.
   */
  readonly subjects: {
    readonly audience: string;
    readonly finances: string;
    readonly planBook: string;
    readonly performance: string;
    readonly vendorSpend: string;
    readonly vendorDetail: string;
    readonly customerLists: string;
  };
  /**
   * One figure card's own words — its TITLE, and that is now the whole of it.
   *
   * Every card here used to carry a `sub` and most carried a `cov`: a caption explaining the
   * figure's construction (`one lane per ACCOUNT · < 30 songs critical, < 100 low`, `a partition
   * of vendor CALLS, not of dollars`) and a coverage badge dating it. Read once each, they are
   * good sentences. Stacked eight deep down a scrolling page, they are what the operator reads
   * INSTEAD of the figures — which is the complaint that removed them.
   *
   * The construction arguments are not lost; they are in the adapters and the chart components
   * that implement them, which is where the next person to change one will look.
   */
  readonly figures: {
    readonly heading: string;
    readonly planBook: string;
    readonly interfaceLanguage: string;
    readonly identifiedCustomers: string;
    readonly activeAccounts: { readonly title: string };
    readonly planUtilisation: { readonly title: string };
    readonly planLiability: { readonly title: string };
    readonly vendorBalances: { readonly title: string };
    readonly pollerFreshness: { readonly title: string };
    readonly songConsumption: { readonly title: string };
    readonly costProvenance: { readonly title: string };
  };
  /** A failed read, as something an operator can act on. `{subject}` is one of the above. */
  readonly note: {
    readonly noCorrelationId: string;
    readonly deniedTitle: string;
    readonly deniedMessage: string;
    readonly driftTitle: string;
    readonly refusedTitle: string;
    readonly refusedMessage: string;
    readonly staleTitle: string;
    readonly staleMessage: string;
    readonly offlineTitle: string;
    readonly failedTitle: string;
  };
  readonly balances: {
    readonly unavailable: string;
    readonly notPolled: string;
    readonly notPolledTitle: string;
  };
  readonly fx: {
    /* `unavailable` and `noRate` were here: the header now prints no rate rather than a
       sentence about not having one. The STATE they described still exists on `FxState`. */
    readonly rate: string;
  };
  readonly cards: {
    readonly totalUsers: CardTranslation;
    readonly newUsers: CardTranslation;
    readonly activeUsers: CardTranslation;
    readonly churn: CardTranslation;
    readonly barred: CardTranslation;
    readonly totalRevenue: CardTranslation;
    readonly topups: CardTranslation;
    readonly vendorSpend: CardTranslation;
    readonly costPerSong: CardTranslation;
    readonly mrr: CardTranslation;
    readonly arr: CardTranslation;
    readonly vendorBalance: CardTranslation;
    readonly songsRemaining: CardTranslation;
    readonly medianSongTime: CardTranslation;
    readonly songsDelivered: CardTranslation;
    readonly musicRenders: CardTranslation;
    readonly musicRenderTime: CardTranslation;
    readonly systemStatus: CardTranslation;
  };
  readonly cardCaptions: {
    readonly spendAllPriced: string;
    readonly spendPartialPriced: string;
    readonly fakeCallsExcluded: string;
    readonly cpsAllAttributed: string;
    readonly cpsPartialAttributed: string;
    readonly runRateRevCost: string;
    readonly runRateNetAnnual: string;
  };
  readonly charts: {
    readonly signups: {
      readonly title: string;
      readonly sub: string;
      readonly subWeekend: string;
    };
    readonly revcost: {
      readonly title: string;
      readonly sub: string;
    };
    readonly delivered: {
      readonly title: string;
      readonly sub: string;
    };
    readonly cps: {
      readonly title: string;
      readonly sub: string;
    };
    readonly costsplit: {
      readonly title: string;
      readonly sub: string;
      /** Before the data lands, the caption names the unit it is waiting on. */
      readonly subPending: string;
    };
    readonly funnel: {
      readonly title: string;
      /**
       * The plural form. Russian agrees a noun with its number in three forms and this
       * carries one of them, so a rung of two, three or four orders reads slightly wrong
       * there; `subOne` covers the case an operator actually sees, a unit of exactly one.
       */
      readonly sub: string;
      readonly subOne: string;
      readonly subPending: string;
    };
    readonly grans: {
      readonly hourly: string;
      readonly daily: string;
      readonly weekly: string;
      readonly monthly: string;
    };
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 5: Chats & Dialogue                                              */
/* -------------------------------------------------------------------------- */

export interface ChatsTranslations {
  readonly title: string;
  readonly subtitle: string;
  readonly searchPlaceholder: string;
  readonly clearSearch: string;
  readonly filterStatus: string;
  readonly refresh: string;
  readonly emptyListTitle: string;
  readonly emptyListMessage: string;
  readonly noThreadsFound: string;
  readonly noThreadsSearchHint: string;
  readonly noThreadsEmptyHint: string;
  readonly selectConversation: string;
  readonly selectConversationHint: string;
  readonly noChatSelectedTitle: string;
  readonly noChatSelectedMessage: string;
  readonly noMessagesYet: string;
  readonly noMessagesHint: string;
  readonly sectionTranscript: string;
  readonly sectionProfile: string;
  readonly openUserDetails: string;
  readonly viewProfile: string;
  /** Leaves the transcript for the thread list; only reachable below `lg`, where the two are not on screen together. */
  readonly backToList: string;
  readonly senderCustomer: string;
  readonly senderBot: string;
  readonly customer: string;
  readonly bayramBot: string;
  readonly wizardStep: string;
  readonly buttonCallback: string;
  readonly audioPreview: string;
  readonly songPreview: string;
  readonly voiceNote: string;
  readonly voiceMessage: string;
  readonly truncatedNote: string;
  readonly inputPlaceholder: string;
  readonly sendButton: string;
  readonly audioMessage: string;
  readonly callback: string;
  readonly media: string;
  readonly badgeAudioMessage: string;
  readonly badgeVoiceNote: string;
  readonly badgeButtonTap: string;
  /**
   * A count and its noun, as `Noun: {count}`.
   *
   * Not `{count} messages`: Russian agrees a noun with its number in three forms and the
   * interpolator has no plural rule, so a phrase with the count in the middle is wrong for
   * two thirds of the numbers it will ever be handed. `Сообщений: 1` is right for all of
   * them, and so is every other locale's version of the same shape.
   */
  readonly messagesCount: string;
  /** The selected thread's Telegram id, labelled. */
  readonly tgId: string;
  /** The header's name for a thread whose conversation row has not arrived. */
  readonly userFallbackName: string;
}

/* -------------------------------------------------------------------------- */
/* Namespace 6: Users & Directory                                             */
/* -------------------------------------------------------------------------- */

export interface UsersTranslations {
  readonly title: string;
  readonly paginationSubtitle: string;
  readonly searchLabel: string;
  readonly searchPlaceholder: string;
  readonly searchHint: string;
  readonly noMatchHint: string;
  /** What this screen's failure notes call the read behind them. */
  readonly subject: string;
  /**
   * The half of a failure note only this screen knows: which route it reads, which roles may
   * read it, and what clearing a filter would actually do. The titles are shared, in
   * `errors.query`.
   */
  readonly notes: {
    readonly forbiddenMessage: string;
    readonly sessionEndedMessage: string;
    readonly refusedFiltersMessage: string;
  };
  readonly filtersAria: string;
  readonly tableCaption: string;
  /** One filter chip's field name, and the values that are not the operator's own words. */
  readonly chips: {
    readonly query: string;
    readonly blocked: string;
    readonly creditBalance: string;
    readonly language: string;
    readonly createdFrom: string;
    readonly createdBefore: string;
    readonly aboveZero: string;
    readonly zeroOrNever: string;
    readonly languageJoin: string;
  };
  /** The one sentence under each filter control that says what it does to the request. */
  readonly hints: {
    readonly blocked: string;
    readonly language: string;
    readonly accountCreated: string;
  };
  /** The toolbar's subtitle, which is a claim about the read and never about the rows. */
  readonly subtitles: {
    readonly reading: string;
    readonly failed: string;
    readonly onThisPage: string;
    /** `withTotal` and a sort on a computed column are a 422 together; say which one went. */
    readonly onThisPageSorted: string;
    readonly accounts: string;
    readonly accountsFiltered: string;
  };
  /**
   * A sortable column heading's accessible name — what ONE press will do, never the state it
   * is in (`aria-sort` on the cell says that). Three, because the cycle is three-legged:
   * unsorted, descending, ascending, and back to the default walk.
   */
  readonly sort: {
    readonly descending: string;
    readonly ascending: string;
    readonly clear: string;
  };
  /** The advanced segment section inside the filter panel. */
  readonly segment: {
    readonly heading: string;
    readonly description: string;
    /** Names the builder region for assistive tech, on this screen specifically. */
    readonly builderLabel: string;
  };
  /**
   * The audience count under the builder.
   *
   * It counts the SEGMENT alone (`/segments/preview` takes `?segment=` and nothing else), and
   * `matched`, `skippedBlocked` and `skippedBotBlocked` overlap — only `reachable` is the
   * complement. No string here may add two of them together.
   */
  readonly audience: {
    readonly counting: string;
    readonly matched: string;
    readonly reachable: string;
    readonly quickFiltersExcluded: string;
    readonly failed: string;
    readonly forbidden: string;
  };
  /** The hand-off to the campaign wizard, and the one case where it is refused. */
  readonly broadcast: {
    readonly action: string;
    readonly ariaSegment: string;
    readonly ariaEveryone: string;
    readonly blockedByQuickFilters: string;
  };
  /** The pager's range label. Never composed while a previous page's rows are on screen. */
  readonly range: {
    readonly loadingNext: string;
    readonly loading: string;
    readonly noneLoaded: string;
    readonly none: string;
    readonly noneMatching: string;
    readonly ofTotal: string;
    readonly onThisPage: string;
    readonly numbered: string;
  };
  /** A count the server capped rather than finished, said honestly. */
  readonly atLeast: string;
  readonly table: {
    readonly user: string;
    readonly language: string;
    readonly orders: string;
    readonly paid: string;
    readonly credits: string;
    readonly standing: string;
    readonly lastOrder: string;
    readonly firstContact: string;
    readonly noOrders: string;
    readonly noUsername: string;
  };
  readonly standing: {
    readonly blocked: string;
    readonly notBlocked: string;
  };
  readonly empty: {
    readonly noUsers: string;
    readonly noMatching: string;
    readonly noUsersHint: string;
    /** A query holding anything but digits cannot match a Telegram id, ever. Say so. */
    readonly unmatchable: string;
  };
  readonly filter: {
    readonly blocked: string;
    readonly creditBalance: string;
    readonly aboveZero: string;
    readonly zeroOrNever: string;
    readonly botLanguage: string;
    readonly accountCreated: string;
  };
  readonly detail: {
    readonly customer: string;
    readonly customerSubtitle: string;
    readonly viewChatHistory: string;
    readonly grantCredits: string;
    readonly block: string;
    readonly unblock: string;
    readonly profile: string;
    readonly standing: string;
    readonly firstContact: string;
    readonly uiLanguage: string;
    readonly photo: string;
    readonly firstName: string;
    readonly lastName: string;
    readonly username: string;
    readonly phone: string;
    readonly phoneShared: string;
    readonly firstOrder: string;
    readonly lastOrder: string;
    readonly wizardSession: string;
  };
  /** The identity panel's field notes, each one a fact the masked value cannot carry. */
  /** The three readings of `isProfilePresent`, and what each one can and cannot claim. */
  readonly profileStanding: {
    readonly onFile: string;
    readonly onFileHint: string;
    readonly absentWithOrders: string;
    readonly absentWithOrdersHint: string;
    readonly absent: string;
    readonly absentHint: string;
  };
  readonly profileAria: string;
  readonly identityNotes: {
    readonly firstContact: string;
    readonly uiLanguage: string;
    readonly photo: string;
    readonly username: string;
    readonly phone: string;
    readonly phoneShared: string;
  };
  /** The orders panel, which pages a customer's own orders. */
  readonly ordersPanel: {
    readonly noun: string;
    readonly caption: string;
    readonly nonePage: string;
    readonly noneAtAll: string;
    readonly goBackPage: string;
    readonly neverConfirmed: string;
    readonly order: string;
    readonly credits: string;
    readonly assets: string;
    readonly delivered: string;
    readonly correlationId: string;
  };
  /** The credit ledger under the profile. */
  readonly creditsPanel: {
    readonly noun: string;
    readonly caption: string;
    readonly movement: string;
    readonly kind: string;
    readonly reason: string;
    readonly order: string;
    readonly actor: string;
    readonly when: string;
    readonly idempotencyKey: string;
  };
  readonly wizard: {
    readonly title: string;
    readonly aria: string;
    readonly noun: string;
    readonly nothingChosen: string;
    readonly noTextFields: string;
    readonly noDraft: string;
    readonly noStepRecorded: string;
    readonly step: string;
    readonly presenceOnly: string;
  };
  readonly detailNouns: {
    readonly record: string;
    readonly grant: string;
  };
  readonly notFound: {
    readonly badIdTitle: string;
    readonly badIdMessage: string;
    readonly missingMessage: string;
  };
  /** `12 orders · 3 paid · Russian`, the one line under a customer's name. */
  readonly orderSummaryLine: string;
  readonly blockedBanner: string;
  /** The avatar's status word: `blocked`, or the state that is not a fault. */
  readonly ableToOrder: string;
  readonly blockedShort: string;
  readonly reasonRefPlaceholder: string;
  readonly credits: {
    readonly title: string;
    readonly balance: string;
    readonly currentBalance: string;
    readonly projected: string;
    readonly rendersInFlight: string;
    readonly lifetimeGranted: string;
    /** The five figures over the ledger, each with the fact its number cannot carry. */
    readonly balanceHint: string;
    readonly projectedHint: string;
    readonly inFlightHint: string;
    readonly lifetimeHint: string;
    readonly allowanceHint: string;
    readonly noAccountTitle: string;
    readonly noAccountMessage: string;
    readonly nothingMovedTitle: string;
    readonly nothingMovedMessage: string;
    readonly allowancePeriod: string;
  };
  readonly orders: {
    readonly title: string;
    readonly state: string;
    readonly recipient: string;
    readonly paid: string;
    readonly failure: string;
    readonly created: string;
    readonly historySummary: string;
  };
  readonly blockDialog: {
    readonly blockTitle: string;
    readonly unblockTitle: string;
    readonly blockConfirm: string;
    readonly unblockConfirm: string;
    readonly blocking: string;
    readonly unblocking: string;
  };
  readonly grantDialog: {
    readonly title: string;
    readonly confirm: string;
    readonly granting: string;
    readonly creditsLabel: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 7: Generations Log                                               */
/* -------------------------------------------------------------------------- */

export interface GenerationsTranslations {
  readonly title: string;
  readonly paginationSubtitle: string;
  readonly subtitleAll: string;
  readonly subtitleFiltered: string;
  readonly searchPlaceholder: string;
  readonly subjects: {
    readonly ledger: string;
    readonly attempt: string;
  };
  /** The singular arms of the two subtitles. English needs them; so does Russian. */
  readonly subtitleAllOne: string;
  readonly subtitleFilteredOne: string;
  readonly countNotRequested: string;
  readonly filtersAria: string;
  readonly tableCaption: string;
  readonly noVendorCall: string;
  readonly chips: {
    readonly kind: string;
    readonly nameStrategy: string;
    readonly outcome: string;
    readonly hasOrder: string;
    readonly provider: string;
    readonly errorCode: string;
    readonly createdFrom: string;
    readonly createdBefore: string;
    readonly succeeded: string;
    readonly failed: string;
    readonly orphanedNo: string;
  };
  readonly hints: {
    readonly nameStrategy: string;
    readonly provider: string;
    readonly errorCode: string;
  };
  readonly range: {
    readonly loadingNext: string;
    readonly loading: string;
    readonly noneLoaded: string;
    readonly noneOnPage: string;
    readonly ofTotal: string;
    readonly onThisPage: string;
    readonly numbered: string;
  };
  readonly notes: {
    readonly sessionEndedMessage: string;
    readonly forbiddenMessage: string;
    readonly notFoundMessage: string;
  };
  readonly empty: {
    readonly failedTitle: string;
    readonly failedMessage: string;
    readonly noMatchTitle: string;
    readonly noMatchMessage: string;
    readonly ledgerEmptyTitle: string;
    readonly ledgerEmptyMessage: string;
  };
  readonly table: {
    readonly created: string;
    readonly kind: string;
    readonly provider: string;
    readonly sequence: string;
    readonly outcome: string;
    readonly language: string;
    readonly latency: string;
    readonly cost: string;
  };
  /**
   * `GenerationKind`, in this console's words. Keyed on the WIRE spelling, so a member added
   * to the vocabulary is a compile error here rather than a blank cell in production.
   */
  readonly kinds: {
    readonly song: string;
    readonly song_inpaint: string;
    readonly greeting: string;
    readonly lyrics: string;
    readonly name_preview: string;
    readonly name_verification: string;
    readonly cover: string;
  };
  /** `NameStrategy`, likewise keyed on the wire spelling. */
  readonly strategies: {
    readonly canonical: string;
    readonly stripped: string;
    readonly ascii: string;
    readonly cyrillic: string;
    readonly hyphenated: string;
    readonly phonetic: string;
  };
  /** `order_id IS NULL`, which has two causes the row cannot tell apart. */
  readonly orphanedLabel: string;
  readonly orphanedExplanation: string;
  readonly outcomes: {
    readonly succeeded: string;
    readonly failed: string;
    readonly orphaned: string;
  };
  /** The detail panel's field labels, lower-case because they sit under a section heading. */
  readonly fields: {
    readonly attemptId: string;
    readonly order: string;
    readonly created: string;
    readonly result: string;
    readonly errorCode: string;
    readonly errorMessage: string;
    readonly retryable: string;
    readonly provider: string;
    readonly providerId: string;
    readonly language: string;
    readonly candidate: string;
    readonly strategy: string;
    readonly verified: string;
    readonly matchConfidence: string;
    readonly length: string;
    readonly cost: string;
    readonly latency: string;
  };
  readonly detailAria: string;
  /** `sequence 3 · attempt 2`, the one line under the detail panel's heading. */
  readonly sequenceLine: string;
  readonly detail: {
    readonly identity: string;
    readonly outcome: string;
    readonly vendor: string;
    readonly nameVerification: string;
    readonly transcript: string;
    readonly telemetry: string;
    readonly close: string;
    readonly verified: string;
    readonly noMatch: string;
    readonly retryable: string;
    readonly notRetryable: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 8: Audit Trail & Verification                                    */
/* -------------------------------------------------------------------------- */

export interface AuditTranslations {
  readonly title: string;
  readonly paginationSubtitle: string;
  readonly subtitleAll: string;
  readonly subtitleFiltered: string;
  readonly subjects: {
    readonly log: string;
    readonly verdict: string;
  };
  readonly noTotalNote: string;
  readonly filtersAria: string;
  readonly tableCaption: string;
  readonly recordCount: string;
  readonly chips: {
    readonly actor: string;
    readonly action: string;
    readonly outcome: string;
    readonly subjectType: string;
    readonly subjectId: string;
    readonly recordedFrom: string;
    readonly recordedThrough: string;
  };
  readonly hints: {
    readonly actor: string;
    readonly subjectType: string;
    readonly subjectId: string;
    readonly action: string;
  };
  readonly actorPlaceholder: string;
  readonly subtitles: {
    readonly reading: string;
    readonly failed: string;
  };
  readonly range: {
    readonly loadingNext: string;
    readonly loading: string;
    readonly noneLoaded: string;
    readonly noneOnPage: string;
    readonly spanned: string;
    readonly numbered: string;
  };
  readonly notes: {
    readonly sessionEndedMessage: string;
    readonly stepUpMessage: string;
    readonly forbiddenMessage: string;
    readonly refusedFiltersMessage: string;
  };
  readonly empty: {
    readonly failedTitle: string;
    readonly failedMessage: string;
    readonly noMatchTitle: string;
    readonly noMatchMessage: string;
    readonly logEmptyTitle: string;
    readonly logEmptyMessage: string;
  };
  readonly table: {
    readonly recorded: string;
    readonly seq: string;
    readonly actor: string;
    readonly action: string;
    readonly outcome: string;
    readonly subject: string;
    readonly exposure: string;
    readonly reason: string;
    readonly correlation: string;
  };
  readonly outcome: {
    readonly ok: string;
    readonly denied: string;
    readonly error: string;
  };
  readonly reasons: {
    readonly reasonWithheld: string;
    readonly noReasonText: string;
  };
  readonly verify: {
    readonly title: string;
    readonly description: string;
    readonly successTitle: string;
    readonly successMessage: string;
    readonly failureTitle: string;
    readonly failureMessage: string;
    readonly checkAgain: string;
    readonly checking: string;
    readonly checkedAt: string;
    readonly rowsChecked: string;
    readonly lastSeq: string;
    readonly walk: string;
    readonly firstBreak: string;
    readonly protection: string;
    readonly validSentence: string;
    readonly brokenSentence: string;
    readonly partialSentence: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 9: Admins Roster                                                 */
/* -------------------------------------------------------------------------- */

export interface AdminsTranslations {
  readonly title: string;
  readonly subtitle: string;
  readonly subject: string;
  readonly subtitles: {
    readonly reading: string;
    readonly failed: string;
    readonly truncated: string;
  };
  readonly tableCaption: string;
  /** Two tooltips that carry a fact the pill beside them cannot. */
  readonly tooltips: {
    readonly deactivated: string;
    readonly temporaryCredential: string;
  };
  /** What each role may do, as the tooltip on its pill. */
  readonly roleHints: {
    readonly owner: string;
    readonly admin: string;
    readonly support: string;
    readonly viewer: string;
  };
  /** The half of a failure note only this screen knows. */
  readonly notes: {
    readonly sessionEndedMessage: string;
    readonly stepUpTitle: string;
    readonly stepUpMessage: string;
    readonly forbiddenMessage: string;
    readonly forbiddenRoleNamed: string;
    readonly forbiddenRoleUnknown: string;
    readonly staleMessage: string;
  };
  readonly table: {
    readonly username: string;
    readonly role: string;
    readonly signIn: string;
    readonly credential: string;
    readonly lastSignIn: string;
    readonly created: string;
    readonly attention: string;
  };
  readonly status: {
    readonly active: string;
    readonly deactivated: string;
    readonly cannotSignIn: string;
  };
  readonly credential: {
    readonly temporary: string;
    readonly rotated: string;
  };
  readonly lastLogin: {
    readonly never: string;
    readonly noSignInRecorded: string;
  };
  readonly roles: {
    readonly owner: string;
    readonly admin: string;
    readonly support: string;
    readonly viewer: string;
  };
  readonly attentionTitle: string;
  readonly staleReasons: {
    readonly neverSignedIn: string;
    readonly temporaryPassword: string;
    readonly dormant: string;
  };
  readonly emptyTitle: string;
  readonly emptyMessage: string;
  readonly noWritesNote: string;
  readonly forbiddenTitle: string;
  /** The one write this screen has: `POST /api/admins`, OWNER only, step-up on the username. */
  readonly create: {
    readonly button: string;
    readonly title: string;
    readonly description: string;
    readonly noun: string;
    readonly usernameLabel: string;
    readonly usernameHint: string;
    readonly usernameInvalid: string;
    readonly passwordLabel: string;
    readonly passwordHint: string;
    readonly roleLabel: string;
    /** Why Owner is not on the menu, said before anybody goes looking for it. */
    readonly ownerNote: string;
    readonly submit: string;
    readonly submitFallback: string;
    readonly pending: string;
    readonly stepUpNote: string;
    readonly createdTitle: string;
    readonly createdMessage: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 10: Feedback & Errors                                            */
/* -------------------------------------------------------------------------- */

export interface ErrorsTranslations {
  readonly notFoundTitle: string;
  readonly backToDashboard: string;
  /**
   * A failed read, as something an operator can act on — the half that is the same on every
   * screen that lists rows.
   *
   * TITLES are shared and take a `{subject}` ("The directory", "The audit log"); MESSAGES are
   * not, and live in the screen's own namespace, because each one carries a fact only that
   * screen knows — which roles may read it, which routes take a step-up, whether a pasted
   * cursor is refused the same way as a filter.
   */
  /**
   * A failed detail read, worded for the panel it broke.
   *
   * `{noun}` is what failed in the operator's own words — "this customer's orders" — and is
   * supplied by the panel, because "Could not load the record" and "Could not load the credit
   * ledger" send an operator to two different places.
   */
  readonly detail: {
    readonly sessionEndedTitle: string;
    readonly sessionEndedMessage: string;
    readonly misconfiguredTitle: string;
    readonly misconfiguredMessage: string;
    readonly forbiddenTitle: string;
    readonly roleCannotTitle: string;
    readonly needsReauthTitle: string;
    readonly notFoundTitle: string;
    readonly conflictTitle: string;
    readonly conflictMessage: string;
    readonly invalidTitle: string;
    readonly invalidMessage: string;
    readonly tooManyStepUpsTitle: string;
    readonly tooManyStepUpsMessage: string;
    readonly rateLimitedTitle: string;
    readonly budgetSpentTitle: string;
    readonly driftTitle: string;
    readonly driftMessage: string;
    readonly driftFields: string;
    readonly offlineTitle: string;
    readonly dependencyTitle: string;
    readonly failedTitle: string;
    readonly noCountdown: string;
    readonly tryAgainIn: string;
  };
  readonly query: {
    readonly noCorrelationId: string;
    readonly sessionEndedTitle: string;
    readonly originTitle: string;
    readonly originMessage: string;
    readonly stepUpTitle: string;
    readonly forbiddenTitle: string;
    readonly driftTitle: string;
    readonly driftMessage: string;
    readonly refusedFiltersTitle: string;
    readonly rateLimitedTitle: string;
    readonly rateLimitedWait: string;
    readonly staleTitle: string;
    readonly staleMessage: string;
    readonly offlineTitle: string;
    readonly failedTitle: string;
    readonly notFoundTitle: string;
  };
  readonly notFound: {
    readonly title: string;
    readonly backToDashboard: string;
  };
  readonly routeError: {
    readonly title: string;
    readonly reload: string;
  };
  readonly emptyState: {
    readonly defaultTitle: string;
    readonly defaultMessage: string;
  };
  readonly dialog: {
    readonly defaultCancel: string;
    readonly defaultConfirm: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 11: Reveal & Step-Up Security                                    */
/* -------------------------------------------------------------------------- */

export interface RevealTranslations {
  readonly stepUpTitle: string;
  readonly stepUpExplanation: string;
  readonly stepUpCostsNoBudgetNote: string;
  readonly stepUpChangesNothingNote: string;
  readonly revealIsAuditedNote: string;
  readonly roleRefusalNote: string;
  readonly costRecords: string;
  /** The affordance beside a masked value, and its accessible name. */
  readonly revealButton: string;
  readonly revealFieldAria: string;
  readonly revealedRecordsAria: string;
  /** What each revealable column IS, keyed on the wire's own `table.column`. */
  readonly fields: {
    readonly recipientNameDisplay: string;
    readonly recipientNameRaw: string;
    readonly recipientLookupKey: string;
    readonly recipientCandidates: string;
    readonly note: string;
    readonly approvedLyrics: string;
    readonly sttTranscript: string;
    readonly nameCandidateText: string;
    readonly phone: string;
    readonly firstName: string;
    readonly lastName: string;
    readonly telegramUsername: string;
  };
  /** One line under each checkbox, saying what is about to be unmasked. */
  readonly fieldHints: {
    readonly recipientNameDisplay: string;
    readonly recipientNameRaw: string;
    readonly recipientLookupKey: string;
    readonly recipientCandidates: string;
    readonly note: string;
    readonly approvedLyrics: string;
    readonly sttTranscript: string;
    readonly nameCandidateText: string;
    readonly phone: string;
    readonly firstName: string;
    readonly lastName: string;
    readonly telegramUsername: string;
  };
  readonly actions: {
    readonly reveal: string;
    readonly orderForceDeliver: string;
    readonly userBlock: string;
    readonly creditGrant: string;
    readonly moderationDecide: string;
    readonly userPurge: string;
    readonly configWrite: string;
    readonly orderEvidenceExport: string;
    readonly auditExport: string;
    readonly adminManage: string;
    readonly broadcastSend: string;
  };
  readonly reasons: {
    readonly customerRequest: string;
    readonly gdprErasure: string;
    readonly abuseReport: string;
    readonly supportInvestigation: string;
    readonly incident: string;
    readonly bakeOff: string;
    readonly routineOps: string;
    readonly other: string;
  };
  /** The dialog's own sentences: what is about to be unmasked, what it costs, what refused. */
  readonly dialog: {
    readonly title: string;
    readonly reasonRequired: string;
    readonly confirm: string;
    readonly pending: string;
    readonly nextPage: string;
    readonly budgetSpentTitle: string;
    readonly recordsUnknown: string;
    readonly recordsAsked: string;
    readonly recordsLeft: string;
    readonly conversationsLeft: string;
    readonly noCountdown: string;
    readonly windowResets: string;
    readonly nothingCharged: string;
    readonly roleRefused: string;
    readonly refused: string;
    readonly stepUpPendingTitle: string;
    readonly stepUpNote: string;
    readonly stepUpAsk: string;
    readonly budgetNotMeasured: string;
    readonly budgetRecords: string;
    readonly budgetConversations: string;
    readonly pageSize: string;
    readonly pageSizeLabel: string;
    readonly mixedShape: string;
    readonly nothingToShow: string;
    readonly reasonCodeLabel: string;
    readonly reasonRefLabel: string;
    readonly reasonTextLabel: string;
    readonly ceilingsSeparate: string;
    readonly recordsNotTouched: string;
    readonly conversationsNotTouched: string;
    readonly pageSizeNote: string;
    readonly refMalformed: string;
    readonly refCredentialShaped: string;
    readonly scopeRecords: string;
    readonly scopeUnknown: string;
    readonly scopeConversations: string;
    readonly costRecordsOne: string;
    readonly costRecordsMany: string;
    readonly costConversationsOne: string;
    readonly costConversationsMany: string;
    readonly costAnd: string;
    readonly retrySeconds: string;
    readonly retryMinutes: string;
    readonly returnedRecords: string;
    readonly chargeIsThePage: string;
  };
  readonly shapes: {
    readonly single: string;
    readonly paged: string;
  };
  /** The password box itself: what a grant admits, and how each refusal differs. */
  readonly stepUpDialog: {
    readonly submit: string;
    readonly pending: string;
    readonly passwordLabel: string;
    readonly zeroGrace: string;
    readonly graceWindow: string;
    readonly wrongPassword: string;
    readonly refused: string;
    readonly rateLimited: string;
    readonly invalidScope: string;
  };
  /** A half-open date range on a filter panel, in the operator's own zone. */
  readonly dateRange: {
    readonly recorded: string;
    readonly recordedFrom: string;
    readonly recordedTo: string;
    readonly created: string;
    readonly createdFrom: string;
    readonly createdTo: string;
    readonly halfOpenHint: string;
    /** Audit's window includes BOTH ends, unlike every other list on this API. */
    readonly bothEndsHint: string;
  };
  readonly stepUp: {
    readonly title: string;
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 12: Segments — the audience DSL's chrome                         */
/* -------------------------------------------------------------------------- */

/**
 * The rule builder's own words.
 *
 * The server publishes the VOCABULARY (`GET /api/segments/fields`: a key, a kind, an operator
 * set, and `doc` — the field's own safety argument in prose) and it publishes no label. `doc`
 * is rendered verbatim wherever it is shown, never paraphrased; `fields` below is the one
 * place a registry key becomes a phrase an operator reads, and `members` the one place an
 * enum member does. Both are keyed by the SERVER's spelling so a lookup miss can fall back to
 * that spelling rather than hiding a field the registry still offers.
 *
 * `fields` and `members` are therefore not a second copy of the registry: they add no field,
 * no operator and no member. A key here that the server stopped publishing renders nowhere; a
 * key the server publishes and this list has not caught up with renders under its raw name.
 */
export interface SegmentsTranslations {
  readonly title: string;
  readonly description: string;
  readonly builderLabel: string;
  readonly everyone: string;
  readonly everyoneWarning: string;
  readonly frozenNote: string;
  readonly readOnlyNote: string;
  readonly summary: string;
  readonly addRule: string;
  readonly addGroup: string;
  readonly removeRule: string;
  readonly removeGroup: string;
  readonly clearAll: string;
  readonly fieldLabel: string;
  readonly conditionLabel: string;
  readonly valueLabel: string;
  readonly chooseField: string;
  readonly unknownField: string;
  readonly unavailableField: string;
  readonly unavailableOption: string;
  readonly aggregateField: string;
  readonly groupLabel: string;
  readonly ruleLabel: string;
  readonly depthLimitReached: string;
  readonly ruleLimitReached: string;
  readonly matchLabel: string;
  readonly loading: string;
  readonly loadFailed: string;
  readonly forbidden: string;
  readonly match: {
    readonly all: string;
    readonly any: string;
    readonly none: string;
  };
  readonly heading: {
    readonly all: string;
    readonly any: string;
    readonly none: string;
  };
  readonly ops: {
    readonly eq: string;
    readonly neq: string;
    readonly in: string;
    readonly not_in: string;
    readonly gt: string;
    readonly gte: string;
    readonly lt: string;
    readonly lte: string;
    readonly between: string;
    readonly is_true: string;
    readonly is_false: string;
    readonly is_null: string;
    readonly is_not_null: string;
    readonly within_last_days: string;
    readonly not_within_last_days: string;
    readonly within_next_days: string;
  };
  /** The five comparisons whose numeric wording is wrong on a date. */
  readonly opsInstant: {
    readonly gt: string;
    readonly gte: string;
    readonly lt: string;
    readonly lte: string;
    readonly is_null: string;
    readonly is_not_null: string;
  };
  readonly opHints: {
    readonly between: string;
    readonly not_within_last_days: string;
    readonly within_next_days: string;
    readonly in: string;
  };
  readonly value: {
    readonly number: string;
    readonly numberFrom: string;
    readonly numberTo: string;
    readonly date: string;
    readonly dateFrom: string;
    readonly dateTo: string;
    readonly wholeMonth: string;
    readonly wholeMonthHint: string;
    readonly days: string;
    readonly daysPreset: string;
    readonly daysRange: string;
    readonly none: string;
    readonly members: string;
    readonly memberPlaceholder: string;
    readonly addMember: string;
    readonly removeMember: string;
    readonly memberCount: string;
    readonly empty: string;
  };
  readonly sort: {
    readonly label: string;
    readonly key: string;
    readonly direction: string;
    readonly asc: string;
    readonly desc: string;
    readonly registryDefault: string;
    readonly narrowsNothing: string;
    readonly aggregateCost: string;
    readonly nullsSortLow: string;
  };
  readonly issues: {
    readonly heading: string;
    readonly maxRules: string;
    readonly maxDepth: string;
    readonly maxValueMembers: string;
    readonly maxAggregateRules: string;
    readonly emptyGroup: string;
    readonly missingValue: string;
    readonly unknownField: string;
    readonly unavailableField: string;
    readonly unsupportedOp: string;
    readonly betweenIncomplete: string;
    readonly betweenOrder: string;
    readonly daysOutOfRange: string;
    readonly unsortableKey: string;
    readonly versionMismatch: string;
  };
  readonly chips: {
    readonly label: string;
    readonly rule: string;
    readonly separatorAnd: string;
    readonly separatorOr: string;
    readonly separatorNone: string;
  };
  /** One phrase per registry key. Never a field the server does not publish. */
  readonly fields: {
    readonly telegram_user_id: string;
    readonly ui_language: string;
    readonly is_blocked: string;
    readonly bot_blocked: string;
    readonly bot_blocked_at: string;
    readonly joined_at: string;
    readonly last_activity_at: string;
    readonly is_reachable: string;
    readonly has_profile: string;
    readonly has_phone: string;
    readonly has_username: string;
    readonly has_avatar: string;
    readonly onboarded_at: string;
    readonly phone_shared_at: string;
    readonly language_chosen_at: string;
    readonly has_credit_account: string;
    readonly credit_balance: string;
    readonly lifetime_credits_granted: string;
    readonly first_metered_at: string;
    readonly order_count: string;
    readonly paid_order_count: string;
    readonly delivered_order_count: string;
    readonly failed_order_count: string;
    readonly first_order_at: string;
    readonly last_order_at: string;
    readonly last_delivered_at: string;
    readonly order_state: string;
    readonly plan_status: string;
    readonly plan_ends_at: string;
    readonly plan_purchase_count: string;
    readonly topup_count: string;
    readonly topup_spend_minor: string;
    readonly last_topup_at: string;
    readonly has_paid_ever: string;
    readonly has_abandoned_checkout: string;
    readonly bot_block_event_count: string;
    readonly has_returned_after_block: string;
    readonly inbound_message_count: string;
    readonly last_inbound_message_at: string;
    readonly wizard_step: string;
  };
  /** The closed vocabularies the registry compares against but does not publish. */
  readonly members: {
    readonly ui_language: {
      readonly uz_latn: string;
      readonly uz_cyrl: string;
      readonly ru: string;
      readonly en: string;
    };
    readonly order_state: {
      readonly draft: string;
      readonly brief_ready: string;
      readonly lyrics_ready: string;
      readonly authorized: string;
      readonly generating: string;
      readonly delivered: string;
      readonly failed: string;
      readonly cancelled: string;
    };
    readonly plan_status: {
      readonly none: string;
      readonly active: string;
      readonly exhausted: string;
      readonly lapsed: string;
    };
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 13: Broadcasts — the campaign list, one campaign, its lifecycle   */
/* -------------------------------------------------------------------------- */

/**
 * The Broadcasts section.
 *
 * Four vocabularies here are traps if they are worded loosely, and each one is a real number
 * an operator will quote:
 *
 *  - `state` is the CAMPAIGN's state and never a recipient's. A campaign in which twelve of
 *    forty thousand messages were refused is `completed`, not `failed`.
 *  - `recipientState.unknown` is its own outcome and must never read as a failure: the message
 *    may well have arrived, and the row is never retried.
 *  - `audience` is frozen at creation. Every sentence about it says WHEN, because the gap
 *    between the preview and the send is the whole reason the counts differ.
 *  - `cancel` does not recall anything. No string in this namespace may imply that it does.
 */
export interface BroadcastsTranslations {
  readonly title: string;
  /** Names the failing read inside `errors.query.*`'s `{subject}` slot. */
  readonly subject: string;
  readonly subjectOne: string;
  readonly subjectRecipients: string;
  readonly tableCaption: string;
  readonly filtersAria: string;
  readonly newCampaign: string;
  readonly newCampaignAria: string;
  /** A bounded count, said as a floor. */
  readonly atLeast: string;
  readonly subtitles: {
    readonly reading: string;
    readonly failed: string;
    readonly onThisPage: string;
    readonly campaigns: string;
    readonly campaignsFiltered: string;
  };
  readonly range: {
    readonly loading: string;
    readonly loadingNext: string;
    readonly noneLoaded: string;
    readonly none: string;
    readonly noneMatching: string;
    readonly numbered: string;
    readonly onThisPage: string;
    readonly ofTotal: string;
  };
  readonly filter: {
    readonly state: string;
    readonly stateHint: string;
    readonly kind: string;
    readonly kindHint: string;
  };
  readonly chips: {
    readonly state: string;
    readonly kind: string;
    readonly join: string;
  };
  readonly table: {
    readonly title: string;
    readonly kind: string;
    readonly state: string;
    readonly audience: string;
    readonly progress: string;
    readonly createdBy: string;
    readonly created: string;
    readonly noCreator: string;
    readonly scheduledFor: string;
  };
  readonly empty: {
    readonly title: string;
    readonly message: string;
    readonly filteredTitle: string;
    readonly filteredMessage: string;
  };
  readonly notes: {
    readonly forbiddenMessage: string;
    readonly sessionEndedMessage: string;
    readonly refusedFiltersMessage: string;
    readonly notFoundMessage: string;
  };
  /** The campaign's own state. Never a recipient's. */
  readonly state: {
    readonly draft: string;
    readonly expanding: string;
    readonly ready: string;
    readonly sending: string;
    readonly paused: string;
    readonly completed: string;
    readonly cancelled: string;
    readonly failed: string;
  };
  /** One sentence each, on the badge's `title`: what the state means for the messages. */
  readonly stateHint: {
    readonly draft: string;
    readonly expanding: string;
    readonly ready: string;
    readonly sending: string;
    readonly paused: string;
    readonly completed: string;
    readonly cancelled: string;
    readonly failed: string;
  };
  readonly kind: {
    readonly service: string;
    readonly marketing: string;
  };
  readonly kindHint: {
    readonly service: string;
    readonly marketing: string;
  };
  readonly recipientState: {
    readonly pending: string;
    readonly sending: string;
    readonly sent: string;
    readonly failed: string;
    readonly skippedBlocked: string;
    readonly undeliverable: string;
    readonly unknown: string;
  };
  readonly progress: {
    readonly settledOf: string;
    readonly notStarted: string;
  };
  readonly audience: {
    readonly size: string;
    readonly frozenAt: string;
    readonly frozenNote: string;
    readonly written: string;
    readonly incomplete: string;
    readonly everyone: string;
    readonly unreadable: string;
    readonly missing: string;
    readonly chipsLabel: string;
  };
  readonly detail: {
    readonly backToList: string;
    readonly loading: string;
    readonly headingAudience: string;
    readonly captionAudience: string;
    readonly headingMessage: string;
    readonly captionMessage: string;
    readonly headingDelivery: string;
    readonly captionDelivery: string;
    readonly headingRecipients: string;
    readonly captionRecipients: string;
    readonly headingRecord: string;
    readonly rolledUp: string;
    readonly recounted: string;
    readonly counters: {
      readonly audience: string;
      readonly written: string;
      readonly unsettled: string;
      readonly sent: string;
      readonly failed: string;
      readonly skipped: string;
      readonly undeliverable: string;
      readonly unknown: string;
      readonly settled: string;
    };
    readonly countersHint: {
      readonly audience: string;
      readonly written: string;
      readonly unsettled: string;
      readonly sent: string;
      readonly failed: string;
      readonly skipped: string;
      readonly undeliverable: string;
      readonly unknown: string;
      readonly settled: string;
    };
    readonly facts: {
      readonly createdBy: string;
      readonly createdAt: string;
      readonly scheduledFor: string;
      readonly scheduledBy: string;
      readonly startedAt: string;
      readonly finishedAt: string;
      readonly reasonCode: string;
      readonly reasonRef: string;
      readonly errorCode: string;
      readonly segmentHash: string;
      readonly unknownActor: string;
      readonly notScheduled: string;
      readonly notStarted: string;
      readonly notFinished: string;
      readonly noReason: string;
      readonly noError: string;
    };
    readonly body: {
      readonly language: string;
      readonly asSent: string;
      readonly renderedLength: string;
      readonly overLimit: string;
      readonly image: string;
      readonly imageCached: string;
      readonly imageNotCached: string;
      readonly noImage: string;
      readonly button: string;
      readonly noButton: string;
      readonly none: string;
    };
    readonly recipients: {
      readonly tableCaption: string;
      readonly filterState: string;
      readonly filterStateHint: string;
      readonly columnRecipient: string;
      readonly columnLanguage: string;
      readonly columnState: string;
      readonly columnAttempts: string;
      readonly columnError: string;
      readonly columnSettled: string;
      readonly erased: string;
      readonly notSettled: string;
      readonly noError: string;
      readonly emptyTitle: string;
      readonly emptyMessage: string;
      readonly emptyFilteredTitle: string;
      readonly emptyFilteredMessage: string;
      readonly noIdColumnNote: string;
    };
  };
  readonly actions: {
    readonly send: string;
    readonly sendAria: string;
    readonly pause: string;
    readonly resume: string;
    readonly cancel: string;
    readonly readOnly: string;
  };
  readonly sendDialog: {
    readonly title: string;
    readonly description: string;
    readonly countWarning: string;
    readonly frozenNote: string;
    readonly whenLabel: string;
    readonly whenNow: string;
    readonly whenLater: string;
    readonly atLabel: string;
    readonly atHint: string;
    readonly atInPast: string;
    readonly atMissing: string;
    readonly confirmNow: string;
    readonly confirmLater: string;
    readonly pending: string;
    readonly stepUpNote: string;
    readonly noRecipients: string;
  };
  readonly pauseDialog: {
    readonly title: string;
    readonly description: string;
    readonly confirm: string;
    readonly pending: string;
  };
  readonly resumeDialog: {
    readonly title: string;
    readonly description: string;
    readonly confirm: string;
    readonly pending: string;
  };
  readonly cancelDialog: {
    readonly title: string;
    readonly description: string;
    readonly noRecall: string;
    readonly confirm: string;
    readonly pending: string;
  };
  /** The 409 every lifecycle move can answer: the campaign had already moved. */
  readonly conflict: {
    readonly title: string;
    readonly message: string;
  };
  /**
   * `/broadcasts/new` — the three-step wizard.
   *
   * Its copy carries three things no other screen has to say: that the audience STOPS MOVING at
   * creation, that a body is measured as the string Telegram will receive rather than as the one
   * in the box, and that a test send needs the campaign to exist and therefore performs that
   * freeze itself.
   */
  readonly wizard: {
    readonly title: string;
    readonly subtitle: string;
    /** Names the failing write inside `errors.query.*`'s `{subject}` slot. */
    readonly subject: string;
    readonly stepsAria: string;
    readonly stepOf: string;
    readonly back: string;
    readonly next: string;
    readonly readOnlyTitle: string;
    readonly readOnlyMessage: string;
    readonly createdNote: string;
    readonly createdLink: string;
    readonly steps: {
      readonly audience: string;
      readonly message: string;
      readonly review: string;
    };
    readonly audience: {
      readonly heading: string;
      readonly caption: string;
      readonly builderLabel: string;
      readonly frozenLocked: string;
      readonly everyoneWarning: string;
      readonly registryFailedTitle: string;
      readonly registryForbidden: string;
      readonly refusalCounting: string;
      readonly refusalInvalid: string;
      readonly refusalNobody: string;
      readonly refusalUnreadable: string;
      readonly counting: string;
      readonly countForbidden: string;
      readonly countFailed: string;
      readonly reachable: string;
      readonly matched: string;
      readonly byLanguage: string;
      readonly sampleShow: string;
      readonly sampleHide: string;
      readonly sampleCaption: string;
      readonly sampleAccount: string;
      readonly sampleLanguage: string;
      readonly sampleJoined: string;
      readonly sampleEmpty: string;
      readonly sampleFailed: string;
      readonly sampleNote: string;
    };
    readonly message: {
      readonly heading: string;
      readonly caption: string;
      readonly titleLabel: string;
      readonly titleHint: string;
      readonly titleMissing: string;
      readonly kindLabel: string;
      readonly bodiesHeading: string;
      readonly bodiesCaption: string;
      readonly noLanguages: string;
      readonly languagesAria: string;
      readonly languageReady: string;
      readonly languageMissing: string;
      readonly bodyLabel: string;
      /** Both lengths and the ceiling: what was typed, and what will be sent. */
      readonly counter: string;
      readonly markupHint: string;
      readonly imageLabel: string;
      readonly imageHint: string;
      readonly buttonLabelLabel: string;
      readonly buttonHint: string;
      readonly buttonUrlLabel: string;
      readonly buttonUrlHint: string;
      readonly previewHeading: string;
      readonly previewCaption: string;
      readonly previewAria: string;
      readonly previewEmpty: string;
      readonly previewImage: string;
      readonly previewSpoiler: string;
      readonly previewUnparsed: string;
      readonly incomplete: string;
      /** One sentence per rule `BroadcastBodyInput` refuses on. */
      readonly issues: {
        readonly empty: string;
        readonly blankText: string;
        readonly incompleteTag: string;
        readonly unknownTag: string;
        readonly badAttribute: string;
        readonly selfClosing: string;
        readonly unbalanced: string;
        readonly nestedLink: string;
        readonly notMarkup: string;
        readonly badHref: string;
        readonly tooLong: string;
        readonly badUrl: string;
        readonly buttonPair: string;
        readonly badStorageKey: string;
      };
      readonly testSend: {
        readonly action: string;
        readonly actionAria: string;
        readonly title: string;
        readonly description: string;
        readonly freezeWarning: string;
        readonly allowlistNote: string;
        readonly recipientLabel: string;
        readonly recipientHint: string;
        readonly confirm: string;
        readonly pending: string;
        readonly sent: string;
        readonly refusedTitle: string;
        readonly refusedMessage: string;
        readonly subject: string;
      };
    };
    readonly review: {
      readonly audienceHeading: string;
      readonly audienceCaption: string;
      readonly audienceCount: string;
      readonly audienceFrozenCount: string;
      readonly freezeWarning: string;
      readonly audienceRulesAria: string;
      readonly messageHeading: string;
      readonly messageCaption: string;
      readonly sendHeading: string;
      readonly sendCaption: string;
      readonly confirmLabel: string;
      readonly confirmHint: string;
      readonly confirmMismatch: string;
      readonly submitNow: string;
      readonly submitLater: string;
      readonly pending: string;
      readonly stepUpNote: string;
      readonly driftTitle: string;
      readonly driftMessage: string;
      readonly driftReview: string;
      readonly driftInsist: string;
    };
  };
}

/* -------------------------------------------------------------------------- */
/* Namespace 14: The Payme rail                                               */
/* -------------------------------------------------------------------------- */

/**
 * The checkout rail: the board, the payments list, one payment's dossier, and the inbound
 * journal.
 *
 * Two families of keys here are not decoration and must not be trimmed to fit a layout.
 *
 * **The provenance sub-lines.** Every fact in the board's header carries a sentence saying
 * WHERE it was read from, because three switches decide whether this rail sells and the admin
 * process can read exactly one of them. Without the provenance the header is five confident
 * assertions, two of which the process is in no position to make.
 *
 * **The lifeline's seven `notes`.** They are the closed `noteCode` vocabulary the server
 * sends instead of an English sentence — the console is trilingual with asserted key parity,
 * so a sentence on the wire would have been a fourth translation no locale file could reach.
 * Every one of the seven is reachable; a missing one renders as nothing at all, on the panel
 * whose entire job is explaining why a step looks the way it does.
 */
export interface BillingTranslations {
  readonly title: string;
  /**
   * The pager's range label, for both keyset lists in this section.
   *
   * Two strings and not one, because `withTotal` is off by default: `total` costs a second
   * query and `bounded_total` saturates at 10,000, so most pages here can say how many rows
   * are ON THEM and nothing more. `onPageOf` is the form for a page that asked for a count;
   * a single string with an optional half would have printed "50 of " on every other page.
   */
  readonly range: {
    readonly onPage: string;
    readonly onPageOf: string;
  };
  /** What an `<ErrorNote>` names when one of these reads fails. */
  readonly subject: string;
  readonly subjectPayments: string;
  readonly subjectPayment: string;
  readonly subjectCalls: string;
  readonly attention: {
    readonly awaitingStale: string;
    readonly paidUnnotified: string;
    readonly paidNoReceipt: string;
  };
  readonly lookup: {
    readonly label: string;
    readonly placeholder: string;
    readonly submit: string;
    readonly malformed: string;
    readonly noMatch: string;
    readonly matchedRef: string;
    readonly matchedTransaction: string;
  };
  readonly intents: {
    readonly title: string;
    readonly caption: string;
    readonly columns: {
      readonly opened: string;
      readonly reference: string;
      readonly state: string;
      readonly product: string;
      readonly amount: string;
      readonly buyer: string;
      readonly rail: string;
      readonly settled: string;
      readonly chain: string;
    };
    readonly buyerErased: string;
    readonly settledByRail: string;
    readonly settledByOperator: string;
    readonly notSettled: string;
    readonly railNever: string;
    readonly railTransactions: string;
    readonly chainReceipt: string;
    readonly chainGrant: string;
    readonly chainNotified: string;
    readonly chainNone: string;
    readonly sandboxBadge: string;
    readonly planShape: string;
    readonly emptyVirgin: string;
    readonly emptyFiltered: string;
    readonly emptyFailed: string;
    readonly chips: {
      readonly state: string;
      readonly product: string;
      readonly settledBy: string;
      readonly attention: string;
      readonly sandbox: string;
      readonly openedFrom: string;
      readonly openedThrough: string;
    };
  };
  readonly lifeline: {
    readonly title: string;
    readonly steps: {
      readonly opened: string;
      readonly railTransaction: string;
      readonly performed: string;
      readonly receipt: string;
      readonly creditGranted: string;
      readonly customerTold: string;
    };
    readonly status: {
      readonly done: string;
      readonly pending: string;
      readonly notApplicable: string;
      readonly missing: string;
    };
    readonly notes: {
      readonly neverOpened: string;
      readonly awaitingRail: string;
      readonly buyerErased: string;
      readonly planGrantsNothing: string;
      readonly notSettled: string;
      readonly alreadyTold: string;
      readonly purged: string;
    };
  };
  readonly dossier: {
    readonly title: string;
    readonly back: string;
    readonly notFound: string;
    readonly notFoundMessage: string;
    readonly intentPanel: string;
    readonly transactionsPanel: string;
    readonly receiptPanel: string;
    readonly ledgerPanel: string;
    readonly callsPanel: string;
    readonly chainStopPanel: string;
    readonly transactionsNone: string;
    readonly receiptNone: string;
    readonly ledgerNone: string;
    readonly callsNever: string;
    readonly callsPurged: string;
    readonly chainStopSingle: string;
    readonly chainStopPlan: string;
    readonly chainStopPlanUnknown: string;
    readonly settleByHand: string;
    readonly settleByHandCaveat: string;
    readonly copyCommand: string;
    readonly copied: string;
    readonly fields: {
      readonly reference: string;
      readonly state: string;
      readonly product: string;
      readonly amount: string;
      readonly buyer: string;
      readonly merchant: string;
      readonly opened: string;
      readonly validUntil: string;
      readonly settled: string;
      readonly notified: string;
      readonly settleNote: string;
      readonly cancelReason: string;
      readonly performTime: string;
      readonly createTime: string;
      readonly cancelTime: string;
      readonly paymeTime: string;
      readonly source: string;
      readonly provider: string;
      readonly cabinetReference: string;
      readonly creditsGranted: string;
      readonly songsIncluded: string;
      readonly songsUsed: string;
      readonly planEndsAt: string;
      readonly kind: string;
      readonly delta: string;
      readonly reason: string;
      readonly actor: string;
    };
  };
  readonly notify: {
    readonly action: string;
    readonly pending: string;
    readonly confirmTitle: string;
    readonly confirmBody: string;
    readonly confirmLabel: string;
    readonly refusalNotPaid: string;
    readonly refusalBuyerErased: string;
    readonly refusalAlreadyNotified: string;
    readonly sent: string;
    readonly replayed: string;
    readonly reasonLabel: string;
    readonly reasonHint: string;
    readonly notDelivered: string;
  };
  readonly pause: {
    readonly pauseAction: string;
    readonly resumeAction: string;
    readonly pauseTitle: string;
    readonly pauseBody: string;
    readonly pauseLabel: string;
    readonly pausePending: string;
    readonly resumeTitle: string;
    readonly resumeBody: string;
    readonly resumeLabel: string;
    readonly resumePending: string;
    readonly reasonLabel: string;
    readonly reasonHint: string;
  };
  readonly calls: {
    readonly title: string;
    readonly subtitle: string;
    readonly caption: string;
    readonly columns: {
      readonly at: string;
      readonly method: string;
      readonly replyCode: string;
      readonly reference: string;
      readonly transactionId: string;
      readonly duration: string;
      readonly peerIp: string;
    };
    readonly peerIpNote: string;
    readonly faultsOnly: string;
    readonly allCalls: string;
    readonly empty: string;
    readonly emptyMessage: string;
    readonly emptyFiltered: string;
    readonly emptyFilteredMessage: string;
    readonly emptyFailed: string;
    readonly emptyFailedMessage: string;
    readonly chips: {
      readonly method: string;
      readonly faultsOnly: string;
      readonly reference: string;
      readonly transactionId: string;
      readonly from: string;
      readonly through: string;
    };
  };
}

/* -------------------------------------------------------------------------- */
/* Top-Level Canonical TranslationSchema                                      */
/* -------------------------------------------------------------------------- */

export interface TranslationSchema {
  readonly common: CommonTranslations;
  readonly nav: NavTranslations;
  readonly auth: AuthTranslations;
  readonly dashboard: DashboardTranslations;
  readonly chats: ChatsTranslations;
  readonly users: UsersTranslations;
  readonly generations: GenerationsTranslations;
  readonly audit: AuditTranslations;
  readonly admins: AdminsTranslations;
  readonly errors: ErrorsTranslations;
  readonly reveal: RevealTranslations;
  readonly segments: SegmentsTranslations;
  readonly broadcasts: BroadcastsTranslations;
  readonly billing: BillingTranslations;
}

/* -------------------------------------------------------------------------- */
/* Recursive Path Type Extraction                                             */
/* -------------------------------------------------------------------------- */

type Join<K, P> = K extends string | number
  ? P extends string | number
    ? `${K}${"" extends P ? "" : "."}${P}`
    : never
  : never;

type Prev = [never, 0, 1, 2, 3, 4, 5, 6];

export type Leaves<T, D extends number = 5> = [D] extends [never]
  ? never
  : T extends object
    ? { [K in keyof T]-?: K extends string | number
        ? T[K] extends string
          ? `${K}`
          : Join<K, Leaves<T[K], Prev[D]>>
        : never
      }[keyof T]
    : "";

export type TranslationPath = Leaves<TranslationSchema>;
export type TranslationKey = TranslationPath;

/* -------------------------------------------------------------------------- */
/* Store Interface Contract                                                   */
/* -------------------------------------------------------------------------- */

export interface I18nStore {
  readonly locale: SupportedLocale;
  readonly setLocale: (locale: SupportedLocale) => void;
  readonly t: (path: TranslationPath, params?: Record<string, string | number>) => string;
}
