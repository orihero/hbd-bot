/**
 * `useCopy` — the one clipboard call in `components/data/`.
 *
 * §11.4 lists `CopyButton` under **Utility**, which is a different agent's directory. This
 * hook is deliberately NOT that component: it is the two lines of state that `JsonViewer`'s
 * copy-path affordance and `CodeBlock`'s copy button need, kept local so this directory does
 * not import a component it does not own. When `CopyButton` lands it can consume this hook
 * or ignore it; nothing here is on its path.
 *
 * `navigator.clipboard` is absent in jsdom and on insecure origins, and `writeText` rejects
 * when the document is not focused. All three are ordinary, so the failure path is "nothing
 * happened", never a thrown error and never an unhandled rejection — the same never-throw
 * discipline `src/api/client.ts` applies to the network.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** How long the "copied" acknowledgement stays on screen. */
export const COPY_FEEDBACK_MS = 1_200;

export interface CopyState {
  /** Copy `text`. Never throws and never returns a promise to forget to await. */
  readonly copy: (text: string) => void;
  /** True for `COPY_FEEDBACK_MS` after a successful copy. */
  readonly isCopied: boolean;
  /** True when the last attempt failed — no clipboard, or a denied permission. */
  readonly isFailed: boolean;
}

export function useCopy(feedbackMs: number = COPY_FEEDBACK_MS): CopyState {
  const [isCopied, setIsCopied] = useState(false);
  const [isFailed, setIsFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  const settle = useCallback(
    (didCopy: boolean) => {
      if (!isMounted.current) return;
      setIsCopied(didCopy);
      setIsFailed(!didCopy);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        if (!isMounted.current) return;
        setIsCopied(false);
        setIsFailed(false);
      }, feedbackMs);
    },
    [feedbackMs],
  );

  const copy = useCallback(
    (text: string) => {
      // Absent on an insecure origin and in jsdom; the type says otherwise.
      const clipboard = (navigator as Partial<Navigator>).clipboard;
      if (clipboard === undefined) {
        settle(false);
        return;
      }
      void clipboard.writeText(text).then(
        () => {
          settle(true);
        },
        () => {
          settle(false);
        },
      );
    },
    [settle],
  );

  return { copy, isCopied, isFailed };
}
