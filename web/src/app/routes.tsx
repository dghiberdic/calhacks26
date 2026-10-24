import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router";
import { Loading } from "@/components/kit";
import { AppShell } from "./AppShell";
import NotFound from "./NotFound";

const StormRun = lazy(() => import("@/screens/storm-run"));
const FlightFile = lazy(() => import("@/screens/flight-file"));
const Questions = lazy(() => import("@/screens/questions"));
const Policies = lazy(() => import("@/screens/policies"));
const Trace = lazy(() => import("@/screens/trace"));
const Close = lazy(() => import("@/screens/close"));
const Desk = lazy(() => import("@/screens/desk"));
const Proof = lazy(() => import("@/screens/proof"));
const Pitch = lazy(() => import("@/pitch"));
const Story = lazy(() => import("@/story"));

const screen = (node: ReactNode) => <Suspense fallback={<Loading />}>{node}</Suspense>;

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: screen(<StormRun />) },
      { path: "run/:stormId", element: screen(<StormRun />) },
      { path: "flights", element: screen(<FlightFile />) },
      { path: "flights/:flightId", element: screen(<FlightFile />) },
      { path: "questions", element: screen(<Questions />) },
      { path: "policies", element: screen(<Policies />) },
      { path: "trace", element: screen(<Trace />) },
      { path: "close", element: screen(<Close />) },
      { path: "desk", element: screen(<Desk />) },
      { path: "proof", element: screen(<Proof />) },
      { path: "*", element: <NotFound /> },
    ],
  },
  { path: "pitch/*", element: <Suspense fallback={null}>{<Pitch />}</Suspense> },
  // The immersive scroll story (outside the app shell), for the Devpost link and the video.
  { path: "story", element: <Suspense fallback={null}>{<Story />}</Suspense> },
]);
