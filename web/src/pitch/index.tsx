import { Link } from "react-router";

export default function PitchScreen() {
  return (
    <div className="grid min-h-svh place-items-center bg-navy-950 px-6 text-cloud-50">
      <div className="text-center">
        <p className="micro text-cloud-500">Pitch</p>
        <h1 className="display mt-3 text-[48px]">Slides land with J11.</h1>
        <Link to="/" className="mt-6 inline-block text-[14px] text-cloud-300 underline-offset-4 hover:underline">Back to the app</Link>
      </div>
    </div>
  );
}
