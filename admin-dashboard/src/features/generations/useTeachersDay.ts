import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getTeachersDayConfig,
  setTeachersDayConfig,
  type TeachersDayConfig,
  type SetTeachersDayRequest,
} from "@/api/config";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  unwrap,
  type AdminQueryError,
} from "@/lib/adminQuery";

export const teachersDayConfigKeys = {
  all: ["config"] as const,
  teachersDay: () => ["config", "teachers-day"] as const,
} as const;

export function useTeachersDayConfig(): UseQueryResult<
  TeachersDayConfig,
  AdminQueryError
> {
  return useQuery<TeachersDayConfig, AdminQueryError>({
    queryKey: teachersDayConfigKeys.teachersDay(),
    queryFn: ({ signal }) => unwrap(getTeachersDayConfig(signal)),
    ...LIST_READ,
  });
}

export function useSetTeachersDay(): UseMutationResult<
  TeachersDayConfig,
  AdminQueryError,
  SetTeachersDayRequest
> {
  const queryClient = useQueryClient();
  return useMutation<
    TeachersDayConfig,
    AdminQueryError,
    SetTeachersDayRequest
  >({
    mutationFn: (payload) => unwrap(setTeachersDayConfig(payload)),
    onSuccess: (result) => {
      queryClient.setQueryData<TeachersDayConfig>(
        teachersDayConfigKeys.teachersDay(),
        result,
      );
    },
    ...PRIVILEGED_WRITE,
  });
}
