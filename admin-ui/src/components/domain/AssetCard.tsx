/**
 * `<AssetCard>` — one stored artefact, as metadata.
 *
 * Three deliberate absences, each of which would be a wrong claim rather than a missing
 * nicety:
 *
 * 1. **No size.** `sizeBytes` is on the wire and is ALWAYS 0 today, which is why §11.2 says
 *    storage size is not shown on `/assets`. "0 B" for a four-megabyte song is a lie the
 *    operator has no way to detect.
 * 2. **No player ON THE CARD.** §12.3: audio assets are metadata only, "no player until
 *    revealed — a greeting says the name aloud, so playing *is* a reveal". Phase 2 gives the
 *    reveal a route, so the card now carries a play BUTTON — but never an `<audio>` element.
 *    The element lives once, at the shell, in `PlayerBar`; one per card would cut the song
 *    off mid-bar on every navigation (§11.1). The button hands a `PlayerTrack` to
 *    `usePlayerStore` and that is the whole of its involvement.
 *
 *    The button is HIDDEN, not disabled, for a role with no reveal cell (§11.4, §12.2: the
 *    row is `—` for VIEWER and `A+S` for SUPPORT and above). The sentence beside it changes
 *    with the role, because an absent control with no explanation is its own support call:
 *    a VIEWER is told the card is metadata only, and everyone else is told that pressing
 *    play is an audited reveal charged against the record budget. Neither is decoration —
 *    the operator is about to spend a unit of a shared hourly ceiling.
 * 3. **No storage key.** What matters is `isStorageKeyRecorded`, and `false` — today's
 *    normal answer — means **the bytes will outlive the row**: the retention sweep can
 *    delete the database record but cannot reach the object, so the audio survives its own
 *    deletion. That is the fact `/assets` exists for, so it is a flagged line, not a
 *    checkbox.
 */

import { Pause, Play } from "lucide-react";
import type { ReactElement } from "react";

import type { AssetWireView } from "@/api";
import { Button, PermissionGate, useHasPermission } from "@/components/util";
import {
  cn,
  EMPTY_VALUE,
  formatDurationS,
  formatInteger,
  humaniseEnum,
  type TimeZoneMode,
} from "@/lib";
import { useIsCurrentTrack, usePlayerStore } from "@/lib/stores";

import { assetTrack, isAudioAsset, isStreamableAsset, PLAYER_COPY } from "./playback";
import { assetRetentionClocks } from "./retention";
import { RetentionClocks } from "./RetentionClocks";

export interface AssetCardProps {
  asset: AssetWireView;
  /** Injected in tests so the expiry countdown is not a function of the wall clock. */
  now?: number | undefined;
  timeZoneMode?: TimeZoneMode | undefined;
  className?: string | undefined;
}

/**
 * §12.3's audio caveat, in the operator's words, for a role that cannot act on it.
 *
 * Kept at its Phase-1 wording and its Phase-1 name: it is what a VIEWER sees, and for a
 * VIEWER the sentence is still exactly true. The role that CAN play sees
 * `PLAYER_COPY.playbackIsAReveal` instead, which says what pressing the button costs.
 */
export const PLAYBACK_IS_A_REVEAL_LABEL = PLAYER_COPY.playbackNotPermitted;

/** §12.2's row for "stream audio or read lyric text": `—` for VIEWER, `A+S` above it. */
const PLAYBACK_PERMISSION = "reveal.media" as const;

/** `isStorageKeyRecorded: false` is not a shrug; it is the durable-orphan warning. */
export const UNRECORDED_STORAGE_KEY_LABEL = "no storage key recorded — bytes will outlive the row";

export function AssetCard({ asset, now, timeZoneMode, className }: AssetCardProps): ReactElement {
  const isAudio = isAudioAsset(asset);
  const canReveal = useHasPermission(PLAYBACK_PERMISSION);
  // Two reasons there may be no button, and each is a different sentence: the role holds no
  // cell (§12.2's `—` for VIEWER), or the stored format is not one this route serves (a 415
  // before a byte moves).
  const isStreamable = isStreamableAsset(asset);
  const hasButton = isAudio && canReveal && isStreamable;
  const playbackNote = hasButton
    ? PLAYER_COPY.playbackIsAReveal
    : isStreamable
      ? PLAYBACK_IS_A_REVEAL_LABEL
      : PLAYER_COPY.unsupported;

  return (
    <article
      data-testid="asset-card"
      data-asset-id={asset.id}
      data-kind={asset.kind}
      className={cn(
        "flex flex-col gap-3 rounded-card bg-surface-card p-card shadow-card",
        "transition-shadow duration-base ease-standard hover:shadow-card-hover",
        className,
      )}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="type-h2 text-ink">
          {humaniseEnum(asset.kind)}
          <span className="type-body-sm num ml-2 text-ink-muted">
            {`#${formatInteger(asset.variantIndex)}`}
          </span>
        </h3>
        <span className="type-mono text-ink-muted" title={asset.mime}>
          {asset.mime}
        </span>
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        <Field label="duration" value={formatDurationS(asset.durationS)} isNumeric />
        <Field
          label="loudness"
          value={
            asset.loudnessLufs === null
              ? EMPTY_VALUE
              : `${asset.loudnessLufs.toFixed(1)} LUFS`
          }
          isNumeric
        />
        <Field label="sha256" value={asset.sha256.slice(0, 12)} isMono />
        <Field
          label="telegram file"
          value={asset.hasTelegramFileId ? "recorded" : "not recorded"}
        />
        {asset.nameCandidateStrategy === null ? null : (
          <Field
            label="name strategy"
            value={
              asset.nameCandidateRank === null
                ? humaniseEnum(asset.nameCandidateStrategy)
                : `${humaniseEnum(asset.nameCandidateStrategy)} · rank ${formatInteger(asset.nameCandidateRank)}`
            }
          />
        )}
        {asset.personaId === null ? null : <Field label="persona" value={asset.personaId} isMono />}
      </dl>

      <RetentionClocks
        clocks={assetRetentionClocks(asset)}
        {...(now === undefined ? {} : { now })}
        {...(timeZoneMode === undefined ? {} : { timeZoneMode })}
      />

      {asset.isStorageKeyRecorded ? null : (
        <p
          data-testid="asset-unrecorded-key"
          className="type-body-sm inline-flex items-baseline gap-1"
          style={{ color: "var(--caution)" }}
        >
          <span aria-hidden="true">⚠</span>
          <span>{UNRECORDED_STORAGE_KEY_LABEL}</span>
        </p>
      )}

      {isAudio ? (
        <div className="flex flex-wrap items-center gap-2">
          {isStreamable ? (
            <PermissionGate permission={PLAYBACK_PERMISSION}>
              <PlayButton asset={asset} />
            </PermissionGate>
          ) : null}
          <p className="type-caption text-ink-muted" data-testid="asset-playback-note">
            {playbackNote}
          </p>
        </div>
      ) : null}
    </article>
  );
}

/**
 * The one control on this card that costs something.
 *
 * It never renders an `<audio>` element: it hands a `PlayerTrack` to the store and the
 * shell's `PlayerBar` does the rest, which is what keeps a song playing while the operator
 * navigates to the order it belongs to (§11.1).
 *
 * When this asset is the loaded track the button becomes Pause, so a grid of takes has one
 * play head rather than five buttons that all say Play while one of them is running. Pausing
 * does not "un-reveal" anything — the reveal happened when the stream was authorised — so
 * this is presentation, not policy.
 */
function PlayButton({ asset }: { readonly asset: AssetWireView }): ReactElement {
  const isCurrent = useIsCurrentTrack(asset.id);
  const isPlaying = usePlayerStore((state) => state.isPlaying);
  const isThisPlaying = isCurrent && isPlaying;
  const what = `${humaniseEnum(asset.kind)} #${formatInteger(asset.variantIndex)}`;

  return (
    <Button
      variant="secondary"
      data-testid="asset-play"
      aria-label={isThisPlaying ? `Pause ${what}` : `Play ${what}`}
      onClick={() => {
        const player = usePlayerStore.getState();
        // Already loaded: this is a transport control, not a second reveal. Sending
        // `requestPlay` again would open another authorisation for a stream the operator is
        // in the middle of listening to.
        if (isCurrent) {
          player.toggle();
          return;
        }
        player.requestPlay(assetTrack(asset));
      }}
    >
      {isThisPlaying ? (
        <Pause aria-hidden="true" className="h-3 w-3" />
      ) : (
        <Play aria-hidden="true" className="h-3 w-3" />
      )}
      {isThisPlaying ? "Pause" : "Play"}
    </Button>
  );
}

function Field({
  label,
  value,
  isNumeric = false,
  isMono = false,
}: {
  label: string;
  value: string;
  isNumeric?: boolean;
  isMono?: boolean;
}): ReactElement {
  return (
    <div className="flex flex-col">
      <dt className="type-caption text-ink-muted">{label}</dt>
      <dd className={cn("type-body-sm text-ink-muted", isNumeric && "num", isMono && "type-mono")}>
        {value}
      </dd>
    </div>
  );
}
