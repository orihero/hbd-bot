/**
 * The inbound journal's columns, outside the Screen file so that file stays a pure component
 * module.
 *
 * **Success and fault are told apart by SIGN**, and the sign is what carries the tone: `0` is
 * success, every protocol fault is negative, and there is no second column. The protocol's name
 * for a code is added beside the integer at the presentation edge only — a code Payme adds
 * tomorrow still renders as itself, because a mapping that blanked an unknown value would hide
 * exactly the row an incident is about.
 *
 * **`peerIp` is Payme's data centre and never a customer's address.** This table holds no
 * Telegram id, no request body and no header, and that absence is the design: it is what keeps
 * the journal off the retention and privacy inventories. The column is captioned so nobody
 * mistakes it for something that needs masking.
 *
 * **Both identifiers are nullable and their absence is informative.** A failed-auth call
 * carries neither, an unknown-account call carries `publicRef` only, a perform carries both. An
 * em dash says "this call did not name one", which is a fact, not a missing value.
 */

import type { InboundCall } from "@/api/billing";
import { Badge } from "@/components/Badge";
import { type Column } from "@/components/DataTable";
import type { TranslationPath } from "@/i18n/types";

import { Instant, formatMs } from "./instants";
import { isFaultReply, replyCodeName } from "./railStatus";

type Translate = (path: TranslationPath, params?: Record<string, string | number>) => string;

const EM_DASH = "—";

export function buildCallColumns(t: Translate): readonly Column<InboundCall>[] {
  return [
    {
      key: "at",
      header: t("billing.calls.columns.at"),
      width: "16%",
      render: (row) => <Instant at={row.at} />,
    },
    {
      key: "method",
      header: t("billing.calls.columns.method"),
      width: "18%",
      render: (row) => <span className="font-mono">{row.method}</span>,
    },
    {
      key: "replyCode",
      header: t("billing.calls.columns.replyCode"),
      width: "20%",
      render: (row) => {
        const name = replyCodeName(row.replyCode);
        return (
          <Badge tone={isFaultReply(row.replyCode) ? "danger" : "accent"}>
            <span className="tabular-nums">
              {row.replyCode}
              {name === null ? "" : ` ${name}`}
            </span>
          </Badge>
        );
      },
    },
    {
      key: "publicRef",
      header: t("billing.calls.columns.reference"),
      width: "16%",
      render: (row) => (
        <span className="font-mono text-[12px] leading-4">{row.publicRef ?? EM_DASH}</span>
      ),
    },
    {
      key: "paymeTransactionId",
      header: t("billing.calls.columns.transactionId"),
      width: "16%",
      render: (row) => (
        <span className="font-mono text-[12px] leading-4">
          {row.paymeTransactionId ?? EM_DASH}
        </span>
      ),
    },
    {
      key: "durationMs",
      header: t("billing.calls.columns.duration"),
      width: "8%",
      align: "right",
      render: (row) => <span className="tabular-nums">{formatMs(row.durationMs)}</span>,
    },
    {
      key: "peerIp",
      header: t("billing.calls.columns.peerIp"),
      width: "10%",
      render: (row) => (
        <span className="font-mono text-[12px] leading-4 text-ink-400">
          {row.peerIp ?? EM_DASH}
        </span>
      ),
    },
  ];
}
