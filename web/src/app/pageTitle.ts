/**
 * The browser tab and search title for an app route: what the page is, then the product. Screens with a
 * subject say it first ("NS31 · Flight File · StormCheck"); /pitch and /story set their own.
 */
const SECTIONS: [RegExp, string][] = [
  [/^\/(run\/.*)?$/, "Storm Run"],
  [/^\/flights\/?$/, "Flight File"],
  [/^\/questions/, "Questions"],
  [/^\/policies/, "Policies"],
  [/^\/trace/, "Trace"],
  [/^\/close/, "Liability & Close"],
  [/^\/desk/, "Judge's Desk"],
  [/^\/proof/, "Proof"],
];

export function pageTitle(pathname: string): string {
  const flight = pathname.match(/^\/flights\/([^/]+)/)?.[1];
  if (flight) return `${decodeURIComponent(flight).split("@")[0]} · Flight File · StormCheck`;
  const section = SECTIONS.find(([re]) => re.test(pathname))?.[1];
  return section ? `${section} · StormCheck` : "Not on the board · StormCheck";
}
