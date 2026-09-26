/**
 * The language control: one flag in the header, three in a menu under it.
 *
 * ## Where it lives, and why it moved
 *
 * It sat in the nav rail's footer — twice, once per layout — which put a preference among the
 * DESTINATIONS. The rail answers "where can I go"; language and palette answer "how do I want
 * this to look", and those two belong together. They are one pair now, at the end of `TopBar`,
 * which is the place that bar's own docstring had been reserving for it all along. The login
 * screen keeps its own copy, because there is no bar on a page nobody has signed into yet.
 *
 * ## A disc that opens, not three discs in a row
 *
 * Three segments of `UZ RU EN` was a control that read as text among icons, and three flags in
 * a row was three round things where the palette toggle is one. A single disc showing the
 * language you are IN, opening onto the three you could be in, is the same weight as the
 * button beside it and says the current state without being read.
 *
 * The cost is one more click to switch, and it is the right trade here: switching language is
 * something an operator does on their first day and then roughly never, while looking at the
 * header happens on every screen.
 *
 * ## The flag is never the accessible name
 *
 * Every control carries the language's own endonym — `Oʻzbekcha`, `Русский`, `English` — as
 * its label, and the drawing is `aria-hidden`. See `LanguageFlag` on why that division is what
 * makes flags defensible at all.
 *
 * ## Menu semantics, not a listbox
 *
 * `menu` + `menuitemradio` + `aria-checked`: picking a language is an ACTION with an immediate
 * effect, not a value staged for a form to submit later. Escape closes and returns focus to
 * the trigger, the arrows walk the items, and a pointer landing anywhere else dismisses it.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FC,
  type JSX,
  type KeyboardEvent,
} from "react";
import { Check } from "lucide-react";

import { LanguageFlag } from "@/components/LanguageFlag";
import { useI18n } from "@/i18n";
import { LOCALES, type SupportedLocale } from "@/i18n/types";
import { cn } from "@/lib/cn";

export type LanguageSwitcherVariant = "bar" | "login";

export interface LanguageOption {
  readonly value: SupportedLocale;
  /** The two-letter code. No longer drawn, and still the id an operator would say out loud. */
  readonly label: string;
  /** The language's own name for itself. This is the accessible name. */
  readonly name: string;
}

/** Supported locales in canonical display order: UZ, RU, EN. */
export const LANGUAGE_OPTIONS: readonly LanguageOption[] = [
  { value: "uz", label: LOCALES.uz.label, name: LOCALES.uz.name },
  { value: "ru", label: LOCALES.ru.label, name: LOCALES.ru.name },
  { value: "en", label: LOCALES.en.label, name: LOCALES.en.name },
] as const;

export interface LanguageSwitcherProps {
  /**
   * Presentation variant:
   * - `bar`: the header's disc, sized to sit beside `TopBar`'s palette button.
   * - `login`: the same control on the login page, where there is no bar to sit in.
   * @default "bar"
   */
  readonly variant?: LanguageSwitcherVariant;

  /** Additional custom CSS classes for the root container. */
  readonly className?: string;

  /**
   * Accessible name for the trigger. Defaults to `common.selectLanguage`, which is itself
   * translated — an operator who cannot read the console cannot read the label on the control
   * that fixes that, so this one is worth the round trip.
   */
  readonly ariaLabel?: string;

  /** Optional callback triggered when the user selects a locale. */
  readonly onChange?: (locale: SupportedLocale) => void;

  /**
   * Render with the menu already open.
   *
   * The uncontrolled-menu affordance every kit has one of, and the only way a renderer with no
   * pointer can see the items at all — `tests/challenger-m2-*.ts` render through
   * `renderToStaticMarkup`, where a closed menu is simply absent from the tree.
   * @default false
   */
  readonly defaultOpen?: boolean;
}

/**
 * Outline-based focus ring from the PlanIQ design system (`Segmented.tsx`, `NavRail.tsx`).
 * `accent-deep` because `accent` lacks contrast on light paper.
 */
const FOCUS_RING =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep";

export const LanguageSwitcher: FC<LanguageSwitcherProps> = ({
  variant = "bar",
  className,
  ariaLabel,
  onChange,
  defaultOpen = false,
}: LanguageSwitcherProps): JSX.Element => {
  const { t, locale, setLocale } = useI18n();

  const [isOpen, setIsOpen] = useState(defaultOpen);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const activeIndex = LANGUAGE_OPTIONS.findIndex((option) => option.value === locale);
  const label = ariaLabel ?? t("common.selectLanguage");

  const close = useCallback((returnFocus: boolean) => {
    setIsOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  const handleSelect = useCallback(
    (nextLocale: SupportedLocale) => {
      setLocale(nextLocale);
      onChange?.(nextLocale);
      close(true);
    },
    [setLocale, onChange, close],
  );

  /* A pointer landing outside dismisses. `pointerdown` rather than `click` so the menu is gone
     before whatever was clicked reacts — otherwise the first click outside is spent closing. */
  useEffect(() => {
    if (!isOpen) return undefined;

    const onPointerDown = (event: PointerEvent) => {
      const root = rootRef.current;
      if (root !== null && event.target instanceof Node && !root.contains(event.target)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [isOpen]);

  /* Opening moves focus onto the language you are already in, so Enter is a no-op rather than
     a surprise, and one arrow press is always the nearest alternative. */
  useEffect(() => {
    if (!isOpen) return;
    const index = activeIndex === -1 ? 0 : activeIndex;
    itemRefs.current[index]?.focus();
  }, [isOpen, activeIndex]);

  const moveFocus = useCallback((from: number, delta: number) => {
    const count = LANGUAGE_OPTIONS.length;
    const next = (from + delta + count) % count;
    itemRefs.current[next]?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Escape") {
        if (!isOpen) return;
        event.preventDefault();
        close(true);
        return;
      }

      if (!isOpen) {
        // The two keys that open a menu from its trigger, per the ARIA menu-button pattern.
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          setIsOpen(true);
        }
        return;
      }

      const focusedIndex = itemRefs.current.findIndex((item) => item === document.activeElement);
      if (focusedIndex === -1) return;

      switch (event.key) {
        case "ArrowDown":
        case "ArrowRight":
          event.preventDefault();
          moveFocus(focusedIndex, 1);
          break;
        case "ArrowUp":
        case "ArrowLeft":
          event.preventDefault();
          moveFocus(focusedIndex, -1);
          break;
        case "Home":
          event.preventDefault();
          itemRefs.current[0]?.focus();
          break;
        case "End":
          event.preventDefault();
          itemRefs.current[LANGUAGE_OPTIONS.length - 1]?.focus();
          break;
        case "Tab":
          // Tabbing out is a dismissal, and the browser's own focus move is the right one.
          setIsOpen(false);
          break;
        default:
          break;
      }
    },
    [isOpen, close, moveFocus],
  );

  const current = LANGUAGE_OPTIONS[activeIndex === -1 ? 2 : activeIndex];

  return (
    <div
      ref={rootRef}
      onKeyDown={handleKeyDown}
      className={cn("relative inline-flex shrink-0", className)}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={label}
        title={`${label}: ${current?.name ?? ""}`}
        data-locale={current?.value}
        data-testid="language-switcher-trigger"
        onClick={() => {
          setIsOpen((open) => !open);
        }}
        className={cn(
          "grid h-9 w-9 shrink-0 cursor-pointer place-items-center rounded-full",
          "border-0 bg-transparent p-0 text-ink-500 transition",
          "hover:bg-row-hover hover:text-ink-900",
          isOpen && "bg-row-hover text-ink-900",
          /* In the bar the disc sits on a card and needs no ground of its own. On the login
             page there is nothing behind it, and a bare flag floating in the corner reads as
             a decoration rather than a control. */
          variant === "login" && "border border-stroke bg-card shadow-sm hover:bg-card",
          FOCUS_RING,
        )}
      >
        <LanguageFlag locale={current?.value ?? "en"} size={20} className="block" />
      </button>

      {isOpen ? (
        <div
          role="menu"
          aria-label={label}
          data-testid="language-switcher-menu"
          /* Right-aligned: this control sits at the end of a right-aligned bar and at the
             top-right of the login page, so a left-aligned menu would hang off the viewport on
             a narrow screen. `z-30` clears `TopBar`'s own `z-20`. */
          className={cn(
            "absolute right-0 top-full z-30 mt-2 min-w-[172px] overflow-hidden",
            "rounded-card border border-stroke bg-card p-1 shadow-lg",
            variant === "login" && "shadow-xl",
          )}
        >
          {LANGUAGE_OPTIONS.map((option, index) => {
            const isChecked = option.value === locale;

            return (
              <button
                key={option.value}
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                type="button"
                role="menuitemradio"
                aria-checked={isChecked}
                data-locale={option.value}
                onClick={() => {
                  handleSelect(option.value);
                }}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-2.5 rounded-button px-2 py-1.5",
                  "border-0 bg-transparent text-left text-[13px] leading-5 transition-colors",
                  FOCUS_RING,
                  isChecked
                    ? "font-semibold text-ink-900"
                    : "font-medium text-ink-500 hover:bg-row-hover hover:text-ink-900",
                )}
              >
                <LanguageFlag locale={option.value} size={18} className="block shrink-0" />
                <span className="min-w-0 flex-1 truncate">{option.name}</span>
                {isChecked ? (
                  <Check
                    className="h-3.5 w-3.5 shrink-0 text-accent-deep"
                    strokeWidth={2.5}
                    aria-hidden
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};

LanguageSwitcher.displayName = "LanguageSwitcher";
