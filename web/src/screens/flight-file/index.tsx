import { useParams } from "react-router";
import FlightFileView from "./FlightFileView";
import FlightIndex from "./FlightIndex";
import { decodeId } from "./lib";

/** `/flights` lists the storm's flights by verdict; `/flights/:flightId` is one flight's file. */
export default function FlightFileScreen() {
  const { flightId } = useParams();
  return flightId ? <FlightFileView key={flightId} flightId={decodeId(flightId)} /> : <FlightIndex />;
}
