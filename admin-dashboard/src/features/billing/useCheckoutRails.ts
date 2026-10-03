/**
 * The owner's per-rail sale switch (DECISIONS.md D28): one read for every role, one owner-only
 * write.
 *
 * The write's response is the whole view RE-READ by the server after the Redis write, and it is
 * seeded into the cache as-is. The panel therefore draws the switch as STORED, which differs
 * from what was requested exactly when something went wrong — the one case worth showing.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getCheckoutRails,
  setCheckoutRail,
  type CheckoutRailsConfig,
  type SetCheckoutRailRequest,
} from "@/api/config";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  unwrap,
  type AdminQueryError,
} from "@/lib/adminQuery";

export const checkoutRailsKeys = {
  all: ["config"] as const,
  rails: () => ["config", "checkout-rails"] as const,
} as const;

export function useCheckoutRails(): UseQueryResult<CheckoutRailsConfig, AdminQueryError> {
  return useQuery<CheckoutRailsConfig, AdminQueryError>({
    queryKey: checkoutRailsKeys.rails(),
    queryFn: ({ signal }) => unwrap(getCheckoutRails(signal)),
    ...LIST_READ,
  });
}

export function useSetCheckoutRail(): UseMutationResult<
  CheckoutRailsConfig,
  AdminQueryError,
  SetCheckoutRailRequest
> {
  const queryClient = useQueryClient();
  return useMutation<CheckoutRailsConfig, AdminQueryError, SetCheckoutRailRequest>({
    mutationFn: (payload) => unwrap(setCheckoutRail(payload)),
    onSuccess: (result) => {
      queryClient.setQueryData<CheckoutRailsConfig>(checkoutRailsKeys.rails(), result);
    },
    ...PRIVILEGED_WRITE,
  });
}
