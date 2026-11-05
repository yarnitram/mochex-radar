import { test } from "node:test";
import assert from "node:assert/strict";
import {
  outboxSchema,
  catalogSchema,
  profilePollsSchema,
} from "../lib/contracts.ts";
import { catalog, polls } from "./discovery-fixture.mjs";

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

test("catalog accepts observation evidence but rejects accidental safety approval", () => {
  assert.equal(catalogSchema.parse(catalog).mints.length, 2);
  for (const mutation of [
    { approved_pump_watch: true },
    { security_status: "PASS" },
    { category: "ai" },
  ]) {
    assert.equal(
      catalogSchema.safeParse({ ...catalog, ...mutation }).success,
      false,
    );
  }
  assert.equal(
    catalogSchema.safeParse({
      ...catalog,
      mints: [{ ...catalog.mints[0], first_known_at: "not-a-time" }],
    }).success,
    false,
  );
});

test("poll schema distinguishes failed unknown counts from successful zero counts", () => {
  assert.equal(profilePollsSchema.parse(polls).polls[0].discovered_count, 0);
  assert.equal(profilePollsSchema.parse(polls).polls[1].discovered_count, null);
  for (const row of [
    { ...polls.polls[1], input_count: 0 },
    { ...polls.polls[0], discovered_count: null },
    { ...polls.polls[0], discovered_count: 1 },
  ]) {
    assert.equal(
      profilePollsSchema.safeParse({ ...polls, polls: [row] }).success,
      false,
    );
  }
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
