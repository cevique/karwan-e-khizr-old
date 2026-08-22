import { JourneyRead } from "../types";
import { MOCK_STOPS } from "./stops";
import { MOCK_AGENCIES, MOCK_ROUTES } from "./routes";

export const MOCK_JOURNEYS: JourneyRead[] = [
  {
    objective: "fastest",
    total_duration_s: 17 * 60, // 17 min
    total_walk_m: 1300,        // 1.3 km
    transfer_count: 0,
    fare_amount_pkr: 0,
    headway_info: "Every 6-8 min",
    is_recommended: true,
    legs: [
      {
        type: "walk",
        from_stop: null,
        to_stop: MOCK_STOPS[10], // Ammar Chowk
        from_location: { latitude: 33.5850, longitude: 73.0760 },
        to_location: { latitude: 33.5850, longitude: 73.0760 },
        distance_m: 210,
        duration_s: 3 * 60,
      },
      {
        type: "ride",
        route: MOCK_ROUTES[0], // Green Line RL-02
        agency: MOCK_AGENCIES[0],
        board_stop: MOCK_STOPS[10], // Ammar Chowk
        alight_stop: MOCK_STOPS[9],  // Saddar
        intermediate_stops: [
          MOCK_STOPS[8],
          MOCK_STOPS[7],
          MOCK_STOPS[6],
          MOCK_STOPS[5],
        ],
        duration_s: 12 * 60,
        route_geometry: {
          type: "LineString",
          coordinates: [
            [73.0760, 33.5850],
            [73.0733, 33.6339],
            [73.0789, 33.6497],
            [73.0825, 33.6631],
            [73.0336, 33.6669],
            [73.0547, 33.5975],
          ],
          geometry_source: "mock",
          geometry_confidence: "HIGH",
        },
      },
      {
        type: "walk",
        from_stop: MOCK_STOPS[9], // Saddar
        to_stop: null,
        from_location: { latitude: 33.5975, longitude: 73.0547 },
        to_location: { latitude: 33.5975, longitude: 73.0547 },
        distance_m: 180,
        duration_s: 2 * 60,
      },
    ],
  },
  {
    objective: "fewest_transfers",
    total_duration_s: 21 * 60, // 21 min
    total_walk_m: 2100,        // 2.1 km
    transfer_count: 0,
    fare_amount_pkr: 0,
    headway_info: "Every 10 min",
    is_recommended: false,
    legs: [
      {
        type: "walk",
        from_stop: null,
        to_stop: MOCK_STOPS[10],
        from_location: { latitude: 33.5850, longitude: 73.0760 },
        to_location: { latitude: 33.5850, longitude: 73.0760 },
        distance_m: 350,
        duration_s: 5 * 60,
      },
      {
        type: "ride",
        route: MOCK_ROUTES[1], // BRT Orange Line
        agency: MOCK_AGENCIES[1],
        board_stop: MOCK_STOPS[10],
        alight_stop: MOCK_STOPS[9],
        intermediate_stops: [MOCK_STOPS[6]],
        duration_s: 12 * 60,
        route_geometry: {
          type: "LineString",
          coordinates: [
            [73.0760, 33.5850],
            [73.0547, 33.5975],
          ],
          geometry_source: "mock",
          geometry_confidence: "HIGH",
        },
      },
      {
        type: "walk",
        from_stop: MOCK_STOPS[9],
        to_stop: null,
        from_location: { latitude: 33.5975, longitude: 73.0547 },
        to_location: { latitude: 33.5975, longitude: 73.0547 },
        distance_m: 280,
        duration_s: 4 * 60,
      },
    ],
  },
  {
    objective: "least_walking",
    total_duration_s: 23 * 60, // 23 min
    total_walk_m: 1700,        // 1.7 km
    transfer_count: 0,
    fare_amount_pkr: 0,
    headway_info: "Every 8-10 min",
    is_recommended: false,
    legs: [
      {
        type: "walk",
        from_stop: null,
        to_stop: MOCK_STOPS[10],
        from_location: { latitude: 33.5850, longitude: 73.0760 },
        to_location: { latitude: 33.5850, longitude: 73.0760 },
        distance_m: 260,
        duration_s: 4 * 60,
      },
      {
        type: "ride",
        route: MOCK_ROUTES[3], // Green Line RL-05
        agency: MOCK_AGENCIES[1],
        board_stop: MOCK_STOPS[10],
        alight_stop: MOCK_STOPS[9],
        intermediate_stops: [MOCK_STOPS[2], MOCK_STOPS[3]],
        duration_s: 16 * 60,
        route_geometry: {
          type: "LineString",
          coordinates: [
            [73.0760, 33.5850],
            [73.0544, 33.6938],
            [73.0547, 33.5975],
          ],
          geometry_source: "mock",
          geometry_confidence: "HIGH",
        },
      },
      {
        type: "walk",
        from_stop: MOCK_STOPS[9],
        to_stop: null,
        from_location: { latitude: 33.5975, longitude: 73.0547 },
        to_location: { latitude: 33.5975, longitude: 73.0547 },
        distance_m: 190,
        duration_s: 3 * 60,
      },
    ],
  },
];
