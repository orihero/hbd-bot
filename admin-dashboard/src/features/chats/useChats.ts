/**
 * React Query hooks for the Chats console.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  fetchChatTranscript,
  fetchConversations,
  type ChatConversationsResponse,
  type ChatTranscriptResponse,
} from "@/api/chats";
import { unwrap, type AdminQueryError } from "@/lib/adminQuery";

export const CHATS_QUERY_KEY = ["admin", "chats"] as const;

export function useChatConversations(
  searchQuery: string = "",
): UseQueryResult<ChatConversationsResponse, AdminQueryError> {
  const trimmed = searchQuery.trim();
  return useQuery({
    queryKey: [...CHATS_QUERY_KEY, "conversations", trimmed],
    queryFn: ({ signal }) =>
      unwrap(
        fetchConversations({
          q: trimmed,
          signal,
        }),
      ),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

export function useChatTranscript(
  telegramUserId: number | null,
): UseQueryResult<ChatTranscriptResponse, AdminQueryError> {
  return useQuery({
    queryKey: [...CHATS_QUERY_KEY, "transcript", telegramUserId],
    queryFn: ({ signal }) => {
      if (telegramUserId === null) {
        throw new Error("No user specified");
      }
      return unwrap(
        fetchChatTranscript(telegramUserId, {
          signal,
        }),
      );
    },
    enabled: telegramUserId !== null,
    staleTime: 3_000,
    refetchInterval: 5_000,
  });
}
