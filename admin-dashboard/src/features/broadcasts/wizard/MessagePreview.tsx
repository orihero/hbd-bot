/**
 * The message as the recipient will read it — drawn from a parse, never from a string.
 *
 * The body is operator-authored text that has been through a form and will be read back out of a
 * database, so the panel that shows it must not be the thing that decides what its angle brackets
 * mean. {@link scanBody} produces a tree of allowlisted tags with an already-validated `href`, and
 * this file maps that tree onto React elements. There is no `dangerouslySetInnerHTML` anywhere in
 * it, and there must never be one: the difference between "a preview of the message" and "a
 * rendering of whatever the string turns out to be" is exactly this indirection.
 *
 * **A body that does not parse gets no preview.** It gets the refusal instead, beside the editor,
 * because a half-rendered message would be a picture of something nobody is going to receive.
 *
 * **The image is a placeholder, not the image.** `mediaStorageKey` names a file in our own object
 * store; there is no route that serves it to this panel and `mediaFileId` is worker-owned and
 * never published. So the preview states that an image is attached and which key it is, and the
 * caption ceiling underneath (1 024, not 4 096) is the part that actually changes what can be
 * sent.
 */

import type { JSX, ReactNode } from "react";

import type { Language } from "@/api/broadcasts";
import { useI18n } from "@/i18n";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

import { scanBody, type BodyNode, type BodyTagNode } from "./bodyMarkup";
import type { BodyDraft } from "./wizardState";

export interface MessagePreviewProps {
  readonly body: BodyDraft;
  readonly language: Language;
}

export function MessagePreview({ body, language }: MessagePreviewProps): JSX.Element {
  const { t } = useI18n();
  const scan = scanBody(body.text);
  const mediaKey = body.mediaStorageKey.trim();
  const buttonLabel = body.buttonLabel.trim();
  const buttonUrl = body.buttonUrl.trim();

  return (
    <div
      className="flex flex-col gap-2"
      role="group"
      aria-label={t("broadcasts.wizard.message.previewAria", {
        language: t(LANGUAGE_LABEL_KEY[language]),
      })}
    >
      <div className="flex flex-col gap-2 rounded-panel border border-stroke bg-bg p-3">
        {mediaKey === "" ? null : (
          <p className="m-0 rounded-field border border-dashed border-stroke px-3 py-4 text-center text-[12px] text-ink-400">
            {t("broadcasts.wizard.message.previewImage", { key: mediaKey })}
          </p>
        )}

        {body.text === "" ? (
          <p className="m-0 text-[13px] italic text-ink-400">
            {t("broadcasts.wizard.message.previewEmpty")}
          </p>
        ) : scan.ok ? (
          <div className="m-0 whitespace-pre-wrap break-words text-[14px] leading-5 text-ink-900">
            {renderNodes(scan.nodes, t("broadcasts.wizard.message.previewSpoiler"))}
          </div>
        ) : (
          <p className="m-0 text-[13px] text-required-deep">
            {t("broadcasts.wizard.message.previewUnparsed")}
          </p>
        )}

        {buttonLabel === "" || buttonUrl === "" ? null : (
          <p
            className="m-0 rounded-field border border-accent-deep bg-accent-12 px-3 py-2 text-center text-[13px] font-semibold text-accent-deep"
            title={buttonUrl}
          >
            {buttonLabel}
          </p>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The tree                                                                    */
/* -------------------------------------------------------------------------- */

function renderNodes(nodes: readonly BodyNode[], spoilerTitle: string): ReactNode {
  return nodes.map((node, index) =>
    /* The index IS the identity here: the tree is rebuilt from the text on every keystroke and
       nothing in it is stateful, so there is no node to keep across a re-parse. */
    node.kind === "text" ? (
      <span key={index}>{node.text}</span>
    ) : (
      <TagNode key={index} node={node} spoilerTitle={spoilerTitle} />
    ),
  );
}

/**
 * One allowlisted tag.
 *
 * A spoiler is drawn as marked text with the explanation on its `title` rather than as hidden
 * text an operator has to hover to read: this is a proof-read of a message, and hiding half of it
 * behind a gesture would be a preview that shows less than the editor above it.
 */
function TagNode({
  node,
  spoilerTitle,
}: {
  readonly node: BodyTagNode;
  readonly spoilerTitle: string;
}): JSX.Element {
  const children = renderNodes(node.children, spoilerTitle);

  switch (node.tag) {
    case "b":
    case "strong":
      return <strong className="font-semibold">{children}</strong>;
    case "i":
    case "em":
      return <em className="italic">{children}</em>;
    case "u":
    case "ins":
      return <u>{children}</u>;
    case "s":
    case "strike":
    case "del":
      return <s>{children}</s>;
    case "code":
      return <code className="rounded bg-card px-1 font-mono text-[13px]">{children}</code>;
    case "pre":
      return (
        <span className="my-1 block whitespace-pre-wrap rounded bg-card p-2 font-mono text-[13px]">
          {children}
        </span>
      );
    case "tg-spoiler":
      return (
        <span
          title={spoilerTitle}
          className="rounded bg-ink-300/30 px-1 underline decoration-dotted"
        >
          {children}
        </span>
      );
    case "blockquote":
      return (
        <span className="my-1 block border-l-2 border-accent-deep pl-2 text-ink-800">
          {children}
        </span>
      );
    case "a":
      return (
        /* The URL passed `isTelegramButtonUrl` in the scan: absolute, http(s), a real host, no
           userinfo. `rel` is belt and braces on top of that. */
        <a
          href={node.href ?? undefined}
          target="_blank"
          rel="noreferrer noopener nofollow"
          className="text-accent-deep underline"
        >
          {children}
        </a>
      );
  }
}
