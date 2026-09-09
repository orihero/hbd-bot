import { useI18n } from "@/i18n";

/**
 * What the app looks like for the one round trip `bootstrap()` takes.
 *
 * Deliberately almost nothing: a spinner and a "checking your session…" line would flash for
 * ~50ms on a warm session and read as a failure state on a cold one. A quiet wordmark on the
 * page background is the same colour and shape as what lands next, so the transition is a
 * fill rather than a flicker.
 */
export function PendingShell() {
  const { t } = useI18n();

  return (
    <div className="grid min-h-screen place-items-center bg-bg">
      <span
        aria-hidden
        className="font-wordmark text-2xl tracking-tight text-wordmark opacity-40"
      >
        hbd
      </span>
      <span className="sr-only">{t("common.loadingApp")}</span>
    </div>
  );
}
