import { useRouteError } from "react-router-dom";

import { useI18n } from "@/i18n";

/**
 * The router's `errorElement`. Without one, React Router paints its own fallback: the raw
 * message and a component stack, on a white page. The API client goes to real trouble to
 * render only server-redacted text, and a render-time throw must not be the hole that puts
 * internals on an operator's screen. The real error goes to the console instead.
 */
export function RouteErrorPage() {
  const { t } = useI18n();
  const error = useRouteError();
  console.error("Unhandled render error", error);

  return (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center">
      <div>
        <p className="text-sm font-medium text-ink-500">{t("errors.routeError.title")}</p>
        <button
          type="button"
          onClick={() => {
            window.location.reload();
          }}
          className="mt-3 rounded-field bg-accent px-4 py-2 text-sm font-semibold text-on-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-deep focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
        >
          {t("errors.routeError.reload")}
        </button>
      </div>
    </div>
  );
}
