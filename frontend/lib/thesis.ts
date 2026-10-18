// A thesis statement is a proposition and the Facts that back it: "Indium phosphide substrate
// supply may be a chokepoint: in January 2026 AXT expected ...". The reader leads with the
// proposition. Drafting should emit it apart (`content.thesis_proposition`, backend ticket B4);
// until then the colon rule is the fallback. There is no thesis parser beyond it, and the text
// is never cut at its first sentence (that splits a proposition as badly as a colon can).

/** How far into the statement a colon may fall and still end a proposition. */
export const PROPOSITION_MAX = 160;

/** The index of the colon that ends the proposition: a colon followed by a space, within the
 * limit ("10:30" has none). -1 when the statement has none. */
function colonAt(statement: string): number {
  const match = /:\s/.exec(statement);
  return match !== null && match.index > 0 && match.index <= PROPOSITION_MAX ? match.index : -1;
}

/** The proposition: the drafted one when the version has it, else the text before the first
 * colon when that falls within 160 characters, else the whole statement (the layout clamps it). */
export function proposition(statement: string, drafted?: string | null): string {
  const explicit = drafted?.trim();
  if (explicit) return explicit;
  const at = colonAt(statement);
  return at < 0 ? statement.trim() : statement.slice(0, at).trim();
}

/** What follows the proposition, or an empty string when the statement is only a proposition
 * (or the drafted proposition is the whole of it). */
export function rest(statement: string, drafted?: string | null): string {
  const explicit = drafted?.trim();
  if (explicit) {
    const stated = statement.trim();
    if (stated === explicit) return "";
    return capitalised(
      stated.startsWith(explicit) ? stated.slice(explicit.length).replace(/^[\s:.,;-]+/, "") : stated,
    );
  }
  const at = colonAt(statement);
  return at < 0 ? "" : capitalised(statement.slice(at + 1).trim());
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** `content.thesis_proposition` when the backend drafted one (it is not in the schema yet). */
export function draftedProposition(content: object): string | null {
  const value = (content as { thesis_proposition?: unknown }).thesis_proposition;
  return typeof value === "string" && value.trim() !== "" ? value : null;
}
