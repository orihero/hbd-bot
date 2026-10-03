import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getMusicProviderConfig,
  setMusicProviderConfig,
  type MusicProviderConfig,
  type SetMusicProviderRequest,
} from "@/api/config";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  unwrap,
  type AdminQueryError,
} from "@/lib/adminQuery";

export const musicConfigKeys = {
  all: ["config"] as const,
  musicProvider: () => ["config", "music-provider"] as const,
} as const;

export function useMusicProviderConfig(): UseQueryResult<
  MusicProviderConfig,
  AdminQueryError
> {
  return useQuery<MusicProviderConfig, AdminQueryError>({
    queryKey: musicConfigKeys.musicProvider(),
    queryFn: ({ signal }) => unwrap(getMusicProviderConfig(signal)),
    ...LIST_READ,
  });
}

export function useSetMusicProvider(): UseMutationResult<
  MusicProviderConfig,
  AdminQueryError,
  SetMusicProviderRequest
> {
  const queryClient = useQueryClient();
  return useMutation<
    MusicProviderConfig,
    AdminQueryError,
    SetMusicProviderRequest
  >({
    mutationFn: (payload) => unwrap(setMusicProviderConfig(payload)),
    onSuccess: (result) => {
      queryClient.setQueryData<MusicProviderConfig>(
        musicConfigKeys.musicProvider(),
        result,
      );
    },
    ...PRIVILEGED_WRITE,
  });
}

