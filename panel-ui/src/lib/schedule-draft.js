// One-time handoff between Command Center and Scheduler in the existing SPA.
// Does not persist private team notes in browser storage or publish to Discord.
let pendingDraft = null;

export function prepareScheduleDraft(item) {
  if (!item || !["task", "idea"].includes(item.type) || typeof item.title !== "string" || !item.title.trim()) {
    return false;
  }
  pendingDraft = {
    id: typeof item.id === "string" ? item.id : "",
    type: item.type,
    title: item.title.trim().slice(0, 256),
    note: typeof item.note === "string" ? item.note.trim().slice(0, 4000) : "",
  };
  return true;
}

export function takeScheduleDraft() {
  const draft = pendingDraft;
  pendingDraft = null;
  return draft;
}
