/**
 * The reveal surface, as one import.
 *
 * A screen that shows personal data needs `<MaskedValue>` and nothing else; a screen that
 * reveals a whole brief at once opens `<RevealDialog>` itself. `useReveal` is exported for
 * the second kind, and for the phases that will add reveals of their own — one flow, one
 * step-up form, one place the plaintext lives.
 *
 * The RBAC helpers are re-exported from `@/lib/rbac` because they are the other half of rule
 * 4: whether to draw an affordance at all is decided beside the affordance.
 */

export { MaskedValue, PurgedValue, EMPTY_VALUE, type MaskedValueProps } from "./MaskedValue";
export {
  RevealDialog,
  LONG_REF_WARNING,
  NO_RETENTION_CLOCK_NOTE,
  REASON_REQUIRED_HINT,
  type RevealDialogProps,
} from "./RevealDialog";
export {
  StepUpDialog,
  STEP_UP_ACTION_KEYS,
  type StepUpDialogProps,
} from "./StepUpDialog";
export { DialogShell, Notice, type DialogShellProps, type NoticeTone } from "./DialogShell";
export {
  budgetScopeKey,
  describeRetryAfter,
  revealFailureAdvice,
  useReveal,
  useStepUp,
  REVEAL_IS_AUDITED_NOTE,
  ROLE_REFUSAL_NOTE,
  STEP_UP_CHANGES_NOTHING_NOTE,
  STEP_UP_COSTS_NO_BUDGET_NOTE,
  type RevealFlow,
  type RevealPhase,
  type StepUpFlow,
} from "./useReveal";
export {
  canSubmitReveal,
  describeRevealCost,
  formatRevealedValue,
  orderFields,
  revealCost,
  revealedValuesOf,
  revealFieldsFor,
  revealGroupsFor,
  ATTEMPT_REVEAL_FIELDS,
  BRIEF_REVEAL_FIELDS,
  FREE_REVEAL,
  REVEAL_FIELD_GROUPS,
  REVEAL_FIELD_HINT_KEYS,
  REVEAL_FIELD_LABEL_KEYS,
  REVEAL_FIELD_SPECS,
  REVEAL_REASON_KEYS,
  REVEAL_SHAPE_KEYS,
  USER_PROFILE_REVEAL_FIELDS,
  type RevealCost,
  type RevealedFieldValue,
  type RevealFieldGroup,
  type RevealFieldSpec,
} from "./revealFields";
export {
  canBlockUsers,
  canGrantCredits,
  canReveal,
  hasPermission,
  useCanBlockUsers,
  useCanGrantCredits,
  useCanReveal,
  useRole,
  type AdminRole,
  type Permission,
} from "@/lib/rbac";
