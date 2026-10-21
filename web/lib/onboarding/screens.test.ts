// Pure pieces behind the screens: validation, unit switching, the day strip, event names and the
// pace preview's debounce.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type Answers, initialAnswers } from "./answers";
import { latestOnly } from "./latest";
import { eventName, mapAnswers } from "./mapAnswers";
import { nextDayType } from "./options";
import { PERSONAS } from "./personas";
import { switchUnits } from "./units";
import { aboutComplete, goalDetailsComplete, healthComplete } from "./validation";

const ASOF = "2026-10-16";
const maya = PERSONAS.maya.answers;

describe("validation", () => {
  it("about you needs sex, a past birth date, weight and height; body fat is optional", () => {
    expect(aboutComplete(maya, ASOF)).toBe(true);
    expect(aboutComplete({ ...maya, sex: null }, ASOF)).toBe(false);
    expect(aboutComplete({ ...maya, birthDate: "2030-01-01" }, ASOF)).toBe(false);
    expect(aboutComplete({ ...maya, birthDate: "not a date" }, ASOF)).toBe(false);
    expect(aboutComplete({ ...maya, weight: 0 }, ASOF)).toBe(false);
    expect(aboutComplete({ ...maya, bodyFatPct: 22 }, ASOF)).toBe(true);
    expect(aboutComplete({ ...maya, bodyFatPct: 95 }, ASOF)).toBe(false);
    const imperial: Answers = {
      ...maya,
      units: "imperial",
      heightCm: null,
      heightFt: 5,
      heightIn: 12,
    };
    expect(aboutComplete(imperial, ASOF)).toBe(false);
    expect(aboutComplete({ ...imperial, heightIn: 6 }, ASOF)).toBe(true);
  });

  it("event goals need a future date and a type; running needs a distance", () => {
    const race = (detail: object): Answers => ({
      ...initialAnswers,
      goals: ["event"],
      goalDetails: { endurance_event: detail },
    });
    expect(goalDetailsComplete(race({ eventType: "cycling", eventDate: "2027-01-01" }), ASOF)).toBe(
      true,
    );
    expect(goalDetailsComplete(race({ eventType: "running", eventDate: "2027-01-01" }), ASOF)).toBe(
      false,
    );
    expect(goalDetailsComplete(race({ eventType: "cycling", eventDate: "2026-01-01" }), ASOF)).toBe(
      false,
    );
    const date: Answers = {
      ...initialAnswers,
      goals: ["date"],
      goalDetails: { deadline_event: { eventDate: "2027-01-01" } },
    };
    expect(goalDetailsComplete(date, ASOF)).toBe(false);
  });

  it("health needs every SCOFF item answered, or prefer not to say", () => {
    expect(healthComplete(initialAnswers)).toBe(false);
    expect(
      healthComplete({
        ...initialAnswers,
        health: { ...initialAnswers.health, scoffDeclined: true },
      }),
    ).toBe(true);
    expect(healthComplete(maya)).toBe(true);
    expect(healthComplete({ ...maya, health: { ...maya.health, ckdStage: 6 } })).toBe(false);
  });

  it("prefer not to say sends no SCOFF score", () => {
    const declined = {
      ...maya,
      health: { ...maya.health, scoffDeclined: true },
    };
    expect(mapAnswers(declined, { asOf: ASOF }).profile.flags?.scoff_score).toBeNull();
  });
});

describe("switching units", () => {
  it("converts weight, height and target weights both ways", () => {
    const metric: Answers = {
      ...maya,
      goalDetails: { lose_fat: { targetWeight: 64 } },
    };
    const imperial = { ...metric, ...switchUnits(metric, "imperial") };
    expect(imperial).toMatchObject({
      units: "imperial",
      weight: 154.3,
      heightFt: 5,
      heightIn: 6,
    });
    expect(imperial.goalDetails.lose_fat?.targetWeight).toBe(141.1);
    const back = { ...imperial, ...switchUnits(imperial, "metric") };
    expect(back).toMatchObject({ units: "metric", weight: 70, heightCm: 168 });
    expect(back.goalDetails.lose_fat?.targetWeight).toBe(64);
  });

  it("does nothing when the units don't change", () => {
    expect(switchUnits(maya, "metric")).toEqual({});
  });
});

describe("training strip", () => {
  it("cycles rest -> easy -> quality -> long -> rest", () => {
    expect(["rest", "easy", "quality", "long"].map((d) => nextDayType(d as never))).toEqual([
      "easy",
      "quality",
      "long",
      "rest",
    ]);
  });
});

describe("event names", () => {
  it("uses the distance for a running race, else the type or occasion", () => {
    expect(
      eventName("endurance_event", {
        eventType: "running",
        distance: "marathon",
      }),
    ).toBe("marathon");
    expect(eventName("endurance_event", { eventType: "cycling", distance: null })).toBe("cycling");
    expect(eventName("deadline_event", { event: "wedding" })).toBe("wedding");
    expect(eventName("lose_fat", { event: "wedding" })).toBeNull();
  });
});

describe("pace preview debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("only calls once the slider rests for 300 ms, with the latest value", async () => {
    const fn = vi.fn(async (n: number) => n * 10);
    const onResult = vi.fn();
    const latest = latestOnly(fn, 300, { onResult });
    latest.call(1);
    await vi.advanceTimersByTimeAsync(200);
    latest.call(2);
    await vi.advanceTimersByTimeAsync(200);
    latest.call(3);
    await vi.advanceTimersByTimeAsync(300);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0]).toBe(3);
    expect(onResult).toHaveBeenCalledWith(30);
  });

  it("drops a slow response once a newer call has been made", async () => {
    const resolvers: ((v: number) => void)[] = [];
    const fn = vi.fn(
      (_: number, signal: AbortSignal) =>
        new Promise<number>((resolve, reject) => {
          resolvers.push(resolve);
          signal.addEventListener("abort", () => reject(new Error("aborted")));
        }),
    );
    const onResult = vi.fn();
    const onError = vi.fn();
    const latest = latestOnly(fn, 300, { onResult, onError });
    latest.call(1);
    await vi.advanceTimersByTimeAsync(300);
    latest.call(2);
    resolvers[0](10); // the first request comes back late
    await vi.advanceTimersByTimeAsync(300);
    resolvers[1](20);
    await vi.advanceTimersByTimeAsync(0);
    expect(onResult.mock.calls).toEqual([[20]]);
    expect(onError).not.toHaveBeenCalled();
  });
});
