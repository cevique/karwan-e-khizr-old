import { AgencyRead, RouteListItem, RouteDetail } from "../types";
import { MOCK_STOPS } from "./stops";

export const MOCK_AGENCIES: AgencyRead[] = [
  {
    id: "agency-pmta-001",
    name: "Punjab Mass Transit Authority (PMTA)",
    network_type: "BRT Metrobus",
  },
  {
    id: "agency-cda-002",
    name: "Capital Development Authority (CDA)",
    network_type: "Feeder & Metrobus",
  },
];

export const MOCK_ROUTES: RouteListItem[] = [
  {
    id: "route-red-line-01",
    agency_id: "agency-pmta-001",
    short_name: "RL-02",
    long_name: "Green Line / Red Metrobus (Pak Secretariat - Saddar)",
    color: "#DC2626",
  },
  {
    id: "route-orange-line-02",
    agency_id: "agency-cda-002",
    short_name: "BRT Orange",
    long_name: "Orange Line (Faiz Ahmed Faiz - Airport)",
    color: "#F59E0B",
  },
  {
    id: "route-blue-line-03",
    agency_id: "agency-cda-002",
    short_name: "Blue Line",
    long_name: "Blue Line (PIMS - Gulberg Green)",
    color: "#2563EB",
  },
  {
    id: "route-green-line-04",
    agency_id: "agency-cda-002",
    short_name: "RL-05",
    long_name: "Green Line (PIMS - Bhara Kahu)",
    color: "#0A6E64",
  },
  {
    id: "route-feeder-fr01",
    agency_id: "agency-cda-002",
    short_name: "FR-01",
    long_name: "Feeder Route 1 (NUST H-12 to PIMS)",
    color: "#7C3AED",
  },
];

export const MOCK_ROUTE_DETAILS: Record<string, RouteDetail> = {
  "route-red-line-01": {
    id: "route-red-line-01",
    agency_id: "agency-pmta-001",
    short_name: "RL-02",
    long_name: "Green Line / Red Metrobus (Pak Secretariat - Saddar)",
    color: "#DC2626",
    agency: MOCK_AGENCIES[0],
    stops: [
      { sequence: 1, distance_along_route_m: 0, stop: MOCK_STOPS[0] },
      { sequence: 2, distance_along_route_m: 1400, stop: MOCK_STOPS[1] },
      { sequence: 3, distance_along_route_m: 4200, stop: MOCK_STOPS[2] },
      { sequence: 4, distance_along_route_m: 5400, stop: MOCK_STOPS[3] },
      { sequence: 5, distance_along_route_m: 6800, stop: MOCK_STOPS[5] },
      { sequence: 6, distance_along_route_m: 11200, stop: MOCK_STOPS[6] },
      { sequence: 7, distance_along_route_m: 13500, stop: MOCK_STOPS[7] },
      { sequence: 8, distance_along_route_m: 16000, stop: MOCK_STOPS[8] },
      { sequence: 9, distance_along_route_m: 22500, stop: MOCK_STOPS[9] },
    ],
    geometry: {
      type: "LineString",
      coordinates: [
        [73.0931, 33.7297],
        [73.0768, 33.7194],
        [73.0544, 33.6938],
        [73.0479, 33.6844],
        [73.0336, 33.6669],
        [73.0825, 33.6631],
        [73.0789, 33.6497],
        [73.0733, 33.6339],
        [73.0547, 33.5975],
      ],
      geometry_source: "manual_verified",
      geometry_confidence: "HIGH",
    },
  },
};
