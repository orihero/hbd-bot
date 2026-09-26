import { BrandMark } from "@/components/icons";
import { useI18n } from "@/i18n";

/**
 * The design's right-hand white panel (OpenPencil 0:2969): 26px radius, a 72px mark, a
 * 32/600 headline and a 16/400 body, all centred in a 544-wide column inset 60/116.
 *
 * Two departures from the kit, both forced. The copy is rewritten — the artboard sells a
 * task manager and this is an internal console — but every type size, weight, leading and
 * tracking below is the design's. And the kit's 551x428 product screenshot beneath the text
 * is a raster of that other product, so it is dropped rather than faked.
 *
 * Hidden below lg: at that width the panel is decoration competing with the form for the
 * whole viewport.
 */
export function ConsolePanel() {
  const { t } = useI18n();

  return (
    <aside className="hidden rounded-panel bg-card px-[60px] pt-[116px] lg:block">
      <div className="mx-auto flex max-w-[544px] flex-col items-center gap-16">
        <BrandMark className="h-[72px] w-[72px]" />
        <div className="flex flex-col gap-[15px]">
          <h2 className="text-center text-[32px] font-semibold leading-[43.712px] tracking-[-0.96px] text-ink-800">
            {t("auth.console.heroTitle")}
          </h2>
          <p className="text-center text-[16px] leading-6 tracking-[-0.32px] text-ink-800">
            {t("auth.console.heroDescription")}
          </p>
        </div>
      </div>
    </aside>
  );
}
