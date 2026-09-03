/**
 * `/config` — §11.2: *"What differs from the deployed config?"*
 *
 * **Read-only at every role in this slice**, and read-only in a stronger sense than "the
 * write button is behind a permission": there is nothing to write to. `AdminSettings` is
 * built inside the lifespan and frozen, so "effective configuration" here means "what the
 * process booted with", full stop. The Phase 7 editor writes the *bot's* `Settings` through
 * an override layer and is a different endpoint.
 *
 * That is also why the dominant signal — §11.2's "active override count +
 * restart-required-pending count" — reads **0 and 0 with the reason attached** rather than
 * being quietly dropped. A screen that omits the number an operator came to check leaves
 * them wondering whether it is zero or missing; a screen that prints 0 and says why there
 * can be no other answer yet has actually answered them. When Phase 7 lands, the tiles get
 * real denominators and nothing else about this screen moves.
 *
 * All four §11.2 tiers are on the page. `live` and `after-fix` are unreachable from this
 * endpoint's data — every field it returns is an `HBD_ADMIN_*` variable read at boot — so
 * they appear where they are true: on the bot's fields in `ABSENT_RUNTIME_FIELDS`, which
 * exist to catch the operator who followed the threshold link from `/generations/names`.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import { getConfig, unwrapAsync } from "@/api";
import { StatTile } from "@/components/data";
import { ConfigField, type ConfigTier } from "@/components/domain";
import { PageHeader } from "@/components/layout";
import { AsyncBoundary, Skeleton } from "@/components/util";
import { NO_POLLING, formatInteger, pollWhileVisible, queryKeys } from "@/lib";

import { ABSENT_RUNTIME_FIELDS, configGroups, type ConfigFieldModel } from "./configFields";

/** §11.2's four tiers, in the order the plan lists them. */
const TIER_LEGEND: readonly { tier: ConfigTier; meaning: string }[] = [
  { tier: "live", meaning: "on the live-editable allowlist — takes hold on refresh or next order" },
  { tier: "after-fix", meaning: "editable only once its named fix lands (§8.3 Tier 2)" },
  { tier: "read-only", meaning: "restart only — an environment change and a redeploy" },
  { tier: "secret-absent", meaning: "never returned at any role, revealed or not" },
];

export function ConfigScreen(): ReactElement {
  const config = useQuery({
    queryKey: queryKeys.config.detail(),
    queryFn: ({ signal }) => unwrapAsync(getConfig({ signal })),
    refetchInterval: pollWhileVisible(NO_POLLING),
  });

  const groups = useMemo(
    () => (config.data === undefined ? [] : configGroups(config.data)),
    [config.data],
  );

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Config"
        description="What differs from the deployed config?"
        signal={
          <div className="flex flex-wrap items-stretch gap-3" data-testid="config-signal">
            <StatTile
              size="hero"
              label="active overrides"
              value={formatInteger(0)}
              hint="no override layer stands behind this endpoint yet — the editor is Phase 7"
            />
            <StatTile
              label="pending restart"
              value={formatInteger(0)}
              hint="every field here is read once at boot, so nothing can be pending"
            />
          </div>
        }
      />

      <div className="flex flex-col gap-8 px-gutter pb-gutter">
        <section aria-label="tier legend" className="flex flex-col gap-3">
          <h2 className="type-h3 text-ink">How to read a field</h2>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="config-tier-legend">
            {TIER_LEGEND.map((entry) => (
              <div key={entry.tier} className="flex flex-col gap-1">
                <ConfigField name={entry.tier} tier={entry.tier} value={entry.meaning} />
              </div>
            ))}
          </dl>
        </section>

        <AsyncBoundary
          status={config.status}
          hasData={config.data !== undefined}
          error={config.error}
          onRetry={() => void config.refetch()}
          {...(config.isError ? { dataUpdatedAt: config.dataUpdatedAt } : {})}
          noun="the configuration"
          skeleton={
            <div className="flex flex-col gap-4">
              {Array.from({ length: 4 }, (_unused, index) => (
                <Skeleton key={index} className="h-32 w-full" />
              ))}
            </div>
          }
        >
          <div className="flex flex-col gap-8">
            {groups.map((group) => (
              <section key={group.id} aria-label={group.title} className="flex flex-col gap-3">
                <h2 className="type-h3 text-ink">{group.title}</h2>
                {group.blurb === undefined ? null : (
                  <p className="type-body-sm max-w-prose text-ink-muted">{group.blurb}</p>
                )}
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {group.fields.map((field) => (
                    <Field key={field.name} field={field} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </AsyncBoundary>

        <section aria-label="bot runtime configuration" className="flex flex-col gap-3">
          <h2 className="type-h3 text-ink">The bot&apos;s runtime configuration</h2>
          <p className="type-body-sm max-w-prose text-ink-muted">
            These are the bot&apos;s <span className="type-mono">Settings</span>, not the
            panel&apos;s, and this endpoint does not return them. §8.3 puts them in the live and
            after-a-named-fix tiers; the editor that writes them is Phase 7. Until then a
            change to any of them is an environment change and a redeploy.
          </p>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="config-absent-fields">
            {ABSENT_RUNTIME_FIELDS.map((field) => (
              <Field key={field.name} field={field} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function Field({ field }: { readonly field: ConfigFieldModel }): ReactElement {
  return (
    <ConfigField
      name={field.name}
      tier={field.tier}
      {...(field.value === undefined ? {} : { value: field.value })}
      {...(field.note === undefined ? {} : { note: field.note })}
    />
  );
}

export const Component = ConfigScreen;
