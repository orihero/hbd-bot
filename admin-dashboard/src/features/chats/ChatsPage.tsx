/**
 * Chats replication and history console (/chats and /chats/:telegramUserId).
 */

import { useEffect, useMemo, useRef, useState, type JSX } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  ExternalLink,
  MessageSquare,
  Mic,
  Music,
  RefreshCw,
  Search,
  User,
  X,
} from "lucide-react";

import { PATH, userDetailPath } from "@/app/paths";
import { Avatar } from "@/components/Avatar";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar } from "@/components/Toolbar";
import { formatDay } from "@/features/users/detailFormat";
import { QueryErrorNote } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useSessionGuard } from "@/state/useSessionGuard";

import { useChatConversations, useChatTranscript } from "./useChats";

function initialsOf(
  firstName: string | null,
  lastName: string | null,
  username: string | null,
): string {
  const f = firstName?.trim() ?? "";
  const l = lastName?.trim() ?? "";
  if (f.length > 0) {
    const firstChar = f[0] ?? "";
    const secondChar = l.length > 0 ? (l[0] ?? "") : (f[1] ?? "");
    return (firstChar + secondChar).toUpperCase();
  }
  const u = username?.trim() ?? "";
  if (u.length > 0) {
    return u.slice(0, 2).toUpperCase();
  }
  return "TG";
}

function formatTimeOnly(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export function ChatsPage(): JSX.Element {
  const { t } = useI18n();
  const params = useParams<{ telegramUserId?: string }>();
  const navigate = useNavigate();

  const selectedUserId = useMemo(() => {
    if (!params.telegramUserId) return null;
    const n = Number(params.telegramUserId);
    return Number.isSafeInteger(n) && n > 0 ? n : null;
  }, [params.telegramUserId]);

  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const conversationsQuery = useChatConversations(debouncedQuery);
  const transcriptQuery = useChatTranscript(selectedUserId);

  useSessionGuard([conversationsQuery.error, transcriptQuery.error]);

  const conversations = useMemo(
    () => conversationsQuery.data?.items ?? [],
    [conversationsQuery.data?.items],
  );
  const selectedConversation = useMemo(
    () => conversations.find((c) => c.telegramUserId === selectedUserId) ?? null,
    [conversations, selectedUserId],
  );

  const messages = transcriptQuery.data?.messages ?? [];

  // Auto-scroll to bottom of messages when conversation or transcript changes
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (messages.length > 0 && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [selectedUserId, messages.length]);

  return (
    <div className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-[1600px] flex-col gap-3 p-3 sm:p-4 lg:p-6">
      <Toolbar
        title={t("chats.title")}
        subtitle={t("chats.subtitle")}
      />

      {/* Master-Detail Two-Column Container */}
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden rounded-2xl border border-stroke bg-card shadow-xs lg:grid-cols-[380px_1fr]">
        {/* Left Column: Conversation List */}
        <aside className="flex flex-col border-r border-stroke bg-surface/40">
          {/* Search Header */}
          <div className="border-b border-stroke p-3">
            <div className="relative flex items-center">
              <Search className="absolute left-3 h-4 w-4 text-ink-400" />
              <input
                type="search"
                placeholder={t("chats.searchPlaceholder")}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-stroke bg-card py-1.5 pl-9 pr-8 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent focus:outline-hidden focus:ring-1 focus:ring-accent"
              />
              {searchQuery ? (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2.5 text-ink-400 hover:text-ink-600"
                  aria-label={t("chats.clearSearch")}
                >
                  <X className="h-4 w-4" />
                </button>
              ) : null}
            </div>
          </div>

          {/* Conversations Scroll Area */}
          <div className="flex-1 overflow-y-auto divide-y divide-stroke/50">
            {conversationsQuery.isLoading ? (
              <div className="flex flex-col gap-3 p-4">
                <Skeleton className="h-14 w-full rounded-xl" />
                <Skeleton className="h-14 w-full rounded-xl" />
                <Skeleton className="h-14 w-full rounded-xl" />
                <Skeleton className="h-14 w-full rounded-xl" />
              </div>
            ) : conversationsQuery.isError ? (
              <div className="p-4">
                <QueryErrorNote
                  noun={t("chats.title")}
                  error={conversationsQuery.error}
                  onRetry={() => {
                    void conversationsQuery.refetch();
                  }}
                />
              </div>
            ) : conversations.length === 0 ? (
              <div className="p-8 text-center text-ink-400">
                <MessageSquare className="mx-auto mb-2 h-8 w-8 text-ink-300" />
                <p className="text-sm font-medium">{t("chats.noThreadsFound")}</p>
                {searchQuery ? (
                  <p className="text-xs text-ink-400">{t("chats.noThreadsSearchHint")}</p>
                ) : (
                  <p className="text-xs text-ink-400">{t("chats.noThreadsEmptyHint")}</p>
                )}
              </div>
            ) : (
              conversations.map((thread) => {
                const isSelected = thread.telegramUserId === selectedUserId;
                const initials = initialsOf(thread.firstName, thread.lastName, thread.username);
                const displayName =
                  [thread.firstName, thread.lastName].filter(Boolean).join(" ") ||
                  (thread.username ? `@${thread.username}` : `ID: ${String(thread.telegramUserId)}`);

                return (
                  <button
                    key={thread.telegramUserId}
                    type="button"
                    onClick={() => {
                      navigate(`${PATH.chats}/${String(thread.telegramUserId)}`);
                    }}
                    className={cn(
                      "flex w-full items-start gap-3 p-3.5 text-left transition-colors",
                      isSelected
                        ? "bg-accent/10 hover:bg-accent/15"
                        : "hover:bg-surface/80",
                    )}
                  >
                    <Avatar
                      initials={initials}
                      size={36}
                      className="shrink-0 mt-0.5"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-1">
                        <span className="truncate text-sm font-semibold text-ink-900">
                          {displayName}
                        </span>
                        <span className="shrink-0 text-[11px] text-ink-400">
                          {formatTimeOnly(thread.lastMessageAt) || formatDay(thread.lastMessageAt)}
                        </span>
                      </div>

                      <div className="mt-0.5 flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-1 text-xs text-ink-500">
                          {thread.lastMessageDirection === "outbound" ? (
                            <ArrowUpRight className="h-3 w-3 shrink-0 text-accent" />
                          ) : (
                            <ArrowDownLeft className="h-3 w-3 shrink-0 text-ink-400" />
                          )}
                          <span className="truncate">
                            {thread.lastMessageKind === "audio"
                              ? t("chats.badgeAudioMessage")
                              : thread.lastMessageKind === "callback"
                                ? t("chats.callback", { data: thread.lastMessageText ?? "" })
                                : thread.lastMessageText || t("chats.media")}
                          </span>
                        </div>

                        <span className="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-[10px] font-medium text-ink-600 border border-stroke">
                          {thread.messageCount}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* Right Column: Transcript View */}
        <main className="flex flex-col bg-card overflow-hidden">
          {selectedUserId === null ? (
            <div className="flex h-full flex-col items-center justify-center p-8">
              <EmptyState
                title={t("chats.selectConversation")}
                message={t("chats.selectConversationHint")}
                icon={<MessageSquare className="h-6 w-6 text-ink-300" />}
              />
            </div>
          ) : (
            <>
              {/* Selected Conversation Header */}
              <header className="flex flex-wrap items-center justify-between gap-3 border-b border-stroke bg-surface/30 px-5 py-3.5">
                <div className="flex items-center gap-3 min-w-0">
                  <Avatar
                    initials={
                      selectedConversation
                        ? initialsOf(
                            selectedConversation.firstName,
                            selectedConversation.lastName,
                            selectedConversation.username,
                          )
                        : "TG"
                    }
                    size={38}
                  />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="truncate text-sm font-semibold text-ink-900">
                        {selectedConversation
                          ? [selectedConversation.firstName, selectedConversation.lastName]
                              .filter(Boolean)
                              .join(" ") || `@${selectedConversation.username || ""}`
                          : t("chats.userFallbackName", { id: selectedUserId })}
                      </h2>
                      {selectedConversation?.username ? (
                        <span className="text-xs text-ink-400">
                          @{selectedConversation.username}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-ink-400">
                      <span>{t("chats.tgId", { id: selectedUserId })}</span>
                      <span>•</span>
                      <span>{t("chats.messagesCount", { count: messages.length })}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Link
                    to={userDetailPath(selectedUserId)}
                    className="inline-flex items-center gap-1 rounded-lg border border-stroke bg-card px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-2xs hover:bg-surface hover:text-ink-900"
                    title={t("chats.openUserDetails")}
                  >
                    <User className="h-3.5 w-3.5" />
                    <span>{t("chats.viewProfile")}</span>
                    <ExternalLink className="h-3 w-3 text-ink-400" />
                  </Link>

                  <button
                    type="button"
                    onClick={() => {
                      void transcriptQuery.refetch();
                    }}
                    disabled={transcriptQuery.isFetching}
                    className="inline-flex items-center gap-1 rounded-lg border border-stroke bg-card px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-2xs hover:bg-surface hover:text-ink-900 disabled:opacity-50"
                    title={t("chats.refresh")}
                  >
                    <RefreshCw
                      className={cn(
                        "h-3.5 w-3.5",
                        transcriptQuery.isFetching && "animate-spin text-accent",
                      )}
                    />
                    <span>{t("chats.refresh")}</span>
                  </button>
                </div>
              </header>

              {/* Message Transcript Timeline */}
              <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 bg-bg/30">
                {transcriptQuery.isLoading ? (
                  <div className="flex flex-col gap-4">
                    <Skeleton className="h-16 w-3/4 self-start rounded-2xl" />
                    <Skeleton className="h-20 w-3/4 self-end rounded-2xl" />
                    <Skeleton className="h-16 w-1/2 self-start rounded-2xl" />
                    <Skeleton className="h-24 w-4/5 self-end rounded-2xl" />
                  </div>
                ) : transcriptQuery.isError ? (
                  <div className="p-4">
                    <QueryErrorNote
                      noun={t("chats.sectionTranscript")}
                      error={transcriptQuery.error}
                      onRetry={() => {
                        void transcriptQuery.refetch();
                      }}
                    />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex h-full flex-col items-center justify-center p-8 text-center text-ink-400">
                    <MessageSquare className="h-8 w-8 text-ink-300 mb-2" />
                    <p className="text-sm font-medium">{t("chats.noMessagesYet")}</p>
                    <p className="text-xs text-ink-400">{t("chats.noMessagesHint")}</p>
                  </div>
                ) : (
                  messages.map((msg, idx) => {
                    const isInbound = msg.direction === "inbound";
                    const prev = messages[idx - 1];
                    const isPrevSameDate =
                      idx > 0 &&
                      prev !== undefined &&
                      formatDay(prev.createdAt) === formatDay(msg.createdAt);

                    return (
                      <div key={msg.id} className="space-y-3">
                        {/* Day Divider */}
                        {!isPrevSameDate ? (
                          <div className="relative my-4 flex items-center justify-center">
                            <div className="absolute inset-0 flex items-center">
                              <div className="w-full border-t border-stroke" />
                            </div>
                            <span className="relative rounded-full border border-stroke bg-card px-3 py-0.5 text-[11px] font-medium text-ink-400 shadow-2xs">
                              {formatDay(msg.createdAt)}
                            </span>
                          </div>
                        ) : null}

                        {/* Bubble Container */}
                        <div
                          className={cn(
                            "flex w-full",
                            isInbound ? "justify-start" : "justify-end",
                          )}
                        >
                          <div
                            className={cn(
                              "flex max-w-[85%] sm:max-w-[75%] flex-col gap-1 rounded-2xl p-3.5 shadow-2xs",
                              isInbound
                                ? "rounded-tl-xs border border-stroke bg-card text-ink-900"
                                : "rounded-tr-xs border border-accent/20 bg-accent/5 text-ink-900",
                            )}
                          >
                            {/* Sender Info & Badges */}
                            <div className="flex items-center justify-between gap-2 text-[11px] text-ink-400">
                              <div className="flex items-center gap-1.5 font-medium">
                                {isInbound ? (
                                  <>
                                    <User className="h-3 w-3 text-ink-500" />
                                    <span className="text-ink-700">{t("chats.customer")}</span>
                                  </>
                                ) : (
                                  <>
                                    <Bot className="h-3.5 w-3.5 text-accent" />
                                    <span className="font-semibold text-accent">{t("chats.bayramBot")}</span>
                                  </>
                                )}

                                {msg.wizardStep ? (
                                  <span className="rounded-sm bg-surface px-1.5 py-0.2 text-[10px] text-ink-500 border border-stroke/60">
                                    {t("chats.wizardStep", { step: msg.wizardStep })}
                                  </span>
                                ) : null}
                              </div>

                              <span className="text-[11px] text-ink-400">
                                {formatTimeOnly(msg.createdAt)}
                              </span>
                            </div>

                            {/* Message Body Content */}
                            <div className="mt-1 text-sm leading-relaxed whitespace-pre-wrap break-words">
                              {msg.kind === "callback" ? (
                                <div className="rounded-lg border border-stroke bg-surface/70 px-2.5 py-1.5 font-mono text-xs text-ink-700">
                                  <span className="font-semibold text-ink-500">🔘 {t("chats.buttonCallback")}</span>{" "}
                                  <span>{msg.callbackData || msg.body}</span>
                                </div>
                              ) : msg.kind === "audio" ? (
                                <div className="flex items-center gap-2 rounded-lg border border-accent/20 bg-card p-2.5">
                                  <Music className="h-5 w-5 text-accent shrink-0" />
                                  <div className="min-w-0 flex-1">
                                    <p className="text-xs font-semibold text-ink-900">
                                      {t("chats.audioPreview")}
                                    </p>
                                    <p className="truncate text-xs text-ink-500">
                                      {msg.body || t("chats.songPreview")}
                                    </p>
                                  </div>
                                </div>
                              ) : msg.kind === "voice" ? (
                                <div className="flex items-center gap-2 rounded-lg border border-stroke bg-card p-2.5">
                                  <Mic className="h-5 w-5 text-ink-600 shrink-0" />
                                  <div className="min-w-0 flex-1">
                                    <p className="text-xs font-semibold text-ink-900">
                                      {t("chats.voiceNote")}
                                    </p>
                                    <p className="truncate text-xs text-ink-500">
                                      {msg.body || t("chats.voiceMessage")}
                                    </p>
                                  </div>
                                </div>
                              ) : (
                                <span>{msg.body}</span>
                              )}
                            </div>

                            {msg.isTruncated ? (
                              <p className="mt-1 text-[10px] text-warn italic">
                                {t("chats.truncatedNote")}
                              </p>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
