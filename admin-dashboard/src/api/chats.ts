/**
 * Chats API client and response schemas.
 */

import { z } from "zod";

import { request, type ApiResult } from "./client";

export const ChatConversationItemSchema = z.object({
  telegramUserId: z.number(),
  username: z.string().nullable(),
  firstName: z.string().nullable(),
  lastName: z.string().nullable(),
  phoneE164: z.string().nullable(),
  hasAvatar: z.boolean(),
  lastMessageText: z.string().nullable(),
  lastMessageDirection: z.enum(["inbound", "outbound"]).nullable(),
  lastMessageKind: z.string().nullable(),
  lastMessageAt: z.string(),
  messageCount: z.number(),
});

export type ChatConversationItem = z.infer<typeof ChatConversationItemSchema>;

export const ChatConversationsResponseSchema = z.object({
  items: z.array(ChatConversationItemSchema),
  total: z.number(),
});

export type ChatConversationsResponse = z.infer<typeof ChatConversationsResponseSchema>;

export const ChatMessageViewSchema = z.object({
  id: z.string(),
  telegramUserId: z.number(),
  chatId: z.number(),
  direction: z.enum(["inbound", "outbound"]),
  kind: z.enum(["text", "callback", "screen", "audio", "voice", "toast", "action"]),
  body: z.string().nullable(),
  wizardStep: z.string().nullable(),
  telegramMessageId: z.number().nullable(),
  callbackData: z.string().nullable(),
  isTruncated: z.boolean(),
  createdAt: z.string(),
});

export type ChatMessageView = z.infer<typeof ChatMessageViewSchema>;

export const ChatTranscriptResponseSchema = z.object({
  telegramUserId: z.number(),
  messages: z.array(ChatMessageViewSchema),
  total: z.number(),
});

export type ChatTranscriptResponse = z.infer<typeof ChatTranscriptResponseSchema>;

export interface FetchConversationsParams {
  readonly q?: string;
  readonly limit?: number;
  readonly offset?: number;
  readonly signal?: AbortSignal;
}

export async function fetchConversations(
  params: FetchConversationsParams = {},
): Promise<ApiResult<ChatConversationsResponse>> {
  const query = new URLSearchParams();
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));

  const qs = query.toString();
  const path = qs ? `/api/chats?${qs}` : "/api/chats";

  return request({
    endpoint: "GET /api/chats",
    path,
    schema: ChatConversationsResponseSchema,
    ...(params.signal ? { signal: params.signal } : {}),
  });
}

export interface FetchTranscriptParams {
  readonly limit?: number;
  readonly beforeId?: string;
  readonly signal?: AbortSignal;
}

export async function fetchChatTranscript(
  telegramUserId: number,
  params: FetchTranscriptParams = {},
): Promise<ApiResult<ChatTranscriptResponse>> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.beforeId) query.set("before_id", params.beforeId);

  const qs = query.toString();
  const path = qs
    ? `/api/chats/${encodeURIComponent(String(telegramUserId))}/messages?${qs}`
    : `/api/chats/${encodeURIComponent(String(telegramUserId))}/messages`;

  return request({
    endpoint: "GET /api/chats/{telegram_user_id}/messages",
    path,
    schema: ChatTranscriptResponseSchema,
    ...(params.signal ? { signal: params.signal } : {}),
  });
}
