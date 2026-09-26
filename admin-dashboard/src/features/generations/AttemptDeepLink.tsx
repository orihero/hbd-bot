/**
 * `/generations/:attemptId` — the same place as `/generations?attempt=<uuid>`, canonicalised.
 *
 * The attempt is a PANEL beside the list, not a screen of its own: an operator reading the
 * render ledger wants the row's neighbours in view while they read it, and the panel's Close
 * has to leave the filtered list standing rather than pop back to an unfiltered one. So the
 * open attempt lives in the query string with the filters and the cursor, and one `apply`
 * writes all of it at once.
 *
 * That leaves the path form worth having but not worth rendering twice. A pasted
 * `/generations/<uuid>` — from a ticket, a chat, another console — lands here and is
 * REPLACED, not pushed, by the query-string spelling: replaced because two URLs for one view
 * in the history stack turn one Back press into two, and the operator did not visit two
 * places. Any search string already on the link survives, so a filtered deep link stays
 * filtered.
 *
 * An empty `:attemptId` cannot reach this component (the router would not match), and a
 * malformed one is left to `/api/generations/{id}` to refuse — the panel already renders that
 * refusal as "No attempt has that id", which is a better answer than a blank redirect.
 */

import type { JSX } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";

import { PATH } from "@/app/paths";

import { ATTEMPT_PARAM } from "./GenerationsScreen";

export function AttemptDeepLink(): JSX.Element {
  const params = useParams<{ attemptId: string }>();
  const location = useLocation();

  const search = new URLSearchParams(location.search);
  const attemptId = params.attemptId ?? "";
  if (attemptId === "") search.delete(ATTEMPT_PARAM);
  else search.set(ATTEMPT_PARAM, attemptId);

  return <Navigate to={{ pathname: PATH.generations, search: search.toString() }} replace />;
}
