import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type JSX } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { setLocale, useI18n } from "@/i18n";

/**
 * The language control, driven the way an operator drives it.
 *
 * These live here rather than in `tests/challenger-m2-*.ts` because those harnesses render
 * through `renderToStaticMarkup`, which cannot open a menu: an SSR pass sees `isOpen === false`
 * and stops. Every assertion below needs a click or a key, so it needs a DOM.
 *
 * The first test is the one that matters most, and it is the one nothing had: switching the
 * locale must repaint a component that is NOT the switcher. `useI18n` spent its whole life
 * failing that silently — it probed a misspelled React internal, concluded it was never inside
 * a render, and handed every caller an unsubscribed snapshot. The catalogues were complete and
 * the console still never changed language.
 */

function Bystander(): JSX.Element {
  const { t } = useI18n();
  return <p data-testid="bystander">{t("common.cancel")}</p>;
}

afterEach(() => {
  setLocale("en");
});

describe("LanguageSwitcher", () => {
  it("repaints a component that is not itself when the locale changes", async () => {
    const user = userEvent.setup();
    render(
      <>
        <LanguageSwitcher />
        <Bystander />
      </>,
    );

    expect(screen.getByTestId("bystander")).toHaveTextContent("Cancel");

    await user.click(screen.getByTestId("language-switcher-trigger"));
    await user.click(screen.getByRole("menuitemradio", { name: "Русский" }));

    await waitFor(() => {
      expect(screen.getByTestId("bystander")).toHaveTextContent("Отмена");
    });
  });

  it("shows the current language on the trigger and no menu until asked", () => {
    setLocale("uz");
    render(<LanguageSwitcher />);

    const trigger = screen.getByTestId("language-switcher-trigger");
    expect(trigger).toHaveAttribute("data-locale", "uz");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("offers all three languages by their own names, with one checked", async () => {
    const user = userEvent.setup();
    setLocale("ru");
    render(<LanguageSwitcher />);

    await user.click(screen.getByTestId("language-switcher-trigger"));

    const items = screen.getAllByRole("menuitemradio");
    expect(items.map((item) => item.getAttribute("data-locale"))).toEqual(["uz", "ru", "en"]);
    expect(items.map((item) => item.textContent)).toEqual(["Oʻzbekcha", "Русский", "English"]);
    expect(items.filter((item) => item.getAttribute("aria-checked") === "true")).toHaveLength(1);
    expect(screen.getByRole("menuitemradio", { name: "Русский" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("selects a language, closes, and reports it to onChange", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    render(
      <LanguageSwitcher
        onChange={(next) => {
          seen.push(next);
        }}
      />,
    );

    await user.click(screen.getByTestId("language-switcher-trigger"));
    await user.click(screen.getByRole("menuitemradio", { name: "Oʻzbekcha" }));

    expect(seen).toEqual(["uz"]);
    expect(useI18n.getState().locale).toBe("uz");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByTestId("language-switcher-trigger")).toHaveAttribute("data-locale", "uz");
  });

  it("opens on ArrowDown, walks with the arrows, and closes on Escape", async () => {
    const user = userEvent.setup();
    setLocale("en");
    render(<LanguageSwitcher />);

    const trigger = screen.getByTestId("language-switcher-trigger");
    trigger.focus();
    await user.keyboard("{ArrowDown}");

    // Focus lands on the language already in use, so Enter is a no-op rather than a surprise.
    expect(screen.getByRole("menuitemradio", { name: "English" })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "Oʻzbekcha" })).toHaveFocus();

    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitemradio", { name: "English" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitemradio", { name: "Oʻzbekcha" })).toHaveFocus();

    await user.keyboard("{End}");
    expect(screen.getByRole("menuitemradio", { name: "English" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("dismisses when a pointer lands outside it", async () => {
    const user = userEvent.setup();
    render(
      <>
        <LanguageSwitcher />
        <button type="button">elsewhere</button>
      </>,
    );

    await user.click(screen.getByTestId("language-switcher-trigger"));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("names itself in the language currently on screen", async () => {
    const user = userEvent.setup();
    setLocale("uz");
    render(<LanguageSwitcher />);

    expect(screen.getByRole("button", { name: "Tilni tanlang" })).toBeInTheDocument();

    await user.click(screen.getByTestId("language-switcher-trigger"));
    expect(screen.getByRole("menu", { name: "Tilni tanlang" })).toBeInTheDocument();
  });

  it("keeps the flags out of the accessibility tree", async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);

    await user.click(screen.getByTestId("language-switcher-trigger"));

    // A screen reader hears a language, never a country: every flag is decoration.
    const flags = document.querySelectorAll("svg");
    expect(flags.length).toBeGreaterThan(0);
    for (const flag of flags) {
      expect(flag).toHaveAttribute("aria-hidden");
    }
  });
});
