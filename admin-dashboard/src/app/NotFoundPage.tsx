import { Link } from "react-router-dom";

import { PATH } from "@/app/paths";
import { useI18n } from "@/i18n";

/** The `*` route. No session claim either way — a bad URL is not an auth outcome. */
export function NotFoundPage() {
  const { t } = useI18n();

  return (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center">
      <div>
        <p className="text-sm font-medium text-ink-500">{t("errors.notFound.title")}</p>
        <Link className="mt-3 inline-block text-sm font-semibold text-accent-deep" to={PATH.dashboard}>
          {t("errors.notFound.backToDashboard")}
        </Link>
      </div>
    </div>
  );
}
