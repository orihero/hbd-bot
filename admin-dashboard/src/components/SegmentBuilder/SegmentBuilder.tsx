/**
 * The audience editor: a tree of AND/OR/NONE groups over the fields the server publishes.
 *
 * Deliberately state-free. The `value`/`onChange` pair is the whole contract, so the URL owns
 * it on the Users screen and the wizard owns it in a campaign, and the two are provably the
 * same document — the same bytes travel in `?segment=` and in the campaign body, which is what
 * lets an operator open the audience they approved and see the rows in it.
 *
 * ## Four things this component refuses to leave ambiguous
 *
 * **AND/OR is read, not inferred.** Every group states its own semantics in a sentence —
 * "Accounts matching ALL of:" — above the toggle that changes it. Mis-reading the connective
 * is the top failure mode of every filter builder ever shipped, and indentation alone does not
 * say it: nesting here is a bordered card with its own heading and its own accent stripe, so
 * the shape of the boolean survives a glance.
 *
 * **An empty segment is everyone.** The root may legally carry no rules, and that is not a
 * neutral state — it is the whole database. It is said out loud, in the builder, rather than
 * inferred from a blank panel.
 *
 * **A limit is named before the round trip.** `maxRules`, `maxDepth`, `maxValueMembers` and
 * `maxAggregateRules` arrive on the registry and are checked on every edit
 * (`segmentValidation.ts`), each breach pointing at the rule that caused it. The server's 422
 * names a parameter and a bound and cannot name a row; by the time it arrives the audience
 * count is blank and the operator is looking at a list of forty fields.
 *
 * **A sort offers only what the server will sort on.** `SORT_KEYS` is a strict subset of the
 * registry — `last_activity_at` is filterable and deliberately NOT sortable, because a sort
 * publishes a total order over identified accounts — so the key list is `sortable` and nothing
 * else. Offering a key and then failing on it teaches an operator that the panel is unreliable
 * about a refusal that is actually deliberate.
 *
 * ## What it does not do
 *
 * It does not fetch. `useSegmentFields.ts` holds the two reads, and the audience count is
 * passed in through {@link SegmentBuilderProps.preview} — because the count belongs to the
 * screen that gates on it (the wizard blocks on `reachable`; the Users screen just shows it),
 * and a component that fetched its own would fetch twice on a page that shows it twice.
 */

import { useEffect, useMemo, useRef, useState, type JSX, type ReactNode } from "react";
import { Plus, Trash2 } from "lucide-react";

import type { SegmentFieldView, SegmentLimitsView } from "@/api/segments";
import { Segmented } from "@/components/Segmented";
import { cn } from "@/lib/cn";
import {
  MATCH_MODE_VALUES,
  countRules,
  isSegmentGroup,
  isSegmentRule,
  isSegmentEmpty,
  segmentDepth,
  type MatchMode,
  type Segment,
  type SegmentNode,
  type SegmentSort,
  type SortDirection,
} from "@/lib/segmentCodec";

import { RuleRow } from "./RuleRow";
import {
  fieldLabel,
  matchHeading,
  matchLabel,
  useTranslate,
  type Translate,
} from "./segmentLabels";
import {
  appendAt,
  canNestAt,
  groupForField,
  pathKey,
  removeAt,
  replaceAt,
  ruleForField,
  setMatchAt,
  withSort,
  type SegmentPath,
} from "./segmentTree";
import {
  formatSegmentIssue,
  issuesAt,
  segmentIssues,
  type SegmentIssue,
} from "./segmentValidation";
import { CONTROL_HINT_CLASS, CONTROL_LABEL_CLASS, FIELD_CLASS } from "./valueEditors";

export interface SegmentBuilderProps {
  readonly value: Segment;
  readonly onChange: (next: Segment) => void;
  /** `GET /api/segments/fields` — the ONLY source of what may be filtered on. */
  readonly fields: readonly SegmentFieldView[];
  readonly limits: SegmentLimitsView;
  /** `SegmentFieldsView.version`, so a bundle that speaks an older shape can say so. */
  readonly version?: number | undefined;
  /** Users screen: `true`. Wizard: `false` — a campaign's order is the sender's, not the operator's. */
  readonly showSort?: boolean | undefined;
  /** Names the region for assistive tech. Defaults to the catalogue's own phrase. */
  readonly label?: string | undefined;
  /** A frozen audience, rendered read-only — the campaign detail screen's mode. */
  readonly disabled?: boolean | undefined;
  /** States that the audience is fixed at creation. The wizard passes `true`; a list does not. */
  readonly showFreezeNote?: boolean | undefined;
  /** The live audience count, owned by the screen that gates on it. */
  readonly preview?: ReactNode;
  readonly className?: string | undefined;
}

export function SegmentBuilder({
  value,
  onChange,
  fields,
  limits,
  version,
  showSort = false,
  label,
  disabled = false,
  showFreezeNote = false,
  preview,
  className,
}: SegmentBuilderProps): JSX.Element {
  const t = useTranslate();

  const fieldIndex = useMemo(
    () => new Map(fields.map((field) => [field.key, field])),
    [fields],
  );
  const issues = useMemo(
    () =>
      segmentIssues(value, {
        fields: fieldIndex,
        limits,
        ...(version === undefined ? {} : { version }),
      }),
    [value, fieldIndex, limits, version],
  );
  const documentIssues = useMemo(() => issuesAt(issues, []), [issues]);

  /** The rule a keystroke should land on next, and the Add button focus should fall back to. */
  const [focusRuleKey, setFocusRuleKey] = useState<string | null>(null);
  const [focusAddKey, setFocusAddKey] = useState<string | null>(null);

  const ruleCount = countRules(value);
  const depth = segmentDepth(value);
  const isFull = ruleCount >= limits.maxRules;

  /**
   * The field a brand-new rule opens on.
   *
   * The cheapest usable one the registry offers — available here, and NOT a correlated
   * subquery — rather than simply the first: a placeholder rule should not spend one of the
   * six `maxAggregateRules` slots before the operator has chosen anything, and a plain column
   * with a no-operand operator makes the new row valid on arrival instead of greeting them
   * with "this needs a value". Which key that is stays the registry's decision, not this
   * file's.
   */
  const seedField =
    fields.find((field) => field.isAvailable && !field.isAggregate) ??
    fields.find((field) => field.isAvailable) ??
    fields[0] ??
    null;

  function commit(next: Segment, focus?: { readonly rule?: string; readonly add?: string }): void {
    setFocusRuleKey(focus?.rule ?? null);
    setFocusAddKey(focus?.add ?? null);
    onChange(next);
  }

  function addRule(groupPath: SegmentPath): void {
    if (seedField === null || isFull) return;
    const index = childrenAt(value, groupPath).length;
    commit(appendAt(value, groupPath, ruleForField(seedField)), {
      rule: pathKey([...groupPath, index]),
    });
  }

  function addGroup(groupPath: SegmentPath): void {
    if (seedField === null || isFull) return;
    const index = childrenAt(value, groupPath).length;
    // The keyboard lands on the new group's first rule, which is the only thing in it.
    commit(appendAt(value, groupPath, groupForField(seedField)), {
      rule: pathKey([...groupPath, index, 0]),
    });
  }

  return (
    <section
      aria-label={label ?? t("segments.builderLabel")}
      className={cn("flex flex-col gap-3", className)}
    >
      <header className="flex flex-col gap-1">
        <h3 className="m-0 text-[16px] font-semibold leading-[21.856px] tracking-[-0.32px] text-ink-900">
          {t("segments.title")}
        </h3>
        <p className={CONTROL_HINT_CLASS}>{t("segments.description")}</p>
        <p className={CONTROL_HINT_CLASS}>
          {t("segments.summary", {
            rules: ruleCount,
            maxRules: limits.maxRules,
            depth,
            maxDepth: limits.maxDepth,
          })}
        </p>
        {showFreezeNote ? (
          <p className="m-0 max-w-[62ch] text-[12px] font-semibold leading-[1.35] text-ink-900">
            {t("segments.frozenNote")}
          </p>
        ) : null}
        {disabled ? <p className={CONTROL_HINT_CLASS}>{t("segments.readOnlyNote")}</p> : null}
      </header>

      <GroupCard
        path={[]}
        match={value.match}
        nodes={value.rules}
        segment={value}
        fields={fields}
        fieldIndex={fieldIndex}
        limits={limits}
        issues={issues}
        disabled={disabled}
        isFull={isFull}
        t={t}
        focusRuleKey={focusRuleKey}
        focusAddKey={focusAddKey}
        onAddRule={addRule}
        onAddGroup={addGroup}
        onCommit={commit}
      />

      {isSegmentEmpty(value) ? (
        <p role="status" className="m-0 max-w-[62ch] text-[12px] leading-[1.35] text-ink-900">
          <span className="font-semibold">{t("segments.everyone")}</span>{" "}
          {t("segments.everyoneWarning")}
        </p>
      ) : null}

      {preview}

      {showSort ? (
        <SortControl
          value={value}
          fields={fields}
          fieldIndex={fieldIndex}
          disabled={disabled}
          t={t}
          onChange={(sort) => {
            commit(withSort(value, sort));
          }}
        />
      ) : null}

      {documentIssues.length === 0 ? null : (
        <div
          role="alert"
          className="flex flex-col gap-1 rounded-card bg-required-24 px-3 py-2 text-required-deep"
        >
          <p className="m-0 text-[12px] font-semibold leading-[1.35]">
            {t("segments.issues.heading")}
          </p>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {documentIssues.map((issue) => (
              <li key={issue.code} className="m-0 text-[11px] leading-[1.35]">
                {formatSegmentIssue(t, issue)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* One group                                                                   */
/* -------------------------------------------------------------------------- */

interface GroupCardProps {
  readonly path: SegmentPath;
  readonly match: MatchMode;
  readonly nodes: readonly SegmentNode[];
  readonly segment: Segment;
  readonly fields: readonly SegmentFieldView[];
  readonly fieldIndex: ReadonlyMap<string, SegmentFieldView>;
  readonly limits: SegmentLimitsView;
  readonly issues: readonly SegmentIssue[];
  readonly disabled: boolean;
  readonly isFull: boolean;
  readonly t: Translate;
  readonly focusRuleKey: string | null;
  readonly focusAddKey: string | null;
  readonly onAddRule: (path: SegmentPath) => void;
  readonly onAddGroup: (path: SegmentPath) => void;
  readonly onCommit: (
    next: Segment,
    focus?: { readonly rule?: string; readonly add?: string },
  ) => void;
}

/**
 * The nesting made legible.
 *
 * Depth is carried by three things at once — a heading sentence, an accent stripe down the
 * left edge, and a ground that steps from card to page — because indentation alone is a
 * relationship a reader has to reconstruct, and the whole point of this control is that the
 * boolean can be checked at a glance by somebody about to authorise a send against it.
 */
function GroupCard(props: GroupCardProps): JSX.Element {
  const {
    path,
    match,
    nodes,
    segment,
    fields,
    fieldIndex,
    limits,
    issues,
    disabled,
    isFull,
    t,
    focusRuleKey,
    focusAddKey,
    onAddRule,
    onAddGroup,
    onCommit,
  } = props;

  const isRoot = path.length === 0;
  const canNest = canNestAt(path, limits);
  const groupIssues = issuesAt(issues, path);

  return (
    <div
      role="group"
      aria-label={t("segments.groupLabel", { mode: matchLabel(t, match) })}
      className={cn(
        "flex flex-col gap-3 rounded-card px-3 py-3",
        isRoot
          ? "border border-stroke bg-card"
          : "border border-stroke border-l-4 border-l-accent-deep bg-bg",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="m-0 text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-900">
          {matchHeading(t, match)}
        </p>
        <div className="flex items-center gap-2">
          <Segmented<MatchMode>
            ariaLabel={t("segments.matchLabel")}
            value={match}
            options={MATCH_MODE_VALUES.map((mode) => ({
              value: mode,
              label: matchLabel(t, mode),
            }))}
            onChange={(mode) => {
              if (disabled) return;
              onCommit(setMatchAt(segment, path, mode));
            }}
          />
          {isRoot ? null : (
            <button
              type="button"
              disabled={disabled}
              aria-label={t("segments.removeGroup")}
              onClick={() => {
                onCommit(removeAt(segment, path), { add: pathKey(path.slice(0, -1)) });
              }}
              className={cn(
                "flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center",
                "rounded-field border border-stroke bg-card text-ink-500",
                "transition-colors hover:bg-bg hover:text-ink-900",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
                "disabled:cursor-not-allowed disabled:text-ink-300",
              )}
            >
              <Trash2 className="h-4 w-4" strokeWidth={1.75} aria-hidden />
            </button>
          )}
        </div>
      </div>

      {groupIssues.length === 0 ? null : (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {groupIssues.map((issue) => (
            <li
              key={issue.code}
              className="m-0 text-[11px] font-semibold leading-[1.35] text-required-deep"
            >
              {formatSegmentIssue(t, issue)}
            </li>
          ))}
        </ul>
      )}

      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {nodes.map((node, index) => {
          const here = [...path, index];
          const key = pathKey(here);
          return (
            <li key={key} className="m-0">
              {isSegmentRule(node) ? (
                <RuleRow
                  rule={node}
                  path={here}
                  index={index + 1}
                  fields={fields}
                  fieldIndex={fieldIndex}
                  limits={limits}
                  issues={issuesAt(issues, here)}
                  disabled={disabled}
                  autoFocus={focusRuleKey === key}
                  t={t}
                  onChange={(next) => {
                    onCommit(replaceAt(segment, here, next));
                  }}
                  onRemove={() => {
                    onCommit(removeAt(segment, here), { add: pathKey(path) });
                  }}
                />
              ) : null}
              {isSegmentGroup(node) ? (
                <GroupCard
                  {...props}
                  path={here}
                  match={node.match}
                  nodes={node.rules}
                />
              ) : null}
            </li>
          );
        })}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        <AddButton
          label={t("segments.addRule")}
          disabled={disabled || isFull}
          autoFocus={focusAddKey === pathKey(path)}
          {...(isFull ? { title: t("segments.ruleLimitReached", { maxRules: limits.maxRules }) } : {})}
          onClick={() => {
            onAddRule(path);
          }}
        />
        <AddButton
          label={t("segments.addGroup")}
          disabled={disabled || isFull || !canNest}
          autoFocus={false}
          {...(canNest ? {} : { title: t("segments.depthLimitReached", { maxDepth: limits.maxDepth }) })}
          onClick={() => {
            onAddGroup(path);
          }}
        />
      </div>
    </div>
  );
}

function AddButton({
  label,
  disabled,
  autoFocus,
  title,
  onClick,
}: {
  readonly label: string;
  readonly disabled: boolean;
  readonly autoFocus: boolean;
  readonly title?: string | undefined;
  readonly onClick: () => void;
}): JSX.Element {
  const node = useRef<HTMLButtonElement | null>(null);

  /* Focus lands here after a rule is deleted: the row that held it is gone, and a keyboard
     left on `document.body` has to start the whole panel again to add another. */
  useEffect(() => {
    if (!autoFocus || disabled) return;
    node.current?.focus();
  }, [autoFocus, disabled]);

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      ref={node}
      {...(title === undefined ? {} : { title })}
      className={cn(
        "flex h-9 cursor-pointer items-center gap-[6px] rounded-chip border border-stroke bg-card px-3",
        "text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-900",
        "transition-[background-color,filter] hover:bg-bg",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep",
        "disabled:cursor-not-allowed disabled:text-ink-300",
      )}
    >
      <Plus className="h-3 w-3" strokeWidth={2} aria-hidden />
      {label}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Sorting                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The order the results are read in — over `sortable` keys and no others.
 *
 * An absent sort DROPS the key rather than writing the registry's default into it, so an
 * unfiltered, unsorted document is no `?segment=` at all and the plain list keeps one cache
 * key. The two notes under the control are the two things an operator gets wrong here: a sort
 * is not a filter, and an aggregate sort is what makes the exact total refuse to run beside it.
 */
function SortControl({
  value,
  fields,
  fieldIndex,
  disabled,
  t,
  onChange,
}: {
  readonly value: Segment;
  readonly fields: readonly SegmentFieldView[];
  readonly fieldIndex: ReadonlyMap<string, SegmentFieldView>;
  readonly disabled: boolean;
  readonly t: Translate;
  readonly onChange: (sort: SegmentSort | null) => void;
}): JSX.Element {
  const sortable = fields.filter((field) => field.sortable);
  const current = value.sort ?? null;
  const chosen = current === null ? null : (fieldIndex.get(current.key) ?? null);

  return (
    <div className="flex flex-col gap-2 rounded-card border border-stroke bg-card px-3 py-3">
      <p className="m-0 text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-ink-900">
        {t("segments.sort.label")}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-col gap-1">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.sort.key")}</span>
          <select
            className={cn(FIELD_CLASS, "min-w-[12rem] pr-2")}
            disabled={disabled}
            value={current?.key ?? ""}
            onChange={(event) => {
              const key = event.target.value;
              if (key === "") {
                onChange(null);
                return;
              }
              onChange({ key, dir: current?.dir ?? "desc" });
            }}
          >
            <option value="">{t("segments.sort.registryDefault")}</option>
            {sortable.map((field) => (
              <option key={field.key} value={field.key}>
                {fieldLabel(t, field.key)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1">
          <span className={CONTROL_LABEL_CLASS}>{t("segments.sort.direction")}</span>
          <select
            className={cn(FIELD_CLASS, "min-w-[9rem] pr-2")}
            disabled={disabled || current === null}
            value={current?.dir ?? "desc"}
            onChange={(event) => {
              if (current === null) return;
              onChange({ key: current.key, dir: event.target.value as SortDirection });
            }}
          >
            <option value="desc">{t("segments.sort.desc")}</option>
            <option value="asc">{t("segments.sort.asc")}</option>
          </select>
        </label>
      </div>
      <p className={CONTROL_HINT_CLASS}>{t("segments.sort.narrowsNothing")}</p>
      {chosen?.isAggregate === true ? (
        <>
          <p className={CONTROL_HINT_CLASS}>{t("segments.sort.aggregateCost")}</p>
          <p className={CONTROL_HINT_CLASS}>{t("segments.sort.nullsSortLow")}</p>
        </>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* internals                                                                   */
/* -------------------------------------------------------------------------- */

function childrenAt(segment: Segment, path: SegmentPath): readonly SegmentNode[] {
  let nodes: readonly SegmentNode[] = segment.rules;
  for (const index of path) {
    const next = nodes[index];
    if (next === undefined || !isSegmentGroup(next)) return [];
    nodes = next.rules;
  }
  return nodes;
}
