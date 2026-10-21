import assert from "node:assert/strict";
import test from "node:test";
import { prepareScheduleDraft, takeScheduleDraft } from "../src/lib/schedule-draft.js";

test("passes one private workboard draft to scheduler exactly once", () => {
  assert.equal(prepareScheduleDraft({
    id: "abc", type: "idea", title: "   Arma highlights   ", note: "Дайджест",
  }), true);
  assert.deepEqual(takeScheduleDraft(), { id: "abc", type: "idea", title: "Arma highlights", note: "Дайджест" });
  assert.equal(takeScheduleDraft(), null);
});

test("rejects invalid entries and caps fields for embeds", () => {
  assert.equal(prepareScheduleDraft({ type: "other", title: "Anything" }), false);
  assert.equal(prepareScheduleDraft({ type: "task", title: "   " }), false);
  assert.equal(takeScheduleDraft(), null);
  assert.equal(prepareScheduleDraft({ type: "task", title: "T".repeat(300), note: "X".repeat(5000) }), true);
  const result = takeScheduleDraft();
  assert.equal(result.title.length, 256);
  assert.equal(result.note.length, 4000);
});
