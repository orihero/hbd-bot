import type { TranslationSchema } from "../types";

export const en: TranslationSchema = {
  common: {
    confirm: "Confirm",
    cancel: "Cancel",
    save: "Save",
    delete: "Delete",
    close: "Close",
    dismiss: "Dismiss",
    retry: "Retry",
    retrying: "Retrying…",
    refresh: "Refresh",
    reload: "Reload",
    export: "Export",
    exportCsv: "Export CSV",
    search: "Search",
    send: "Send",
    done: "Done",
    all: "All",
    yes: "Yes",
    no: "No",
    active: "Active",
    inactive: "Inactive",
    blocked: "Blocked",
    notBlocked: "Not blocked",
    loading: "Loading…",
    loadingApp: "Loading application…",
    previous: "Previous",
    next: "Next",
    pageOf: "{start}–{end} of {total}",
    pagination: "Pagination",
    filters: "Filters",
    filtersCount: "Filters · {count}",
    clearFilters: "Clear filters",
    clearAll: "Clear all",
    clearAllFilters: "Clear all filters",
    activeFilters: "Active filters",
    removeFilter: "Remove filter {field}: {value}",
    requiredAsterisk: " *",
    usersCount: "{count} users",
    neverMetered: "never metered",
    notTracked: "not tracked",
    unknown: "unknown",
    justNow: "just now",
    noCreditRow:
      "No credit_accounts row at all. That is a different fact from a balance of 0 — the row is opened by the first charge or grant.",
    none: "none",
    any: "Any",
    selectLanguage: "Select language",
    switchToDark: "Switch to the dark palette",
    switchToLight: "Switch to the light palette",
    to: "to",
    rangeFrom: "{label}: from",
    rangeTo: "{label}: to",
    stats: {
      unavailable: {
        noFxRate: "No exchange rate published",
        noPricePublished: "No unit price published",
        mixedCurrencies: "Receipts span several currencies",
        notPriced: "No vendor rate configured",
        noDenominator: "Nothing to divide by",
        notInstrumented: "Nothing records this yet",
      },
    },
  },

  nav: {
    brandTitle: "Bayram Admin",
    ariaNavigation: "Navigation",
    sections: "Sections",
    groupOperations: "Operations",
    groupAdministration: "Administration",
    dashboard: "Dashboard",
    chats: "Chats",
    users: "Users",
    generations: "Generations",
    audit: "Audit",
    admins: "Admins",
    collapseSidebar: "Collapse sidebar",
    expandSidebar: "Expand sidebar",
    signedInAs: "Signed in as {username}, {role}",
    signedInAsPrefix: "Signed in as",
    signedIn: "Signed in",
    signOut: "Sign out",
    signingOut: "Signing out…",
    groups: {
      operations: "Operations",
      administration: "Administration",
    },
    items: {
      dashboard: "Dashboard",
      chats: "Chats",
      users: "Users",
      generations: "Generations",
      billing: "Billing",
      broadcasts: "Campaigns",
      support: "Support",
      audit: "Audit",
      admins: "Admins",
    },
    footer: {
      signOut: "Sign out",
      signingOut: "Signing out…",
      signedInAs: "Signed in as {username}, {role}",
      signedIn: "Signed in",
      expandSidebar: "Expand sidebar",
      collapseSidebar: "Collapse sidebar",
    },
  },

  auth: {
    loginTitle: "Login to your account",
    loginSubtitle: "Operator credentials for the Bayram console.",
    loginSubtitleIssued: "Sign in with the account an owner issued you.",
    usernameLabel: "Username",
    usernamePlaceholder: "operator",
    passwordLabel: "Password",
    passwordPlaceholder: "••••••••",
    rememberMe: "Keep me signed in for 7 days",
    rememberUsername: "Remember my username",
    signIn: "Sign in",
    signingIn: "Signing in…",
    forgotPassword: "Forgot password?",
    forgotPasswordHint:
      "Operator accounts are provisioned and reset by console administrators. Contact your system owner or run the admin bootstrap CLI to issue a temporary credential.",
    ownerProvisionedNote: "Accounts are provisioned by an owner.",
    showPassword: "Show password",
    hidePassword: "Hide password",
    invalidCredentials: "Invalid username or password.",
    networkError: "Could not reach the server. Check your connection.",
    rateLimited: "Too many failed attempts. Try again later.",

    consoleTitle: "Bayram Operations Console",
    consoleDescription:
      "Customer care, song generation pipeline, audit log, and system configuration for Bayram — Tabriklar, Qoʻshiqlar.",
    featurePipelineTitle: "End-to-End Pipeline",
    featurePipelineDesc:
      "Track lyrics drafting, audio synthesis, and delivery verification in real time.",
    featureAuditTitle: "Full Audit Trail",
    featureAuditDesc:
      "Every operator action is signed with a cryptographic HMAC seal and tamper-checked.",
    featurePrivacyTitle: "Privacy by Design",
    featurePrivacyDesc:
      "Customer personal data is masked by default with strict step-up re-authentication.",

    changePasswordTitle: "Change your password",
    changePasswordSubtitle:
      "Your account requires a password update before proceeding.",
    changePasswordForcedTitle: "Create a new password",
    changePasswordForcedNote:
      "This account was created with a temporary password. Until it is changed, every other route — including signing out — answers 403, so choose a new password to continue.",
    changePasswordRegularNote:
      "The new password replaces every session it authorised.",
    currentPasswordLabel: "Current password",
    currentPasswordPlaceholder: "Current temporary password",
    newPasswordLabel: "New password",
    newPasswordPlaceholder: "At least {min} characters",
    confirmPasswordLabel: "Confirm new password",
    confirmPasswordPlaceholder: "Repeat your new password",
    passwordRequirements:
      "At least 12 characters, including uppercase, lowercase, numbers, and symbols.",
    passwordTooShort: "Password must be at least {min} characters.",
    passwordsDoNotMatch: "Passwords do not match.",
    updatePassword: "Update password",
    updatingPassword: "Updating password…",
    updateAndContinue: "Update & continue to console",
    signOut: "Sign out",

    login: {
      title: "Login to your account",
      subtitle: "Operator credentials for the Bayram console.",
      username: "Username",
      password: "Password",
      rememberMe: "Remember my username",
      forgotPassword: "Forgot password?",
      resetHint: "Contact system owner to reset password.",
      signIn: "Sign in",
      signingIn: "Signing in…",
      ownerProvisionedNote: "Accounts are provisioned by an owner.",
      showPassword: "Show password",
      hidePassword: "Hide password",
    },
    console: {
      heroTitle: "The operator console for the Bayram birthday-song bot",
      heroDescription:
        "Orders, lyrics, generations and delivery, in one place. Sign in to see what ran, what failed, and what is still waiting on someone.",
    },
    passwordChange: {
      forcedTitle: "Create a new password",
      title: "Change your password",
      forcedNote:
        "This account was created with a temporary password. Until it is changed, every other route — including signing out — answers 403, so choose a new password to continue.",
      regularNote: "The new password replaces every session it authorised.",
      currentPassword: "Current password",
      currentPlaceholder: "Current temporary password",
      newPassword: "New password",
      newPlaceholder: "At least {min} characters",
      confirmPassword: "Confirm new password",
      confirmPlaceholder: "Repeat your new password",
      tooShort: "Password must be at least {min} characters.",
      minLengthHint: "Must be at least {min} characters.",
      mismatched: "Passwords do not match.",
      updateAndContinue: "Update & continue to console",
      submit: "Update password",
      updating: "Updating password…",
    },
  },

  dashboard: {
    title: "Bayram Dashboard",
    overviewTitle: "Overview",
    subtitle: "Executive summary and operational telemetry.",
    chartWindowAria: "Chart window",
    sectionTabsAria: "Dashboard section",
    figureWindowAria: "Figure window",
    cardPeriodAria: "{label} period",
    unreported: "not reported",
    refreshMetrics: "Refresh metrics",

    balanceHealthy: "API balance healthy",
    balanceLow: "Low provider balance",
    balanceCritical: "Critical provider balance",
    balancesUnavailable: "balances unavailable",
    balancesNotPolled: "balances not polled",
    balancesNotPolledTitle:
      "No vendor in this deployment reports a balance, so nothing is polled.",
    fxUnavailable: "FX rate unavailable",
    fxNoRate: "no FX rate published",
    fxRate: "1 USD = {rate} soʻm",
    fxSubtitle: "{span} · {rate} UZS/$",

    periods: {
      today: "Today",
      week: "Week",
      month: "Month",
      year: "Year",
      all: "All",
    },
    periodsMini: {
      today: "D",
      week: "W",
      month: "M",
      year: "Y",
    },
    groups: {
      audience: "Audience",
      finances: "Finances",
      vendor: "Vendor",
      performance: "Performance",
      charts: "Charts",
    },
    header: {
      allTime: "all time",
      allTimeTo: "all time to {date}",
      to: "to {date}",
    },
    componentState: {
      ok: "OK",
      degraded: "degraded",
      notProbed: "not probed",
    },
    subjects: {
      audience: "Audience",
      finances: "Finances",
      planBook: "The plan book",
      performance: "Performance",
      vendorSpend: "Vendor spend and balances",
      vendorDetail: "Vendor detail",
      customerLists: "The customer lists",
    },
    figures: {
      heading: "Figures",
      planBook: "Plan book",
      interfaceLanguage: "Interface language",
      identifiedCustomers: "Identified customers",
      activeAccounts: {
        title: "Active accounts",
      },
      planUtilisation: {
        title: "How fully plans were used",
      },
      planLiability: {
        title: "What the plans still owe",
      },
      vendorBalances: {
        title: "Vendor balances",
      },
      pollerFreshness: {
        title: "Poller freshness",
      },
      songConsumption: {
        title: "What a song consumes",
      },
      costProvenance: {
        title: "How the cost was priced",
      },
    },
    note: {
      noCorrelationId: "no correlation id",
      deniedTitle: "{subject} is not visible to this role",
      deniedMessage: "Your role cannot read this section.",
      driftTitle:
        "{subject}: this build does not understand the server's answer",
      refusedTitle: "{subject}: the server refused this request",
      refusedMessage: "{message} Narrow the window or the grain.",
      staleTitle: "{subject} stopped refreshing",
      staleMessage: "{message} The figures below are the last good answer.",
      offlineTitle: "{subject} could not reach the API",
      failedTitle: "{subject} failed to load",
    },
    balances: {
      unavailable: "balances unavailable",
      notPolled: "balances not polled",
      notPolledTitle:
        "No vendor in this deployment reports a balance, so nothing is polled.",
    },
    fx: {
      rate: "1 USD = {rate} soʻm",
    },
    cards: {
      totalUsers: {
        label: "Total users",
        title: "Total users",
        subtitle: "ever contacted the bot",
      },
      newUsers: {
        label: "New users",
        title: "New users",
        subtitle: "first contact in period",
      },
      activeUsers: {
        label: "Active users",
        title: "Active users",
        subtitle: "rolling window, not calendar",
      },
      churn: {
        label: "Churn",
        title: "Churn",
        subtitle: "blocked the bot in period",
      },
      barred: {
        label: "Barred by operator",
        title: "Barred by operator",
        subtitle: "admin block flag",
      },
      totalRevenue: {
        label: "Est. revenue",
        title: "Est. revenue",
        subtitle: "delivered × published price",
      },
      topups: {
        label: "Top-ups sold",
        title: "Top-ups sold",
        subtitle: "amount never recorded",
      },
      vendorSpend: {
        label: "Vendor spend",
        title: "Vendor spend",
        subtitle: "measured vendor calls",
      },
      costPerSong: {
        label: "Cost per song",
        title: "Cost per song",
        subtitle: "all vendors, per song",
      },
      mrr: {
        label: "MRR",
        title: "MRR",
        subtitle: "revenue − cost, trailing window",
      },
      arr: {
        label: "ARR",
        title: "ARR",
        subtitle: "net, annualised",
      },
      vendorBalance: {
        label: "Vendor balance",
        title: "Vendor balance",
        subtitle: "last successful poll",
      },
      songsRemaining: {
        label: "Songs remaining",
        title: "Songs remaining",
        subtitle: "estimate from balances",
      },
      medianSongTime: {
        label: "Median song time",
        title: "Median song time",
        subtitle: "brief to delivery",
      },
      songsDelivered: {
        label: "Songs delivered",
        title: "Songs delivered",
        subtitle: "delivered kits, one song each",
      },
      musicRenders: {
        label: "Music renders",
        title: "Music renders",
        subtitle: "vendor calls, includes retries",
      },
      musicRenderTime: {
        label: "Music render time",
        title: "Music render time",
        subtitle: "compose call only",
      },
      systemStatus: {
        label: "System status",
        title: "System status",
        subtitle: "components probed",
      },
    },
    cardCaptions: {
      spendAllPriced: "{count} vendor calls, all priced",
      spendPartialPriced: "{costed} of {calls} calls priced",
      fakeCallsExcluded: " · {count} fake, excluded",
      cpsAllAttributed: "{count} delivered, all attributed",
      cpsPartialAttributed: "{attributed} of {delivered} attributed",
      runRateRevCost: "revenue − cost, {span}",
      runRateNetAnnual: "net × 365 ÷ {span}",
    },
    charts: {
      signups: {
        title: "Sign-ups",
        sub: "one dot = one bucket",
        subWeekend: "one dot = one bucket · hollow = weekend",
      },
      revcost: {
        title: "Revenue against cost",
        sub: "ink = revenue · faint = cost",
      },
      delivered: {
        title: "Songs delivered",
        sub: "one hairline = one bucket",
      },
      cps: {
        title: "Cost per song",
        sub: "one rung = one cent",
      },
      costsplit: {
        title: "Where the cost goes",
        sub: "one tick = {amount}",
        subPending: "one tick = a fixed dollar step",
      },
      funnel: {
        title: "Where orders drop off",
        sub: "one rung = {count} orders · dashed drops",
        subOne: "one rung = one order · dashed drops",
        subPending: "one rung = a fixed number of orders · dashed drops",
      },
      grans: {
        hourly: "Hourly",
        daily: "Daily",
        weekly: "Weekly",
        monthly: "Monthly",
      },
    },
  },

  chats: {
    title: "Chats",
    subtitle:
      "Replicated customer dialogues, bot screens, callbacks, and media transcripts.",
    searchPlaceholder: "Search username, name, phone, ID…",
    clearSearch: "Clear search",
    filterStatus: "Filter by status",
    refresh: "Refresh",
    emptyListTitle: "No active conversations",
    emptyListMessage: "No chats matched your search query or filter selection.",
    noThreadsFound: "No chat threads found",
    noThreadsSearchHint: "Try changing your search keywords.",
    noThreadsEmptyHint: "Customer conversations will appear here.",
    selectConversation: "Select a conversation",
    selectConversationHint:
      "Choose a conversation from the left to view details.",
    noChatSelectedTitle: "Select a chat",
    noChatSelectedMessage:
      "Choose a conversation from the left to view the message transcript and customer profile.",
    noMessagesYet: "No messages recorded for this user yet",
    noMessagesHint:
      "Inbound and outbound messages will be logged automatically.",
    sectionTranscript: "Transcript",
    sectionProfile: "Customer Profile",
    openUserDetails: "Open user details",
    viewProfile: "View Profile",
    backToList: "Back to conversations",
    senderCustomer: "Customer",
    senderBot: "Bayram",
    customer: "Customer",
    bayramBot: "Bayram",
    wizardStep: "step: {step}",
    buttonCallback: "Button Callback:",
    audioPreview: "Audio Message",
    songPreview: "Birthday Song Preview",
    voiceNote: "Voice Note",
    voiceMessage: "Voice message",
    truncatedNote: "Note: Body truncated due to length limits.",
    inputPlaceholder: "Send message…",
    sendButton: "Send",
    audioMessage: "🎵 Audio message",
    callback: "🔘 Callback: {data}",
    media: "(media)",
    badgeAudioMessage: "🎵 Audio message",
    badgeVoiceNote: "Voice note",
    badgeButtonTap: "🔘 Button tap: {action}",
    messagesCount: "Messages: {count}",
    tgId: "TG ID: {id}",
    userFallbackName: "User #{id}",
  },

  users: {
    title: "Users",
    stats: {
      accounts: "Accounts",
      reachable: "Reachable",
      blocked: "Barred by us",
      botBlocked: "Blocked the bot",
    },
    paginationSubtitle: "Showing {start}–{end} of {total} users",
    searchLabel: "Search by Telegram id",
    searchPlaceholder: "Search by Telegram ID or username…",
    searchHint:
      "Matches a substring of the Telegram id and nothing else. Names, usernames and phone numbers are masked at every role and are deliberately not searchable — a substring filter over them would be a reveal with no step-up, no budget and no audit row.",
    noMatchHint:
      "This list searches the Telegram id only, so a name or a handle can never match here.",
    subject: "The directory",
    notes: {
      forbiddenMessage:
        "Your role cannot read /api/users. The records exist — this account is not permitted to list them.",
      sessionEndedMessage:
        "{message} The session cookie is gone, so signing in again is the only way back.",
      refusedFiltersMessage:
        "{message} Asking again cannot change the answer — clear or narrow the filter it names.",
    },
    filtersAria: "User filters",
    tableCaption: "Users, newest account first",
    chips: {
      query: "Telegram id contains",
      blocked: "Blocked",
      creditBalance: "Credit balance",
      language: "Language",
      createdFrom: "Account created from",
      createdBefore: "Account created before",
      aboveZero: "above zero",
      zeroOrNever: "zero or never metered",
      languageJoin: " or ",
    },
    hints: {
      blocked: "Any asks for everyone; the parameter is absent, not false.",
      language:
        "Several may be on at once: the parameter repeats, and the API reads that as OR.",
      accountCreated:
        "Half-open, in your own time zone: “to” includes the whole day picked.",
    },
    subtitles: {
      reading: "Reading the directory…",
      failed: "The directory could not be read.",
      onThisPage: "Showing {count} on this page.",
      onThisPageSorted:
        "Showing {count} on this page. No total: this sort and a count cannot be asked for together.",
      accounts: "{total} accounts.",
      accountsFiltered: "{total} accounts match these filters.",
    },
    sort: {
      descending: "Sort by {column} — highest or most recent first",
      ascending: "Sort by {column} — lowest or oldest first",
      clear: "Stop sorting by {column} and go back to newest account first",
    },
    segment: {
      heading: "Advanced segment",
      description:
        "Build the audience from the fields the server publishes. Every rule is ANDed with the quick filters above, and the same audience can be handed straight to a campaign.",
      builderLabel: "Audience rules",
    },
    audience: {
      counting: "Counting the audience…",
      matched: "{count} accounts match this segment",
      reachable:
        "{reachable} of them can be messaged. {blocked} are barred by us and {botBlocked} have blocked the bot — the two overlap, so never add them together.",
      quickFiltersExcluded:
        "This count is the segment alone: the quick filters above are not part of it.",
      failed: "The audience could not be counted. {message}",
      forbidden: "Your role cannot count an audience.",
    },
    broadcast: {
      action: "Message these users",
      ariaSegment:
        "Message these users — open the campaign wizard on this segment",
      ariaEveryone:
        "Message these users — open the campaign wizard with no segment, which is every account",
      blockedByQuickFilters:
        "Message these users — unavailable: a campaign audience is a segment. Clear the quick filters, or express them as segment rules, to carry this view into a campaign.",
    },
    range: {
      loadingNext: "Loading the next page",
      loading: "Loading users",
      noneLoaded: "No users loaded",
      none: "No users",
      noneMatching: "No matching users",
      ofTotal: " of {total}",
      onThisPage: "{count} users on this page{total}",
      numbered: "{start}–{end}{total}",
    },
    atLeast: "{count}+",
    table: {
      user: "User",
      language: "Language",
      orders: "Orders",
      paid: "Paid",
      credits: "Credits",
      standing: "Standing",
      lastOrder: "Last order",
      firstContact: "First contact",
      noOrders: "no orders",
      noUsername: "no username",
    },
    standing: {
      blocked: "Blocked",
      notBlocked: "Not blocked",
    },
    empty: {
      noUsers: "No users yet",
      noMatching: "No users match these filters",
      noUsersHint:
        "A row appears the first time somebody speaks to the bot — there is no signup event to count.",
      unmatchable: "“{query}” holds characters a Telegram id cannot. {hint}",
    },
    filter: {
      blocked: "Blocked",
      creditBalance: "Credit balance",
      aboveZero: "Above zero",
      zeroOrNever: "Zero or never metered",
      botLanguage: "Bot language",
      accountCreated: "Account created",
    },
    detail: {
      customer: "Customer",
      customerSubtitle:
        "Their profile, their orders, what they can pay with, and the draft they are in the middle of.",
      viewChatHistory: "View Chat History",
      grantCredits: "Grant credits",
      block: "Block",
      unblock: "Unblock",
      profile: "Profile",
      standing: "standing",
      firstContact: "first contact",
      uiLanguage: "ui language",
      photo: "photo",
      firstName: "first name",
      lastName: "last name",
      username: "@username",
      phone: "phone",
      phoneShared: "phone shared",
      firstOrder: "first order",
      lastOrder: "last order",
      wizardSession: "Wizard session",
    },
    profileStanding: {
      onFile: "profile on file",
      onFileHint:
        "A user_profiles row exists. Its columns are masked here; the plaintext costs a reason, a re-authentication and an audit row.",
      absentWithOrders: "no profile row",
      absentWithOrdersHint:
        "This customer has ordered, but there is no user_profiles row now. /forget DELETEs that row and the table carries no retention clock, so this is what an erasure looks like — and it is also what a profile that was never captured looks like. The two cannot be told apart from here.",
      absent: "never onboarded",
      absentHint:
        "No user_profiles row and no orders. Almost certainly somebody who never got past first contact — but an erased account with its orders long gone looks the same.",
    },
    profileAria: "contact profile",
    identityNotes: {
      firstContact:
        "When this account first spoke to the bot — NOT their first order. Reading it as one understates the account's age.",
      uiLanguage: "The language the bot talks to them in.",
      photo:
        "When WE last fetched their picture, never when they changed it. `hasAvatar` is a claim about a stored file, not a stat of one — which is why the header falls back to a monogram.",
      username:
        "A handle the customer chose and can change at any time. Not a stable identifier, and not a name.",
      phone:
        "The mask carries no country prefix, by design. The number itself is on no wire at any role — only a reveal produces it.",
      phoneShared:
        "When the customer pressed Telegram's share-contact button. Absent means they never did.",
    },
    ordersPanel: {
      noun: "this customer's orders",
      caption: "This customer's orders, newest first",
      nonePage: "No orders on this page",
      noneAtAll: "No orders in any state.",
      goBackPage: "The page before this one has rows. Go back to it.",
      neverConfirmed:
        "This account has a users row, so it spoke to the bot — it just never confirmed an order.",
      order: "order",
      credits: "credits",
      assets: "assets",
      delivered: "delivered",
      correlationId: "correlation id",
    },
    creditsPanel: {
      noun: "this customer's credit ledger",
      caption: "This account's credit movements, newest first",
      movement: "movement",
      kind: "kind",
      reason: "reason",
      order: "order",
      actor: "actor",
      when: "when",
      idempotencyKey: "idempotency key",
    },
    wizard: {
      title: "Wizard session",
      aria: "wizard session",
      noun: "the wizard draft",
      nothingChosen: "Nothing chosen yet.",
      noTextFields: "No text fields in this draft.",
      noDraft:
        "No draft held for this Telegram id. Either they are not mid-wizard, or the session expired and the abandoned-draft sweep took it. Neither is a fault.",
      noStepRecorded: "no step recorded",
      step: "step",
      presenceOnly:
        "Presence and lengths only. The draft's own text is on this wire at no role, and there is no reveal route behind it — for an abandoned session this is the only copy that exists.",
    },
    detailNouns: {
      record: "this customer's record",
      grant: "the grant",
    },
    notFound: {
      badIdTitle: "That is not a Telegram user id",
      badIdMessage: "That address does not name one.",
      missingMessage: "No record is held under this Telegram id.",
    },
    orderSummaryLine: "{orders} orders · {paid} paid · {language}",
    blockedBanner: "This account is refused by the bot.",
    ableToOrder: "able to order",
    blockedShort: "blocked",
    reasonRefPlaceholder: "SUP-1423",
    credits: {
      title: "Credits Ledger",
      balance: "balance",
      currentBalance: "Current balance: {balance} credits",
      projected: "projected",
      rendersInFlight: "renders in flight",
      lifetimeGranted: "lifetime granted",
      balanceHint:
        "credit_accounts.balance — what the ledger below can prove. Absent when there is no account row at all, which is not a balance of 0.",
      projectedHint:
        "What the bot would tell this customer right now: the stored balance plus a rolling allowance that is due and has not been minted yet.",
      inFlightHint:
        "Debits this account has not settled yet, inside the settlement grace window. The only number here that explains a customer with credits being refused.",
      lifetimeHint:
        "Every credit ever added, allowances included — whether this account has already been comped, without reading the ledger.",
      allowanceHint:
        "The last rolling-allowance window this account was minted for. Absent for two reasons — no account row, or an account that has never had an allowance — and the balance beside it is what tells them apart.",
      noAccountTitle: "No credit account",
      noAccountMessage:
        "Nothing has ever been granted, spent or refunded here — there is no account row to move.",
      nothingMovedTitle: "Nothing has moved on this page",
      nothingMovedMessage:
        "The account exists; this page of its history is empty.",
      allowancePeriod: "allowance period",
    },
    orders: {
      title: "Orders",
      state: "state",
      recipient: "recipient",
      paid: "paid",
      failure: "failure",
      created: "created",
      historySummary:
        "{delivered} delivered and {failed} failed over the whole history — counted by the server, not from the page below.",
    },
    blockDialog: {
      blockTitle: "Block Customer",
      unblockTitle: "Unblock Customer",
      blockConfirm: "Block {subject}",
      unblockConfirm: "Unblock {subject}",
      blocking: "Blocking…",
      unblocking: "Unblocking…",
    },
    grantDialog: {
      title: "Grant credits",
      confirm: "Grant {count} {unit} to {subject}",
      granting: "Granting…",
      creditsLabel: "credits (required)",
    },
  },

  generations: {
    title: "Generations",
    stats: {
      attempts: "Attempts",
      passRate: "Pass rate",
      checked: "Checked",
    },
    paginationSubtitle: "Showing {start}–{end} of {total} attempts",
    subtitleAll: "{count} attempts in the render ledger",
    subtitleFiltered: "{count} attempts match these filters",
    searchPlaceholder: "Search by attempt ID or correlation ID…",
    subjects: {
      ledger: "The render ledger",
      attempt: "This attempt",
    },
    subtitleAllOne: "{count} attempt in the render ledger",
    subtitleFilteredOne: "{count} attempt matches these filters",
    countNotRequested: "count not requested",
    filtersAria: "Generation filters",
    tableCaption: "Generation attempts, newest first",
    noVendorCall: "no vendor call",
    chips: {
      kind: "Kind",
      nameStrategy: "Name strategy",
      outcome: "Outcome",
      hasOrder: "Has an order",
      provider: "Provider",
      errorCode: "Error code",
      createdFrom: "Created from",
      createdBefore: "Created before",
      succeeded: "succeeded",
      failed: "failed",
      orphanedNo: "no — orphaned",
    },
    hints: {
      nameStrategy: "One strategy at a time — the parameter is scalar.",
      provider:
        "Exact adapter name. The list suggests the adapters this deployment writes; a new one can still be typed.",
      errorCode: "Exact pipeline error code, not a substring.",
    },
    range: {
      loadingNext: "Loading the next page",
      loading: "Loading attempts…",
      noneLoaded: "No page loaded",
      noneOnPage: "No attempts on this page",
      ofTotal: " of {total}",
      onThisPage: "{count} attempts on this page{total}",
      numbered: "{start}–{end}{total}",
    },
    notes: {
      sessionEndedMessage:
        "Sign in again to keep reading the render ledger. Nothing was lost — this is a read, and it wrote nothing.",
      forbiddenMessage:
        "Your role cannot read this. The rows exist — this account is not permitted to see them.",
      notFoundMessage:
        "{message} The link may be from another deployment, or the row may have been pruned.",
    },
    empty: {
      failedTitle: "Nothing to show",
      failedMessage:
        "The read above failed, so this table is empty for a reason that has nothing to do with the filters.",
      noMatchTitle: "No attempts match these filters",
      noMatchMessage:
        "Every vendor call the pipeline makes writes a row here. Widen the window, or clear a filter — the chips above say which are set.",
      ledgerEmptyTitle: "The render ledger is empty",
      ledgerEmptyMessage:
        "No vendor call has been recorded yet. Every attempt the pipeline makes lands here, successful or not.",
    },
    table: {
      created: "Created ({zone})",
      kind: "Kind",
      provider: "Provider",
      sequence: "Seq / try",
      outcome: "Outcome",
      language: "Language",
      latency: "Latency",
      cost: "Cost",
    },
    kinds: {
      song: "song",
      song_inpaint: "song inpaint",
      greeting: "greeting",
      lyrics: "lyrics",
      name_preview: "name preview",
      name_verification: "name verification",
      cover: "cover",
    },
    strategies: {
      canonical: "canonical",
      stripped: "stripped",
      ascii: "ASCII",
      cyrillic: "Cyrillic",
      hyphenated: "hyphenated",
      phonetic: "phonetic",
    },
    orphanedLabel: "Orphaned",
    orphanedExplanation:
      "No order row: either a name preview rendered before any order existed, or an order that has since been deleted. The attempt is kept for tuning either way, and the row cannot say which of the two it is.",
    outcomes: {
      succeeded: "Succeeded",
      failed: "Failed",
      orphaned: "Orphaned",
    },
    fields: {
      attemptId: "attempt id",
      order: "order",
      created: "created",
      result: "result",
      errorCode: "error code",
      errorMessage: "error message",
      retryable: "retryable",
      provider: "provider",
      providerId: "provider id",
      language: "language",
      candidate: "candidate",
      strategy: "strategy",
      verified: "verified",
      matchConfidence: "match confidence",
      length: "length",
      cost: "cost",
      latency: "latency",
    },
    detailAria: "Generation attempt",
    sequenceLine: "sequence {sequence} · attempt {attempt}",
    detail: {
      identity: "Identity",
      outcome: "Outcome",
      vendor: "Vendor",
      nameVerification: "Name verification",
      transcript: "Transcript",
      telemetry: "Telemetry",
      close: "Close",
      verified: "Verified",
      noMatch: "No match",
      retryable: "Retryable",
      notRetryable: "Not retryable",
    },
  },

  audit: {
    title: "Audit",
    paginationSubtitle: "Showing {start}–{end} of {total} audit entries",
    subtitleAll: "Every recorded action, newest first — {note}.",
    subtitleFiltered: "Actions matching these filters, newest first — {note}.",
    subjects: {
      log: "The audit log",
      verdict: "The chain verdict",
    },
    noTotalNote: "this endpoint mints no count, so figures are per page",
    filtersAria: "Audit filters",
    tableCaption: "Audit entries, newest first",
    recordCount: "{count} records",
    chips: {
      actor: "Actor",
      action: "Action",
      outcome: "Outcome",
      subjectType: "Subject type",
      subjectId: "Subject id",
      recordedFrom: "Recorded from",
      recordedThrough: "Recorded through",
    },
    hints: {
      actor:
        "A UUID matches the actor id exactly; anything else matches the username exactly, case-insensitively. Never a prefix and never a substring.",
      subjectType: "One type at a time — the parameter is scalar.",
      subjectId:
        "Exact match on an opaque identifier — a UUID, a Telegram id or a config version. Never a name.",
      action:
        "Any number of them: repeats are OR within the field, AND across fields.",
    },
    actorPlaceholder: "username or id",
    subtitles: {
      reading: "Reading the log…",
      failed: "The log could not be read.",
    },
    range: {
      loadingNext: "Loading the next page",
      loading: "Loading the log…",
      noneLoaded: "No page loaded",
      noneOnPage: "No entries on this page",
      spanned: "{count} entries, {first} down to {last}",
      numbered: "{start}–{end}",
    },
    notes: {
      sessionEndedMessage:
        "Sign in again to keep reading the log. Nothing was lost — this is a read, and it wrote nothing.",
      stepUpMessage:
        "{message} Neither audit route requires one, so there is no password that would answer this. It is a server-side fault worth reporting with the id below.",
      forbiddenMessage:
        "Reading the audit log is owner and admin only. The rows exist — this account is not permitted to see them, and this refusal was itself recorded.",
      refusedFiltersMessage:
        "{message} Asking again cannot change the answer — clear the filter it names. A pasted cursor that this endpoint did not issue is refused the same way.",
    },
    empty: {
      failedTitle: "Nothing to show",
      failedMessage:
        "The read above failed, so this table is empty for a reason that has nothing to do with the filters.",
      noMatchTitle: "No entries match these filters",
      noMatchMessage:
        "Every audited action writes a row here, including the refusals. Widen the window, or clear a filter — the chips above say which are set.",
      logEmptyTitle: "The log has no entries",
      logEmptyMessage:
        "Nothing has been recorded yet — which on a deployment somebody has signed into should be impossible, since signing in writes a row of its own.",
    },
    table: {
      recorded: "Recorded ({zone})",
      seq: "Sequence",
      actor: "Actor",
      action: "Action",
      outcome: "Outcome",
      subject: "Subject",
      exposure: "Exposure",
      reason: "Reason",
      correlation: "Correlation",
    },
    outcome: {
      ok: "Success",
      denied: "Permission Denied",
      error: "System Error",
    },
    reasons: {
      reasonWithheld: "a reason was recorded, you may not read it",
      noReasonText: "no free text on this row",
    },
    verify: {
      title: "Audit Log Integrity Verification",
      description:
        "Verifies the cryptographic HMAC hash-chain across consecutive audit entries to detect database alteration.",
      successTitle: "Audit log integrity confirmed",
      successMessage:
        "HMAC seal chain is unbroken across {count} verified records.",
      failureTitle: "Integrity check failed: chain broken!",
      failureMessage:
        "HMAC signature mismatch detected at entry #{entryId}. Possible log tampering.",
      checkAgain: "Check again",
      checking: "Verifying chain…",
      checkedAt: "Checked at",
      rowsChecked: "Rows checked",
      lastSeq: "Last sequence",
      walk: "Walk",
      firstBreak: "First break",
      protection: "Protection",
      validSentence: "The log has not been edited since it was written.",
      brokenSentence: "The log has been tampered with or corrupted.",
      partialSentence: "Valid up to checked limit; not all rows verified.",
    },
  },

  admins: {
    title: "Admins",
    subtitle: "{active} can sign in · {deactivated} cannot",
    subject: "The roster",
    subtitles: {
      reading: "Reading the roster…",
      failed: "The roster could not be read.",
      truncated:
        "{counted} — The server returns at most {cap} accounts and says nothing about what it left out, so this list may be incomplete.",
    },
    tableCaption:
      "Operator accounts — those who can sign in first, deactivated accounts after",
    tooltips: {
      deactivated:
        "The account exists and cannot sign in. It is kept because the audit log points at it.",
      temporaryCredential:
        "The password somebody else chose is still the password on this account.",
    },
    roleHints: {
      owner:
        "The only role that can read this roster, and the only one that will hold the account writes when they land.",
      admin:
        "Blocks, unblocks and credit grants, plus everything Support can do. Cannot read this roster.",
      support:
        "Reads records and may reveal personal data with a step-up. Cannot read this roster.",
      viewer:
        "Reads masked records only — no reveal, no writes. Cannot read this roster.",
    },
    notes: {
      sessionEndedMessage: "{message} Signing in again is the only way back.",
      stepUpTitle: "The server asked for a step-up this route cannot take",
      stepUpMessage:
        "{message} Reading the roster requires no re-authentication (§6.8 line 949), so this is a server-side permission change rather than something to answer here.",
      forbiddenMessage:
        "{message} {who} has no admin.read cell, so the accounts exist and this session may not list them. Asking again cannot change that, and each attempt is recorded as a refusal in the audit log.",
      forbiddenRoleNamed: "The {role} role",
      forbiddenRoleUnknown: "This account's role",
      staleMessage:
        "{message} The accounts below are the last good answer, not the current one.",
    },
    table: {
      username: "Username",
      role: "Role",
      signIn: "Sign-in",
      credential: "Credential",
      lastSignIn: "Last sign-in",
      created: "Created",
      attention: "Worth a look",
    },
    status: {
      active: "Active",
      deactivated: "Deactivated",
      cannotSignIn: "cannot sign in",
    },
    credential: {
      temporary: "Temporary",
      rotated: "Rotated",
    },
    lastLogin: {
      never: "Never",
      noSignInRecorded: "no sign-in recorded",
    },
    roles: {
      owner: "Owner",
      admin: "Admin",
      support: "Support",
      viewer: "Viewer",
    },
    attentionTitle: "Accounts worth a look",
    staleReasons: {
      neverSignedIn: "never signed in",
      temporaryPassword: "still on its temporary password",
      dormant: "no sign-in in {days} days",
    },
    emptyTitle: "The roster came back empty",
    emptyMessage:
      "On a bootstrapped deployment that should be impossible — the account you are signed in as would be in it. Check that this panel is pointed at the database you think it is.",
    noWritesNote:
      "Creating an operator is the only account write this build has. Changing a role, resetting somebody else's password and deactivating an account still have no supported path here or on the CLI; a button for them would only 404. The CLI (bayram.admin.bootstrap) creates the first Owner and recovers one when no active Owner is left, and you change your own password from this console.",
    forbiddenTitle: "The roster is visible to Owner only",
    create: {
      button: "New operator",
      title: "Add an operator",
      description:
        "The account is created active, with the password you type here. Its holder must replace that password at first sign-in — until they do, every route answers 403 — and the whole action is recorded on the audit log with the reason you give.",
      noun: "the new account",
      usernameLabel: "username (required)",
      usernameHint:
        "{min} to {max} characters: lowercase letters, digits, dot, underscore and hyphen, starting and ending on a letter or digit. No @ — an email-shaped login can only be created on the host, because re-authenticating for this account uses the name itself as the subject.",
      usernameInvalid:
        "That name cannot be re-authenticated for. Use lowercase letters, digits, dot, underscore and hyphen only, starting and ending on a letter or digit.",
      passwordLabel: "temporary password (required)",
      passwordHint:
        "At least {min} characters. Hand it over out of band — it is replaced at first sign-in and is never shown again here.",
      roleLabel: "role (required)",
      ownerNote:
        "Owner is not on this list: the database holds exactly one active Owner, and ownership is handed over with `python -m bayram.admin.bootstrap --reset-owner` on the host.",
      submit: "Create {username}",
      submitFallback: "Create operator",
      pending: "Creating…",
      stepUpNote: "Creating {username} needs a grant scoped to that username.",
      createdTitle: "{username} was created",
      createdMessage:
        "Hand the password over out of band. {username} must replace it at first sign-in, and until then every route answers 403.",
    },
  },

  errors: {
    notFoundTitle: "That page does not exist.",
    backToDashboard: "Back to the dashboard",
    detail: {
      sessionEndedTitle: "Your session has ended",
      sessionEndedMessage:
        "Sign in again to read this. The session cookie and its CSRF twin are set and cleared together, so a rejected token means the session itself is gone — asking again cannot bring it back.",
      misconfiguredTitle: "This deployment is misconfigured",
      misconfiguredMessage:
        "The API refused the request's origin. That is a deployment fault, not something you did and not something a retry fixes — BAYRAM_ADMIN_PUBLIC_ORIGIN does not match where this panel is served from.",
      forbiddenTitle: "Your role cannot read {noun}",
      roleCannotTitle: "Your role cannot do this",
      needsReauthTitle: "This action needs re-authentication",
      notFoundTitle: "Nothing is held for {noun}",
      conflictTitle: "Someone else changed this first",
      conflictMessage:
        "{message} The state on screen has been re-read; check it before acting again.",
      invalidTitle: "The request was refused as invalid",
      invalidMessage:
        "{message} The same request will be refused the same way; change it rather than repeating it.",
      tooManyStepUpsTitle: "Too many re-authentication attempts",
      tooManyStepUpsMessage:
        "{message} That counter is scoped to this session, so waiting on this screen does not clear it — sign in again.",
      rateLimitedTitle: "Rate limited",
      budgetSpentTitle: "Your reveal budget is spent",
      driftTitle: "This panel and the server disagree about the contract",
      driftMessage:
        "{message}{fields} Nothing here can be trusted until the two builds match; report it rather than working around it.",
      driftFields: " Fields: {paths}.",
      offlineTitle: "Could not reach the API for {noun}",
      dependencyTitle: "A dependency is not answering",
      failedTitle: "Could not load {noun}",
      noCountdown: "{message} The envelope carried no countdown.",
      tryAgainIn: "{message} Try again in {seconds} seconds.",
    },
    query: {
      noCorrelationId: "no correlation id",
      sessionEndedTitle: "Your session has ended",
      originTitle:
        "This console is served from an origin the API does not accept",
      originMessage:
        "{message} That is a deployment setting (BAYRAM_ADMIN_PUBLIC_ORIGIN), not something you did — retrying cannot change it.",
      stepUpTitle:
        "{subject}: the server asked for a step-up this route does not have",
      forbiddenTitle: "{subject} is not visible to this role",
      driftTitle:
        "{subject}: this build does not understand the server's answer",
      driftMessage: "{message} ({paths})",
      refusedFiltersTitle: "{subject}: the server refused these filters",
      rateLimitedTitle: "{subject}: the API is rate limiting this session",
      rateLimitedWait: " Try again in {seconds} seconds.",
      staleTitle: "{subject} stopped refreshing",
      staleMessage:
        "{message} The rows below are the last good answer, not the current one.",
      offlineTitle: "{subject} could not reach the API",
      failedTitle: "{subject} failed to load",
      notFoundTitle: "{subject}: nothing has that id",
    },
    notFound: {
      title: "That page does not exist.",
      backToDashboard: "Back to the dashboard",
    },
    routeError: {
      title:
        "Something in this screen failed to render. The detail is in the browser console.",
      reload: "Reload",
    },
    emptyState: {
      defaultTitle: "No data available",
      defaultMessage: "Nothing has been recorded yet.",
    },
    dialog: {
      defaultCancel: "Cancel",
      defaultConfirm: "Confirm",
    },
  },

  reveal: {
    stepUpTitle: "Re-authenticate for this action",
    stepUpExplanation:
      "This action is marked A+S: holding the permission is not enough, and the panel needs your password again for this subject specifically.",
    stepUpCostsNoBudgetNote:
      "Nothing has been charged and nothing disclosed: the password check runs before the budget, so a refused or abandoned re-authentication costs you no records.",
    stepUpChangesNothingNote:
      "Nothing has happened yet: the password check runs before the write, so a refused or abandoned re-authentication changes nothing on this account and writes only the refusal to the audit log.",
    revealIsAuditedNote:
      "Every reveal writes an audit row naming you, the subject, the columns and this reason, and it is written before the read — so the disclosure is attributable even if the read then fails. The row records WHICH columns were revealed, never what they said.",
    roleRefusalNote:
      "This refusal came from the route's own guard rather than from a grant check, so re-authenticating cannot change it: your role holds no cell in this row.",
    costRecords: "{count} records",
    revealButton: "Reveal",
    revealFieldAria: "Reveal {field}",
    revealedRecordsAria: "revealed records",
    fields: {
      recipientNameDisplay: "recipient name, as displayed",
      recipientNameRaw: "recipient name, exactly as typed",
      recipientLookupKey: "recipient lookup key",
      recipientCandidates: "recipient candidates",
      note: "the note to the recipient",
      approvedLyrics: "approved lyrics",
      sttTranscript: "voice-note transcripts",
      nameCandidateText: "name candidates, as heard",
      phone: "phone number",
      firstName: "first name, as Telegram has it",
      lastName: "last name, as Telegram has it",
      telegramUsername: "@username",
    },
    fieldHints: {
      recipientNameDisplay:
        "The name the pipeline sang. Masked to its first character everywhere else.",
      recipientNameRaw:
        "The keystrokes the customer sent — the answer to “which apostrophe did they type”.",
      recipientLookupKey: "The folded key the name matcher compared against.",
      recipientCandidates:
        "Every candidate spelling considered, with the strategy that produced it.",
      note: "Free text the customer wrote about the recipient. On the 30-day clock.",
      approvedLyrics: "The full lyric the customer approved.",
      sttTranscript:
        "What speech-to-text heard, one record per take. Paged, and charged per page.",
      nameCandidateText:
        "The name text each attempt proposed, one record per take. Paged, and charged per page.",
      phone:
        "The E.164 number shared once with Telegram's contact button. Masked to its last digits everywhere else. Kept while the account exists; /forget deletes it.",
      firstName:
        "Not the recipient's name — the customer's own, from their Telegram contact.",
      lastName: "Often absent: Telegram does not require one.",
      telegramUsername:
        "Without the “@”. A handle the customer chose and can change; not a stable identifier.",
    },
    actions: {
      reveal: "unmask personal data on this subject",
      orderForceDeliver: "force this order to delivered",
      userBlock: "block or unblock this customer",
      creditGrant: "grant credits to this account",
      moderationDecide: "decide this moderation case",
      userPurge: "purge this customer's data",
      configWrite: "change configuration",
      orderEvidenceExport: "export this order's evidence bundle",
      auditExport: "export the audit log",
      adminManage: "manage admin accounts",
      broadcastSend:
        "send this campaign to the audience frozen at its creation",
    },
    reasons: {
      customerRequest: "the customer asked",
      gdprErasure: "erasure request",
      abuseReport: "abuse report",
      supportInvestigation: "support investigation",
      incident: "incident",
      bakeOff: "strategy bake-off",
      routineOps: "routine operations",
      other: "other — say why below",
    },
    dialog: {
      title: "Reveal {subjectType} {subjectLabel}",
      reasonRequired:
        "Choose a reason code. It is required, it goes on the audit row, and the server refuses the reveal without one.",
      confirm: "Reveal — {cost}",
      pending: "Revealing…",
      nextPage: "Next page — a fresh reveal, {cost} again",
      budgetSpentTitle: "Your {scope} budget is spent.",
      recordsUnknown:
        "The server did not say how many records this reveal asked for.",
      recordsAsked: "This reveal asked for {count} records.",
      recordsLeft: " {count} records left this hour.",
      conversationsLeft: " {count} conversations left today.",
      noCountdown: "The envelope carried no countdown.",
      windowResets:
        "That window resets in {delay}. It is a fixed window, not a sliding one.",
      nothingCharged:
        "Nothing was charged and nothing was disclosed — a refused reveal gives its charge back.",
      roleRefused: "Your role cannot do this.",
      refused: "The reveal was refused.",
      stepUpPendingTitle: "One more step: re-authenticate.",
      stepUpNote: "You asked to unmask {cost} on this {subjectType}.",
      stepUpAsk:
        "Revealing {cost} of {subjectType} {subjectLabel} needs a grant scoped to this subject. Nothing has been charged.",
      budgetNotMeasured:
        "Budget: not measured yet this session. The server reports what is left with each reveal.",
      budgetRecords: "records left this hour: {count}",
      budgetConversations: "conversations left today: {count}",
      pageSize: "{count} records",
      pageSizeLabel: "records this page may return",
      mixedShape: "These columns cannot share one reveal.",
      nothingToShow: "Nothing to show.",
      reasonCodeLabel: "reason code (required)",
      reasonRefLabel: "ticket reference (optional)",
      reasonTextLabel: "why (optional, {max} characters, kept for 90 days)",
      ceilingsSeparate:
        " The two ceilings are separate: spending one never spends the other.",
      recordsNotTouched: "records: not touched by the last reveal",
      conversationsNotTouched: "conversations: not touched",
      pageSizeNote:
        "This is the charge, not a ceiling on what exists: the budget is debited before the read, so a page of fifty that finds three still costs fifty.",
      refMalformed:
        "Letters, digits, #, _ and - only, up to 64 characters. The server refuses anything else — and a refused body writes no audit row, which is the wrong way to fail a §9.2 action.",
      refCredentialShaped:
        "40 or more characters of letters, digits, _ and - reads as a credential to the audit boundary, and the reveal will be refused before it is charged. Shorten it, or add a # or another separator.",
      scopeRecords: "hourly records",
      scopeUnknown: "reveal",
      scopeConversations: "daily conversations",
      costRecordsOne: "{count} record",
      costRecordsMany: "{count} records",
      costConversationsOne: "{count} conversation",
      costConversationsMany: "{count} conversations",
      costAnd: "{records} and {conversations}",
      retrySeconds: "{count}s",
      retryMinutes: "{count} min",
      returnedRecords: "{returned} of {charged} charged records returned. ",
      chargeIsThePage:
        "The charge is the page this reveal was authorised to return, not what it found.",
    },
    shapes: {
      single: "one record",
      paged: "one page of records",
    },
    stepUpDialog: {
      submit: "Re-authenticate",
      pending: "Re-authenticating…",
      passwordLabel: "Your password",
      zeroGrace:
        "This action's grant expires the instant it is issued: it authorises exactly this one request.",
      graceWindow:
        "A grant is not single-use. Within the short window the server sets, it also admits a retry and the next page of a paged reveal — the budget, not the grant, is what bounds how much is disclosed.",
      wrongPassword: "That password was not accepted.",
      refused: "Re-authentication was refused.",
      rateLimited:
        "The re-auth budget is spent. It is scoped to this session, so signing in again starts a fresh window — waiting here will not.",
      invalidScope:
        "The server could not store this subject id as a scope. That is a panel bug in how the id was built, not something you can retype past.",
    },
    dateRange: {
      recorded: "Recorded",
      recordedFrom: "Recorded from",
      recordedTo: "Recorded to",
      created: "Created",
      createdFrom: "Created from",
      createdTo: "Created to",
      halfOpenHint: "Half-open: from is included, to is not. Times are {zone}.",
      bothEndsHint:
        "Both ends included, unlike every other list on this API. Times are {zone}.",
    },
    stepUp: {
      title: "Re-authenticate for this action",
    },
  },
  broadcasts: {
    title: "Campaigns",
    stats: {
      campaigns: "Campaigns",
      inFlight: "In flight",
      recipients: "Recipients written",
      lastSend: "Last send",
      noSendYet: "No run has started yet",
    },
    subject: "The campaign list",
    subjectOne: "This campaign",
    subjectRecipients: "The recipient ledger",
    tableCaption:
      "Campaigns, newest composed first — one row per campaign, never one per recipient",
    filtersAria: "Campaign filters",
    newCampaign: "New campaign",
    newCampaignAria: "New campaign — compose a message and freeze an audience",
    atLeast: "at least {count}",
    subtitles: {
      reading: "Reading campaigns…",
      failed: "Campaigns could not be read.",
      onThisPage: "On this page: {count}.",
      campaigns: "Campaigns: {total}.",
      campaignsFiltered: "Campaigns matching these filters: {total}.",
    },
    range: {
      loading: "Loading the first page…",
      loadingNext: "Loading the next page…",
      noneLoaded: "No page loaded.",
      none: "No campaigns yet.",
      noneMatching: "No campaign matches these filters.",
      numbered: "{start}–{end}{total}",
      onThisPage: "{count} on this page{total}",
      ofTotal: " of {total}",
    },
    filter: {
      state: "State",
      stateHint:
        "Several at once is an OR: the parameter repeats and the API reads it that way.",
      kind: "Kind",
      kindHint:
        "A campaign declares its kind when it is composed, and a revision cannot change it.",
    },
    chips: {
      state: "State",
      kind: "Kind",
      join: " or ",
    },
    table: {
      title: "Campaign",
      kind: "Kind",
      state: "State",
      audience: "Audience",
      progress: "Delivery",
      createdBy: "Composed by",
      created: "Composed",
      noCreator: "account since removed",
      scheduledFor: "scheduled for {at}",
    },
    empty: {
      title: "No campaigns yet",
      message:
        "Nothing has been composed on this deployment. A campaign starts from an audience — build one on the directory, or open the wizard here.",
      filteredTitle: "No campaign matches these filters",
      filteredMessage:
        "The filters narrow by state and kind only; a campaign that exists under another state is still there.",
    },
    notes: {
      forbiddenMessage:
        "Your role cannot read /api/broadcasts. The campaigns exist — this account is not allowed to list them.",
      sessionEndedMessage:
        "{message} The session cookie is gone, so signing in again is the only way back.",
      refusedFiltersMessage:
        "{message} Asking again cannot change the answer — clear or narrow the filter it named.",
      notFoundMessage:
        "No campaign is held under that id. The refusal does not echo the id back, so check the link you followed.",
    },
    state: {
      draft: "Draft",
      expanding: "Building the audience",
      ready: "Ready to send",
      sending: "Sending",
      paused: "Paused",
      completed: "Completed",
      cancelled: "Cancelled",
      failed: "Failed",
    },
    stateHint: {
      draft:
        "Composed and not yet expanded. Nothing this API returns stays here: an audience begins to be written the moment a campaign is created.",
      expanding:
        "The recipient rows are still being written. The campaign cannot be authorised until they are all there — a half-written ledger is half an audience.",
      ready:
        "The audience is written and nothing has been sent. This is the only state a send may be authorised from.",
      sending:
        "Messages are leaving now. The counters climb without anybody touching this screen.",
      paused:
        "Stopped between chunks. Rows a worker had already claimed still settle for a few seconds, so the counters keep moving.",
      completed:
        "Every recipient row reached an outcome. Messages that Telegram refused are counted, not hidden — the campaign is still completed.",
      cancelled:
        "Stopped for good. What had already gone out has gone out; the counters were not reset.",
      failed:
        "The run itself failed — the reason is the error code. Individual refusals never grade a campaign this way.",
    },
    kind: {
      service: "Service",
      marketing: "Marketing",
    },
    kindHint: {
      service:
        "A message the product owes the customer — an outage, a price change. It goes to everyone the audience selects unless they revoked marketing consent.",
      marketing:
        "A message the product wants to send — a promotion, an announcement. It goes only to accounts that granted marketing consent.",
    },
    recipientState: {
      pending: "Pending",
      sending: "Sending",
      sent: "Delivered",
      failed: "Failed",
      skippedBlocked: "Skipped — blocked",
      undeliverable: "Undeliverable",
      unknown: "Outcome unknown",
    },
    progress: {
      settledOf: "{settled} of {total} settled",
      notStarted: "Nothing sent yet",
    },
    audience: {
      size: "{count} accounts",
      frozenAt: "Frozen {at}",
      frozenNote:
        "The audience was fixed when the campaign was composed and does not move again. Anyone who joined afterwards is not in it, and anyone who left still is.",
      written: "{written} of {size} recipient rows written",
      incomplete:
        "The audience is still being written, so these counts are not final yet.",
      everyone:
        "This audience has no rules at all: it is EVERY account, not an empty selection.",
      unreadable:
        "This build cannot read the stored filter. It was legal when it was written and a later schema version does not speak it; the campaign it belongs to has already been decided.",
      missing: "No filter document was stored with this campaign.",
      chipsLabel: "The frozen audience",
    },
    detail: {
      backToList: "All campaigns",
      loading: "Reading this campaign…",
      headingAudience: "Audience",
      captionAudience:
        "Who this campaign was pointed at, and when that was decided. Read-only: changing who hears a message is a new campaign.",
      headingMessage: "Message",
      captionMessage:
        "What the recipient sees, exactly as it goes to Telegram — one body per language, and no personalisation of any kind.",
      headingDelivery: "Delivery",
      captionDelivery:
        "Two counts of one funnel: the worker's own rollup, and the same numbers recounted from the recipient rows. They differ while a send is being watched, which is the honest picture rather than a bug.",
      headingRecipients: "Recipients",
      captionRecipients:
        "One row per account, masked. Filter by outcome to find the refusals.",
      headingRecord: "Record",
      rolledUp: "Worker rollup",
      recounted: "Recounted from rows",
      counters: {
        audience: "Audience",
        written: "Rows written",
        unsettled: "Not settled",
        sent: "Delivered",
        failed: "Failed",
        skipped: "Skipped",
        undeliverable: "Undeliverable",
        unknown: "Unknown",
        settled: "Settled",
      },
      countersHint: {
        audience:
          "What the segment counted at composition. It does not move again.",
        written:
          "How many recipient rows the expansion has actually written so far.",
        unsettled:
          "Rows with no outcome yet — waiting, or claimed by a worker this second.",
        sent: "Messages Telegram accepted.",
        failed:
          "Messages Telegram refused, for a reason we recorded as a code.",
        skipped: "Accounts skipped because of a block, in either direction.",
        undeliverable: "Telegram says the chat no longer exists.",
        unknown:
          "A killed job left these claimed and they are never retried. The message may well have arrived — this is not a failure, and it is never counted as one.",
        settled:
          "The five terminal outcomes added up. The five do not have to equal the audience.",
      },
      facts: {
        createdBy: "Composed by",
        createdAt: "Composed",
        scheduledFor: "Scheduled for",
        scheduledBy: "Authorised by",
        startedAt: "Started",
        finishedAt: "Finished",
        reasonCode: "Reason",
        reasonRef: "Ticket",
        errorCode: "Error code",
        segmentHash: "Audience fingerprint",
        unknownActor: "account since removed",
        notScheduled: "not scheduled",
        notStarted: "not started",
        notFinished: "not finished",
        noReason: "none recorded",
        noError: "none",
      },
      body: {
        language: "Language",
        asSent: "As the recipient sees it",
        renderedLength:
          "{length} of {limit} characters, as Telegram counts them",
        overLimit: "Over the limit Telegram will accept for this message.",
        image: "Image attached",
        imageCached: "already uploaded once — the next send costs no upload",
        imageNotCached:
          "not uploaded yet — the first recipient pays for the upload",
        noImage: "No image",
        button: "Button: {label} → {url}",
        noButton: "No button",
        none: "This campaign has no message bodies.",
      },
      recipients: {
        tableCaption: "Recipients of this campaign, masked",
        filterState: "Outcome",
        filterStateHint:
          "Several at once is an OR. Unknown is its own outcome and is never folded into failed.",
        columnRecipient: "Recipient",
        columnLanguage: "Language",
        columnState: "Outcome",
        columnAttempts: "Tries",
        columnError: "Error code",
        columnSettled: "Settled",
        erased: "erased on request",
        notSettled: "not settled",
        noError: "—",
        emptyTitle: "No recipient rows yet",
        emptyMessage:
          "The audience is still being written, or this campaign selected nobody.",
        emptyFilteredTitle: "No recipient matches this filter",
        emptyFilteredMessage:
          "Another outcome may still hold rows — clear the filter to see them.",
        noIdColumnNote:
          "There is no Telegram id column here at any role, and no reveal that would produce one.",
      },
    },
    actions: {
      send: "Send",
      sendAria:
        "Send — authorise this campaign to go out to its frozen audience",
      pause: "Pause",
      resume: "Resume",
      cancel: "Cancel campaign",
      readOnly: "Your role can read campaigns but not send them.",
    },
    sendDialog: {
      title: "Authorise this campaign",
      description:
        "This is the action that makes messages leave. It is recorded on the audit log with your name, the reason you give, and the size of the audience.",
      countWarning: "{count} people will receive this message.",
      frozenNote:
        "That audience was frozen {at} and is not recounted now. Nobody who joined since is in it.",
      whenLabel: "When",
      whenNow: "Send now",
      whenLater: "Schedule for later",
      atLabel: "Send at",
      atHint:
        "Your own time zone. The campaign is picked up by the due sweep, not by this screen.",
      atInPast:
        "That instant has already passed. Choose a later one, or send now.",
      atMissing: "Choose the instant to send at.",
      confirmNow: "Send to {count} people now",
      confirmLater: "Schedule for {count} people",
      pending: "Authorising…",
      stepUpNote:
        "Sending needs your password again, scoped to this campaign. Nothing has left yet: the password check runs before the write.",
      noRecipients:
        "This campaign has no recipient rows, so there is nobody to send to.",
    },
    pauseDialog: {
      title: "Pause this campaign",
      description:
        "Delivery stops within seconds. Rows a worker has already claimed are settled rather than abandoned, so the counters keep climbing for a moment afterwards — that is the pause working, not failing.",
      confirm: "Pause delivery",
      pending: "Pausing…",
    },
    resumeDialog: {
      title: "Resume this campaign",
      description:
        "Delivery continues from where it stopped. The audience is unchanged — it was frozen when the campaign was composed — and nobody is messaged twice.",
      confirm: "Resume delivery",
      pending: "Resuming…",
    },
    cancelDialog: {
      title: "Cancel this campaign",
      description:
        "The campaign stops for good and cannot be restarted. Composing it again is a new campaign with a newly frozen audience.",
      noRecall:
        "This does not recall anything: {count} messages have already been delivered and stay delivered. The counters are not reset.",
      confirm: "Cancel this campaign",
      pending: "Cancelling…",
    },
    conflict: {
      title: "The campaign had already moved",
      message:
        "It is {state} now, so that action no longer applies. This screen has the current state; read it before trying again.",
    },
    wizard: {
      title: "New campaign",
      subtitle:
        "Choose who hears it, write it, then read it back before anything leaves.",
      subject: "This campaign",
      stepsAria: "Campaign steps",
      stepOf: "{index} of {total} · {name}",
      back: "Back",
      next: "Next: {name}",
      readOnlyTitle: "Composing a campaign needs the campaign permission",
      readOnlyMessage:
        "Your role can read campaigns and their delivery, but not compose or send one. Ask an administrator to send it, or to widen your role.",
      createdNote:
        "The campaign exists and its audience is frozen at {count} accounts. Nothing has been sent yet.",
      createdLink: "Open the campaign",
      steps: {
        audience: "Audience",
        message: "Message",
        review: "Review and send",
      },
      audience: {
        heading: "Who hears this",
        caption:
          "Build the audience from the fields the server publishes. The count underneath is exact, and it is the number the send is authorised against.",
        builderLabel: "Campaign audience",
        frozenLocked:
          "This audience is frozen: the recipient rows already exist, and the filter is now a record of who was selected. Messaging different people is a new campaign.",
        everyoneWarning:
          "No rules: this is EVERY account, not an empty selection. Add a rule if you did not mean the whole database.",
        registryFailedTitle: "The audience fields could not be read",
        registryForbidden:
          "Your role cannot read the audience vocabulary, so the builder cannot be shown.",
        refusalCounting:
          "Counting the audience… the next step opens once the number is in.",
        refusalInvalid:
          "The audience has a rule the server would refuse. Fix the rule marked above before going on.",
        refusalNobody:
          "Nobody in this audience can be reached, so there is no message to compose. Widen it, or check who is blocked.",
        refusalUnreadable:
          "The audience fields are not available, so this audience cannot be checked.",
        counting: "Counting…",
        countForbidden: "Your role cannot count an audience.",
        countFailed: "The audience could not be counted: {message}",
        reachable: "{count} people would be messaged",
        matched:
          "{matched} match the filter · {blocked} barred by us · {botBlocked} blocked the bot. The two bars overlap; the audience is the first number.",
        byLanguage: "By language: {split}",
        sampleShow: "Show a few of these accounts",
        sampleHide: "Hide the sample",
        sampleCaption:
          "{count} accounts from this audience, with the same masking the directory uses.",
        sampleAccount: "Account",
        sampleLanguage: "Language",
        sampleJoined: "First contact",
        sampleEmpty:
          "This filter matches nobody, so there is nothing to sample.",
        sampleFailed: "The sample could not be read: {message}",
        sampleNote:
          "A sanity check, not the audience: open the directory with the same filter to page through all of it, {limit} at a time.",
      },
      message: {
        heading: "What it says",
        caption:
          "The title is ours, to find the campaign by. The message is what the customer reads.",
        titleLabel: "Campaign title",
        titleHint:
          "Internal — it never reaches a recipient. Up to {limit} characters.",
        titleMissing: "A campaign needs a title.",
        kindLabel: "Kind",
        bodiesHeading: "The message",
        bodiesCaption:
          "One message per language the audience reads. A language nobody in it reads is not offered; one that somebody reads cannot be skipped.",
        noLanguages:
          "This audience has no languages yet, so there is nothing to write. Go back and check the count.",
        languagesAria: "Languages in this audience",
        languageReady: "ready",
        languageMissing: "unwritten",
        bodyLabel: "Message in {language}",
        counter:
          "{sent} of {limit} characters as Telegram will count them ({typed} typed).",
        markupHint:
          "Telegram markup only: {tags}. Every tag must be closed, and a link needs an absolute http(s) address.",
        imageLabel: "Image (optional)",
        imageHint:
          "The storage key of a file this deployment already holds. Attaching one lowers the ceiling to 1,024 characters.",
        buttonLabelLabel: "Button label (optional)",
        buttonHint: "A button needs both a label and a link, or neither.",
        buttonUrlLabel: "Button link (optional)",
        buttonUrlHint: "Absolute http(s), with a public host.",
        previewHeading: "As the recipient sees it",
        previewCaption:
          "Drawn from the same parse the length is measured with, so what is missing here is missing on the wire.",
        previewAria: "Message preview in {language}",
        previewEmpty: "Nothing written yet.",
        previewImage: "Image attached: {key}",
        previewSpoiler: "Hidden until the recipient taps it in Telegram.",
        previewUnparsed:
          "This message cannot be previewed until the markup below is fixed.",
        incomplete: "Still to write: {languages}.",
        issues: {
          empty: "This language has no message yet.",
          blankText: "The message has no words once its markup is parsed away.",
          incompleteTag: "A tag is missing its closing '>'.",
          unknownTag: "That is an HTML tag Telegram does not accept.",
          badAttribute:
            "A tag carries an attribute that is not allowed. Only a link may carry href.",
          selfClosing:
            "A self-closing tag is not Telegram markup — write the pair instead.",
          unbalanced:
            "A tag is not closed, or closes one that was never opened.",
          nestedLink: "A link may not contain another link.",
          notMarkup:
            "The text contains a comment or a declaration, which is not markup.",
          badHref: "A link's address must be an absolute http(s) URL.",
          tooLong:
            "{actual} characters, and Telegram takes {limit}. Ampersands and tags cost more on the wire than in the box.",
          badUrl:
            "The button link must be an absolute http(s) URL with a public host.",
          buttonPair: "A button needs both a label and a link, or neither.",
          badStorageKey: "That is not a storage key this deployment wrote.",
        },
        testSend: {
          action: "Send a test copy",
          actionAria:
            "Send a test copy — deliver this message to one allowlisted account",
          title: "Send a test copy",
          description:
            "The composed message is sent to one account so it can be read in Telegram. It is recorded on the audit log.",
          freezeWarning:
            "A test send needs the campaign to exist, so confirming FREEZES the audience now. Nothing goes to that audience until you authorise the send on the next step.",
          allowlistNote:
            "Only accounts on this deployment's test-send list can receive it; that list is configuration, not a permission.",
          recipientLabel: "Telegram id of the test recipient",
          recipientHint:
            "Digits only. It must be on the deployment's test-send list.",
          confirm: "Send the test copy",
          pending: "Sending…",
          sent: "Sent to {recipient}. Read it in Telegram before authorising the campaign.",
          refusedTitle: "That test send was refused",
          refusedMessage:
            "The recipient is not on this deployment's test-send list. The list ships empty and is set in the admin environment, so ask whoever owns it to add the account.",
          subject: "The test send",
        },
      },
      review: {
        audienceHeading: "The audience",
        audienceCaption: "The number this send is authorised against.",
        audienceCount: "{count} people will be messaged",
        audienceFrozenCount: "{count} recipient rows are written and waiting",
        freezeWarning:
          "Sending freezes this audience first: the recipients are decided at that moment and never recounted. Anyone who joins afterwards is not in it, and anyone who leaves still is.",
        audienceRulesAria: "The audience being frozen",
        messageHeading: "The message",
        messageCaption: "Exactly what each language will receive.",
        sendHeading: "Send",
        sendCaption:
          "This is the action that makes messages leave. It is recorded with your name, the reason you give, and the size of the audience.",
        confirmLabel: "Type {count} to confirm the audience",
        confirmHint:
          "The last check before the messages leave: type the number above.",
        confirmMismatch: "That is not the audience size. Type {count}.",
        submitNow: "Freeze the audience and send to {count} people now",
        submitLater: "Freeze the audience and schedule for {count} people",
        pending: "Sending…",
        stepUpNote:
          "Sending needs your password again, scoped to this campaign. Nothing has left yet: the password check runs before the write.",
        driftTitle: "The audience has moved since it was counted",
        driftMessage:
          "You were shown {expected} accounts; the filter now selects {actual}. Nothing has been created.",
        driftReview: "Go back and read the audience again",
        driftInsist: "Freeze it as it stands now ({count})",
      },
    },
  },
  segments: {
    title: "Advanced segment",
    description:
      "Build the audience out of the fields the server publishes. Nothing here is a name, a phone number or a message — only facts about the account.",
    builderLabel: "Segment rules",
    everyone: "No rules yet — this selects everyone.",
    everyoneWarning:
      "An empty segment is not a narrowed one: it matches every account in the database.",
    frozenNote:
      "The audience is frozen when the campaign is created. Editing this segment afterwards changes nothing that was already scheduled.",
    readOnlyNote: "This audience is frozen and can no longer be edited.",
    summary: "{rules} of {maxRules} rules · nesting {depth} of {maxDepth}",
    addRule: "Add rule",
    addGroup: "Add group",
    removeRule: "Remove this rule",
    removeGroup: "Remove this group",
    clearAll: "Clear the segment",
    fieldLabel: "Field",
    conditionLabel: "Condition",
    valueLabel: "Value",
    chooseField: "Choose a field…",
    unknownField: "{key} — no longer offered",
    unavailableField:
      "Needs the {capability} table, which this deployment does not have.",
    unavailableOption: "{label} — unavailable here",
    aggregateField:
      "Counted across other tables, so this rule costs more to run.",
    groupLabel: "Group matching {mode}",
    ruleLabel: "Rule {index}",
    depthLimitReached: "Nesting is at the server's limit of {maxDepth}.",
    ruleLimitReached:
      "This segment already carries the server's limit of {maxRules} rules.",
    matchLabel: "How these combine",
    loading: "Reading the field registry…",
    loadFailed:
      "The field registry could not be read, so no rule can be composed.",
    forbidden:
      "Your role does not hold the campaign cell, so the field registry is closed.",
    match: {
      all: "All",
      any: "Any",
      none: "None",
    },
    heading: {
      all: "Accounts matching ALL of:",
      any: "Accounts matching ANY of:",
      none: "Accounts matching NONE of:",
    },
    ops: {
      eq: "is",
      neq: "is not",
      in: "is any of",
      not_in: "is none of",
      gt: "is more than",
      gte: "is at least",
      lt: "is less than",
      lte: "is at most",
      between: "is between",
      is_true: "yes",
      is_false: "no",
      is_null: "never happened",
      is_not_null: "has happened",
      within_last_days: "in the last N days",
      not_within_last_days: "not in the last N days",
      within_next_days: "in the next N days",
    },
    opsInstant: {
      gt: "after",
      gte: "on or after",
      lt: "before",
      lte: "on or before",
      is_null: "never happened",
      is_not_null: "has happened",
    },
    opHints: {
      between: "Half-open: the first bound is included, the second is not.",
      not_within_last_days:
        "Wherever the field can be empty, accounts this never happened to are included as well.",
      within_next_days:
        "Counted forward from now, so it never looks into the past.",
      in: "Several values read as OR within this one field.",
    },
    value: {
      number: "Number",
      numberFrom: "From",
      numberTo: "To (excluded)",
      date: "Date",
      dateFrom: "From",
      dateTo: "To (excluded)",
      wholeMonth: "Whole month",
      wholeMonthHint:
        "Fills both bounds with that month, in your own time zone.",
      days: "Days",
      daysPreset: "{days} days",
      daysRange: "Between {min} and {max} days.",
      none: "This condition takes no value.",
      members: "Values",
      memberPlaceholder: "Add a value",
      addMember: "Add",
      removeMember: "Remove {value}",
      memberCount: "{count} of {max} values",
      empty: "Pick at least one value.",
    },
    sort: {
      label: "Order the results",
      key: "Sort by",
      direction: "Direction",
      asc: "Lowest first",
      desc: "Highest first",
      registryDefault: "Default order (first contact, newest first)",
      narrowsNothing:
        "A sort orders the audience; it never narrows it. Add a rule for that.",
      aggregateCost:
        "This sort is computed across other tables, so an exact total is refused beside it.",
      nullsSortLow:
        "Accounts this never happened to sort as zero, or as the epoch.",
    },
    issues: {
      heading: "Fix these before this segment can be used",
      maxRules: "{actual} rules, and the server accepts at most {limit}.",
      maxDepth: "Nested {actual} deep, and the server accepts at most {limit}.",
      maxValueMembers:
        "{field} names {actual} values, and the server accepts at most {limit}.",
      maxAggregateRules:
        "{actual} rules are counted across other tables, and the server accepts at most {limit}.",
      emptyGroup: "A nested group must carry at least one rule.",
      missingValue: "{field} needs a value.",
      unknownField: "{field} is not a field this server publishes.",
      unavailableField: "{field} needs a table this deployment does not have.",
      unsupportedOp: "{field} does not take this condition.",
      betweenIncomplete: "{field} needs both bounds of the range.",
      betweenOrder: "{field} ends before it starts.",
      daysOutOfRange: "{field} needs a day count between {min} and {max}.",
      unsortableKey: "{field} cannot be sorted on.",
      versionMismatch:
        "This panel writes version {expected} documents and the server asked for version {actual}. Reload before composing an audience.",
    },
    chips: {
      label: "Segment rules",
      rule: "{op} {value}",
      separatorAnd: "and",
      separatorOr: "or",
      separatorNone: "nor",
    },
    fields: {
      telegram_user_id: "Telegram id",
      ui_language: "Bot language",
      is_blocked: "Barred by us",
      bot_blocked: "Blocked our bot",
      bot_blocked_at: "Blocked our bot at",
      joined_at: "First contact",
      last_activity_at: "Last activity",
      is_reachable: "Reachable",
      has_profile: "Has a profile",
      has_phone: "Phone on file",
      has_username: "Username on file",
      has_avatar: "Avatar on file",
      onboarded_at: "Finished onboarding",
      phone_shared_at: "Shared a phone",
      language_chosen_at: "Chose a language",
      has_credit_account: "Has a credit account",
      credit_balance: "Credit balance",
      lifetime_credits_granted: "Credits granted, lifetime",
      first_metered_at: "First metered",
      order_count: "Orders",
      paid_order_count: "Paid orders",
      delivered_order_count: "Songs delivered",
      failed_order_count: "Failed orders",
      first_order_at: "First order",
      last_order_at: "Last order",
      last_delivered_at: "Last delivery",
      order_state: "Order state",
      plan_status: "Plan status",
      plan_ends_at: "Plan ends",
      plan_purchase_count: "Plans bought",
      topup_count: "Top-ups",
      topup_spend_minor: "Top-up spend, in minor units",
      last_topup_at: "Last top-up",
      has_paid_ever: "Has ever paid",
      has_abandoned_checkout: "Abandoned a checkout",
      bot_block_event_count: "Times they blocked the bot",
      has_returned_after_block: "Came back after blocking",
      inbound_message_count: "Messages they sent",
      last_inbound_message_at: "Last message they sent",
      wizard_step: "Wizard step",
    },
    members: {
      ui_language: {
        uz_latn: "Uzbek (Latin)",
        uz_cyrl: "Uzbek (Cyrillic)",
        ru: "Russian",
        en: "English",
      },
      order_state: {
        draft: "Draft",
        brief_ready: "Brief ready",
        lyrics_ready: "Lyrics ready",
        authorized: "Authorized",
        generating: "Generating",
        delivered: "Delivered",
        failed: "Failed",
        cancelled: "Cancelled",
      },
      plan_status: {
        none: "Never bought a plan",
        active: "Plan running, songs left",
        exhausted: "Plan running, songs used up",
        lapsed: "Plan expired, not bought again",
      },
    },
  },
  billing: {
    title: "Checkout rail",
    stats: {
      intents: "Payments opened",
      settled: "Settled",
      faults: "Failed inbound calls",
      attention: "Needs chasing",
      ofPayments: "{count} payments",
      period: {
        label: "Period",
        day: "Day",
        week: "Week",
        month: "Month",
        year: "Year",
      },
    },
    range: {
      onPage: "{count} on this page",
      onPageOf: "{count} of {total}",
    },
    subject: "The rail",
    subjectPayments: "Payments",
    subjectPayment: "This payment",
    subjectCalls: "Inbound calls",
    attention: {
      awaitingStale: "Held past the rail's own timeout",
      paidUnnotified: "Paid, never announced",
      paidNoReceipt: "Paid, no receipt written",
    },
    lookup: {
      label: "Reference or Payme transaction id",
      placeholder: "a1b2c3d4e5f60718293a4b5c",
      submit: "Find",
      malformed:
        "That is not a reference. A payment reference and a Payme transaction id are both exactly 24 hex characters.",
      noMatch: "No payment exists under that reference on this deployment.",
      matchedRef: "Matched our payment reference.",
      matchedTransaction: "Matched Payme's own transaction id.",
    },
    intents: {
      title: "Payments",
      caption: "Payments",
      columns: {
        opened: "Opened",
        reference: "Reference",
        state: "State",
        product: "Product",
        amount: "Amount",
        buyer: "Buyer",
        rail: "Rail",
        settled: "Settled",
        chain: "Chain",
      },
      buyerErased: "buyer erased",
      settledByRail: "by Payme",
      settledByOperator: "by hand",
      notSettled: "not settled",
      railNever: "never opened",
      railTransactions: "{count} × {state}",
      chainReceipt: "receipt",
      chainGrant: "credit",
      chainNotified: "told",
      chainNone: "nothing yet",
      sandboxBadge: "sandbox",
      planShape: "{songs} songs · {days} days",
      emptyVirgin: "No payment has ever been opened here",
      emptyFiltered: "No payment matches these filters",
      emptyFailed: "The payments list failed to load",
      chips: {
        state: "State",
        product: "Product",
        settledBy: "Settled by",
        attention: "Needs attention",
        sandbox: "Sandbox",
        openedFrom: "Opened from",
        openedThrough: "Opened through",
      },
    },
    lifeline: {
      title: "What happened to this money",
      steps: {
        opened: "Checkout opened",
        railTransaction: "Payme opened a transaction",
        performed: "Payme took the money",
        receipt: "Sale recorded",
        creditGranted: "Credit granted",
        customerTold: "Customer told",
      },
      status: {
        done: "done",
        pending: "not yet",
        notApplicable: "not applicable",
        missing: "missing",
      },
      notes: {
        neverOpened:
          "Payme has never opened a transaction against this payment. That is also what a payment settled by hand looks like.",
        awaitingRail:
          "A transaction is open and the rail has not come back. Our clock and Payme's are not the same clock, so this is waiting rather than late.",
        buyerErased:
          "The buyer asked to be forgotten. The money moved and there is nobody left to grant to or tell — this is a state, not a discrepancy.",
        planGrantsNothing:
          "A plan mints songs as they are used, so it grants no credit at purchase.",
        notSettled:
          "This payment never settled, so nothing after it was ever going to happen.",
        alreadyTold: "The confirmation went out.",
        purged:
          "The row that recorded this has been deleted on its retention schedule. It happened; the evidence has aged out.",
      },
    },
    dossier: {
      title: "Payment {reference}",
      back: "All payments",
      notFound: "No payment under that id",
      notFoundMessage:
        "This deployment holds no payment with that identifier. Check the reference in the box on the board.",
      intentPanel: "The payment",
      transactionsPanel: "Payme's transactions",
      receiptPanel: "The sale",
      ledgerPanel: "Credit ledger",
      callsPanel: "Payme's calls about this payment",
      chainStopPanel: "Did it become a song?",
      transactionsNone:
        "Payme has never opened a transaction against this payment.",
      receiptNone: "No sale has been recorded for this payment.",
      ledgerNone: "No credit movement was written under this payment.",
      callsNever: "Payme has never called us about this payment.",
      callsPurged:
        "This payment is older than the 90 days the inbound journal is kept for, so its calls have aged out. Purged, not absent.",
      chainStopSingle:
        "Unanswerable, by design. A credit balance is a single number with no lots, so no query can prove which song a purchased credit rendered.",
      chainStopPlan: "{used} of {included} songs used on this plan.",
      chainStopPlanUnknown:
        "No plan receipt was recorded, so there is nothing counting songs against it.",
      settleByHand: "Settle this by hand",
      settleByHandCaveat:
        "The console cannot do this and will not offer to. It is run in a terminal, and only after a charge for this reference is confirmed in the Payme merchant cabinet — which this process is structurally forbidden to see.",
      copyCommand: "Copy the command",
      copied: "Copied",
      fields: {
        reference: "Reference",
        state: "State",
        product: "Product",
        amount: "Amount",
        buyer: "Buyer",
        merchant: "Merchant",
        opened: "Opened",
        validUntil: "Valid until",
        settled: "Settled",
        notified: "Confirmation sent",
        settleNote: "Settled by",
        cancelReason: "Cancel reason",
        performTime: "Performed",
        createTime: "Created",
        cancelTime: "Cancelled",
        paymeTime: "Payme's clock",
        source: "Recorded in",
        provider: "Provider",
        cabinetReference: "Cabinet reference",
        creditsGranted: "Credits granted",
        songsIncluded: "Songs included",
        songsUsed: "Songs used",
        planEndsAt: "Plan ends",
        kind: "Kind",
        delta: "Change",
        reason: "Reason",
        actor: "Written by",
      },
    },
    notify: {
      action: "Re-send the confirmation",
      pending: "Queueing…",
      confirmTitle: "Re-send this confirmation?",
      confirmBody:
        "The customer is told about a payment they already made. Nothing is charged, no credit is issued and no money row is written. Pressing this twice sends one message.",
      confirmLabel: "Re-send the confirmation",
      refusalNotPaid:
        "This payment has not settled, so there is nothing to confirm.",
      refusalBuyerErased:
        "The buyer asked to be forgotten. There is nobody to send this to; the receipt and the credit are untouched.",
      refusalAlreadyNotified:
        "The confirmation has already gone out. The job stops on that stamp, so re-sending would do nothing.",
      sent: "Queued. The worker sends it within the minute.",
      replayed:
        "Already queued — this press changed nothing, which is the job doing its work.",
      reasonLabel: "Why this is being re-sent",
      reasonHint:
        "Goes on the audit row against your name. Your words, never the customer's.",
      notDelivered:
        "This records that we sent it. Whether the customer saw it is a Telegram fact this database does not hold.",
    },
    pause: {
      pauseAction: "Pause checkouts",
      resumeAction: "Resume checkouts",
      pauseTitle: "Pause new checkouts?",
      pauseBody:
        "The bot stops quoting new checkout links. Payments already in flight are unaffected and no money moves. Any operator can undo this in one press.",
      pauseLabel: "Pause checkouts",
      pausePending: "Pausing…",
      resumeTitle: "Resume checkouts?",
      resumeBody:
        "The bot starts quoting checkout links again. Nothing that happened while paused is replayed.",
      resumeLabel: "Resume checkouts",
      resumePending: "Resuming…",
      reasonLabel: "Why the switch is being moved",
      reasonHint:
        "Goes on the audit row against your name. One line is enough.",
    },
    calls: {
      title: "Inbound calls",
      subtitle:
        "Every JSON-RPC call Payme made to this deployment, newest first.",
      caption: "Inbound calls from Payme",
      columns: {
        at: "At",
        method: "Method",
        replyCode: "Reply",
        reference: "Reference",
        transactionId: "Payme transaction",
        duration: "Took",
        peerIp: "Peer",
      },
      peerIpNote: "Payme's data centre, never a customer.",
      faultsOnly: "Faults only",
      allCalls: "All calls",
      empty: "Payme has never called this endpoint",
      emptyMessage:
        "On a live rail this is also what a payment settled by hand looks like, so it is never a synonym for “the gateway is down”.",
      emptyFiltered: "No call matches these filters",
      emptyFilteredMessage:
        "Calls exist on this deployment; none is in the range or of the kind you asked for.",
      emptyFailed: "The journal failed to load",
      emptyFailedMessage:
        "The note above carries what the server said and the correlation id to quote.",
      chips: {
        method: "Method",
        faultsOnly: "Faults only",
        reference: "Reference",
        transactionId: "Payme transaction",
        from: "From",
        through: "Through",
      },
    },
  },
  support: {
    title: "Support",
    subject: "the support queue",
    subjectOne: "this ticket",
    subjectBoard: "the support board",
    atLeast: "at least {count}",
    refresh: "Refresh",
    backToBoard: "Back to the board",
    openTicket: "Open ticket",
    tableCaption: "Support tickets, newest first",
    filtersAria: "Ticket filters",
    subtitles: {
      reading: "Reading the queue…",
      failed: "The queue could not be read",
      onThisPage: "{count} on this page",
      tickets: "{count} tickets",
      ticketsFiltered: "{count} tickets match these filters",
    },
    range: {
      onPage: "{count} on this page",
      onPageOf: "{count} of {total}",
      none: "No tickets yet",
      noneMatching: "No ticket matches these filters",
    },
    board: {
      aria: "Support board, four columns",
      columnAria: "{status}, {count} tickets",
      cardAria: "Ticket {reference} from {customer}, {status}",
      columnCount: "{count} in this column",
      empty: "Nothing in this column",
      emptyFiltered: "Nothing here matches these filters",
      loading: "Reading the board…",
      undescribedHidden:
        "Tickets nobody described are not on the board — somebody tapped the button and never typed. Those rows are kept, and the list is where to find them.",
      dropHere: "Move to {status}",
      cannotDropHere: "A ticket in {from} cannot be moved to {to}",
    },
    status: {
      new: "New",
      inProgress: "In progress",
      waiting: "Waiting on customer",
      resolved: "Resolved",
    },
    statusHint: {
      new: "Nobody has looked at this yet. Nothing ever comes back to this column.",
      inProgress: "Somebody has it, and the customer is waiting on us.",
      waiting:
        "We asked the customer something, and the answer is theirs to send. Nothing here moves until they reply.",
      resolved:
        "Answered and closed. A reply from the customer reopens it into In progress, and the date it was closed is kept.",
    },
    source: {
      deliveryButton: "Delivered song",
      supportCommand: "/support",
    },
    sourceHint: {
      deliveryButton:
        "Opened from the button under a delivered song, so it carries the order.",
      supportCommand:
        "Typed from anywhere in the bot, so no order is attached. It is the same queue.",
    },
    card: {
      reference: "Reference",
      customer: "Customer",
      order: "Order",
      noOrder: "No order",
      opened: "Opened",
      updated: "Last change",
      assignee: "With",
      unassigned: "Nobody",
      events: "{count} entries",
      language: "Written in",
      body: "What they told us",
      noBody: "Nothing was described",
      noBodyHint:
        "The customer opened this and never typed. The row is kept because it is the only measure of how many people tried to tell us something and gave up.",
      inGroup: "Posted to the support group",
      notInGroup: "Not in the support group",
      notInGroupHint:
        "The card is still owed, or this deployment has no support group configured. The ticket is not lost and the customer has their reference.",
      resolvedAt: "Closed",
      reopened: "Reopened",
      reopenedHint:
        "This was closed once and is open again. The date it was closed is deliberately kept.",
    },
    actions: {
      move: "Move",
      moveTo: "Move to {status}",
      claim: "Take it",
      assign: "Hand over",
      reply: "Reply to the customer",
      note: "Add an internal note",
      reopen: "Reopen",
      resolve: "Resolve",
      pickColumn: "Choose a column",
      readOnly: "Your role can read tickets but not answer them.",
      cancel: "Cancel",
    },
    dialogs: {
      assign: {
        title: "Hand this ticket to an operator",
        label: "Operator username",
        placeholder: "dilnoza",
        hint: "Not checked against the roster: the name is recorded as it was, so an operator who leaves does not take the queue's history with them.",
        submit: "Hand over",
        pending: "Handing over…",
        invalid:
          "Lowercase letters, digits, dots, dashes and underscores only.",
      },
      reply: {
        title: "Reply to the customer",
        label: "Your answer",
        placeholder: "Write in the language the ticket was opened in.",
        hint: "Sent to the customer in the bot, in the language they wrote to us in.",
        submit: "Send",
        pending: "Sending…",
        warning:
          "These words go into somebody's phone. There is no way to unsend them.",
        remaining: "{count} characters left",
      },
      note: {
        title: "Add an internal note",
        label: "Note",
        placeholder: "What the next operator needs to know.",
        hint: "Kept on this ticket's timeline, beside everything else that happened to it.",
        submit: "Save the note",
        pending: "Saving…",
        warning:
          "The customer never sees this — and neither do the staff working from the card in the Telegram group.",
      },
      move: {
        title: "Move this ticket",
        body: "Moving it to {status}.",
        reopenBody:
          "Reopening this ticket into {status}. The date it was closed is kept, so it stays visible as a complaint that came back.",
        submit: "Move",
        pending: "Moving…",
      },
    },
    timeline: {
      title: "What happened",
      empty: "Nothing has happened to this ticket yet",
      relayed: "Delivered {when}",
      notRelayed: "Not delivered",
      notRelayedHint:
        "This answer was written and has not reached the customer. They may have blocked the bot, or no worker was running when it was sent.",
      statusMove: "{from} → {to}",
      assignedTo: "Handed to {username}",
      unknownAuthor: "Unknown",
      kind: {
        opened: "Ticket opened",
        described: "The customer described the problem",
        statusChange: "Moved",
        note: "Internal note",
        reply: "Replied to the customer",
        assigned: "Handed over",
        groupPosted: "Posted to the support group",
      },
      author: {
        customer: "The customer",
        operator: "Operator",
        staffGroup: "Staff, in the Telegram group",
        system: "The system",
      },
    },
    dnd: {
      instructions:
        "Press Space to pick a ticket up, the arrow keys to choose a column, Space again to move it, Escape to put it back.",
      grabbed:
        "Ticket {reference} picked up from {status}. Use the arrow keys to choose a column.",
      dropped: "Ticket {reference} put back in {status}.",
      moved: "Ticket {reference} moved from {from} to {to}.",
      cancelled: "Move cancelled. Ticket {reference} is still in {status}.",
      blocked: "A ticket in {from} cannot be moved to {to}.",
    },
    empty: {
      title: "Nobody has written in",
      message:
        "A ticket arrives when a customer taps the button under a delivered song, or types /support in the bot.",
      filteredTitle: "No ticket matches these filters",
      filteredMessage:
        "Tickets exist; none is in the range or of the kind you asked for.",
    },
    notes: {
      forbiddenMessage:
        "Your role may not read this. Nothing here retries, and asking again would only record another refusal.",
      sessionEndedMessage:
        "{message} Sign in again and the queue will be where you left it.",
      refusedFiltersMessage: "{message} Narrow the filters and ask again.",
      notFoundMessage:
        "No ticket is held under that id. It may have been erased at the customer's request — a ticket is deleted rather than anonymised.",
      conflictTitle: "This ticket moved first",
      conflictMessage:
        "Somebody else moved it while you were reading — most often a staffer pressing a button on the card in the Telegram group. Nothing was written, and the ticket is being re-read.",
      workerTitle: "The worker is not reachable",
      workerMessage:
        "Nothing was written. A change here has to reach the card in the Telegram group, so the whole action is refused rather than half-done — otherwise the board and the card would disagree for ever.",
    },
    filter: {
      status: "Column",
      statusHint: "Where the ticket is now.",
      source: "Opened from",
      sourceHint:
        "Which door it came through. Both file the same kind of ticket.",
      language: "Written in",
      languageHint:
        "The language the ticket was opened in — the one a reply has to be written in.",
      assignedTo: "With",
      assignedToHint:
        "An exact name, and deliberately not part of the search box: “Dilnoza's tickets” and “tickets that mention Dilnoza” are two questions.",
      search: "Reference or words",
      searchHint: "Matches the reference and the customer's own words.",
      onlyDescribed: "Only described",
      onlyDescribedHint:
        "Hide the tickets somebody opened and never typed into. The board hides them always.",
    },
    chips: {
      status: "Column",
      source: "Opened from",
      language: "Written in",
      assignedTo: "With",
      search: "Search",
      onlyDescribed: "Only described",
      join: ", ",
    },
    groups: {
      open: "Support group",
      title: "Where ticket cards are posted",
      subject: "the support group",
      subtitle:
        "Every ticket is filed here whatever this says. This is the Telegram group the bot posts a card into when one arrives, and whether it has been proved able to post there.",
      constraint:
        "Telegram gives a bot no list of its groups — it only learns of one when it is added. For a group it is already in, paste the chat id.",
      close: "Close",
      refresh: "Refresh",
      known: "Chats the bot knows about",
      listAria: "Chats the bot knows about",
      loading: "Reading the chat directory…",
      emptyMessage:
        "Nothing has been recorded yet. Add the bot to a group and it appears here, or paste a chat id below.",
      readOnly:
        "Your role can see the group but not change it. That needs support.group.write.",
      botStatusHint:
        "What Telegram last said about the bot's standing here, at the moment it said it. Evidence, not permission — only a check proves the bot can post.",
      current: {
        heading: "Ticket cards go to",
        none: "No group is selected",
        noneHint:
          "Tickets still work and customers still get a reference. Only the Telegram card is not posted.",
        thread: "In topic {id}",
        noThread: "In the group itself, no topic",
        chosenBy: "chosen by {username} on {when}",
      },
      row: {
        selected: "Receives tickets",
        thread: "topic {id}",
        selectAria: "Post ticket cards to {chat}",
      },
      type: {
        group: "Group",
        supergroup: "Supergroup",
        channel: "Channel",
      },
      source: {
        membershipEvent: "Telegram told us",
        manual: "Typed in",
      },
      sourceHint: {
        membershipEvent:
          "The bot was added to or removed from this chat and Telegram sent an update saying so.",
        manual:
          "Somebody pasted this chat id. Nothing has confirmed the bot is in this room except the check below.",
      },
      botStatus: {
        member: "Member",
        administrator: "Administrator",
        restricted: "Restricted",
        left: "Left",
        kicked: "Removed",
        unknown: "Not known",
      },
      verification: {
        verified: "Posting works",
        failed: "Cannot post",
        checking: "Checking…",
        verifiedWhen: "A message reached this chat {when}.",
        checkingHint:
          "A test message is on its way. Refresh in a moment; if nothing changes, no worker is running.",
      },
      actions: {
        select: "Post tickets here",
        recheck: "Check again",
        selecting: "Selecting…",
        clear: "Stop posting to a group",
        clearing: "Stopping…",
        clearHint:
          "Tickets keep working; only the Telegram card stops.",
      },
      paste: {
        heading: "Use a chat id",
        hint:
          "For a group the bot is already in. Forward a message from it to a bot that reports chat ids.",
        chatLabel: "Chat id",
        chatPlaceholder: "-1001234567890",
        chatHint: "A group chat id is negative and starts with a minus.",
        chatIsPerson:
          "That is not a group. A chat id without a minus belongs to one person, and ticket cards posted there would be visible to nobody else.",
        threadLabel: "Topic id (optional)",
        threadPlaceholder: "12",
        threadHint:
          "Empty posts into the group itself.",
        threadInvalid: "A topic id is a whole number above zero.",
        submit: "Post tickets here",
      },
      notes: {
        forbiddenMessage:
          "Your role may not change where ticket cards are posted. Asking again cannot change that, and each attempt is recorded as a refusal.",
        sessionEndedMessage:
          "{message} Sign in again and this screen will be where you left it.",
        conflictTitle: "Somebody else changed it first",
        conflictMessage:
          "Another operator chose a group at the same moment, and only one group can be selected. Nothing of yours was written — read the list again and choose from what it now says.",
        refusedTitle: "That chat id was refused",
        refusedMessage: "{message} Nothing was written.",
        workerTitle: "Selected, and nothing can check it",
        workerMessage:
          "The group was changed and the change is saved. No worker is running, so nothing posted a test message — this chat stays unchecked until one does.",
      },
    },
  },
};

export default en;
