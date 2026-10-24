import { describe, expect, it } from "vitest";
import { clampSlide, clickTarget, keyToAction, parseSlide } from "./nav";

const key = (k: string, mods: Partial<Record<"shiftKey" | "metaKey" | "ctrlKey" | "altKey", boolean>> = {}) => ({ key: k, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false, ...mods });

describe("parseSlide", () => {
  it("reads the index from the URL segment", () => {
    expect(parseSlide("3", 6)).toBe(3);
    expect(parseSlide("3/extra", 6)).toBe(3);
  });
  it("falls back to the cover and clamps past the end", () => {
    expect(parseSlide(undefined, 6)).toBe(0);
    expect(parseSlide("", 6)).toBe(0);
    expect(parseSlide("abc", 6)).toBe(0);
    expect(parseSlide("-2", 6)).toBe(0);
    expect(parseSlide("99", 6)).toBe(5);
  });
});

describe("keyToAction", () => {
  it("moves forward on the keys presenters and clickers send", () => {
    for (const k of ["ArrowRight", "ArrowDown", "PageDown", " "]) expect(keyToAction(key(k), 2, 6)).toEqual({ type: "go", to: 3 });
  });
  it("moves back, including Shift+Space", () => {
    for (const k of ["ArrowLeft", "ArrowUp", "PageUp"]) expect(keyToAction(key(k), 2, 6)).toEqual({ type: "go", to: 1 });
    expect(keyToAction(key(" ", { shiftKey: true }), 2, 6)).toEqual({ type: "go", to: 1 });
  });
  it("jumps with Home, End and digits", () => {
    expect(keyToAction(key("Home"), 4, 6)).toEqual({ type: "go", to: 0 });
    expect(keyToAction(key("End"), 1, 6)).toEqual({ type: "go", to: 5 });
    expect(keyToAction(key("4"), 0, 6)).toEqual({ type: "go", to: 4 });
    expect(keyToAction(key("0"), 3, 6)).toEqual({ type: "go", to: 0 });
    expect(keyToAction(key("9"), 0, 6)).toBeNull();
  });
  it("leaves the deck on Escape and toggles full screen on F", () => {
    expect(keyToAction(key("Escape"), 2, 6)).toEqual({ type: "exit" });
    expect(keyToAction(key("f"), 2, 6)).toEqual({ type: "fullscreen" });
  });
  it("lets browser shortcuts through", () => {
    expect(keyToAction(key("ArrowRight", { metaKey: true }), 2, 6)).toBeNull();
    expect(keyToAction(key("r", { ctrlKey: true }), 2, 6)).toBeNull();
    expect(keyToAction(key("1", { altKey: true }), 2, 6)).toBeNull();
    expect(keyToAction(key("x"), 2, 6)).toBeNull();
  });
});

describe("clicks", () => {
  it("right half next, left half previous", () => {
    expect(clickTarget(900, 1000, 2)).toBe(3);
    expect(clickTarget(100, 1000, 2)).toBe(1);
  });
  it("clamps to the deck", () => {
    expect(clampSlide(-1, 6)).toBe(0);
    expect(clampSlide(6, 6)).toBe(5);
  });
});
