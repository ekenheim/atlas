"use client";

// Where the operations live: everything that is not Today, Themes, Record or Decide. Each row
// carries one state line, read on its own; a row whose read fails shows its name alone.
import Link from "next/link";

import { api } from "../../lib/api/client";
import {
  SYSTEM_ITEMS,
  countState,
  inQueueState,
  memoryState,
  openState,
  runsState,
  runsThisWeek,
} from "../../lib/system";
import { useApi } from "../../lib/use-api";

const STATES: Record<string, () => Promise<string>> = {
  memory: async () => memoryState(await api.memoryHealth(), Date.now()),
  sessions: async () => runsState(runsThisWeek((await api.sessions()).items, new Date())),
  issues: async () =>
    openState((await api.issues()).items.filter((issue) => issue.status === "active").length),
  relationships: async () => countState((await api.relationships({})).total),
  exceptions: async () => inQueueState(await api.exceptionsTotal()),
  workbench: async () => `${countState((await api.investigations()).total)} runs`,
  beliefs: async () => `${countState((await api.beliefs({ status: "active" })).total)} active`,
  hypotheses: async () => countState((await api.hypotheses()).total),
  companies: async () => countState((await api.companies()).total),
};

const noState = async () => "";

function StateLine({ itemKey }: { itemKey: string }) {
  const load = STATES[itemKey] ?? noState;
  const state = useApi(itemKey, load);
  // A failed or pending read shows the name alone.
  return (
    <div className="reader-row-sub row-secondary" aria-live="off">
      {state.state === "ready" ? state.data : ""}
    </div>
  );
}

export default function SystemPage() {
  return (
    <>
      <h1>System</h1>
      <ul className="reader-rows system-rows" aria-label="System">
        {SYSTEM_ITEMS.map((item) => (
          <li className="reader-row" key={item.key}>
            <div>
              <div className="row-title">
                <Link href={item.href}>{item.label}</Link>
              </div>
              <StateLine itemKey={item.key} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
