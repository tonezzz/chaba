import test from "node:test";
import assert from "node:assert/strict";
import { limitFromEnv, truncateMessages, capMediaMessages } from "./refresh-limits.mjs";

test("limitFromEnv falls back on missing/invalid values and clamps to range", () => {
  const name = "YOMI_TEST_LIMIT";
  delete process.env[name];
  assert.equal(limitFromEnv(name, 5), 5);

  process.env[name] = "not-a-number";
  assert.equal(limitFromEnv(name, 5), 5);

  process.env[name] = "12";
  assert.equal(limitFromEnv(name, 5), 12);

  process.env[name] = "0";
  assert.equal(limitFromEnv(name, 5, { min: 1 }), 1);

  process.env[name] = "999";
  assert.equal(limitFromEnv(name, 5, { max: 10 }), 10);
});

test("truncateMessages keeps only the newest bounded slice", () => {
  const messages = Array.from({ length: 8 }, (_, i) => ({ id: `m${i}` }));
  assert.deepEqual(
    truncateMessages(messages, 3).map((m) => m.id),
    ["m0", "m1", "m2"]
  );
  assert.deepEqual(truncateMessages(null, 3), []);
});

test("capMediaMessages selects media types and caps fan-out", () => {
  const messages = [
    { id: "1", mediaType: "text" },
    { id: "2", mediaType: "image" },
    { id: "3", mediaType: "AUDIO" },
    { id: "4", mediaType: "video" },
    { id: "5", mediaType: "file" },
  ];
  assert.deepEqual(
    capMediaMessages(messages, 3).map((m) => m.id),
    ["2", "3", "4"]
  );
  assert.deepEqual(capMediaMessages(messages, 0), []);
});
