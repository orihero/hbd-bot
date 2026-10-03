import { Music } from "lucide-react";
import { useId, useState, type JSX } from "react";

import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import { ToolbarButton } from "@/components/Toolbar";
import {
  EMPTY_REASON,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useCanManageConfig } from "@/lib/rbac";
import type { AdminQueryError } from "@/lib/adminQuery";
import { useMusicProviderConfig, useSetMusicProvider } from "./useMusicProvider";

const PROVIDER_NAMES: Record<string, string> = {
  elevenlabs_music: "ElevenLabs",
  gemini_music: "Gemini",
  fake_music: "Fake Music",
};

export function formatMusicProvider(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

export function MusicProviderSwitch(): JSX.Element {
  const { data: config, isLoading } = useMusicProviderConfig();
  const setProvider = useSetMusicProvider();
  const canManage = useCanManageConfig();

  const [isOpen, setIsOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);
  const selectId = useId();

  const activeProvider = config?.activeProvider ?? "elevenlabs_music";
  const availableProviders = config?.availableProviders ?? ["elevenlabs_music", "gemini_music"];

  const otherProvider = availableProviders.find((p) => p !== activeProvider) ?? activeProvider;
  const currentTarget = selectedProvider ?? otherProvider;

  const body = reasonBodyOf(reason);
  const error: AdminQueryError | null = setProvider.error;

  function handleOpen(): void {
    setSelectedProvider(otherProvider);
    setReason(EMPTY_REASON);
    setProvider.reset();
    setIsOpen(true);
  }

  function handleClose(): void {
    setReason(EMPTY_REASON);
    setSelectedProvider(null);
    setProvider.reset();
    setIsOpen(false);
  }

  return (
    <>
      <div className="flex items-center gap-2">
        <span className="text-[14px] font-medium text-ink-500">Music Provider:</span>
        <Badge tone="accent" icon={<Music className="h-3 w-3" strokeWidth={2} />}>
          {isLoading ? "Loading…" : formatMusicProvider(activeProvider)}
        </Badge>
        {canManage && (
          <ToolbarButton
            variant="secondary"
            onClick={handleOpen}
            ariaLabel="Change music provider"
            className="!h-9 !py-1 !px-3 !text-[14px]"
          >
            Change
          </ToolbarButton>
        )}
      </div>

      {isOpen && (
        <ConfirmDialog
          isOpen={isOpen}
          title="Change Music Provider"
          description="Switch the active music generation provider. Future music generations across the fleet will route to the selected provider immediately without restarting services."
          confirmLabel={`Switch to ${formatMusicProvider(currentTarget)}`}
          pendingLabel="Switching…"
          tone="default"
          isPending={setProvider.isPending}
          isConfirmDisabled={!canSubmitReason(reason) || currentTarget === activeProvider}
          error={
            error === null ? undefined : (
              <ErrorNote
                tone={error.status === 403 ? "denied" : "error"}
                title="Switch failed"
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
            label: "Why (optional, up to 500 characters)",
            hint: "Audit explanation. Free text on a 90-day sweep.",
            value: reason.text,
            isRequired: false,
            onChange: (text) => {
              setReason({ ...reason, text });
            },
          }}
          onConfirm={() => {
            if (body === null) return;
            setProvider.mutate(
              {
                provider: currentTarget,
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
          <div className="mb-4 flex flex-col gap-2">
            <label
              htmlFor={selectId}
              className="text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-label"
            >
              Select provider
            </label>
            <select
              id={selectId}
              value={currentTarget}
              onChange={(e) => setSelectedProvider(e.target.value)}
              disabled={setProvider.isPending}
              className="mt-1 block w-full rounded-field border border-stroke bg-card px-3 py-2 text-[14px] text-ink-900"
            >
              {availableProviders.map((p) => (
                <option key={p} value={p}>
                  {formatMusicProvider(p)} {p === activeProvider ? "(Current)" : ""}
                </option>
              ))}
            </select>
          </div>
          <ReasonFieldset value={reason} onChange={setReason} isDisabled={setProvider.isPending} />
        </ConfirmDialog>
      )}
    </>
  );
}
