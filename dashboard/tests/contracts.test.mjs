import { test } from "node:test";
import assert from "node:assert/strict";
import { outboxSchema } from "../lib/contracts.ts";

test("outbox contract fills omitted stored states with zero and strips unrelated data", () => {
  const data = outboxSchema.parse({
    status: "stored_outbox",
    states: { sent: 2 },
    body: "must not reach dashboard",
    chat_id: "private-example",
  });
  assert.equal(data.states.sent, 2);
  assert.equal(data.states.uncertain, 0);
  assert.equal("body" in data, false);
  assert.equal("chat_id" in data, false);
});

test("invalid counts or unknown states cannot masquerade as valid delivery health", () => {
  for (const states of [
    { sent: -1 },
    { pending: 1.5 },
    { new_state: 4 },
    { sent: "2" },
  ]) {
    assert.equal(
      outboxSchema.safeParse({ status: "stored_outbox", states }).success,
      false,
    );
  }
});
