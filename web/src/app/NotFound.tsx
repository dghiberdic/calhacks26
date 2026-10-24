import { Link } from "react-router";

/** One row of the departure board, flipped to DIVERTED. */
export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-[640px] flex-col items-center py-24 text-center">
      <div className="rounded-lg bg-navy-900 px-5 py-4 font-mono text-[22px] tracking-[0.08em] text-cloud-50">
        <span className="text-cloud-500">--:-- </span>404 <span className="text-held">DIVERTED</span>
      </div>
      <h1 className="display-tight mt-8 text-[30px] text-navy-900">This page isn&rsquo;t on the board.</h1>
      <p className="mt-2 text-[15px] text-slate-500">The link may be old, or the page has moved.</p>
      <Link to="/" className="mt-7 rounded-lg bg-navy-900 px-4 py-2 text-[14px] font-semibold text-cloud-50">
        Back to Storm Run
      </Link>
    </div>
  );
}
