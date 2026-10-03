import { GraduationCap } from "lucide-react";
import { useState, type JSX } from "react";

import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import { ToolbarButton } from "@/components/Toolbar";
import { useI18n } from "@/i18n";
import {
  EMPTY_REASON,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useCanManageConfig } from "@/lib/rbac";
import type { AdminQueryError } from "@/lib/adminQuery";
import { useTeachersDayConfig, useSetTeachersDay } from "./useTeachersDay";

export function TeachersDaySwitch(): JSX.Element {
  const { data: config, isLoading } = useTeachersDayConfig();
  const setTeachersDay = useSetTeachersDay();
  const canManage = useCanManageConfig();
  const { t } = useI18n();

  const [isOpen, setIsOpen] = useState(false);
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  const isEnabled = config?.enabled ?? false;
  const discountPercent = config?.discountPercent ?? 30;
  const percent = { percent: discountPercent };

  const nextState = !isEnabled;
  const body = reasonBodyOf(reason);
  const error: AdminQueryError | null = setTeachersDay.error;

  function handleOpen(): void {
    setReason(EMPTY_REASON);
    setTeachersDay.reset();
    setIsOpen(true);
  }

  function handleClose(): void {
    setReason(EMPTY_REASON);
    setTeachersDay.reset();
    setIsOpen(false);
  }

  return (
    <>
      <div className="flex items-center gap-2">
        <span className="text-[14px] font-medium text-ink-500">
          {t("generations.teachersDay.label")}
        </span>
        <Badge
          tone={isEnabled ? "accent" : "neutral"}
          icon={<GraduationCap className="h-3 w-3" strokeWidth={2} />}
        >
          {isLoading
            ? t("generations.teachersDay.loading")
            : isEnabled
              ? t("generations.teachersDay.active", percent)
              : t("generations.teachersDay.off")}
        </Badge>
        {canManage && (
          <ToolbarButton
            variant="secondary"
            onClick={handleOpen}
            ariaLabel={
              isEnabled
                ? t("generations.teachersDay.disableAria")
                : t("generations.teachersDay.enableAria")
            }
            className="!h-9 !py-1 !px-3 !text-[14px]"
          >
            {isEnabled ? t("generations.teachersDay.turnOff") : t("generations.teachersDay.turnOn")}
          </ToolbarButton>
        )}
      </div>

      {isOpen && (
        <ConfirmDialog
          isOpen={isOpen}
          title={
            isEnabled
              ? t("generations.teachersDay.disableTitle")
              : t("generations.teachersDay.enableTitle", percent)
          }
          description={
            isEnabled
              ? t("generations.teachersDay.disableDescription")
              : t("generations.teachersDay.enableDescription", percent)
          }
          confirmLabel={
            isEnabled
              ? t("generations.teachersDay.confirmOff")
              : t("generations.teachersDay.confirmOn")
          }
          pendingLabel={
            isEnabled
              ? t("generations.teachersDay.pendingOff")
              : t("generations.teachersDay.pendingOn")
          }
          tone={isEnabled ? "danger" : "default"}
          isPending={setTeachersDay.isPending}
          isConfirmDisabled={!canSubmitReason(reason)}
          error={
            error === null ? undefined : (
              <ErrorNote
                tone={error.status === 403 ? "denied" : "error"}
                title={t("generations.teachersDay.errorTitle")}
                message={error.message}
                hint={
                  error.correlationId === null
                    ? undefined
                    : `${error.endpoint} · ${error.correlationId}`
                }
                retryable={false}
              />
            )
          }
          reason={{
            label: t("generations.teachersDay.reasonLabel"),
            hint: t("generations.teachersDay.reasonHint"),
            value: reason.text,
            isRequired: false,
            onChange: (text) => {
              setReason({ ...reason, text });
            },
          }}
          onConfirm={() => {
            if (body === null) return;
            setTeachersDay.mutate(
              {
                enabled: nextState,
                reasonCode: body.reasonCode,
                reasonRef: body.reasonRef,
                reasonText: body.reasonText,
              },
              {
                onSuccess: () => {
                  handleClose();
                },
              },
            );
          }}
          onClose={handleClose}
        >
          <div className="mb-4">
            <p className="text-[13px] text-ink-600">
              {nextState
                ? t("generations.teachersDay.enableDetail", percent)
                : t("generations.teachersDay.disableDetail")}
            </p>
          </div>
          <ReasonFieldset value={reason} onChange={setReason} isDisabled={setTeachersDay.isPending} />
        </ConfirmDialog>
      )}
    </>
  );
}
